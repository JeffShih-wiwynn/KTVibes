"""Check real logind lock ownership, normal release and server crash cleanup."""
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ktvibes.power import LinuxSleep


def locks():
    return subprocess.check_output(['systemd-inhibit', '--list', '--no-pager', '--no-legend'], text=True)


def registered(driver):
    for _ in range(50):
        driver.check()
        if 'KTVibes' in locks():
            return
        time.sleep(.1)
    raise AssertionError('No real KTVibes sleep inhibitor registered')


def released():
    for _ in range(50):
        if 'KTVibes' not in locks():
            return
        time.sleep(.1)
    raise AssertionError('KTVibes inhibitor survived release or parent exit')


if __name__ == '__main__':
    released()
    driver = LinuxSleep()
    if '--crash' in sys.argv:
        driver.acquire()
        registered(driver)
        os._exit(0)
    try:
        driver.acquire()
        registered(driver)
    finally:
        driver.release()
    released()
    subprocess.run([sys.executable, str(Path(__file__).resolve()), '--crash'], check=True)
    released()
    print('Linux sleep inhibitor acquisition, release and crash cleanup passed.')
