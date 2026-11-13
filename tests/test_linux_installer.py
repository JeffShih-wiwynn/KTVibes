"""Installer arguments fail before changing the installation or contacting GitHub."""
from pathlib import Path
import os
import subprocess
import sys

import pytest

INSTALLER = Path(__file__).resolve().parents[1] / 'install.sh'


def test_acceleration_bootstrap_imports_without_installed_dependencies():
    # -S removes site-packages, matching the installer's fresh standalone Python.
    result = subprocess.run(
        [sys.executable, '-S', '-m', 'ktvibes.acceleration'],
        cwd=INSTALLER.parent, capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert 'Usage: acceleration.py' in result.stderr
    assert 'Traceback' not in result.stderr


@pytest.mark.parametrize('arguments', [
    ['--channel', 'dev'], ['--branch'], ['--branch='], ['--branch', ''],
    ['--branch', '-bad'], ['--branch', '../bad'], ['--branch', 'a b'],
])
@pytest.mark.skipif(os.name == 'nt', reason='Linux shell installer requires a POSIX host')
def test_invalid_install_arguments_fail(arguments):
    result = subprocess.run(['bash', str(INSTALLER), *arguments], capture_output=True, text=True)
    assert result.returncode != 0
    assert result.stderr
    assert not result.stdout


@pytest.mark.skipif(os.name == 'nt', reason='Linux shell installer requires a POSIX host')
def test_install_help_documents_branch():
    result = subprocess.run(['bash', str(INSTALLER), '--help'], capture_output=True, text=True)
    assert result.returncode == 0
    assert '--branch BRANCH_NAME' in result.stdout
    assert '--channel' not in result.stdout
