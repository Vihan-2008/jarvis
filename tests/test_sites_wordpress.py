"""Connecting and posting to WordPress the ways real sites are set up (jcc/sites.py): a site without "pretty" links, a site
that sends JARVIS to its www. address, every way a WordPress refuses (each said in words that say what to do), a
firewall, and a site hosted on WordPress.com. Stand-ins play the sites; nothing here reaches a real one."""
import base64
import io
import urllib.error
import urllib.parse
import urllib.request

from jcc import secrets, sites
from tests.test_sites import SitesCase

GOOD = "Basic " + base64.b64encode(b"ann:abcd efgh ijkl").decode()
INDEX = {"name": "Ann's Blog", "home": "https://blog.example.com", "namespaces": ["wp/v2"], "authentication": {"application-passwords": {}}}
ME = {"id": 1, "name": "Ann", "capabilities": {"edit_posts": True, "publish_posts": True}}


class WordPress:
    """One WordPress site, set up in one of the ways real ones are. Every request is written down."""

    def __init__(self, pretty=True, index=None, me=None, refuse=None, home="https://blog.example.com"):
        self.pretty, self.index, self.me, self.refuse, self.calls = pretty, {**INDEX, "home": home, **(index or {})}, me or ME, refuse, []

    def __call__(self, method, url, headers, body=None, form=False):
        self.calls.append((method, url, body))
        parts = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qs(parts.query)
        if parts.path.startswith("/wp-json"):
            if not self.pretty:
                return 404, {"_page": "Page not found - Ann's Blog"}       # (the site's own 404 page: no /wp-json/ without pretty links)
            route = parts.path[len("/wp-json"):]
        elif "rest_route" in query:
            route = query["rest_route"][0]
        else:
            return 200, {"_page": "Ann's Blog - Just another WordPress site"}
        if route == "/":
            return 200, self.index
        if self.refuse:
            return self.refuse
        if headers.get("Authorization") != GOOD:
            return 401, {"code": "incorrect_password", "message": "The provided password is an invalid application password."}
        if route == "/wp/v2/users/me":
            return 200, self.me
        if route == "/wp/v2/posts" and method == "GET":
            return 200, []
        if route == "/wp/v2/posts" and method == "POST":
            return 201, {"id": 31, "link": "https://blog.example.com/?p=31"}
        return 404, {"code": "rest_no_route", "message": "No route was found matching the URL and request method."}


class TheWordPressWays(SitesCase):
    def use(self, site):
        sites.FETCH = site
        return site

    def connect(self, user="ann", key="abcd efgh ijkl"):
        return sites.add(self.cfg, "wordpress", "blog.example.com", key, user=user)

    def post(self, site_id):
        made = sites.stage(self.cfg, site_id, "post", "a new post", title="Hello", content="<p>Hi</p>")
        return sites.publish(self.cfg, made["id"])

    def test_a_site_without_pretty_links_is_reached_at_rest_route(self):
        site = self.use(WordPress(pretty=False))
        added = self.connect()
        self.assertEqual(added["name"], "Ann's Blog")
        self.assertEqual(self.post(added["id"])["state"], "published")
        method, url, body = site.calls[-1]
        self.assertEqual((method, body["title"], body["status"]), ("POST", "Hello", "publish"))
        self.assertTrue(url.startswith("https://blog.example.com/?rest_route=/wp/v2/posts"), url)

    def test_an_older_site_kept_before_this_finds_its_api_by_itself(self):
        self.use(WordPress())
        added = self.connect()
        self.use(WordPress(pretty=False))                    # (its links were changed to plain afterwards)
        self.assertEqual(self.post(added["id"])["state"], "published")

    def test_the_address_wordpress_calls_its_own_is_used(self):
        site = self.use(WordPress(home="https://www.blog.example.com"))
        added = self.connect()
        self.assertEqual(added["address"], "https://www.blog.example.com")
        self.post(added["id"])
        self.assertTrue(site.calls[-1][1].startswith("https://www.blog.example.com/wp-json/wp/v2/posts"))

    def test_a_post_that_is_sent_on_elsewhere_is_not_quietly_turned_into_a_read(self):
        self.use(WordPress())
        added = self.connect()

        def moved(method, url, headers, body=None, form=False):
            if method == "POST":
                return 301, {"_page": "Moved", "_moved": "https://www.blog.example.com/wp-json/wp/v2/posts"}
            return 200, []
        sites.FETCH = moved
        made = sites.stage(self.cfg, added["id"], "post", "s", title="Hello", content="x")
        with self.assertRaisesRegex(sites.SiteError, r"sends JARVIS to another address \(https://www\.blog\.example\.com"):
            sites.publish(self.cfg, made["id"])
        handler = sites._OnlyReadsFollow()
        posted = urllib.request.Request("https://blog.example.com/wp-json/wp/v2/posts", data=b"{}", method="POST")
        self.assertIsNone(handler.redirect_request(posted, io.BytesIO(), 301, "Moved", {}, "https://www.blog.example.com/x"))
        looked = urllib.request.Request("https://blog.example.com/wp-json/")
        self.assertIsNotNone(handler.redirect_request(looked, io.BytesIO(), 301, "Moved", {}, "https://www.blog.example.com/wp-json/"))

    def test_each_refusal_says_what_to_do(self):
        cases = [
            (dict(), "wrong pass", "ann", "did not take that application password"),
            (dict(refuse=(401, {"code": "invalid_username", "message": "Unknown username."})), "abcd efgh ijkl", "JARVIS", "no user called JARVIS"),
            (dict(refuse=(401, {"code": "rest_not_logged_in", "message": "You are not currently logged in."})), "abcd efgh ijkl", "ann", "SetEnvIf Authorization"),
            (dict(index={"authentication": []}), "abcd efgh ijkl", "ann", "Application passwords are switched off"),
            (dict(refuse=(403, {"_page": "Attention Required! | Cloudflare"})), "abcd efgh ijkl", "ann", "firewall turned JARVIS away"),
            (dict(me={"id": 2, "capabilities": {"read": True}}), "abcd efgh ijkl", "ann", "may not write posts"),
        ]
        for setup, key, user, words in cases:
            with self.subTest(words):
                self.use(WordPress(**setup))
                with self.assertRaisesRegex(sites.SiteError, words):
                    self.connect(user, key)
        self.assertEqual(sites.listing(self.cfg), [], "nothing that failed is kept")

    def test_a_server_lock_and_a_wrong_address_are_told_apart(self):
        sites.FETCH = lambda *a, **k: (401, {"_page": "401 Authorization Required", "_locked": True})
        with self.assertRaisesRegex(sites.SiteError, "web server asks for a password of its own"):
            self.connect()
        sites.FETCH = lambda *a, **k: (200, {"_page": "Welcome to my shop"})
        with self.assertRaisesRegex(sites.SiteError, "No WordPress answered at https://blog.example.com"):
            self.connect()

    def test_a_notice_printed_before_the_answer_does_not_spoil_it(self):
        self.assertEqual(sites._decoded(b"\n<br />\n<b>Deprecated</b>: something in plugin.php\n{\"id\": 5}"), {"id": 5})
        self.assertEqual(sites._decoded(b"<html><body>Hello</body></html>"), {"_page": "Hello"})


