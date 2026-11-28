"""Setting up the phone app in the owner's own Supabase and Cloudflare (jcc/phone_setup.py), against fake APIs. No network."""
import base64
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from jcc import phone, phone_setup

SB_TOKEN = "sbp_" + "a" * 40
CF_TOKEN = "cf-token-" + "b" * 32


class FakeApis:
    def __init__(self, broad=False, secrets_have=()):
        self.calls, self.broad, self.secrets_have, self.secrets_set = [], broad, list(secrets_have), []
        self.live, self.made = {}, []

    def __call__(self, method, url, headers=None, data=None, timeout=60):
        self.calls.append((method, url, headers or {}, data))
        ok = lambda value: (200, json.dumps({"success": True, "result": value}).encode())
        if url.endswith("/zones?per_page=1"):
            return (200, json.dumps({"success": True, "result": [{"id": "z"}] if self.broad else []}).encode())
        if url.endswith("/user/tokens/verify"):
            return ok({"id": "tok1", "status": "active"})
        if url.endswith("/user/tokens/tok1") or url.endswith("/tokens") or url.endswith("/pages/projects"):
            return ok([]) if self.broad == "tokens" else (403, b'{"success": false, "errors": [{"message": "no"}]}')
        if url.endswith("/accounts"):
            return ok([{"id": "acct1"}])
        if url.endswith("/workers/subdomain"):
            return ok({"subdomain": "owner"})
        if url.endswith("/assets-upload-session"):
            manifest = json.loads(data)["manifest"]
            return ok({"jwt": "session-jwt", "buckets": [[v["hash"] for v in manifest.values()]]})
        if "/workers/assets/upload" in url:
            assert headers["Authorization"] == "Bearer session-jwt"
            return (201, json.dumps({"success": True, "result": {"jwt": "done-jwt"}}).encode())
        if re.search(r"/workers/scripts/[\w-]+$", url) and method == "PUT":
            self.script = data
            return ok({})
        if url.endswith("/subdomain") and method == "POST":
            return ok({})
        if url.endswith("/v1/projects") and method == "GET":
            return 200, json.dumps([{"ref": "abcdefghijklmnop", "name": "jarvis", "status": "ACTIVE_HEALTHY"}] + self.made).encode()
        if url.endswith("/v1/organizations"):
            return 200, b'[{"id": "org1", "slug": "mine-abc", "name": "Mine"}]'
        if url.endswith("/v1/projects") and method == "POST":
            body = json.loads(data)
            self.made.append({"ref": "newprojectref123", "name": body["name"], "status": "COMING_UP"})
            return 201, json.dumps(self.made[-1]).encode()
        if url.endswith("/v1/projects/newprojectref123") and method == "GET":
            return 200, b'{"ref": "newprojectref123", "status": "ACTIVE_HEALTHY"}'
        if url.endswith("/database/query"):
            return 201, b"[]"
        if url.endswith("/secrets") and method == "GET":
            return 200, json.dumps([{"name": n} for n in self.secrets_have]).encode()
        if url.endswith("/secrets") and method == "POST":
            self.secrets_set = json.loads(data)
            return 201, b"{}"
        if "/functions/deploy" in url:
            self.function = data
            return 201, b'{"id":"f","slug":"jarvis-phone","name":"jarvis-phone","status":"ACTIVE","version":1}'
        if url.startswith("https://") and ".workers.dev" in url:
            return self.live.get(url, (404, b""))
        raise AssertionError("unexpected call " + method + " " + url)


class SetupCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.cfg = SimpleNamespace(state_dir=Path(self.dir.name), vault=Path(self.dir.name))
        self.stored = {}
        for p in (mock.patch.object(phone.secrets, "store", lambda k, v: self.stored.__setitem__(k, v)),
                  mock.patch.object(phone.secrets, "get", lambda k: self.stored.get(k)),
                  mock.patch.object(phone.secrets, "delete", lambda k: self.stored.pop(k, None)),
                  mock.patch.object(phone, "ensure_chat", lambda cfg: "20261128-120000-abcd")):
            p.start()
            self.addCleanup(p.stop)

    def run_setup(self, apis, **kw):
        setup = phone_setup.Setup(self.cfg, request=apis, sleep=lambda s: None)
        return setup, setup.run(SB_TOKEN, CF_TOKEN, relay_status=lambda: {"vapid": "BPUBLICKEY"}, **kw)


