import json
import os
import sys
import threading
import time
from pathlib import Path
from jcc import config, agents, efficiency, sessions, job_control, diagnostics, workspace, projects
from jcc.chats import Chats
from jcc.jobrunner import run_job, run_process, record
from jcc.vault import parse_frontmatter, render_note, Vault
from tests.helpers import EngineTestCase
from tests.test_projects import make_repo, overrides
from tests.test_gui import GuiTestCase


class EfficiencyTests(EngineTestCase):
    def test_small_helper_keeps_security_work_large(self):
        self.assertEqual(agents.classify_level('Add subtract(a, b) to src/app.py. Add unit tests for positive and negative results. Preserve main().'), 'small')
        self.assertEqual(agents.classify_level('Add a small function that rewrites the security architecture'), 'large')

    def test_usage_is_measured_and_unknown_stays_unknown(self):
        a = efficiency.metadata(json.dumps({'type':'turn.completed','usage':{'input_tokens':100,'cached_input_tokens':70,'output_tokens':8}}),'codex')
        self.assertEqual((a['input_tokens'],a['cached_tokens'],a['output_tokens']),(100,70,8))
        c = efficiency.metadata(json.dumps({'type':'result','usage':{'input_tokens':10,'cache_read_input_tokens':20,'cache_creation_input_tokens':5,'output_tokens':2}}),'claude')
        self.assertEqual(c['input_tokens'],35)
        self.assertIsNone(efficiency.metadata('a finished job','codex')['input_tokens'])

    def test_reuse_is_bound_to_chat_scope_and_drops_duplicate_history(self):
        cfg = config.load(overrides(make_repo(self.tmp)))
        cid = Chats(cfg).create()['id']
        calls=[]
        sid='11111111-2222-3333-4444-555555555555'
        def runner(argv,cwd,env,remaining):
            calls.append(argv)
            (cwd/'RESULT.md').write_text('Nebula','utf-8')
            return 0,json.dumps({'type':'thread.started','thread_id':sid})+'\n'+json.dumps({'type':'turn.completed','usage':{'input_tokens':100,'cached_input_tokens':80,'output_tokens':4}})
        for i in range(2):
            rid=f'20261110-12000{i}-abcd'
            work=cfg.jobs_root/rid;work.mkdir(parents=True)
            spec={'id':rid,'kind':'chat','task':'what is the codename','chat_id':cid,'reference_project':'none','project':None,'vault':str(self.vault),'level':'small','context':'<chat-history>already sent dialogue</chat-history>\nNew attachment: reference'}
            result=run_job(cfg,spec,work,runner)
            self.assertEqual(result.status,'done')
            record(cfg,spec,work,result,1)
            self.assertTrue((work/'RESULT.md').exists())
        self.assertNotIn('resume',calls[0])
        self.assertIn('resume',calls[1])
        self.assertIn(sid,calls[1])
        self.assertNotIn('already sent dialogue',calls[1][-1])
        self.assertIn('New attachment',calls[0][-1])
        self.assertNotIn('New attachment',calls[1][-1])
        self.assertIn('references are unchanged',calls[1][-1])
        self.assertEqual(efficiency.summary(cfg)[0]['cached_tokens'],80)
        cwd=sessions.workspace(cfg,spec,work)
        self.assertIsNone(sessions.get(cfg,{**spec,'reference_project':'another'},'codex','',cwd))
        self.assertIsNone(sessions.get(cfg,{**spec,'task':'new topic: gardening'},'codex','',cwd))

    def test_local_search_selects_relevant_private_safe_bounded_passage(self):
        cfg=config.load()
        self.note('Notes/Gardening.md','# Gardening\n\nHow to plant tomatoes.')
        self.note('Notes/Queues.md','# Message queues\n\nUse a durable queue for notification retries.')
        self.note('Private/Queues.md','notification retries secret')
        text=workspace.memory(cfg,None,'notification queue retries')
        self.assertIn('durable queue',text)
        self.assertNotIn('tomatoes',text)
        self.assertNotIn('secret',text)
        self.note('Notes/Queues.md','---\nprivate: true\n---\nnotification retries secret')
        self.assertNotIn('durable queue',workspace.memory(cfg,None,'notification queue retries'))

    def test_expired_provider_session_retries_fresh_within_budget(self):
        cfg=config.load(overrides(make_repo(self.tmp)))
        cid=Chats(cfg).create()['id'];rid='20261110-120020-abcd';work=cfg.jobs_root/rid;work.mkdir(parents=True)
        spec={'id':rid,'kind':'chat','task':'what is the codename','chat_id':cid,'project':None,'vault':str(self.vault),'level':'small'}
        cwd=sessions.workspace(cfg,spec,work)
        sessions.remember(cfg,spec,'codex','',cwd,{'session_id':'11111111-2222-3333-4444-555555555555'})
        calls=[]
        def runner(argv,cwd,env,seconds):
            calls.append(argv)
            if len(calls)==1:return 1,'Session not found'
            (cwd/'RESULT.md').write_text('Fresh response','utf-8')
            return 0,'finished'
        result=run_job(cfg,spec,work,runner)
        self.assertEqual(result.status,'done')
        self.assertIn('resume',calls[0]);self.assertNotIn('resume',calls[1])
        self.assertEqual(len(result.attempts),2)

    def test_reuse_resets_when_provider_changes_or_uncached_input_grows(self):
        cfg=config.load();spec={'kind':'chat','chat_id':'20261110-120000-abcd','task':'hello','context':''}
        cwd=cfg.jobs_root/'chat';cwd.mkdir(parents=True)
        m={'session_id':'11111111-2222-3333-4444-555555555555','input_tokens':100,'cached_tokens':60}
        sessions.remember(cfg,spec,'codex','fast',cwd,m)
        previous=sessions.get(cfg,spec,'codex','fast',cwd)
        self.assertIsNotNone(previous)
        reason=sessions.remember(cfg,spec,'codex','fast',cwd,{**m,'input_tokens':200,'cached_tokens':100},previous)
        self.assertIn('uncached',reason)
        self.assertIsNone(sessions.get(cfg,spec,'codex','fast',cwd))
        sessions.remember(cfg,spec,'codex','fast',cwd,m)
        sessions.remember(cfg,spec,'claude','sonnet',cwd,m)
        self.assertIsNone(sessions.get(cfg,spec,'codex','fast',cwd))

    def test_attempt_budget_pauses_preserves_and_resumes_edits(self):
        repo=make_repo(self.tmp);raw=overrides(repo)
        raw['agents']['codex']['models']={'small':'fast','medium':'normal','large':'deep'}
        cfg=config.load(raw);rid='20261110-120010-abcd';work=cfg.jobs_root/rid;work.mkdir(parents=True)
        spec={'id':rid,'kind':'job','task':'fix typo','project':'trading','vault':str(self.vault),'level':'small','max_attempts':1}
        def fail(argv,cwd,env,seconds):
            (cwd/'src/pkg/__init__.py').write_text('VALUE = 2\n','utf-8');return 0,'edited'
        result=run_job(cfg,spec,work,fail)
        self.assertEqual(result.status,'paused')
        self.assertTrue((work/'repo').exists())
        self.assertEqual(projects.git(['show','master:src/pkg/__init__.py'],repo).strip(),'VALUE = 1')
        def repair(argv,cwd,env,seconds):
            self.assertEqual((cwd/'src/pkg/__init__.py').read_text(),'VALUE = 2\n')
            (cwd/'src/pkg/__init__.py').write_text('VALUE = 1\n# repaired\n','utf-8');return 0,'fixed'
        result=run_job(cfg,{**spec,'max_attempts':3},work,repair)
        self.assertEqual(result.status,'done')
        self.assertEqual(len(result.attempts),2)

    def test_pause_and_cancel_stop_only_the_owned_process(self):
        for action,expected in [('pause',130),('cancel',131)]:
            work=self.tmp/action;work.mkdir()
            env={**os.environ,'JCC_CONTROL_FILE':str(work/'control.json')}
            results=[]
            thread=threading.Thread(target=lambda:results.append(run_process([sys.executable,'-c','import time; time.sleep(15)'],work,env,20)))
            start=time.monotonic();thread.start();time.sleep(.2)
            (work/'control.json').write_text(json.dumps({'action':action}),'utf-8')
            thread.join(8)
            self.assertFalse(thread.is_alive())
            self.assertEqual(results[0][0],expected)
            self.assertLess(time.monotonic()-start,8)

    def test_paused_coding_job_reuses_its_own_preserved_session(self):
        repo=make_repo(self.tmp);cfg=config.load(overrides(repo));rid='20261110-120030-abcd'
        work=cfg.jobs_root/rid;work.mkdir(parents=True)
        spec={'id':rid,'kind':'job','task':'fix typo','project':'trading','vault':str(self.vault),'level':'small','max_attempts':3}
        sid='11111111-2222-3333-4444-555555555555'
        def pause(argv,cwd,env,seconds):
            (cwd/'src/pkg/__init__.py').write_text('VALUE = 1\n# partial edit\n','utf-8')
            return 130,json.dumps({'type':'thread.started','thread_id':sid})
        self.assertEqual(run_job(cfg,spec,work,pause).status,'paused')
        def resume(argv,cwd,env,seconds):
            self.assertIn('resume',argv);self.assertIn(sid,argv)
            self.assertIn('partial edit',(cwd/'src/pkg/__init__.py').read_text())
            return 0,'completed'
        result=run_job(cfg,spec,work,resume)
        self.assertEqual(result.status,'done')
        self.assertTrue(result.merged)

    def test_diagnostics_do_not_call_one_capture_full_sync(self):
        cfg=config.load()
        self.state.mkdir(parents=True,exist_ok=True)
        (self.state/'capture-status.json').write_text(json.dumps({'source':'Claude','at':time.time()}))
        diagnostics.probe(cfg,{'source':'ChatGPT','messages':0,'saved':True,'version':'1.2.0'})
        d=diagnostics.snapshot(cfg)
        self.assertIn('no messages',d['ChatGPT website']['status'])
        self.assertIsNone(d['ChatGPT website']['last_success'])
        self.assertIsNotNone(d['Claude website']['last_success'])


