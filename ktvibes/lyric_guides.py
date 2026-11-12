"""Lyric guides operations; independent of HTTP and application state."""
import re

def add_pinyin(lines: list[dict]) -> list[dict]:
    """Append tone-marked pinyin to each unit; whole-line context picks polyphone readings (还是 hái, 了解 liǎo)."""
    from pypinyin import Style, lazy_pinyin
    for line in lines:
        units = line.get("units")
        if not units or line.get("lang") == "ja" or not re.search(r"[\u3400-\u9fff\uf900-\ufaff]", line["text"]):
            continue
        text = "".join(u[0] for u in units)
        readings = iter(lazy_pinyin(text, style=Style.TONE, errors=lambda s: [""] * len(s)))
        for unit in units:
            unit[3:] = [" ".join(filter(None, (next(readings) for _ in unit[0])))]
    return lines

HAN = re.compile(r"[一-鿿]")
KANA_CHARS = re.compile(r"[\u3040-\u30ff]")
SMALL_KANA = set("ゃゅょぁぃぅぇぉゎャュョァィゥェォヮ")
_kakasi = None

def japanese(lines: list[dict]) -> bool:
    """Kana anywhere marks a Japanese song, so its kanji-only lines are read as Japanese too."""
    return any(KANA_CHARS.search(line["text"]) for line in lines)

def romaji(units: list[str]) -> list[str]:
    """Hepburn reading per unit. A kanji word's reading goes on its first character; kana are read
    one by one, with small kana (きゃ kya) and っ (doubles the next consonant) joined to their neighbour."""
    global _kakasi
    if _kakasi is None:
        import pykakasi
        _kakasi = pykakasi.kakasi()
    text = "".join(units)
    owner = [i for i, unit in enumerate(units) for _ in unit]  # character position -> unit index
    out, position = [""] * len(units), 0
    for segment in _kakasi.convert(text):
        word, reading = segment["orig"], segment["hepburn"]
        if KANA_CHARS.search(word) and not HAN.search(word):
            chars = list(word)
            for k, char in enumerate(chars):
                if char in SMALL_KANA or char == "ー" or not KANA_CHARS.match(char):
                    continue
                pair = char + (chars[k + 1] if k + 1 < len(chars) and chars[k + 1] in SMALL_KANA else "")
                sound = "" if char in "っッ" else _kakasi.convert(pair)[0]["hepburn"]
                if k and chars[k - 1] in "っッ" and sound:
                    sound = sound[0] + sound
                if position + k < len(owner):
                    out[owner[position + k]] += sound
        elif HAN.search(word) and reading.strip() and position < len(owner):
            out[owner[position]] += reading
        position += len(word)
    return [r.strip() for r in out]

def add_romaji(lines: list[dict]) -> list[dict]:
    """Append romaji to each unit of a Japanese song; marks its lines so the Chinese guides skip them."""
    if not japanese(lines):
        return lines
    for line in lines:
        units = line.get("units")
        line["lang"] = "ja"
        if not units:
            continue
        for unit, reading in zip(units, romaji([u[0] for u in units])):
            if not re.search(r"[A-Za-z]", unit[0]):
                unit[3:] = [reading]
    return lines

def kana_with_groups(units: list[str]) -> list[tuple[str, int | None]]:
    """Return readings and shared ruby-group IDs for Japanese word segments."""
    global _kakasi
    if _kakasi is None:
        import pykakasi
        _kakasi = pykakasi.kakasi()
    text = "".join(units)
    owner = [i for i, unit in enumerate(units) for _ in unit]
    starts, total = [], 0
    for unit in units:
        starts.append(total)
        total += len(unit)
    out, groups, position = [""] * len(units), [None] * len(units), 0
    for segment in _kakasi.convert(text):
        word, reading = segment["orig"], segment.get("hira", "")
        if HAN.search(word) and reading.strip() and position < len(owner):
            first, last = owner[position], owner[min(position + len(word) - 1, len(owner) - 1)]
            # A ruby group must start/end on timing-unit boundaries. Trailing spaces belong to
            # the preceding CJK unit, so allow whitespace after the segment's final character.
            exact_edges = position == starts[first] and text[position:starts[last] + len(units[last])].rstrip() == word
            if exact_edges:
                for index in range(first, last + 1):
                    groups[index] = position
                out[first] += reading
        position += len(word)
    return [(value.strip(), group) for value, group in zip(out, groups)]

