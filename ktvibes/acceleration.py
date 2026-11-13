"""Linux PyTorch backend selection and transactional environment switching."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
LABELS = {'cpu': 'CPU', 'cuda': 'NVIDIA CUDA', 'xpu': 'Intel XPU · Experimental'}


def settings_path():
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'ktvibes/acceleration.json'


def settings():
    path = settings_path()
    return json.loads(path.read_text()) if path.exists() else {}


def write_settings(value):
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value))
    temporary.replace(path)


def available():
    modes = ['cpu']
    if shutil.which('nvidia-smi'):
        try:
            if subprocess.run(['nvidia-smi', '-L'], capture_output=True, timeout=10).returncode == 0:
                modes.append('cuda')
        except (OSError, subprocess.TimeoutExpired):
            pass
    # Intel display/render devices are candidates, not proof of XPU runtime support.
    for vendor in Path('/sys/class/drm').glob('renderD*/device/vendor'):
        try:
            intel = vendor.read_text().strip() == '0x8086'
        except OSError:
            continue
        if intel:
            modes.append('xpu')
            break
    return modes


def sync(mode, uv):
    subprocess.run([uv, 'sync', '--locked', '--no-dev', '--extra', mode], cwd=ROOT, check=True)


def probe(mode):
    import torch
    if mode != 'cpu' and not getattr(torch, mode).is_available():
        raise RuntimeError(f'{mode.upper()} is unavailable. Check GPU drivers and compute runtime, or select CPU.')
    if mode == 'xpu':
        from demucs.pretrained import get_model
        from demucs.apply import apply_model
        model = get_model('htdemucs').to('xpu').eval()
        with torch.inference_mode():
            output = apply_model(model, torch.zeros(1, 2, 88200), device='xpu', shifts=0, split=True)
        if not torch.isfinite(output).all().item():
            raise RuntimeError('XPU model validation produced invalid audio.')
    else:
        result = (torch.ones(4, device=mode) * 2).sum().item()
        if result != 8:
            raise RuntimeError('PyTorch backend validation failed.')


def validate(mode):
    subprocess.run([str(ROOT / '.venv/bin/python'), '-m', 'ktvibes.acceleration', 'probe', mode], cwd=ROOT, check=True)


def switch(mode, progress=print):
    from .linux import systemctl, wait_ready
    previous = settings()
    uv = previous.get('uv') or shutil.which('uv')
    if not uv:
        raise RuntimeError('uv not found. Rerun the Linux installer.')
    systemctl('stop', 'ktvibes.service')
    try:
        progress('Installing ' + LABELS[mode] + ' packages…')
        sync(mode, uv)
        progress('Validating ' + LABELS[mode] + '…')
        validate(mode)
        write_settings({'backend': mode, 'uv': uv})
        from .linux import config_dir
        (config_dir() / 'port-conflict').unlink(missing_ok=True)
        systemctl('start', 'ktvibes.service')
        wait_ready()
    except (Exception, KeyboardInterrupt) as error:
        progress('Restoring previous backend…')
        try:
            sync(previous.get('backend', 'cpu'), uv)
            write_settings(previous)
            from .linux import config_dir
            (config_dir() / 'port-conflict').unlink(missing_ok=True)
            systemctl('start', 'ktvibes.service')
            wait_ready()
        except Exception as restore_error:
            raise RuntimeError('Restore failed. Rerun the installer. ' + str(restore_error)) from error
        raise RuntimeError('Previous backend restored. ' + str(error)) from error


def install():
    previous = settings()
    mode = previous.get('backend')
    if mode not in LABELS:
        modes = available()
        mode = 'cuda' if 'cuda' in modes else 'cpu'
        if mode == 'cpu' and 'xpu' in modes:
            try:
                with open('/dev/tty', 'r+') as tty:
                    tty.write('Intel GPU detected. Enable experimental XPU acceleration? [y/N] ')
                    tty.flush()
                    if tty.readline().strip().lower() in ('y', 'yes'):
                        mode = 'xpu'
            except OSError:
                pass
    uv = shutil.which('uv')
    if not uv:
        raise RuntimeError('uv not found')
    print('Installing ' + LABELS[mode], flush=True)
    try:
        sync(mode, uv)
        validate(mode)
    except subprocess.CalledProcessError:
        if mode == 'cpu':
            raise
        print('GPU validation failed; installing CPU instead.', flush=True)
        mode = 'cpu'
        sync(mode, uv)
        validate(mode)
    write_settings({'backend': mode, 'uv': uv})


if __name__ == '__main__':
    if sys.argv[1:] == ['install']:
        install()
    elif len(sys.argv) == 3 and sys.argv[1] == 'probe':
        probe(sys.argv[2])
    else:
        sys.exit('Usage: acceleration.py install | probe cpu|cuda|xpu')