class EfficiencyApiTests(GuiTestCase):
    def test_job_controls_auth_validation_and_queue_resume(self):
        cfg=self.state.cfg;rid='20261110-120000-abcd'
        Vault(cfg.vault).write(f'Jobs/{rid}.md',render_note({'id':rid,'status':'queued','task':'fix typo'},'# Queued'))
        self.assertEqual(self.req('POST','/api/job/control',{'id':rid,'action':'pause'},token=False)[0],401)
        self.assertEqual(self.req('POST','/api/job/control',{'id':'../x','action':'cancel'})[0],400)
        self.assertEqual(self.req('POST','/api/job/control',{'id':rid,'action':'pause'})[1]['status'],'paused')
        self.assertEqual(self.req('POST','/api/job/control',{'id':rid,'action':'resume'})[1]['status'],'queued')
        self.assertEqual(self.req('POST','/api/job/control',{'id':rid,'action':'cancel'})[1]['status'],'cancelled')

    def test_settings_and_diagnostics_shape(self):
        good={**efficiency.DEFAULTS,'max_attempts':3}
        self.assertEqual(self.req('POST','/api/efficiency',{'settings':good})[0],200)
        self.assertEqual(efficiency.settings(self.state.cfg)['max_attempts'],3)
        self.assertEqual(self.req('POST','/api/efficiency',{'settings':{**good,'max_attempts':100}})[0],400)
        d=self.req('GET','/api/state')[1]
        self.assertIn('diagnostics',d)
        self.assertIn('jobs',d['efficiency'])
