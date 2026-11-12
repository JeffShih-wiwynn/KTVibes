"""Run the production macOS readiness probe against an authenticated service."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
import shutil
import subprocess
from threading import Thread

import pytest


def test_macos_readiness_uses_desktop_config_credential(tmp_path):
    if os.name == 'nt':
        pytest.skip('macOS shell startup probe')
    if not shutil.which('bash') or not shutil.which('curl') or not shutil.which('seq'):
        pytest.skip('POSIX startup probe needs bash, curl and seq')
    paths = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            ok = self.path == '/api/config' and self.headers.get('Authorization') == 'Bearer test-desktop-token'
            self.send_response(200 if ok else 401); self.end_headers(); self.wfile.write(b'{}')
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    port_file = tmp_path / 'active-port'; port_file.write_text(str(server.server_port))
    source = (Path(__file__).parents[1] / 'installer/macos/setup-and-run.sh').read_text()
    probe = source[source.index('server_ready=0'):source.rindex('wait "$server_pid"')]
    probe = probe.replace('seq 1 120', 'seq 1 2')
    try:
        result = subprocess.run(['bash', '-c', 'log(){ echo "$*"; }; server_pid=$$\n' + probe], env={**os.environ, 'KTVIBES_PORT_FILE': str(port_file), 'KTVIBES_DESKTOP_TOKEN': 'test-desktop-token'}, text=True, capture_output=True, timeout=8)
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'KTVIBES_SERVER_READY' in result.stdout
        assert paths == ['/api/config']
    finally:
        server.shutdown(); server.server_close(); thread.join()
