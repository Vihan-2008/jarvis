"""A real browser inside the Browser panel.

A hidden Edge (or Chrome) window with its own separate profile loads the page. Its live picture
is sent to the panel and the owner's clicks, scrolling and typing are passed back, so any site
works, including ones that refuse to be embedded. Only the owner drives it: nothing here lets a
model browse on its own. Downloads are refused and pop-ups open in the same view.
"""
from __future__ import annotations

import base64
import json
import os
import queue
import re
import shutil
import socket
import struct
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlparse

IDLE_SECONDS = 600
# Runs in every page. It only notices a sign-in being submitted and offers it to JARVIS; nothing is
# stored unless the owner presses Save in the panel.
LOGIN_WATCH = ("(()=>{if(window.__jv)return;window.__jv=1;const T=['text','email','tel',''];"
               "const grab=f=>{try{if(typeof window.jarvisLogin!=='function')return;const s=f||document;"
               "const pw=[...s.querySelectorAll('input[type=password]')].find(i=>i.value);if(!pw)return;"
               "const fs=[...(pw.form||document).querySelectorAll('input')].filter(i=>T.includes((i.getAttribute('type')||'').toLowerCase())&&i.value&&i.offsetParent!==null);"
               "const b=fs.filter(i=>pw.compareDocumentPosition(i)&2);const u=(b.pop()||fs[0]||{}).value||'';"
               "window.jarvisLogin(JSON.stringify({u:String(u).slice(0,200),p:String(pw.value).slice(0,300)}))}catch(e){}};"
               "addEventListener('submit',e=>grab(e.target),true);"
               "addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target&&e.target.tagName==='INPUT')grab(e.target.form)},true);"
               "addEventListener('click',e=>{const b=e.target&&e.target.closest&&e.target.closest('button,input[type=submit],[role=button]');if(b)grab(b.form||b.closest('form'))},true)})()")
SCREEN_WATCH = ("(()=>{if(window.__jf)return;window.__jf=1;document.addEventListener('fullscreenchange',()=>{"
                "try{window.jarvisScreen(document.fullscreenElement?'1':'0')}catch(e){}})})()")
LOGIN_FILL = ("((u,p)=>{const T=['text','email','tel',''];const vis=i=>i.offsetParent!==null;"
              "const set=(el,v)=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,v);"
              "el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}))};"
              "const pw=[...document.querySelectorAll('input[type=password]')].find(vis);"
              "const fs=[...((pw&&pw.form)||document).querySelectorAll('input')].filter(i=>T.includes((i.getAttribute('type')||'').toLowerCase())&&vis(i));"
              "const user=pw?(fs.filter(i=>pw.compareDocumentPosition(i)&2).pop()||fs[0]):fs.find(i=>/user|email|login|name|id/i.test((i.name||'')+(i.id||'')+(i.autocomplete||'')))||fs[0];"
              "if(user&&u)set(user,u);if(pw)set(pw,p);return !!(pw||user)})")


class CredentialStore:
    """Saved sign-ins live in Windows Credential Manager, never in files."""

    def get(self, name: str) -> str | None:
        from jcc import secrets
        return secrets._cred_read(name)

    def set(self, name: str, value: str) -> None:
        from jcc import secrets
        secrets.store(name, value)

    def delete(self, name: str) -> None:
        from jcc import secrets
        secrets.delete(name)


def site_of(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return ""
    return parsed.hostname.lower() + (f":{parsed.port}" if parsed.port else "")
SAME_TAB = ("(()=>{window.open=u=>{if(u)location.href=u;return window};"
            "addEventListener('click',e=>{const a=e.target&&e.target.closest&&e.target.closest('a[target]');"
            "if(a&&a.target!=='_self')a.target='_self'},true)})()")


def sign_in_site(url: str) -> str:
    """The site a saved sign-in belongs to. Only secure (https) pages count, so a password saved on the
    real site is never offered to a look-alike reached over an unprotected connection."""
    parsed = urlparse(url)
    local = parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")   # this PC itself: nobody in between
    return site_of(url) if parsed.scheme == "https" or local else ""


def find_browser() -> str | None:
    if os.name != "nt":
        from jcc import system
        return next(iter(system.browsers()), None)
    roots = [os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), os.environ.get("ProgramFiles", r"C:\Program Files"),
             os.environ.get("LOCALAPPDATA", "")]
    for tail in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
        for root in roots:
            path = Path(root) / tail if root else None
            if path and path.exists():
                return str(path)
    return shutil.which("msedge") or shutil.which("chrome") or shutil.which("chromium")


