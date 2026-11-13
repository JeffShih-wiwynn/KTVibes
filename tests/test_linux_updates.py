"""Exercise update orchestration with a real shell and disposable fake commands."""
import json
import os
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest
from ktvibes import linux_updates as updates


def test_saved_branch_and_legacy_tag_detection(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, 'v0.7.1\n'))
    monkeypatch.setattr(updates.subprocess, 'run', runner)
    assert updates.branch() is None
    runner.return_value = subprocess.CompletedProcess([], 1, '')
    assert updates.branch() == 'dev'
    path = tmp_path / 'ktvibes/installation.json'
    path.parent.mkdir()
    path.write_text(json.dumps({'channel': 'stable'}))
    assert updates.branch() is None
    runner.return_value = subprocess.CompletedProcess([], 0, '')
    path.write_text(json.dumps({'channel': 'dev'}))
    assert updates.branch() == 'dev'


@pytest.mark.parametrize('branch', [None, 'dev', 'feature/new-ui', 'stable', "feature/o'connor"])
@pytest.mark.parametrize('failure', [False, True])
def test_handoff_stops_installs_and_only_restarts_on_success(tmp_path, monkeypatch, branch, failure):
    root = tmp_path / 'application with spaces'
    root.mkdir()
    record = tmp_path / 'events'
    monkeypatch.setattr(updates, 'ROOT', root)
    monkeypatch.setenv('RECORD', str(record))
    (root / 'install.sh').write_text('echo "install $*" >> "$RECORD"\nexit ' + ('1' if failure else '0') + '\n')
    fake_bin = tmp_path / 'bin'
    fake_bin.mkdir()
    systemctl = fake_bin / 'systemctl'
    systemctl.write_text('#!/bin/sh\necho "$*" >> "$RECORD"\n')
    systemctl.chmod(0o755)
    monkeypatch.setenv('PATH', str(fake_bin) + os.pathsep + os.environ['PATH'])
    python = root / '.venv/bin/python'
    python.parent.mkdir(parents=True)
    python.write_text('#!/bin/sh\necho "tui $*" >> "$RECORD"\n')
    python.chmod(0o755)
    helper = updates.prepare_handoff(branch)
    # Resetting the source checkout cannot replace the updater's snapshot.
    (root / 'install.sh').write_text('exit 99\n')
    result = subprocess.run(['bash', str(helper)], capture_output=True, text=True)
    events = record.read_text().splitlines()
    assert events[:2] == ['--user stop ktvibes.service', 'install' + (' --branch ' + branch if branch else ' ')]
    if failure:
        assert result.returncode == 1
        assert len(events) == 2
        assert 'remains stopped' in result.stderr
    else:
        assert result.returncode == 0
        assert events[2:] == ['--user start ktvibes.service', 'tui -m ktvibes.linux']
    assert not helper.parent.exists()


@pytest.mark.parametrize('value', [None, 'feature/new-ui', 'stable'])
def test_reads_branch_metadata(tmp_path, monkeypatch, value):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    path = tmp_path / 'ktvibes/installation.json'
    path.parent.mkdir()
    path.write_text(json.dumps({'branch': value}))
    assert updates.branch() == value


@pytest.mark.parametrize('value', ['', '-bad', '../bad', 'a b', 'a~b'])
def test_rejects_invalid_branch(value):
    with pytest.raises(ValueError):
        updates.prepare_handoff(value)


def test_custom_branch_update_checks_exact_ref(monkeypatch):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        if args[1] == 'check-ref-format':
            return subprocess.CompletedProcess(args, 0, '')
        if args[1] == 'ls-remote':
            return subprocess.CompletedProcess(args, 0, 'abcdef123456 refs/heads/feature/new-ui')
        return subprocess.CompletedProcess(args, 0, 'old')
    monkeypatch.setattr(updates.subprocess, 'run', run)
    assert updates.available('feature/new-ui') == 'feature/new-ui · abcdef12'
    assert calls[1][-1] == 'refs/heads/feature/new-ui'
