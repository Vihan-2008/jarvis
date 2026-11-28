"""Setting up the phone app in the owner's own accounts, in one go: the relay in their Supabase project, the page on
their Cloudflare account. Nothing runs on servers of the JARVIS project, and nothing is shared between users.

- The Supabase token is used for this run only and never stored (it can reach the whole Supabase account).
- The Cloudflare token is kept only when it is limited to Workers Scripts (JARVIS redeploys the page when it updates).
  A broader one is refused unless the owner says to use it once and forget it.
- Every file deployed is hashed, so the laptop can see if the page was changed outside JARVIS (check()).
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets as _random
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from jcc import phone, secrets
from jcc.redact import redact

SUPABASE = "https://api.supabase.com/v1"
CLOUDFLARE = "https://api.cloudflare.com/client/v4"
HERE = Path(__file__).resolve().parent.parent / "cloud" / "phone"
FUNCTION_FILES = ("index.ts", "relay.js", "webpush.js", "docx.js")
APP_FILES = ("index.html", "app.js", "proto.js", "md.js", "app.css", "manifest.webmanifest", "sw.js")
SLUG = "jarvis-phone"
CF_SECRET = "phone-cloudflare"
TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".webmanifest": "application/manifest+json",
         ".png": "image/png", ".json": "application/json"}


class SetupError(Exception):
    """Said to the owner as it is: what went wrong and what to do."""


def http(method: str, url: str, headers: dict | None = None, data: bytes | None = None, timeout: float = 60):
    request = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": "jarvis-setup/1", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(20_000_000)
    except urllib.error.HTTPError as e:
        return e.code, e.read(200_000)
    except (urllib.error.URLError, OSError) as e:
        raise SetupError("No connection to set things up: " + str(e)[:120]) from e


def multipart(parts: list[tuple[str, str | None, str, bytes]]) -> tuple[str, bytes]:
    """(field, filename or None, content type, bytes) -> (Content-Type header, body)."""
    boundary = "jarvis" + uuid.uuid4().hex
    out = bytearray()
    for field, filename, kind, data in parts:
        out += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"".encode()
        if filename:
            out += f"; filename=\"{filename}\"".encode()
        out += f"\r\nContent-Type: {kind}\r\n\r\n".encode() + data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return f"multipart/form-data; boundary={boundary}", bytes(out)


def page_headers(relay_origin: str) -> dict[str, str]:
    """The headers that keep the page to itself and the relay."""
    csp = (f"default-src 'self'; connect-src 'self' {relay_origin}; img-src 'self' blob: data:; media-src 'self' blob:; "
           "frame-ancestors 'none'; base-uri 'none'; form-action 'none'; object-src 'none'")
    return {"Content-Security-Policy": csp, "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
            "Permissions-Policy": "camera=(self), microphone=(self), geolocation=()", "Cross-Origin-Opener-Policy": "same-origin"}


def headers_rule(relay_origin: str) -> str:
    """The same headers as a Cloudflare _headers rule for every file (assets.config._headers)."""
    return "/*\n" + "".join(f"  {k}: {v}\n" for k, v in page_headers(relay_origin).items())


def worker_script(relay_origin: str) -> str:
    """The page's tiny Worker: runs before any file is served (run_worker_first) and adds the page's headers."""
    headers = page_headers(relay_origin)
    return ("export default {\n  async fetch(request, env) {\n    const response = await env.ASSETS.fetch(request);\n"
            "    const out = new Response(response.body, response);\n"
            f"    for (const [k, v] of Object.entries({json.dumps(headers)})) out.headers.set(k, v);\n"
            "    return out;\n  }\n};\n")


def asset_hash(data: bytes, path: str) -> str:
    """Cloudflare's own hash for an asset: SHA-256 of the base64 content and the extension, cut to 32 characters."""
    ext = Path(path).suffix.lstrip(".")
    return hashlib.sha256((base64.b64encode(data).decode() + ext).encode()).hexdigest()[:32]


