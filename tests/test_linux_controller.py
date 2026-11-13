"""Controller transactions without requiring a live systemd user manager."""
import json
from unittest.mock import Mock
import pytest
from ktvibes import linux



@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    return linux.config_dir()


def test_install_does_not_enable_or_start_service(config, monkeypatch):
    command = Mock()
    monkeypatch.setattr(linux, 'systemctl', command)
    linux.install()
    unit = config.parent / 'systemd/user/ktvibes.service'
    text = unit.read_text()
    assert '-m ktvibes.linux serve' in text
    assert 'WantedBy=default.target' in text
    assert command.call_args_list == [(('daemon-reload',),)]


def test_apply_restores_previous_settings_when_restart_fails(config, monkeypatch):
    previous = linux.preferences()
    linux.save(config / 'network.json', previous)
    candidate = dict(previous, port=12345)
    command = Mock()
    monkeypatch.setattr(linux, 'systemctl', command)
    monkeypatch.setattr(linux, 'wait_ready', Mock(side_effect=[RuntimeError('Port conflict'), {'port': 8765}]))
    with pytest.raises(RuntimeError, match='Previous settings restored'):
        linux.apply(candidate)
    assert linux.preferences() == previous
    assert command.call_count == 2


def test_working_directory_preserves_spaces_and_escapes_specifiers(config, tmp_path, monkeypatch):
    root = tmp_path / 'application with spaces 100%'
    root.mkdir()
    monkeypatch.setattr(linux, '__file__', str(root / 'ktvibes/linux.py'))
    monkeypatch.setattr(linux, 'systemctl', Mock())
    linux.install()
    text = (config.parent / 'systemd/user/ktvibes.service').read_text()
    line = next(line for line in text.splitlines() if line.startswith('WorkingDirectory='))
    assert line == 'WorkingDirectory=' + str(root).replace('%', '%%')


@pytest.mark.parametrize('value', ['/tmp/app\nother', '/tmp/app\rother'])
def test_working_directory_rejects_line_breaks(value):
    with pytest.raises(ValueError, match='line break'):
        linux.unit_path(value)


def test_apply_retains_new_settings_after_readiness(config, monkeypatch):
    monkeypatch.setattr(linux, 'systemctl', Mock())
    monkeypatch.setattr(linux, 'wait_ready', lambda: {'port': 9876})
    candidate = dict(linux.preferences(), port=9876)
    assert linux.apply(candidate)['port'] == 9876
    assert linux.preferences() == candidate


def test_saved_network_settings_are_private(config):
    linux.save(config / 'network.json', linux.preferences())
    assert (config / 'network.json').stat().st_mode & 0o077 == 0


def test_status_rejects_other_server_instance(config, monkeypatch):
    linux.save(config / 'runtime.json', {'token': 'secret', 'instance': 'expected'})
    (config / 'active-port').write_text('8765')
    from io import BytesIO
    monkeypatch.setattr(linux, 'urlopen', lambda *args, **kwargs: BytesIO(json.dumps({'instance_id': 'another-server'}).encode()))
    assert linux.status() is None


@pytest.mark.parametrize('quit_server', [False, True])
def test_terminal_exit_only_stops_service_on_quit(config, monkeypatch, quit_server):
    import curses
    for name in ('curs_set', 'raw'):
        monkeypatch.setattr(curses, name, Mock())
    monkeypatch.setattr(curses, 'has_colors', lambda: False)
    monkeypatch.setattr(linux, 'enabled', lambda: False)
    monkeypatch.setattr(linux, 'status', lambda: {'port': 8765, 'remote_url': 'http://host/remote', 'version': '0.7.0'})
    browser = Mock()
    monkeypatch.setattr(linux.webbrowser, 'open', browser)
    command = Mock()
    monkeypatch.setattr(linux, 'systemctl', command)
    screen = Mock()
    screen.getmaxyx.return_value = (24, 90)
    screen.getch.side_effect = [curses.KEY_DOWN] * 7 + [10] if quit_server else [3]
    linux.tui(screen)
    browser.assert_called_once_with('http://localhost:8765')
    if quit_server:
        command.assert_called_once_with('stop', linux.UNIT)
    else:
        command.assert_not_called()


