"""Websites the owner connected (WordPress, Shopify, Wix, Squarespace), and changes to them that are shown on this computer
first and go online only when the owner presses Publish.

Only sites the owner added are ever touched, each through its own platform's API, with a key the owner created there
and kept in the system's key store (never in a file, a note or a log). The assistant can read what is on a site, and
it can stage a change: a new or edited post, page or product. A staged change is a preview on this computer, at
http://127.0.0.1:<port>/site-preview/<id>?k=<key> (the key is in the link only; without it the page is not shown),
showing what is on the site now beside what it would become. Nothing is sent to the site until the owner publishes it,
in the chat card or by saying so; then exactly what was previewed is sent.

What each platform's API allows (and so what JARVIS can change there):
- WordPress: posts and pages (create and edit), through the REST API with an application password.
- Shopify: products and pages (create and edit), through the Admin API with an access token, or with a Dev Dashboard
  app's client ID and secret (exchanged for a token).
- Wix: new blog posts, through the REST API with an API key and the site's ID.
- Squarespace: products (edit name, description and whether it is shown): its API reaches the store only, not pages or
  blog posts.
"""
from __future__ import annotations

import base64
import html
import json
import re
import secrets as _random
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from jcc import secrets
from jcc.redact import redact, register_secret
from jcc.vault import atomic_write, read_json

SHOPIFY_VERSION = "2026-07"
WIX_API = "https://www.wixapis.com"                  # (tests point these at a stand-in)
SQUARESPACE_API = "https://api.squarespace.com/1.0"
KINDS = ("post", "page", "product")
PLATFORMS = {
    "wordpress": {"label": "WordPress", "kinds": ("post", "page"), "edits": True, "needs": ("user",),
                  "key": "Application password",
                  "how": "In WordPress: Users > Profile > Application Passwords. Type JARVIS as the name, press Add, and copy the password "
                         "it shows. Give the same user name you sign in with. Use a user whose role may do what you want JARVIS to do (Editor, "
                         "or Author for posts only)."},
    "shopify": {"label": "Shopify", "kinds": ("product", "page"), "edits": True, "needs": (),
                "key": "Admin API access token (shpat_...), or the app's client ID and secret as id:secret",
                "how": "In Shopify admin: Settings > Apps > Develop apps > Build apps in Dev Dashboard. Make an app for this store with the "
                       "scopes read_products, write_products, read_content and write_content, install it, and copy its client ID and secret "
                       "(give them as id:secret). An older custom app's Admin API access token (shpat_...) works too."},
    "wix": {"label": "Wix", "kinds": ("post",), "edits": False, "needs": ("site_id",),
            "key": "API key",
            "how": "In Wix: your account's Settings > API Keys > Generate API Key, with the Wix Blog permissions, for this site only. "
                   "The site ID is in the address of the site's dashboard, after /dashboard/."},
    "squarespace": {"label": "Squarespace", "kinds": ("product",), "edits": True, "needs": (),
                    "key": "API key",
                    "how": "In Squarespace: Settings > Developer Tools > Developer API Keys > Generate Key, with the Products permission "
                           "(read and write). Squarespace's API reaches the store only: JARVIS can change products, not pages or blog posts."},
}
ID = re.compile(r"[a-z0-9]{6,24}")
CHANGE_ID = re.compile(r"[A-Za-z0-9_-]{8,40}")


class SiteError(ValueError):
    """Said to the owner as it is: plain words, no key in them."""


# ------------------------------------------------------------------------------------------------- the sites
def _file(cfg) -> Path:
    return cfg.state_dir / "sites.json"


def _saved(cfg) -> list[dict]:
    rows = read_json(_file(cfg), {}).get("sites", [])
    return [row for row in rows if isinstance(row, dict) and row.get("platform") in PLATFORMS and ID.fullmatch(str(row.get("id", "")))]


def _save(cfg, rows: list[dict]) -> None:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(_file(cfg), json.dumps({"sites": rows}, indent=1))


def listing(cfg) -> list[dict]:
    """The connected sites, with what JARVIS can change on each (never a key)."""
    return [{"id": row["id"], "name": row["name"], "platform": row["platform"], "label": PLATFORMS[row["platform"]]["label"],
             "address": row["address"], "kinds": list(PLATFORMS[row["platform"]]["kinds"]), "edits": PLATFORMS[row["platform"]]["edits"]}
            for row in _saved(cfg)]