def page_files(relay_url: str, vapid: str, version: str) -> dict[str, bytes]:
    from jcc import icon
    files = {"/" + name: (HERE / "app" / name).read_bytes() for name in APP_FILES}
    files["/sw.js"] = files["/sw.js"].replace(b"__VERSION__", version.encode())
    files["/icon-192.png"], files["/icon-512.png"] = icon.png(192), icon.png(512)
    files["/config.json"] = json.dumps({"relay": relay_url, "vapid": vapid, "version": version}).encode()
    return files


class Setup:
    def __init__(self, cfg, request=http, clock=time.time, sleep=time.sleep):
        self.cfg, self.request, self.clock, self.sleep = cfg, request, clock, sleep

    # ------------------------------------------------------------------ the two APIs
    def _json(self, method, url, token, body=None, extra=None, ok=(200, 201)):
        headers = {"Authorization": "Bearer " + token, **(extra or {})}
        data = None
        if body is not None and not isinstance(body, bytes):
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        elif isinstance(body, bytes):
            data = body
        status, raw = self.request(method, url, headers, data)
        try:
            value = json.loads(raw or b"null")
        except ValueError:
            value = {"raw": raw[:200].decode("utf-8", "replace")}
        if status not in ok:
            raise SetupError(self._problem(url, status, value))
        return value

    @staticmethod
    def _problem(url, status, value):
        where = "Cloudflare" if url.startswith(CLOUDFLARE) else "Supabase"
        if status in (401, 403):
            return f"{where} did not accept that token ({status}). Make a new one as the steps say, and paste it again."
        detail = value.get("message") if isinstance(value, dict) else None
        if isinstance(value, dict) and isinstance(value.get("errors"), list) and value["errors"]:
            detail = value["errors"][0].get("message")
        return f"{where} answered {status}: " + redact(str(detail or value))[:200]

    def cf(self, method, path, token, body=None, extra=None):
        value = self._json(method, CLOUDFLARE + path, token, body, extra)
        if isinstance(value, dict) and value.get("success") is False:
            raise SetupError(self._problem(CLOUDFLARE + path, 400, value))
        return value.get("result") if isinstance(value, dict) else value

    def sb(self, method, path, token, body=None, ok=(200, 201)):
        return self._json(method, SUPABASE + path, token, body, ok=ok)

    # ------------------------------------------------------------------ Cloudflare
    def cloudflare(self, token: str) -> dict:
        accounts = self.cf("GET", "/accounts", token) or []
        if not accounts:
            raise SetupError("That Cloudflare token can't see any account. Make it from the 'Edit Cloudflare Workers' template.")
        account = accounts[0]["id"]
        url = CLOUDFLARE + f"/accounts/{account}/workers/subdomain"
        status, raw = self.request("GET", url, {"Authorization": "Bearer " + token}, None)
        try:
            value = json.loads(raw or b"null")
        except ValueError:
            value = None
        if status == 200 and isinstance(value, dict) and value.get("success") is not False:
            sub = (value.get("result") or {}).get("subdomain")
        elif status == 404:
            sub = None                                          # none yet: one is made below
        else:
            raise SetupError(self._problem(url, status, value if isinstance(value, dict) else {}))
        if not sub:
            sub = "jarvis-" + _random.token_hex(4)
            self.cf("PUT", f"/accounts/{account}/workers/subdomain", token, {"subdomain": sub})
        return {"account": account, "subdomain": sub}

    def broad(self, token: str) -> bool:
        """Whether the token can do more than the "Edit Cloudflare Workers" template allows: list DNS zones, read API tokens
        or use Pages. No answer that is not a plain refusal counts as narrow: a busy or odd reply stops setup instead."""
        def look(path: str):
            status, raw = self.request("GET", CLOUDFLARE + path, {"Authorization": "Bearer " + token}, None)
            try:
                value = json.loads(raw or b"null")
            except ValueError:
                value = None
            if status in (401, 403):
                return False, value                             # refused: this power is not in the token
            if status == 200 and isinstance(value, dict) and value.get("success") is True:
                return True, value
            raise SetupError("Couldn't check what that Cloudflare token can do (Cloudflare answered " + str(status) + "). Try again in a minute.")
        can, zones = look("/zones?per_page=1")
        if can and zones.get("result"):
            return True
        accounts = self.cf("GET", "/accounts", token) or []
        for account in accounts[:1]:
            for path in (f"/accounts/{account['id']}/tokens", f"/accounts/{account['id']}/pages/projects"):
                if look(path)[0]:
                    return True
        status, raw = self.request("GET", CLOUDFLARE + "/user/tokens/verify", {"Authorization": "Bearer " + token}, None)
        try:
            ident = (json.loads(raw or b"null") or {}).get("result", {}).get("id") if status == 200 else None
        except (ValueError, AttributeError):
            ident = None
        if ident and look(f"/user/tokens/{ident}")[0]:
            return True                                         # (a token that can read its own permissions can manage tokens)
        return False

    def deploy_page(self, token: str, account: str, name: str, files: dict[str, bytes], relay_origin: str) -> dict[str, str]:
        manifest = {path: {"hash": asset_hash(data, path), "size": len(data)} for path, data in files.items()}
        session = self.cf("POST", f"/accounts/{account}/workers/scripts/{name}/assets-upload-session", token, {"manifest": manifest})
        upload, by_hash = session["jwt"], {v["hash"]: (p, files[p]) for p, v in manifest.items()}
        buckets = session.get("buckets") or []
        finished = upload if not buckets else None          # (nothing to send: the session's token already finishes it)
        for bucket in buckets:
            kind, body = multipart([(h, h, TYPES.get(Path(by_hash[h][0]).suffix, "application/octet-stream"),
                                     base64.b64encode(by_hash[h][1])) for h in bucket])
            done = self._json("POST", CLOUDFLARE + f"/accounts/{account}/workers/assets/upload?base64=true", upload, body,
                              {"Content-Type": kind}, ok=(200, 201, 202))
            if isinstance(done, dict) and done.get("success") is False:
                raise SetupError(self._problem(CLOUDFLARE + "/workers/assets/upload", 400, done))
            finished = ((done.get("result") or {}).get("jwt") if isinstance(done, dict) else None) or finished
        if not finished:
            raise SetupError("Cloudflare didn't finish taking the page's files. Try again in a minute.")
        metadata = {"main_module": "worker.js", "compatibility_date": "2025-06-01", "bindings": [{"type": "assets", "name": "ASSETS"}],
                    "assets": {"jwt": finished, "config": {"not_found_handling": "single-page-application", "run_worker_first": True,
                                                           "_headers": headers_rule(relay_origin)}}}
        kind, body = multipart([("metadata", None, "application/json", json.dumps(metadata).encode()),
                                ("worker.js", "worker.js", "application/javascript+module", worker_script(relay_origin).encode())])
        self.cf("PUT", f"/accounts/{account}/workers/scripts/{name}", token, body, {"Content-Type": kind})
        self.cf("POST", f"/accounts/{account}/workers/scripts/{name}/subdomain", token, {"enabled": True, "previews_enabled": False})
        return {path: hashlib.sha256(data).hexdigest() for path, data in files.items()}

    # ------------------------------------------------------------------ Supabase
    def project(self, token: str, ref: str = "", region: str = "ap-south-1") -> str:
        projects = self.sb("GET", "/projects", token) or []
        if ref:
            if not any(p.get("id") == ref or p.get("ref") == ref for p in projects):
                raise SetupError("That Supabase project isn't in this account.")
            return ref
        known = settings_ref(self.cfg)
        for p in projects:
            # (only the project this computer made before: one that just has a familiar name may hold someone's other work)
            if known and (p.get("ref") or p.get("id")) == known:
                return known
        orgs = self.sb("GET", "/organizations", token) or []
        if not orgs:
            raise SetupError("This Supabase account has no organization yet. Open supabase.com once, then try again.")
        body = {"name": "jarvis-phone", "db_pass": _random.token_urlsafe(24), "region_selection": {"type": "specific", "code": region}}
        if orgs[0].get("slug"):
            body["organization_slug"] = orgs[0]["slug"]
        else:
            body["organization_id"] = orgs[0]["id"]             # (an older answer without a slug)
        made = self.sb("POST", "/projects", token, body)
        ref = made.get("ref") or made.get("id")
        for _ in range(60):                                     # a new project takes a minute or two to start
            if str((self.sb("GET", f"/projects/{ref}", token) or {}).get("status", "")).startswith("ACTIVE"):
                return ref
            self.sleep(5)
        raise SetupError("The new Supabase project is still starting. Try again in a few minutes.")

    def install_relay(self, token: str, ref: str, origin: str) -> str:
        self.sb("POST", f"/projects/{ref}/database/query", token, {"query": (HERE / "schema.sql").read_text("utf-8")})
        have = {s.get("name") for s in (self.sb("GET", f"/projects/{ref}/secrets", token) or [])}
        device = secrets.get(phone.DEVICE_SECRET) if "JARVIS_DEVICE_HASH" in have else None
        device = device or _random.token_urlsafe(40)
        values = [{"name": "JARVIS_DEVICE_HASH", "value": hashlib.sha256(device.encode()).hexdigest()},
                  {"name": "JARVIS_APP_ORIGIN", "value": origin}]
        if "JARVIS_DATA_KEY" not in have:                       # never replaced: what is sealed with it would be lost
            values.append({"name": "JARVIS_DATA_KEY", "value": base64.b64encode(_random.token_bytes(32)).decode()})
        self.sb("POST", f"/projects/{ref}/secrets", token, values)
        meta = {"entrypoint_path": "index.ts", "name": SLUG, "verify_jwt": False}
        kind, body = multipart([("metadata", None, "application/json", json.dumps(meta).encode())]
                               + [("file", name, "application/typescript" if name.endswith(".ts") else "application/javascript",
                                   (HERE / name).read_bytes()) for name in FUNCTION_FILES])
        self._json("POST", SUPABASE + f"/projects/{ref}/functions/deploy?slug={SLUG}", token, body, {"Content-Type": kind})
        return device

    # ------------------------------------------------------------------ all of it
    def run(self, supabase_token: str, cloudflare_token: str, region: str = "ap-south-1", use_broad_once: bool = False, relay_status=None) -> dict:
        supabase_token, cloudflare_token = supabase_token.strip(), cloudflare_token.strip()
        if not re.fullmatch(r"sbp_[A-Za-z0-9_]{20,}", supabase_token):
            raise SetupError("That doesn't look like a Supabase access token (it starts with sbp_).")
        if len(cloudflare_token) < 30:
            raise SetupError("That doesn't look like a Cloudflare API token.")
        is_broad = self.broad(cloudflare_token)
        if is_broad and not use_broad_once:
            raise SetupError("BROAD_TOKEN")
        cf = self.cloudflare(cloudflare_token)
        saved = phone.settings(self.cfg)
        name = saved.get("page_name") or "jarvis-" + "".join(_random.choice("abcdefghijkmnpqrstuvwxyz23456789") for _ in range(8))
        origin = f"https://{name}.{cf['subdomain']}.workers.dev"
        ref = self.project(supabase_token, region=region)
        device = self.install_relay(supabase_token, ref, origin)
        relay_url = f"https://{ref}.supabase.co/functions/v1/{SLUG}"
        phone.configure(self.cfg, relay_url, origin, device)
        status = None
        for attempt in range(12):                               # the function takes a few seconds to go live
            try:
                status = (relay_status or (lambda: phone.relay_for(self.cfg, phone.http_post).call("status")))()
                break
            except (phone.RelayError, OSError, ValueError):
                if attempt == 11:
                    raise SetupError("The relay was deployed but does not answer yet. Try again in a minute.")
                self.sleep(5)
        version = hashlib.sha256(json.dumps(sorted(p.name for p in (HERE / "app").iterdir())).encode() + str(self.clock()).encode()).hexdigest()[:12]
        files = page_files(relay_url, status.get("vapid") or "", version)
        hashes = self.deploy_page(cloudflare_token, cf["account"], name, files, f"https://{ref}.supabase.co")
        if is_broad:
            secrets.delete(CF_SECRET)                            # used once, as the owner chose; not kept
        else:
            secrets.store(CF_SECRET, cloudflare_token)
        phone.save_settings(self.cfg, page_name=name, account=cf["account"], ref=ref, hashes=hashes, deployed=int(self.clock()))
        phone.ensure_chat(self.cfg)
        return {"origin": origin, "relay": relay_url, "project": ref}

    # ------------------------------------------------------------------ is the live page still the one deployed?
    def check(self) -> list[str]:
        saved = phone.settings(self.cfg)
        origin, hashes, changed = saved.get("origin"), saved.get("hashes") or {}, []
        for path, digest in hashes.items():
            try:
                status, raw = self.request("GET", origin + path, {"Cache-Control": "no-cache"}, None)
            except SetupError:
                return ["(no connection)"]
            if status != 200 or hashlib.sha256(raw).hexdigest() != digest:
                changed.append(path)
        phone.save_settings(self.cfg, checked=int(self.clock()), tampered=changed)
        return changed


