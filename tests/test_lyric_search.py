"""Search timing quality must not outrank a different song or artist."""
import httpx
import pytest
from ktvibes import lyrics

ENHANCED = '[00:01.00]<00:01.00>Hello <00:02.00>world<00:03.00>'


@pytest.mark.parametrize('raw,expected', [
    (ENHANCED, True),
    ('[00:01.00]<00:01.00>Hello<00:02.00> <00:02.50>world<00:03.00>', True), ('[00:01.00]Hello world', False),
    ('Hello <00:01.00>world', False), ('[00:01.00]<00:01.00>  <00:02.00>', False),
    ('[00:01.00]<00:03.00>Hello<00:02.00>world<00:01.00>', False),
    ('[00:01.00][00:05.00]<00:01.00>Hello<00:02.00>', False),
    ('[00:00.00]Intro\n' + ENHANCED, True),
])
def test_enhanced_requires_parsed_usable_word_timing(raw, expected):
    assert bool(lyrics.enhanced_sync(raw)) is expected


async def test_search_ranks_identity_then_quality_then_duration_and_keeps_all_versions(monkeypatch):
    def record(identifier, *, duration=240, title='Song', artist='Artist', synced=None, plain='words'):
        return dict(id=identifier, trackName=title, artistName=artist, duration=duration,
                    syncedLyrics=synced, plainLyrics=plain)
    records = [
        record(1, duration=242, synced=ENHANCED),
        record(2, duration=241, synced=ENHANCED, plain=None),
        record(3, duration=240, synced='[00:01.00]Hello world'),
        record(4), record(5, duration=239),
        record(6, title='Another Song', synced=ENHANCED),
        record(7, artist='Other Artist', synced=ENHANCED),
        record(8, duration=None, synced=ENHANCED),
        record(9, duration=300, synced=ENHANCED),
        record(10, synced=None, plain=''),
    ]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=list(reversed(records)) + [records[0]]))
    monkeypatch.setattr(lyrics, 'lrclib', lambda: httpx.AsyncClient(transport=transport, base_url='https://lyrics.test'))
    found = await lyrics.mixed_search('Song', 'Artist', 'Song', 240)
    assert [r['id'] for r in found] == [2, 1, 9, 8, 3, 4, 5, 7, 6]
    assert len([r for r in found if r['id'] == 1]) == 1
    assert found[1]['plainLyrics'] == 'words'
