"""Atomic writes shared by preparation and lyric selection."""
import json
from contextlib import suppress
import uuid
from pathlib import Path

def write_json(path: Path, value, *, indent=None):
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=indent), encoding="utf-8")
        temporary.replace(path)
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)

def save_meta(folder: Path, meta: dict):
    write_json(folder / "meta.json", meta, indent=2)

def save_lyrics(folder: Path, raw: str):
    """Atomically replace the selected LRC so readers never see a partial file."""
    temporary = folder / f".lyrics.{uuid.uuid4().hex}.tmp"
    if raw:
        temporary.write_text(raw, encoding="utf-8")
        temporary.replace(folder / "lyrics.lrc")
    else:
        temporary.unlink(missing_ok=True)
        (folder / "lyrics.lrc").unlink(missing_ok=True)
