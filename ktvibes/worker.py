import asyncio
import hashlib
import json
import logging
import time
import uuid
from pathlib import Path
import soundfile as sf
from . import align, guides, songbook, stems, youtube, lyrics

log = logging.getLogger(__name__)
TIMING_VERSION = 11  # bump when alignment or guide output changes, so cached timing is rebuilt
LYRICS_RECHECK = 7 * 86400  # a song LRCLIB had no lyrics for is looked up again after this long
STARTED = time.time()  # energy-only timing (aligner failed) cached before this run is retried once

def timing_key(raw: str) -> str:
    return f"{TIMING_VERSION}:{hashlib.sha256(raw.encode()).hexdigest()}"

def separate(source, destination):
    # Keep model imports off the server startup path.
    from .separate import separate as separate_audio
    return separate_audio(source, destination)

def reporter(state, item, step):
    """Progress callback for worker threads: while `step` is the one on show, record the fraction; broadcast at most twice a second."""
    loop, last = asyncio.get_running_loop(), [0.0]
    def report(fraction):
        def apply():
            if item.get("step") != step:
                return
            item["progress"] = fraction
            if loop.time() - last[0] >= 0.5:
                last[0] = loop.time()
                asyncio.ensure_future(state.broadcast())
        loop.call_soon_threadsafe(apply)
    return report

def missing_tools() -> list[str]:
    """External programs KTVibes needs on PATH: ffmpeg/ffprobe for media, Node.js for YouTube extraction."""
    import shutil
    return [name for name, exe in (("ffmpeg", "ffmpeg"), ("ffprobe", "ffprobe"), ("Node.js", "node")) if not shutil.which(exe)]

def save_meta(folder: Path, meta: dict):
    temporary = folder / f".meta.{uuid.uuid4().hex}.tmp"
    temporary.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(folder / "meta.json")

def save_lyrics(folder: Path, raw: str):
    """Atomically replace the selected LRC so readers never see a partial file."""
    temporary = folder / f".lyrics.{uuid.uuid4().hex}.tmp"
    if raw:
        temporary.write_text(raw, encoding="utf-8")
        temporary.replace(folder / "lyrics.lrc")
    else:
        temporary.unlink(missing_ok=True)
        (folder / "lyrics.lrc").unlink(missing_ok=True)

def fetch_video(video_id, folder, progress):
    """Runs alongside the audio work; a missing video only means the stage background."""
    try:
        youtube.download_video(video_id, folder, progress)
    except Exception:
        log.exception("Video unavailable for %s", video_id)
        return "Video unavailable; using the stage background."

def timed_lyrics(folder: Path, raw: str, samples_path: Path, lines: list[dict]) -> list[dict]:
    """Word timing and guides for these lyrics, reused from timed.json when the LRC text is unchanged."""
    key = timing_key(raw)
    try:
        cached = json.loads((folder / "timed.json").read_text(encoding="utf-8"))
        # Energy-only timing (the aligner failed) is retried once per run, not on every play.
        if cached.get("key") == key and (cached.get("aligned", True) or (folder / "timed.json").stat().st_mtime >= STARTED):
            return cached["lines"]
    except (OSError, ValueError, KeyError):
        pass
    samples, rate = sf.read(samples_path, dtype="float32")
    energy = lyrics.envelope(samples, rate)
    if shift := lyrics.find_shift(lines, energy):
        log.info("Lyrics for %s shifted %+.2fs to match the vocals", folder.name, shift)
        lyrics.shift_lines(lines, shift)
    if any(moved := lyrics.shift_sections(lines, energy)):
        log.info("Lyric sections for %s moved %s to match the vocals", folder.name, moved)
    aligned = True
    try:
        # Forced alignment on the vocals; lines it cannot place keep the energy estimate.
        align.align(lines, samples, rate)
    except Exception:
        log.exception("Forced alignment unavailable for %s", folder.name)
        aligned = False
    lyrics.time_units(lines, energy)
    lines = lyrics.add_kana(lyrics.add_jyutping(guides.add_hangul(lyrics.add_korean_romanization(lyrics.add_pinyin(lyrics.add_romaji(lines))))))
    temporary = folder / f".timed.{uuid.uuid4().hex}.tmp"
    temporary.write_text(json.dumps({"key": key, "aligned": aligned, "lines": lines}, ensure_ascii=False), encoding="utf-8")
    temporary.replace(folder / "timed.json")
    return lines