def _local(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1") or host.endswith(".localhost")


def clean_address(platform: str, address: str) -> str:
    """The site's address as https://host[/path], checked for its platform."""
    text = str(address or "").strip()
    if not text:
        raise SiteError("Give the site's address.")
    if not re.match(r"^https?://", text, re.I):
        text = "https://" + text
    parts = urllib.parse.urlsplit(text)
    host = (parts.hostname or "").lower()
    if not host or "." not in host and not _local(host) or parts.username or parts.password:
        raise SiteError("That does not look like a website's address.")
    if parts.scheme.lower() == "http" and not _local(host):
        raise SiteError("Use the site's https:// address: a key is never sent over plain http.")
    if platform == "shopify" and not (host.endswith(".myshopify.com") or _local(host)):
        raise SiteError("For Shopify, give the store's myshopify.com address (Settings > Domains shows it), e.g. mystore.myshopify.com.")
    path = parts.path.rstrip("/") if platform == "wordpress" else ""
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme.lower()}://{host}{port}{path}"


def find(cfg, which: str) -> dict:
    """A connected site by its id, its name or its address. Only those: anything else is refused."""
    want = str(which or "").strip().lower()
    rows = _saved(cfg)
    if not rows:
        raise SiteError("No website is connected yet. Type /sites in the chat to connect one.")
    if not want and len(rows) == 1:
        return rows[0]
    for row in rows:
        if want in (row["id"], row["name"].lower(), row["address"].lower(), urllib.parse.urlsplit(row["address"]).hostname):
            return row
    near = [row for row in rows if want and (want in row["name"].lower() or want in row["address"].lower())]
    if len(near) == 1:
        return near[0]
    raise SiteError("That is not one of the connected websites (" + ", ".join(row["name"] for row in rows) + "). Only those can be changed.")


def _key_name(site_id: str) -> str:
    return "site-" + site_id


def _key(site: dict) -> str:
    value = (secrets._cred_read(_key_name(site["id"])) or "").strip()
    if not value:
        raise SiteError(f"The key for {site['name']} is missing from this computer's key store. Remove the site and add it again.")
    register_secret(value)
    return value


def add(cfg, platform: str, address: str, key: str, user: str = "", site_id: str = "", name: str = "", check: bool = True) -> dict:
    """Connect a site: its key goes into the key store, and the connection is tried before it is kept."""
    platform = str(platform or "").lower().strip()
    if platform not in PLATFORMS:
        raise SiteError("Choose WordPress, Shopify, Wix or Squarespace.")
    key = str(key or "").strip()
    if not key or len(key) > 400 or any(ch in key for ch in "\r\n"):
        raise SiteError("Paste the " + PLATFORMS[platform]["key"].split(",")[0].lower() + ".")
    register_secret(key)
    row = {"id": _random.token_hex(5), "platform": platform, "address": clean_address(platform, address), "added": time.time()}
    if "user" in PLATFORMS[platform]["needs"]:
        row["user"] = str(user or "").strip()[:80]
        if not row["user"]:
            raise SiteError("Give the WordPress user name the application password belongs to.")
    if "site_id" in PLATFORMS[platform]["needs"]:
        row["site_id"] = str(site_id or "").strip()
        if not re.fullmatch(r"[0-9a-fA-F-]{20,40}", row["site_id"]):
            raise SiteError("Give the Wix site ID: it is in the address of the site's dashboard, after /dashboard/.")
    row["name"] = (" ".join(str(name or "").split())[:60] or urllib.parse.urlsplit(row["address"]).hostname or platform)
    rows = _saved(cfg)
    if any(other["address"] == row["address"] and other["platform"] == platform for other in rows):
        raise SiteError("That site is connected already.")
    secrets.store(_key_name(row["id"]), key)
    try:
        if check:
            found = Remote(row, key).check()
            if not name and found:
                row["name"] = found[:60]
    except SiteError:
        secrets.delete(_key_name(row["id"]))
        raise
    rows.append(row)
    _save(cfg, rows)
    return next(item for item in listing(cfg) if item["id"] == row["id"])


