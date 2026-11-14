"""The first run: the vault it sets up, the one line it writes into config/local.toml, and what it refuses."""
import hashlib
import os
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path

os.environ.setdefault("JCC_NO_LOCAL_CONFIG", "1")      # tests never read one PC's own settings (config/local.toml)

from jcc import firstrun  # noqa: E402

PLACES = ("JCC_VAULT", "JCC_STATE_DIR", "JCC_JOBS_ROOT", "JCC_PROJECTS_ROOT", "JCC_NO_CREDMAN", "JCC_NO_SCREEN")


def snapshot(*folders: Path) -> dict:
    """Every file under the folders with a digest of what it holds, to see whether anything changed."""
    seen = {}
    for folder in folders:
        for path in sorted(folder.rglob("*")) if folder.exists() else []:
            if path.is_file():
                seen[path] = hashlib.sha256(path.read_bytes()).hexdigest()
    return seen


class FirstRunTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jcc-firstrun-"))
        self.app = self.tmp / "app"
        (self.app / "config").mkdir(parents=True)
        self.state = self.tmp / "state"
        self._env = {k: os.environ.get(k) for k in PLACES}
        os.environ.update({"JCC_STATE_DIR": str(self.state), "JCC_JOBS_ROOT": str(self.tmp / "jobs"),
                           "JCC_PROJECTS_ROOT": str(self.tmp / "projects"), "JCC_NO_CREDMAN": "1", "JCC_NO_SCREEN": "1"})
        os.environ.pop("JCC_VAULT", None)

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_first(self, vault):
        return firstrun.run(self.app, vault, state_dir=self.state)

    def local(self) -> Path:
        return self.app / "config" / "local.toml"


class NewVault(FirstRunTestCase):
    def test_a_new_vault_is_created_with_the_folders_and_starter_notes_the_app_expects(self):
        vault = self.tmp / "vault"
        said = self.run_first(vault)
        for folder in ("Requests", "Reports", "Research", "Conversations", "Jobs", "System", "Private", "Projects", "Notes"):
            self.assertTrue((vault / folder).is_dir(), folder)
        for note in ("Start here.md", "Inbox.md", "Dashboard.md", "Priorities.md", "Tasks.md", "Private/README.md",
                     "System/JARVIS Guide.md", "System/Setup Guide.md"):
            self.assertTrue((vault / note).is_file(), note)
        self.assertIn("Private", (vault / "Start here.md").read_text("utf-8"))
        self.assertEqual((vault / ".obsidian" / "app.json").read_text("utf-8").strip(), "{}")
        self.assertEqual(tomllib.loads(self.local().read_text("utf-8"))["paths"]["vault"], str(vault))
        self.assertTrue(any("Created your notes vault" in s for s in said))
        self.assertTrue(any(str(vault) in s and "Obsidian" in s for s in said))

    def test_the_app_data_it_writes_goes_to_the_folder_it_was_given(self):
        self.run_first(self.tmp / "vault")
        self.assertTrue((self.state / "settings-schema.json").is_file())

    def test_without_a_vault_given_it_uses_the_one_already_in_local_toml(self):
        chosen = self.tmp / "from settings"
        self.local().write_text(f"[paths]\nvault = '{chosen}'\n", "utf-8")
        self.assertEqual(firstrun.choose_vault(self.app), chosen.absolute())

    def test_without_any_vault_named_it_offers_documents_jarvis_vault(self):
        self.assertEqual(firstrun.choose_vault(self.app), (Path.home() / "Documents" / "JARVIS Vault").absolute())


class ExistingVault(FirstRunTestCase):
    def test_an_existing_vault_keeps_every_note_and_its_obsidian_settings_exactly_as_they_were(self):
        vault = self.tmp / "my notes"
        mine = {"Inbox.md": "# My own inbox\n", "Ideas/Garden.md": "Plant tomatoes.\n", "Start here.md": "My start.\n",
                ".obsidian/app.json": '{"theme": "dark"}', ".obsidian/plugins/dataview/main.js": "// a plugin\n"}
        for rel, text in mine.items():
            (vault / rel).parent.mkdir(parents=True, exist_ok=True)
            (vault / rel).write_text(text, "utf-8")
        said = self.run_first(vault)
        for rel, text in mine.items():
            self.assertEqual((vault / rel).read_text("utf-8"), text, rel)
        self.assertEqual(sorted(p.name for p in (vault / ".obsidian").rglob("*")), ["app.json", "dataview", "main.js", "plugins"])
        self.assertTrue((vault / "Tasks.md").is_file())
        self.assertTrue(any("Nothing in it was removed or overwritten" in s for s in said))

    def test_a_file_where_the_vault_should_be_is_refused(self):
        not_a_folder = self.tmp / "notes.txt"
        not_a_folder.write_text("x", "utf-8")
        with self.assertRaises(firstrun.FirstRunError):
            self.run_first(not_a_folder)


