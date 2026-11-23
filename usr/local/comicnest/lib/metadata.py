"""Filename and directory heuristics for comic metadata.

Comic libraries are messy. This module deliberately favours a readable title
over a perfect parse: an unrecognised number stays part of the title instead of
being silently dropped.
"""

import os
import re
import struct

_IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".avif",
}

_BRACKET_RE = re.compile(r"[\[｛{][^\]｝}]*[\]｝}]")
_YEAR_RE = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")
_VOLUME_RES = (
    re.compile(r"(?:vol(?:ume)?|v)\s*[._-]?\s*(\d+(?:\.\d+)?)", re.I),
    re.compile(r"第\s*(\d+(?:\.\d+)?)\s*[卷册部]"),
)
_CHAPTER_RES = (
    re.compile(r"(?:chapter|chap|ch|c|episode|ep)\s*[._-]?\s*(\d+(?:\.\d+)?)", re.I),
    re.compile(r"第\s*(\d+(?:\.\d+)?)\s*[话話章回集]"),
    re.compile(r"\[\s*(\d+(?:\.\d+)?)\s*\]"),
)
_LEADING_NUMBER_RE = re.compile(r"^[\s._-]*(\d+(?:\.\d+)?)[\s._-]*$")
_LANGUAGE_TAGS = {
    "digital", "scan", "scans", "scanlation", "repack", "complete", "ongoing",
    "webrip", "web", "webtoon", "raw", "translated", "translation", "english",
    "chinese", "japanese", "korean", "han", "gb", "big5", "uncensored",
    "censored", "decensored", "color", "colour", "colored", "coloured", "hd",
    "sd", "retail", "fixed", "cbr", "cbz", "cb7", "pdf",
    "中文", "汉化", "漢化", "中字", "生肉", "熟肉", "全彩", "彩色", "黑白",
    "高清", "连载", "連載", "完结", "完結", "翻译", "翻譯", "官方",
}
_RESOLUTION_RE = re.compile(r"^\d{3,4}[pi]$", re.I)
_VIDEO_RE = re.compile(r"^(x|h)26[45]$|^(aac|flac|dts|web-?dl|blu-?ray)$", re.I)
_SEPARATORS_RE = re.compile(r"[\s._\-–—:：|/\\]+")
_BAD_RE = re.compile(r"[^\w\s\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af+\-&'!?,.]", re.UNICODE)


def image_extensions(extra=()):
    return _IMAGE_EXTENSIONS | set(ext.lower() for ext in extra)


def is_image(name, extra=()):
    return os.path.splitext(name)[1].lower() in image_extensions(extra)


def natural_key(text):
    return [int(part) if part.isdigit() else part.casefold()
            for part in re.split(r"(\d+)", text or "")]


def _strip_tags(text):
    text = _BRACKET_RE.sub(" ", text)
    # Parenthesised release tags are removed, but a year is kept for later.
    def paren(match):
        inner = match.group(1).strip()
        if re.fullmatch(r"(19|20)\d{2}", inner):
            return " (%s)" % inner
        parts = re.split(r"[\s._\-]+", inner.casefold())
        if parts and any(part in _LANGUAGE_TAGS or _RESOLUTION_RE.match(part)
                         or _VIDEO_RE.match(part) for part in parts):
            return " "
        return " (%s)" % inner

    text = re.sub(r"\(([^)]*)\)", paren, text)
    text = _SEPARATORS_RE.sub(" ", text)
    tokens = []
    for token in text.split():
        folded = token.casefold().strip(".,!?")
        if folded in _LANGUAGE_TAGS or _RESOLUTION_RE.match(folded) or _VIDEO_RE.match(folded):
            continue
        tokens.append(token)
    return " ".join(tokens)


