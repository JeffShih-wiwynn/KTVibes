"""External access protects HTTP, WebSocket and QR credentials together."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from ktvibes.auth import password_hash, Access
from ktvibes.application import create_app
from ktvibes.runtime import Runtime


@pytest.fixture(scope='module')
def encoded():
    return password_hash('a good test password')


@pytest.fixture
def external(tmp_path, encoded):
    with patch.dict('os.environ', {'KTVIBES_EXTERNAL_ENABLED': '1', 'KTVIBES_REMOTE_URL': 'https://ktv.example.test', 'KTVIBES_PASSWORD_HASH': encoded, 'KTVIBES_DESKTOP_TOKEN': 'desktop-secret'}):
        runtime = Runtime(cache=tmp_path)
        app = create_app(runtime)
        yield runtime, app


def test_inner_network_requires_no_credentials(tmp_path):
    with patch.dict('os.environ', {'KTVIBES_EXTERNAL_ENABLED': '0'}):
        runtime = Runtime(cache=tmp_path)
    client = TestClient(create_app(runtime))
    assert 'remote.js' in client.get('/remote').text
    assert client.get('/api/state').status_code == 200
    assert '#key=' not in runtime.join_url()
    assert runtime.access.key is None


def test_password_gate_and_owner_session(external):
    runtime, app = external
    client = TestClient(app, base_url='https://ktv.example.test')
    assert f'/static/{runtime.asset_version}/login.js' in client.get('/').text
    for path in ('/api/state', '/api/config', '/api/qr.svg', '/media/aaaaaaaaaaa/video.mp4'):
        assert client.get(path).status_code == 401
    assert client.post('/api/auth/login', json={'password': 'wrong'}).status_code == 401
    response = client.post('/api/auth/login', json={'password': 'a good test password'})
    assert response.status_code == 200
    cookie = response.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=strict' in cookie
    assert 'tv.js' in client.get('/').text
    assert client.get('/api/qr.svg?branded=true').status_code == 200
    assert client.get('/api/config').json()['remote_url'] == 'https://ktv.example.test/remote'
    assert runtime.access.key not in client.get('/api/config').text
    assert '#key=' + runtime.access.key in runtime.join_url()


def test_pair_is_reusable_but_cannot_take_player_role(external):
    runtime, app = external
    for _ in range(2):
        client = TestClient(app)
        assert client.post('/api/auth/pair', json={'key': runtime.access.key}).status_code == 200
        assert 'remote.js' in client.get('/remote').text
        assert 'login.js' in client.get('/tv').text
        assert client.get('/api/qr.svg').status_code == 401
        assert client.post('/api/queue', json={'id': 'aaaaaaaaaaa', 'artist': 'Artist', 'title': 'Song'}).status_code == 201
        with client.websocket_connect('/ws?role=tv', headers={'origin': 'http://testserver'}) as ws:
            assert ws.receive()['code'] == 4003
        with client.websocket_connect('/ws?role=remote', headers={'origin': 'http://testserver'}) as ws:
            assert ws.receive_json()['type'] == 'state'


def test_restart_revokes_qr_and_cookies(external):
    runtime, app = external
    client = TestClient(app)
    old_key = runtime.access.key
    client.post('/api/auth/login', json={'password': 'a good test password'})
    old_cookie = client.cookies.get('ktvibes_session')
    # Recreate a runtime just as a new server process does.
    replacement = Runtime(cache=runtime.cache)
    other = TestClient(create_app(replacement))
    other.cookies.set('ktvibes_session', old_cookie)
    assert other.get('/api/state').status_code == 401
    assert other.post('/api/auth/pair', json={'key': old_key}).status_code == 401
    assert replacement.access.key != old_key


def test_origin_and_desktop_scope(external):
    runtime, app = external
    client = TestClient(app)
    desktop = {'Authorization': 'Bearer desktop-secret'}
    assert client.get('/api/config', headers=desktop).status_code == 200
    assert client.get('/api/qr.svg', headers=desktop).status_code == 401
    assert client.post('/api/auth/login', json={'password': 'a good test password'}, headers={'origin': 'https://evil.test'}).status_code == 403
    client.post('/api/auth/login', json={'password': 'a good test password'})
    with client.websocket_connect('/ws?role=tv', headers={'origin': 'https://evil.test'}) as ws:
        assert ws.receive()['code'] == 4003
    with client.websocket_connect('/ws?role=tv', headers={'origin': 'http://testserver'}) as ws:
        assert ws.receive_json()['type'] == 'state'


def test_wrong_password_rate_limit(external):
    _, app = external
    client = TestClient(app)
    for _ in range(5):
        assert client.post('/api/auth/login', json={'password': 'wrong'}).status_code == 401
    response = client.post('/api/auth/login', json={'password': 'wrong'})
    assert response.status_code == 429
    assert response.headers['retry-after'] == '60'


@pytest.mark.parametrize('url', ['http://example.test', 'https://example.test/other', 'https://user:pass@example.test', 'https://example.test?key=secret'])
def test_invalid_external_config_fails_closed(encoded, url):
    with patch.dict('os.environ', {'KTVIBES_EXTERNAL_ENABLED': '1', 'KTVIBES_REMOTE_URL': url, 'KTVIBES_PASSWORD_HASH': encoded}):
        with pytest.raises(ValueError):
            Access()


def test_enabled_without_password_fails_closed():
    with patch.dict('os.environ', {'KTVIBES_EXTERNAL_ENABLED': '1', 'KTVIBES_REMOTE_URL': 'https://example.test', 'KTVIBES_PASSWORD_HASH': ''}):
        with pytest.raises(ValueError):
            Access()


def test_untrusted_credentials_do_not_crash(external):
    _, app = external
    client = TestClient(app)
    assert client.post('/api/auth/pair', json={'key': '不是有效的憑證'}).status_code == 401
    client.cookies.set('ktvibes_session', 'owner.invalid.' + 'g' * 64)
    assert client.get('/api/state').status_code == 401


def test_disabled_external_ignores_old_credentials():
    with patch.dict('os.environ', {'KTVIBES_EXTERNAL_ENABLED': '0', 'KTVIBES_REMOTE_URL': '', 'KTVIBES_PASSWORD_HASH': 'old-invalid-value'}):
        assert Access().key is None


def test_pin_validation_and_legacy_mode(external):
    runtime, app = external
    client = TestClient(app)
    assert client.get('/api/auth/status').json()['credential_type'] == 'password'
    runtime.access.credential_type = 'pin'
    runtime.access.encoded = password_hash('123456')
    for invalid in ('12345', 'abc123', '１２３４５６'):
        assert client.post('/api/auth/login', json={'password': invalid}).status_code == 400
    assert client.post('/api/auth/login', json={'password': '654321'}).json()['detail'] == 'Incorrect PIN.'
    assert client.post('/api/auth/login', json={'password': '123456'}).status_code == 200


def test_invite_has_same_key_as_qr_and_requires_owner(external):
    runtime, app = external
    client = TestClient(app)
    assert client.get('/api/invite').status_code == 401
    assert client.get('/api/invite', headers={'Authorization': 'Bearer desktop-secret'}).status_code == 401
    client.post('/api/auth/pair', json={'key': runtime.access.key})
    assert client.get('/api/invite').status_code == 401
    client.post('/api/auth/login', json={'password': 'a good test password'})
    response = client.get('/api/invite')
    assert response.json()['url'] == runtime.join_url()
    assert response.headers['cache-control'] == 'no-store'
