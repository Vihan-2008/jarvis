"""Read a public web page as plain text, safely.

Only ordinary internet addresses are fetched. Addresses on this computer or the home network
(including JARVIS itself) are refused, also when a page tries to redirect there.
"""
from __future__ import annotations

import ipaddress
import json
import re
import socket
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlparse

MAX_BYTES = 2_000_000
AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 JARVIS/1.0"
_BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "header", "footer", "blockquote",
          "pre", "table", "ul", "ol", "dd", "dt", "figcaption", "summary", "option"}
_SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "canvas", "form", "nav", "button", "select"}


def check_address(url: str, resolve=socket.getaddrinfo) -> str:
    """Return the URL if it points at the public internet; raise ValueError otherwise."""
    parsed = urlparse(str(url).strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only ordinary http and https web addresses can be read.")
    if parsed.port not in (None, 80, 443):
        raise ValueError("Only standard web ports can be read.")
    host = parsed.hostname.strip("[]")
    try:
        found = {info[4][0] for info in resolve(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
    except (OSError, UnicodeError):
        raise ValueError("That web address could not be found.") from None
    if not found:
        raise ValueError("That web address could not be found.")
    for raw in found:
        address = ipaddress.ip_address(raw.split("%")[0])
        mapped = getattr(address, "ipv4_mapped", None)
        if not (mapped or address).is_global:
            raise ValueError("JARVIS only reads public web pages, not addresses on this computer or your home network.")
    return parsed.geturl()


class _Redirects(urllib.request.HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_address(urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title, self.skip, self.in_title = "", 0, False
        self.links: list[tuple[str, str]] = []            # (what the link says, where it goes), in page order
        self.link, self.words = "", []

    def handle_starttag(self, tag, attrs):
        if tag == "a" and not self.link and not self.skip:      # (not the site's menus)
            self.link, self.words = str(dict(attrs).get("href") or "").strip(), []
        if tag in _SKIP:
            self.skip += 1
        elif tag == "title":
            self.in_title = True
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "a" and self.link:
            said = " ".join(" ".join(self.words).split())
            if said and len(self.links) < 400:
                self.links.append((said[:100], self.link))
            self.link = ""
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "title":
            self.in_title = False
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.link:
            self.words.append(data)
        if self.in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(data)


def page_links(parser: "_Text", base: str, limit: int = 40) -> list[tuple[str, str]]:
    """The page's links as (words, full address): ordinary web addresses only, each once, in page order."""
    seen, found = set(), []
    for said, href in parser.links:
        if href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            continue
        address = urljoin(base, href).split("#", 1)[0]
        if not re.match(r"^https?://[^/\s]+", address, re.I) or address in seen or len(address) > 400:
            continue
        seen.add(address)
        found.append((said, address))
        if len(found) >= limit:
            break
    return found


def find_videos(query: str, opener=None, limit: int = 6) -> list[dict]:
    """The first videos YouTube lists for a search: title, length, channel and address. No browser and no key are needed."""
    query = " ".join(str(query).split())
    if not query or len(query) > 150:
        raise ValueError("Say what to look for (up to 150 characters).")
    request = urllib.request.Request("https://www.youtube.com/results?search_query=" + quote(query),
                                     headers={"User-Agent": AGENT.rsplit(" JARVIS", 1)[0], "Accept-Language": "en", "Cookie": "CONSENT=YES+1; SOCS=CAI"})
    try:
        with (opener or urllib.request.build_opener(_Redirects)).open(request, timeout=15) as response:
            body = response.read(6_000_000).decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise ValueError("YouTube could not be searched just now.") from None
    found: list[dict] = []

    def walk(node, depth=0):
        if depth > 40 or len(found) >= limit:
            return
        if isinstance(node, dict):
            video = node.get("videoRenderer")
            if isinstance(video, dict) and re.fullmatch(r"[\w-]{11}", str(video.get("videoId", ""))):
                def words(part):
                    part = video.get(part)
                    if not isinstance(part, dict):
                        return ""
                    runs = part.get("runs")
                    return str(part.get("simpleText") or "".join(str(run.get("text", "")) for run in runs if isinstance(run, dict)) if isinstance(runs, list) else part.get("simpleText") or "")
                if not any(row["url"].endswith(video["videoId"]) for row in found):
                    found.append({"title": " ".join(words("title").split())[:160], "length": words("lengthText")[:12], "by": words("ownerText")[:60],
                                  "views": words("viewCountText")[:24], "url": "https://www.youtube.com/watch?v=" + video["videoId"]})
            for value in node.values():
                walk(value, depth + 1)
        elif isinstance(node, list):
            for value in node:
                walk(value, depth + 1)

    match = re.search(r"var ytInitialData = (\{.*?\});\s*</script>", body, re.S)
    if match:
        try:
            walk(json.loads(match.group(1)))
        except ValueError:
            pass
    if not found:      # the page is laid out differently today: the video numbers alone still let one be opened
        for ident in dict.fromkeys(re.findall(r'"videoId":"([\w-]{11})"', body)):
            found.append({"title": "", "length": "", "by": "", "views": "", "url": "https://www.youtube.com/watch?v=" + ident})
            if len(found) >= limit:
                break
    return found


def to_text(html: str) -> tuple[str, str]:
    parser = _Text()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - broken markup still yields whatever was read so far
        pass
    return _tidy(parser)


def _tidy(parser: "_Text") -> tuple[str, str]:
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(parser.parts))
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return " ".join(parser.title.split())[:200], text


def read_page(url: str, opener=None, limit: int = 15000) -> str:
    target = check_address(url)
    opener = opener or urllib.request.build_opener(_Redirects)
    request = urllib.request.Request(target, headers={"User-Agent": AGENT, "Accept": "text/html,text/plain;q=0.9,*/*;q=0.5",
                                                      "Accept-Language": "en"})
    try:
        with opener.open(request, timeout=15) as response:
            kind = (response.headers.get_content_type() or "").lower()
            if not (kind.startswith("text/") or kind in ("application/json", "application/xml", "application/xhtml+xml")):
                raise ValueError("That address is not a page of text (it is " + (kind or "an unknown type") + ").")
            raw = response.read(MAX_BYTES)
            charset = response.headers.get_content_charset() or "utf-8"
            final = response.geturl()
    except urllib.error.HTTPError as error:
        raise ValueError(f"The site answered with error {error.code}.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError("The page could not be loaded.") from None
    try:
        body = raw.decode(charset, errors="replace")
    except LookupError:
        body = raw.decode("utf-8", errors="replace")
    links = []
    if kind in ("text/html", "application/xhtml+xml"):
        parser = _Text()
        try:
            parser.feed(body)
        except Exception:  # noqa: BLE001 - broken markup still yields whatever was read so far
            pass
        title, text = _tidy(parser)
        links = page_links(parser, final)
    else:
        title, text = "", body
    if not text.strip() and not links:
        raise ValueError("The page has no readable text. It may need a real browser; try the Browser panel.")
    more = "\n\n[The page continues; only the first part is shown.]" if len(text) > limit else ""
    listed = ("\n\nLinks on this page (open one with open_website):\n" + "\n".join(f"- {said}: {address}" for said, address in links)) if links else ""
    return f"{title or 'Web page'}\n{final}\n\n{text[:limit]}{more}{listed}"
