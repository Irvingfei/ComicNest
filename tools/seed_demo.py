#!/usr/bin/env python3
"""Create a small demo library for local development.

The artwork is generated with the standard library: coloured panels, a gradient
and large page numbers. It is deliberately synthetic so the repository does not
ship questionable sample pages.
"""

import argparse
import io
import os
import struct
import zipfile
import zlib

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ROOT = os.path.join(REPO_ROOT, ".devdata", "share", "comicnest", "library")

_DIGITS = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    "A": ("010", "101", "111", "101", "101"),
    "B": ("110", "101", "110", "101", "110"),
    "C": ("011", "100", "100", "100", "011"),
    "E": ("111", "100", "110", "100", "111"),
    "F": ("111", "100", "110", "100", "100"),
    "G": ("011", "100", "101", "101", "011"),
    "H": ("101", "101", "111", "101", "101"),
    "I": ("111", "010", "010", "010", "111"),
    "L": ("100", "100", "100", "100", "111"),
    "M": ("101", "111", "111", "101", "101"),
    "N": ("101", "111", "111", "111", "101"),
    "O": ("010", "101", "101", "101", "010"),
    "P": ("110", "101", "110", "100", "100"),
    "R": ("110", "101", "110", "101", "101"),
    "S": ("011", "100", "010", "001", "110"),
    "T": ("111", "010", "010", "010", "010"),
    "U": ("101", "101", "101", "101", "111"),
    "V": ("101", "101", "101", "101", "010"),
    "W": ("101", "101", "111", "111", "101"),
    "Y": ("101", "101", "010", "010", "010"),
    " ": ("000", "000", "000", "000", "000"),
    "-": ("000", "000", "111", "000", "000"),
}

_PALETTES = [
    ((18, 24, 39), (36, 58, 88), (238, 196, 116), (244, 241, 234)),
    ((38, 20, 28), (92, 42, 50), (225, 176, 125), (246, 235, 222)),
    ((15, 28, 26), (40, 76, 66), (208, 214, 176), (240, 243, 232)),
    ((28, 22, 40), (72, 54, 94), (202, 168, 220), (243, 237, 247)),
    ((32, 26, 18), (92, 70, 35), (230, 186, 92), (248, 240, 224)),
]


def _chunk(kind, payload):
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _png(width, height, rows):
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + row for row in rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw, 6))
        + _chunk(b"IEND", b"")
    )


def _fill(rows, width, top, bottom, left, right, colour):
    top = max(0, top)
    bottom = min(len(rows), bottom)
    left = max(0, left)
    right = min(width, right)
    if right <= left:
        return
    chunk = bytes(colour) * (right - left)
    for y in range(top, bottom):
        rows[y][left * 3:right * 3] = chunk


def _border(rows, width, top, bottom, left, right, colour, thickness=4):
    _fill(rows, width, top, top + thickness, left, right, colour)
    _fill(rows, width, bottom - thickness, bottom, left, right, colour)
    _fill(rows, width, top, bottom, left, left + thickness, colour)
    _fill(rows, width, top, bottom, right - thickness, right, colour)


def _text(rows, width, height, text, x, y, scale, colour):
    cursor = x
    for character in text.upper():
        glyph = _DIGITS.get(character, _DIGITS[" "])
        for gy, line in enumerate(glyph):
            for gx, bit in enumerate(line):
                if bit == "1":
                    _fill(
                        rows,
                        width,
                        y + gy * scale,
                        y + (gy + 1) * scale,
                        cursor + gx * scale,
                        cursor + (gx + 1) * scale,
                        colour,
                    )
        cursor += 4 * scale
    return cursor


def render_page(number, palette_index=0, wide=False, label=None):
    width, height = (1600, 1100) if wide else (900, 1350)
    top, bottom, accent, ink = _PALETTES[palette_index % len(_PALETTES)]
    rows = []
    for y in range(height):
        ratio = y / max(1, height - 1)
        colour = bytes(
            int(top[channel] + (bottom[channel] - top[channel]) * ratio)
            for channel in range(3)
        )
        rows.append(bytearray(colour * width))

    if wide:
        gutter = width // 2
        _fill(rows, width, 0, height, gutter - 5, gutter + 5, (10, 10, 12))
        _fill(rows, width, 90, 560, 90, gutter - 70, (245, 238, 226))
        _fill(rows, width, 620, height - 90, 90, gutter - 70, (28, 34, 48))
        _fill(rows, width, 90, height - 90, gutter + 70, width - 90, (70, 88, 120))
        _border(rows, width, 90, 560, 90, gutter - 70, accent)
        _border(rows, width, 620, height - 90, 90, gutter - 70, ink)
        _border(rows, width, 90, height - 90, gutter + 70, width - 90, accent)
        _text(rows, width, height, label or "2A", 150, 180, 30, (20, 24, 32))
        _text(rows, width, height, "2B", gutter + 150, 760, 30, (245, 238, 226))
    else:
        _fill(rows, width, 80, 520, 70, width - 70, (246, 239, 227))
        _fill(rows, width, 560, 900, 70, 430, (26, 32, 46))
        _fill(rows, width, 560, 900, 470, width - 70, (198, 208, 224))
        _fill(rows, width, 940, height - 80, 70, width - 70, (18, 20, 28))
        _border(rows, width, 80, 520, 70, width - 70, accent, 6)
        _border(rows, width, 560, 900, 70, 430, ink)
        _border(rows, width, 560, 900, 470, width - 70, accent)
        _border(rows, width, 940, height - 80, 70, width - 70, ink)
        _text(rows, width, height, label or str(number), 120, 140, 34, (22, 26, 34))
        _text(rows, width, height, "COMICNEST", 110, 990, 14, (238, 214, 168))
        _text(rows, width, height, "%02d" % number, width - 230, height - 220, 42, ink)
        # Speech bubble.
        _fill(rows, width, 600, 720, 520, 790, (248, 245, 238))
        _border(rows, width, 600, 720, 520, 790, (20, 24, 32), 3)
        _text(rows, width, height, "HELLO", 560, 640, 8, (26, 30, 38))
    return _png(width, height, rows)