def test_q_returns_from_network_and_network_picker(config, monkeypatch):
    import curses
    for name in ('curs_set', 'raw'):
        monkeypatch.setattr(curses, name, Mock())
    monkeypatch.setattr(curses, 'has_colors', lambda: False)
    monkeypatch.setattr(linux, 'status', lambda: None)
    monkeypatch.setattr(linux, 'preferences', lambda: dict(port=8765, ip='', external_url='', password_hash=''))
    monkeypatch.setattr(linux, 'interfaces', lambda: [('', 'Automatic'), ('192.0.2.1', 'test')])
    monkeypatch.setattr(linux, 'enabled', lambda: False)
    screen = Mock()
    screen.getmaxyx.return_value = (12, 36)
    screen.getch.side_effect = [curses.KEY_DOWN] * 3 + [10, 10, ord('q'), ord('q'), 3]

    linux.tui(screen)

    assert screen.getch.call_count == 8


def test_q_is_inserted_while_editing_a_text_field(config, monkeypatch):
    import curses
    for name in ('curs_set', 'raw'):
        monkeypatch.setattr(curses, name, Mock())
    monkeypatch.setattr(curses, 'has_colors', lambda: False)
    monkeypatch.setattr(linux, 'status', lambda: None)
    monkeypatch.setattr(linux, 'preferences', lambda: dict(port=8765, ip='', external_url='', password_hash=''))
    monkeypatch.setattr(linux, 'enabled', lambda: False)
    screen = Mock()
    screen.getmaxyx.return_value = (24, 80)
    screen.getch.side_effect = [curses.KEY_DOWN] * 3 + [10, curses.KEY_DOWN, 10, ord('q'), 3]
    screen.get_wch.side_effect = ['q', '\n']

    linux.tui(screen)

    assert screen.get_wch.call_count == 2


def test_logs_horizontal_scroll_and_bounds(config, monkeypatch):
    import curses
    import subprocess
    for name in ('curs_set', 'raw'):
        monkeypatch.setattr(curses, name, Mock())
    monkeypatch.setattr(curses, 'has_colors', lambda: False)
    monkeypatch.setattr(linux, 'status', lambda: None)
    monkeypatch.setattr(linux, 'enabled', lambda: False)
    content = '01234567' + 'abcdefghijklmnopqrstuvwx'
    monkeypatch.setattr(linux.subprocess, 'run', Mock(return_value=subprocess.CompletedProcess([], 0, content)))
    screen = Mock()
    screen.getmaxyx.return_value = (12, 22)
    screen.getch.side_effect = [curses.KEY_DOWN] * 2 + [10, curses.KEY_LEFT, curses.KEY_RIGHT,
        curses.KEY_RIGHT, curses.KEY_RIGHT, curses.KEY_LEFT, ord('q'), 3]
    linux.tui(screen)
    rendered = [call.args[2].strip() for call in screen.addnstr.call_args_list]
    assert content[:20] in rendered
    assert content[8:28] in rendered
    assert content[12:] in rendered  # Clamp at the longest line, rather than scrolling past it.


@pytest.mark.parametrize('target,confirm', [(None, False), ('dev · abc12345', False), ('dev · abc12345', True)])
def test_version_checks_and_confirmation(config, monkeypatch, target, confirm):
    import curses
    from ktvibes import linux_updates
    for name in ('curs_set', 'raw'):
        monkeypatch.setattr(curses, name, Mock())
    monkeypatch.setattr(curses, 'has_colors', lambda: False)
    monkeypatch.setattr(linux, 'status', lambda: None)
    monkeypatch.setattr(linux, 'enabled', lambda: False)
    monkeypatch.setattr(linux_updates, 'branch', lambda: 'dev')
    monkeypatch.setattr(linux_updates, 'available', lambda mode: target)
    prepare = Mock(return_value='/tmp/helper')
    monkeypatch.setattr(linux_updates, 'prepare_handoff', prepare)
    screen = Mock()
    screen.getmaxyx.return_value = (24, 80)
    screen.getch.side_effect = [10] + ([curses.KEY_DOWN, 10] if confirm else ([ord('q')] if target else [])) + [3]
    if confirm:
        with pytest.raises(linux_updates.UpdateRequested):
            linux.tui(screen)
        prepare.assert_called_once_with('dev')
    else:
        linux.tui(screen)
        prepare.assert_not_called()
        if target is None:
            assert any('Already up to date' in call.args[2] for call in screen.addnstr.call_args_list)
