"""Power requests follow room activity and never outlive the application."""
import asyncio
import ctypes
from types import SimpleNamespace
from unittest.mock import Mock
import threading
import subprocess

import pytest

from ktvibes import power
from ktvibes.queue import State


@pytest.mark.parametrize('current,upcoming,playing,expected', [
    (None, [], True, False),
    ({'key': 'current'}, [], True, True),
    ({'key': 'current'}, [], False, True),
    (None, [{'status': 'queued'}], False, True),
    (None, [{'status': 'processing'}], True, True),
    (None, [{'status': 'error'}], True, False),
    (None, [{'status': 'error'}, {'status': 'ready'}], True, True),
])
def test_room_activity(current, upcoming, playing, expected):
    state = State()
    state.current, state.upcoming, state.playing = current, upcoming, playing
    assert power.has_work(state) is expected


def test_native_requests_share_one_thread_and_do_not_repeat():
    calls = []
    checked = threading.Event()
    def factory():
        calls.append(('create', threading.get_ident()))
        return SimpleNamespace(
            acquire=lambda: calls.append(('acquire', threading.get_ident())),
            release=lambda: calls.append(('release', threading.get_ident())),
            check=checked.set)
    inhibitor = power.SleepInhibitor(factory)
    inhibitor.thread.start()
    for active in (False, True, True):
        inhibitor.commands.put(active)
    assert checked.wait(2)
    for active in (False, False, True, None):
        inhibitor.commands.put(active)
    inhibitor.thread.join(2)
    assert not inhibitor.thread.is_alive()
    assert [name for name, _ in calls] == ['create', 'acquire', 'release', 'acquire', 'release']
    assert len({thread for _, thread in calls}) == 1
    assert calls[0][1] != threading.get_ident()


def test_failed_request_logs_once_and_can_recover(caplog):
    driver = Mock()
    driver.acquire.side_effect = [OSError('driver unavailable'), None]
    inhibitor = power.SleepInhibitor(lambda: driver)
    inhibitor.thread.start()
    for active in (True, True, True, False, True, None):
        inhibitor.commands.put(active)
    inhibitor.thread.join(2)
    assert not inhibitor.thread.is_alive()
    assert driver.acquire.call_count == 2
    assert caplog.text.count('Could not maintain') == 1


async def test_monitor_starts_with_restored_queue_and_releases_on_cancel():
    state = State()
    state.upcoming = [{'status': 'queued'}]
    driver = Mock()
    acquired = threading.Event()
    driver.acquire.side_effect = acquired.set
    inhibitor = power.SleepInhibitor(lambda: driver)
    task = asyncio.create_task(inhibitor.run(state))
    assert await asyncio.to_thread(acquired.wait, 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not inhibitor.thread.is_alive()
    driver.release.assert_called_once()


def test_windows_only_requests_system_not_display(monkeypatch):
    api = Mock(return_value=1)
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *a, **k: SimpleNamespace(SetThreadExecutionState=api), raising=False)
    driver = power.WindowsSleep()
    driver.acquire()
    driver.release()
    assert [call.args for call in api.call_args_list] == [(0x80000001,), (0x80000000,)]


def test_mac_assertion_and_cf_objects_are_released(monkeypatch):
    cf = SimpleNamespace(CFStringCreateWithCString=Mock(side_effect=[10, 20]), CFRelease=Mock())
    def create(kind, level, reason, output):
        assert (kind, level, reason) == (10, 255, 20)
        ctypes.cast(output, ctypes.POINTER(ctypes.c_uint32))[0] = 123
        return 0
    api = SimpleNamespace(IOPMAssertionCreateWithName=Mock(side_effect=create), IOPMAssertionRelease=Mock(return_value=0))
    monkeypatch.setattr(ctypes, 'CDLL', lambda path: cf if 'CoreFoundation' in path else api)
    driver = power.MacSleep()
    driver.acquire()
    driver.release()
    driver.release()
    api.IOPMAssertionRelease.assert_called_once_with(123)
    assert [call.args for call in cf.CFRelease.call_args_list] == [(10,), (20,)]


def test_linux_inhibitor_uses_eof_and_reaps_helper(monkeypatch):
    child = Mock()
    child.wait.side_effect = [subprocess.TimeoutExpired('inhibit', .15), 0]
    popen = Mock(return_value=child)
    monkeypatch.setattr(power.subprocess, 'Popen', popen)
    driver = power.LinuxSleep()
    driver.acquire()
    args = popen.call_args.args[0]
    assert '--what=sleep' in args and '--no-ask-password' in args
    assert 'sys.stdin.buffer.read()' in args[-1]
    driver.release()
    child.stdin.close.assert_called_once()
    child.terminate.assert_not_called()
    assert driver.process is None


def test_linux_denied_inhibitor_is_reported(monkeypatch):
    child = Mock()
    child.wait.return_value = 1
    monkeypatch.setattr(power.subprocess, 'Popen', Mock(return_value=child))
    driver = power.LinuxSleep()
    with pytest.raises(OSError, match='status 1'):
        driver.acquire()
    driver.release()


async def test_application_owns_inhibitor_lifetime(tmp_path, monkeypatch):
    from ktvibes.application import create_app
    from ktvibes.runtime import Runtime
    from ktvibes import worker
    runtime = Runtime(cache=tmp_path)
    async def idle(*args):
        await asyncio.Event().wait()
    monkeypatch.setattr(worker, 'run', idle)
    monkeypatch.setattr(runtime.updates, 'run', idle)
    driver = Mock()
    acquired = threading.Event()
    driver.acquire.side_effect = acquired.set
    monkeypatch.setattr(power, 'backend', lambda: driver)
    app = create_app(runtime)
    async with app.router.lifespan_context(app):
        runtime.state.upcoming.append({'status': 'queued'})
        assert await asyncio.to_thread(acquired.wait, 3)
    driver.release.assert_called_once()


async def test_monitor_releases_when_only_failed_songs_remain():
    state = State()
    state.upcoming = [{'status': 'queued'}]
    acquired, released = threading.Event(), threading.Event()
    driver = Mock()
    driver.acquire.side_effect = acquired.set
    driver.release.side_effect = released.set
    inhibitor = power.SleepInhibitor(lambda: driver)
    task = asyncio.create_task(inhibitor.run(state))
    try:
        assert await asyncio.to_thread(acquired.wait, 2)
        state.upcoming[0]['status'] = 'error'
        assert await asyncio.to_thread(released.wait, 2)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    driver.acquire.assert_called_once()
