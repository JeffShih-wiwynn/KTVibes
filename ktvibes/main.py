import asyncio
from contextlib import asynccontextmanager, suppress
import io
import json
import os
import shutil
from pathlib import Path
import socket
import math
import qrcode
import qrcode.image.svg
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from .queue import State
from . import lyrics, songbook, stems, worker, youtube

ROOT = Path(__file__).resolve().parent.parent
CACHE = Path(os.environ.get("KTVIBES_CACHE", ROOT / "cache"))
PORT = int(os.environ.get("KTVIBES_PORT", 8765))
state = State()

@asynccontextmanager
async def lifespan(app):
    CACHE.mkdir(parents=True, exist_ok=True)
    state.build = build()
    await asyncio.to_thread(songbook.backfill, CACHE, stems.prepared)  # caches from before the songbook
    state.restore(CACHE / "queue.json", seed=lambda: {id: meta["prepared"] for id, meta in prepared_songs().items()})
    task = asyncio.create_task(worker.run(state, CACHE))
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

def build() -> str:
    """Fingerprint of the files the pages load. A TV left open across an update reloads itself
    instead of running old code against the new server."""
    import hashlib
    digest = hashlib.sha256()
    for path in sorted((ROOT / "static").rglob("*")):
        if path.is_file():
            digest.update(path.name.encode() + path.read_bytes())
    return digest.hexdigest()[:12]

