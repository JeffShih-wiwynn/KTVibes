"""Check Remote layout boundaries with long content and responsive columns."""

import pytest
from playwright.sync_api import expect


LONG_TITLE = '月と私のかくれんぼ Official Music Video ' * 8 + 'VeryLongUnbrokenTitle' * 8


def horizontal_bounds(element, width):
    box = element.bounding_box()
    assert box is not None
    assert box['x'] >= -1, box
    assert box['x'] + box['width'] <= width + 1, box
    return box


@pytest.mark.parametrize('width', [360, 959, 960, 1440])
def test_remote_long_content_stays_inside_columns(remote, page, width):
    page.set_viewport_size({'width': width, 'height': 900})
    requester = {'id': 'a' * 32, 'name': 'LongGuest名', 'avatar': None}
    remote.state['current'].update(title=LONG_TITLE, artist=LONG_TITLE, requester=requester)
    for item in remote.state['upcoming']:
        item.update(title=LONG_TITLE, artist=LONG_TITLE, requester=requester)
    remote.recent[0].update(title=LONG_TITLE, artist=LONG_TITLE)
    page.reload()
    expect(page.locator('#hero-title')).to_have_text(LONG_TITLE)
    expect(page.locator('#queue .row')).to_have_count(3)

    for selector in ('#search-form', '#hero', '#queue', '#recent', '#hero-play', '#skip', '#open-controls'):
        horizontal_bounds(page.locator(selector), width)
    for row in page.locator('#queue .row').all():
        bounds = horizontal_bounds(row, width)
        info = row.locator('.info').bounding_box()
        assert info['x'] >= bounds['x']
        assert info['x'] + info['width'] <= bounds['x'] + bounds['width'] + 1
        assert row.locator('h3').evaluate('el => el.scrollWidth > el.clientWidth && getComputedStyle(el).textOverflow === "ellipsis"')

    browse = page.locator('.browse-column').bounding_box()
    play = page.locator('.play-column').bounding_box()
    if width >= 960:
        assert browse['x'] + browse['width'] <= play['x']
    else:
        search = page.locator('#search-form').bounding_box()
        hero = page.locator('#hero').bounding_box()
        assert search['y'] + search['height'] <= hero['y']

    page.locator('#query').fill('song')
    page.locator('#search-button').click()
    expect(page.locator('#results .result')).to_have_count(1)
    horizontal_bounds(page.locator('#results .result'), width)
    add = page.locator('#results .result-add')
    horizontal_bounds(add, width)
    info = page.locator('#results .result-info').bounding_box()
    button = add.bounding_box()
    assert info['x'] + info['width'] <= button['x'] + 1
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')


def test_remote_panels_fit_the_viewport_with_long_song(remote, page):
    width, height = page.viewport_size['width'], page.viewport_size['height']
    remote.state['current'].update(title=LONG_TITLE, artist=LONG_TITLE)
    remote.push()
    expect(page.locator('#hero-title')).to_have_text(LONG_TITLE)
    page.locator('#open-controls').click()
    expect(page.locator('body')).to_have_class('sheet-open')
    page.wait_for_function("document.querySelector('#sheet').getBoundingClientRect().bottom <= innerHeight + 1")
    box = horizontal_bounds(page.locator('#sheet'), width)
    assert box['y'] >= -1 and box['y'] + box['height'] <= height + 1
    page.locator('#sheet-handle').click()
    expect(page.locator('body')).not_to_have_class('sheet-open')
    page.locator('#hero-lyrics').click()
    expect(page.locator('.lyric-reader')).to_contain_text('風が呼んでいる')
    panel = page.locator('.lyric-sheet-panel')
    expect(panel).to_be_visible()
    page.wait_for_function("document.querySelector('.lyric-sheet-panel').getBoundingClientRect().bottom <= innerHeight + 1")
    box = horizontal_bounds(panel, width)
    assert box['y'] >= -1 and box['y'] + box['height'] <= height + 1
    assert panel.evaluate('el => el.scrollWidth <= el.clientWidth + 1')
