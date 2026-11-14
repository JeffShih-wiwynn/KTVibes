"""Unicode LRC support. Run: uv run python -m ktvibes.lyrics ARTIST TITLE SECONDS"""
import asyncio
import json
import math
import re
import sys
import time
import unicodedata

from .lyric_text import CJK, STAMP, VOICE, WORD_STAMP, LRC_META, UNIT
from .lyric_text import split_units, weight, parse_lrc, lrc_display_text
from .lyric_guides import HANGUL, KANA_CHARS, add_pinyin, japanese, romaji, add_romaji, kana_with_groups, kana, add_kana, cantonese, add_jyutping, romanize, add_korean_romanization
from .lyric_timing import envelope, onsets, onset_scorer, nearest_peak, find_shift, line_scores, shift_sections, shift_lines, echo, line_end, line_starts, time_units

from .lyric_cache import PLAIN_MISSING_TTL, read_plain_cache, read_viewer_selection

def plain_identity(value: str) -> str:
    """Normalize identity for cache and conservative LRCLIB matching across punctuation variants."""
    folded = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(ch for ch in folded if ch.isalnum())

def valid_plain_text(candidate: dict) -> str | None:
    """Return usable plain lyrics for a manually selected LRCLIB record."""
    if not isinstance(candidate, dict):
        return None
    text = candidate.get("plainLyrics")
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        if len(text.encode("utf-8")) > 200_000:
            return None
    except UnicodeEncodeError:
        return None
    return text.strip()

def plain_match_score(candidate: dict, artist: str, title: str, duration: float | None) -> tuple | None:
    """Return a deterministic relevance score, or reject a plain-lyrics record."""
    if valid_plain_text(candidate) is None:
        return None
    wanted_titles = [plain_identity(v) for v in variants(title)]
    wanted_artists = [plain_identity(v) for v in variants(artist)]
    got_title = plain_identity(str(candidate.get("trackName") or ""))
    got_artist = plain_identity(str(candidate.get("artistName") or ""))
    title_match = any(value and (got_title == value or (len(value) >= 4 and (value in got_title or got_title in value))) for value in wanted_titles)
    artist_match = any(value and (got_artist == value or (len(value) >= 4 and (value in got_artist or got_artist in value))) for value in wanted_artists)
    if not title_match or not artist_match:
        return None
    duration_gap = 0.0
    candidate_duration = candidate.get("duration")
    if duration and candidate_duration:
        try:
            duration_gap = abs(float(candidate_duration) - float(duration))
        except (TypeError, ValueError):
            duration_gap = 0.0
        if duration_gap > 10:
            return None
    return (got_title != next((v for v in wanted_titles if v), ""), got_artist != next((v for v in wanted_artists if v), ""), duration_gap, int(candidate.get("id") or 0))

async def plain_record(artist: str, title: str, duration: float | None) -> dict | None:
    """Find a relevant LRCLIB plain-lyrics record without changing synced candidate lookup."""
    import httpx
    searches = [{"artist_name": a, "track_name": t} for a in variants(artist) for t in variants(title)]
    searches += [{"q": f"{a} {t}"} for a in variants(artist) for t in variants(title)]
    searches = list({tuple(sorted(params.items())): params for params in searches}.values())[:8]
    found = {}
    async with lrclib() as client:
        for params in searches:
            response = await client.get("/api/search", params=params)
            response.raise_for_status()
            for candidate in response.json():
                if plain_match_score(candidate, artist, title, duration) is not None:
                    found[candidate.get("id") or (candidate.get("artistName"), candidate.get("trackName"))] = candidate
    if not found:
        return None
    selected = min(found.values(), key=lambda c: plain_match_score(c, artist, title, duration))
    return {"id": selected.get("id"), "text": selected["plainLyrics"].strip()}

