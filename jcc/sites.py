"""Websites the owner connected (WordPress, WordPress.com, Shopify, Wix, Squarespace), and changes to them that are shown on this computer
first and go online only when the owner presses Publish.

A site stays connected until the owner removes it: nothing JARVIS meets (an error, the site being down, an expired
token) disconnects it. A Shopify app's token is renewed by itself; a key changed on the platform's side is replaced in
place with Replace key.

Only sites the owner added are ever touched, each through its own platform's API, with a key the owner created there
and kept in the system's key store (never in a file, a note or a log). The assistant can read what is on a site, and
it can stage a change: a new or edited post, page or product. A staged change is a preview on this computer, at
http://127.0.0.1:<port>/site-preview/<id>?k=<key> (the key is in the link only; without it the page is not shown),
showing what is on the site now beside what it would become. Nothing is sent to the site until the owner publishes it,
in the chat card or by saying so; then exactly what was previewed is sent.

What each platform's API allows (and so what JARVIS can change there):
- WordPress: posts and pages (create and edit), through the REST API with an application password. JARVIS finds the
  site's API itself (at /wp-json/, or at ?rest_route= on a site without "pretty" links, at the address WordPress calls
  its own) and says plainly what is in the way when it cannot get in: a wrong password or user name, application
  passwords switched off, a host that drops the sign-in, a firewall.
- WordPress.com (sites without hosting features): the same, through WordPress.com's own API, with a token WordPress.com
  gives for the owner's own app and an application password (see PLATFORMS["wordpresscom"]["how"]). A WordPress.com
  site with hosting features works like any WordPress site.
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
WPCOM_API = "https://public-api.wordpress.com"
KINDS = ("post", "page", "product")
PLATFORMS = {
    "wordpress": {"label": "WordPress", "kinds": ("post", "page"), "edits": True, "needs": ("user",),
                  "key": "Application password",
                  "how": "In WordPress: Users > Profile > Application Passwords. Type JARVIS as the name, press Add, and copy the password "
                         "it shows (your usual sign-in password does not work here). Give the user name you sign in with, not the "
                         "password's name. Use a user whose role may do what you want JARVIS to do (Editor, or Author for posts only). "
                         "A site on WordPress.com without hosting features: choose WordPress.com instead."},
    "wordpresscom": {"label": "WordPress.com", "kinds": ("post", "page"), "edits": True, "needs": ("user", "client"),
                     "key": "Application password (or your WordPress.com password, if two-step sign-in is off)",
                     "how": "For a site hosted on WordPress.com without hosting features (with them, choose WordPress). WordPress.com lets "
                            "only an app of your own in: 1. At developer.wordpress.com/apps, press Create New Application; any name and "
                            "description, your site's address as the website, https://localhost as the redirect address; then copy its "
                            "Client ID and Client Secret. 2. If two-step sign-in is on, make an application password at wordpress.com/me/"
                            "security/two-step (Application Passwords). 3. Give your WordPress.com user name."},
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
    if platform == "wordpress" and host.endswith(".wordpress.com") and not _local(host):
        raise SiteError("That is a site on WordPress.com: choose WordPress.com as the platform (WordPress is for sites with their own hosting).")
    path = re.sub(r"/(?:wp-admin|wp-login\.php|wp-json)(?:/.*)?$", "", parts.path.rstrip("/")) if platform == "wordpress" else ""
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


def _client(client_id: str, client_secret: str) -> str:
    """A WordPress.com app's client ID and secret, as they are kept in front of the password: "id:secret:"."""
    client_id, client_secret = str(client_id or "").strip(), str(client_secret or "").strip()
    if not re.fullmatch(r"\d{1,12}", client_id):
        raise SiteError("Give the Client ID of your app at developer.wordpress.com/apps (a number).")
    if not re.fullmatch(r"[A-Za-z0-9]{20,128}", client_secret):
        raise SiteError("Give the Client Secret of your app at developer.wordpress.com/apps.")
    return f"{client_id}:{client_secret}:"


