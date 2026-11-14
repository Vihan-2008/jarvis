"""Nothing waits for nothing: a job that changed nothing never waits for a review, and older ones that do are put right
once at start (jcc/review.py tidy). Delete project leaves the folder unless asked, and only ever to the Recycle Bin."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jcc import review, workspace
from jcc.vault import Vault, parse_frontmatter, render_note


class Cfg:
    def __init__(self, root: Path):
        self.vault, self.state_dir, self.jobs_root = root / "vault", root / "state", root / "jobs"
        for folder in (self.vault / "Jobs", self.state_dir, self.jobs_root):
            folder.mkdir(parents=True)
        self.projects = {}

    def all_protected(self):
        return []


class TestNothingWaitsForNothing(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="jcc-tidy-"))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        self.cfg = Cfg(self.root)

    def job(self, rid, **front):
        Vault(self.cfg.vault).write(f"Jobs/{rid}.md", render_note({"id": rid, "status": "needs_approval", "project_key": "wii", **front}, "# Job"))

    def status(self, rid):
        return parse_frontmatter(Vault(self.cfg.vault).read(f"Jobs/{rid}.md"))[0]["status"]

    def test_only_reviews_with_nothing_in_them_are_put_right(self):
        self.job("20261115-010101-aaaa")                                        # nothing left to keep
        self.job("20261115-010102-bbbb"); (self.cfg.jobs_root / "20261115-010102-bbbb" / "repo").mkdir(parents=True)   # a real change
        self.job("20261115-010103-cccc", blocked_by="deploying")                # held for its words: answered on its card
        self.job("20261115-010104-dddd", asked=True)                            # a question
        self.job("20261115-010105-eeee", status="done")
        self.assertEqual(review.tidy(self.cfg), 1)
        self.assertEqual([self.status(r) for r in ("20261115-010101-aaaa", "20261115-010102-bbbb", "20261115-010103-cccc", "20261115-010104-dddd", "20261115-010105-eeee")],
                         ["failed", "needs_approval", "needs_approval", "needs_approval", "done"])
        self.assertEqual(review.tidy(self.cfg), 0, "once is enough")


class TestMasterAndWorkChats(unittest.TestCase):
    """The chat a request was made in is its Master; each piece of work has a chat of its own under it, and the Master
    hears how each one goes (its line and its checklist)."""
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="jcc-master-"))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        self.cfg = Cfg(self.root)

    def test_a_work_chat_reports_to_its_master(self):
        from jcc.chats import Chats
        chats = Chats(self.cfg)
        master = chats.create("Build a party console")["id"]
        work = chats.create("Package skeleton and launcher", None, parent=master)["id"]
        listed = {c["id"]: c for c in chats.list()}
        self.assertEqual(listed[work]["parent"], master, "the sidebar can put it under its Master")
        chats.update(master, message={"role": "assistant", "receipt": "20261115-050505-abcd", "status": "queued", "job": True, "child": work, "content": "Started"})
        chats.update(work, message={"role": "assistant", "receipt": "20261115-050505-abcd", "status": "done", "content": "Done. The changes are in WII.\n\nChecks passed: npm test."})
        line = [m for m in chats.get(master)["messages"] if m.get("receipt") == "20261115-050505-abcd"]
        self.assertEqual(len(line), 1, "one line for it in the Master, kept up to date")
        self.assertEqual((line[0]["status"], line[0]["content"], line[0]["child"]), ("done", "Done. The changes are in WII.", work))
        with self.assertRaises(ValueError):
            chats.create("x", None, parent="../../etc")


class TestDeleteProject(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="jcc-del-"))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        self.cfg = Cfg(self.root)
        self.folder = self.root / "work" / "wii"
        (self.folder / "src").mkdir(parents=True)
        (self.folder / "src" / "game.js").write_text("x", "utf-8")
        (self.cfg.state_dir / "projects.json").write_text(json.dumps({"wii": {"name": "WII", "path": str(self.folder)}}), "utf-8")
        self.cfg.projects = {"wii": object(), "trading": object()}

    def test_it_leaves_jarvis_with_its_chats_and_the_folder_stays(self):
        from jcc.chats import Chats
        chats = Chats(self.cfg)
        mine, other = chats.create("Build the console", "wii")["id"], chats.create("Something else", None)["id"]
        done = workspace.remove(self.cfg, "wii")
        self.assertEqual((done["removed"], done["trashed"], done["chats"]), ("wii", False, 1))
        self.assertEqual([c["id"] for c in chats.list()], [other], "its chat went with it, the other stays")
        self.assertIn(mine, chats.deleted_ids(), "to Deleted chats, where it can be brought back")
        self.assertTrue((self.folder / "src" / "game.js").exists(), "the folder is never touched unless asked")
        self.assertNotIn("wii", json.loads((self.cfg.state_dir / "projects.json").read_text("utf-8")))
        self.assertNotIn("wii", self.cfg.projects)

    def test_asked_for_its_folder_goes_to_the_recycle_bin_and_only_there(self):
        moved = []
        with mock.patch.object(workspace, "to_trash", lambda folder: moved.append(folder) or True):
            done = workspace.remove(self.cfg, "wii", trash=True)
        self.assertEqual((done["trashed"], moved), (True, [self.folder]))

    def test_a_folder_that_holds_the_vault_or_jarvis_is_never_binned(self):
        self.assertFalse(workspace._may_trash(self.cfg, self.root), "it holds the vault and JARVIS's data")
        self.assertFalse(workspace._may_trash(self.cfg, Path.home()))
        self.assertFalse(workspace._may_trash(self.cfg, Path(self.root.anchor)))
        self.assertTrue(workspace._may_trash(self.cfg, self.folder))

    def test_what_cannot_be_deleted_here(self):
        with self.assertRaises(ValueError) as said:
            workspace.remove(self.cfg, "trading")
        self.assertIn("config/local.toml", str(said.exception))
        with self.assertRaises(ValueError):
            workspace.remove(self.cfg, "nope")
        Vault(self.cfg.vault).write("Jobs/20261115-020202-ffff.md", render_note({"status": "running", "project_key": "wii"}, "# Job"))
        with self.assertRaises(ValueError) as said:
            workspace.remove(self.cfg, "wii")
        self.assertIn("Stop it first", str(said.exception))


if __name__ == "__main__":
    unittest.main()
