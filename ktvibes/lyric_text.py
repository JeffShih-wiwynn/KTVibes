"""Lyric text operations; independent of HTTP and application state."""
import re
STAMP = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")
VOICE = re.compile(r"(v\d+):\s*")
WORD_STAMP = re.compile(r"<(\d+):(\d+(?:\.\d+)?)>")
LRC_META = re.compile(r"\[(?:ar|ti|al|by|re|ve|length|offset|kana|la):[^]]*\]", re.I)
# Chinese/Japanese/Korean highlight per character; other scripts per word.
CJK = "\u1100-\u11ff\u2e80-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef"
UNIT = re.compile(rf"[{CJK}]\s*|[^\s{CJK}]+\s*|\s+")

def split_units(text: str) -> list[str]:
    return UNIT.findall(text)

def weight(unit: str) -> int:
    """Rough sung length: one per CJK character, one per vowel group in other words."""
    return max(1, len(re.findall(r"[aeiouyà-ÿ]+", unit, re.I))) if re.search(rf"[^\s{CJK}]", unit) else 1

def parse_lrc(raw: str) -> list[dict]:
    offset = re.search(r"\[offset:([+-]?\d+)\]", raw, re.I)
    shift = int(offset[1]) / 1000 if offset else 0
    lines = []
    for line in raw.splitlines():
        stamps = STAMP.findall(line)
        body = STAMP.sub("", line).strip()
        # Enhanced LRC: "<mm:ss.xx>word" gives real per-word timing.
        # Enhanced LRC duet tags ("v1:", "v2:") name the singer; keep them out of the text.
        voice = VOICE.match(body)
        body = body[voice.end():] if voice else body
        pieces = WORD_STAMP.split(body)
        text = "".join(pieces[::3]).strip()
        marks = [(pieces[i + 2], max(0, int(pieces[i]) * 60 + float(pieces[i + 1]) + shift)) for i in range(1, len(pieces) - 2, 3)]
        # A trailing empty "<mm:ss>" marks when the last word ends.
        words = [[w, start, marks[k + 1][1] if k + 1 < len(marks) else None] for k, (w, start) in enumerate(marks) if w]
        for minute, second in stamps:
            entry = {"t": max(0, int(minute) * 60 + float(second) + shift), "text": text}
            if voice:
                entry["voice"] = voice[1]
            if words and len(stamps) == 1:
                entry["units"], entry["exact"] = [list(w) for w in words], True
            lines.append(entry)
    lines.sort(key=lambda line: line["t"])
    for line, following in zip(lines, lines[1:] + [None]):
        units = line.get("units")
        if units:
            for unit, after in zip(units, units[1:] + [None]):
                if unit[2] is None:
                    unit[2] = after[1] if after else min(following["t"] if following else unit[1] + 1, unit[1] + 1.5)
    return lines

def lrc_display_text(raw: str) -> str:
    """Readable raw LRC, preserving source order and blank lines without alignment parsing."""
    shown = []
    for line in raw.splitlines():
        body = STAMP.sub("", line)
        body = WORD_STAMP.sub("", body)
        metadata = bool(LRC_META.search(body))
        body = LRC_META.sub("", body)
        if not body.strip():
            if not metadata:
                shown.append("")
            continue
        body = VOICE.sub("", body)
        shown.append(body.rstrip())
    # Metadata-only rows are omitted, while actual blank lines and lyric order remain intact.
    return "\n".join(shown)