def settings_ref(cfg) -> str:
    return str(phone.settings(cfg).get("ref") or "")


def brains(cfg, names: list[str]) -> list[dict]:
    """The owner's AI keys switched on for laptop-off answers, one by one, with a daily cap each. Local models cannot go."""
    from jcc import providers
    out = []
    for ident in names:
        entry = providers.CATALOG.get(ident)
        if not entry or entry.get("local") or entry.get("agent") or ident == "custom":
            continue
        key = secrets.get(providers.key_name(ident))
        if not key:
            continue
        model = providers.default_model(cfg, ident, ask=False)
        if model:
            out.append({"name": ident, "base": entry["base"], "key": key, "model": model, "daily": 100})
    return out


def switch_brains(cfg, names: list[str]) -> list[str]:
    """Sends exactly these keys to the relay (sealed there); any other copy is deleted. [] removes them all."""
    chosen = brains(cfg, names)
    result = phone.relay_for(cfg).call("brains", {"brains": chosen})
    phone.save_settings(cfg, brains=[b["name"] for b in chosen])
    return result.get("brains", [])


# ---------------------------------------------------------------------- what the /phone card shows and does
PRIVACY = ("Your messages pass through your own Supabase project and stay there for up to 7 days. With laptop-off answers "
           "switched on, the AI service you choose reads those messages. Nothing goes to the JARVIS project.")


