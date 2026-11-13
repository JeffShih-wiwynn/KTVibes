"""Linux terminal controller. systemd owns the server independently of the terminal."""
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
import webbrowser
from urllib.request import Request, urlopen

UNIT = 'ktvibes.service'
RELEASE = 'https://github.com/JeffShih-wiwynn/KTVibes/releases/latest'


def config_dir():
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'ktvibes'


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream)
    temporary.replace(path)


def preferences():
    path = config_dir() / 'network.json'
    return json.loads(path.read_text()) if path.exists() else dict(port=8765, ip='', external_url='', password_hash='')


def systemctl(*args):
    result = subprocess.run(['systemctl', '--user', *args], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'systemctl failed')
    return result.stdout.strip()


def enabled():
    return subprocess.run(['systemctl', '--user', 'is-enabled', '--quiet', UNIT], capture_output=True).returncode == 0


def quote_unit(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('\n', '\\n') + '"'


def unit_path(value):
    """Escape a filesystem path for systemd path-valued directives."""
    escapes = {'\\': '\\\\', ' ': '\\x20', '\t': '\\x09', '\n': '\\x0a', '\r': '\\x0d', '"': '\\x22'}
    return ''.join(escapes.get(char, '%%' if char == '%' else char) for char in str(value))


def install():
    root = Path(__file__).resolve().parent.parent
    unit_dir = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'systemd/user'
    unit_dir.mkdir(parents=True, exist_ok=True)
    environment = {key: os.environ[key] for key in ('PATH', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'KTVIBES_CACHE') if key in os.environ}
    text = '[Unit]\nDescription=KTVibes karaoke server\n\n[Service]\nType=simple\n'
    text += 'WorkingDirectory=' + unit_path(root) + '\n'
    text += 'ExecStart=' + quote_unit(sys.executable) + ' -m ktvibes.linux serve\n'
    text += ''.join('Environment=' + quote_unit(f'{key}={value}') + '\n' for key, value in environment.items())
    text += 'KillMode=control-group\nTimeoutStopSec=30\nStandardOutput=journal\nStandardError=journal\n\n[Install]\nWantedBy=default.target\n'
    (unit_dir / UNIT).write_text(text)
    systemctl('daemon-reload')


def serve():
    settings = preferences()
    from .acceleration import settings as acceleration_settings
    os.environ['KTVIBES_DEVICE'] = acceleration_settings().get('backend', 'cpu')
    directory = config_dir()
    runtime = dict(token=secrets.token_urlsafe(32), instance=secrets.token_hex(16))
    save(directory / 'runtime.json', runtime)
    port_file = directory / 'active-port'
    conflict_file = directory / 'port-conflict'
    port_file.unlink(missing_ok=True)
    conflict_file.unlink(missing_ok=True)
    os.environ.update(KTVIBES_PORT=str(settings['port']), KTVIBES_ADVERTISE_IP=settings['ip'],
                      KTVIBES_AUTO_PORT='1', KTVIBES_OPEN_BROWSER='0',
                      KTVIBES_PORT_FILE=str(port_file), KTVIBES_CONFLICT_FILE=str(conflict_file),
                      KTVIBES_DESKTOP_TOKEN=runtime['token'], KTVIBES_INSTANCE_ID=runtime['instance'],
                      KTVIBES_EXTERNAL_ENABLED='1' if settings['external_url'] else '0',
                      KTVIBES_REMOTE_URL=settings['external_url'], KTVIBES_PASSWORD_HASH=settings['password_hash'],
                      KTVIBES_CREDENTIAL_TYPE='pin')
    from .main import run
    sys.argv = ['ktvibes']
    run()


def status():
    try:
        runtime = json.loads((config_dir() / 'runtime.json').read_text())
        port = int((config_dir() / 'active-port').read_text())
        request = Request(f'http://127.0.0.1:{port}/api/config', headers={'Authorization': 'Bearer ' + runtime['token']})
        with urlopen(request, timeout=.4) as response:
            config = json.load(response)
        return config if config.get('instance_id') == runtime['instance'] else None
    except (OSError, ValueError, KeyError):
        return None


def wait_ready():
    for _ in range(150):
        if config := status():
            return config
        if (config_dir() / 'port-conflict').exists():
            break
        time.sleep(1)
    raise RuntimeError('Server unavailable. Check Show Logs or choose another port in Network Settings.')


def apply(settings):
    previous = preferences()
    save(config_dir() / 'network.json', settings)
    try:
        (config_dir() / 'port-conflict').unlink(missing_ok=True)
        systemctl('restart', UNIT)
        # A restart replaces credentials and active-port before readiness is checked.
        return wait_ready()
    except Exception as error:
        save(config_dir() / 'network.json', previous)
        (config_dir() / 'port-conflict').unlink(missing_ok=True)
        systemctl('restart', UNIT)
        try:
            wait_ready()
        except RuntimeError:
            raise RuntimeError('Server unavailable after restoring settings. Check Show Logs.') from error
        raise RuntimeError('Previous settings restored. ' + str(error)) from error


def interfaces():
    result = subprocess.run(['ip', '-j', '-4', 'address', 'show', 'up'], capture_output=True, text=True, check=True)
    return [('', 'Automatic')] + [(address['local'], entry['ifname'] + ' — ' + address['local'])
                                 for entry in json.loads(result.stdout) if entry['ifname'] != 'lo'
                                 for address in entry.get('addr_info', []) if address.get('family') == 'inet']


def tui(screen):
    import curses
    from .updates import project_version
    local_version = project_version()
    from .linux_updates import channel
    installed_channel = channel()
    curses.curs_set(0)
    curses.raw()  # Ctrl+C is a navigation key, not a server signal.
    colors = curses.has_colors()
    if colors:
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_RED, -1)
        curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_GREEN)
        curses.init_pair(3, curses.COLOR_GREEN, -1)
    screen.timeout(500)

    def row(text, kind='item', selectable=True):
        return text, kind, selectable

    def draw(title, rows, selected=None, footer='↑↓ Move  Enter Select  q / Esc Back'):
        screen.erase()
        height, width = screen.getmaxyx()
        box_width = max(1, min(84, width - 2))
        left = max(0, (width - box_width) // 2)
        top = 1 if height >= 16 else 0
        inner_width = box_width
        normalized = []
        for item in rows:
            entry = (item, 'item', True) if isinstance(item, str) else item
            if entry[1] == 'section' and normalized:
                normalized.append(('', 'info', False))
            normalized.append(entry)

        def put(y, value, style=curses.A_NORMAL):
            if y < 0 or y >= height - 1:
                return
            try:
                screen.addnstr(y, left, value[:box_width].ljust(box_width), box_width, style)
            except curses.error:
                pass

        put(top, title, curses.A_BOLD)

        max_body = max(0, height - top - 4)
        selectable_rows = [position for position, (_, _, selectable) in enumerate(normalized) if selectable]
        selected_position = selectable_rows[selected] if selected is not None and selected < len(selectable_rows) else None
        start = max(0, len(normalized) - max_body) if selected_position is None else max(
            0, min(selected_position - max_body + 1, len(normalized) - max_body))
        visible_rows = normalized[start:start + max_body]
        for offset, (text, kind, selectable) in enumerate(visible_rows):
            style = curses.A_NORMAL
            if kind == 'section':
                style = (curses.color_pair(3) | curses.A_BOLD) if colors else curses.A_BOLD
            elif kind == 'info':
                style = getattr(curses, 'A_DIM', curses.A_NORMAL)
            elif kind == 'status':
                style = curses.A_BOLD
            elif kind == 'success':
                style = (curses.color_pair(3) | curses.A_BOLD) if colors else curses.A_BOLD
            is_selected = selectable and selected_position == start + offset
            if selectable:
                if is_selected:
                    style = (curses.color_pair(2) | curses.A_BOLD) if colors else (curses.A_REVERSE | curses.A_BOLD)
            if kind == 'danger' and colors and not is_selected:
                style = curses.color_pair(1) | curses.A_BOLD
            content = text[:inner_width].ljust(inner_width)
            put(top + 2 + offset, content, style)

        try:
            screen.addnstr(height - 1, 0, footer[:max(0, width - 1)], max(0, width - 1), curses.A_DIM)
        except curses.error:
            pass
        screen.refresh()

    def choose(title, rows):
        index = 0
        while True:
            draw(title, [row(label) for label in rows], index, '↑↓ Move  Enter Select  q / Esc Back')
            key = screen.getch()
            if key in (27, 3, ord('q')):
                return None
            if key in (curses.KEY_UP, curses.KEY_DOWN):
                index = (index + (1 if key == curses.KEY_DOWN else -1)) % len(rows)
            if key in (10, 13):
                return index

    def edit(label, value='', secret=False):
        text = str(value)
        while True:
            shown = ('•' * len(text) if secret else text) or '(empty)'
            draw('Edit · ' + label, [row(shown, 'info', False)], footer='Type value  Enter Save  Esc Cancel')
            try:
                key = screen.get_wch()
            except curses.error:
                continue
            if key in ('\n', '\r'):
                return text
            if key in ('\x1b', '\x03'):
                return str(value)
            if key in (curses.KEY_BACKSPACE, '\x7f', '\b'):
                text = text[:-1]
            elif isinstance(key, str) and key.isprintable():
                text += key

    def logs():
        horizontal = 0
        while True:
            result = subprocess.run(['journalctl', '--user', '-u', UNIT, '-n', str(max(1, screen.getmaxyx()[0] - 4)), '--no-pager', '-o', 'short'], capture_output=True, text=True)
            lines = result.stdout.splitlines() or [result.stderr or 'No logs yet.']
            viewport = max(1, min(84, screen.getmaxyx()[1] - 2))
            limit = max(0, max(map(len, lines)) - viewport)
            horizontal = min(horizontal, limit)
            draw('Logs', [row(line[horizontal:], 'info', False) for line in lines],
                 footer='←/→ Scroll  q / Esc Back')
            key = screen.getch()
            if key in (ord('q'), 27, 3):
                return
            if key == curses.KEY_RIGHT:
                horizontal = min(limit, horizontal + 8)
            elif key == curses.KEY_LEFT:
                horizontal = max(0, horizontal - 8)

    def network():
        draft = preferences()
        external = bool(draft['external_url'])
        pin = ''
        message = 'Applying changes will restart the server.'
        index = 0
        while True:
            config = status()
            fields = ['network', 'port', 'external'] + (['https', 'pin'] if external else []) + ['reset', 'apply']
            index = min(index, len(fields) - 1)
            remote = config['remote_url'] if config else 'Unavailable'
            rows = [row('REMOTE ADDRESS', 'section', False), row(remote, 'info', False),
                    row('NETWORK', 'section', False)]
            values = {
                'network': f"Network interface   [ {draft['ip'] or 'Automatic'} ▾ ]",
                'port': f"Port                [ {draft['port']} ]",
                'external': f"External address    [ {'x' if external else ' '} ]",
                'https': f"HTTPS URL           [ {draft['external_url']} ]",
                'pin': f"PIN                 [ {'•' * len(pin) if pin else 'blank keeps current PIN'} ]",
            }
            rows.extend(row(values[field]) for field in fields if field in values)
            rows.append(row('ACTIONS', 'section', False))
            rows.extend([row('[ Reset ]', 'action'), row('[ Apply ]', 'action'), row(message, 'status', False)])
            draw('Network Settings', rows, index,
                 '↑↓ Move  Enter Edit/Apply  Space Toggle  q / Esc Back')
            key = screen.getch()
            if key in (27, 3, ord('q')):
                return
            if key in (curses.KEY_UP, curses.KEY_DOWN, 9):
                index = (index + (-1 if key == curses.KEY_UP else 1)) % len(fields)
            if key not in (10, 13, 32):
                continue
            try:
                field = fields[index]
                if field == 'network':
                    choices = interfaces()
                    chosen = choose('Select network', [label for _, label in choices])
                    if chosen is not None:
                        draft['ip'] = choices[chosen][0]
                elif field == 'port':
                    port = int(edit('Port (1–65535)', draft['port']))
                    if not 1 <= port <= 65535:
                        raise ValueError('Port must be between 1 and 65535.')
                    draft['port'] = port
                elif field == 'external':
                    external = not external
                elif field == 'https':
                    draft['external_url'] = edit('HTTPS URL', draft['external_url']).strip()
                elif field == 'pin':
                    pin = edit('PIN (at least 6 digits)', pin, secret=True)
                elif field == 'reset':
                    draft = dict(port=8765, ip='', external_url='', password_hash='')
                    external = False
                    pin = ''
                elif field == 'apply':
                    from .auth import password_hash, validate_external
                    candidate = dict(draft)
                    if external:
                        if pin:
                            if not pin.isascii() or not pin.isdecimal() or not 6 <= len(pin) <= 1024:
                                raise ValueError('Use a PIN of at least 6 digits (0–9).')
                            candidate['password_hash'] = password_hash(pin)
                        if not candidate['password_hash']:
                            raise ValueError('Set a PIN of at least 6 digits before enabling External address.')
                        candidate['external_url'] = validate_external(candidate['external_url'], candidate['password_hash'])
                    else:
                        candidate.update(external_url='', password_hash='')
                    draw('Network Settings', [row('Restarting service…', 'status', False)], None)
                    if candidate != preferences() or not status() or (config_dir() / 'port-conflict').exists():
                        apply(candidate)
                    draft = candidate
                    pin = ''
                    message = 'Applying changes will restart the server.'
            except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
                message = str(error)

    def acceleration():
        from .acceleration import available, settings, switch, LABELS
        modes = available()
        current = settings().get('backend', 'cpu')
        selected = choose('AI Acceleration · Current: ' + LABELS[current],
                          [LABELS[mode] for mode in modes] + ['Cancel'])
        if selected is None or selected == len(modes) or modes[selected] == current:
            return
        if choose('Switching downloads packages and restarts the server.', ['Cancel', 'Apply']) != 1:
            return
        # Let uv display its progress outside curses, then restore the terminal UI.
        curses.def_prog_mode()
        curses.endwin()
        try:
            switch(modes[selected])
        finally:
            curses.reset_prog_mode()
            screen.refresh()

    index = 0
    message = ''
    message_kind = 'status'
    opened = False
    while True:
        config = status()
        if config and not opened:
            webbrowser.open(f"http://localhost:{config['port']}")
            opened = True
        conflict = (config_dir() / 'port-conflict').exists()
        version = 'Port conflict' if conflict else 'Version ' + (config['version'] if config else local_version)
        if not conflict:
            version += ' · ' + installed_channel
        if installed_channel == 'stable' and config and config.get('update'):
            version += ' → ' + config['update']['version']
        rows = [row('REMOTE ADDRESS', 'section', False),
                row(config['remote_url'] if config else 'Unavailable', 'info', False),
                row('PLAYER', 'section', False), row(version, 'danger' if conflict else 'item')]
        if message:
            rows.append(row(message, message_kind, False))
        rows.extend([row('Open Player'), row('Show Logs'),
                row('SETTINGS', 'section', False), row('Network Settings…'), row('AI Acceleration…'),
                row('Launch at Login     ' + ('[x]' if enabled() else '[ ]')),
                row('SERVICE', 'section', False), row('Detach', 'action'), row('Quit', 'danger')])
        draw('KTVibes', rows, index, '↑↓ Move  Enter Select  Ctrl+C Detach')
        key = screen.getch()
        if key == 3:
            return
        if key in (curses.KEY_UP, curses.KEY_DOWN):
            index = (index + (1 if key == curses.KEY_DOWN else -1)) % 8
        if key in (ord('q'), 27) or key not in (10, 13):
            continue
        try:
            if index == 0:
                if conflict:
                    network()
                else:
                    from .linux_updates import available, UpdateRequested, prepare_handoff
                    selected_channel = installed_channel
                    draw('Updates', [row('Checking for updates…', 'status', False)])
                    target = available(selected_channel)
                    if not target:
                        message = '✓ Already up to date (' + selected_channel + ').'
                        message_kind = 'success'
                    elif choose('Update to ' + target + '? Service will restart.', ['Cancel', 'Update']) == 1:
                        helper = prepare_handoff(selected_channel)
                        raise UpdateRequested(helper)
            elif index == 1:
                if config:
                    webbrowser.open(f"http://localhost:{config['port']}")
                else:
                    message = 'Server unavailable. Check Show Logs.'
                    message_kind = 'danger'
            elif index == 2:
                logs()
            elif index == 3:
                network()
            elif index == 4:
                acceleration()
            elif index == 5:
                systemctl('disable' if enabled() else 'enable', UNIT)
            elif index == 6:
                return
            elif index == 7:
                systemctl('stop', UNIT)
                return
        except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
            message = str(error)
            message_kind = 'danger'


def main():
    from .linux_updates import UpdateRequested
    if sys.argv[1:] == ['serve']:
        return serve()
    if sys.argv[1:] not in ([], ['--install']):
        sys.exit('Usage: python -m ktvibes.linux [--install | serve]')
    if sys.platform != 'linux' or not shutil.which('systemctl'):
        sys.exit('The Linux TUI requires systemd. Use uv run ktvibes for foreground operation.')
    if sys.argv[1:] != ['--install'] and (not sys.stdin.isatty() or not sys.stdout.isatty()):
        sys.exit('The TUI needs an interactive terminal. Use systemctl --user start ktvibes to start the service.')
    try:
        install()
        if sys.argv[1:] == ['--install']:
            return
        systemctl('start', UNIT)
        import curses
        try:
            curses.wrapper(tui)
        except KeyboardInterrupt:
            pass  # Detach; systemd keeps the server alive.
    except UpdateRequested as request:
        os.execv('/bin/bash', ['bash', str(request.helper)])
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        sys.exit(str(error))


if __name__ == '__main__':
    main()