def remove(cfg, site_id: str) -> bool:
    rows = _saved(cfg)
    kept = [row for row in rows if row["id"] != site_id]
    if len(kept) == len(rows):
        return False
    secrets.delete(_key_name(site_id))
    _save(cfg, kept)
    return True


# --------------------------------------------------------------------------------------- talking to a platform
def _fetch(method: str, url: str, headers: dict, body=None, form: bool = False) -> tuple[int, object]:
    data = None
    if body is not None:
        data = urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode()
        headers = {**headers, "Content-Type": "application/x-www-form-urlencoded" if form else "application/json"}
    request = urllib.request.Request(url, data=data, method=method, headers={"Accept": "application/json", "User-Agent": "JARVIS", **headers})
    try:
        with urllib.request.urlopen(request, timeout=30) as answer:
            raw = answer.read(8_000_000)
            return answer.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as problem:
        raw = problem.read(200_000)
        try:
            return problem.code, json.loads(raw)
        except ValueError:
            return problem.code, {"message": raw.decode("utf-8", "replace")[:300]}
    except (urllib.error.URLError, TimeoutError, OSError) as problem:
        raise SiteError("The site could not be reached: " + redact(str(getattr(problem, "reason", problem)))[:160]) from None
    except ValueError:
        raise SiteError("The site answered with something that is not its API's answer. Check the address.") from None


FETCH = _fetch                    # (tests put a stand-in here)
_TOKENS: dict[str, tuple[str, float]] = {}       # Shopify tokens exchanged from a client ID and secret, until they expire


def _said(status: int, answer) -> str:
    if isinstance(answer, dict):
        for field in ("message", "errors", "error_description", "error", "details"):
            if answer.get(field):
                return redact(json.dumps(answer[field]) if not isinstance(answer[field], str) else answer[field])[:200]
    return f"error {status}"


