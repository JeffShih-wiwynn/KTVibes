from unittest.mock import AsyncMock
import pytest
from ktvibes.sections import boundaries
from ktvibes.queue import State


def timed_song():
    return dict(key="song", duration=120, lyrics_status="ready",
                lyrics=[dict(text="first", units=[["first", 20, 22]]),
                        dict(text="last", units=[["last", 90, 94]])])


def test_boundaries_follow_sung_words_and_offset():
    item = timed_song()
    assert boundaries(item) == {"intro": 15, "outro": 94}
    assert boundaries(item, 2) == {"intro": 13, "outro": 92}
    item["lyrics"][0]["units"][0][1] = 2
    assert boundaries(item)["intro"] == 0


@pytest.mark.parametrize("change", [
    {"lyrics_status": "missing"}, {"lyrics": []},
    {"lyrics": [{"text": "line only", "t": 20}]},
    {"lyrics": [{"units": [["bad", 10, float("nan")]]}]},
    {"lyrics": [{"units": [["bad", 10, 121]]}]},
])
def test_missing_or_invalid_timing_disables_skipping(change):
    assert boundaries({**timed_song(), **change}) is None


@pytest.mark.asyncio
async def test_manual_skips_are_keyed_guarded_and_do_not_auto_advance():
    state = State()
    state.current = timed_song()
    state.player = object()
    state.broadcast = AsyncMock()
    state.send = AsyncMock()
    assert state.snapshot()["sections"] == {"intro": 15, "outro": 94}
    await state.control({"action": "skip_intro", "key": "stale"})
    assert state.position == 0
    await state.control({"action": "skip_intro", "key": "song"})
    assert state.position == 0 and state.intro_pending == 15
    await state.control({"action": "skip_intro", "key": "song"})
    assert state.seek_id == 0
    await state.control({"action": "intro_seek", "key": "song"})
    assert state.position == 0
    await state.control({"action": "intro_seek", "key": "song"}, state.player)
    assert state.position == 15 and state.intro_pending == 15
    await state.control({"action": "skip_next", "key": "song"})
    assert not state.next_pending
    await state.control({"action": "intro_complete", "key": "song"}, state.player)
    await state.control({"action": "skip_next", "key": "song"})
    assert state.next_pending and state.current["key"] == "song"
    assert state.send.call_args.args[1] == {"type": "section_skip", "key": "song", "kind": "next"}
    calls = state.send.call_count
    await state.control({"action": "skip_next", "key": "song"})
    assert state.send.call_count == calls
    await state.control({"action": "skip_complete", "key": "stale"}, state.player)
    assert state.current is not None
    await state.control({"action": "skip_complete", "key": "song"}, state.player)
    assert state.current is None and state.position == 0


def test_zero_duration_syllables_and_punctuation_do_not_hide_controls():
    item = timed_song()
    item["lyrics"][0]["units"] = [["(", 20, 20], ["き", 20, 21], ["み", 21, 21], [")", 22, 22]]
    assert boundaries(item) == {"intro": 15, "outro": 94}


def test_entirely_zero_duration_or_reversed_timing_is_unavailable():
    item = timed_song()
    item["lyrics"] = [{"units": [["word", 20, 20]]}]
    assert boundaries(item) is None
    item["lyrics"] = [{"units": [["word", 22, 20]]}]
    assert boundaries(item) is None


@pytest.mark.asyncio
async def test_section_skips_are_rejected_during_next_song_countdown():
    import time
    state = State()
    state.current = timed_song()
    state.player = object()
    state.broadcast = AsyncMock()
    state.send = AsyncMock()
    state.transition_until = time.time() + 8
    for action, position in (("skip_intro", 0), ("skip_next", 95)):
        state.position = position
        await state.control({"action": action, "key": "song"})
    state.send.assert_not_called()
    assert state.intro_pending is None and not state.next_pending


@pytest.mark.asyncio
async def test_next_song_fades_even_without_lyrics_and_cannot_be_completed_by_remote():
    state = State()
    state.current = {**timed_song(), "lyrics": [], "lyrics_status": "missing"}
    state.player = object()
    state.broadcast = AsyncMock()
    state.send = AsyncMock()
    await state.control({"action": "skip_next", "key": "song"})
    assert state.next_pending and state.current is not None
    await state.control({"action": "skip_complete", "key": "song"})
    assert state.current is not None
    await state.control({"action": "skip_complete", "key": "song"}, state.player)
    assert state.current is None