def variants(name: str) -> list[str]:
    """'아이유(IU)' -> ['아이유(IU)', '아이유', 'IU']; '安靜 Silence' -> [..., '安靜', 'Silence'].

    LRCLIB often stores only one script of a bilingual name.
    """
    parts = [name, *re.split(r"\s*[(（]\s*|\s*[)）]\s*", name)]
    parts += re.findall(rf"[{CJK}][{CJK}\s]*", name) + re.findall(rf"[^\s{CJK}()（）][^{CJK}()（）]*", name)
    return list(dict.fromkeys(p.strip() for p in parts if p.strip()))

NATIVE = re.compile(rf"[{CJK}]")
KANA = re.compile(r"[぀-ヿ]")
HAN = re.compile(r"[一-鿿]")
LANGUAGES = {"ko": "Korean", "ja": "Japanese", "zh": "Chinese", "latin": "Latin script"}

def script(text: str) -> str:
    """The script lyrics are written in. Kana marks Japanese even beside kanji; Han alone is Chinese."""
    hangul, kana, han = len(HANGUL.findall(text)), len(KANA.findall(text)), len(HAN.findall(text))
    if not hangul + kana + han:
        return "latin"
    if hangul >= kana + han:
        return "ko"
    return "ja" if kana else "zh"

def wanted_script(*hints: str) -> str | None:
    """The song's own language, judged from its artist, title and YouTube title; None if they are all Latin."""
    found = script(" ".join(hints))
    return None if found == "latin" else found

def native(candidate: dict, want: str | None = None) -> bool:
    """Lyrics in the wanted script (any CJK script when unknown), rather than romanized or another language."""
    found = script(candidate.get("syncedLyrics") or "")
    return found == want if want else found != "latin"

def rank(candidate: dict, titles: list[str], duration: float, want: str | None = None) -> tuple:
    track = candidate.get("trackName", "").casefold()
    return (not any(t.casefold() in track for t in titles), "instrumental" in track, want is not None and not native(candidate, want),
            abs(float(candidate["duration"]) - duration))

def fits(candidate: dict, duration: float) -> bool:
    # Some LRCLIB records put untimed text in syncedLyrics; require real timestamps.
    # Music videos often run a few seconds longer than the album track; alignment re-times the lines.
    return bool(STAMP.search(candidate.get("syncedLyrics") or "")) and abs(float(candidate.get("duration") or 0) - duration) <= 10

def lrclib():
    import httpx
    return httpx.AsyncClient(base_url="https://lrclib.net", timeout=20, headers={"User-Agent": "KTVibes/0.2 (home karaoke)"})

async def search(query: str, duration: float) -> list[dict]:
    """Free-text LRCLIB search for the remote, when the automatic lookup found nothing or the wrong song.
    Any synced record qualifies; the caller ranks and limits versions for its target."""
    async with lrclib() as client:
        response = await client.get("/api/search", params={"q": query})
        response.raise_for_status()
    synced = [c for c in response.json() if STAMP.search(c.get("syncedLyrics") or "")]
    return synced

def enhanced_sync(raw: str) -> bool:
    """Only parsed, non-empty lines with usable word timing count as Enhanced LRC."""
    for line in parse_lrc(raw):
        if not line.get("exact") or not line["text"].strip():
            continue
        words = [unit for unit in line.get("units", []) if unit[0].strip()]
        if words and all(math.isfinite(unit[1]) and math.isfinite(unit[2]) and unit[2] > unit[1] for unit in words):
            return True
    return False


def search_rank(candidate: dict, artist: str, title: str, duration: float | None) -> tuple:
    """Match the song first, then prefer supplied word timing, line timing and plain text."""
    def match(value, wanted):
        got = plain_identity(value)
        names = [plain_identity(v) for v in variants(wanted)]
        if got and names and got == names[0]:
            return 0
        if got and any(name and (got == name or (len(name) >= 4 and (name in got or got in name))) for name in names):
            return 1
        return 2
    raw = candidate.get("syncedLyrics") or ""
    quality = 0 if enhanced_sync(raw) else 1 if STAMP.search(raw) else 2
    try:
        seconds = float(candidate.get("duration"))
        gap = abs(seconds - float(duration)) if seconds > 0 and duration else float("inf")
        if not math.isfinite(gap):
            gap = float("inf")
    except (TypeError, ValueError):
        gap = float("inf")
    return (match(candidate.get("trackName"), title), match(candidate.get("artistName"), artist),
            quality, gap, int(candidate.get("id") or 0), str(candidate.get("trackName") or "").casefold())


