import re
from playwright.sync_api import expect


def test_tv_invite_short_label_and_copy_fallback(remote, page, remote_url):
    url = 'https://ktv.example.test/remote#key=current-key'
    page.route('**/api/invite', lambda route: route.fulfill(json={'url': url}))
    page.route_web_socket('**/ws?role=tv', remote.websocket)
    page.add_init_script("""Object.defineProperty(navigator, 'clipboard', {value:{writeText:async value=>window.copied=value}});Object.defineProperty(navigator, 'share', {value:undefined});""")
    page.goto(remote_url.replace('/remote', '/tv'))
    remote.state['current'] = None
    remote.state['upcoming'] = []
    remote.push()
    page.evaluate("document.getElementById('enable').hidden=true")
    link = page.locator('#remote-url a')
    expect(link).to_have_attribute('href', url)
    expect(link).not_to_have_text(re.compile('key='))
    page.get_by_role('button', name='Copy invite link').click()
    expect(page.locator('.invite-notice')).to_have_text('Link copied')
    assert page.evaluate('window.copied') == url
    page.evaluate('window.copied=null')
    page.get_by_role('button', name='Share invite link').click()
    expect(page.locator('.invite-notice')).to_have_text('Link copied')
    assert page.evaluate('window.copied') == url


def test_tv_invite_retries_transient_failure(remote, page, remote_url):
    attempts = []
    url = 'https://ktv.example.test/remote#key=retry-key'
    def invite(route):
        attempts.append(1)
        if len(attempts) == 1:
            route.fulfill(status=503, json={'detail': 'Unavailable'})
        else:
            route.fulfill(json={'url': url})
    page.route('**/api/invite', invite)
    page.route_web_socket('**/ws?role=tv', remote.websocket)
    page.clock.install()
    page.goto(remote_url.replace('/remote', '/tv'))
    expect(page.locator('.invite-notice')).to_have_text('Invite unavailable')
    expect(page.locator('#remote-url a')).not_to_have_attribute('href', url)
    page.clock.run_for(5100)
    expect(page.locator('#remote-url a')).to_have_attribute('href', url)
    assert len(attempts) == 2


def test_external_address_keeps_invite_actions_in_view(remote, page, remote_url):
    address = 'https://ktvibesmac.masatoserver.com/remote'
    page.route('**/api/config', lambda route: route.fulfill(json={'remote_url': address}))
    page.route('**/api/invite', lambda route: route.fulfill(json={'url': address + '#key=current-key'}))
    page.route_web_socket('**/ws?role=tv', remote.websocket)
    page.goto(remote_url.replace('/remote', '/tv'))
    remote.state.update(current=None, upcoming=[])
    remote.push()
    page.evaluate("document.getElementById('enable').hidden=true")
    expect(page.locator('#remote-url a')).to_have_text(address)
    for name in ('Copy invite link', 'Share invite link'):
        button = page.get_by_role('button', name=name)
        expect(button).to_be_visible()
        box = button.bounding_box()
        assert 0 <= box['x'] and box['x'] + box['width'] <= page.viewport_size['width'], box
        assert 0 <= box['y'] and box['y'] + box['height'] <= page.viewport_size['height'], box
