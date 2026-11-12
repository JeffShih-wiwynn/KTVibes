"""Validation and expiration of cached lyrics and manual viewer choices."""
import json
import time

PLAIN_MISSING_TTL = 7 * 86400

def read_plain_cache(path, identity: list[str], now: float | None = None) -> dict | None:
    """Return a usable plain-lyrics cache record for this normalized song identity."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or value.get("identity") != identity:
        return None
    status = value.get("status")
    if status == "ready" and isinstance(value.get("text"), str) and value["text"].strip() and len(value["text"].encode("utf-8")) <= 200_000:
        return value
    if status == "missing":
        try:
            if (time.time() if now is None else now) - float(value.get("checked_at") or 0) < PLAIN_MISSING_TTL:
                return value
        except (TypeError, ValueError):
            pass
    return None

def read_viewer_selection(path, identity: list[str]) -> dict | None:
    """Return an explicit, identity-matched manual lyrics choice for this song."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (not isinstance(value, dict) or value.get("identity") != identity or
            value.get("origin") != "manual" or value.get("format") not in ("synced", "plain", "none")):
        return None
    if value.get("format") == "none":
        return value if value.get("record_id") is None else None
    if not isinstance(value.get("record_id"), int) or isinstance(value.get("record_id"), bool):
        return None
    return value
