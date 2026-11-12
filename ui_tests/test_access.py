"""Exercise the shipped access screen and credential exchange in both viewports."""
from pathlib import Path
from playwright.sync_api import expect

LOGIN = (Path(__file__).resolve().parents[1] / 'static/login.html').read_text()


def test_qr_sign_in_clears_key_before_exchange(remote, page, remote_url):
    authorized = False
    exchanges = []

    def entry(route):
        if authorized:
            route.continue_()
        else:
            route.fulfill(content_type='text/html', body=LOGIN)

    def pair(route):
        nonlocal authorized
        exchanges.append(route.request.post_data_json)
        assert '#' not in route.request.url
        assert '#key=' not in page.url
        authorized = True
        route.fulfill(json={'ok': True})

    page.route('**/remote', entry)
    page.route('**/api/auth/pair', pair)
    page.goto('about:blank')
    page.goto(remote_url + '#key=one-run-key')
    expect(page.locator('#hero')).to_be_visible()
    assert exchanges == [{'key': 'one-run-key'}]
    assert page.url == remote_url


def test_expired_qr_offers_password_and_recovers(remote, page, remote_url):
    authorized = False

    def entry(route):
        if authorized:
            route.continue_()
        else:
            route.fulfill(content_type='text/html', body=LOGIN)

    def login(route):
        nonlocal authorized
        if route.request.post_data_json['password'] == 'correct password':
            authorized = True
            route.fulfill(json={'ok': True})
        else:
            route.fulfill(status=401, json={'detail': 'Incorrect password.'})

    page.route('**/remote', entry)
    page.route('**/api/auth/pair', lambda route: route.fulfill(status=401, json={'detail': 'This QR code has expired.'}))
    page.route('**/api/auth/login', login)
    page.goto('about:blank')
    page.goto(remote_url + '#key=old-key')
    expect(page.locator('#message')).to_have_text('This QR code has expired.')
    page.locator('#password').fill('wrong')
    page.get_by_role('button', name='Continue').click()
    expect(page.locator('#message')).to_have_text('Incorrect password.')
    page.locator('#password').fill('correct password')
    page.get_by_role('button', name='Continue').click()
    expect(page.locator('#hero')).to_be_visible()


def test_pin_keypad_and_physical_input(remote, page, remote_url):
    page.route('**/api/auth/status', lambda route: route.fulfill(json={'credential_type': 'pin'}))
    page.route('**/remote', lambda route: route.fulfill(content_type='text/html', body=LOGIN))
    values = []
    def login(route):
        values.append(route.request.post_data_json['password'])
        route.fulfill(status=401, json={'detail': 'Incorrect PIN.'})
    page.route('**/api/auth/login', login)
    page.goto('about:blank'); page.goto(remote_url)
    expect(page.get_by_label('PIN', exact=True)).to_be_visible()
    expect(page.locator('h2')).to_have_count(0)
    for digit in '123457':
        page.get_by_role('button', name=digit, exact=True).click()
    page.get_by_role('button', name='Backspace').click()
    page.get_by_role('button', name='6', exact=True).click()
    page.get_by_role('button', name='Continue').click()
    expect(page.locator('#message')).to_have_text('Incorrect PIN.')
    assert values == ['123456']
    page.locator('#password').fill('12345')
    page.get_by_role('button', name='Continue').click()
    assert values == ['123456']
    page.locator('#password').fill('654321')
    page.get_by_role('button', name='Continue').click()
    expect(page.get_by_role('button', name='Continue')).to_be_enabled()
    assert values[-1] == '654321'
