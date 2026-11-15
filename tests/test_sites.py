"""The owner's websites (jcc/sites.py): only the sites they connected, keys in the key store, and every change shown on this
computer first and sent to the site only when the owner publishes it. The four platforms are played by stand-ins that
answer as their APIs are documented to; nothing here reaches a real site."""
import json
import os
import re
import urllib.parse

from jcc import policy, secrets, sites, voice_tools
from tests.helpers import EngineTestCase
from tests.test_gui import GuiTestCase


class Platforms:
    """WordPress, Shopify, Wix and Squarespace, as far as JARVIS uses them. Every request is written down."""

    def __init__(self):
        self.calls = []
        self.wp_posts = {"7": {"id": 7, "title": {"raw": "Hello"}, "content": {"raw": "<p>Old text</p>"}, "status": "publish", "link": "https://blog.example.com/hello"}}
        self.products = {"11": {"id": 11, "title": "Mug", "body_html": "<p>A mug</p>", "handle": "mug", "status": "active", "variants": [{"id": 99, "price": "9.00"}]}}

    def __call__(self, method, url, headers, body=None, form=False):
        self.calls.append({"method": method, "url": url, "headers": dict(headers), "body": body, "form": form})
        parts = urllib.parse.urlsplit(url)
        path = parts.path
        if "/wp-json/wp/v2/" in path:
            if headers.get("Authorization") != "Basic " + __import__("base64").b64encode(b"ann:abcd efgh ijkl").decode():
                return 401, {"message": "Sorry, you are not allowed to do that."}
            tail = path.split("/wp-json/wp/v2/")[1]
            if method == "GET" and tail == "posts":
                return 200, list(self.wp_posts.values())
            if method == "GET" and tail.startswith("posts/"):
                found = self.wp_posts.get(tail.split("/")[1])
                return (200, found) if found else (404, {"message": "Invalid post ID."})
            if method == "POST" and tail == "posts":
                return 201, {"id": 8, "link": "https://blog.example.com/new", "title": {"raw": body["title"]}}
            if method == "POST" and tail.startswith("posts/"):
                return 200, {"id": int(tail.split("/")[1]), "link": "https://blog.example.com/hello"}
        if parts.hostname == "shop.myshopify.com":
            if path == "/admin/oauth/access_token":
                return (200, {"access_token": "shpat_exchanged", "expires_in": 86399}) if body.get("client_secret") == "s3cret" else (400, {"error": "invalid_client"})
            if headers.get("X-Shopify-Access-Token") not in ("shpat_good", "shpat_exchanged"):
                return 401, {"errors": "[API] Invalid API key or access token"}
            tail = path.split(f"/admin/api/{sites.SHOPIFY_VERSION}/")[1]
            if tail == "shop.json":
                return 200, {"shop": {"name": "Ann's Shop"}}
            if method == "GET" and tail.startswith("products/"):
                return 200, {"product": self.products[tail.split("/")[1].split(".")[0]]}
            if method == "PUT" and tail.startswith("products/"):
                return 200, {"product": {**self.products["11"], **body["product"]}}
            if method == "PUT" and tail.startswith("variants/"):
                return 200, {"variant": body["variant"]}
            if method == "POST" and tail == "products.json":
                return 201, {"product": {"id": 12, "handle": "new-thing", **body["product"]}}
        if url.startswith(sites.WIX_API):
            if headers.get("Authorization") != "IST.wixkey" or headers.get("wix-site-id") != "0a1b2c3d-1111-2222-3333-444455556666":
                return 403, {"message": "Forbidden"}
            if path == "/site-properties/v4/properties":
                return 200, {"properties": {"siteDisplayName": "Ann's Bakery"}}
            if path == "/blog/v3/posts":
                return 200, {"posts": [{"id": "p1", "title": "Opening day", "memberId": "m-ann", "url": {"base": "https://ann.wixsite.com/bakery", "path": "/post/opening-day"}}]}
            if path == "/blog/v3/draft-posts":
                return 200, {"draftPost": {"id": "d2", "url": {"base": "https://ann.wixsite.com/bakery", "path": "/post/new"}}}
        if url.startswith(sites.SQUARESPACE_API):
            if headers.get("Authorization") != "Bearer sq-key":
                return 401, {"message": "Unauthorized"}
            if method == "GET" and path.endswith("/commerce/products"):
                return 200, {"products": [{"id": "sq1", "name": "Print", "isVisible": True, "url": "https://ann.squarespace.com/shop/print"}]}
            if method == "GET" and "/commerce/products/" in path:
                return 200, {"products": [{"id": "sq1", "name": "Print", "description": "<p>A print</p>", "isVisible": True}]}
            if method == "POST" and "/commerce/products/" in path:
                return 200, {"id": "sq1", "url": "https://ann.squarespace.com/shop/print"}
        return 404, {"message": "no such thing"}

    def sent(self):
        """What changed something on a site (anything but looking)."""
        return [c for c in self.calls if c["method"] in ("POST", "PUT", "DELETE") and "/oauth/access_token" not in c["url"]]