async def mixed_search(query: str, artist: str, title: str, duration: float | None) -> list[dict]:
    """One LRCLIB record per result; manual queries may surface plain records despite bad auto metadata."""
    async with lrclib() as client:
        response = await client.get("/api/search", params={"q": query})
        response.raise_for_status()
        records = response.json()
    unique = {}
    for candidate in records:
        synced = isinstance(candidate.get("syncedLyrics"), str) and bool(STAMP.search(candidate["syncedLyrics"]))
        if not synced and valid_plain_text(candidate) is None:
            continue
        key = candidate.get("id") or (candidate.get("artistName"), candidate.get("trackName"), candidate.get("albumName"))
        unique.setdefault(key, candidate)
    return sorted(unique.values(), key=lambda c: search_rank(c, artist, title, duration))[:50]

async def record(record_id: int) -> dict | None:
    """One LRCLIB record by id, as listed by candidates() or search()."""
    async with lrclib() as client:
        response = await client.get(f"/api/get/{record_id}")
    return response.json() if response.status_code == 200 else None

async def candidates(artist: str, title: str, duration: float, hints: tuple[str, ...] = (), exhaustive: bool = False) -> list[dict]:
    """LRCLIB records that fit the song. Stops at the first good one unless exhaustive (for the remote's picker)."""
    import httpx
    artists, titles = variants(artist), variants(title)
    want = wanted_script(artist, title, *hints)
    found = []
    # Without a language hint, a record with CJK lyrics still suggests romanized ones are a poor second.
    good = lambda c: fits(c, duration) and (native(c, want) if want else (native(c) or not any(map(native, found))))
    async with lrclib() as client:
        response = await client.get("/api/get", params={"artist_name": artist, "track_name": title, "duration": round(duration)})
        if response.status_code == 200:
            found.append(response.json())
        searches = [{"artist_name": a, "track_name": t} for a in artists for t in titles] + [{"q": f"{a} {t}"} for a in artists for t in titles] + [{"track_name": t} for t in titles]
        failure = None
        for params in searches:
            # A song can have several LRCLIB records: romanized, or another language's version.
            # Keep looking until one in the song's own script turns up.
            if not exhaustive and any(map(good, found)):
                break
            # LRCLIB intermittently returns 5xx; retry, then move on to the next variant.
            for attempt in range(3):
                try:
                    response = await client.get("/api/search", params=params)
                    response.raise_for_status()
                    found += response.json()
                    break
                except (httpx.TransportError, httpx.HTTPStatusError) as error:
                    failure = error
                    if isinstance(error, httpx.HTTPStatusError) and error.response.status_code < 500:
                        break
                    await asyncio.sleep(1 + attempt)
        if failure and not found:
            raise failure
    unique = {c.get("id") or id(c): c for c in found if fits(c, duration)}
    if not want:
        # Latin-only names (say "NewJeans - Super Shy"): the original language usually has the most records;
        # translations and other-language releases fewer. Ties favour Korean, then Chinese.
        votes = [script(c.get("syncedLyrics") or "") for c in unique.values()]
        votes = [v for v in votes if v != "latin"]
        want = max(("ko", "zh", "ja"), key=votes.count) if votes else None
    return sorted(unique.values(), key=lambda c: rank(c, titles, duration, want))

async def fetch(artist: str, title: str, duration: float, hints: tuple[str, ...] = ()) -> dict:
    matches = await candidates(artist, title, duration, hints)
    selected = matches[0] if matches else {}
    raw = selected.get("syncedLyrics", "")
    return {"id": selected.get("id"), "raw": raw, "lines": parse_lrc(raw)}

if __name__ == "__main__":
    print(json.dumps(asyncio.run(fetch(sys.argv[1], sys.argv[2], float(sys.argv[3]))), ensure_ascii=False, indent=2))
