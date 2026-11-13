"""Recover real page state after WebSocket disconnects and server builds change."""

import pytest
from playwright.sync_api import expect


def open_role(remote, page, remote_url, role):
    connections = []

    def connected(socket):
        connections.append(socket)
        remote.websocket(socket)

    page.route_web_socket(f'**/ws?role={role}', connected)
    page.goto(remote_url if role == 'remote' else remote_url.replace('/remote', '/tv'))
    return connections


def current_title(page, role):
    return page.locator('#hero-title' if role == 'remote' else '#song-title')


@pytest.mark.parametrize('role', ['remote', 'tv'])
def test_disconnect_reconnect_restores_latest_queue_without_skipping(remote, page, remote_url, role):
    connections = open_role(remote, page, remote_url, role)
    expect(current_title(page, role)).to_have_text('Current Song')
    connections[-1].close(code=1011, reason='simulated server restart')
    connection = page.locator('#connection-label' if role == 'remote' else '#connection')
    expect(connection).to_have_text('Disconnected')
    remote.state['current'] = remote.state['upcoming'].pop(0)
    remote.state['upcoming'].reverse()
    # Poll through Playwright so the real 1.5-second reconnect timer can run.
    expect(current_title(page, role)).to_have_text('First Song')
    expect(connection).to_have_text('Ready' if role == 'remote' else 'Connected')
    rows = page.locator('#queue .queue-swipe' if role == 'remote' else '#on-deck li')
    expect(rows).to_have_count(2)
    expect(rows.first).to_have_attribute('data-key', 'three')
    assert len(connections) == 2
    assert not [command for command in remote.commands if command['action'] in ('ended', 'skip', 'remove', 'reorder')]


@pytest.mark.parametrize('role', ['remote', 'tv'])
def test_changed_server_build_reloads_once_and_restores_state(remote, page, remote_url, role):
    connections = open_role(remote, page, remote_url, role)
    expect(current_title(page, role)).to_have_text('Current Song')
    remote.state['build'] = 'updated-server-build'
    remote.state['current']['title'] = 'Song after update'
    with page.expect_navigation(wait_until='domcontentloaded'):
        remote.push()
    expect(current_title(page, role)).to_have_text('Song after update')
    rows = page.locator('#queue .queue-swipe' if role == 'remote' else '#on-deck li')
    expect(rows).to_have_count(3)
    remote.push()
    expect(current_title(page, role)).to_have_text('Song after update')
    assert len(connections) == 2
    assert not [command for command in remote.commands if command['action'] in ('ended', 'skip', 'remove')]
