"""JARVIS's icon, drawn in memory: a round orb shading from violet to teal. No image files are needed.

  ico(size)  a Windows icon file (the tray icon, and the shortcuts on Windows)
  png(size)  a PNG image (the Mac installer turns it into the app's icon with the Mac's own sips)
"""
from __future__ import annotations

import struct
import zlib


def _pixel(x: int, y: int, size: int) -> tuple[int, int, int, int]:
    """(red, green, blue, alpha) of one pixel, counted from the top-left corner."""
    centre = (size - 1) / 2
    dx, dy = (x - centre) / centre, (y - centre) / centre      # (y counts down from the top: the lower half is shaded)
    distance = (dx * dx + dy * dy) ** 0.5
    if distance > 1:
        return 0, 0, 0, 0
    mix = (dx + 1) / 2
    red, green, blue = int(143 + (90 - 143) * mix), int(128 + (209 - 128) * mix), int(255 + (230 - 255) * mix)
    shade = 1 - 0.35 * max(0.0, dy)
    alpha = 255 if distance < 0.92 else int(255 * (1 - distance) / 0.08)
    return int(red * shade), int(green * shade), int(blue * shade), max(0, alpha)


def ico(size: int = 32) -> bytes:
    """A Windows .ico holding one image of size x size pixels."""
    pixels = bytearray()
    for y in range(size - 1, -1, -1):                 # (a Windows bitmap is stored bottom row first)
        for x in range(size):
            red, green, blue, alpha = _pixel(x, y, size)
            pixels += bytes((blue, green, red, alpha))
    mask = b"\x00" * (((size + 31) // 32) * 4 * size)
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, len(pixels) + len(mask), 0, 0, 0, 0)
    image = header + bytes(pixels) + mask
    return struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(image), 22) + image


def png(size: int = 512) -> bytes:
    """A PNG image of size x size pixels, with transparency."""
    rows = bytearray()
    for y in range(size):
        rows.append(0)                                # (no filter on this row)
        for x in range(size):
            rows += bytes(_pixel(x, y, size))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b""))


if __name__ == "__main__":                            # python -m jcc.icon <file.png> [size]
    import sys
    with open(sys.argv[1], "wb") as out:
        out.write(png(int(sys.argv[2]) if len(sys.argv) > 2 else 512))
