"""Updates (jcc/updates.py): asking GitHub which version is newest, believing only a release signed by JARVIS's maker,
fetching only exactly the signed package, and starting the install helper. GitHub is stood in for: nothing here goes
on the internet, and a test key signs the releases."""
import hashlib
import io
import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from jcc import config, desktop, ed25519, system, updates
from tests.helpers import EngineTestCase
from tests.test_gui import GuiTestCase

SEED = bytes(range(32))                       # a made-up test key (never the real one)
TEST_KEY = ed25519.public_key(SEED)
REPO = updates.repo_name(updates.DEFAULTS["repo"])


def release(version: str, files: dict, signed=True, sign_with=SEED, manifest_version=None, body="Fixes and improvements."):
    """A stand-in GitHub: the release's page and every file it holds, by address."""
    manifest = {"app": "JARVIS", "version": manifest_version or version, "tag": "v" + version,
                "files": {name: {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)} for name, data in files.items()}}
    body_bytes = json.dumps(manifest).encode("utf-8")
    base = f"https://github.com/{REPO}/releases/download/v{version}/"
    assets = [{"name": name, "browser_download_url": base + name} for name in files]
    served = {base + name: data for name, data in files.items()}
    if signed:
        assets += [{"name": updates.MANIFEST, "browser_download_url": base + updates.MANIFEST},
                   {"name": updates.SIGNATURE, "browser_download_url": base + updates.SIGNATURE}]
        served[base + updates.MANIFEST] = body_bytes
        served[base + updates.SIGNATURE] = ed25519.sign(sign_with, body_bytes).hex().encode()
    served[f"{updates.API}/repos/{REPO}/releases/latest"] = json.dumps({
        "tag_name": "v" + version, "html_url": f"https://github.com/{REPO}/releases/tag/v{version}", "body": body,
        "published_at": "2026-11-15T10:00:00Z", "assets": assets}).encode()
    return served


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class UpdateCase(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.load()
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self.app = Path(tempfile.mkdtemp(prefix="jcc-app-"))
        self.addCleanup(lambda: shutil.rmtree(self.app, ignore_errors=True))
        (self.app / "VERSION").write_text("0.1.3\n", "utf-8")
        (self.app / ".jarvis-files").write_text("VERSION\n", "utf-8")
        self.served, self.asked = {}, []
        for patch in (mock.patch.object(updates, "ROOT", self.app), mock.patch.object(updates, "PUBLIC_KEY", TEST_KEY),
                      mock.patch.object(updates, "_open", self.open), mock.patch.object(system, "PLATFORM", "win32")):
            patch.start()
            self.addCleanup(patch.stop)

    def open(self, url, accept="*/*", timeout=30.0):
        self.asked.append(url)
        if url not in self.served:
            raise OSError("not reachable")
        return Answer(self.served[url])


class TestWhatIsNewest(UpdateCase):
    def test_a_newer_signed_release_is_offered_with_its_package(self):
        self.served = release("0.1.4", {"JARVIS-windows.zip": b"PK windows", "JARVIS-mac.zip": b"PK mac"})
        found = updates.check(self.cfg)
        self.assertEqual((found["latest"], found["available"], found["signed"], found["problem"]), ("0.1.4", True, True, ""))
        self.assertEqual(found["package"]["name"], "JARVIS-windows.zip", "the package for this system")
        self.assertEqual(found["package"]["sha256"], hashlib.sha256(b"PK windows").hexdigest())
        self.assertEqual(found["notes"], "Fixes and improvements.")
        self.assertTrue(found["page"].startswith(updates.DEFAULTS["repo"] + "/releases/"))
        with mock.patch.object(system, "PLATFORM", "darwin"):
            self.assertEqual(updates.check(self.cfg)["package"]["name"], "JARVIS-mac.zip")

    def test_the_same_or_an_older_version_is_not_offered(self):
        for version in ("0.1.3", "0.1.2", "0.0.9"):
            self.served = release(version, {"JARVIS-windows.zip": b"PK"})
            found = updates.check(self.cfg)
            self.assertEqual((found["available"], found["problem"]), (False, ""), version)
        self.served = release("0.1.10", {"JARVIS-windows.zip": b"PK"})
        self.assertTrue(updates.check(self.cfg)["available"], "0.1.10 is newer than 0.1.3 (numbers, not letters)")

    def test_only_a_release_signed_by_its_maker_is_believed(self):
        cases = {"not signed": dict(signed=False), "signed by someone else": dict(sign_with=bytes(32)),
                 "a list for another version": dict(manifest_version="0.9.9")}
        for why, change in cases.items():
            self.served = release("0.1.4", {"JARVIS-windows.zip": b"PK"}, **change)
            found = updates.check(self.cfg)
            self.assertEqual((found["available"], found["signed"]), (True, False), why)
            self.assertTrue(found["problem"], why)
            self.assertNotIn("package", found, why)
        self.served = release("0.1.4", {"JARVIS-mac.zip": b"PK"})
        self.assertIn("no package for this computer", updates.check(self.cfg)["problem"])

    def test_github_out_of_reach_or_odd_answers_are_said_not_thrown(self):
        self.served = {}
        self.assertIn("could not be reached", updates.check(self.cfg)["problem"])
        self.served = {f"{updates.API}/repos/{REPO}/releases/latest": b"not json"}
        self.assertIn("could not be read", updates.check(self.cfg)["problem"])
        self.served = {f"{updates.API}/repos/{REPO}/releases/latest": json.dumps({"tag_name": "nightly"}).encode()}
        self.assertIn("no version number", updates.check(self.cfg)["problem"])

    def test_a_page_address_from_elsewhere_is_not_shown(self):
        self.served = release("0.1.4", {"JARVIS-windows.zip": b"PK"})
        url = f"{updates.API}/repos/{REPO}/releases/latest"
        page = json.loads(self.served[url])
        page["html_url"] = "https://evil.example/download"
        self.served[url] = json.dumps(page).encode()
        self.assertEqual(updates.check(self.cfg)["page"], "")

    def test_copies_that_are_updated_another_way_are_left_alone(self):
        self.served = release("0.1.4", {"JARVIS-windows.zip": b"PK"})
        (self.app / ".deployed.json").write_text("{}", "utf-8")
        self.assertIn("deploy tool", updates.check(self.cfg)["managed"])
        self.assertEqual(self.asked, [], "GitHub was not even asked")
        (self.app / ".deployed.json").unlink()
        (self.app / ".git").mkdir()
        self.assertIn("source code", updates.managed())
        (self.app / ".git").rmdir()
        with mock.patch.object(system, "PLATFORM", "linux"):
            self.assertIn("Linux", updates.managed())
        (self.app / ".jarvis-files").unlink()
        self.assertIn("not installed by the JARVIS installer", updates.managed())

    def test_how_often_and_whether_it_looks(self):
        self.assertTrue(updates.due(self.cfg))
        self.served = release("0.1.3", {"JARVIS-windows.zip": b"PK"})
        updates.check(self.cfg)
        self.assertFalse(updates.due(self.cfg), "it looked just now")
        self.assertTrue(updates.due(self.cfg, now=time.time() + 25 * 3600))
        updates.set_mode(self.cfg, "off")
        self.assertFalse(updates.due(self.cfg, now=time.time() + 99 * 3600))
        with self.assertRaises(updates.UpdateError):
            updates.set_mode(self.cfg, "sometimes")
        self.assertEqual(updates.settings(self.cfg)["mode"], "off")


class TestFetchingAndInstalling(UpdateCase):
    def setUp(self):
        super().setUp()
        self.served = release("0.1.4", {"JARVIS-windows.zip": b"PK the new version"})
        updates.check(self.cfg)

    def test_the_package_is_kept_only_when_it_matches_the_signed_list_exactly(self):
        found = updates.download(self.cfg)
        path = Path(found["ready"]["path"])
        self.assertEqual(path.read_bytes(), b"PK the new version")
        self.assertEqual(path.parent, self.cfg.state_dir / "updates" / "0.1.4")
        self.assertTrue(updates.ready(self.cfg))
        status = updates.status(self.cfg)
        self.assertEqual((status["current"], status["latest"], status["ready"], status["signed"]), ("0.1.3", "0.1.4", True, True))
        self.assertNotIn("path", json.dumps(status), "the window is not told where files are")

    def test_a_changed_download_is_thrown_away(self):
        url = next(u for u in self.served if u.endswith("JARVIS-windows.zip"))
        for wrong in (b"PK the new versioN", b"PK the new version plus more", b"PK"):
            self.served[url] = wrong
            with self.assertRaises(updates.UpdateError):
                updates.download(self.cfg)
            self.assertFalse(any((self.cfg.state_dir / "updates" / "0.1.4").glob("JARVIS-windows.zip*")), wrong)
            self.assertIsNone(updates.ready(self.cfg))

    def test_what_may_be_installed(self):
        updates.download(self.cfg)
        self.assertTrue(updates.install_at_start(self.cfg), "automatic: at the next start")
        updates.set_mode(self.cfg, "ask")
        self.assertFalse(updates.install_at_start(self.cfg), "ask: only when its owner presses Install")
        updates.set_mode(self.cfg, "auto")
        (self.cfg.state_dir / "update-failed.json").write_text('["0.1.4"]', "utf-8")
        self.assertIsNone(updates.ready(self.cfg), "a version that failed once is not tried by itself again")
        (self.cfg.state_dir / "update-failed.json").unlink()
        (self.app / "VERSION").write_text("0.1.4", "utf-8")
        self.assertIsNone(updates.ready(self.cfg), "already installed")

    def test_the_helper_is_started_from_a_copy_and_on_its_own(self):
        updates.download(self.cfg)
        started = []
        updates.start_install(self.cfg, start="window", popen=lambda argv, **kw: started.append((argv, kw)))
        argv, options = started[0]
        helper = Path(argv[argv.index("-I") + 1])
        self.assertEqual(helper.parent, self.cfg.state_dir / "updates" / "0.1.4", "a copy outside the app's folder")
        self.assertEqual(helper.read_bytes(), (Path(updates.__file__).with_name("update_helper.py")).read_bytes())
        self.assertEqual(argv[argv.index("--version") + 1], "0.1.4")
        self.assertEqual(argv[argv.index("--sha256") + 1], hashlib.sha256(b"PK the new version").hexdigest())
        self.assertEqual(argv[argv.index("--app-dir") + 1], str(self.app))
        self.assertEqual(argv[argv.index("--start") + 1], "window")
        self.assertTrue(options.get("creationflags") or options.get("start_new_session"))
        self.assertEqual(updates.status(self.cfg)["installing"]["version"], "0.1.4")

    def test_jarvis_installs_a_ready_update_before_it_starts(self):
        updates.download(self.cfg)
        asked = []
        with mock.patch.object(desktop, "ready", lambda: False), mock.patch.object(desktop, "_helper", lambda *a, **k: None), \
                mock.patch.object(desktop.subprocess, "Popen", lambda *a, **k: asked.append(("popen", a))), \
                mock.patch.object(updates, "start_install", lambda cfg, start: asked.append(("install", start))):
            self.assertEqual(desktop.main(background=True), 0)
        self.assertIn(("install", "background"), asked)
        self.assertFalse([a for a in asked if a[0] == "popen" and "gui" in a[1][0]], "the service was not started: the helper does that after installing")

    def test_the_background_loop_checks_and_fetches_by_itself(self):
        (self.cfg.state_dir / "update-status.json").unlink()
        stop = mock.Mock()
        stop.wait = mock.Mock(side_effect=[False, True])
        updates.background(self.cfg, stop, pause=0, first=0)
        self.assertTrue(updates.ready(self.cfg), "checked, and fetched the signed update")


class TestTheWindowsView(GuiTestCase):
    def test_the_window_reads_the_status_and_chooses_how_updates_happen(self):
        status, data = self.req("GET", "/api/updates")
        self.assertEqual(status, 200)
        for key in ("current", "mode", "managed", "available", "ready", "result"):
            self.assertIn(key, data)
        status, data = self.req("POST", "/api/updates", {"action": "mode", "mode": "ask"})
        self.assertEqual((status, data["mode"]), (200, "ask"))
        status, data = self.req("POST", "/api/updates", {"action": "mode", "mode": "whenever"})
        self.assertEqual(status, 400)
        status, data = self.req("POST", "/api/updates", {"action": "explode"})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()


class TestSigningARelease(unittest.TestCase):
    """scripts/sign_release.py: the list it signs is the one JARVIS accepts, and it never signs with a key JARVIS would refuse."""

    def tool(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("sign_release", Path(__file__).resolve().parents[1] / "scripts" / "sign_release.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_a_signed_list_is_accepted_by_jarvis_and_lists_every_package(self):
        tool = self.tool()
        files = {"JARVIS-windows.zip": b"PK win", "JARVIS-mac.zip": b"PK mac"}
        body = tool.manifest_for("0.1.4", files)
        with mock.patch.object(updates, "PUBLIC_KEY", TEST_KEY):
            signature = tool.sign(SEED, body)
            manifest = updates.verified_manifest(body, signature, "0.1.4")
        self.assertEqual(sorted(manifest["files"]), sorted(files))
        self.assertEqual(manifest["files"]["JARVIS-mac.zip"]["sha256"], hashlib.sha256(b"PK mac").hexdigest())

    def test_it_refuses_to_sign_with_a_key_jarvis_does_not_have(self):
        tool = self.tool()
        with mock.patch.object(updates, "PUBLIC_KEY", TEST_KEY), self.assertRaises(SystemExit):
            tool.sign(bytes(32), tool.manifest_for("0.1.4", {"JARVIS-mac.zip": b"PK"}))
