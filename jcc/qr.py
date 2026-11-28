"""A small QR code maker (byte mode, error correction level M, versions 1 to 10), drawn as SVG.

Used by /phone to show the phone page's address and the pairing link as codes the phone can scan. Nothing is fetched:
JARVIS has no outside packages for this. Follows ISO/IEC 18004; the layout steps mirror Project Nayuki's reference
implementation (MIT), written again here for the few versions JARVIS needs.
"""
from __future__ import annotations

# Level M, per version: (error correction codewords per block, number of blocks).
_ECC_M = {1: (10, 1), 2: (16, 1), 3: (26, 1), 4: (18, 2), 5: (24, 2), 6: (16, 4), 7: (18, 4), 8: (22, 4), 9: (22, 5), 10: (26, 5)}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50]}


def _raw_modules(ver: int) -> int:
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        align = ver // 7 + 2
        result -= (25 * align - 10) * align - 55
        if ver >= 7:
            result -= 36
    return result


def _data_codewords(ver: int) -> int:
    ecc, blocks = _ECC_M[ver]
    return _raw_modules(ver) // 8 - ecc * blocks


def _gf_mul(x: int, y: int) -> int:
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z & 0xFF


def _rs_divisor(degree: int) -> list[int]:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def rs_remainder(data: list[int], degree: int) -> list[int]:
    divisor, result = _rs_divisor(degree), [0] * degree
    for byte in data:
        factor = byte ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


def format_bits(mask: int) -> int:
    data = (0 << 3) | mask                     # level M is 00
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    return ((data << 10) | rem) ^ 0x5412


def version_bits(ver: int) -> int:
    rem = ver
    for _ in range(12):
        rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
    return (ver << 12) | rem


def _codewords(data: bytes, ver: int) -> list[int]:
    capacity = _data_codewords(ver) * 8
    bits: list[int] = []
    push = lambda value, n: bits.extend((value >> i) & 1 for i in range(n - 1, -1, -1))   # noqa: E731
    push(0b0100, 4)
    push(len(data), 8 if ver < 10 else 16)
    for byte in data:
        push(byte, 8)
    push(0, min(4, capacity - len(bits)))
    push(0, (-len(bits)) % 8)
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(words) < capacity // 8:
        words.append(pad)
        pad ^= 0xEC ^ 0x11
    ecc_len, blocks = _ECC_M[ver]
    raw = _raw_modules(ver) // 8
    short_count, short_len = blocks - raw % blocks, raw // blocks
    split, at = [], 0
    for i in range(blocks):
        size = short_len - ecc_len + (0 if i < short_count else 1)
        split.append(words[at:at + size])
        at += size
    eccs = [rs_remainder(block, ecc_len) for block in split]
    out = [block[i] for i in range(max(map(len, split))) for block in split if i < len(block)]
    return out + [ecc[i] for i in range(ecc_len) for ecc in eccs]


