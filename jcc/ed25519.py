"""Ed25519 signatures (RFC 8032), in plain Python: how JARVIS knows an update really comes from its maker.

Each release has a small list of its files and their fingerprints, signed with a private key that only the maker holds
(it never leaves the maker's own computer). Every copy of JARVIS has the matching public key built in, and installs an
update only when the list's signature checks out with it and the download matches its fingerprint in the list. Someone
who took over the download site, or the address it is fetched from, could not make such a signature.

This follows the reference code in RFC 8032, section 6, and is checked against that document's test values
(tests/test_ed25519.py). It is slow by the standards of a cryptography library (a signature is checked in a few tenths
of a second) and that is all it needs to be: it runs once per update. It is not meant to keep secrets from someone who
can time it; signing happens only on the maker's own computer.
"""
from __future__ import annotations

import hashlib

P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493          # the order of the group (q in RFC 8032)


def _inverse(x: int) -> int:
    return pow(x, P - 2, P)


D = -121665 * _inverse(121666) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)


def _sha512_int(data: bytes) -> int:
    return int.from_bytes(hashlib.sha512(data).digest(), "little")


def _add(a, b):
    """Two points (extended coordinates X, Y, Z, T) added."""
    p1 = (a[1] - a[0]) * (b[1] - b[0]) % P
    p2 = (a[1] + a[0]) * (b[1] + b[0]) % P
    c = 2 * a[3] * b[3] * D % P
    d = 2 * a[2] * b[2] % P
    e, f, g, h = p2 - p1, d - c, d + c, p2 + p1
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _multiply(scalar: int, point):
    out = (0, 1, 1, 0)                                             # the neutral point
    while scalar > 0:
        if scalar & 1:
            out = _add(out, point)
        point = _add(point, point)
        scalar >>= 1
    return out


def _equal(a, b) -> bool:
    return (a[0] * b[2] - b[0] * a[2]) % P == 0 and (a[1] * b[2] - b[1] * a[2]) % P == 0


def _recover_x(y: int, sign: int) -> int | None:
    if y >= P:
        return None
    x2 = (y * y - 1) * _inverse(D * y * y + 1) % P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P:
        x = x * SQRT_M1 % P
    if (x * x - x2) % P:
        return None
    if (x & 1) != sign:
        x = P - x
    return x


_GY = 4 * _inverse(5) % P
_GX = _recover_x(_GY, 0)
G = (_GX, _GY, 1, _GX * _GY % P)


def _compress(point) -> bytes:
    z = _inverse(point[2])
    x, y = point[0] * z % P, point[1] * z % P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _decompress(data: bytes):
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % P)


def _expand(seed: bytes) -> tuple[int, bytes]:
    if len(seed) != 32:
        raise ValueError("A private key is 32 bytes.")
    digest = hashlib.sha512(seed).digest()
    a = int.from_bytes(digest[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, digest[32:]


def public_key(seed: bytes) -> bytes:
    """The public key (32 bytes) that belongs to a private key (its 32-byte seed)."""
    a, _ = _expand(seed)
    return _compress(_multiply(a, G))


def sign(seed: bytes, message: bytes) -> bytes:
    """A signature (64 bytes) of the message with the private key."""
    a, prefix = _expand(seed)
    public = _compress(_multiply(a, G))
    r = _sha512_int(prefix + message) % L
    big_r = _compress(_multiply(r, G))
    h = _sha512_int(big_r + public + message) % L
    s = (r + h * a) % L
    return big_r + s.to_bytes(32, "little")


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    """Was the message signed with the private key that belongs to this public key? Never raises: False for anything odd."""
    try:
        if len(public) != 32 or len(signature) != 64:
            return False
        a = _decompress(bytes(public))
        r = _decompress(bytes(signature[:32]))
        if a is None or r is None:
            return False
        s = int.from_bytes(signature[32:], "little")
        if s >= L:
            return False
        h = _sha512_int(bytes(signature[:32]) + bytes(public) + bytes(message)) % L
        return _equal(_multiply(s, G), _add(r, _multiply(h, a)))
    except (TypeError, ValueError):
        return False