def target_url(query: str) -> str:
    query = str(query).strip()
    if not query or len(query) > 2000:
        raise ValueError("Enter a web address or something to search for.")
    if re.match(r"^https?://", query, re.I):
        url = query
    elif re.fullmatch(r"(localhost|[\w-]+(\.[\w-]+)+)(:\d+)?(/\S*)?", query):
        url = ("http://" if query.startswith("localhost") else "https://") + query
    else:
        url = "https://www.google.com/search?q=" + quote(query)
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Enter a normal web address, without a password in it.")
    return url


class Socket:
    """The small part of the WebSocket protocol needed to talk to a local browser."""

    def __init__(self, url: str):
        parsed = urlparse(url)
        self.sock = socket.create_connection((parsed.hostname, parsed.port), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {parsed.path} HTTP/1.1\r\nHost: {parsed.hostname}:{parsed.port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            part = self.sock.recv(4096)
            if not part:
                raise OSError("browser closed the connection")
            head += part
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise OSError("browser refused the connection")
        self.rest = head.split(b"\r\n\r\n", 1)[1]
        self.sock.settimeout(None)
        self.write_lock = threading.Lock()

    def _frame(self, opcode: int, payload: bytes) -> None:
        mask, size = os.urandom(4), len(payload)
        head = bytes([0x80 | opcode]) + (bytes([0x80 | size]) if size < 126 else
                                         bytes([0x80 | 126]) + struct.pack(">H", size) if size < 65536 else
                                         bytes([0x80 | 127]) + struct.pack(">Q", size))
        body = bytes(b ^ mask[i & 3] for i, b in enumerate(payload))
        with self.write_lock:
            self.sock.sendall(head + mask + body)

    def send(self, text: str) -> None:
        self._frame(1, text.encode("utf-8"))

    def _take(self, count: int) -> bytes:
        chunks, have = [self.rest], len(self.rest)
        while have < count:
            part = self.sock.recv(max(65536, count - have))
            if not part:
                raise OSError("browser closed the connection")
            chunks.append(part)
            have += len(part)
        data = b"".join(chunks)
        self.rest = data[count:]
        return data[:count]

    def receive(self) -> str:
        message = b""
        while True:
            first, second = self._take(2)
            opcode, size = first & 0x0F, second & 0x7F
            if size == 126:
                size = struct.unpack(">H", self._take(2))[0]
            elif size == 127:
                size = struct.unpack(">Q", self._take(8))[0]
            payload = self._take(size)
            if opcode == 8:
                raise OSError("browser closed the connection")
            if opcode == 9:
                self._frame(10, payload)
                continue
            if opcode in (0, 1, 2):
                message += payload
                if first & 0x80:
                    return message.decode("utf-8", errors="replace")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class Pipe:
    """A private two-way pipe to the hidden browser.

    The browser is told to take its commands from this pipe instead of opening a debugging port, so
    nothing else on this PC (no other program, no other Windows account) can reach its controls."""

    def __init__(self, read_fd: int, write_fd: int):
        self.read_fd, self.write_fd = read_fd, write_fd
        self.lock = threading.Lock()
        self.next, self.waiting, self.tabs, self.alive, self.events = 1_000_000_000, {}, {}, True, None
        threading.Thread(target=self._read, daemon=True, name="webview-pipe").start()

    def write(self, message: dict) -> None:
        data = memoryview(json.dumps(message).encode("utf-8") + b"\0")
        with self.lock:
            if not self.alive:
                raise OSError("browser closed the connection")
            while data:
                data = data[os.write(self.write_fd, data):]

    def call(self, method: str, params: dict | None = None, timeout: float = 15.0) -> dict:
        """A command for the browser as a whole (tabs, downloads), not for one page."""
        with self.lock:
            self.next += 1
            ident, slot = self.next, {"event": threading.Event(), "result": None}
            self.waiting[ident] = slot
        try:
            self.write({"id": ident, "method": method, "params": params or {}})
        except OSError:
            self.waiting.pop(ident, None)
            raise ValueError("The built-in browser stopped. Open the page again.") from None
        if not slot["event"].wait(timeout) or slot["result"] is None:
            self.waiting.pop(ident, None)
            raise ValueError("The built-in browser took too long to respond.")
        return slot["result"]

    def attach(self, target_id: str) -> "Tab":
        tab = Tab(self, self.call("Target.attachToTarget", {"targetId": target_id, "flatten": True})["sessionId"])
        self.tabs[tab.session] = tab
        return tab

    def _read(self) -> None:
        pending = bytearray()
        try:
            while True:
                piece = os.read(self.read_fd, 1 << 18)
                if not piece:
                    break
                pending += piece
                while True:
                    end = pending.find(b"\0")
                    if end < 0:
                        break
                    raw, pending = bytes(pending[:end]), pending[end + 1:]
                    try:
                        data = json.loads(raw)
                    except ValueError:
                        continue
                    session = data.get("sessionId")
                    if session:
                        tab = self.tabs.get(session)
                        if tab:
                            tab.inbox.put(data)
                    elif "id" in data:
                        slot = self.waiting.pop(data["id"], None)
                        if slot:
                            slot["result"] = data.get("result") if "error" not in data else None
                            slot["event"].set()
                    elif self.events:
                        try:
                            self.events(data.get("method"), data.get("params") or {})
                        except Exception:  # noqa: BLE001 - one odd event must not end the connection
                            pass
        except OSError:
            pass
        finally:
            self.alive = False
            for slot in list(self.waiting.values()):
                slot["event"].set()
            for tab in list(self.tabs.values()):
                tab.inbox.put(None)

    def close(self) -> None:
        """Closed without ever hanging. On Windows, closing the reading end while the reader thread is still waiting on it
        can block until the browser writes again (seen on GitHub's Windows machine: closing the last tab never returned).
        So the writing end goes first (the browser sees the end of its input and stops), and the closing is done on a
        thread of its own that is waited for a few seconds at most."""
        self.alive = False

        def shut():
            for handle in (self.write_fd, self.read_fd):
                try:
                    os.close(handle)
                except OSError:
                    pass
        closer = threading.Thread(target=shut, daemon=True, name="webview-pipe-close")
        closer.start()
        closer.join(3)


class Tab:
    """One page's share of the pipe. Looks like a connection of its own to the rest of the code."""

    def __init__(self, pipe: Pipe, session: str):
        self.pipe, self.session, self.inbox = pipe, session, queue.Queue()

    def send(self, text: str) -> None:
        self.pipe.write({**json.loads(text), "sessionId": self.session})

    def receive(self) -> dict:
        message = self.inbox.get()
        if message is None:
            raise OSError("browser closed the connection")
        return message

    def close(self) -> None:
        self.pipe.tabs.pop(self.session, None)
        self.inbox.put(None)
        try:
            self.pipe.write({"id": 0, "method": "Target.detachFromTarget", "params": {"sessionId": self.session}})
        except OSError:
            pass


def _open_pipes():
    """(our read end, our write end, the browser's read handle, the browser's write handle). Windows only."""
    import _winapi
    import msvcrt
    theirs_in, ours_out = _winapi.CreatePipe(None, 1 << 16)       # we write, the browser reads
    ours_in, theirs_out = _winapi.CreatePipe(None, 1 << 20)       # the browser writes (live pictures are large), we read
    for handle in (theirs_in, theirs_out):
        os.set_handle_inheritable(handle, True)
    return msvcrt.open_osfhandle(ours_in, os.O_RDONLY), msvcrt.open_osfhandle(ours_out, 0), theirs_in, theirs_out


class WebView:
    def __init__(self, cfg, store=None):
        self.cfg = cfg
        self.store = store or CredentialStore()
        self.offer, self.main_frame, self.contexts, self.known = None, "", {}, {}
        self.lock = threading.RLock()
        self.changed = threading.Condition()
        self.proc = self.ws = self.pipe = None
        self.next_id, self.waiting = 0, {}
        self.frame, self.seq = b"", 0
        self.url, self.title, self.loading = "", "", False
        self.width, self.height, self.scale = 1000, 700, 1.0
        self.used = time.time()
        self.active, self.chooser, self.downloads, self._listing = "", None, [], (0.0, [])
        self.fullscreen = False

    # ------------------------------------------------------------------ lifecycle
    def running(self) -> bool:
        return bool(self.proc and self.proc.poll() is None and self.ws and self.pipe and self.pipe.alive)

    def start(self) -> None:
        with self.lock:
            if self.running():
                return
            self.stop()
            exe = find_browser()
            if not exe:
                raise ValueError("Microsoft Edge or Google Chrome is needed for the built-in browser.")
            profile = self.cfg.state_dir / "webview-profile"
            profile.mkdir(parents=True, exist_ok=True)
            if os.name != "nt":
                raise ValueError("The built-in browser works on Windows only.")
            self._end_leftover(profile)
            (profile / "DevToolsActivePort").unlink(missing_ok=True)
            try:
                from jcc.assistant import light_mode
                self.light = light_mode(self.cfg)
            except Exception:  # noqa: BLE001 - settings are optional here
                self.light = False
            extra = ["--renderer-process-limit=2", "--disable-background-networking", "--disable-features=Translate,OptimizationHints",
                     "--js-flags=--max-old-space-size=384"] if self.light else []
            read_fd, write_fd, browser_in, browser_out = _open_pipes()
            startup = subprocess.STARTUPINFO()
            startup.lpAttributeList = {"handle_list": [browser_in, browser_out]}   # the browser receives these two handles and nothing else
            try:
                # --remote-debugging-pipe: commands travel over the private pipe; no debugging port is opened.
                self.proc = subprocess.Popen(
                    [exe, "--headless=new", "--remote-debugging-pipe", f"--remote-debugging-io-pipes={browser_in},{browser_out}",
                     f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check", "--disable-extensions",
                     "--hide-scrollbars=false", *extra, f"--window-size={self.width},{self.height}", "about:blank"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startup,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            finally:
                import _winapi
                for handle in (browser_in, browser_out):
                    _winapi.CloseHandle(handle)
            try:
                (profile / "jarvis-browser.pid").write_text(str(self.proc.pid), "utf-8")
            except OSError:
                pass
            self.pipe = Pipe(read_fd, write_fd)
            self.pipe.events = self._browser_event
            page, deadline = None, time.time() + 20
            while time.time() < deadline and not page:
                if self.proc.poll() is not None or not self.pipe.alive:
                    self.stop()
                    raise ValueError("The built-in browser could not start.")
                try:
                    page = next((t for t in self._targets(True) if str(t.get("url", "")).startswith("about:")), None)
                except ValueError:
                    page = None
                if not page:
                    time.sleep(0.1)
            if not page:
                self.stop()
                raise ValueError("The built-in browser could not open a page.")
            folder = Path.home() / "Downloads" / "JARVIS"
            folder.mkdir(parents=True, exist_ok=True)
            try:
                self.pipe.call("Browser.setDownloadBehavior", {"behavior": "allow", "downloadPath": str(folder), "eventsEnabled": True})
            except ValueError:
                pass
            self._attach(page)

    def _browser_event(self, method: str, params: dict) -> None:
        """Things the browser reports for all tabs together: files being downloaded."""
        if method == "Browser.downloadWillBegin":
            name = str(params.get("suggestedFilename") or "file")[:120]
            if not any(d["id"] == params.get("guid") for d in self.downloads):
                self.downloads = (self.downloads + [{"id": params.get("guid"), "name": name, "state": "started"}])[-8:]
                self._touch()
        elif method == "Browser.downloadProgress" and params.get("state") in ("completed", "canceled"):
            for row in self.downloads:
                if row["id"] == params.get("guid") and row["state"] == "started":
                    row["state"] = "saved" if params["state"] == "completed" else "cancelled"
                    self._touch()

    # ------------------------------------------------------------------ tabs
    def _attach(self, target: dict) -> None:
        """Show one tab: connect to it and start its live picture. Other tabs keep running unseen."""
        old, self.ws = self.ws, None
        if old:
            old.close()
        self.active, self.url = target["id"], target.get("url", "") if target.get("url") != "about:blank" else ""
        self.contexts, self.offer, self.chooser, self.main_frame, self.loading = {}, None, None, "", False
        self.fullscreen = False
        with self.changed:
            self.frame = b""
        self.ws = self.pipe.attach(target["id"])
        threading.Thread(target=self._listen, args=(self.ws,), daemon=True, name="webview").start()
        folder = Path.home() / "Downloads" / "JARVIS"
        folder.mkdir(parents=True, exist_ok=True)
        for method, params in (("Page.enable", {}), ("Runtime.enable", {}),
                               ("Page.addScriptToEvaluateOnNewDocument", {"source": SAME_TAB}),
                               ("Runtime.addBinding", {"name": "jarvisLogin"}),
                               ("Page.addScriptToEvaluateOnNewDocument", {"source": LOGIN_WATCH}),
                               ("Page.setDownloadBehavior", {"behavior": "allow", "downloadPath": str(folder)}),
                               ("Page.setInterceptFileChooserDialog", {"enabled": True}),
                               ("Runtime.addBinding", {"name": "jarvisScreen"}),
                               ("Page.addScriptToEvaluateOnNewDocument", {"source": SCREEN_WATCH}),
                               ("Runtime.evaluate", {"expression": SAME_TAB}), ("Runtime.evaluate", {"expression": LOGIN_WATCH}),
                               ("Runtime.evaluate", {"expression": SCREEN_WATCH}),
                               ("Page.bringToFront", {})):  # a page may only go full screen when it is the front one
            self.call(method, params, wait=False)
        self._metrics()
        self.call("Page.startScreencast", {"format": "jpeg", "quality": 58 if self.light else 72,
                                           "everyNthFrame": 2 if self.light else 1}, wait=False)
        self._listing = (0.0, [])
        self._touch()

    def _targets(self, fresh: bool = False) -> list[dict]:
        if not (self.proc and self.proc.poll() is None and self.pipe and self.pipe.alive):
            return []
        at, rows = self._listing
        if fresh or time.time() - at > 0.8:
            try:
                # Only real pages count as tabs; the browser's own internal pages (first-run dialogs and so on) do not.
                rows = [{"id": t["targetId"], "type": t.get("type"), "title": t.get("title", ""), "url": t.get("url", "")}
                        for t in self.pipe.call("Target.getTargets", timeout=5).get("targetInfos", [])
                        if t.get("type") == "page" and str(t.get("url", "")).startswith(("http://", "https://", "about:"))]
            except (ValueError, AttributeError, KeyError):
                rows = []
            self._listing = (time.time(), rows)
        return rows

    def tabs(self) -> list[dict]:
        def name(t):
            title, url = str(t.get("title") or ""), str(t.get("url") or "")
            if url in ("", "about:blank"):
                return "New tab"
            return (site_of(url) or "Page") if title in ("", "about:blank") or title == url else title[:80]
        return [{"id": t["id"], "title": name(t),
                 "active": t["id"] == self.active} for t in self._targets()]

    def new_tab(self, query: str = "") -> dict:
        self.used = time.time()
        if not self.running():
            self.start()
            return self.open(query) if query.strip() else {"opened": ""}
        if len(self._targets(True)) >= 8:
            raise ValueError("Close a tab before opening another.")
        target = {"id": self.pipe.call("Target.createTarget", {"url": "about:blank"})["targetId"], "url": "about:blank"}
        with self.lock:
            self._attach(target)
        return self.open(query) if query.strip() else {"opened": ""}

    def switch_tab(self, ident: str) -> dict:
        self.used = time.time()
        target = next((t for t in self._targets(True) if t["id"] == ident), None)
        if not target:
            raise ValueError("That tab is no longer open.")
        if ident != self.active:
            with self.lock:
                self._attach(target)
        return {"ok": True}

    def close_tab(self, ident: str) -> dict:
        targets = self._targets(True)
        if not any(t["id"] == ident for t in targets):
            raise ValueError("That tab is no longer open.")
        if len(targets) <= 1:
            self.stop()
            return {"closed": True, "last": True}
        if ident == self.active:
            with self.lock:
                self._attach(next(t for t in targets if t["id"] != ident))
        try:
            self.pipe.call("Target.closeTarget", {"targetId": ident}, timeout=5)
        except (ValueError, AttributeError):
            pass
        self._listing = (0.0, [])
        self._touch()
        return {"closed": True}

    # ------------------------------------------------------------------ files going in and out
    def upload(self, name: str, data: bytes) -> dict:
        """Give the page the file its own 'choose file' button asked for."""
        if not self.chooser:
            raise ValueError("The page is not asking for a file right now.")
        if not data or len(data) > 25_000_000:
            raise ValueError("Choose a file of up to 25 MB.")
        import secrets as _rand
        safe = re.sub(r"[^\w. ()-]", "_", Path(str(name)).name)[:120].strip(". ") or "file"
        folder = self.cfg.state_dir / "web-uploads" / _rand.token_hex(6)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / safe).write_bytes(data)
        chooser, self.chooser = self.chooser, None
        self.call("DOM.setFileInputFiles", {"files": [str(folder / safe)], "backendNodeId": chooser})
        self._touch()
        return {"uploaded": safe}

    def leave_fullscreen(self) -> dict:
        self.call("Runtime.evaluate", {"expression": "document.fullscreenElement&&document.exitFullscreen()"}, wait=False)
        self.fullscreen = False
        return {"ok": True}

    def cancel_upload(self) -> dict:
        self.chooser = None
        self._touch()
        return {"ok": True}

    @staticmethod
    def _end_leftover(profile: Path) -> None:
        """If JARVIS was closed abruptly, its hidden browser may still be running. End that one only."""
        record = profile / "jarvis-browser.pid"
        try:
            pid = int(record.read_text("utf-8").strip())
        except (OSError, ValueError):
            return
        record.unlink(missing_ok=True)
        if os.name != "nt" or pid <= 0:
            return
        listing = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                                 creationflags=subprocess.CREATE_NO_WINDOW).stdout.lower()
        if "msedge.exe" in listing or "chrome.exe" in listing:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            time.sleep(0.3)

    def stop(self) -> None:
        with self.lock:
            ws, proc, pipe, self.ws, self.proc, self.pipe = self.ws, self.proc, self.pipe, None, None, None
        if ws:
            ws.close()
        # The browser is stopped first: its end of the pipe closes with it, so the reader thread is no longer waiting when
        # the pipe is closed (closing it under a waiting reader could hang on Windows).
        if proc and proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        if pipe:
            pipe.close()
        self.active, self.chooser, self._listing = "", None, (0.0, [])
        shutil.rmtree(self.cfg.state_dir / "web-uploads", ignore_errors=True)
        with self.changed:
            self.changed.notify_all()

    def idle_check(self) -> None:
        if self.running() and time.time() - self.used > (180 if getattr(self, "light", False) else IDLE_SECONDS):
            self.stop()

    # ------------------------------------------------------------------ protocol
    def call(self, method: str, params: dict | None = None, wait: bool = True, timeout: float = 15.0):
        ws = self.ws
        if not ws:
            raise ValueError("The built-in browser is not running.")
        with self.lock:
            self.next_id += 1
            ident = self.next_id
            slot = {"event": threading.Event(), "result": None} if wait else None
            if slot:
                self.waiting[ident] = slot
        try:
            ws.send(json.dumps({"id": ident, "method": method, "params": params or {}}))
        except OSError:
            self.waiting.pop(ident, None)
            raise ValueError("The built-in browser stopped. Open the page again.") from None
        if not slot:
            return None
        if not slot["event"].wait(timeout):
            self.waiting.pop(ident, None)
            raise ValueError("The page took too long to respond.")
        return slot["result"]

    def _listen(self, ws) -> None:
        try:
            while True:
                data = ws.receive()
                data = json.loads(data) if isinstance(data, str) else data
                if "id" in data:
                    slot = self.waiting.pop(data["id"], None)
                    if slot:
                        slot["result"] = data.get("result") or {}
                        slot["event"].set()
                    continue
                method, params = data.get("method"), data.get("params") or {}
                if method == "Page.screencastFrame":
                    try:
                        image = base64.b64decode(params.get("data", ""))
                    except ValueError:
                        image = b""
                    with self.changed:
                        self.frame, self.seq = image, self.seq + 1
                        self.changed.notify_all()
                    try:
                        ws.send(json.dumps({"id": 0, "method": "Page.screencastFrameAck", "params": {"sessionId": params.get("sessionId")}}))
                    except OSError:
                        return
                elif method == "Page.frameNavigated" and not params.get("frame", {}).get("parentId"):
                    self.url, self.main_frame = params["frame"].get("url", ""), params["frame"].get("id", "")
                    self._touch()
                elif method == "Runtime.executionContextCreated":
                    context = params.get("context", {})
                    self.contexts[context.get("id")] = (context.get("auxData") or {}).get("frameId", "")
                elif method == "Runtime.executionContextsCleared":
                    self.contexts = {}
                elif method == "Runtime.bindingCalled" and params.get("name") == "jarvisLogin":
                    # Only the page the owner is looking at may offer a sign-in, never an embedded frame.
                    if self.contexts.get(params.get("executionContextId")) == self.main_frame:
                        self._offer(params.get("payload", ""))
                elif method == "Page.navigatedWithinDocument":
                    self.url = params.get("url", self.url)
                    self._touch()
                elif method in ("Page.frameStartedLoading", "Page.frameStoppedLoading"):
                    self.loading = method.endswith("StartedLoading")
                    self._listing = (0.0, [])
                    self._touch()
                elif method == "Runtime.bindingCalled" and params.get("name") == "jarvisScreen":
                    self.fullscreen = params.get("payload") == "1"
                    self._touch()
                elif method == "Page.fileChooserOpened":
                    self.chooser = params.get("backendNodeId")
                    self._touch()
                elif method == "Page.javascriptDialogOpening":
                    ws.send(json.dumps({"id": 0, "method": "Page.handleJavaScriptDialog", "params": {"accept": False}}))
        except (OSError, ValueError):
            pass
        finally:
            if self.ws is ws or self.ws is None:  # a tab switch closes the old connection on purpose
                for slot in list(self.waiting.values()):
                    slot["event"].set()
            with self.changed:
                self.changed.notify_all()

    # ------------------------------------------------------------------ saved sign-ins
    def _never(self) -> list:
        path = self.cfg.state_dir / "web-never-save.json"
        try:
            return json.loads(path.read_text("utf-8")) if path.exists() else []
        except (OSError, ValueError):
            return []

    def _saved(self, site: str) -> dict | None:
        if not site:
            return None
        if site not in self.known:
            try:
                raw = self.store.get("web/" + site)
                data = json.loads(raw) if raw else None
            except (OSError, ValueError, RuntimeError):
                data = None
            self.known[site] = data if isinstance(data, dict) and data.get("p") else None
        return self.known[site]

    def _offer(self, payload: str) -> None:
        site = sign_in_site(self.url)
        try:
            data = json.loads(payload)
            user, password = str(data.get("u", ""))[:200], str(data.get("p", ""))[:300]
        except (ValueError, AttributeError):
            return
        saved = self._saved(site)
        if not site or not password or site in self._never() or (saved and saved.get("u") == user and saved.get("p") == password):
            return
        self.offer = {"site": site, "u": user, "p": password, "at": time.time()}
        self._touch()

    def login(self, decision: str) -> dict:
        self.used = time.time()
        site = sign_in_site(self.url)
        if decision in ("save", "dismiss", "never"):
            offer, self.offer = self.offer, None
            if offer and decision == "save":
                self.store.set("web/" + offer["site"], json.dumps({"u": offer["u"], "p": offer["p"]}))
                self.known[offer["site"]] = {"u": offer["u"], "p": offer["p"]}
            elif offer and decision == "never":
                from jcc.vault import atomic_write
                atomic_write(self.cfg.state_dir / "web-never-save.json", json.dumps(sorted({*self._never(), offer["site"]})[:500]))
            self._touch()
            return {"ok": True}
        if decision == "fill":
            saved = self._saved(site)
            if not saved:
                raise ValueError("No saved sign-in for this site.")
            result = self.call("Runtime.evaluate", {"expression": LOGIN_FILL + "(" + json.dumps(saved.get("u", "")) + "," + json.dumps(saved["p"]) + ")",
                                                    "returnByValue": True})
            if not (result or {}).get("result", {}).get("value"):
                raise ValueError("There is no sign-in box on this page to fill.")
            return {"filled": True}
        if decision == "forget":
            if self._saved(site):
                try:
                    self.store.delete("web/" + site)
                except (OSError, AttributeError):
                    self.store.set("web/" + site, json.dumps({"u": "", "p": ""}))
                self.known[site] = None
            return {"ok": True}
        raise ValueError("Unknown sign-in action.")

    def _touch(self) -> None:
        with self.changed:
            self.seq += 1
            self.changed.notify_all()

    def _metrics(self) -> None:
        self.call("Emulation.setDeviceMetricsOverride", {"width": self.width, "height": self.height,
                                                         "deviceScaleFactor": self.scale, "mobile": False}, wait=False)

    # ------------------------------------------------------------------ owner actions
    def open(self, query: str) -> dict:
        url = target_url(query)
        self.start()
        self.used = time.time()
        self.url, self.loading = url, True
        self.call("Page.navigate", {"url": url}, wait=False)
        return {"opened": url}

    def history(self, step: int) -> dict:
        self.used = time.time()
        data = self.call("Page.getNavigationHistory")
        entries, index = data.get("entries", []), data.get("currentIndex", 0) + step
        if 0 <= index < len(entries):
            self.call("Page.navigateToHistoryEntry", {"entryId": entries[index]["id"]}, wait=False)
        return {"ok": True}

    def reload(self) -> dict:
        self.used = time.time()
        self.call("Page.reload", {}, wait=False)
        return {"ok": True}

    def resize(self, width, height, scale=1) -> dict:
        try:
            self.width, self.height = max(320, min(2400, int(width))), max(240, min(1800, int(height)))
            self.scale = max(1.0, min(2.0, float(scale)))
        except (TypeError, ValueError):
            raise ValueError("Invalid size.") from None
        if self.running():
            self._metrics()
        return {"ok": True}

    def inputs(self, events) -> dict:
        if not isinstance(events, list) or len(events) > 200:
            raise ValueError("Invalid input.")
        self.used = time.time()
        for event in events:
            if not isinstance(event, dict):
                continue
            kind = event.get("t")
            modifiers = int(event.get("m", 0)) & 15
            if kind in ("mousePressed", "mouseReleased", "mouseMoved", "mouseWheel"):
                params = {"type": kind, "x": float(event.get("x", 0)), "y": float(event.get("y", 0)), "modifiers": modifiers,
                          "button": event.get("b") if event.get("b") in ("left", "middle", "right") else "none",
                          "buttons": int(event.get("bs", 0)) & 7, "clickCount": max(0, min(3, int(event.get("c", 0))))}
                if kind == "mouseWheel":
                    params.update(deltaX=float(event.get("dx", 0)), deltaY=float(event.get("dy", 0)))
                self.call("Input.dispatchMouseEvent", params, wait=False)
            elif kind in ("keyDown", "keyUp"):
                text = str(event.get("text", ""))[:8]
                params = {"type": "keyDown" if kind == "keyDown" and text else "rawKeyDown" if kind == "keyDown" else "keyUp",
                          "key": str(event.get("key", ""))[:32], "code": str(event.get("code", ""))[:32], "modifiers": modifiers,
                          "windowsVirtualKeyCode": int(event.get("vk", 0)) & 0xFFFF, "nativeVirtualKeyCode": int(event.get("vk", 0)) & 0xFFFF}
                if kind == "keyDown" and text:
                    params.update(text=text, unmodifiedText=text)
                self.call("Input.dispatchKeyEvent", params, wait=False)
            elif kind == "text":
                self.call("Input.insertText", {"text": str(event.get("text", ""))[:20000]}, wait=False)
        return {"ok": True}

    def page_text(self, automatic: bool = False) -> dict:
        """Readable text of the open page. Typed-in values such as passwords are never part of it."""
        self.used = time.time()
        if automatic:
            from jcc.computer import SENSITIVE
            if SENSITIVE.search(self.url):
                return {"skipped": True, "reason": "Private pages such as sign-in, banking and payments are not shared automatically."}
        result = self.call("Runtime.evaluate", {"expression": "JSON.stringify({title:document.title,text:(document.body&&document.body.innerText||'').slice(0,180000)})",
                                                "returnByValue": True})
        try:
            data = json.loads(result.get("result", {}).get("value", "{}"))
        except (ValueError, AttributeError):
            data = {}
        if automatic:
            from jcc.computer import SENSITIVE
            if SENSITIVE.search(str(data.get("title", ""))):
                return {"skipped": True, "reason": "Private pages such as sign-in, banking and payments are not shared automatically."}
        if not data.get("text"):
            raise ValueError("This page has no readable text yet.")
        return {"url": self.url, "title": data.get("title") or "Web page", "text": data["text"]}

    def snapshot(self, since: int = -1, wait: float = 0.0) -> dict:
        self.used = time.time()
        deadline = time.monotonic() + max(0.0, min(wait, 20.0))
        with self.changed:
            while self.seq <= since and self.running():
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self.changed.wait(remaining):
                    break
            frame, seq = self.frame, self.seq
        site, offer = sign_in_site(self.url), self.offer
        if offer and time.time() - offer["at"] > 180:
            offer = self.offer = None
        return {"running": self.running(), "seq": seq, "url": self.url, "loading": self.loading, "site": site,
                "login_offer": {"site": offer["site"], "user": offer["u"]} if offer else None,
                "can_fill": bool(self._saved(site)) if self.running() else False,
                "tabs": self.tabs(), "file_request": bool(self.chooser), "fullscreen": self.fullscreen,
                "downloads": [{"id": d["id"], "name": d["name"], "state": d["state"]} for d in self.downloads],
                "width": self.width, "height": self.height,
                "image": base64.b64encode(frame).decode() if frame and seq > since else ""}