def add(cfg, platform: str, address: str, key: str, user: str = "", site_id: str = "", name: str = "", check: bool = True,
        client_id: str = "", client_secret: str = "") -> dict:
    """Connect a site: its key goes into the key store, and the connection is tried before it is kept."""
    platform = str(platform or "").lower().strip()
    if platform not in PLATFORMS:
        raise SiteError("Choose WordPress, WordPress.com, Shopify, Wix or Squarespace.")
    key = str(key or "").strip()
    if not key or len(key) > 400 or any(ch in key for ch in "\r\n"):
        raise SiteError("Paste the " + PLATFORMS[platform]["key"].split(",")[0].split(" (")[0].lower() + ".")
    register_secret(key)
    row = {"id": _random.token_hex(5), "platform": platform, "address": clean_address(platform, address), "added": time.time()}
    if "client" in PLATFORMS[platform]["needs"]:
        key = _client(client_id, client_secret) + key
        register_secret(key)
    if "user" in PLATFORMS[platform]["needs"]:
        row["user"] = str(user or "").strip()[:80]
        if not row["user"]:
            raise SiteError("Give the user name you sign in with" + (" to WordPress.com." if platform == "wordpresscom" else
                                                                    ", which the application password belongs to (not the password's name)."))
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
            found = Remote(row, key).check()            # (for WordPress it also notes where the site's API is: row["route"], row["address"])
            if not name and found:
                row["name"] = " ".join(html.unescape(found).split())[:60]
    except SiteError:
        secrets.delete(_key_name(row["id"]))
        _TOKENS.pop(row["id"], None)
        raise
    if any(other["address"] == row["address"] and other["platform"] == platform for other in rows):
        secrets.delete(_key_name(row["id"]))
        raise SiteError("That site is connected already.")
    rows.append(row)
    _save(cfg, rows)
    return next(item for item in listing(cfg) if item["id"] == row["id"])


def rekey(cfg, site_id: str, key: str) -> dict:
    """A new key for a connected site (changed or withdrawn on the platform's side). Tried first; the old one stays if the
    new one is refused. The site, its name and its changes are untouched."""
    site = next((row for row in _saved(cfg) if row["id"] == site_id), None)
    if not site:
        raise SiteError("That site is not connected.")
    key = str(key or "").strip()
    if not key or len(key) > 400 or any(ch in key for ch in "\r\n"):
        raise SiteError("Paste the new " + PLATFORMS[site["platform"]]["key"].split(",")[0].split(" (")[0].lower() + ".")
    register_secret(key)
    if site["platform"] == "wordpresscom" and not re.match(r"\d{1,12}:[A-Za-z0-9]{20,128}:", key):
        client, secret, _ = _key(site).split(":", 2)       # (a new password: the app stays the same)
        key = f"{client}:{secret}:{key}"
        register_secret(key)
    _TOKENS.pop(site_id, None)
    before = dict(site)
    Remote(site, key).check()
    secrets.store(_key_name(site_id), key)
    if site != before:                                     # (where the site's API is, learned again)
        _save(cfg, [site if row["id"] == site_id else row for row in _saved(cfg)])
    return next(item for item in listing(cfg) if item["id"] == site_id)


def remove(cfg, site_id: str) -> bool:
    rows = _saved(cfg)
    kept = [row for row in rows if row["id"] != site_id]
    if len(kept) == len(rows):
        return False
    secrets.delete(_key_name(site_id))
    _save(cfg, kept)
    return True