class TestSetup(SetupCase):
    def test_one_run_sets_up_the_relay_and_the_page_in_the_owners_own_accounts(self):
        apis = FakeApis()
        setup, done = self.run_setup(apis)
        self.assertRegex(done["origin"], r"^https://jarvis-[a-z2-9]{8}\.owner\.workers\.dev$")
        self.assertEqual(done["relay"], "https://newprojectref123.supabase.co/functions/v1/jarvis-phone")
        names = {s["name"]: s["value"] for s in apis.secrets_set}
        self.assertEqual(names["JARVIS_APP_ORIGIN"], done["origin"])
        self.assertEqual(names["JARVIS_DEVICE_HASH"], hashlib.sha256(self.stored[phone.DEVICE_SECRET].encode()).hexdigest())
        self.assertEqual(len(base64.b64decode(names["JARVIS_DATA_KEY"])), 32)
        self.assertNotIn(SB_TOKEN, json.dumps(self.stored), "the Supabase token is never kept")
        self.assertEqual(self.stored[phone_setup.CF_SECRET], CF_TOKEN, "a Workers-only token is kept for redeploys")
        self.assertIn(b'"verify_jwt": false', apis.function)
        for name in phone_setup.FUNCTION_FILES:
            self.assertIn(f'filename="{name}"'.encode(), apis.function)
        self.assertIn(b"connect-src 'self' https://newprojectref123.supabase.co", apis.script)
        self.assertIn(b"frame-ancestors 'none'", apis.script)

    def test_the_deployed_page_holds_no_secret(self):
        apis = FakeApis()
        self.run_setup(apis)
        uploaded = b"".join(d or b"" for m, u, h, d in apis.calls if "/workers/assets/upload" in u)
        files = re.findall(rb"\r\n\r\n([A-Za-z0-9+/=]+)\r\n", uploaded)
        everything = b"".join(base64.b64decode(f) for f in files)
        self.assertIn(b'"vapid": "BPUBLICKEY"', everything)
        for secret in (self.stored[phone.DEVICE_SECRET].encode(), SB_TOKEN.encode(), CF_TOKEN.encode()):
            self.assertNotIn(secret, everything)
        data_key = next(s["value"] for s in apis.secrets_set if s["name"] == "JARVIS_DATA_KEY").encode()
        self.assertNotIn(data_key, everything)

    def test_a_broad_cloudflare_token_is_refused_unless_used_once_and_then_forgotten(self):
        with self.assertRaises(phone_setup.SetupError) as caught:
            self.run_setup(FakeApis(broad=True))
        self.assertEqual(str(caught.exception), "BROAD_TOKEN")
        self.run_setup(FakeApis(broad=True), use_broad_once=True)
        self.assertNotIn(phone_setup.CF_SECRET, self.stored)

    def test_running_again_keeps_the_data_key_and_the_page_name(self):
        _, first = self.run_setup(FakeApis())
        apis = FakeApis(secrets_have=["JARVIS_DATA_KEY", "JARVIS_DEVICE_HASH"])
        device = self.stored[phone.DEVICE_SECRET]
        _, again = self.run_setup(apis)
        self.assertEqual(first["origin"], again["origin"])
        self.assertNotIn("JARVIS_DATA_KEY", {s["name"] for s in apis.secrets_set}, "sealed data stays readable")
        self.assertEqual(self.stored[phone.DEVICE_SECRET], device)

    def test_tokens_that_are_plainly_wrong_are_refused_before_any_call(self):
        apis = FakeApis()
        with self.assertRaises(phone_setup.SetupError):
            phone_setup.Setup(self.cfg, request=apis).run("not-a-token", CF_TOKEN)
        self.assertEqual(apis.calls, [])

    def test_a_page_changed_outside_jarvis_is_noticed(self):
        apis = FakeApis()
        setup, done = self.run_setup(apis)
        hashes = phone.settings(self.cfg)["hashes"]
        self.assertIn("/app.js", hashes)
        for path in hashes:
            apis.live[done["origin"] + path] = (200, b"")
        changed = setup.check()
        self.assertEqual(sorted(changed), sorted(hashes))


