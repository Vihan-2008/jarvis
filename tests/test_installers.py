"""The installer packages: what goes in, what stays out, and that the Mac scripts are executable inside the zip.

These build the zips into a temporary folder and only read them, so they run on every system. The full Windows
install, which runs the installer for real, is installer/windows/test_install.py.
"""
import importlib.util
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def load(relative: str, name: str):
    """An installer build script as a module (they live outside the jcc package, beside their installers)."""
    spec = importlib.util.spec_from_file_location(name, REPO / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git_works() -> bool:
    try:
        return subprocess.run(["git", "-C", str(REPO), "ls-files", "VERSION"], capture_output=True).returncode == 0
    except OSError:
        return False


LEFT_OUT = ("tests/", "installer/", "website/", ".github/")


@unittest.skipUnless(git_works(), "the packages are built from the files git lists")
class Packages(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jarvis-packages-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_windows_zip_has_the_app_and_its_installer_and_nothing_private_or_internal(self):
        windows = load("installer/windows/build.py", "jarvis_windows_build")
        names = zipfile.ZipFile(windows.build_zip(self.tmp)).namelist()
        for wanted in ("install.ps1", "uninstall.ps1", "jcc/__init__.py", "jcc/firstrun.py", "config/default.toml", "VERSION"):
            self.assertIn(wanted, names)
        for name in names:
            self.assertFalse(name.startswith(LEFT_OUT), name)
        for unwanted in ("LEDGER.md", "scripts/deploy.py", "config/local.toml", ".python"):
            self.assertNotIn(unwanted, names)

    def test_the_mac_zip_has_its_scripts_executable_with_unix_line_endings(self):
        mac = load("installer/mac/build.py", "jarvis_mac_build")
        target = mac.build_zip(self.tmp)
        with zipfile.ZipFile(target) as z:
            infos = {i.filename: i for i in z.infolist()}
            for name in (".jarvis-app/install.sh", ".jarvis-app/uninstall.sh", "Install JARVIS.command"):
                info = infos[f"JARVIS Installer/{name}"]
                self.assertEqual(info.create_system, 3)
                self.assertTrue((info.external_attr >> 16) & stat.S_IXUSR, name)
                self.assertNotIn(b"\r", z.read(info))
            plain = infos["JARVIS Installer/.jarvis-app/jcc/__init__.py"]
            self.assertFalse((plain.external_attr >> 16) & stat.S_IXUSR)
            self.assertFalse(any(n.startswith("JARVIS Installer/.jarvis-app/" + p) for n in infos for p in LEFT_OUT))
            shown = sorted({n.split("/")[1] for n in infos if n.count("/") >= 1})
            self.assertEqual(shown, [".jarvis-app", "Install JARVIS.command", "Read me first.txt"],
                             "opened, the package shows the installer and a note; the app's files are tucked away")
            note = z.read("JARVIS Installer/Read me first.txt").decode("utf-8")
            self.assertIn("Open Anyway", note, "it says what to do when macOS blocks the installer")

    def test_the_version_is_one_plain_version(self):
        payload = load("installer/payload.py", "jarvis_payload")
        self.assertRegex(payload.version(), r"^\d+\.\d+\.\d+$")

    def test_a_mac_stage_folder_keeps_the_executable_bits(self):
        if sys.platform == "win32":
            self.skipTest("Windows does not keep Unix permissions on files")
        mac = load("installer/mac/build.py", "jarvis_mac_build_stage")
        folder = mac.stage(self.tmp / "stage")
        self.assertTrue((folder / ".jarvis-app" / "install.sh").stat().st_mode & stat.S_IXUSR)
        self.assertTrue((folder / "Install JARVIS.command").stat().st_mode & stat.S_IXUSR)


if __name__ == "__main__":
    unittest.main()
