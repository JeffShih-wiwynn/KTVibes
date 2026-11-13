"""Channel-aware updates, handed to bash after the terminal UI exits."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent


class UpdateRequested(Exception):
    def __init__(self, helper):
        self.helper = helper


def channel():
    directory = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'ktvibes'
    path = directory / 'installation.json'
    if path.exists():
        value = json.loads(path.read_text()).get('channel')
        if value not in ('stable', 'dev'):
            raise RuntimeError('Invalid installation channel. Rerun the installer with --channel stable or dev.')
        return value
    # Historical installers tracked dev; exact numeric release tags identify stable installs.
    result = subprocess.run(['git', 'describe', '--tags', '--exact-match', 'HEAD'], cwd=ROOT,
                            capture_output=True, text=True, timeout=10)
    from .updates import version_key
    return 'stable' if result.returncode == 0 and version_key(result.stdout.strip()) else 'dev'


def available(selected_channel):
    if selected_channel == 'dev':
        result = subprocess.run(['git', 'ls-remote', 'https://github.com/JeffShih-wiwynn/KTVibes.git',
                                 'refs/heads/dev'], capture_output=True, text=True, timeout=15, check=True)
        remote = result.stdout.split()
        if not remote:
            raise RuntimeError('Could not find the dev branch.')
        local = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True,
                               text=True, timeout=10, check=True).stdout.strip()
        return 'dev · ' + remote[0][:8] if remote[0] != local else None
    from .updates import GITHUB_RELEASE_API, newer_release, project_version
    request = Request(GITHUB_RELEASE_API, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'KTVibes'})
    with urlopen(request, timeout=10) as response:
        release = json.load(response)
    update = newer_release(project_version(), release)
    return update['version'] if update else None


def prepare_handoff(selected_channel):
    if selected_channel not in ('stable', 'dev'):
        raise ValueError('Invalid update channel')
    directory = Path(tempfile.mkdtemp(prefix='ktvibes-update-'))
    try:
        # Snapshot both scripts: git reset during installation may replace their originals.
        installer = directory / 'install.sh'
        shutil.copyfile(ROOT / 'install.sh', installer)
        helper = directory / 'update.sh'
        helper.write_text(f'''#!/usr/bin/env bash
set -u
trap 'rm -rf -- {shlex.quote(str(directory))}' EXIT
if ! systemctl --user stop ktvibes.service; then
  echo "Could not stop KTVibes. Update cancelled." >&2
  exit 1
fi
if ! bash {shlex.quote(str(installer))} --channel {selected_channel}; then
  echo "Update failed. KTVibes remains stopped. Rerun the installer to retry." >&2
  exit 1
fi
if ! systemctl --user start ktvibes.service; then
  echo "Update installed, but the service could not start. Check journalctl --user -u ktvibes." >&2
  exit 1
fi
rm -rf -- {shlex.quote(str(directory))}
trap - EXIT
cd {shlex.quote(str(ROOT))}
exec {shlex.quote(str(ROOT / '.venv/bin/python'))} -m ktvibes.linux
''')
        return helper
    except BaseException:
        shutil.rmtree(directory)
        raise
