"""Guard the Player layout against queue growth and cropped song cards."""

import re
import time

import pytest
from playwright.sync_api import expect


def within_screen(box, width, height):
    assert box is not None
    assert box['x'] >= -1, box
    assert box['y'] >= -1, box
    assert box['x'] + box['width'] <= width + 1, box
    assert box['y'] + box['height'] <= height + 1, box


@pytest.mark.parametrize('width,height', [(1920, 1080), (1280, 720)])
def test_default_player_layout_with_growing_queue(remote, page, remote_url, width, height):
    page.set_viewport_size({'width': width, 'height': height})
    remote.state['current'].update(
        title='月と私のかくれんぼ Official Music Video ' * 8,
        lyrics=[{'text': 'た だ 花 が 降 る だ け', 'start': 0},
                {'text': '春 泥 棒', 'start': 2}],
    )
    queued = [dict(remote.state['upcoming'][0], key=f'queued-{i}',
                   title='月と私のかくれんぼ Official Music Video ' * 8,
                   requester={'id': 'a' * 32, 'name': 'Guest', 'avatar': None})
              for i in range(5)]
    page.route_web_socket('**/ws?role=tv', remote.websocket)
    page.goto(remote_url.replace('/remote', '/tv'))

    baseline = None
    for count in (0, 1, 5):
        remote.state['upcoming'] = queued[:count]
        remote.push()
        expect(page.locator('#on-deck li')).to_have_count(max(count, 1))
        expect(page.locator('#lyrics .lyric.shown')).to_have_count(2)
        stage = page.locator('.stage').bounding_box()
        performance = page.locator('#performance').bounding_box()
        positions = (stage['y'], performance['y'])
        if baseline is None:
            baseline = positions
        else:
            assert all(abs(a - b) <= 1 for a, b in zip(positions, baseline)), (baseline, positions)
        for slot in (0, 1):
            within_screen(page.locator(f'#lyrics .lyric.shown[data-slot="{slot}"]').bounding_box(), width, height)

    title = page.locator('#on-deck .on-deck-song').first
    assert title.evaluate('el => el.scrollWidth > el.clientWidth && getComputedStyle(el).textOverflow === "ellipsis"')
    current = page.locator('.now-songline').bounding_box()
    queue = page.locator('.top-queue').bounding_box()
    assert current['x'] + current['width'] + 12 <= queue['x']

    remote.state['transition_until'] = time.time() + 30
    remote.state['server_time'] = time.time()
    remote.push()
    expect(page.locator('body')).to_have_class(re.compile(r'\bbetween\b'))
    expect(page.locator('#up-next')).to_be_visible()
    expect(page.locator('.top-queue')).to_have_css('opacity', '0')
    page.locator('.next-card').evaluate('el => el.getAnimations().forEach(animation => animation.finish())')
    for selector in ('.next-card', '.next-art', '.countdown', '#peek-1', '#peek-2'):
        element = page.locator(selector)
        expect(element).to_be_visible()
        within_screen(element.bounding_box(), width, height)
    card = page.locator('.next-card').bounding_box()
    assert abs(card['x'] + card['width'] / 2 - width / 2) <= 2, card


def test_classic_player_keeps_reservation_board(remote, page, remote_url):
    remote.state['theme'] = 'classic'
    remote.state['transition_until'] = time.time() + 30
    remote.state['server_time'] = time.time()
    page.route_web_socket('**/ws?role=tv', remote.websocket)
    page.goto(remote_url.replace('/remote', '/tv'))
    expect(page.locator('#up-next .board')).to_be_visible()
    expect(page.locator('#up-next .next-stack')).to_be_hidden()