class Removed(Exception):
    """The song left the queue while it was being prepared."""

# Video downloads still running, by video id: a song queued again reuses its download instead of starting a second.
videos = {}

async def run(state, cache: Path):
    while True:
        state.wake.clear()
        item = next((i for i in state.upcoming if i["status"] == "queued"), None)
        if item is None:
            await state.wake.wait()
            continue
        folder = cache / item["id"]
        def check():
            # A removed song stops holding up the queue; a download already running finishes on its own.
            if item is not state.current and item not in state.upcoming:
                raise Removed
        try:
            folder.mkdir(parents=True, exist_ok=True)
            meta_path = folder / "meta.json"
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {}
            # The (larger, optional) video downloads while the audio is fetched and separated.
            video = None
            if not (folder / "video.mp4").is_file():
                video = videos.get(item["id"])
                if video is None or video.done():
                    video = videos[item["id"]] = asyncio.ensure_future(asyncio.to_thread(fetch_video, item["id"], folder, reporter(state, item, "video")))
            if not stems.ready(folder):
                # Songs cached as WAV or FLAC convert in seconds instead of separating again.
                gain = await asyncio.to_thread(stems.migrate, folder, meta.get("stem_gain"))
                if gain is None:
                    if not (folder / "audio.m4a").is_file():
                        item["status"], item["step"], item["progress"] = "downloading", "audio", 0.0
                        await state.broadcast()
                        meta.update(await asyncio.to_thread(youtube.download, item["id"], folder, reporter(state, item, "audio")))
                        check()
                    item["status"], item["step"], item["progress"] = "separating", None, None
                    await state.broadcast()
                    meta["separation_seconds"], gain = await asyncio.to_thread(separate, folder / "audio.m4a", folder)
                meta["stem_gain"] = gain
                async with state.cache_lock(item["id"]):
                    latest = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
                    latest.update({k: meta[k] for k in ("stem_gain", "separation_seconds") if k in meta})
                    save_meta(folder, latest)  # the gain must survive even if a later step fails
            check()
            if video and not video.done():
                item["status"], item["step"], item["progress"] = "downloading", "video", 0.0
                await state.broadcast()
                while not video.done():
                    await asyncio.wait({video}, timeout=0.5)
                    check()
            if video and (warning := await video):
                item["video_warning"] = warning
            item["video"] = (folder / "video.mp4").is_file()
            item["duration"] = sf.info(stems.path(folder, "no_vocals")).duration
            # Where the song stops, before any trailing silence: Classic scores it there. Remembered per stem
            # file, and left unset (the TV waits for the file's end) if a stem can't be read.
            stamps = [p.stat().st_mtime for name in stems.NAMES if (p := stems.path(folder, name))]
            meta.pop("music_end", None)  # the old instrumental-only value
            known = meta.get("song_end")
            if stamps and not (isinstance(known, list) and len(known) == 2 and known[0] == stamps):
                end = await asyncio.to_thread(stems.song_end, folder)
                known = meta["song_end"] = [stamps, end] if end else None
            if stamps and known:
                item["music_end"] = known[1]
            item["gain"] = float(meta.get("stem_gain") or 1)
            item["lyrics_status"], item["lyrics_error"] = "processing", None
            identity = [item["artist"], item["title"]]
            async with state.cache_lock(item["id"]):
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    meta = {}
                cached = (folder / "lyrics.lrc").read_text(encoding="utf-8") if (folder / "lyrics.lrc").is_file() else ""
                plain_cache = lyrics.read_plain_cache(
                    folder / "plain_lyrics.json",
                    [lyrics.plain_identity(identity[0]), lyrics.plain_identity(identity[1])], time.time())
                viewer_selection = lyrics.read_viewer_selection(folder / "viewer_selection.json",
                    [lyrics.plain_identity(identity[0]), lyrics.plain_identity(identity[1])])
            raw = ""
            same = meta.get("lyrics_identity") == identity
            manual = meta.get("lyrics_source") == "manual"
            has_cached_synced = (same or manual) and bool(lyrics.parse_lrc(cached))
            recently_checked = same and time.time() - meta.get("lyrics_checked", 0) < LYRICS_RECHECK
            if has_cached_synced:
                item["status"] = "aligning_lyrics"
            elif recently_checked:
                item["status"] = "ready"
            else:
                item["status"] = "searching_synced_lyrics"
            item["step"], item["progress"] = None, None
            if (same or manual) and lyrics.parse_lrc(cached):
                item["viewer_lyrics_source"] = "synced"
            elif plain_cache and plain_cache.get("status") == "ready":
                item["viewer_lyrics_source"] = "plain"
            else:
                item["viewer_lyrics_source"] = "processing"
            if viewer_selection and viewer_selection["format"] == "plain" and plain_cache and plain_cache.get("record_id") == viewer_selection["record_id"]:
                item["viewer_lyrics_source"] = "plain"
            elif viewer_selection and viewer_selection["format"] == "synced" and (same or manual) and lyrics.parse_lrc(cached):
                item["viewer_lyrics_source"] = "synced"
            elif viewer_selection:
                item["viewer_lyrics_source"] = "missing"
            await state.broadcast()
            if (same or manual) and lyrics.parse_lrc(cached):
                raw = cached
                item["lyrics"] = lyrics.parse_lrc(cached)
                item["lyrics_status"] = "ready"
                item["viewer_lyrics_source"] = "synced"
            elif same and time.time() - meta.get("lyrics_checked", 0) < LYRICS_RECHECK:
                pass  # LRCLIB had none recently; "Lyrics language…" on the remote still searches
            else:
                try:
                    result = await lyrics.fetch(*identity, item["duration"], (meta.get("source_title") or "",))
                    async with state.cache_lock(item["id"]):
                        latest = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
                        latest_raw = (folder / "lyrics.lrc").read_text(encoding="utf-8") if (folder / "lyrics.lrc").is_file() else ""
                        # A manual choice made while LRCLIB was being queried wins over the old result.
                        if latest.get("lyrics_source") == "manual" and lyrics.parse_lrc(latest_raw):
                            meta, raw = latest, latest_raw
                            item["lyrics"] = lyrics.parse_lrc(raw)
                            item["viewer_lyrics_source"] = "synced"
                        else:
                            raw, item["lyrics"] = result["raw"], result["lines"]
                            if lyrics.STAMP.search(raw) and lyrics.lrc_display_text(raw).strip():
                                item["viewer_lyrics_source"] = "synced"
                            latest["lyrics_identity"], latest["lyrics_checked"] = identity, time.time()
                            latest["lyrics_source"] = "automatic"
                            latest["lyrics_revision"] = int(latest.get("lyrics_revision") or 0) + 1
                            if result.get("id") is None:
                                latest.pop("lyrics_record_id", None)
                            else:
                                latest["lyrics_record_id"] = result["id"]
                            latest.pop("lyric_offset", None)  # a nudge for other lyrics no longer fits
                            save_lyrics(folder, raw)
                            meta = latest
                    item["lyrics_status"] = "ready" if item["lyrics"] else "missing"
                except Exception:
                    log.exception("Lyrics unavailable for %s", item["id"])
                    item["lyrics_status"], item["lyrics_error"] = "error", "Lyrics unavailable; audio is ready."
            lyrics_revision = int(meta.get("lyrics_revision") or 0)
            if item["lyrics"]:
                item["status"] = "aligning_lyrics"
                await state.broadcast()
                try:
                    item["lyrics"] = await asyncio.to_thread(timed_lyrics, folder, raw, stems.path(folder, "vocals"), item["lyrics"])
                    # A manual selection may have arrived while alignment was running. Do not publish
                    # the older result; retry once using the latest LRC and revision.
                    async with state.cache_lock(item["id"]):
                        latest = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
                        latest_raw = (folder / "lyrics.lrc").read_text(encoding="utf-8") if (folder / "lyrics.lrc").is_file() else ""
                    if latest_raw != raw or int(latest.get("lyrics_revision") or 0) != lyrics_revision:
                        raw, lyrics_revision = latest_raw, int(latest.get("lyrics_revision") or 0)
                        item["lyrics"] = lyrics.parse_lrc(raw)
                        item["lyrics"] = await asyncio.to_thread(timed_lyrics, folder, raw, stems.path(folder, "vocals"), item["lyrics"])
                    lyrics.line_starts(item["lyrics"])  # cheap, so kept out of the timing cache
                    item["lyrics_status"] = "ready"
                except Exception:
                    log.exception("Word timing unavailable for %s", item["id"])
                    item["lyrics_status"], item["lyrics_error"] = "error", "Lyrics timing failed."
            elif item["lyrics_status"] == "processing":
                item["lyrics_status"] = "missing"
            if viewer_selection and viewer_selection["format"] == "plain" and plain_cache and plain_cache.get("record_id") == viewer_selection["record_id"]:
                item["viewer_lyrics_source"] = "plain"
            elif viewer_selection and viewer_selection["format"] == "synced" and lyrics.parse_lrc(raw):
                item["viewer_lyrics_source"] = "synced"
            meta.update(duration=item["duration"], artist=item["artist"], title=item["title"])
            item["number"] = songbook.assign(cache, meta)
            async with state.cache_lock(item["id"]):
                latest = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
                latest.update({"duration": item["duration"], "artist": item["artist"], "title": item["title"]})
                if item.get("number") is not None:
                    latest["number"] = item["number"]
                meta = latest
                item["offset"] = float(meta.get("lyric_offset") or 0)
                save_meta(folder, meta)
                latest_raw = (folder / "lyrics.lrc").read_text(encoding="utf-8") if (folder / "lyrics.lrc").is_file() else ""
                saved_identity = latest.get("lyrics_identity")
                identity_matches = not (isinstance(saved_identity, (list, tuple)) and len(saved_identity) >= 2 and
                    [lyrics.plain_identity(str(saved_identity[0])), lyrics.plain_identity(str(saved_identity[1]))] !=
                    [lyrics.plain_identity(identity[0]), lyrics.plain_identity(identity[1])])
                viewer_selection = lyrics.read_viewer_selection(folder / "viewer_selection.json",
                    [lyrics.plain_identity(identity[0]), lyrics.plain_identity(identity[1])])
                plain_cache = lyrics.read_plain_cache(
                    folder / "plain_lyrics.json",
                    [lyrics.plain_identity(identity[0]), lyrics.plain_identity(identity[1])], time.time())
                if identity_matches and lyrics.STAMP.search(latest_raw) and lyrics.lrc_display_text(latest_raw).strip():
                    item["viewer_lyrics_source"] = "synced"
                else:
                    if plain_cache and plain_cache.get("status") == "ready":
                        item["viewer_lyrics_source"] = "plain"
                    elif plain_cache and plain_cache.get("status") == "missing":
                        item["viewer_lyrics_source"] = "missing"
                    elif item.get("lyrics_status") == "error" or item.get("viewer_lyrics_source") == "error":
                        item["viewer_lyrics_source"] = "error"
                    else:
                        item["viewer_lyrics_source"] = "unknown"
                if viewer_selection and viewer_selection["format"] == "plain" and plain_cache and plain_cache.get("record_id") == viewer_selection["record_id"]:
                    item["viewer_lyrics_source"] = "plain"
                elif viewer_selection and viewer_selection["format"] == "synced" and identity_matches and lyrics.STAMP.search(latest_raw) and lyrics.lrc_display_text(latest_raw).strip():
                    item["viewer_lyrics_source"] = "synced"
                elif viewer_selection:
                    item["viewer_lyrics_source"] = "missing"
            check()
            item["status"], item["step"], item["progress"] = "ready", None, None
            state.promote()
        except Removed:
            # Undoing the removal puts it back as queued, to be prepared again (fast from cache).
            log.info("Stopped preparing %s: removed from the queue", item["id"])
            item["status"], item["step"], item["progress"] = "queued", None, None
        except Exception as exc:
            log.exception("Preparation failed for %s", item["id"])
            item["status"] = "error"
            missing = missing_tools()
            # A missing ffmpeg or Node.js surfaces as an obscure "WinError 2"; say what to fix instead.
            item["error"] = f"{' and '.join(missing)} not found. Install, open a new terminal, restart KTVibes, then Retry." if missing else youtube.explain(exc)
            state.promote()
        await state.broadcast()
