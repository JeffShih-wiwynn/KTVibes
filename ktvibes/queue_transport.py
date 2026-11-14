"""State publication, slow-client eviction and TV lyric delivery."""
import asyncio
import time

async def broadcast(state, persist=True):
    async with state.broadcast_lock:
        state.revision += 1
        if persist:
            try:
                state.save()
                state.saved_at = time.monotonic()
            except OSError:
                pass  # a full disk should not stop the party
        message = {"type": "state", **state.snapshot(lyrics=False)}
        key = state.current and state.current["key"]
        async def deliver(ws):
            # A TV gets the current song's lyrics once per song (and again after reconnecting).
            out = message
            if key and state.clients.get(ws) == "tv" and state.lyrics_sent.get(ws) != key:
                out = {**message, "current": {**message["current"], "lyrics": state.current["lyrics"]}}
            if await state.send(ws, out):
                state.lyrics_sent[ws] = key
        await asyncio.gather(*(deliver(ws) for ws in list(state.clients)))


async def send(state, ws, message):
    """Send to one client; a socket that can't take it within 2 s is dropped."""
    try:
        await asyncio.wait_for(ws.send_json(message), timeout=2)
        return True
    except Exception:
        state.disconnect(ws)
        return False


def disconnect(state, ws):
    state.clients.pop(ws, None)
    state.lyrics_sent.pop(ws, None)
    if state.player is ws:
        state.intro_pending = None
        state.next_pending = False
        state.player = None
        state.audio = False