class SitesCase(EngineTestCase):
    def setUp(self):
        super().setUp()
        from jcc import config
        self.cfg = config.load()
        self.web = Platforms()
        self._fetch, sites.FETCH = sites.FETCH, self.web
        sites._TOKENS.clear()

    def tearDown(self):
        sites.FETCH = self._fetch
        super().tearDown()

    def wordpress(self):
        return sites.add(self.cfg, "wordpress", "blog.example.com", "abcd efgh ijkl", user="ann", name="Ann's blog")


class TheSites(SitesCase):
    def test_a_site_is_kept_with_its_key_in_the_key_store_never_in_a_file(self):
        site = self.wordpress()
        self.assertEqual((site["name"], site["address"], site["kinds"]), ("Ann's blog", "https://blog.example.com", ["post", "page"]))
        saved = (self.cfg.state_dir / "sites.json").read_text("utf-8")
        self.assertNotIn("abcd efgh ijkl", saved)
        self.assertEqual(secrets._cred_read("site-" + site["id"]), "abcd efgh ijkl")
        self.assertTrue(sites.remove(self.cfg, site["id"]))
        self.assertIsNone(secrets._cred_read("site-" + site["id"]), "removing a site deletes its key")

    def test_a_wrong_key_is_not_kept(self):
        with self.assertRaisesRegex(sites.SiteError, "refused JARVIS's key"):
            sites.add(self.cfg, "wordpress", "blog.example.com", "wrong", user="ann")
        self.assertEqual(sites.listing(self.cfg), [])

    def test_addresses_are_checked(self):
        with self.assertRaisesRegex(sites.SiteError, "https"):
            sites.add(self.cfg, "wordpress", "http://blog.example.com", "abcd efgh ijkl", user="ann")
        with self.assertRaisesRegex(sites.SiteError, "myshopify.com"):
            sites.add(self.cfg, "shopify", "annsshop.com", "shpat_good")
        with self.assertRaisesRegex(sites.SiteError, "WordPress, Shopify, Wix or Squarespace"):
            sites.add(self.cfg, "joomla", "x.com", "k")

    def test_only_connected_sites_are_ever_reached(self):
        self.wordpress()
        with self.assertRaisesRegex(sites.SiteError, "not one of the connected websites"):
            sites.stage(self.cfg, "evil.example.com", "post", "a post", title="Hi")
        self.assertFalse([c for c in self.web.calls if "evil" in c["url"]])


