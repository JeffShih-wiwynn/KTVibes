"""Installer arguments fail before changing the installation or contacting GitHub."""
from pathlib import Path
import subprocess

import pytest

INSTALLER = Path(__file__).resolve().parents[1] / 'install.sh'


@pytest.mark.parametrize('arguments', [
    ['--channel', 'dev'], ['--branch'], ['--branch='], ['--branch', ''],
    ['--branch', '-bad'], ['--branch', '../bad'], ['--branch', 'a b'],
])
def test_invalid_install_arguments_fail(arguments):
    result = subprocess.run(['bash', str(INSTALLER), *arguments], capture_output=True, text=True)
    assert result.returncode != 0
    assert result.stderr
    assert not result.stdout


def test_install_help_documents_branch():
    result = subprocess.run(['bash', str(INSTALLER), '--help'], capture_output=True, text=True)
    assert result.returncode == 0
    assert '--branch BRANCH_NAME' in result.stdout
    assert '--channel' not in result.stdout
