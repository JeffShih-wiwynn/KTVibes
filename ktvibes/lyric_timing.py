"""Lyric timing operations; independent of HTTP and application state."""
import re
from .lyric_text import split_units, weight

def envelope(samples, rate: int, hop: float = 0.05):
    """RMS of the (mono) vocal stem in hop-second frames."""
    import numpy as np
    mono = np.asarray(samples, dtype=np.float32)
    mono = mono.mean(axis=1) if mono.ndim == 2 else mono
    size = max(1, int(rate * hop))
    frames = mono[: len(mono) // size * size].reshape(-1, size)
    return np.sqrt((frames ** 2).mean(axis=1))

def onsets(energy, hop: float = 0.05):
    """Per frame: how much singing follows it (the next second) compared with just before it (half a second).
    Frames whose following second runs past the audio are left out."""
    import numpy as np
    energy = np.asarray(energy)
    active = (energy > np.percentile(energy, 95) * 0.15).astype(float)
    total = np.concatenate([[0.0], np.cumsum(active)])
    after, before = int(1 / hop), int(0.5 / hop)
    frames = np.arange(len(active) - after + 1)
    # A line sung in the first half second has less silence before it to compare with, not none:
    # scoring it -1 made a song that opens on its first word look misplaced as stamped.
    ahead = np.maximum(frames - before, 0)
    return (total[frames + after] - total[frames]) / after - (total[frames] - total[ahead]) / np.maximum(frames - ahead, 1)

def onset_scorer(energy, hop: float = 0.05):
    """score(starts, shift, fit): how much singing follows the shifted stamps compared with just before
    them, averaged over the lines whose windows fit in the audio; -1 when fewer than `fit` of them do."""
    import numpy as np
    onset = onsets(energy, hop)
    def score(starts, shift, fit):
        frames = np.round((starts + shift) / hop).astype(int)
        frames = frames[(frames >= 0) & (frames < len(onset))]
        if not len(frames) or len(frames) < fit * len(starts):
            return -1.0
        return float(np.mean(onset[frames]))
    return score

def nearest_peak(shifts, scores) -> int:
    """Index of the best shift, preferring the smallest of the peaks nearly as good. Lines sung at a steady
    pace also fit when shifted a whole line early or late (Fix You: -2 s scored 0.50, -8.95 s 0.63)."""
    best = int(scores.argmax())
    peaks = [i for i in range(1, len(scores) - 1) if scores[i] >= scores[i - 1] and scores[i] >= scores[i + 1]
             and scores[i] >= scores[best] * 2 / 3]
    return min(peaks + [best], key=lambda i: (abs(shifts[i]), -scores[i]))

def find_shift(lines: list[dict], energy, hop: float = 0.05, limit: float = 30.0) -> float:
    """Seconds to add to every stamp so the lines start where the vocals do.

    LRCLIB records follow the album track, and a music video often adds an intro;
    alignment only searches near each line, so it cannot recover a whole-song shift.
    """
    import numpy as np
    starts = np.array([line["t"] for line in lines if line["text"]])
    if len(starts) < 10 or not len(energy):
        return 0.0
    score = onset_scorer(energy, hop)
    in_place = score(starts, 0.0, 0.75)

    def search(shifts):
        # A shift that pushes many lines out of the audio is not a fit.
        scores = np.array([score(starts, shift, 0.75) for shift in shifts])
        best = nearest_peak(shifts, scores)
        # Measured on cached songs: correct stamps score 0.26-0.55 as they are, while a
        # music video 3.3 s late scored 0.01 as is and 0.33 shifted; noise stays below 0.25.
        # Offsets under a second are left to per-line alignment.
        if scores[best] < 0.25 or in_place > scores[best] / 2 or abs(shifts[best]) < 1:
            return 0.0
        return round(float(shifts[best]), 2)

    if shift := search(np.arange(-limit, limit + hop / 2, hop)):
        return shift
    # A long music-video intro can push the singing past `limit` (Adele's Hello sings from ~81 s, its LRC
    # from 5.8 s). Later shifts are searched only when the stamps fit badly as they are and nothing fits
    # nearer, so a song that already fits can't latch onto a far repeat of its chorus.
    later = len(energy) * hop - starts[0]
    if in_place >= 0.25 or later <= limit:
        return 0.0
    return search(np.arange(limit + hop, later + hop / 2, hop))

def line_scores(lines: list[dict], energy, hop: float, reach: int):
    """Onset score of each line at every shift of -reach..reach frames; NaN where the line leaves the audio
    (a real onset can score -1: sung just before, silent after)."""
    import numpy as np
    onset = onsets(energy, hop)
    at = np.round(np.array([line["t"] for line in lines]) / hop).astype(int)[:, None] + np.arange(-reach, reach + 1)
    inside = (at >= 0) & (at < len(onset))
    return np.where(inside, onset[np.clip(at, 0, len(onset) - 1)], np.nan) if len(onset) else np.full(at.shape, np.nan)

def shift_sections(lines: list[dict], energy, hop: float = 0.05, limit: float = 10.0, change: float = 5.0, per_second: float = 0.5) -> list[float]:
    """Move whole sections (lines between instrumental gaps) that the vocals sing earlier or later.

    A music video can cut or lengthen a break, so everything after it is off by the same amount
    (Fix You's video drops ~7 s after the first chorus). The shifts for all sections are chosen together:
    each line that clearly starts on singing counts one, and each change of shift between sections costs
    `change` plus `per_second` for every second it moves, so an edit is only found where it pays off over
    the lines after it, and the smaller of two fits wins: lines sung at a steady pace also fit a whole line
    early or late (好心分手, lines ~4.2 s apart: 12 lines start on singing at +0.75 s, 13 at -3.45 s).
    One misleading section can't move on its own and drag every later one along with it. Returns the shift given to each section."""
    import numpy as np
    if not len(energy):
        return []
    # A gap (empty line) moves with the section it ends.
    sections = []
    for line in lines:
        if line["text"] and (not sections or not sections[-1][-1]["text"]):
            sections.append([])
        if sections:
            sections[-1].append(line)
    if not sections:
        return []
    reach = int(round(limit / hop))
    offsets = np.arange(-reach, reach + 1)
    # Each line counts once, as a clear onset (+1), nothing (0), or outside the audio (-1), so faint noise
    # summed over a long verse can't outweigh a change. A tenth of the score itself centres a fit on the
    # sharpest onsets: a line still counts a quarter second late, and the cost of moving would stop there.
    sung = [[line for line in section if line["text"]] for section in sections]
    def evidence(group):
        raw = line_scores(group, energy, hop, reach)
        return np.where(np.isnan(raw), -1.0, (raw >= 0.5) + 0.1 * np.nan_to_num(raw)).sum(axis=0)
    scores = [evidence(group) for group in sung]
    distance = np.abs(offsets[:, None] - offsets[None, :]) * hop  # [previous shift, this shift]
    cost = np.where(distance > 0, change + per_second * distance, 0.0)
    best = scores[0] - cost[reach]  # the stamps as given (offset 0) come first
    back = []
    for index in range(1, len(sections)):
        # A section can't move back over the start of the previous section's last line, though keeping the
        # previous section's shift is always allowed: the stamps themselves are in order.
        room = (sung[index][0]["t"] - sung[index - 1][-1]["t"] - 1) / hop
        allowed = (offsets[:, None] <= offsets[None, :] + room) | (distance == 0)
        total = np.where(allowed, best[:, None] - cost, -np.inf)
        back.append(total.argmax(axis=0))
        best = scores[index] + total.max(axis=0)
    chosen = [int(best.argmax())]
    for step in reversed(back):
        chosen.append(int(step[chosen[-1]]))
    # Offsets under a second are left to per-line alignment. Dropping one can bring a section within a
    # second of the one before; that section then keeps the previous shift, as the search always allows.
    moved = [round(float(offsets[k] * hop), 2) if abs(offsets[k] * hop) >= 1 else 0.0 for k in reversed(chosen)]
    for index in range(1, len(moved)):
        if sung[index][0]["t"] + moved[index] < sung[index - 1][-1]["t"] + moved[index - 1] + 1:
            moved[index] = moved[index - 1]
    for section, shift in zip(sections, moved):
        shift_lines(section, shift)
    return moved

def shift_lines(lines: list[dict], shift: float) -> list[dict]:
    for line in lines:
        line["t"] = round(max(0.0, line["t"] + shift), 2)
        for unit in line.get("units") or []:
            unit[1], unit[2] = round(max(0.0, unit[1] + shift), 2), round(max(0.0, unit[2] + shift), 2)
    return lines

ECHO = re.compile(r"^\s*[(（][^()（）]*[)）]\s*$")

def echo(line: dict) -> bool:
    """A line wholly in brackets is a backing vocal ("(Caught in the undertow)"), often sung over the lead line."""
    return bool(ECHO.match(line.get("text") or ""))

def line_end(lines: list[dict], index: int, longest: float = 15) -> float:
    """Where a line's singing must end: the next lead line's stamp. A backing-vocal line overlaps the lead,
    so it does not cut the line before it short."""
    line = lines[index]
    following = (l["t"] for l in lines[index + 1:] if echo(line) or not echo(l))
    return min(next(following, line["t"] + 8), line["t"] + longest)

def line_starts(lines: list[dict], lead: float = 0.3) -> list[dict]:
    """When each line takes over on the TV, from its sung words rather than its LRC stamp.

    A stamp can come before the previous line's last word is sung ("bark after dark"
    ends at 29.33, the next stamp is 29.03) or after a line's first word; a line
    becomes active shortly before its first word, but not before the previous
    line's last word ends, and never after its own first word.

    A backing-vocal line overlaps the lead, so it neither waits for the lead to finish nor holds
    up the next lead line; `over` names the lead line it is sung over, which the TV keeps lit.
    """
    previous_end = previous_start = 0.0
    lead_index = None
    for index, line in enumerate(lines):
        units = line.get("units")
        first = units[0][1] if units else line["t"]
        backing = echo(line)
        start = min(max(first - lead if units else first, 0 if backing else previous_end), first)
        line["start"] = previous_start = round(max(start, previous_start), 2)
        line.pop("over", None)
        if backing and lead_index is not None:
            line["over"] = lead_index
        elif not backing:
            lead_index, previous_end = index, units[-1][2] if units else line["t"]
    return lines

def time_units(lines: list[dict], energy, hop: float = 0.05) -> list[dict]:
    """Spread each line's characters/words over the time the vocal stem is audible.

    LRCLIB is mostly line-timed; the separated vocals tell us when singing
    happens inside each line, so the wipe pauses on breaths and gaps.
    """
    import numpy as np
    energy = np.asarray(energy)
    floor = float(np.percentile(energy, 95)) * 0.04 if len(energy) else 0
    for index, line in enumerate(lines):
        if line.get("units") or not line["text"]:
            continue
        units = split_units(line["text"])
        # Energy can't tell a backing vocal from the lead, so this estimate stops at any next line.
        end = min(lines[index + 1]["t"] if index + 1 < len(lines) else line["t"] + 8, line["t"] + 15)
        # LRC stamps often come before the previous line is finished: start after its last aligned word.
        previous = lines[index - 1].get("units") if index and not echo(line) else None
        start = min(max(line["t"], previous[-1][2] if previous else 0), end - 0.5) if end - line["t"] > 0.5 else line["t"]
        window = energy[int(start / hop): max(int(start / hop) + 1, int(end / hop))]
        active = window > max(floor, float(np.percentile(window, 90)) * 0.25) if len(window) else window
        if active.sum() < 4:
            active = np.ones(max(1, int(min(end - start, len(units) * 0.4) / hop)), bool)
        clock = np.cumsum(active) * hop  # singing time elapsed at each frame end
        total = clock[-1]
        weights = np.cumsum([0] + [weight(u) for u in units]) / sum(weight(u) for u in units)
        def at(fraction, side):
            # "right": first frame singing past this point (a unit starts when singing resumes);
            # "left": frame where this point is reached (a unit ends when its singing finishes).
            frame = int(np.searchsorted(clock, fraction * total + (1e-9 if side == "right" else -1e-9), side))
            return round(start + min(frame, len(clock) - 1) * hop + (hop if side == "left" else 0), 2)
        line["units"] = [[unit, at(weights[i], "right") if i else start, at(weights[i + 1], "left")] for i, unit in enumerate(units)]
    return lines