class Remote:
    """One site's API: what is there, and making a change. Every request goes to that site's own API host."""

    def __init__(self, site: dict, key: str):
        self.site, self.key, self.platform = site, key, site["platform"]

    # -- plumbing
    def _call(self, method: str, url: str, body=None, form: bool = False, headers: dict | None = None) -> object:
        status, answer = FETCH(method, url, {**self._auth(), **(headers or {})}, body, form)
        if status in (401, 403):
            raise SiteError(f"{self.site.get('name') or 'The site'} refused JARVIS's key ({_said(status, answer)}). Check that the key is right and "
                            "allowed to do this, then remove the site and add it again with a new key.")
        if status == 404:
            raise SiteError("The site has no such item (or its API is switched off).")
        if status >= 400:
            raise SiteError(f"The site said no: {_said(status, answer)}")
        return answer

    def _auth(self) -> dict:
        if self.platform == "wordpress":
            return {"Authorization": "Basic " + base64.b64encode(f"{self.site['user']}:{self.key}".encode()).decode()}
        if self.platform == "shopify":
            return {"X-Shopify-Access-Token": self._shopify_token()}
        if self.platform == "wix":
            return {"Authorization": self.key, "wix-site-id": self.site["site_id"]}
        return {"Authorization": "Bearer " + self.key}

    def _shopify_token(self) -> str:
        if self.key.startswith("shpat_") or ":" not in self.key:
            return self.key
        held = _TOKENS.get(self.site["id"])
        if held and held[1] > time.time() + 60:
            return held[0]
        client, _, secret = self.key.partition(":")
        status, answer = FETCH("POST", self.site["address"] + "/admin/oauth/access_token", {},
                               {"client_id": client.strip(), "client_secret": secret.strip(), "grant_type": "client_credentials"}, True)
        token = answer.get("access_token") if isinstance(answer, dict) else None
        if status >= 400 or not token:
            raise SiteError("Shopify did not give JARVIS a token for this app (" + _said(status, answer) + "). Check the client ID and secret, and that "
                            "the app is installed on this store.")
        register_secret(token)
        _TOKENS[self.site["id"]] = (token, time.time() + float(answer.get("expires_in") or 3600))
        return token

    def _base(self) -> str:
        address = self.site["address"]
        return {"wordpress": address + "/wp-json/wp/v2", "shopify": f"{address}/admin/api/{SHOPIFY_VERSION}",
                "wix": WIX_API, "squarespace": SQUARESPACE_API}[self.platform]

    def _plural(self, kind: str) -> str:
        return {"post": "posts", "page": "pages", "product": "products"}[kind]

    # -- what JARVIS asks of a site
    def check(self) -> str:
        """Try the key; the site's own name if it says it."""
        base = self._base()
        if self.platform == "wordpress":
            self._call("GET", base + "/posts?per_page=1&context=edit&_fields=id")
            return ""
        if self.platform == "shopify":
            shop = self._call("GET", base + "/shop.json")
            return str((shop.get("shop") or {}).get("name") or "") if isinstance(shop, dict) else ""
        if self.platform == "wix":
            got = self._call("GET", base + "/site-properties/v4/properties")
            return str(((got or {}).get("properties") or {}).get("siteDisplayName") or "") if isinstance(got, dict) else ""
        self._call("GET", base + "/commerce/products")
        return ""

    def items(self, kind: str, limit: int = 20) -> list[dict]:
        base, many = self._base(), self._plural(kind)
        if self.platform == "wordpress":
            got = self._call("GET", f"{base}/{many}?per_page={limit}&context=edit&_fields=id,title,status,link")
            return [{"id": str(row.get("id")), "title": _raw(row.get("title")), "status": row.get("status", ""), "url": row.get("link", "")}
                    for row in got if isinstance(row, dict)] if isinstance(got, list) else []
        if self.platform == "shopify":
            got = self._call("GET", f"{base}/{many}.json?limit={limit}")
            rows = got.get(many, []) if isinstance(got, dict) else []
            return [{"id": str(row.get("id")), "title": row.get("title", ""), "status": row.get("status") or ("published" if row.get("published_at") else "hidden"),
                     "url": self._shopify_url(kind, row.get("handle", ""))} for row in rows]
        if self.platform == "wix":
            got = self._call("GET", f"{base}/blog/v3/posts?paging.limit={limit}")
            return [{"id": str(row.get("id")), "title": row.get("title", ""), "status": "published",
                     "url": ((row.get("url") or {}).get("base", "") + (row.get("url") or {}).get("path", ""))} for row in (got or {}).get("posts", [])]
        got = self._call("GET", f"{base}/commerce/products")
        return [{"id": str(row.get("id")), "title": row.get("name", ""), "status": "shown" if row.get("isVisible") else "hidden", "url": row.get("url", "")}
                for row in (got or {}).get("products", [])][:limit]

    def item(self, kind: str, item_id: str) -> dict:
        base, many = self._base(), self._plural(kind)
        safe = urllib.parse.quote(str(item_id), safe="")
        if self.platform == "wordpress":
            row = self._call("GET", f"{base}/{many}/{safe}?context=edit")
            return {"id": str(row.get("id")), "title": _raw(row.get("title")), "content": _raw(row.get("content")), "status": row.get("status", ""),
                    "url": row.get("link", "")}
        if self.platform == "shopify":
            row = (self._call("GET", f"{base}/{many}/{safe}.json") or {}).get(kind) or {}
            variants = row.get("variants") or [{}]
            return {"id": str(row.get("id")), "title": row.get("title", ""), "content": row.get("body_html") or "",
                    "price": str(variants[0].get("price") or "") if kind == "product" else "", "variant": str(variants[0].get("id") or ""),
                    "url": self._shopify_url(kind, row.get("handle", ""))}
        if self.platform == "wix":
            raise SiteError("JARVIS can add new blog posts on Wix, not read or change existing ones.")
        rows = (self._call("GET", f"{base}/commerce/products/{safe}") or {}).get("products") or [{}]
        row = rows[0]
        return {"id": str(row.get("id")), "title": row.get("name", ""), "content": row.get("description") or "", "visible": bool(row.get("isVisible")),
                "url": row.get("url", "")}

    def apply(self, change: dict) -> dict:
        """Send exactly what was previewed. {id, url} of what is now on the site."""
        kind, fields, target = change["kind"], change["fields"], change.get("target") or ""
        base, many = self._base(), self._plural(kind)
        safe = urllib.parse.quote(str(target), safe="")
        if self.platform == "wordpress":
            body = {k: v for k, v in (("title", fields.get("title")), ("content", fields.get("content"))) if v is not None}
            if not target:
                body["status"] = "publish"
            row = self._call("POST", f"{base}/{many}/{safe}" if target else f"{base}/{many}", body)
            return {"id": str(row.get("id")), "url": row.get("link", "")}
        if self.platform == "shopify":
            body = {k: v for k, v in (("title", fields.get("title")), ("body_html", fields.get("content"))) if v is not None}
            if not target:
                if kind == "product":
                    body.update(status="active", variants=[{"price": fields.get("price") or "0.00"}])
                else:
                    body["published"] = True
                row = (self._call("POST", f"{base}/{many}.json", {kind: body}) or {}).get(kind) or {}
            else:
                row = (self._call("PUT", f"{base}/{many}/{safe}.json", {kind: {"id": int(target) if str(target).isdigit() else target, **body}}) or {}).get(kind) or {}
                if kind == "product" and fields.get("price") is not None and (change.get("before") or {}).get("variant"):
                    variant = change["before"]["variant"]
                    self._call("PUT", f"{base}/variants/{urllib.parse.quote(variant, safe='')}.json", {"variant": {"id": int(variant) if variant.isdigit() else variant,
                                                                                                                 "price": fields["price"]}})
            return {"id": str(row.get("id") or target), "url": self._shopify_url(kind, row.get("handle", ""))}
        if self.platform == "wix":
            author = self._wix_author()
            body = {"draftPost": {"title": fields.get("title") or "Untitled", "memberId": author, "richContent": ricos(fields.get("content") or "")},
                    "publish": True}
            row = (self._call("POST", f"{base}/blog/v3/draft-posts", body) or {}).get("draftPost") or {}
            link = (row.get("url") or {})
            return {"id": str(row.get("id") or ""), "url": (link.get("base", "") + link.get("path", "")) if isinstance(link, dict) else ""}
        body = {k: v for k, v in (("name", fields.get("title")), ("description", fields.get("content")), ("isVisible", fields.get("visible"))) if v is not None}
        row = self._call("POST", f"{base}/commerce/products/{safe}", body) or {}
        return {"id": str(row.get("id") or target), "url": row.get("url", "")}

    def _shopify_url(self, kind: str, handle: str) -> str:
        return f"{self.site['address']}/{'products' if kind == 'product' else 'pages'}/{handle}" if handle else ""

    def _wix_author(self) -> str:
        """Wix needs a post's author: the author of the site's own latest post."""
        got = self._call("GET", f"{self._base()}/blog/v3/posts?paging.limit=1")
        posts = (got or {}).get("posts") or []
        if not posts or not posts[0].get("memberId"):
            raise SiteError("Wix needs to know who writes the posts: publish one post on the site yourself first, then JARVIS writes as you.")
        return str(posts[0]["memberId"])


