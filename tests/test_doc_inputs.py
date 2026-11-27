"""Attached documents (jcc/doc_inputs.py, jcc/pdf_bridge.ps1): a PDF's pages become pictures a job can look at, with the
text read off them; what the bridge writes is checked, not trusted; problems each have their own plain message and leave
nothing behind; jobs get the files (Claude reads them, Codex is handed the pictures). A stand-in plays the bridge, so
these run on any PC; one test runs the real bridge, on Windows only."""
import base64
import json
import os
import subprocess
import sys
import time
import zlib
from pathlib import Path
from unittest import mock

from jcc import config, doc_inputs, documents, sessions
from jcc.jobrunner import run_job
from tests.helpers import EngineTestCase
from tests.test_gui import GuiTestCase
from tests.test_projects import make_repo, overrides

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a7TQAAAAASUVORK5CYII=")
PDF = b"%PDF-1.4\n% stand-in bytes: the stand-in bridge never reads them\n" + b"x" * 200


def encoded(data: bytes) -> str:
    return base64.b64encode(data).decode()


def bridge(count=2, shown=None, texts=None, problem=None, extra=None, late=False, calls=None):
    """A stand-in for jcc/pdf_bridge.ps1: writes tiny pages into the folder it is given and answers as the bridge does."""
    def run(argv, payload, timeout):
        request = json.loads(base64.b64decode(payload))
        if calls is not None:
            calls.append((argv, request, timeout))
        if late:
            raise subprocess.TimeoutExpired(argv, timeout)
        if problem:
            return encoded(json.dumps({"ok": False, "problem": problem}).encode())
        folder = Path(request["folder"])
        assert (folder / "source.pdf").exists()
        pages = []
        for n in range(1, (shown or count) + 1):
            name = f"page-{n:03d}.png"
            (folder / name).write_bytes(PNG)
            pages.append({"n": n, "file": name, "text": (texts or {}).get(n, f"Page {n} words")})
        if extra:
            extra(folder, pages)
        return encoded(json.dumps({"ok": True, "count": count, "ocr": True, "read": True, "pages": pages}).encode())
    return run