class LocalSettings(FirstRunTestCase):
    def test_other_settings_in_local_toml_are_kept_line_for_line(self):
        before = ("# my settings\n[paths]\nstate_dir = '~/elsewhere'   # keep me\nvault = '~/Old vault'\n"
                  "protected = [\n  '~/.ssh',\n]\n\n[bot]\nurl = \"http://127.0.0.1:9\"\n")
        self.local().write_text(before, "utf-8")
        vault = self.tmp / "vault"
        self.run_first(vault)
        after = self.local().read_text("utf-8")
        self.assertEqual(after, before.replace("vault = '~/Old vault'", f"vault = '{vault}'"))
        data = tomllib.loads(after)
        self.assertEqual(data["bot"]["url"], "http://127.0.0.1:9")
        self.assertEqual(data["paths"]["protected"], ["~/.ssh"])

    def test_a_local_toml_without_paths_gets_a_paths_section_at_the_end(self):
        self.local().write_text("[bot]\nurl = \"\"\n[[mods]]\nname = \"x\"", "utf-8")
        vault = self.tmp / "vault"
        self.run_first(vault)
        data = tomllib.loads(self.local().read_text("utf-8"))
        self.assertEqual(data["paths"]["vault"], str(vault))
        self.assertEqual(data["mods"], [{"name": "x"}])

    def test_a_paths_section_without_a_vault_gets_the_line_under_its_header(self):
        self.local().write_text("[paths]\nstate_dir = '~/s'\n[bot]\nurl = \"\"\n", "utf-8")
        vault = self.tmp / "vault"
        self.run_first(vault)
        self.assertEqual(self.local().read_text("utf-8"), f"[paths]\nvault = '{vault}'\nstate_dir = '~/s'\n[bot]\nurl = \"\"\n")

    def test_windows_line_endings_are_kept(self):
        self.local().write_bytes(b"[paths]\r\nvault = 'x'\r\n[bot]\r\nurl = \"\"\r\n")
        self.run_first(self.tmp / "vault")
        self.assertNotIn(b"\n", self.local().read_bytes().replace(b"\r\n", b""))

    def test_a_broken_local_toml_is_left_alone_and_reported(self):
        self.local().write_text("[paths\nvault = \n", "utf-8")
        with self.assertRaises(firstrun.FirstRunError):
            self.run_first(self.tmp / "vault")
        self.assertEqual(self.local().read_text("utf-8"), "[paths\nvault = \n")
        self.assertFalse((self.tmp / "vault").exists())


class Paths(FirstRunTestCase):
    def test_a_path_with_spaces_is_written_and_read_back_exactly(self):
        vault = self.tmp / "My Documents" / "JARVIS Vault 2"
        self.run_first(vault)
        self.assertEqual(tomllib.loads(self.local().read_text("utf-8"))["paths"]["vault"], str(vault))
        self.assertTrue((vault / "Start here.md").is_file())

    def test_a_path_with_a_single_quote_is_refused_before_anything_is_created(self):
        vault = self.tmp / "it's mine"
        with self.assertRaises(firstrun.FirstRunError):
            self.run_first(vault)
        self.assertFalse(vault.exists())
        self.assertFalse(self.local().exists())

    def test_a_path_with_a_line_break_is_refused_before_anything_is_created(self):
        for name in ("two\nlines", "carriage\rreturn", "bell\x07"):
            with self.subTest(name=repr(name)):
                with self.assertRaises(firstrun.FirstRunError):
                    firstrun.toml_literal(self.tmp / name)
        with self.assertRaises(firstrun.FirstRunError):
            self.run_first(str(self.tmp) + "/evil\n[paths]\nvault = 'C:/'")
        self.assertFalse(self.local().exists())


class Again(FirstRunTestCase):
    def test_running_it_twice_changes_nothing_the_second_time(self):
        vault = self.tmp / "vault"
        self.local().write_text("# mine\n[bot]\nurl = \"\"\n", "utf-8")
        self.run_first(vault)
        first = snapshot(vault, self.app)
        said = self.run_first(vault)
        self.assertEqual(snapshot(vault, self.app), first)
        self.assertTrue(any("none were added" in s for s in said))
        self.assertTrue(any("was not changed" in s for s in said))

    def test_main_prints_what_it_did_and_takes_no_questions_with_yes(self):
        import contextlib
        import io
        vault = self.tmp / "vault"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):      # (JCC_STATE_DIR keeps the app's data in the temporary folder)
            code = firstrun.main(["--vault", str(vault), "--app-dir", str(self.app), "--yes", "--no-open"])
        self.assertEqual(code, 0)
        self.assertIn(str(vault), out.getvalue())
        self.assertTrue((self.state / "settings-schema.json").is_file())

    def test_main_reports_a_refused_path_and_exits_with_an_error(self):
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = firstrun.main(["--vault", str(self.tmp / "it's"), "--app-dir", str(self.app), "--yes", "--no-open"])
        self.assertEqual(code, 2)
        self.assertIn("single quote", err.getvalue())


if __name__ == "__main__":
    unittest.main()
