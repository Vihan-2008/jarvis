"""Simple-view delivery and frontend contracts, with no live browser or models."""
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tests.test_gui import GuiTestCase
from tests.helpers import EngineTestCase


class EverydayApiTests(GuiTestCase):
    def test_everyday_assets_are_served_and_apis_stay_authenticated(self):
        status,page=self.req('GET','/');self.assertEqual(status,200)
        self.assertIn('<body class="everyday">',page);self.assertIn('/everyday.css',page);self.assertIn('/everyday.js',page)
        for path in ('/everyday.js','/everyday.css'):
            status,body=self.req('GET',path,token=False);self.assertEqual(status,200);self.assertTrue(body)
        self.assertEqual(self.req('POST','/api/chat/send',{'text':'Hello'},token=False)[0],401)
        self.assertEqual(self.spawned,[])


class EverydayContractTests(unittest.TestCase):
    def test_simple_view_preserves_controls_and_never_sends_implicitly(self):
        node=shutil.which('node')
        self.assertIsNotNone(node,'The installed UI contract suite requires Node.js.')
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([node,'--test','tests/everyday_ui.test.js','tests/operations_ui.test.js','tests/upload_ui.test.js'],cwd=root,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
        self.assertEqual(result.returncode,0,(result.stdout+result.stderr)[-2500:])


class EverydayExplanationTests(EngineTestCase):
    def test_waiting_requests_keep_their_actual_reason(self):
        from jcc import config,task_queue
        from jcc.vault import render_note
        cfg=config.load();rid='20261111-050000-abcd'
        self.note('Jobs/'+rid+'.md',render_note({'id':rid,'status':'queued','wait_reason':'Daily measured token budget reached.','task':'A small request'},'# Waiting'))
        row=next(r for r in task_queue.snapshot(cfg)['tasks'] if r['id']==rid)
        self.assertEqual(row['reason'],'Daily measured token budget reached.')