app = FastAPI(title="KTVibes", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

@app.middleware("http")
async def revalidate_static(request, call_next):
    # Pages load plain JS/CSS without a build step; revalidate so edits show up on reload.
    # Media too: a song's tracks keep their URL when converted to a new format or prepared again.
    response = await call_next(request)
    if request.url.path.startswith(("/static/", "/media/")) or request.url.path in ("/", "/tv", "/remote"):
        response.headers["Cache-Control"] = "no-cache"
    return response

# The TV is the front page: someone on a laptop can open the remote from it, but not the other way round.
@app.get("/")
@app.get("/tv")
async def tv():
    return FileResponse(ROOT / "static/tv.html")

@app.get("/remote")
async def remote():
    return FileResponse(ROOT / "static/remote.html")

@app.get("/api/state")
async def get_state():
    return state.snapshot()

@app.get("/api/suggest")
async def suggest(q: str = Query(min_length=1, max_length=200)):
    try:
        return await asyncio.to_thread(youtube.suggest, q)
    except Exception:
        return []  # completions are a nicety; never surface their failures

@app.get("/api/search")
async def search(q: str = Query(min_length=1, max_length=200), page: int = Query(0, ge=0, le=9)):
    try:
        results = await asyncio.to_thread(youtube.search, q, page)
    except Exception as exc:
        raise HTTPException(502, f"YouTube search failed: {youtube.explain(exc)}") from exc
    # Prepared songs start right away; the remote marks them.
    cached = prepared_songs()
    return [{**result, "cached": result["id"] in cached} for result in results]

class Song(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    artist: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=300)

    @field_validator("artist", "title")
    @classmethod
    def nonempty(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Artist and title must not be blank")
        return value

def prepared_songs() -> dict:
    """Cached songs with stems and confirmed details, by video id."""
    songs = {}
    for meta_path in CACHE.glob("*/meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            prepared = meta_path.stat().st_mtime
        except (OSError, ValueError):
            continue
        video_id = meta_path.parent.name
        if youtube.ID.fullmatch(video_id) and meta.get("artist") and meta.get("title") and stems.prepared(meta_path.parent):
            songs[video_id] = {"id": video_id, "artist": meta["artist"], "title": meta["title"], "duration": meta.get("duration"),
                               "thumbnail": f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg", "prepared": prepared, "number": meta.get("number")}
    return songs

@app.get("/api/recent")
async def recent(limit: int = Query(20, ge=1, le=50)):
    """Songs that went on stage, most recent first, so the remote can re-queue them without a search."""
    songs = prepared_songs()
    played = sorted((when, video_id) for video_id, when in state.played.items() if video_id in songs)
    return [{k: v for k, v in songs[video_id].items() if k != "prepared"} for _, video_id in reversed(played[-limit:])]

@app.get("/api/songbook")
async def songbook_list():
    """Prepared songs by songbook number, for the remote's keypad and songbook (with when each was prepared, for 신곡)."""
    return sorted((s for s in prepared_songs().values() if s.get("number")), key=lambda s: s["number"])

@app.get("/api/ambient")
async def ambient():
    """Cached music videos the TV loops, muted, behind an empty stage: only songs that were prepared,
    so a video left behind by a failed download never shows up between songs."""
    return sorted(path.parent.name for path in CACHE.glob("*/video.mp4") if youtube.ID.fullmatch(path.parent.name) and stems.prepared(path.parent))

def song_meta(video_id: str) -> tuple[Path, dict]:
    folder = CACHE / video_id
    if not youtube.ID.fullmatch(video_id) or not (folder / "meta.json").is_file():
        raise HTTPException(404, "Song not found")
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    if not meta.get("artist") or not meta.get("title") or not meta.get("duration"):
        raise HTTPException(409, "This song isn't fully prepared yet")
    return folder, meta

@app.get("/api/songs/{video_id}/lyrics")
async def lyric_options(video_id: str, q: str = Query("", max_length=200)):
    """Every LRCLIB version that fits the song, best first, so the remote can pick a language or edition.
    With `q`, a free-text search instead, for songs the automatic lookup missed or got wrong."""
    folder, meta = song_meta(video_id)
    current = (folder / "lyrics.lrc").read_text(encoding="utf-8") if (folder / "lyrics.lrc").is_file() else ""
    try:
        found = await (lyrics.search(q.strip(), meta["duration"]) if q.strip() else
                       lyrics.candidates(meta["artist"], meta["title"], meta["duration"], (meta.get("source_title") or "",), exhaustive=True))
    except Exception as exc:
        raise HTTPException(502, f"Lyrics lookup failed: {exc}") from exc
    saved_id = meta.get("lyrics_record_id") if "lyrics_record_id" in meta else None
    has_saved_id = "lyrics_record_id" in meta and saved_id is not None
    matched_content = False
    options = []
    for c in found:
        raw = c.get("syncedLyrics") or ""
        lines = [line["text"] for line in lyrics.parse_lrc(raw) if line.get("text")]
        if has_saved_id:
            selected = c.get("id") == saved_id
        else:
            selected = not matched_content and raw == current
            matched_content = matched_content or selected
        options.append({"id": c.get("id"), "track": c.get("trackName"), "artist": c.get("artistName"), "album": c.get("albumName"),
                        "language": lyrics.LANGUAGES[lyrics.script(raw)], "lines": len(lines), "preview": lines[:2], "current": selected,
                        # seconds longer (+) or shorter than this song: a big gap usually means another version
                        "difference": round(float(c.get("duration") or 0) - meta["duration"])})
    return options

class LyricChoice(BaseModel):
    id: int

class OffsetChoice(BaseModel):
    value: float

    @field_validator("value")
    @classmethod
    def finite(cls, value):
        if not math.isfinite(value):
            raise ValueError("Expected a finite number")
        return value

def queue_item(queue_key: str, video_id: str | None = None):
    item = next((i for i in state.upcoming if i["key"] == queue_key), None)
    if item is None:
        raise HTTPException(404, "Queue song not found")
    if video_id is not None and item["id"] != video_id:
        raise HTTPException(409, "Queue song changed")
    if item["status"] != "ready":
        raise HTTPException(409, "Lyrics settings are not ready yet")
    return item

async def select_lyrics(video_id: str, choice: LyricChoice, target=None):
    """Save and prepare a selected LRCLIB record for current or queued playback."""
    folder, _ = song_meta(video_id)
    try:
        chosen = await lyrics.record(choice.id)
    except Exception as exc:
        raise HTTPException(502, f"Lyrics lookup failed: {exc}") from exc
    raw = (chosen or {}).get("syncedLyrics") or ""
    if not chosen or not lyrics.STAMP.search(raw):
        raise HTTPException(404, "That lyrics version is no longer available")
    if target is not None and (target not in state.upcoming or target["status"] != "ready"):
        raise HTTPException(409, "Queue song changed while saving")

    async with state.cache_lock(video_id):
        meta_path = folder / "meta.json"
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HTTPException(409, "Song cache changed; try again") from exc
        old_raw = (folder / "lyrics.lrc").read_text(encoding="utf-8") if (folder / "lyrics.lrc").is_file() else ""
        changed = raw != old_raw
        if changed:
            worker.save_lyrics(folder, raw)
            meta.pop("lyric_offset", None)
            meta["lyrics_revision"] = int(meta.get("lyrics_revision") or 0) + 1
        meta["lyrics_record_id"] = choice.id
        meta["lyrics_identity"] = [meta["artist"], meta["title"]]
        meta["lyrics_source"] = "manual"
        worker.save_meta(folder, meta)
        revision = int(meta.get("lyrics_revision") or 0)

    lines = lyrics.parse_lrc(raw)
    vocals_path = stems.path(folder, "vocals")
    if changed and vocals_path and vocals_path.is_file():
        try:
            lines = await asyncio.to_thread(worker.timed_lyrics, folder, raw, vocals_path, lines)
        except Exception as exc:
            raise HTTPException(502, "Lyrics timing failed") from exc
    lyrics.line_starts(lines)

    async with state.cache_lock(video_id):
        latest = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        current_raw = (folder / "lyrics.lrc").read_text(encoding="utf-8") if (folder / "lyrics.lrc").is_file() else ""
        if current_raw != raw or int(latest.get("lyrics_revision") or 0) != revision:
            raise HTTPException(409, "Lyrics changed while saving; try again")
        offset = float(latest.get("lyric_offset") or 0)

    if target is not None:
        target.update(lyrics=lines, lyrics_status="ready", lyrics_error=None, offset=offset)
    if state.current and state.current["id"] == video_id:
        state.current.update(lyrics=lines, lyrics_status="ready", lyrics_error=None,
                             lyrics_rev=state.current.get("lyrics_rev", 0) + (1 if changed else 0))
        if changed:
            state.offset = 0
            state.lyrics_sent.clear()
    await state.broadcast()
    return {"saved": choice.id, "changed": changed}

@app.post("/api/songs/{video_id}/lyrics")
async def choose_lyrics(video_id: str, choice: LyricChoice):
    """Save the chosen version; a current song switches immediately."""
    return await select_lyrics(video_id, choice)

@app.get("/api/queue/{queue_key}/lyrics")
async def queued_lyrics(queue_key: str):
    item = queue_item(queue_key)
    folder, meta = song_meta(item["id"])
    raw = (folder / "lyrics.lrc").read_text(encoding="utf-8") if (folder / "lyrics.lrc").is_file() else ""
    lines = []
    try:
        timed = json.loads((folder / "timed.json").read_text(encoding="utf-8"))
        lines = (timed.get("lines") or []) if timed.get("key") == worker.timing_key(raw) else []
    except (OSError, ValueError, TypeError):
        lines = lyrics.parse_lrc(raw)
    if not lines and raw:
        lines = lyrics.parse_lrc(raw)
    return {"key": item["key"], "id": item["id"], "artist": item["artist"], "title": item["title"],
            "lyrics_status": item.get("lyrics_status", "missing"), "lyrics": lines,
            "raw": raw, "offset": float(meta.get("lyric_offset") or item.get("offset") or 0),
            "source": meta.get("lyrics_source")}

@app.post("/api/queue/{queue_key}/lyrics")
async def choose_queued_lyrics(queue_key: str, choice: LyricChoice):
    item = queue_item(queue_key)
    return await select_lyrics(item["id"], choice, item)

@app.patch("/api/queue/{queue_key}/offset")
async def set_queued_offset(queue_key: str, choice: OffsetChoice):
    try:
        item = await state.set_queue_offset(queue_key, choice.value)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    await state.broadcast()
    return {"key": item["key"], "id": item["id"], "offset": item["offset"]}

@app.delete("/api/songs/{video_id}")
async def delete_song(video_id: str):
    """Forget a song and delete its download; queueing it again downloads it fresh."""
    folder = CACHE / video_id
    if not youtube.ID.fullmatch(video_id) or not (folder.is_dir() or video_id in state.played):
        raise HTTPException(404, "Song not found")
    if state.queued(video_id):
        raise HTTPException(409, "Remove it from the queue first")
    state.played.pop(video_id, None)
    if folder.is_symlink():
        folder.unlink()
    elif folder.is_dir():
        await asyncio.to_thread(shutil.rmtree, folder)
    await state.broadcast()
    return {"deleted": video_id}

@app.post("/api/queue", status_code=201)
async def enqueue(song: Song):
    if len(state.upcoming) >= 100:
        raise HTTPException(409, "Queue is full")
    try:
        return await state.add(song.id, song.artist, song.title)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

@app.get("/media/{video_id}/{filename}")
async def media(video_id: str, filename: str):
    """Stems are requested by name (vocals, no_vocals) and served in whichever format is cached."""
    if not youtube.ID.fullmatch(video_id) or filename not in (*stems.NAMES, "video.mp4"):
        raise HTTPException(404)
    folder = CACHE / video_id
    path = folder / filename if filename == "video.mp4" else stems.path(folder, filename)
    if not path or not path.is_file():
        raise HTTPException(404)
    types = {".mp4": "video/mp4", ".opus": "audio/ogg", ".flac": "audio/flac", ".wav": "audio/wav"}
    return FileResponse(path, media_type=types[path.suffix])

def remote_url():
    if os.environ.get("KTVIBES_REMOTE_URL"):
        url = os.environ["KTVIBES_REMOTE_URL"].rstrip("/")
        return url if url.endswith("/remote") else url + "/remote"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            host = sock.getsockname()[0]
    except OSError:
        host = "127.0.0.1"
    return f"http://{host}:{PORT}/remote"

@app.get("/api/config")
async def config():
    return {"remote_url": remote_url()}

@app.get("/api/qr.svg")
async def qr():
    out = io.BytesIO()
    qrcode.make(remote_url(), image_factory=qrcode.image.svg.SvgPathImage).save(out)
    return Response(out.getvalue(), media_type="image/svg+xml")

@app.websocket("/ws")
async def websocket(ws: WebSocket):
    await ws.accept()
    role = ws.query_params.get("role", "remote")
    if role == "tv" and state.player is not None:
        # Newest TV wins: a reload must not be locked out by its own stale socket.
        previous = state.player
        state.disconnect(previous)
        with suppress(Exception):
            await previous.send_json({"type": "error", "message": "Another device took over playback."})
            await previous.close(code=4001)
    state.clients[ws] = role
    if role == "tv":
        state.player = ws
    await state.broadcast()
    try:
        while True:
            message = await ws.receive_json()
            try:
                if not isinstance(message, dict):
                    raise ValueError("Expected a control object")
                for field in ("value", "delta", "position", "minutes"):
                    # Text values (guide modes) pass through; State.control converts numbers itself.
                    if isinstance(message.get(field), (int, float)) and not math.isfinite(message[field]):
                        raise ValueError("Expected a finite number")
                await state.control(message, ws)
            except (ValueError, TypeError, KeyError) as exc:
                await ws.send_json({"type": "error", "message": str(exc)})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        state.disconnect(ws)
        await state.broadcast()


def update():
    """`ktvibes update`: pull the latest version. The next `ktvibes` (uv run) installs any new dependencies."""
    import subprocess
    import sys
    git = lambda *args: subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
    if not (ROOT / ".git").exists():
        sys.exit(f"{ROOT} is not a git checkout; download the new version from https://github.com/andyleenz/KTVibes")
    if git("status", "--porcelain", "--untracked-files=no").stdout.strip():
        sys.exit(f"{ROOT} has local changes; commit or stash them, then run ktvibes update again.")
    before = git("rev-parse", "--short", "HEAD").stdout.strip()
    pulled = git("pull", "--ff-only")
    if pulled.returncode:
        sys.exit(pulled.stderr.strip() or "git pull failed")
    after = git("rev-parse", "--short", "HEAD").stdout.strip()
    print("Already up to date." if before == after else f"Updated {before} -> {after}. Stop KTVibes if it is running, then start it again: ktvibes")

def run():
    """`uv run ktvibes`: one process only, since queue state and the model live in memory."""
    import sys
    if sys.argv[1:] == ["update"]:
        return update()
    import uvicorn
    if missing := worker.missing_tools():
        # Common right after installing: the terminal predates the install and has a stale PATH.
        print(f"WARNING: {', '.join(missing)} not found on PATH. Songs can't be prepared until it is installed.\n"
              "If you just installed it, open a new terminal and run ktvibes again.", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