# --------------------------------------------------------------------------------------- talking to a platform
class _OnlyReadsFollow(urllib.request.HTTPRedirectHandler):
    """A redirect is followed only when reading. Followed after a POST, urllib would ask again with GET and no body: the
    post would quietly become a look at the list. JARVIS says where the site wants it to go instead (see _call)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if req.get_method() not in ("GET", "HEAD"):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_OnlyReadsFollow)


def _agent() -> str:
    from jcc import __version__
    return f"Mozilla/5.0 (compatible; JARVIS/{__version__}; personal assistant)"   # (a bare "JARVIS" is turned away by some site firewalls)


def _decoded(raw: bytes) -> object:
    """The API's answer, or {"_page": the start of it} when it is a web page and not an API's answer."""
    text = raw.decode("utf-8", "replace").lstrip("﻿")
    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except ValueError:
        # (Some sites print a notice or blank lines before WordPress's answer: the answer itself still counts.)
        start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
        if start > 0:
            try:
                return json.loads(text[start:])
            except ValueError:
                pass
        text = re.sub(r"(?is)<(script|style)\b.*?</\1\s*>", " ", text)
        return {"_page": " ".join(re.sub(r"<[^>]+>", " ", text).split())[:300]}


def _fetch(method: str, url: str, headers: dict, body=None, form: bool = False) -> tuple[int, object]:
    data = None
    if body is not None:
        data = urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode()
        headers = {**headers, "Content-Type": "application/x-www-form-urlencoded" if form else "application/json"}
    request = urllib.request.Request(url, data=data, method=method, headers={"Accept": "application/json", "User-Agent": _agent(), **headers})
    try:
        with _OPENER.open(request, timeout=30) as answer:
            return answer.status, _decoded(answer.read(8_000_000))
    except urllib.error.HTTPError as problem:
        got = _decoded(problem.read(200_000) or b"")
        if isinstance(got, dict) and 300 <= problem.code < 400:
            got["_moved"] = str(problem.headers.get("Location") or "")[:300]
        if isinstance(got, dict) and problem.code == 401 and "basic" in str(problem.headers.get("WWW-Authenticate") or "").lower() and "_page" in got:
            got["_locked"] = True                         # (a password the web server itself asks for, in front of WordPress)
        return problem.code, got
    except (urllib.error.URLError, TimeoutError, OSError) as problem:
        from jcc import net
        raise SiteError("The site could not be reached: " + redact(net.reason(problem))[:300]) from None


FETCH = _fetch                    # (tests put a stand-in here)
_TOKENS: dict[str, tuple[str, float]] = {}       # Shopify and WordPress.com tokens exchanged for the owner's own app, until they expire
_ROUTES: dict[str, str] = {}                      # WordPress sites found to answer at ?rest_route= only since they were connected


def _said(status: int, answer) -> str:
    if isinstance(answer, dict):
        for field in ("message", "errors", "error_description", "error", "details"):
            if answer.get(field):
                return redact(json.dumps(answer[field]) if not isinstance(answer[field], str) else answer[field])[:200]
    return f"error {status}"


_NO_APP_PASSWORDS = ("Application passwords are switched off on this site, so it cannot let JARVIS in. They are on in WordPress unless "
                     "something turns them off: a security plugin (in Wordfence: Login Security > Settings, untick \"Disable WordPress "
                     "application passwords\"; others have a similar setting), the host, or the site not using https. Switch them on, "
                     "then make one in Users > Profile > Application Passwords.")
_LOCKED = ("The web server asks for a password of its own before WordPress is reached (a protected or staging site). An application "
           "password cannot pass that lock: lift it for /wp-json/, or connect the live site.")
_HEADER_LOST = ("The site did not see JARVIS's sign-in at all. Usually the web host drops it on the way to WordPress. The fix is one line, "
                "put by the host or in the site's .htaccess file, above WordPress's own lines: SetEnvIf Authorization \"(.*)\" "
                "HTTP_AUTHORIZATION=$1 . Many hosts' support will do it if asked to \"pass the Authorization header to PHP\". A security "
                "plugin that blocks the REST API for signed-out visitors can cause it too.")


def _wordpress_trouble(status: int, answer, site: dict) -> str:
    """What a WordPress refusal means, in words that say what to do. ("" when it is nothing special.)"""
    if not isinstance(answer, dict):
        return ""
    code, said, user = str(answer.get("code") or ""), redact(str(answer.get("message") or ""))[:160], site.get("user") or "that user"
    if answer.get("_locked"):
        return _LOCKED
    if code == "incorrect_password":
        return ("WordPress did not take that application password. Make a new one in Users > Profile > Application Passwords and paste it "
                "(type /sites, Replace key); the password you sign in with does not work here.")
    if code in ("invalid_username", "invalid_email"):
        return (f"WordPress has no user called {user}. Give the user name you sign in with (Users > Profile shows it), not the "
                "application password's name.")
    if code in ("application_passwords_disabled", "application_passwords_disabled_for_user"):
        return _NO_APP_PASSWORDS
    if code in ("rest_not_logged_in", "rest_forbidden_context", "rest_cannot_access", "rest_login_required") or \
            (status == 401 and code == "rest_forbidden"):
        return _HEADER_LOST
    if code in ("rest_cannot_create", "rest_cannot_publish", "rest_cannot_edit", "rest_cannot_edit_others"):
        return (f"WordPress says {user} may not do that ({said}). Give the user the Editor role (or Author, for posts only), or use "
                "an application password of a user who may.")
    if status in (403, 406, 409, 429, 503) and "_page" in answer:
        return ("The site's firewall turned JARVIS away before WordPress saw the request (error " + str(status) + ": a security plugin, "
                "the host's firewall or Cloudflare). Allow requests to /wp-json/ from this computer there, then try again.")
    if site.get("platform") == "wordpresscom" and status in (401, 403):
        return ("WordPress.com refused the request (" + (said or f"error {status}") + "). Check that the user name is the one that "
                "owns the site, and that the site is not one with hosting features (those connect as WordPress).")
    return ""


class Remote:
    """One site's API: what is there, and making a change. Every request goes to that site's own API host."""

    def __init__(self, site: dict, key: str):
        self.site, self.key, self.platform = site, key, site["platform"]

    # -- plumbing
    def _call(self, method: str, url: str, body=None, form: bool = False, headers: dict | None = None) -> object:
        status, answer = FETCH(method, url, {**self._auth(), **(headers or {})}, body, form)
        if status == 401 and self.platform in ("shopify", "wordpresscom") and self.site["id"] in _TOKENS:
            # The app's token ran out before the platform said it would: a new one, and the same request once more.
            _TOKENS.pop(self.site["id"], None)
            status, answer = FETCH(method, url, {**self._auth(), **(headers or {})}, body, form)
        if self.platform == "wordpress" and self._wrong_route(status, answer) and self.site.get("route") != "plain":
            # A site without "pretty" links has no /wp-json/: its API answers at ?rest_route= instead.
            plain = self._wp_url(url, "plain")
            if plain:
                again = FETCH(method, plain, {**self._auth(), **(headers or {})}, body, form)
                if not self._wrong_route(*again):
                    self.site["route"], (status, answer) = "plain", again
                    _ROUTES[self.site["id"]] = "plain"            # (remembered while JARVIS runs, so it is not asked twice each time)
        if isinstance(answer, dict) and answer.get("_moved") is not None and 300 <= status < 400:
            raise SiteError("The site sends JARVIS to another address (" + (answer["_moved"] or "no address given") + "). Remove the site in /sites "
                            "and add it again with the address WordPress uses (Settings > General shows it), so that what JARVIS sends is not lost on the way.")
        if self.platform in ("wordpress", "wordpresscom") and status >= 400:
            plain = _wordpress_trouble(status, answer, self.site)
            if plain:
                raise SiteError(plain)
        if status in (401, 403):
            raise SiteError(f"{self.site.get('name') or 'The site'} refused JARVIS's key ({_said(status, answer)}). The site stays connected: if the "
                            "key was changed or withdrawn on the site, type /sites and use Replace key; if it lacks a permission, give it that there.")
        if status == 404:
            raise SiteError("The site has no such item (or its API is switched off).")
        if status >= 400:
            raise SiteError(f"The site said no: {_said(status, answer)}")
        if isinstance(answer, dict) and "_page" in answer:
            raise SiteError("The site answered with a web page, not its API's answer (" + answer["_page"][:120] + "). Check the address" +
                            (", and that nothing on the site (a maintenance or coming-soon page, a security plugin) hides its API." if self.platform == "wordpress" else "."))
        return answer

    @staticmethod
    def _wrong_route(status: int, answer) -> bool:
        """The address reached no WordPress API at all (a web page, or a 404 that is not WordPress's own)."""
        page = isinstance(answer, dict) and "_page" in answer
        return (page and status < 500 and not answer.get("_locked")) or (status == 404 and isinstance(answer, dict) and answer.get("code") in (None, "rest_no_route") and
                                                                           not str(answer.get("message", "")).startswith("Invalid"))

    def _wp_url(self, url: str, route: str) -> str:
        """The same WordPress API address, written the other way ("plain": ?rest_route=, otherwise /wp-json/)."""
        address = self.site["address"]
        if route == "plain" and url.startswith(address + "/wp-json/"):
            path, _, query = url[len(address) + len("/wp-json"):].partition("?")
            return address + "/?rest_route=" + urllib.parse.quote(path, safe="/") + ("&" + query if query else "")
        return ""

    def _wp(self, tail: str) -> str:
        """The address of a WordPress API call, /wp/v2/<tail>, written the way this site takes it."""
        path, _, query = tail.partition("?")
        if self.platform == "wordpresscom":
            host = urllib.parse.urlsplit(self.site["address"]).hostname
            return f"{WPCOM_API}/wp/v2/sites/{host}/{path}" + ("?" + query if query else "")
        if self.site.get("route") == "plain":
            return self.site["address"] + "/?rest_route=" + urllib.parse.quote("/wp/v2/" + path, safe="/") + ("&" + query if query else "")
        return self.site["address"] + "/wp-json/wp/v2/" + path + ("?" + query if query else "")

    def _auth(self) -> dict:
        if self.platform == "wordpress":
            return {"Authorization": "Basic " + base64.b64encode(f"{self.site['user']}:{self.key}".encode()).decode()}
        if self.platform == "wordpresscom":
            return {"Authorization": "Bearer " + self._wpcom_token()}
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

    def _wpcom_token(self) -> str:
        """A WordPress.com token, given for the owner's own app, user name and (application) password. It lasts two weeks;
        a new one is asked for when it runs out."""
        held = _TOKENS.get(self.site["id"])
        if held and held[1] > time.time() + 60:
            return held[0]
        client, secret, password = (self.key.split(":", 2) + ["", ""])[:3]
        status, answer = FETCH("POST", WPCOM_API + "/oauth2/token", {},
                               {"client_id": client, "client_secret": secret, "grant_type": "password", "username": self.site.get("user", ""),
                                "password": password}, True)
        token = answer.get("access_token") if isinstance(answer, dict) else None
        if status >= 400 or not token:
            said = (answer.get("error_description") or answer.get("error") or "") if isinstance(answer, dict) else ""
            low = str(said).lower()
            if "client" in low:
                why = "the app's Client ID or Client Secret is not right (developer.wordpress.com/apps shows them)"
            elif "two" in low or "2fa" in low or "application password" in low or "two_step" in low:
                why = "two-step sign-in is on for this account, so it needs an application password (wordpress.com/me/security/two-step)"
            else:
                why = "the user name or password is not right" + (f" ({redact(str(said))[:120]})" if said else "")
            raise SiteError("WordPress.com did not let JARVIS in: " + why + ".")
        register_secret(token)
        _TOKENS[self.site["id"]] = (token, time.time() + min(float(answer.get("expires_in") or 1_209_600), 1_209_600))
        return token

    def _base(self) -> str:
        address = self.site["address"]
        return {"wordpress": address + "/wp-json/wp/v2", "wordpresscom": WPCOM_API + "/wp/v2/sites/" + str(urllib.parse.urlsplit(address).hostname),
                "shopify": f"{address}/admin/api/{SHOPIFY_VERSION}", "wix": WIX_API, "squarespace": SQUARESPACE_API}[self.platform]

    def _plural(self, kind: str) -> str:
        return {"post": "posts", "page": "pages", "product": "products"}[kind]

    # -- what JARVIS asks of a site
    def check(self) -> str:
        """Try the key; the site's own name if it says it."""
        base = self._base()
        if self.platform == "wordpress":
            return self._wordpress_check()
        if self.platform == "wordpresscom":
            self._call("GET", self._wp("posts?per_page=1&context=edit&_fields=id"))
            status, about = FETCH("GET", f"{WPCOM_API}/rest/v1.1/sites/{urllib.parse.urlsplit(self.site['address']).hostname}?fields=name", self._auth())
            return str(about.get("name") or "") if status < 400 and isinstance(about, dict) else ""
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
        if self.platform in ("wordpress", "wordpresscom"):
            got = self._call("GET", self._wp(f"{many}?per_page={limit}&context=edit&_fields=id,title,status,link"))
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
        if self.platform in ("wordpress", "wordpresscom"):
            row = self._call("GET", self._wp(f"{many}/{safe}?context=edit"))
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
        if self.platform in ("wordpress", "wordpresscom"):
            body = {k: v for k, v in (("title", fields.get("title")), ("content", fields.get("content"))) if v is not None}
            if not target:
                body["status"] = "publish"
            row = self._call("POST", self._wp(f"{many}/{safe}" if target else many), body)
            if not isinstance(row, dict) or not row.get("id"):
                raise SiteError("The site did not say that it saved the " + kind + ". Look at the site before trying again, so it is not posted twice.")
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

    def _wordpress_check(self) -> str:
        """Find the site's API, see that application passwords are on there, and try the key. The site's name if it says it.

        Where the API is: /wp-json/ normally, ?rest_route=/ on a site without "pretty" links. WordPress also says its own
        address there: when the one given differs only in "www." or http/https, its own is used, because a site that
        sends JARVIS on to another address loses what JARVIS posts on the way (see _OnlyReadsFollow)."""
        address = self.site["address"]
        status, index = FETCH("GET", address + "/wp-json/", self._auth())
        route = "pretty"
        if self._wrong_route(status, index) or not isinstance(index, dict) or status == 404:
            again = FETCH("GET", address + "/?rest_route=/", self._auth())
            if not self._wrong_route(*again) and isinstance(again[1], dict) and again[0] != 404:
                route, (status, index) = "plain", again
        if isinstance(index, dict) and index.get("_locked"):
            raise SiteError(_LOCKED)
        if self._wrong_route(status, index):
            raise SiteError("No WordPress answered at " + address + " (it gave " + ("a web page" if isinstance(index, dict) and "_page" in index else f"error {status}") +
                            "). Check the address: it is the one in WordPress's Settings > General, Site Address. If a plugin switches the "
                            "REST API off, JARVIS needs it on. A site on WordPress.com without hosting features: choose WordPress.com.")
        self.site["route"] = route
        name = ""
        if status < 400 and isinstance(index, dict):
            name = str(index.get("name") or "")
            home = urllib.parse.urlsplit(str(index.get("home") or ""))
            given = urllib.parse.urlsplit(address)
            if home.scheme == "https" and home.hostname and home.hostname.removeprefix("www.") == (given.hostname or "").removeprefix("www.") \
                    and (home.hostname, home.path.rstrip("/")) != (given.hostname, given.path.rstrip("/")):
                self.site["address"] = clean_address("wordpress", f"https://{home.hostname}{':' + str(home.port) if home.port else ''}{home.path}")
            ways = index.get("authentication")
            if isinstance(ways, (dict, list)) and "application-passwords" not in (ways if isinstance(ways, dict) else {}):
                raise SiteError(_NO_APP_PASSWORDS)
        me = self._call("GET", self._wp("users/me?context=edit&_fields=id,name,capabilities"))
        able = me.get("capabilities") if isinstance(me, dict) else None
        if isinstance(able, dict) and able and not (able.get("publish_posts") or able.get("edit_posts")):
            raise SiteError(f"The user {self.site.get('user')} may not write posts on this site (a Subscriber, perhaps). Give it the Author or "
                            "Editor role, or use another user's application password.")
        return name

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
    if site["id"] in _ROUTES:
        site["route"] = _ROUTES[site["id"]]
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