def _worker(cfg, assistant):
    worker = phone.WORKER or (phone.start(cfg, assistant) if assistant is not None else None)
    if worker is None:
        raise ValueError("The phone app is not set up on this computer yet.")
    return worker


def _seen(cfg) -> dict:
    """What the relay knows of each phone: when it was last used, and whether it can be sent notifications.
    Empty when the relay can't be reached; the card then shows only what this computer knows."""
    try:
        got = phone.relay_for(cfg).call("phones", timeout=6)
    except (phone.RelayError, OSError, ValueError):
        return {}
    rows = got.get("phones") if isinstance(got, dict) else None
    return {str(row.get("id")): row for row in rows or [] if isinstance(row, dict)}


def state(cfg, live: bool = False) -> dict:
    """Everything the card shows. No secret, token or key leaves this function. live: also ask the relay when each
    phone was last used and whether notifications reach it (only when the card is opened)."""
    from jcc import providers
    saved = phone.settings(cfg)
    worker = phone.WORKER
    seen = _seen(cfg) if live and saved.get("enabled") else {}
    phones = [{"id": ident, "name": item.get("name", ""), "added": item.get("added"), "revoked": bool(item.get("revoked")),
               **({"last_seen": seen[ident].get("last_seen"), "push": bool(seen[ident].get("push"))} if ident in seen else {})}
              for ident, item in phone.keys(cfg).items()]
    can = [{"id": ident, "name": entry["name"]} for ident, entry in providers.CATALOG.items()
           if not entry.get("local") and not entry.get("agent") and ident != "custom" and secrets.get(providers.key_name(ident))]
    waiting = (worker.waiting_pair or {}).get("name") if worker else None
    pairing = worker.pairing if worker else None
    return {"privacy": PRIVACY, "setup": bool(saved.get("origin") and saved.get("enabled")), "origin": saved.get("origin", ""),
            "project": saved.get("ref", ""), "deployed": saved.get("deployed"), "tampered": saved.get("tampered") or [],
            "status": worker.status if worker else "off", "phones": [p for p in phones if not p["revoked"]],
            "brains": {"on": saved.get("brains") or [], "can": can}, "waiting": waiting,
            "pairing": bool(pairing), "page_qr": _qr(saved.get("origin", ""), "The phone page's address")}