class TestCard(SetupCase):
    def test_the_card_state_holds_no_secret_and_shows_the_page_as_a_code(self):
        apis = FakeApis()
        self.run_setup(apis)
        with mock.patch("jcc.providers.CATALOG", {"groq": {"name": "Groq", "base": "b"}}), mock.patch("jcc.providers.key_name", lambda i: i):
            self.stored["groq"] = "gsk_secret"
            shown = phone_setup.state(self.cfg)
        text = json.dumps(shown)
        self.assertTrue(shown["setup"])
        self.assertIn("<svg", shown["page_qr"])
        self.assertEqual(shown["brains"]["can"], [{"id": "groq", "name": "Groq"}])
        for secret in (self.stored[phone.DEVICE_SECRET], CF_TOKEN, "gsk_secret"):
            self.assertNotIn(secret, text)

    def test_setup_never_takes_over_a_project_it_did_not_make(self):
        apis = FakeApis()                       # (the account already has a project called "jarvis": it is left alone)
        _, done = self.run_setup(apis)
        self.assertIn("newprojectref123", done["relay"])
        made = [json.loads(c[3]) for c in apis.calls if c[0] == "POST" and c[1].endswith("/v1/projects")]
        self.assertEqual([m["name"] for m in made], ["jarvis-phone"])
        self.assertEqual(made[0]["organization_slug"], "mine-abc")
        self.assertEqual(made[0]["region_selection"], {"type": "specific", "code": "ap-south-1"})
        self.assertNotIn("organization_id", made[0])
        self.assertNotIn("region", made[0])
        self.assertFalse(any("abcdefghijklmnop" in c[1] for c in apis.calls))
        self.run_setup(apis)                    # set up again: the project it made is used, not a second one
        self.assertEqual(len([c for c in apis.calls if c[0] == "POST" and c[1].endswith("/v1/projects")]), 1)

    def test_the_pages_headers_reach_cloudflare_as_rules_and_the_worker_runs_first(self):
        apis = FakeApis()
        self.run_setup(apis)
        meta = json.loads(re.search(rb'name="metadata"\r\nContent-Type: application/json\r\n\r\n(.*?)\r\n--', apis.script, re.S).group(1))
        config = meta["assets"]["config"]
        self.assertIs(config["run_worker_first"], True)
        self.assertTrue(config["_headers"].startswith("/*\n"))
        self.assertIn("Content-Security-Policy: default-src 'self'; connect-src 'self' https://newprojectref123.supabase.co", config["_headers"])
        self.assertEqual(meta["assets"]["jwt"], "done-jwt", "the token that finished the upload, never the session's")

    def test_a_token_that_can_read_api_tokens_or_pages_counts_as_broad(self):
        self.assertTrue(phone_setup.Setup(self.cfg, request=FakeApis(broad="tokens"), sleep=lambda s: None).broad(CF_TOKEN))
        self.assertTrue(phone_setup.Setup(self.cfg, request=FakeApis(broad=True), sleep=lambda s: None).broad(CF_TOKEN))
        self.assertFalse(phone_setup.Setup(self.cfg, request=FakeApis(), sleep=lambda s: None).broad(CF_TOKEN))

    def test_a_busy_cloudflare_never_lets_a_token_through_unchecked(self):
        busy = FakeApis()
        real = busy.__call__
        busy_call = lambda method, url, headers=None, data=None, timeout=60: (429, b"{}") if "/zones" in url else real(method, url, headers, data, timeout)
        with self.assertRaisesRegex(phone_setup.SetupError, "Couldn't check what that Cloudflare token can do"):
            phone_setup.Setup(self.cfg, request=busy_call, sleep=lambda s: None).broad(CF_TOKEN)

    def test_the_workers_dev_name_is_never_replaced_after_a_hiccup(self):
        apis = FakeApis()
        real = apis.__call__
        calls = []

        def flaky(method, url, headers=None, data=None, timeout=60):
            calls.append((method, url))
            if url.endswith("/workers/subdomain") and method == "GET":
                return 503, b'{"success": false}'
            return real(method, url, headers, data, timeout)
        with self.assertRaises(phone_setup.SetupError):
            phone_setup.Setup(self.cfg, request=flaky, sleep=lambda s: None).cloudflare(CF_TOKEN)
        self.assertNotIn("PUT", [m for m, u in calls if u.endswith("/workers/subdomain")])

    def test_a_broad_token_comes_back_as_a_choice_not_an_error(self):
        with mock.patch.object(phone_setup, "Setup", lambda cfg: SimpleNamespace(run=mock.Mock(side_effect=phone_setup.SetupError("BROAD_TOKEN")))):
            got = phone_setup.window(self.cfg, None, {"action": "setup", "supabase_token": SB_TOKEN, "cloudflare_token": CF_TOKEN})
        self.assertTrue(got["broad"])
        with mock.patch.object(phone_setup, "Setup", lambda cfg: SimpleNamespace(run=mock.Mock(side_effect=phone_setup.SetupError("Cloudflare refused it.")))):
            with self.assertRaisesRegex(ValueError, "Cloudflare refused it."):
                phone_setup.window(self.cfg, None, {"action": "setup"})

    def test_removing_everything_clears_the_relay_the_page_the_pairings_and_the_secrets(self):
        apis = FakeApis()
        self.run_setup(apis)
        phone._save_keys(self.cfg, {"phone0001aa": {"public_key": "k", "name": "Pixel"}})
        relay = mock.Mock()
        with mock.patch.object(phone, "relay_for", lambda cfg, post=None: relay):
            deleted = []
            def request(method, url, headers=None, data=None, timeout=60):
                deleted.append((method, url))
                return 200, b'{"success": true, "result": null}'
            phone_setup.remove_everything(self.cfg, request=request)
        relay.call.assert_called_with("remove_everything")
        self.assertEqual(deleted[0][0], "DELETE")
        self.assertIn("/workers/scripts/jarvis-", deleted[0][1])
        self.assertTrue(phone.keys(self.cfg)["phone0001aa"]["revoked"])
        self.assertNotIn(phone_setup.CF_SECRET, self.stored)
        self.assertNotIn(phone.DEVICE_SECRET, self.stored)
        self.assertFalse(phone_setup.state(self.cfg)["setup"])

    def test_remove_everything_forgets_nothing_while_the_relay_cannot_be_told(self):
        self.run_setup(FakeApis())
        relay = mock.Mock()
        relay.call.side_effect = OSError("offline")
        with mock.patch.object(phone, "relay_for", lambda cfg, post=None: relay):
            with self.assertRaises(ValueError):
                phone_setup.remove_everything(self.cfg, request=lambda *a, **k: (200, b'{"success": true}'))
        self.assertIn(phone.DEVICE_SECRET, self.stored, "the secret is kept, so trying again can still reach the relay")
        self.assertTrue(phone_setup.state(self.cfg)["setup"])