def _mask_on(mask: int, x: int, y: int) -> bool:
    return [(x + y) % 2 == 0, y % 2 == 0, x % 3 == 0, (x + y) % 3 == 0, (x // 3 + y // 2) % 2 == 0,
            x * y % 2 + x * y % 3 == 0, (x * y % 2 + x * y % 3) % 2 == 0, ((x + y) % 2 + x * y % 3) % 2 == 0][mask]


class _Grid:
    def __init__(self, ver: int):
        self.ver, self.size = ver, ver * 4 + 17
        self.dark = [[False] * self.size for _ in range(self.size)]
        self.fixed = [[False] * self.size for _ in range(self.size)]

    def put(self, x: int, y: int, dark: bool) -> None:
        self.dark[y][x], self.fixed[y][x] = bool(dark), True

    def patterns(self) -> None:
        n = self.size
        for i in range(n):
            self.put(6, i, i % 2 == 0)
            self.put(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    if 0 <= cx + dx < n and 0 <= cy + dy < n:
                        self.put(cx + dx, cy + dy, max(abs(dx), abs(dy)) not in (2, 4))
        spots, last = _ALIGN[self.ver], len(_ALIGN[self.ver]) - 1
        for i, ax in enumerate(spots):
            for j, ay in enumerate(spots):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.put(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
        self.format(0)
        if self.ver >= 7:
            bits = version_bits(self.ver)
            for i in range(18):
                a, b, on = n - 11 + i % 3, i // 3, (bits >> i) & 1
                self.put(a, b, on)
                self.put(b, a, on)

    def format(self, mask: int) -> None:
        bits, n = format_bits(mask), self.size
        bit = lambda i: (bits >> i) & 1                        # noqa: E731
        for i in range(6):
            self.put(8, i, bit(i))
        self.put(8, 7, bit(6))
        self.put(8, 8, bit(7))
        self.put(7, 8, bit(8))
        for i in range(9, 15):
            self.put(14 - i, 8, bit(i))
        for i in range(8):
            self.put(n - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.put(8, n - 15 + i, bit(i))
        self.put(8, n - 8, True)

    def order(self) -> list[tuple[int, int]]:
        """The free modules in the order the codewords' bits fill them."""
        n, out, right = self.size, [], self.size - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(n):
                for j in range(2):
                    x = right - j
                    y = n - 1 - vert if ((right + 1) & 2) == 0 else vert
                    if not self.fixed[y][x]:
                        out.append((x, y))
            right -= 2
        return out

    def fill(self, words: list[int]) -> None:
        for i, (x, y) in enumerate(self.order()):
            self.dark[y][x] = i < len(words) * 8 and bool((words[i >> 3] >> (7 - (i & 7))) & 1)

    def apply(self, mask: int) -> None:
        for y in range(self.size):
            for x in range(self.size):
                if not self.fixed[y][x] and _mask_on(mask, x, y):
                    self.dark[y][x] = not self.dark[y][x]

    def penalty(self) -> int:
        n, score, dark = self.size, 0, self.dark
        lines = dark + [[dark[y][x] for y in range(n)] for x in range(n)]
        finder = ([True, False, True, True, True, False, True, False, False, False, False],
                  [False, False, False, False, True, False, True, True, True, False, True])
        for line in lines:
            run = 1
            for i in range(1, n + 1):
                if i < n and line[i] == line[i - 1]:
                    run += 1
                else:
                    score += run - 2 if run >= 5 else 0
                    run = 1
            for i in range(n - 10):
                if line[i:i + 11] in finder:
                    score += 40
        for y in range(n - 1):
            for x in range(n - 1):
                if dark[y][x] == dark[y][x + 1] == dark[y + 1][x] == dark[y + 1][x + 1]:
                    score += 3
        share = sum(map(sum, dark)) * 100 // (n * n)
        return score + abs(share - 50) // 5 * 10


def matrix(text: str) -> list[list[bool]]:
    data = text.encode("utf-8")
    ver = next((v for v in _ECC_M if len(data) <= _data_codewords(v) - (2 if v < 10 else 3)), None)
    if ver is None:
        raise ValueError("Too long for a QR code here.")
    words = _codewords(data, ver)
    best = None
    for mask in range(8):
        grid = _Grid(ver)
        grid.patterns()
        grid.fill(words)
        grid.apply(mask)
        grid.format(mask)
        score = grid.penalty()
        if best is None or score < best[0]:
            best = (score, grid)
    return best[1].dark


def svg(text: str, label: str = "QR code") -> str:
    grid = matrix(text)
    n, quiet = len(grid), 4
    cells = "".join(f"M{x + quiet} {y + quiet}h1v1h-1z" for y, row in enumerate(grid) for x, on in enumerate(row) if on)
    side = n + 2 * quiet
    safe = label.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {side} {side}" role="img" aria-label="{safe}" shape-rendering="crispEdges">'
            f'<rect width="{side}" height="{side}" fill="#fff"/><path d="{cells}" fill="#000"/></svg>')