class PreviewThenPublish(SitesCase):
    def test_a_new_post_is_a_preview_until_it_is_published(self):
        self.wordpress()
        made = sites.stage(self.cfg, "Ann's blog", "post", "A post about the summer sale", title="Summer sale", content="<p>All mugs half price</p>")
        self.assertEqual(self.web.sent(), [], "nothing reached the site")
        self.assertEqual(sites.pending(self.cfg)[0]["id"], made["id"])
        self.assertIsNone(sites.preview_html(self.cfg, made["id"], "not-its-key"), "the preview is shown only with its link")
        page = sites.preview_html(self.cfg, made["id"], made["view"])
        self.assertIn("Preview on this computer", page)
        self.assertIn("Summer sale", page)
        self.assertIn("Not published yet", page)
        done = sites.publish(self.cfg, made["id"])
        self.assertEqual(done["state"], "published")
        sent = self.web.sent()
        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0]["url"].endswith("/wp-json/wp/v2/posts"))
        self.assertEqual(sent[0]["body"], {"title": "Summer sale", "content": "<p>All mugs half price</p>", "status": "publish"}, "exactly what was previewed")
        with self.assertRaisesRegex(sites.SiteError, "published already"):
            sites.publish(self.cfg, made["id"])
        self.assertEqual(sites.pending(self.cfg), [])

    def test_a_discarded_change_never_reaches_the_site(self):
        self.wordpress()
        made = sites.stage(self.cfg, "Ann's blog", "post", "x", title="Nope")
        sites.discard(self.cfg, made["id"])
        with self.assertRaisesRegex(sites.SiteError, "thrown away"):
            sites.publish(self.cfg, made["id"])
        self.assertEqual(self.web.sent(), [])

    def test_an_edit_shows_the_site_as_it_is_beside_what_it_becomes(self):
        self.wordpress()
        made = sites.stage(self.cfg, "Ann's blog", "post", "Fix the greeting", item_id="7", content="<p>New text</p>")
        page = sites.preview_html(self.cfg, made["id"], made["view"])
        self.assertIn("Now on the site", page)
        self.assertIn("Old text", page)
        self.assertIn("New text", page)
        sites.publish(self.cfg, made["id"])
        self.assertEqual(self.web.sent()[0]["body"], {"content": "<p>New text</p>"}, "only what changes; an existing post keeps its status")

    def test_what_a_preview_shows_cannot_run_anything(self):
        self.wordpress()
        made = sites.stage(self.cfg, "Ann's blog", "post", "x", title="<script>alert(1)</script>", content="<img src=x onerror=alert(1)><script>steal()</script>")
        page = sites.preview_html(self.cfg, made["id"], made["view"])
        self.assertNotIn("<script>", page, "everything from the change is escaped")
        self.assertRegex(page, r"<iframe sandbox title='content' srcdoc=")
        self.assertNotIn("allow-scripts", page)
        self.assertIn("default-src 'none'", sites.PREVIEW_POLICY)