def _qr(text: str, label: str) -> str:
    if not text:
        return ""
    from jcc import qr
    try:
        return qr.svg(text, label)
    except ValueError:
        return ""


def window(cfg, assistant, body: dict) -> dict:
    """/api/phone: the /phone card's actions. Setup errors come back as their plain sentence."""
    action = str(body.get("action") or "show")
    try:
        if action == "setup":
            done = Setup(cfg).run(str(body.get("supabase_token") or ""), str(body.get("cloudflare_token") or ""),
                                  str(body.get("region") or "ap-south-1"), bool(body.get("use_broad_once")))
            _worker(cfg, assistant)
            return {**state(cfg), "done": done}
        if action == "pair":
            made = _worker(cfg, assistant).start_pairing()
            return {**state(cfg), "code": made["code"], "minutes": made["minutes"], "until": int(time.time()) + made["minutes"] * 60,
                    "code_qr": _qr(made["link"], "The pairing code")}
        if action == "pair_stop":
            _worker(cfg, assistant).stop_pairing()
        elif action == "approve":
            done = _worker(cfg, assistant).approve_pair(bool(body.get("yes")))
            return {**state(cfg), "paired": done.get("name", "")}
        elif action == "remove":
            _worker(cfg, assistant).remove_phone(str(body.get("phone") or ""))
        elif action == "brains":
            switch_brains(cfg, [str(n) for n in (body.get("names") or [])][:20])
        elif action == "check":
            Setup(cfg).check()
        elif action == "remove_everything":
            remove_everything(cfg)
        elif action != "show":
            raise ValueError("Unknown phone action.")
    except SetupError as problem:
        if str(problem) == "BROAD_TOKEN":
            return {**state(cfg), "broad": True}
        raise ValueError(str(problem)) from None
    except phone.RelayError as problem:
        raise ValueError("Your relay answered " + str(problem.status) + ". Check your connection, then try again.") from None
    except OSError:
        raise ValueError("Couldn't reach your relay. Check your connection, then try again.") from None
    return state(cfg, live=action == "show")


