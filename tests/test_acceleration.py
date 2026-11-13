from unittest.mock import Mock
import pytest
from ktvibes import acceleration as a, linux


def test_cpu_probe_runs_in_separate_python_process():
    # Exercise the real import path: torch imports stdlib queue, which must not
    # resolve to ktvibes/queue.py when launching the probe.
    if not (a.ROOT / '.venv/bin/python').exists():
        pytest.skip('Requires the project virtual environment')
    a.validate('cpu')


def test_switch_rolls_back_packages_and_setting(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    previous = {'backend': 'cpu', 'uv': '/bin/uv'}
    a.write_settings(previous)
    sync = Mock()
    monkeypatch.setattr(a, 'sync', sync)
    monkeypatch.setattr(a, 'validate', Mock(side_effect=RuntimeError('unsupported operator')))
    monkeypatch.setattr(linux, 'systemctl', Mock())
    monkeypatch.setattr(linux, 'wait_ready', Mock())
    with pytest.raises(RuntimeError, match='Previous backend restored'):
        a.switch('xpu', Mock())
    assert [call.args[0] for call in sync.call_args_list] == ['xpu', 'cpu']
    assert a.settings() == previous


def test_switch_validates_before_saving_backend(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    a.write_settings({'backend': 'cpu', 'uv': '/bin/uv'})
    monkeypatch.setattr(a, 'sync', Mock())
    def validate(mode):
        assert a.settings()['backend'] == 'cpu'
        assert mode == 'xpu'
    monkeypatch.setattr(a, 'validate', validate)
    command = Mock()
    monkeypatch.setattr(linux, 'systemctl', command)
    monkeypatch.setattr(linux, 'wait_ready', Mock())
    a.switch('xpu', Mock())
    assert a.settings()['backend'] == 'xpu'
    assert [call.args[0] for call in command.call_args_list] == ['stop', 'start']
