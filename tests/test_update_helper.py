"""The install helper (jcc/update_helper.py), with the installer, JARVIS's processes and its answering stood in for:
an update that works, one whose new version does not start (the old one must come back), one whose installer fails,
a package that was changed after it was checked, and a package that tries to write outside its own folder."""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from jcc import update_helper as helper


class HelperCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jcc-update-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.app, self.state = self.tmp / "app", self.tmp / "state"
        for folder in (self.app / "jcc", self.app / "config", self.state):
            folder.mkdir(parents=True)
        self.write(self.app, {"VERSION": "0.1.3\n", "jcc/__init__.py": "OLD = True\n", "jcc/gone.py": "x = 1\n",
                              "config/default.toml": "old = 1\n"})
        (self.app / ".jarvis-files").write_text("VERSION\njcc/__init__.py\njcc/gone.py\nconfig/default.toml\n", "utf-8")
        (self.app / "config" / "local.toml").write_text("[paths]\nvault = 'mine'\n", "utf-8")       # the owner's own
        (self.app / "my notes.txt").write_text("the owner's own file", "utf-8")
        (self.state / "update-status.json").write_text(json.dumps({"ready": {"version": "0.1.4"}, "available": True}), "utf-8")
        self.events, self.answers = [], []

    @staticmethod
    def write(root: Path, files: dict) -> None:
        for name, text in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text, "utf-8")

    def package(self, version="0.1.4", extra=None, broken_paths=False) -> tuple[Path, str]:
        """A release package: the app's new files, and an installer beside them."""
        target = self.tmp / f"package-{version}.zip"
        top = "JARVIS Installer/.jarvis-app/" if os.name != "nt" else ""
        files = {"VERSION": version + "\n", "jcc/__init__.py": "NEW = True\n", "jcc/added.py": "y = 2\n", "config/default.toml": "new = 1\n",
                 "install.ps1" if os.name == "nt" else "install.sh": "# the installer\n", **(extra or {})}
        with zipfile.ZipFile(target, "w") as z:
            for name, text in files.items():
                z.writestr(top + name, text)
            if broken_paths:
                z.writestr("../outside.txt", "escaped")
        return target, hashlib.sha256(target.read_bytes()).hexdigest()

    def run_fake(self, installer_ok=True, installs_version=None):
        """Stands in for every program the helper runs: listing JARVIS's processes, stopping them, and the installer,
        which (like the real one) copies the package's files over the app and writes the list of them."""
        def run(argv, **kw):
            self.events.append(argv[0] if argv[0] != "powershell" or "-File" not in argv else "installer")
            if "-File" in argv or (argv and argv[0] == "/bin/bash"):
                self.events[-1] = "installer"
                installer = Path(argv[argv.index("-File") + 1] if "-File" in argv else argv[1])
                if not installer_ok:
                    return subprocess.CompletedProcess(argv, 1, "it went wrong\n", "")
                listed = []
                for path in installer.parent.rglob("*"):
                    if path.is_file() and path.name not in ("install.ps1", "install.sh"):
                        name = path.relative_to(installer.parent).as_posix()
                        (self.app / name).parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(path, self.app / name)
                        listed.append(name)
                if installs_version:
                    (self.app / "VERSION").write_text(installs_version, "utf-8")
                (self.app / ".jarvis-files").write_text("\n".join(sorted(listed)) + "\n", "utf-8")
                return subprocess.CompletedProcess(argv, 0, "Installed.\n", "")
            return subprocess.CompletedProcess(argv, 0, "", "")         # (no JARVIS process is running here)
        return run

    def popen(self, argv, **kw):
        self.events.append(("start", tuple(argv)))

    def alive(self):
        return self.answers.pop(0) if self.answers else False

    def update(self, package, sha, version="0.1.4", start="background", **fake):
        return helper.run_update(package, sha, version, self.app, self.state, start, run=self.run_fake(**fake), popen=self.popen,
                                 alive=self.alive, pause=lambda s: None, wait_seconds=0.05)