class TestSeen(SetupCase):
    def test_the_opened_card_shows_last_use_and_notifications_from_the_relay(self):
        self.run_setup(FakeApis())
        phone._save_keys(self.cfg, {"phone0001aa": {"public_key": "k", "name": "Pixel", "added": 1}})
        relay = mock.Mock()
        relay.call.return_value = {"phones": [{"id": "phone0001aa", "last_seen": "2026-11-28T01:00:00Z", "push": False}]}
        with mock.patch.object(phone, "relay_for", lambda cfg, post=None: relay):
            shown = phone_setup.window(self.cfg, None, {"action": "show"})["phones"][0]
            self.assertEqual((shown["last_seen"], shown["push"]), ("2026-11-28T01:00:00Z", False))
            relay.call.side_effect = OSError("offline")
            self.assertNotIn("last_seen", phone_setup.window(self.cfg, None, {"action": "show"})["phones"][0])
            relay.call.reset_mock()
            phone_setup.state(self.cfg)
            relay.call.assert_not_called()                      # only an opened card asks the relay


class TestKeyNames(unittest.TestCase):
    def test_the_phone_keys_are_names_the_key_store_knows(self):
        from jcc import secrets as real
        for name in (phone.DEVICE_SECRET, phone_setup.CF_SECRET):
            self.assertIn(name, real.ENV_NAMES)       # (get() refuses any other name)


class TestBrains(SetupCase):
    def test_only_keys_switched_on_go_and_local_models_never_do(self):
        self.stored.update({"groq": "gsk_x", "gemini": "AIza_y"})
        with mock.patch("jcc.providers.default_model", lambda cfg, ident, ask=True: "model-" + ident):
            chosen = phone_setup.brains(self.cfg, ["groq", "ollama", "perplexity", "openai"])
        self.assertEqual([b["name"] for b in chosen], ["groq"])           # no key for openai; ollama is local; perplexity is not chat
        self.assertEqual(chosen[0]["key"], "gsk_x")

    def test_asset_hash_is_cloudflares(self):
        self.assertEqual(phone_setup.asset_hash(b"hi", "/a.js"), hashlib.sha256(b"aGk=js").hexdigest()[:32])


if __name__ == "__main__":
    unittest.main()