def _raw(value) -> str:
    return str(value.get("raw") if isinstance(value, dict) and "raw" in value else (value.get("rendered", "") if isinstance(value, dict) else value or ""))


def ricos(text_or_html: str) -> dict:
    """Wix's rich text, made of paragraphs of plain text (the HTML's tags are left out)."""
    text = re.sub(r"<(?:br|/p|/h[1-6]|/li|/div)\s*/?>", "\n", str(text_or_html), flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n|\n", text) if part.strip()] or [""]
    return {"nodes": [{"type": "PARAGRAPH", "id": f"p{n}", "nodes": [{"type": "TEXT", "id": f"t{n}", "nodes": [], "textData": {"text": part, "decorations": []}}],
                       "paragraphData": {}} for n, part in enumerate(paragraphs)]}


def remote(cfg, which: str) -> tuple[dict, Remote]:
    site = find(cfg, which)
    return site, Remote(site, _key(site))


def read(cfg, which: str, kind: str, item_id: str = "") -> dict:
    """What is on a site: its latest posts, pages or products, or one of them in full."""
    site, api = remote(cfg, which)
    kind = _kind(site, kind)
    if item_id:
        return {"site": site["name"], "kind": kind, "item": api.item(kind, item_id)}
    return {"site": site["name"], "kind": kind, "items": api.items(kind)}


def _kind(site: dict, kind: str) -> str:
    kind = str(kind or "").lower().rstrip("s")
    allowed = PLATFORMS[site["platform"]]["kinds"]
    if kind not in allowed:
        raise SiteError(f"On {PLATFORMS[site['platform']]['label']} JARVIS can work with " + " and ".join(k + "s" for k in allowed) + " only.")
    return kind


# ------------------------------------------------------------------------------- changes: preview, then publish
def _changes_dir(cfg) -> Path:
    return cfg.state_dir / "site-changes"


def _change_path(cfg, change_id: str) -> Path:
    if not CHANGE_ID.fullmatch(str(change_id or "")):
        raise SiteError("That change is not known.")
    return _changes_dir(cfg) / f"{change_id}.json"


def change(cfg, change_id: str) -> dict:
    found = read_json(_change_path(cfg, change_id), None)
    if not isinstance(found, dict):
        raise SiteError("That change is not known.")
    return found


def _keep(cfg, made: dict) -> None:
    _changes_dir(cfg).mkdir(parents=True, exist_ok=True)
    atomic_write(_change_path(cfg, made["id"]), json.dumps(made, indent=1))


def public(made: dict) -> dict:
    """What the window is told about a change (everything but the content, which the preview page shows)."""
    return {k: made.get(k) for k in ("id", "view", "site", "site_name", "platform", "kind", "action", "target", "summary", "state", "created", "result", "error")} | \
           {"title": (made.get("fields") or {}).get("title") or (made.get("before") or {}).get("title") or ""}


def stage(cfg, which: str, kind: str, summary: str, item_id: str = "", title: str | None = None, content: str | None = None,
          price: str | None = None, visible: bool | None = None) -> dict:
    """A change, made into a preview on this computer. Nothing is sent to the site."""
    site, api = remote(cfg, which)
    kind = _kind(site, kind)
    item_id = str(item_id or "").strip()
    if item_id and not PLATFORMS[site["platform"]]["edits"]:
        raise SiteError(f"On {PLATFORMS[site['platform']]['label']} JARVIS can add new {kind}s, not change existing ones.")
    if not item_id and site["platform"] == "squarespace":
        raise SiteError("On Squarespace JARVIS can change existing products (name, description, shown or hidden), not add new ones.")
    fields = {"title": None if title is None else " ".join(str(title).split())[:300],
              "content": None if content is None else str(content)[:200_000],
              "price": None if price is None or kind != "product" else _price(price),
              "visible": visible if isinstance(visible, bool) else None}
    if not item_id and not fields["title"]:
        raise SiteError(f"A new {kind} needs a title.")
    if item_id and all(value is None for value in fields.values()):
        raise SiteError("Say what to change: the title, the content" + (", the price" if kind == "product" else "") + ".")
    before = api.item(kind, item_id) if item_id else None
    made = {"id": _random.token_urlsafe(9), "view": _random.token_urlsafe(18), "site": site["id"], "site_name": site["name"], "platform": site["platform"],
            "address": site["address"], "kind": kind, "action": "update" if item_id else "create", "target": item_id,
            "fields": fields, "before": before, "summary": " ".join(str(summary or "").split())[:400] or f"{'Change' if item_id else 'New'} {kind}",
            "state": "preview", "created": time.time()}
    _keep(cfg, made)
    return made


def _price(value) -> str:
    text = str(value).strip().replace(",", "")
    if not re.fullmatch(r"\d{1,9}(?:\.\d{1,2})?", text.lstrip("$£€₹")):
        raise SiteError("Give the price as a number, e.g. 19.99.")
    return f"{float(text.lstrip('$£€₹')):.2f}"


def pending(cfg) -> list[dict]:
    """Changes waiting for the owner (newest first)."""
    found = []
    folder = _changes_dir(cfg)
    if folder.is_dir():
        for path in folder.glob("*.json"):
            made = read_json(path, None)
            if isinstance(made, dict) and made.get("state") == "preview":
                found.append(public(made))
    return sorted(found, key=lambda row: -float(row.get("created") or 0))[:30]


def publish(cfg, change_id: str) -> dict:
    """The owner said publish: exactly what was previewed goes to the site."""
    made = change(cfg, change_id)
    if made.get("state") != "preview":
        raise SiteError("That change was " + {"published": "published already", "discarded": "thrown away"}.get(made.get("state"), "already dealt with") + ".")
    site, api = remote(cfg, made["site"])
    if site["address"] != made.get("address"):
        raise SiteError("The site was connected again since this preview was made. Ask for the change again.")
    try:
        made["result"] = api.apply(made)
        made["state"] = "published"
    except SiteError as problem:
        made["error"] = str(problem)
        _keep(cfg, made)
        raise
    made["decided"] = time.time()
    made.pop("error", None)
    _keep(cfg, made)
    return public(made)


def discard(cfg, change_id: str) -> dict:
    made = change(cfg, change_id)
    if made.get("state") == "preview":
        made["state"], made["decided"] = "discarded", time.time()
        _keep(cfg, made)
    return public(made)


# ------------------------------------------------------------------------------------------- the preview page
PREVIEW_POLICY = ("default-src 'none'; style-src 'unsafe-inline'; img-src https: http://127.0.0.1:* data:; font-src https: data:; "
                  "frame-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'")


def preview_html(cfg, change_id: str, view: str) -> str | None:
    """The preview page, for whoever has its link (None otherwise). The content is shown in frames that run no script."""
    try:
        made = change(cfg, change_id)
    except SiteError:
        return None
    if not view or not _random.compare_digest(str(made.get("view", "")), str(view)):
        return None
    e = html.escape
    fields, before = made.get("fields") or {}, made.get("before") or {}
    label = PLATFORMS.get(made.get("platform"), {}).get("label", "")
    state = {"preview": "Not published yet: press Publish in JARVIS to put it on the site.", "published": "Published.",
             "discarded": "Thrown away: nothing was sent to the site."}.get(made.get("state"), "")

    def frame(markup: str) -> str:
        page = ("<!doctype html><meta charset='utf-8'><style>body{font:16px/1.6 system-ui,sans-serif;margin:16px;color:#111;background:#fff}"
                "img{max-width:100%;height:auto}</style>" + (markup or "<p><em>(empty)</em></p>"))
        return "<iframe sandbox title='content' srcdoc=\"" + e(page, quote=True) + "\"></iframe>"

    def side(heading: str, title, content, price=None, visible=None) -> str:
        rows = "<h2>" + e(heading) + "</h2><h3>" + e(title or "(no title)") + "</h3>"
        if price:
            rows += "<p class='meta'>Price: " + e(price) + "</p>"
        if visible is not None:
            rows += "<p class='meta'>" + ("Shown in the store" if visible else "Hidden from the store") + "</p>"
        return "<section>" + rows + frame(content or "") + "</section>"

    after_title = fields.get("title") if fields.get("title") is not None else before.get("title")
    after_content = fields.get("content") if fields.get("content") is not None else before.get("content")
    after_price = fields.get("price") if fields.get("price") is not None else before.get("price")
    after_visible = fields.get("visible") if fields.get("visible") is not None else before.get("visible")
    columns = (side("Now on the site", before.get("title"), before.get("content"), before.get("price"), before.get("visible")) if made.get("action") == "update" else "") + \
        side("After the change" if made.get("action") == "update" else "New " + made.get("kind", ""), after_title, after_content, after_price, after_visible)
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Preview · " + e(made.get("site_name", "")) + "</title><style>"
            "body{margin:0;font:15px/1.5 system-ui,sans-serif;background:#f4f4f6;color:#16161d}"
            "header{position:sticky;top:0;background:#16161d;color:#fff;padding:12px 18px}header b{color:#ffd166}"
            "header p{margin:4px 0 0;opacity:.85}main{display:flex;gap:16px;padding:16px;flex-wrap:wrap}"
            "section{flex:1 1 380px;background:#fff;border-radius:10px;padding:12px 16px;box-shadow:0 1px 3px rgba(0,0,0,.08)}"
            "h2{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:#666;margin:4px 0}h3{margin:4px 0 8px}.meta{color:#444;margin:0 0 8px}"
            "iframe{width:100%;height:62vh;border:1px solid #ddd;border-radius:8px;background:#fff}</style></head><body>"
            "<header><b>Preview on this computer</b> · " + e(label) + " · " + e(made.get("site_name", "")) + " (" + e(made.get("address", "")) + ")"
            "<p>" + e(made.get("summary", "")) + "</p><p>" + e(state) + "</p></header><main>" + columns + "</main></body></html>")