def remove_everything(cfg, request=http) -> None:
    """Deletes the relay's messages, the phone page and every pairing. The chat stays on this computer."""
    saved = phone.settings(cfg)
    try:
        phone.relay_for(cfg).call("remove_everything")
    except phone.RelayError as problem:
        # 401 or 404: the relay no longer knows this computer, or is gone, so there is nothing left there to delete.
        if problem.status not in (401, 404):
            raise ValueError("Your relay answered " + str(problem.status) + ", so nothing was removed yet. Try again in a minute.") from None
    except OSError:
        # (the computer's secret is kept, so trying again can still reach the relay and delete what it holds)
        raise ValueError("Couldn't reach your relay, so nothing was removed yet. Check your connection, then try again. "
                         "Deleting the Supabase project also removes everything it holds.") from None
    except ValueError:
        pass                                                  # (not set up on this computer: there is no relay to tell)
    token = secrets.get(CF_SECRET)
    if token and saved.get("account") and saved.get("page_name"):
        try:
            Setup(cfg, request=request).cf("DELETE", f"/accounts/{saved['account']}/workers/scripts/{saved['page_name']}", token)
        except SetupError:
            pass
    if phone.WORKER:
        phone.WORKER.stop.set()
        phone.WORKER = None
    table = phone.keys(cfg)
    for item in table.values():
        item["revoked"] = True
    phone._save_keys(cfg, table)
    for name in (CF_SECRET, phone.DEVICE_SECRET):
        secrets.delete(name)
    phone.save_settings(cfg, enabled=False, origin="", endpoint="", hashes={}, brains=[], tampered=[])