def kana(units: list[str]) -> list[str]:
    """Return hiragana readings for kanji word segments only."""
    return [reading for reading, _ in kana_with_groups(units)]

def add_kana(lines: list[dict]) -> list[dict]:
    """Append hiragana readings to Japanese lyric units in the kana guide slot."""
    if not japanese(lines):
        return lines
    for line in lines:
        units = line.get("units")
        if not units:
            continue
        for unit, (reading, group) in zip(units, kana_with_groups([u[0] for u in units])):
            while len(unit) < 8:
                unit.append("")
            unit[6] = reading
            unit[7] = group
    return lines

# Characters that appear in written Cantonese but hardly ever in Mandarin lyrics.
CANTONESE = re.compile(r"[嘅咗唔冇佢啲喺嚟嘢噉哋睇諗啱乜嗰攞畀嗮揾搵嘥瞓攰咩㗎噃]")

def cantonese(lines: list[dict]) -> bool:
    """Written-Cantonese characters on a few lines mark a Cantopop song (one stray character is not enough)."""
    return sum(1 for line in lines if CANTONESE.search(line["text"])) >= 2

def add_jyutping(lines: list[dict]) -> list[dict]:
    """Store Cantonese jyutping as unit[5] for Chinese characters, for the "jyutping" guide."""
    import ToJyutping
    for line in lines:
        units = line.get("units")
        if not units or line.get("lang") == "ja" or not re.search(r"[\u3400-\u9fff\uf900-\ufaff]", line["text"]):
            continue
        readings = iter(ToJyutping.get_jyutping_list("".join(u[0] for u in units)))
        for unit in units:
            sounds = [next(readings, (None, None))[1] for _ in unit[0]]
            while len(unit) < 5:
                unit.append("")
            unit[5:] = [" ".join(filter(None, sounds))]
    return lines

HANGUL = re.compile(r"[\uac00-\ud7a3]")
# Revised Romanization of Korean, per jamo.
INITIALS = "g kk n d tt r m b pp s ss  j jj ch k t p h".split(" ")
VOWELS = "a ae ya yae eo e yeo ye o wa wae oe yo u wo we wi yu eu ui i".split()
FINALS = ["", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l", "p", "l", "m", "p", "p", "t", "t", "ng", "t", "t", "k", "t", "p", "t"]
_g2p = None

def romanize(syllables: str) -> list[str]:
    """Romanize Hangul syllables as sung. Input should already be the pronounced form."""
    out, previous_final = [], 0
    for char in syllables:
        code = ord(char) - 0xAC00
        initial, vowel, final = code // 588, code % 588 // 28, code % 28
        onset = "l" if initial == 5 and previous_final == 8 else INITIALS[initial]  # ㄹㄹ -> ll
        out.append(onset + VOWELS[vowel] + FINALS[final])
        previous_final = final
    return out

def add_korean_romanization(lines: list[dict]) -> list[dict]:
    """Romanize each Korean syllable from its sung pronunciation (눈물이 -> nun mu ri, 못하게 -> mo ta ge)."""
    global _g2p
    needs_g2p = any(
        line.get("units") and HANGUL.search(line["text"]) and any(
            HANGUL.search(unit[0]) and not (len(unit) > 3 and unit[3])
            for unit in line["units"]
        )
        for line in lines
    )
    if not needs_g2p:
        return lines
    if _g2p is None:
        from g2pk2 import G2p
        _g2p = G2p()
    for line in lines:
        units = line.get("units")
        if not units or not HANGUL.search(line["text"]):
            continue
        written = HANGUL.findall(line["text"])
        spoken = HANGUL.findall(_g2p(line["text"]))
        # If sound changes altered the syllable count, fall back to the written form.
        readings = iter(romanize("".join(spoken if len(spoken) == len(written) else written)))
        for unit in units:
            syllables = HANGUL.findall(unit[0])
            if syllables and not (len(unit) > 3 and unit[3]):
                unit[3:] = [" ".join(next(readings) for _ in syllables)]
            elif syllables:
                for _ in syllables:
                    next(readings)
    return lines
