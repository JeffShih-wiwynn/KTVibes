"""One preview per record; format buttons name the preview, not the next version."""
import pytest
from playwright.sync_api import expect


def choice(*, synced=True, enhanced=False, plain=True, current=False):
    return dict(id=42, track='Fixture Lyrics', artist='Test Artist', album='Album', difference=-2,
                formats=dict(synced=dict(available=synced, enhanced=enhanced, current=current,
                                         preview=['同步第一行', '同步第二行']),
                             plain=dict(available=plain, selected=False, active=False,
                                        preview=['純文字第一行', '純文字第二行'])))


def open_card(remote, page, data):
    page.route('**/api/lyrics/choices/**', lambda route: route.fulfill(json={'results': [data]}))
    if remote.state['theme'] == 'classic':
        page.locator('#tabs [data-tab=queue]').click()
    page.locator('#hero-lyrics').click()
    page.get_by_role('button', name='Select Lyrics', exact=True).click()
    card = page.locator('.lyric-option')
    expect(card).to_have_count(1)
    return card


@pytest.mark.parametrize('theme', ['default', 'classic'])
@pytest.mark.parametrize('synced,enhanced,plain', [
    (True, True, True), (True, False, True),
    (True, True, False), (True, False, False), (False, False, True),
])
def test_all_format_combinations_use_one_preview_and_current_format_button(remote, page, theme, synced, enhanced, plain):
    remote.state['theme'] = theme
    remote.push()
    expect(page.locator('body')).to_have_attribute('data-theme', theme)
    card = open_card(remote, page, choice(synced=synced, enhanced=enhanced, plain=plain))
    name = 'Enhanced Sync' if enhanced else 'Sync' if synced else 'Plain'
    tags = ([name] if synced else []) + (['Plain'] if plain else []) + ['2s shorter']
    expect(card.locator('.lyric-format')).to_have_text(tags)
    expect(card.locator('.lyric-format.active')).to_have_text(name)
    expect(card.locator('.lyric-format-preview')).to_have_count(1)
    expect(card.locator('.lyric-format-preview small')).to_have_text(
        ['同步第一行', '同步第二行'] if synced else ['純文字第一行', '純文字第二行'])
    toggle, select = card.locator('.lyric-version'), card.locator('.lyric-select')
    expect(toggle).to_have_text(name)
    expect(select).to_have_text('Select')
    expect(select).to_be_enabled()
    if synced and plain:
        expect(toggle).to_be_enabled()
        toggle.click()
        expect(toggle).to_have_text('Plain')
        expect(card.locator('.lyric-format.active')).to_have_text('Plain')
        expect(card.locator('.lyric-format-preview small')).to_have_text(['純文字第一行', '純文字第二行'])
        expect(card.locator('.lyric-format')).to_have_text(tags)
        toggle.click()
        expect(toggle).to_have_text(name)
        expect(card.locator('.lyric-format-preview small')).to_have_text(['同步第一行', '同步第二行'])
    else:
        expect(toggle).to_be_disabled()
        expect(toggle).to_have_css('filter', 'grayscale(1)')
    # Both buttons occupy opposite ends of the same action row, including on phones.
    left, right = toggle.bounding_box(), select.bounding_box()
    assert abs(left['y'] - right['y']) <= 1
    assert left['x'] + left['width'] < right['x']
    assert card.evaluate('el=>el.scrollWidth<=el.clientWidth+1')


@pytest.mark.parametrize('kind', ['synced', 'plain'])
def test_select_applies_previewed_format_and_retains_existing_selection(remote, page, kind):
    card = open_card(remote, page, choice(enhanced=True, current=(kind == 'plain')))
    if kind == 'plain':
        expect(card.locator('.lyric-select')).to_have_text('Selected')
        expect(card.locator('.lyric-select')).to_be_disabled()
        card.locator('.lyric-version').click()
        expect(card.locator('.lyric-select')).to_have_text('Select')
    card.locator('.lyric-select').click()
    expect(page.locator('.lyric-view-status')).to_have_text('Plain lyrics' if kind == 'plain' else 'Synced lyrics')
    posts = [(path, body) for method, path, body in remote.requests if method == 'POST']
    assert posts[-1] == ('/api/lyrics/plain/current' if kind == 'plain' else '/api/songs/aaaaaaaaaaa/lyrics', {'id': 42})


def test_failed_selection_does_not_enable_a_single_format_switch(remote, page):
    card = open_card(remote, page, choice(plain=False))
    page.route('**/api/songs/*/lyrics', lambda route: route.fulfill(status=503, json={'detail': 'Try again'}))
    card.locator('.lyric-select').click()
    expect(card.locator('.lyric-select')).to_be_enabled()
    expect(card.locator('.lyric-version')).to_be_disabled()
    expect(card.locator('.lyric-version')).to_have_text('Sync')


