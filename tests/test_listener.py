"""The app's port is the app's alone.

What was wrong: a server made the usual way sets "reuse the address", and on Windows that lets any other program on
the PC (of any Windows account) open the very same address and port beside it. Windows then hands some of the window's
requests to that program, access token and all. A second copy of JARVIS could also start beside the first.

How it was shown, safely: on a free port of this PC, a second socket was opened beside a server made the usual way,
and Windows allowed it (the first test below keeps that on record). Beside the app's own listener it is refused.
"""
import http.client
import os
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from jcc import desktop, gui, peer

WINDOWS = os.name == "nt"


class Hello(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = b"<title>JARVIS</title>"
        try:
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except ConnectionError:
            pass                                    # (the caller hung up without reading: the app's own handler shrugs too)

    def log_message(self, *args):
        pass


def beside(port: int) -> socket.socket:
    """What another program on this PC would do: open the same address and port, asking to share it."""
    other = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        other.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        other.bind(("127.0.0.1", port))
        other.listen(1)
    except OSError:
        other.close()
        raise
    return other


@unittest.skipUnless(WINDOWS, "the sharing of a port described here is how Windows behaves")
class PortTest(unittest.TestCase):
    def test_on_record_a_server_made_the_usual_way_shares_its_port(self):
        usual = ThreadingHTTPServer(("127.0.0.1", 0), Hello)
        try:
            try:
                other = beside(usual.server_address[1])
            except OSError:
                self.skipTest("this Windows does not let a second program in beside the usual server")
            other.close()
        finally:
            usual.server_close()

    def test_nothing_else_can_open_the_apps_port_beside_it(self):
        own = gui.listener(0, Hello)
        try:
            port = own.server_address[1]
            with self.assertRaises(OSError):
                beside(port).close()
            plain = socket.socket(socket.AF_INET, socket.SOCK_STREAM)          # (asking for nothing special is refused too)
            try:
                with self.assertRaises(OSError):
                    plain.bind(("127.0.0.1", port))
            finally:
                plain.close()
        finally:
            own.server_close()

    def test_a_second_copy_of_the_app_is_refused_and_told_why(self):
        own = gui.listener(0, Hello)
        try:
            port = own.server_address[1]
            with self.assertRaises(OSError) as refused:
                gui.listener(port, Hello, wait=0).server_close()
            self.assertIn("held by another program", str(refused.exception.strerror))
            self.assertIn(str(port), str(refused.exception.strerror))
        finally:
            own.server_close()

    def test_a_port_that_is_let_go_of_in_time_is_taken(self):
        first = gui.listener(0, Hello)
        port = first.server_address[1]
        threading.Timer(0.5, first.server_close).start()                       # (the copy being replaced goes away shortly)
        second = gui.listener(port, Hello, wait=6, pause=0.1)
        try:
            self.assertEqual(second.server_address[1], port)
        finally:
            second.server_close()

    def test_a_port_someone_else_got_to_first_is_not_taken_over(self):
        other = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        other.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        other.bind(("127.0.0.1", 0))
        other.listen(1)
        try:
            with self.assertRaises(OSError):
                gui.listener(other.getsockname()[1], Hello, wait=0).server_close()
        finally:
            other.close()

    def test_the_app_still_answers_on_its_own_listener(self):
        own = gui.listener(0, Hello)
        threading.Thread(target=own.serve_forever, daemon=True).start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", own.server_address[1], timeout=5)
            conn.request("GET", "/")
            self.assertIn(b"JARVIS", conn.getresponse().read())
            conn.close()
        finally:
            own.shutdown()
            own.server_close()


class LauncherTest(unittest.TestCase):
    """The launcher opens the window only on JARVIS itself: its page, from a program of this Windows account."""

    def setUp(self):
        self.own = gui.listener(0, Hello)
        threading.Thread(target=self.own.serve_forever, daemon=True).start()
        self.url, desktop.URL = desktop.URL, f"http://127.0.0.1:{self.own.server_address[1]}/"

    def tearDown(self):
        desktop.URL = self.url
        self.own.shutdown()
        self.own.server_close()

    def test_this_accounts_own_listener_is_jarvis(self):
        self.assertTrue(desktop.ready())

    def test_a_listener_of_another_account_is_not_however_its_page_looks(self):
        asked, real = [], peer.answered_by_me
        peer.answered_by_me = lambda mine, theirs: asked.append((mine, theirs)) or False
        try:
            self.assertFalse(desktop.ready())
        finally:
            peer.answered_by_me = real
        self.assertEqual(asked[0][1], self.own.server_address[1])
        self.assertGreater(asked[0][0], 0)

    def test_a_listener_whose_owner_cannot_be_told_is_judged_by_its_page(self):
        real = peer.answered_by_me
        peer.answered_by_me = lambda mine, theirs: None
        try:
            self.assertTrue(desktop.ready())
        finally:
            peer.answered_by_me = real

    def test_nothing_on_the_port_is_not_ready(self):
        free = socket.socket()
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
        free.close()
        desktop.URL = f"http://127.0.0.1:{port}/"
        self.assertFalse(desktop.ready())

    @unittest.skipUnless(WINDOWS, "accounts are looked up through Windows")
    def test_the_real_lookup_finds_this_account_on_the_answering_side(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.own.server_address[1], timeout=5)
        try:
            conn.request("GET", "/")
            self.assertIs(peer.answered_by_me(conn.sock.getsockname()[1], self.own.server_address[1]), True)
            conn.getresponse().read()
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
