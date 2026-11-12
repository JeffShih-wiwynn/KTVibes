"""A new build must bypass cached entry points and their module dependencies."""
from fastapi.testclient import TestClient
from ktvibes.application import create_app
from ktvibes.runtime import Runtime


def test_versioned_player_remote_and_relative_imports(tmp_path):
    runtime = Runtime(cache=tmp_path)
    client = TestClient(create_app(runtime))
    for page, entry in (('/', 'tv.js'), ('/tv', 'tv.js'), ('/remote', 'remote.js')):
        response = client.get(page)
        assert response.headers['cache-control'] == 'no-store'
        assert f'/static/{runtime.asset_version}/{entry}' in response.text
        assert f'/static/{runtime.asset_version}/' in response.text
    source = client.get(f'/static/{runtime.asset_version}/tv.js')
    assert source.status_code == 200
    assert "from './tv-invite.js'" in source.text
    assert client.get(f'/static/{runtime.asset_version}/tv-invite.js').status_code == 200
    assert client.get(f'/static/{runtime.asset_version}/style.css').status_code == 200
    assert client.get('/static/tv.js').status_code == 200


def test_asset_content_changes_version(tmp_path):
    static = tmp_path / 'static'; static.mkdir()
    (static / 'tv.js').write_text('old')
    runtime = Runtime(root=tmp_path, cache=tmp_path / 'cache')
    first = runtime.build()
    (static / 'tv.js').write_text('new')
    assert runtime.build() != first
