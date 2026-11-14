"""Hold an idle-sleep inhibitor while the room has songs to play."""
import asyncio
import ctypes
import logging
import queue
import subprocess
import sys
import threading

log = logging.getLogger(__name__)


def has_work(state):
    return state.current is not None or any(item.get('status') != 'error' for item in state.upcoming)


class MacSleep:
    def __init__(self):
        self.iokit = ctypes.CDLL('/System/Library/Frameworks/IOKit.framework/IOKit')
        self.cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        self.cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        self.cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        self.cf.CFRelease.argtypes = [ctypes.c_void_p]
        self.iokit.IOPMAssertionCreateWithName.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        self.iokit.IOPMAssertionCreateWithName.restype = ctypes.c_int
        self.iokit.IOPMAssertionRelease.argtypes = [ctypes.c_uint32]
        self.iokit.IOPMAssertionRelease.restype = ctypes.c_int
        self.assertion = None

    def acquire(self):
        kind = self.cf.CFStringCreateWithCString(None, b'PreventUserIdleSystemSleep', 0x08000100)
        reason = self.cf.CFStringCreateWithCString(None, b'KTVibes has songs to play', 0x08000100)
        try:
            assertion = ctypes.c_uint32()
            result = self.iokit.IOPMAssertionCreateWithName(kind, 255, reason, ctypes.byref(assertion))
            if result:
                raise OSError(f'IOPMAssertionCreateWithName failed: {result}')
            self.assertion = assertion.value
        finally:
            if kind:
                self.cf.CFRelease(kind)
            if reason:
                self.cf.CFRelease(reason)

    def release(self):
        if self.assertion is not None:
            result = self.iokit.IOPMAssertionRelease(self.assertion)
            if result:
                raise OSError(f'IOPMAssertionRelease failed: {result}')
            self.assertion = None


class WindowsSleep:
    def __init__(self):
        self.set_state = ctypes.WinDLL('kernel32', use_last_error=True).SetThreadExecutionState
        self.set_state.argtypes = [ctypes.c_uint32]
        self.set_state.restype = ctypes.c_uint32

    def _set(self, flags):
        if not self.set_state(flags):
            raise ctypes.WinError(ctypes.get_last_error())

    def acquire(self):
        self._set(0x80000001)  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED; display is independent.

    def release(self):
        self._set(0x80000000)


class LinuxSleep:
    def __init__(self):
        self.process = None

    def acquire(self):
        # EOF ends the helper even if the server crashes; do not orphan a sleep inhibitor.
        self.process = subprocess.Popen([
            'systemd-inhibit', '--what=sleep', '--mode=block', '--who=KTVibes',
            '--why=Songs are playing or queued', '--no-ask-password',
            sys.executable, '-c', 'import sys; sys.stdin.buffer.read()',
        ], stdin=subprocess.PIPE)
        try:
            code = self.process.wait(timeout=0.15)
        except subprocess.TimeoutExpired:
            return
        raise OSError(f'systemd-inhibit exited with status {code}')

    def check(self):
        if self.process is not None and self.process.poll() is not None:
            raise OSError(f'systemd-inhibit exited with status {self.process.returncode}')

    def release(self):
        if self.process is None:
            return
        process, self.process = self.process, None
        process.stdin.close()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def backend():
    if sys.platform == 'darwin':
        return MacSleep()
    if sys.platform == 'win32':
        return WindowsSleep()
    if sys.platform.startswith('linux'):
        return LinuxSleep()
    raise OSError(f'Sleep inhibition is unsupported on {sys.platform}')


class SleepInhibitor:
    """Serialize native calls on one long-lived thread (required by Windows)."""
    def __init__(self, factory=None):
        self.factory = factory or backend
        self.commands = queue.Queue()
        self.thread = threading.Thread(target=self._worker, name='ktvibes-power', daemon=True)

    def _worker(self):
        driver = None
        wanted = False
        failed = False
        try:
            while (active := self.commands.get()) is not None:
                try:
                    if active != wanted:
                        wanted = active
                        failed = False
                        if active:
                            driver = driver or self.factory()
                            driver.acquire()
                        elif driver:
                            driver.release()
                    elif active and driver and not failed:
                        getattr(driver, 'check', lambda: None)()
                except Exception:
                    if not failed:
                        log.warning('Could not maintain the host sleep inhibitor', exc_info=True)
                    failed = True
                    if driver:
                        try:
                            driver.release()
                        except Exception:
                            log.warning('Could not release the host sleep inhibitor', exc_info=True)
        finally:
            if driver:
                try:
                    driver.release()
                except Exception:
                    log.warning('Could not release the host sleep inhibitor on shutdown', exc_info=True)

    async def run(self, state):
        self.thread.start()
        try:
            while True:
                self.commands.put(has_work(state))
                await asyncio.sleep(1)
        finally:
            self.commands.put(None)
            await asyncio.to_thread(self.thread.join)
