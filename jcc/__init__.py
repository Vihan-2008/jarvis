"""JARVIS Command Center: Obsidian-based request router (free tiers only, cost always 0)."""

__version__ = "0.1.7"


def trust_store() -> str:
    """Give Python the Mac's own list of trusted certificates when it has none of its own.

    The Python from python.org for macOS comes without one, until its "Install Certificates" step is run, and then every
    secure web address fails with "certificate verify failed": the speech services, the AI services, the downloads. macOS
    keeps such a list itself, in /etc/ssl/cert.pem. Returns the file now used ("" when nothing was changed)."""
    import os
    import sys
    if sys.platform != "darwin" or os.environ.get("SSL_CERT_FILE"):
        return ""
    try:
        import ssl
        paths = ssl.get_default_verify_paths()
        if paths.cafile and os.path.isfile(paths.cafile):
            return ""
        if paths.capath and os.path.isdir(paths.capath) and any(name.endswith((".0", ".pem")) for name in os.listdir(paths.capath)):
            return ""
    except (ImportError, OSError, AttributeError):
        return ""
    if os.path.isfile("/etc/ssl/cert.pem"):
        os.environ["SSL_CERT_FILE"] = "/etc/ssl/cert.pem"
        return "/etc/ssl/cert.pem"
    return ""


trust_store()