class EachPlatform(SitesCase):
    def test_shopify_with_a_token_edits_a_product_and_its_price(self):
        site = sites.add(self.cfg, "shopify", "shop.myshopify.com", "shpat_good")
        self.assertEqual(site["name"], "Ann's Shop", "named as the shop calls itself")
        made = sites.stage(self.cfg, "shop", "product", "Cheaper mug", item_id="11", price="7.5")
        self.assertIn("9.00", sites.preview_html(self.cfg, made["id"], made["view"]))
        sites.publish(self.cfg, made["id"])
        sent = self.web.sent()
        self.assertEqual([c["method"] for c in sent], ["PUT", "PUT"])
        self.assertEqual(sent[1]["body"], {"variant": {"id": 99, "price": "7.50"}})

    def test_shopify_with_a_dev_dashboard_app_gets_its_token_first(self):
        site = sites.add(self.cfg, "shopify", "https://shop.myshopify.com", "client123:s3cret")
        exchange = self.web.calls[0]
        self.assertTrue(exchange["url"].endswith("/admin/oauth/access_token") and exchange["form"])
        self.assertEqual(exchange["body"]["grant_type"], "client_credentials")
        self.assertEqual(self.web.calls[1]["headers"]["X-Shopify-Access-Token"], "shpat_exchanged")
        sites.remove(self.cfg, site["id"])
        sites._TOKENS.clear()
        with self.assertRaisesRegex(sites.SiteError, "did not give JARVIS a token"):
            sites.add(self.cfg, "shopify", "https://shop.myshopify.com", "client123:wrong")
        self.assertEqual(sites.listing(self.cfg), [], "and nothing is kept")

    def test_wix_adds_blog_posts_written_as_the_sites_own_author(self):
        site = sites.add(self.cfg, "wix", "ann.wixsite.com/bakery", "IST.wixkey", site_id="0a1b2c3d-1111-2222-3333-444455556666")
        self.assertEqual(site["name"], "Ann's Bakery")
        with self.assertRaisesRegex(sites.SiteError, "new posts|not change existing"):
            sites.stage(self.cfg, site["id"], "post", "x", item_id="p1", title="t")
        made = sites.stage(self.cfg, site["id"], "post", "Weekend opening hours", title="Open on Sunday", content="<p>From 9.</p><p>Until 2.</p>")
        sites.publish(self.cfg, made["id"])
        body = self.web.sent()[0]["body"]
        self.assertEqual(body["draftPost"]["memberId"], "m-ann")
        self.assertTrue(body["publish"])
        self.assertEqual([n["nodes"][0]["textData"]["text"] for n in body["draftPost"]["richContent"]["nodes"]], ["From 9.", "Until 2."])

    def test_squarespace_changes_products_only(self):
        site = sites.add(self.cfg, "squarespace", "ann.squarespace.com", "sq-key")
        with self.assertRaisesRegex(sites.SiteError, "products only"):
            sites.stage(self.cfg, site["id"], "page", "x", title="t")
        with self.assertRaisesRegex(sites.SiteError, "not add new ones"):
            sites.stage(self.cfg, site["id"], "product", "x", title="t")
        made = sites.stage(self.cfg, site["id"], "product", "Hide the print", item_id="sq1", visible=False)
        sites.publish(self.cfg, made["id"])
        self.assertEqual(self.web.sent()[0]["body"], {"isVisible": False})


class WhoDecides(SitesCase):
    def ctx(self, level):
        return policy.Context(level=level) if "level" in policy.Context.__dataclass_fields__ else policy.Context()

    def test_making_a_preview_is_never_asked_about_and_publishing_is_like_sending(self):
        for level in ("sending", "all", "bypass"):
            self.assertEqual(policy.decide("site_change", {"site": "x", "kind": "post", "summary": "s"}, self.ctx(level)).verdict, policy.ALLOW, level)
        asked = policy.decide("site_publish", {"change": "abc", "site": "Ann's blog"}, self.ctx("sending"))
        self.assertEqual(asked.verdict, policy.CONFIRM)
        self.assertTrue(policy.needs_owner(asked, self.ctx("sending")))
        self.assertFalse(policy.needs_owner(asked, self.ctx("bypass")), "Bypass asks nothing (the preview was still shown)")

    def test_the_assistant_has_the_four_tools(self):
        names = {tool["name"] for tool in voice_tools.offered(full=True)}
        self.assertTrue({"list_sites", "site_read", "site_change", "site_publish"} <= names)