class DocumentTests(EngineTestCase):
    def store(self, run, name="plan.pdf", data=PDF):
        cfg = config.load()
        with mock.patch.object(doc_inputs, "RENDER", run):
            return cfg, documents.extract(name, encoded(data), cfg)

    def leftovers(self, cfg):
        base = cfg.state_dir / doc_inputs.FOLDER
        return sorted(p.name for p in base.iterdir()) if base.exists() else []

    def test_a_pdf_becomes_page_pictures_text_and_the_file_itself(self):
        calls = []
        cfg, result = self.store(bridge(texts={1: "Quarterly plan", 2: "Collect then review"}, calls=calls))
        self.assertEqual(result["label"], "2 pages")
        self.assertEqual(result["pages"], 2)
        self.assertEqual(result["notice"], "")
        self.assertIn("Quarterly plan", result["text"])
        self.assertIn("## Page 2", result["text"])
        self.assertIn("read off those pictures by Windows", result["text"])
        folder = cfg.state_dir / "doc-inputs" / result["doc_id"]
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         ["manifest.json", "original.pdf", "page-001.png", "page-002.png", "text.md"])
        self.assertEqual((folder / "original.pdf").read_bytes(), PDF)
        # The request went in on standard input; nothing a person named is on the command line.
        argv, request, timeout = calls[0]
        self.assertNotIn("plan.pdf", " ".join(argv))
        self.assertEqual(request["pages"], 40)
        self.assertLessEqual(timeout, 60)
        self.assertFalse((cfg.vault / "doc-inputs").exists())
        # The same file again is not read twice.
        with mock.patch.object(doc_inputs, "RENDER", lambda *a: self.fail("read twice")):
            again = documents.extract("copy.pdf", encoded(PDF), cfg)
        self.assertEqual(again["doc_id"], result["doc_id"])
        self.assertEqual(again["name"], "copy.pdf")

    def test_a_long_pdf_says_only_the_first_forty_pages_are_attached(self):
        cfg, result = self.store(bridge(count=212, shown=40))
        self.assertEqual(result["label"], "first 40 of 212 pages")
        self.assertEqual(result["notice"], "plan.pdf: the first 40 of 212 pages are attached.")
        folder = cfg.state_dir / "doc-inputs" / result["doc_id"]
        self.assertFalse((folder / "original.pdf").exists())        # (too long to read whole: only the pictures and the text)
        self.assertFalse((folder / "source.pdf").exists())

    def test_a_scan_with_no_words_is_attached_as_pictures(self):
        cfg, result = self.store(bridge(texts={1: "", 2: "  "}))
        self.assertEqual(result["notice"], "plan.pdf: attached as pictures. No text could be read out of it.")
        self.assertIn("look at the pictures", result["text"])

    def test_each_problem_has_its_own_message_and_leaves_nothing_behind(self):
        cases = {"locked": "plan.pdf is locked with a password. Save a copy without the password and attach that.",
                 "damaged": "plan.pdf could not be opened. The file may be damaged.",
                 "empty": "plan.pdf could not be opened. The file may be damaged.",
                 "unknown": "plan.pdf could not be opened. The file may be damaged."}
        for problem, message in cases.items():
            with self.subTest(problem):
                with self.assertRaises(ValueError) as caught:
                    cfg, _ = self.store(bridge(problem=problem))
                self.assertEqual(str(caught.exception), message)
                self.assertEqual(self.leftovers(config.load()), [])
        with self.assertRaises(ValueError) as caught:
            self.store(bridge(late=True))
        self.assertEqual(str(caught.exception), "plan.pdf took too long to read. Try attaching a smaller part of it.")
        self.assertEqual(self.leftovers(config.load()), [])

    def test_without_windows_drawing_a_small_pdf_is_kept_whole_for_claude(self):
        cfg, result = self.store(bridge(problem="no-renderer"))
        self.assertEqual(result["notice"], "plan.pdf: this PC cannot turn its pages into pictures, so only Claude can read it.")
        folder = cfg.state_dir / "doc-inputs" / result["doc_id"]
        self.assertTrue((folder / "original.pdf").exists())
        big = PDF + b"y" * (doc_inputs.WHOLE_BYTES + 10)
        with self.assertRaises(ValueError) as caught:
            self.store(bridge(problem="no-renderer"), name="big.pdf", data=big)
        self.assertEqual(str(caught.exception), "This PC cannot turn PDF pages into pictures, so big.pdf was not attached.")

    def test_what_the_bridge_writes_is_checked_not_trusted(self):
        def not_png(folder, pages):
            (folder / "page-002.png").write_bytes(b"not a picture")

        def wrong_name(folder, pages):
            pages[1]["file"] = "..\\..\\credentials.json"

        def too_big(folder, pages):
            (folder / "page-001.png").write_bytes(PNG[:-12] + b"\0" * (doc_inputs.PAGE_BYTES + 1) + PNG[-12:])

        for name, extra in (("not a png", not_png), ("a path outside", wrong_name), ("too large", too_big)):
            with self.subTest(name):
                with self.assertRaises(ValueError):
                    self.store(bridge(extra=extra))
                self.assertEqual(self.leftovers(config.load()), [])
        with self.assertRaises(ValueError):
            self.store(bridge(count=50, shown=41))
        # Anything else written in the folder is not kept.
        def stray(folder, pages):
            (folder / "notes.exe").write_bytes(b"MZ")
        cfg, result = self.store(bridge(extra=stray), data=PDF + b"other")
        self.assertFalse((cfg.state_dir / "doc-inputs" / result["doc_id"] / "notes.exe").exists())

    def test_sizes_formats_and_non_pdfs_are_refused_before_reading(self):
        cfg = config.load()
        with mock.patch.object(doc_inputs, "RENDER", lambda *a: self.fail("bridge called")):
            with self.assertRaises(ValueError) as caught:
                documents.extract("huge.pdf", encoded(PDF + b"z" * 21_000_000), cfg)
            self.assertEqual(str(caught.exception), "huge.pdf is 21 MB. The most JARVIS can take is 20 MB.")
            with self.assertRaises(ValueError) as caught:
                documents.extract("fake.pdf", encoded(b"MZ this is not a PDF"), cfg)
            self.assertEqual(str(caught.exception), "fake.pdf could not be opened. The file may be damaged.")
            for name, kind, newer in (("report.doc", "Word", ".docx"), ("deck.ppt", "PowerPoint", ".pptx"), ("sheet.xls", "Excel", ".xlsx")):
                with self.assertRaises(ValueError) as caught:
                    documents.extract(name, encoded(b"old"), cfg)
                self.assertEqual(str(caught.exception), f"{name} is an older {kind} format. Save it as {newer} or PDF and attach that.")
            with self.assertRaises(ValueError) as caught:
                documents.extract("notes.txt", encoded(b"a" * 1_000_001), cfg)
            self.assertEqual(str(caught.exception), "Attachment limit is 1 MB.")
        with self.assertRaises(ValueError):
            documents.extract("plan.pdf", encoded(PDF))          # (a document needs the app's own folder to be kept in)

    def test_prepare_copies_checked_files_and_refuses_changed_ones(self):
        cfg, result = self.store(bridge())
        work = self.tmp / "job"
        work.mkdir()
        prepared = doc_inputs.prepare(cfg, [result["doc_id"]], work)
        self.assertEqual(len(prepared), 1)
        doc = prepared[0]
        self.assertEqual([p.name for p in doc["pages"]], ["page-001.png", "page-002.png"])
        self.assertTrue(doc["text"].exists())
        self.assertTrue(doc["original"].exists())
        self.assertTrue(doc["folder"].is_relative_to(work))
        stored = cfg.state_dir / "doc-inputs" / result["doc_id"] / "page-002.png"
        stored.write_bytes(PNG + b"changed")
        with self.assertRaises(ValueError) as caught:
            doc_inputs.prepare(cfg, [result["doc_id"]], self.tmp / "job2")
        self.assertIn("was changed", str(caught.exception))

    def test_validate_limits_and_identities(self):
        cfg = config.load()
        with self.assertRaises(ValueError) as caught:
            doc_inputs.validate(cfg, ["a" * 64] * 4)
        self.assertEqual(str(caught.exception), "You can attach three documents to one message.")
        for bad in (["../../credentials.json"], ["A" * 64], [7]):
            with self.assertRaises(ValueError):
                doc_inputs.validate(cfg, bad)
        with self.assertRaises(ValueError) as caught:
            doc_inputs.validate(cfg, ["b" * 64])
        self.assertIn("no longer on this PC", str(caught.exception))
        self.assertEqual(doc_inputs.validate(cfg, []), [])

    def test_codex_is_handed_the_pages_named_in_the_task_first(self):
        folder = self.tmp / "d"
        doc = {"pages": [folder / f"page-{n:03d}.png" for n in range(1, 13)], "pictures": []}
        chosen = doc_inputs.codex_pictures([doc], "What does the diagram on page 11 show? Compare with p. 3")
        self.assertEqual([p.name for p in chosen[:2]], ["page-011.png", "page-003.png"])
        self.assertEqual(len(chosen), 8)
        self.assertEqual(len(set(chosen)), 8)
        self.assertEqual(doc_inputs.codex_pictures([doc], "page 99"), doc["pages"][:8])

    def test_claude_reads_the_folder_and_codex_gets_the_pictures(self):
        for provider in ("codex", "claude"):
            cfg = config.load(overrides(make_repo(self.tmp / provider), levels=(provider,)))
            with mock.patch.object(doc_inputs, "RENDER", bridge()):
                result = documents.extract("plan.pdf", encoded(PDF), cfg)
            rid = "20261127-040000-" + ("abcd" if provider == "codex" else "abce")
            work = cfg.jobs_root / rid
            work.mkdir(parents=True)
            calls = []

            def runner(argv, cwd, env, timeout):
                calls.append(argv)
                (cwd / "RESULT.md").write_text("Document answer")
                return 0, "done"
            spec = {"id": rid, "kind": "chat", "task": "What is on page 2 of the plan?", "project": None, "vault": str(cfg.vault),
                    "doc_ids": [result["doc_id"]]}
            outcome = run_job(cfg, spec, work, runner)
            self.assertEqual(outcome.status, "done", outcome.log)
            folder = work / "doc-inputs" / result["doc_id"]
            self.assertTrue((folder / "page-002.png").exists())
            joined = " ".join(calls[0])
            self.assertIn(str(folder), joined)
            self.assertIn("untrusted reference", joined)
            self.assertNotIn(encoded(PDF), joined)
            if provider == "codex":
                images = [calls[0][i + 1] for i, a in enumerate(calls[0]) if a == "--image"]
                self.assertEqual(Path(images[0]).name, "page-002.png")
                self.assertIn("--", calls[0])
            else:
                self.assertIn("Read(", joined)
                self.assertIn("doc-inputs", joined)
                self.assertIn("original.pdf", joined)

    def test_a_document_changes_the_reused_session_identity(self):
        plain = {"context": "Same draft"}
        self.assertEqual(sessions.reference_hash(plain), sessions.reference_hash({**plain, "doc_ids": []}))
        self.assertNotEqual(sessions.reference_hash({**plain, "doc_ids": ["a" * 64]}), sessions.reference_hash({**plain, "doc_ids": ["b" * 64]}))

    def test_old_and_half_made_folders_are_removed(self):
        cfg, result = self.store(bridge())
        base = cfg.state_dir / "doc-inputs"
        part = base / ("c" * 64 + ".part-1234abcd")
        part.mkdir()
        now = time.time()
        self.assertEqual(doc_inputs.prune(cfg, now), 0)                 # (in use, and made a moment ago)
        self.assertEqual(doc_inputs.prune(cfg, now + 2 * 3600), 1)      # the half-made one, after an hour
        self.assertTrue((base / result["doc_id"]).exists())
        self.assertEqual(doc_inputs.prune(cfg, now + 31 * 86400), 1)    # not used for a month
        self.assertEqual(self.leftovers(cfg), [])
        cfg, first = self.store(bridge(), data=PDF + b"1")
        cfg, second = self.store(bridge(), data=PDF + b"2")
        os.utime(base / first["doc_id"] / "manifest.json", (now - 100, now - 100))
        with mock.patch.object(doc_inputs, "KEEP_BYTES", 1):
            doc_inputs.prune(cfg, now)
        self.assertEqual(self.leftovers(cfg), [])

    def test_the_real_bridge_draws_and_reads_a_pdf(self):
        if sys.platform != "win32":
            self.skipTest("Windows draws the pages")
        cfg = config.load()
        result = documents.extract("plan.pdf", encoded(_small_pdf()), cfg)
        if result.get("notice", "").endswith("only Claude can read it."):
            self.skipTest("this Windows cannot draw PDFs")
        self.assertEqual(result["pages"], 2)
        folder = cfg.state_dir / "doc-inputs" / result["doc_id"]
        self.assertTrue((folder / "page-001.png").stat().st_size > 1000)
        self.assertTrue((folder / "page-002.png").exists())