class WordPressCom:
    """WordPress.com's own API: a token for the owner's app, user and application password, then wp/v2 through it."""

    def __init__(self):
        self.calls = []

    def __call__(self, method, url, headers, body=None, form=False):
        self.calls.append((method, url, dict(headers), body))
        if url == sites.WPCOM_API + "/oauth2/token":
            if body.get("client_secret") != "S3cretS3cretS3cretS3cret":
                return 400, {"error": "invalid_client", "error_description": "Unknown client_id or client_secret."}
            if (body["username"], body["password"]) != ("annwp", "wxyz wxyz wxyz") or body["grant_type"] != "password":
                return 400, {"error": "invalid_request", "error_description": "Incorrect username or password."}
            return 200, {"access_token": "wpcom-token-1", "token_type": "bearer", "blog_id": "0"}
        if headers.get("Authorization") != "Bearer wpcom-token-1":
            return 401, {"code": "rest_forbidden", "message": "Sorry"}
        if url.startswith(sites.WPCOM_API + "/rest/v1.1/sites/annwrites.wordpress.com"):
            return 200, {"name": "Ann Writes"}
        if url.startswith(sites.WPCOM_API + "/wp/v2/sites/annwrites.wordpress.com/posts"):
            return (200, []) if method == "GET" else (201, {"id": 4, "link": "https://annwrites.wordpress.com/2026/11/17/hello/"})
        return 404, {"code": "rest_no_route"}


class TheWordPressComWay(SitesCase):
    def test_a_wordpress_com_site_posts_through_its_own_api(self):
        site = WordPressCom()
        sites.FETCH = site
        added = sites.add(self.cfg, "wordpresscom", "annwrites.wordpress.com", "wxyz wxyz wxyz", user="annwp",
                          client_id="12345", client_secret="S3cretS3cretS3cretS3cret")
        self.assertEqual((added["name"], added["label"]), ("Ann Writes", "WordPress.com"))
        self.assertEqual(secrets._cred_read("site-" + added["id"]), "12345:S3cretS3cretS3cretS3cret:wxyz wxyz wxyz", "kept in the key store, never a file")
        self.assertNotIn("S3cret", (self.cfg.state_dir / "sites.json").read_text("utf-8"))
        made = sites.stage(self.cfg, added["id"], "post", "s", title="Hello", content="<p>Hi</p>")
        self.assertEqual(sites.publish(self.cfg, made["id"])["state"], "published")
        method, url, headers, body = site.calls[-1]
        self.assertEqual((method, url, headers["Authorization"], body["status"]),
                         ("POST", sites.WPCOM_API + "/wp/v2/sites/annwrites.wordpress.com/posts", "Bearer wpcom-token-1", "publish"))
        # A new application password keeps the same app.
        sites._TOKENS.clear()
        sites.rekey(self.cfg, added["id"], "wxyz wxyz wxyz")
        self.assertEqual(secrets._cred_read("site-" + added["id"]), "12345:S3cretS3cretS3cretS3cret:wxyz wxyz wxyz")

    def test_what_wordpress_com_refuses_is_said_plainly(self):
        sites.FETCH = WordPressCom()
        with self.assertRaisesRegex(sites.SiteError, "Client ID or Client Secret"):
            sites.add(self.cfg, "wordpresscom", "annwrites.wordpress.com", "wxyz wxyz wxyz", user="annwp", client_id="12345", client_secret="WrongWrongWrongWrongWrong")
        with self.assertRaisesRegex(sites.SiteError, "user name or password is not right"):
            sites.add(self.cfg, "wordpresscom", "annwrites.wordpress.com", "my password", user="annwp", client_id="12345", client_secret="S3cretS3cretS3cretS3cret")
        with self.assertRaisesRegex(sites.SiteError, "Client ID"):
            sites.add(self.cfg, "wordpresscom", "annwrites.wordpress.com", "wxyz wxyz wxyz", user="annwp", client_id="", client_secret="S3cretS3cretS3cretS3cret")
        self.assertEqual(sites.listing(self.cfg), [])
