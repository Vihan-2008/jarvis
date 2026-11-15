"""Settings > Advanced > Uninstall JARVIS: it runs the installer's own uninstaller, detached, with the owner's choices,
and never touches a copy of JARVIS that no installer made."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from jcc import uninstall


def installed(folder: Path, script: str) -> Path:
    (folder / "jcc").mkdir(parents=True)
    (folder / "jcc" / "__init__.py").write_text("", "utf-8")
    (folder / ".jarvis-files").write_text("jcc/__init__.py\n", "utf-8")
    (folder / script).write_text("# the uninstaller\n", "utf-8")
    return folder


class Uninstall(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg = SimpleNamespace(state_dir=self.tmp / "state", vault=self.tmp / "Vault")

    def test_windows_runs_the_installers_uninstaller_hidden_with_the_choices(self):
        with mock.patch.object(uninstall, "WINDOWS", True), mock.patch.object(uninstall, "MAC", False):
            app = installed(self.tmp / "app", "uninstall.ps1")
            plan = uninstall.plan(self.cfg, app)
            self.assertTrue(plan["can"]); self.assertEqual(plan["bin"], "Recycle Bin"); self.assertEqual(plan["vault"], str(self.cfg.vault))
            started = []
            uninstall.start(self.cfg, delete_data=True, delete_notes=False, folder=app, popen=lambda argv, **kw: started.append((argv, kw)))
            argv, kw = started[0]
            self.assertEqual(argv[:2], ["powershell", "-NoProfile"])
            self.assertIn(str(app / "uninstall.ps1"), argv)
            self.assertIn("-Quiet", argv); self.assertIn("-DeleteData", argv); self.assertNotIn("-DeleteNotes", argv)
            self.assertTrue(kw["creationflags"] & 0x00000008)              # detached: it outlives the JARVIS it stops
            self.assertEqual(kw["env"]["JCC_STATE_DIR"], str(self.cfg.state_dir))
            self.assertNotEqual(Path(kw["cwd"]), app)                        # (not inside the folder it removes)

    def test_mac_runs_uninstall_sh_in_a_session_of_its_own(self):
        with mock.patch.object(uninstall, "WINDOWS", False), mock.patch.object(uninstall, "MAC", True):
            app = installed(self.tmp / "app", "uninstall.sh")
            self.assertEqual(uninstall.plan(self.cfg, app)["bin"], "Trash")
            started = []
            uninstall.start(self.cfg, delete_data=False, delete_notes=True, folder=app, popen=lambda argv, **kw: started.append((argv, kw)))
            argv, kw = started[0]
            self.assertEqual(argv, ["/bin/bash", str(app / "uninstall.sh"), "--quiet", "--delete-notes"])
            self.assertTrue(kw["start_new_session"]); self.assertEqual(kw["cwd"], "/")

    def test_a_copy_no_installer_made_is_never_removed(self):
        with mock.patch.object(uninstall, "WINDOWS", True), mock.patch.object(uninstall, "MAC", False):
            app = self.tmp / "checkout"
            (app / "jcc").mkdir(parents=True); (app / "jcc" / "__init__.py").write_text("", "utf-8")
            (app / "uninstall.ps1").write_text("", "utf-8")                 # (no .jarvis-files: not the installer's)
            self.assertFalse(uninstall.plan(self.cfg, app)["can"])
            with self.assertRaises(ValueError):
                uninstall.start(self.cfg, folder=app, popen=lambda *a, **k: self.fail("started"))

    def test_this_checkout_is_not_an_installed_copy(self):
        self.assertFalse(uninstall.plan(self.cfg)["can"])


class GettingStarted(unittest.TestCase):
    def test_the_guide_is_loaded_and_setup_is_a_command(self):
        from jcc import gui, mods
        static = Path(gui.__file__).with_name("static")
        self.assertIn("/nova-start.js", gui.SCRIPTS)
        self.assertIn('src="/nova-start.js"', (static / "desktop.html").read_text("utf-8"))
        self.assertIn("setup", [name for name, _ in mods.BUILTIN])
        guide = (static / "nova-start.js").read_text("utf-8")
        for words in ("open calculator", "Hey JARVIS", "Sleep JARVIS", "Check again", "Test the microphone", "/setup"):
            self.assertIn(words, guide)


if __name__ == "__main__":
    unittest.main()
