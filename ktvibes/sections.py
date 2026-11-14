"""Playback boundaries from timed sung words, in media seconds."""
import math


def boundaries(item, offset=0):
    if not item or item.get("lyrics_status") != "ready":
        return None
    words = [unit for line in item.get("lyrics", []) for unit in line.get("units", [])
             if isinstance(unit, (list, tuple)) and len(unit) >= 3 and str(unit[0]).strip()]
    if not words:
        return None
    try:
        spans = [(float(word[1]), float(word[2])) for word in words]
        duration = float(item["duration"])
        if not math.isfinite(duration) or not math.isfinite(offset):
            return None
        if any(not math.isfinite(s) or not math.isfinite(e) or s < 0 or e < s for s, e in spans):
            return None
        if not any(e > s for s, e in spans):
            return None
        first, last = min(s for s, _ in spans) - offset, max(e for _, e in spans) - offset
        if not 0 <= first < last <= duration:
            return None
        return {"intro": max(0, first - 5), "outro": last}
    except (ValueError, TypeError, IndexError, KeyError):
        return None
