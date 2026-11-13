"""Pronunciation guides must follow their word timing, including after seeking."""

import pytest
from playwright.sync_api import expect


@pytest.mark.parametrize('theme', ['default', 'classic'])
@pytest.mark.parametrize('grouped', [False, True])
def test_all_readings_wait_for_their_word(remote, page, remote_url, theme, grouped):
    page.set_viewport_size({'width': 1920, 'height': 1080})
    units = [
        ['春', 0, 1, 'haru', '하루', 'ceon1', 'はる', 'first' if grouped else None],
        ['泥', 2, 3 if grouped else 4, 'dorobou', '도로보', 'nai4', 'どろぼう', 'second' if grouped else None],
    ]
    if grouped:
        units.append(['棒', 3, 4, '', '', '', '', 'second'])
    remote.state.update(theme=theme, guide='latin', guides=['off', 'latin', 'jyutping', 'hangul', 'kana'], offset=.5)
    remote.state['current']['lyrics'] = [{'text': '春泥棒', 'start': 0, 'units': units}]
    page.route_web_socket('**/ws?role=tv', remote.websocket)
    page.goto(remote_url.replace('/remote', '/tv'))
    expect(page.locator('#lyrics .lyric.active')).to_have_count(1)

    for guide in ('latin', 'jyutping', 'hangul', 'kana'):
        remote.state.update(guide=guide, offset=.5)
        remote.push()
        reading = page.locator(f'#lyrics rt .{guide}').nth(1)
        expect(reading).to_be_visible()
        for offset, progress in ((.5, 0), (3, .5), (4, 1), (.5, 0)):
            remote.state['offset'] = offset
            remote.push()
            page.wait_for_function('''({guide,progress}) => {
                const reading=document.querySelectorAll(`#lyrics rt .${guide}`)[1];
                return Math.abs(parseFloat(getComputedStyle(reading).getPropertyValue('--p'))-progress)<.01;
            }''', arg={'guide': guide, 'progress': progress})
            style = reading.evaluate('el => {const s=getComputedStyle(el);return {color:s.color,background:s.backgroundImage,clip:s.backgroundClip}}')
            assert style['color'] == 'rgba(0, 0, 0, 0)'
            assert 'linear-gradient' in style['background']
            assert style['clip'] == 'text'
