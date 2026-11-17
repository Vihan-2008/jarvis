"""Secure connections that work on a PC fresh out of the box, and plain words when one does not.

Windows keeps only some of the certificate authorities it trusts on the PC, and fetches the rest the first time a
browser (or another Windows program) meets a site that needs one. Python reads the PC's list but never asks Windows to
fetch, so on a new PC a site the browser opens fine (GitHub among them) can fail in JARVIS with "certificate verify
failed", which used to be reported as "check the internet connection".

So every secure connection Python opens with its defaults trusts the PC's own list (which keeps a company's or an
antivirus's own authority working) and, beside it, the list Mozilla keeps for Firefox, which comes with JARVIS
(jcc/data/cacert.pem, from the certifi package; see jcc/data/README.md). Nothing is trusted less than before, and no
check is ever switched off.
"""
from __future__ import annotations

import ssl
from pathlib import Path

BUNDLE = Path(__file__).with_name("data") / "cacert.pem"
_original = ssl.create_default_context
_bundle: str | None = None


def _bundled() -> str:
    global _bundle
    if _bundle is None:
        try:
            _bundle = BUNDLE.read_text("ascii", "ignore")
        except OSError:
            _bundle = ""
    return _bundle


def context() -> ssl.SSLContext:
    """A context for a secure connection: certificates checked against the PC's list and Mozilla's."""
    made = _original()
    extra = _bundled()
    if extra:
        try:
            made.load_verify_locations(cadata=extra)
        except (ssl.SSLError, ValueError):
            pass
    return made


def install() -> None:
    """Make `context` what Python uses when a connection is opened with its defaults (urllib, http.client). This is the
    way Python's own documentation (PEP 476) gives for changing the default; the check itself is left as it is."""
    ssl._create_default_https_context = context


def reason(problem: BaseException) -> str:
    """Why a connection failed, in words that say what to do: a certificate, the PC's clock, the address, a proxy, a firewall."""
    text = str(getattr(problem, "reason", None) or problem)
    low = text.lower()
    if "certificate" in low and ("not yet valid" in low or "expired" in low):
        return ("the site's certificate looked " + ("not yet valid" if "not yet" in low else "expired") +
                ", which usually means this PC's date or time is wrong. Set the clock right (Windows: Settings, Time, Set time automatically) and try again")
    if "certificate" in low or "ssl" in low and "verify" in low:
        return ("the secure connection could not be checked (" + text[:120] + "). Something on this network may be reading secure "
                "traffic (a school or company filter, or an antivirus's web shield); allowing JARVIS through it, or another network, fixes it")
    if "getaddrinfo" in low or "name or service not known" in low or "nodename nor servname" in low or "no address associated" in low or "11001" in low:
        return "its address could not be looked up. Check that this PC is online, or try another DNS server or network"
    if "timed out" in low or "10060" in low or "timeout" in low:
        return "it did not answer in time. A firewall or a slow network may be in the way; try again in a moment"
    if "refused" in low or "10061" in low:
        return "the connection was refused. A firewall, a VPN or a proxy on this PC may be blocking JARVIS"
    if "proxy" in low or "tunnel" in low:
        return "the proxy this PC uses did not let the connection through (" + text[:100] + ")"
    if "reset" in low or "10054" in low or "aborted" in low or "eof occurred" in low:
        return "the connection was cut. A firewall, antivirus or VPN may be blocking JARVIS; try again, or allow JARVIS through it"
    return text[:160] or "the connection failed"