@pytest.mark.parametrize('theme', ['default', 'classic'])
def test_animated_preview_keeps_width_and_interpolates_height(remote, page, theme):
    page.emulate_media(reduced_motion='no-preference')
    remote.state['theme'] = theme
    remote.push()
    expect(page.locator('body')).to_have_attribute('data-theme', theme)
    data = choice(enhanced=True)
    data['formats']['plain']['preview'] = ['longer plain lyrics ' * 25, 'second line ' * 20]
    card = open_card(remote, page, data)
    before = card.locator('.lyric-version').bounding_box()['width']
    state = card.evaluate('''card=>{
      card.querySelector('.lyric-version').click();
      const block=card.querySelector('.lyric-card-preview');
      for(const a of card.getAnimations({subtree:true}))a.pause();
      const height=block.getAnimations()[0],frames=height.effect.getKeyframes();
      height.currentTime=110;
      return {from:parseFloat(frames[0].height),to:parseFloat(frames.at(-1).height),
        middle:block.getBoundingClientRect().height,duration:height.effect.getTiming().duration};
    }''')
    assert state['duration'] == 220
    assert state['from'] < state['middle'] < state['to']
    assert abs(card.locator('.lyric-version').bounding_box()['width'] - before) <= 1
    expect(card.locator('.lyric-version')).to_have_text('Plain')
    expect(card.locator('.lyric-preview-outgoing')).to_have_attribute('aria-hidden', 'true')
    card.evaluate('card=>card.getAnimations({subtree:true}).forEach(a=>a.finish())')
    expect(card.locator('.lyric-preview-outgoing')).to_have_count(0)
    assert card.locator('.lyric-card-preview').evaluate('el=>el.style.height') == ''
    assert abs(card.locator('.lyric-card-preview').bounding_box()['height'] - state['to']) <= 1


def test_identical_previews_preserve_nodes_without_text_animation(remote, page):
    page.emulate_media(reduced_motion='no-preference')
    data = choice(enhanced=True)
    data['formats']['plain']['preview'] = data['formats']['synced']['preview']
    card = open_card(remote, page, data)
    assert card.evaluate('''card=>{
      const reading=card.querySelector('.lyric-format-preview'),word=reading.firstChild;
      card.querySelector('.lyric-version').click();
      return reading.firstChild===word && !reading.getAnimations().length
        && !card.querySelector('.lyric-preview-outgoing');
    }''')
    expect(card.locator('.lyric-version')).to_have_text('Plain')
    expect(card.locator('.lyric-format.active')).to_have_text('Plain')


def test_rapid_animated_switches_apply_the_latest_version(remote, page):
    page.emulate_media(reduced_motion='no-preference')
    card = open_card(remote, page, choice(enhanced=True))
    card.evaluate('card=>{for(let i=0;i<5;i++)card.querySelector(".lyric-version").click()}')
    expect(card.locator('.lyric-version')).to_have_text('Plain')
    expect(card.locator('.lyric-format-preview small')).to_have_text(['純文字第一行', '純文字第二行'])
    expect(card.locator('.lyric-preview-outgoing')).to_have_count(1)
    card.locator('.lyric-select').click()
    expect(page.locator('.lyric-view-status')).to_have_text('Plain lyrics')
    assert ('POST', '/api/lyrics/plain/current', {'id': 42}) in remote.requests


@pytest.mark.parametrize('action', ['close', 'search', 'song'])
def test_animated_previews_are_cleaned_up_when_card_is_replaced(remote, page, action):
    page.emulate_media(reduced_motion='no-preference')
    card = open_card(remote, page, choice(enhanced=True))
    card.evaluate('''card=>{
      window.oldLyricCard=card;
      card.querySelector('.lyric-version').click();
      card.getAnimations({subtree:true}).forEach(a=>a.pause());
    }''')
    if action == 'close':
        page.get_by_role('button', name='Close Lyrics panel').click()
        expect(page.locator('.lyric-sheet')).to_have_count(0)
    elif action == 'search':
        page.locator('.lyric-search').evaluate('form=>form.requestSubmit()')
        expect(page.locator('.lyric-option')).to_have_attribute('data-preview-format', 'synced')
    else:
        remote.state['current'] = remote.state['upcoming'].pop(0)
        remote.push()
        expect(page.locator('#hero-title')).to_have_text('First Song')
        expect(page.locator('.lyric-option')).to_have_attribute('data-preview-format', 'synced')
    assert page.evaluate('oldLyricCard.getAnimations({subtree:true}).length') == 0
    assert page.evaluate('oldLyricCard.querySelectorAll(".lyric-preview-outgoing").length') == 0


def test_reduced_motion_switch_is_immediate(remote, page):
    card = open_card(remote, page, choice(enhanced=True))
    card.locator('.lyric-version').click()
    expect(card.locator('.lyric-version')).to_have_text('Plain')
    assert card.evaluate('card=>card.getAnimations({subtree:true}).length') == 0
    expect(card.locator('.lyric-preview-outgoing')).to_have_count(0)
    assert card.locator('.lyric-card-preview').evaluate('el=>el.style.height') == ''