def clean_title(text):
    text = (text or "").strip()
    text = os.path.splitext(text)[0]
    text = _strip_tags(text)
    text = _BAD_RE.sub(" ", text)
    text = _SEPARATORS_RE.sub(" ", text)
    text = re.sub(r"^[\s\-–—_:：|]+|[\s\-–—_:：|]+$", "", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_year(*texts):
    for text in texts:
        match = None
        for match in _YEAR_RE.finditer(text or ""):
            pass
        if match:
            return match.group(0)
    return ""


def _first_number(patterns, text):
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            try:
                return float(match.group(1)), pattern
            except ValueError:
                continue
    return None, None


def parse_release(stem):
    """Return a best-effort description of one file or folder name."""
    raw = os.path.splitext(stem or "")[0]
    working = _BRACKET_RE.sub(" ", raw)
    year = extract_year(working, raw)
    working_no_year = _YEAR_RE.sub(" ", working)

    volume, volume_pattern = _first_number(_VOLUME_RES, working_no_year)
    working_no_volume = working_no_year
    if volume_pattern:
        working_no_volume = volume_pattern.sub(" ", working_no_volume)

    number, chapter_pattern = _first_number(_CHAPTER_RES, working_no_volume)
    remaining = working_no_volume
    if chapter_pattern:
        remaining = chapter_pattern.sub(" ", remaining)

    leading = _LEADING_NUMBER_RE.match(remaining)
    if number is None and leading:
        number = float(leading.group(1))
        remaining = ""

    series_hint = clean_title(remaining)
    title = clean_title(raw)
    if not title:
        title = clean_title(remaining) or (stem or "").strip()
    return {
        "raw": raw,
        "title": title,
        "series_hint": series_hint,
        "volume": volume,
        "number": number,
        "year": year,
        "remainder": remaining.strip(),
    }


def looks_like_chapter(name):
    parsed = parse_release(name)
    if parsed["volume"] is None and parsed["number"] is None:
        return False
    remainder = _SEPARATORS_RE.sub("", parsed["remainder"] or "")
    return len(remainder) <= 2


def strip_series_prefix(title, series_title):
    if not title or not series_title:
        return title
    folded_title = title.casefold()
    folded_series = series_title.casefold()
    if folded_title == folded_series:
        return title
    if folded_title.startswith(folded_series):
        tail = title[len(series_title):].lstrip(" -–—:：")
        if tail:
            return tail
    return title


def chapter_sort_key(chapter):
    volume = chapter.get("volume")
    number = chapter.get("number")
    title = chapter.get("title") or ""
    return (
        volume if volume is not None else float("inf"),
        number if number is not None else float("inf"),
        natural_key(title),
    )


# ------------------------------------------------------------- image headers


def image_size(data):
    """Read pixel dimensions from the first bytes of an image, or ``None``."""
    if not data:
        return None
    try:
        return _image_size(data)
    except (IndexError, struct.error, ValueError):
        return None


def _image_size(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return struct.unpack(">II", data[16:24])

    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        return struct.unpack("<HH", data[6:10])

    if data[:2] == b"BM" and len(data) >= 26:
        width, height = struct.unpack("<ii", data[18:26])
        return abs(width), abs(height)

    if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
        chunk = data[12:16]
        if chunk == b"VP8X":
            width = 1 + int.from_bytes(data[24:27], "little")
            height = 1 + int.from_bytes(data[27:30], "little")
            return width, height
        if chunk == b"VP8L" and len(data) >= 25:
            bits = int.from_bytes(data[21:25], "little")
            width = (bits & 0x3FFF) + 1
            height = ((bits >> 14) & 0x3FFF) + 1
            return width, height
        if chunk == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
            width, height = struct.unpack("<HH", data[26:30])
            return width & 0x3FFF, height & 0x3FFF

    if data[:2] == b"\xff\xd8":
        return _jpeg_size(data)

    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return _tiff_size(data)

    return None


def _jpeg_size(data):
    index = 2
    length = len(data)
    while index + 9 < length:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > length:
            break
        segment = struct.unpack(">H", data[index:index + 2])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if index + 7 <= length:
                height, width = struct.unpack(">HH", data[index + 3:index + 7])
                return width, height
            break
        index += max(2, segment)
    return None


def _tiff_size(data):
    endian = "<" if data[:2] == b"II" else ">"
    offset = struct.unpack(endian + "I", data[4:8])[0]
    if offset + 2 > len(data):
        return None
    count = struct.unpack(endian + "H", data[offset:offset + 2])[0]
    width = height = None
    for item in range(count):
        base = offset + 2 + item * 12
        if base + 12 > len(data):
            break
        tag, kind, _count = struct.unpack(endian + "HHI", data[base:base + 8])
        if tag not in (256, 257):
            continue
        if kind == 3:
            value = struct.unpack(endian + "H", data[base + 8:base + 10])[0]
        elif kind == 4:
            value = struct.unpack(endian + "I", data[base + 8:base + 12])[0]
        else:
            continue
        if tag == 256:
            width = value
        else:
            height = value
    if width and height:
        return width, height
    return None


def is_wide(width, height, threshold=1.25):
    return bool(width and height and width / float(height) >= threshold)