class TestAnUpdate(HelperCase):
    def test_it_installs_keeps_the_owners_files_and_starts_jarvis_again(self):
        package, sha = self.package()
        self.answers = [False, True]                    # stopped; then the new version answers
        result = self.update(package, sha)
        self.assertTrue(result["ok"], result)
        self.assertEqual((self.app / "VERSION").read_text("utf-8").strip(), "0.1.4")
        self.assertEqual((self.app / "jcc" / "added.py").read_text("utf-8"), "y = 2\n")
        self.assertIn("vault = 'mine'", (self.app / "config" / "local.toml").read_text("utf-8"), "the owner's settings are kept")
        self.assertEqual((self.app / "my notes.txt").read_text("utf-8"), "the owner's own file")
        started = [e for e in self.events if isinstance(e, tuple)]
        self.assertEqual(len(started), 1)
        self.assertIn("--background", started[0][1])
        self.assertEqual(self.events.index("installer") > 0, True, "JARVIS was stopped before the installer ran")
        written = json.loads((self.state / "update-result.json").read_text("utf-8"))
        self.assertEqual((written["ok"], written["from"], written["version"]), (True, "0.1.3", "0.1.4"))
        status = json.loads((self.state / "update-status.json").read_text("utf-8"))
        self.assertNotIn("ready", status, "the update is no longer waiting")
        self.assertEqual(len(list((self.state / "update-backups").glob("*.zip"))), 1, "a copy of the old version was kept")
        self.assertIn("installed and answering", (self.state / "update.log").read_text("utf-8"))

    def test_a_new_version_that_does_not_start_is_replaced_by_the_old_one(self):
        package, sha = self.package()
        self.answers = [False]                          # stopped, and then nothing ever answers
        result = self.update(package, sha)
        self.assertEqual((result["ok"], result["rolled_back"]), (False, True))
        self.assertIn("did not answer", result["problem"])
        self.assertEqual((self.app / "VERSION").read_text("utf-8").strip(), "0.1.3", "the old version is back")
        self.assertEqual((self.app / "jcc" / "__init__.py").read_text("utf-8"), "OLD = True\n")
        self.assertTrue((self.app / "jcc" / "gone.py").exists(), "a file the new version dropped is back too")
        self.assertFalse((self.app / "jcc" / "added.py").exists(), "and a file only the new version had is gone")
        self.assertEqual((self.app / "my notes.txt").read_text("utf-8"), "the owner's own file", "the owner's own file is never touched")
        self.assertEqual(len([e for e in self.events if isinstance(e, tuple)]), 2, "started once as new, once as old")
        self.assertEqual(json.loads((self.state / "update-failed.json").read_text("utf-8")), ["0.1.4"], "not tried by itself again")

    def test_an_installer_that_fails_leaves_the_old_version(self):
        package, sha = self.package()
        result = self.update(package, sha, installer_ok=False)
        self.assertEqual((result["ok"], result["rolled_back"]), (False, True))
        self.assertIn("installer stopped", result["problem"])
        self.assertEqual((self.app / "VERSION").read_text("utf-8").strip(), "0.1.3")

    def test_the_wrong_version_after_installing_counts_as_a_failure(self):
        package, sha = self.package()
        result = self.update(package, sha, installs_version="0.1.2")
        self.assertFalse(result["ok"])
        self.assertIn("not 0.1.4", result["problem"])
        self.assertEqual((self.app / "VERSION").read_text("utf-8").strip(), "0.1.3")

    def test_a_package_changed_after_it_was_checked_is_not_installed_and_nothing_is_stopped(self):
        package, sha = self.package()
        with package.open("ab") as handle:
            handle.write(b"tampered")
        result = self.update(package, sha)
        self.assertFalse(result["ok"])
        self.assertIn("no longer matches", result["problem"])
        self.assertNotIn("installer", self.events)
        self.assertFalse((self.state / "update-backups").exists(), "nothing was touched")
        self.assertEqual((self.app / "VERSION").read_text("utf-8").strip(), "0.1.3")

    def test_a_package_that_would_write_outside_its_folder_is_refused(self):
        package, sha = self.package(broken_paths=True)
        result = self.update(package, sha)
        self.assertFalse(result["ok"])
        self.assertIn("outside its folder", result["problem"])
        self.assertFalse((self.tmp / "outside.txt").exists())
        self.assertEqual((self.app / "VERSION").read_text("utf-8").strip(), "0.1.3")

    def test_only_the_last_three_copies_are_kept(self):
        for n in range(5):
            helper.backup(self.app, self.state, f"0.1.{n}")
            for made in (self.state / "update-backups").glob("*.zip"):
                os.utime(made)
        self.assertLessEqual(len(list((self.state / "update-backups").glob("*.zip"))), 3)

    def test_the_installer_is_run_quietly_as_an_upgrade_keeping_earlier_choices(self):
        installer = self.tmp / "install.ps1"
        argv = helper.installer_argv(installer, self.app)
        self.assertIn(str(self.app), argv)
        if os.name == "nt":
            self.assertEqual([a for a in argv if a.startswith("-") and a not in ("-NoProfile", "-ExecutionPolicy", "-File", "-InstallDir")],
                             ["-Quiet", "-NoObsidian", "-NoShortcuts"])
            (self.app / ".shortcuts").write_text("C:\\x\\JARVIS (background).lnk\n", "utf-8")
            self.assertIn("-Autostart", helper.installer_argv(installer, self.app), "it started at sign-in before: it still does")
        else:
            self.assertIn("--quiet", argv)
            self.assertTrue("--login" in argv or "--no-login" in argv)


if __name__ == "__main__":
    unittest.main()