def _page_names(count=""):
    return ["%03d.png" % index for index in range(1, count + 1)]


def make_cbz(path, pages, prefix="") :
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, data in enumerate(pages, 1):
            archive.writestr("%s%03d.png" % (prefix, index), data)


def write_folder(path, pages):
    os.makedirs(path, exist_ok=True)
    for index, data in enumerate(pages, 1):
        with open(os.path.join(path, "%03d.png" % index), "wb") as handle:
            handle.write(data)


def _pdf(pages):
    objects = []
    font_id = 3
    pages_id = 2
    content_ids = []
    page_ids = []

    def add(value):
        objects.append(value)
        return len(objects)

    add(b"<< /Type /Catalog /Pages 2 0 R >>")  # 1
    add(b"")  # 2 pages, filled below
    add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")  # 3
    ids = {}
    for number in range(1, pages + 1):
        content = (
            "0.09 0.10 0.13 rg 0 0 900 1350 re f\n"
            "0.95 0.93 0.88 rg 70 880 760 380 re f\n"
            "0.20 0.24 0.32 rg 70 90 760 720 re f\n"
            "BT /F1 28 Tf 0.15 0.16 0.19 rg 100 1200 Td (COMICNEST) Tj ET\n"
            "BT /F1 170 Tf 0.95 0.92 0.85 rg 330 950 Td (%d) Tj ET\n"
            "BT /F1 22 Tf 0.90 0.78 0.55 rg 100 140 Td (A SAMPLE PDF CHAPTER) Tj ET\n"
        ) % number
        stream = content.encode("ascii")
        content_id = add(
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
        )
        page_id = add(
            (
                "<< /Type /Page /Parent %d 0 R /MediaBox [0 0 900 1350] "
                "/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
                % (pages_id, font_id, content_id)
            ).encode("ascii")
        )
        ids[number] = (page_id, content_id)
        page_ids.append(page_id)
    objects[pages_id - 1] = (
        ("<< /Type /Pages /Count %d /Kids [%s] >>" % (
            pages,
            " ".join("%d 0 R" % pid for pid in page_ids),
        )).encode("ascii")
    )

    output = io.BytesIO()
    output.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, body in enumerate(objects, 1):
        offsets.append(output.tell())
        output.write(("%d 0 obj\n" % index).encode("ascii"))
        output.write(body)
        output.write(b"\nendobj\n")
    xref = output.tell()
    output.write(("xref\n0 %d\n" % (len(objects) + 1)).encode("ascii"))
    output.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.write(("%010d 00000 n \n" % offset).encode("ascii"))
    output.write(
        ("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
            len(objects) + 1, xref,
        )).encode("ascii")
    )
    return output.getvalue()


def seed(root, reset=False):
    root = os.path.abspath(root)
    if reset and os.path.isdir(root):
        import shutil

        shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root, exist_ok=True)

    blue = [render_page(index, index) for index in range(1, 7)]
    paper = [
        render_page(index, index + 1) for index in range(1, 6)
    ] + [render_page(6, 2, wide=True, label="6A")]
    night = [render_page(index, index + 2) for index in range(1, 5)]

    write_folder(os.path.join(root, "Blue Hour", "Chapter 01"), blue)
    make_cbz(os.path.join(root, "Blue Hour", "Chapter 02.cbz"), blue)
    make_cbz(os.path.join(root, "Paper Moon", "Paper Moon v01.cbz"), paper)
    write_folder(os.path.join(root, "Night Signal"), night)

    pdf_dir = os.path.join(root, "Field Notes")
    os.makedirs(pdf_dir, exist_ok=True)
    with open(os.path.join(pdf_dir, "Field Notes v01.pdf"), "wb") as handle:
        handle.write(_pdf(6))

    print("demo library:", root)
    return root


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=DEFAULT_ROOT)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    seed(args.root, args.reset)


if __name__ == "__main__":
    main()