class OverTheWire(GuiTestCase):
    def setUp(self):
        super().setUp()
        self.web = Platforms()
        self._fetch, sites.FETCH = sites.FETCH, self.web

    def tearDown(self):
        sites.FETCH = self._fetch
        super().tearDown()

    def get(self, path):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", path, headers={"Host": f"127.0.0.1:{self.port}"})
        r = c.getresponse()
        out = (r.status, dict(r.getheaders()), r.read().decode("utf-8"))
        c.close()
        return out

    def test_connect_preview_and_publish_from_the_window(self):
        status, got = self.req("POST", "/api/sites", {"action": "add", "platform": "wordpress", "address": "blog.example.com", "user": "ann", "key": "abcd efgh ijkl"})
        self.assertEqual(status, 200, got)
        self.assertNotIn("abcd efgh ijkl", json.dumps(got))
        self.assertEqual(self.req("POST", "/api/sites", {"action": "list"}, token=False)[0], 401, "only JARVIS's own window")
        events = []
        self.state.assistant.emit = lambda what, **fields: events.append((what, fields))
        answer = self.state.perform("site_change", {"site": "blog.example.com", "kind": "post", "summary": "s", "title": "Hi", "content": "<p>x</p>"}, None)
        change = events[0][1]["change"]
        self.assertEqual((events[0][0], answer["id"], change["state"]), ("site", change["id"], "preview"))
        self.assertEqual(self.web.sent(), [])
        status, headers, page = self.get(f"/site-preview/{change['id']}?k={change['view']}")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("X-Frame-Options"), "SAMEORIGIN", "it can be shown inside the chat")
        self.assertIn("default-src 'none'", headers.get("Content-Security-Policy", ""))
        self.assertEqual(self.get(f"/site-preview/{change['id']}?k=wrong")[0], 404)
        status, got = self.req("POST", "/api/sites", {"action": "publish", "id": change["id"]})
        self.assertEqual((status, got["change"]["state"]), (200, "published"))
        self.assertEqual(len(self.web.sent()), 1)

    def test_the_window_loads_the_websites_card(self):
        from jcc import gui, mods
        self.assertIn("/nova-sites.js", gui.SCRIPTS)
        self.assertIn("sites", [name for name, _ in mods.BUILTIN])
        page = (gui.STATIC.with_name("nova-sites.js")).read_text("utf-8")
        self.assertTrue(re.search(r"N\.siteCard = ", page) and "data-publish" in page and "data-discard" in page)


class StaysConnected(SitesCase):
    """A site stays connected until its owner removes it: nothing JARVIS meets disconnects it."""

    def test_it_is_still_there_after_a_restart(self):
        site = self.wordpress()
        from jcc import config
        again = config.load()                                     # (JARVIS started again: everything read afresh)
        self.assertEqual([s["id"] for s in sites.listing(again)], [site["id"]])
        self.assertEqual(sites.read(again, site["id"], "post")["items"][0]["title"], "Hello", "and its key still works")

    def test_errors_a_site_that_is_down_or_a_refused_key_never_disconnect_it(self):
        site = self.wordpress()

        def down(*_a, **_k):
            raise sites.SiteError("The site could not be reached: timed out")
        sites.FETCH = down
        with self.assertRaises(sites.SiteError):
            sites.read(self.cfg, site["id"], "post")
        sites.FETCH = lambda *a, **k: (401, {"message": "Sorry, you are not allowed to do that."})
        with self.assertRaisesRegex(sites.SiteError, "stays connected"):
            sites.read(self.cfg, site["id"], "post")
        self.assertEqual([s["id"] for s in sites.listing(self.cfg)], [site["id"]])
        self.assertEqual(secrets._cred_read("site-" + site["id"]), "abcd efgh ijkl")

    def test_a_new_key_replaces_the_old_one_in_place_and_a_wrong_one_is_not_kept(self):
        site = self.wordpress()
        with self.assertRaisesRegex(sites.SiteError, "refused"):
            sites.rekey(self.cfg, site["id"], "wrong key")
        self.assertEqual(secrets._cred_read("site-" + site["id"]), "abcd efgh ijkl", "the old key is kept")
        made = sites.stage(self.cfg, site["id"], "post", "x", title="Kept")
        sites.FETCH = lambda method, url, headers, body=None, form=False: (200, []) if method == "GET" else (201, {"id": 9, "link": ""})
        sites.rekey(self.cfg, site["id"], "new key 1234")
        self.assertEqual(secrets._cred_read("site-" + site["id"]), "new key 1234")
        self.assertEqual(sites.pending(self.cfg)[0]["id"], made["id"], "its waiting changes are untouched")

    def test_an_expired_shopify_app_token_is_renewed_by_itself(self):
        site = sites.add(self.cfg, "shopify", "shop.myshopify.com", "client123:s3cret")
        sites._TOKENS[site["id"]] = ("shpat_expired", 9e12)        # (Shopify let it run out early)
        self.assertEqual(sites.read(self.cfg, site["id"], "product", "11")["item"]["title"], "Mug")
        self.assertEqual(sites._TOKENS[site["id"]][0], "shpat_exchanged")