class DocumentApiTests(GuiTestCase):
    def test_attach_send_and_follow_up_keep_the_document(self):
        with mock.patch.object(doc_inputs, "RENDER", bridge()):
            status, doc = self.req("POST", "/api/attachments/extract", {"name": "plan.pdf", "base64": encoded(PDF)})
        self.assertEqual(status, 200, doc)
        self.assertEqual(doc["label"], "2 pages")
        upload = {"name": doc["name"], "doc_id": doc["doc_id"], "text": doc["text"], "label": doc["label"]}
        _, chat = self.req("POST", "/api/chats", {"title": "Plan"})
        status, first = self.req("POST", "/api/chat/send", {"id": chat["id"], "text": "Summarise the plan", "mode": "chat", "uploads": [upload]})
        self.assertEqual(status, 200, first)
        latest = next(m for m in reversed(first["messages"]) if m["role"] == "user")
        self.assertEqual(latest["doc_ids"], [doc["doc_id"]])
        status, second = self.req("POST", "/api/chat/send", {"id": chat["id"], "text": "And the diagram on page 2?", "mode": "chat"})
        self.assertEqual(status, 200, second)
        latest = next(m for m in reversed(second["messages"]) if m["role"] == "user")
        self.assertEqual(latest["doc_ids"], [doc["doc_id"]])
        status, third = self.req("POST", "/api/chat/send", {"id": chat["id"], "text": "New topic: what is a loop", "mode": "chat"})
        latest = next(m for m in reversed(third["messages"]) if m["role"] == "user")
        self.assertEqual(latest["doc_ids"], [])
        status, plan = self.req("POST", "/api/dry-run", {"text": "Summarise", "mode": "chat", "uploads": [upload]})
        self.assertEqual(status, 200, plan)
        self.assertEqual(plan["documents"]["count"], 1)
        self.assertIn("Attached document plan.pdf", plan["context"]["text"])

    def test_a_refusal_reaches_the_window_as_its_message(self):
        with mock.patch.object(doc_inputs, "RENDER", bridge(problem="locked")):
            status, answer = self.req("POST", "/api/attachments/extract", {"name": "plan.pdf", "base64": encoded(PDF)})
        self.assertEqual(status, 400)
        self.assertIn("locked with a password", answer["error"])


def _small_pdf() -> bytes:
    """Two pages: words and a drawing, written by hand."""
    first = b"BT /F1 20 Tf 72 740 Td (Quarterly plan) Tj ET 2 w 100 500 140 70 re S 330 500 140 70 re S 240 535 m 330 535 l S"
    second = b"BT /F1 20 Tf 72 740 Td (Page two) Tj ET"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 7 0 R >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for content in (first, second):
        packed = zlib.compress(content)
        objects.append(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(packed) + packed + b"\nendstream")
    data, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(data))
        data += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(data)
    data += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    data += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(data)
