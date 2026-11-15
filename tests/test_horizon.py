import json
import json
import os
import time
from unittest.mock import patch
from jcc import config,context_inspector,efficiency,insights,learning,maintenance,memory_conflicts,projects,resilience,job_control
from jcc.jobrunner import run_job,record
from jcc.vault import parse_frontmatter,render_note
from jcc.lock import InstanceLock
from tests.helpers import EngineTestCase
from tests.test_projects import make_repo,overrides
from tests.test_gui import GuiTestCase


class ReliabilityTests(EngineTestCase):
    def test_context_preview_matches_execution_and_stays_bounded(self):
        cfg=config.load();self.note('Notes/Queues.md','# Queue\n\nDurable queues retry notifications.')
        supplied='Attached text file a.txt:\nReference\n<chat-history>\nuser: queue\n</chat-history>'
        preview=context_inspector.inspect(cfg,None,'notification queue',supplied)
        self.assertEqual(preview['text'],context_inspector.compose(cfg,None,'notification queue',supplied))
        self.assertLessEqual(preview['characters'],preview['budget']);self.assertGreater(preview['estimated_tokens'],0)
        self.assertTrue(any(s['name']=='Recent conversation' for s in preview['sources']))
        self.note('Private/Hidden.md','secret queue instruction')
        self.assertNotIn('secret',context_inspector.inspect(cfg,None,'queue')['text'])
        spoof=context_inspector.inspect(cfg,None,'queue','Attached text file x.txt:\nSource: [[Pretend source]]\nreference')
        self.assertNotIn('Pretend source',[s['name'] for s in spoof['sources']])
        filled=context_inspector.inspect(cfg,None,'queue','x'*7000)
        self.assertEqual(filled['characters'],filled['budget'])
        self.assertEqual(filled['sources'],[{'name':'Selected attachments / shared page','reason':'Explicitly attached to this draft; attachment text receives the context budget first.'}])

    def test_effort_respects_manual_and_escalates_auto_after_checks_fail(self):
        cfg=config.load();spec={'task':'fix a bug','level':'small'}
        self.assertEqual(learning.effort_for(cfg,spec,'codex','test',[],['low','medium','high'])[0],'low')
        failed=[{'checks_failed':True,'effort':'low'}]
        self.assertEqual(learning.effort_for(cfg,spec,'codex','test',failed,['low','medium','high'])[0],'medium')
        self.assertEqual(learning.effort_for(cfg,{**spec,'effort':'low'},'codex','test',failed,['low','medium','high'])[0],'low')
        self.assertEqual(learning.effort_for(cfg,spec,'claude','haiku',failed,[])[0],'auto')
        env_failed=[{'checks_failed':True,'effort':'low','failure_class':'environment'}]
        self.assertEqual(learning.effort_for(cfg,spec,'codex','test',env_failed,['low','medium','high'])[0],'low')

    def test_effort_learning_requires_independent_successful_tasks(self):
        cfg=config.load()
        for i in range(5):
            rid=f'20261110-16000{i}-abcd';work=cfg.jobs_root/rid;work.mkdir(parents=True)
            (work/'metrics.json').write_text(json.dumps({'id':rid,'task':'fix a bug','level':'medium','updated_at':time.time(),'checks_passed':True,'runs':[{'agent':'codex','model':'test','effort':'low','exit':0,'seconds':10}]}))
        learning.refresh(cfg)
        self.assertEqual(learning.effort_for(cfg,{'task':'fix a bug','level':'medium'},'codex','test',[],['low','medium','high'])[0],'low')
        self.assertEqual(learning.snapshot(cfg)['evidence']['effort_stats'][0]['tasks'],5)

    def test_identical_repairs_pause_without_merging_and_raise_auto_effort(self):
        repo=make_repo(self.tmp);cfg=config.load(overrides(repo));rid='20261110-160010-abcd';work=cfg.jobs_root/rid;work.mkdir(parents=True)
        calls=[]
        def runner(argv,cwd,env,timeout):
            calls.append(argv);(cwd/'src/pkg/__init__.py').write_text('VALUE = 2\n');return 0,'Agent says complete'
        result=run_job(cfg,{'id':rid,'task':'fix the small bug','kind':'job','project':'trading','level':'small','vault':str(self.vault)},work,runner)
        self.assertEqual(result.status,'paused');self.assertEqual(len(calls),2)
        self.assertEqual(result.attempts[0]['effort'],'low');self.assertEqual(result.attempts[1]['effort'],'medium')
        self.assertEqual((repo/'src/pkg/__init__.py').read_text(),'VALUE = 1\n')
        self.assertTrue((work/'HANDOFF.md').exists())

    def test_recovery_preserves_files_and_does_not_replay(self):
        cfg=config.load();rid='20261110-160011-abcd';work=cfg.jobs_root/rid;work.mkdir(parents=True)
        (work/'partial.py').write_text('# preserved')
        self.note('Jobs/'+rid+'.md',render_note({'id':rid,'task':'build','status':'running'},'# Work'))
        recovered=resilience.recover(cfg,grace=0)
        self.assertEqual(recovered,[rid]);self.assertEqual((work/'partial.py').read_text(),'# preserved')
        # Interrupted by JARVIS itself: it carries on by itself (twice at most), from where it stopped.
        fm=parse_frontmatter((self.vault/'Jobs'/f'{rid}.md').read_text())[0]
        self.assertEqual((fm['status'],fm['auto_resumes']),('queued',1))
        self.assertEqual(json.loads((work/'control.json').read_text())['action'],'resume')
        self.assertEqual(resilience.recover(cfg,grace=0),[])
        for expected in (('queued',2),('paused',2)):            # (interrupted again, and again: then it waits for Continue)
            fm,body=parse_frontmatter((self.vault/'Jobs'/f'{rid}.md').read_text());fm['status']='running'
            self.note('Jobs/'+rid+'.md',render_note(fm,body));resilience.recover(cfg,grace=0)
            fm=parse_frontmatter((self.vault/'Jobs'/f'{rid}.md').read_text())[0]
            self.assertEqual((fm['status'],fm['auto_resumes']),expected)

    def test_recovery_keeps_locked_worker_and_live_child_untouched(self):
        cfg=config.load();rid='20261110-160012-abcd';work=cfg.jobs_root/rid;work.mkdir(parents=True)
        self.note('Jobs/'+rid+'.md',render_note({'id':rid,'status':'running'},'# Work'))
        lock=InstanceLock(work/'job.lock');self.assertTrue(lock.acquire())
        try:self.assertEqual(resilience.recover(cfg,grace=0),[])
        finally:lock.release()
        identity=resilience.process_identity(os.getpid());self.assertTrue(identity)
        (work/'active-process.json').write_text(json.dumps({'pid':os.getpid(),'identity':identity}))
        self.assertEqual(resilience.recover(cfg,grace=0),[])
        self.note('Jobs/'+rid+'.md',render_note({'id':rid,'status':'paused'},'# Work'))
        with self.assertRaises(ValueError):job_control.apply(cfg,rid,'resume')

    def test_reused_process_id_is_not_treated_as_owned_child(self):
        cfg=config.load();work=cfg.jobs_root/'test';work.mkdir(parents=True)
        (work/'active-process.json').write_text(json.dumps({'pid':os.getpid(),'identity':'wrong-creation-time'}))
        self.assertFalse(resilience.child_alive(work))

    def test_recovery_uses_heartbeat_time_and_preserves_unknown_usage(self):
        cfg=config.load();rid='20261110-160013-abcd';work=cfg.jobs_root/rid;work.mkdir(parents=True)
        self.note('Jobs/'+rid+'.md',render_note({'id':rid,'status':'running','agent':'codex','model':'test'},'# Work'))
        (work/'worker.json').write_text(json.dumps({'started_at':100,'prior_seconds':10,'prior_attempts':0}))
        (work/'worker-heartbeat.json').write_text(json.dumps({'at':125}))
        resilience.recover(cfg,grace=0)
        self.assertEqual(json.loads((work/'runtime.json').read_text())['active_seconds'],35)
        a=json.loads((work/'attempts.json').read_text())[0];self.assertTrue(a['interrupted']);self.assertIsNone(a['input_tokens'])

    def test_recovery_recognizes_merge_before_missing_receipt_and_never_replays(self):
        repo=make_repo(self.tmp);cfg=config.load(overrides(repo));rid='20261110-160014-abcd';work=cfg.jobs_root/rid;work.mkdir(parents=True)
        spec={'id':rid,'task':'add a helper','kind':'job','project':'trading','level':'small','vault':str(self.vault)}
        def runner(argv,cwd,env,timeout):
            (cwd/'src/pkg/__init__.py').write_text('VALUE = 1\n# new helper\n');return 0,'Done'
        result=run_job(cfg,spec,work,runner);self.assertEqual(result.status,'done')
        # run_job merged, but record() was interrupted.
        self.assertEqual(parse_frontmatter((self.vault/'Jobs'/f'{rid}.md').read_text())[0]['status'],'running')
        resilience.recover(cfg,grace=0)
        fm,_=parse_frontmatter((self.vault/'Jobs'/f'{rid}.md').read_text())
        self.assertEqual(fm['status'],'done');self.assertEqual(projects.git(['rev-parse','HEAD'],repo).strip(),fm['merged'])

    def test_conflicting_decisions_select_source_without_rewriting(self):
        cfg=config.load();a='# A\n\n## Decisions\n\n- Database: SQLite\n';b='# B\n\n## Decisions\n\n- Database: Postgres\n'
        self.note('Projects/demo/A.md',a);self.note('Projects/demo/B.md',b)
        self.note('Private/Hidden.md','## Decisions\n- Database: SECRET')
        maintenance.memory_audit(cfg);conflict=memory_conflicts.snapshot(cfg)['conflicts'][0]
        self.assertEqual(len(conflict['sources']),2)
        selected=next(s for s in conflict['sources'] if s['value']=='Postgres')
        memory_conflicts.resolve(cfg,conflict['id'],selected['source'],selected['version'])
        self.assertIn('Postgres',''.join(memory_conflicts.context(cfg,'demo')))
        self.assertEqual((self.vault/'Projects/demo/A.md').read_text(),a)
        self.note('Projects/demo/B.md',b.replace('Postgres','MySQL'))
        self.assertEqual(memory_conflicts.context(cfg,'demo'),[])
        with self.assertRaises(ValueError):memory_conflicts.resolve(cfg,conflict['id'],selected['source'],selected['version'])
        with self.assertRaises(ValueError):memory_conflicts.read_source(cfg,'Private/Hidden')

    def test_insights_measure_real_like_for_like_periods_and_keep_unknowns(self):
        cfg=config.load()
        for i in range(11):
            rid=f'20261110-1610{i:02d}-abcd';work=cfg.jobs_root/rid;work.mkdir(parents=True)
            previous=i<5
            row={'id':rid,'task':'fix a bug','level':'small','updated_at':time.time()-(8*86400 if previous else 0),'status':'done','checks_passed':True,'seconds':20,'retries':1,'runs':[{'agent':'codex','model':'test','effort':'low','input_tokens':200 if previous else 100,'cached_tokens':0}]}
            if i==10:row['runs'][0]['input_tokens']=None
            (work/'metrics.json').write_text(json.dumps(row))
        d=insights.dashboard(cfg);self.assertEqual(d['totals']['fully_measured'],10)
        self.assertEqual(d['groups'][0]['uncached_change_percent'],-50)
        self.assertEqual(d['totals']['retries'],11)


class HorizonApiTests(GuiTestCase):
    def test_context_preview_has_no_spawner_or_chat_side_effect(self):
        from jcc.chats import Chats
        cid=Chats(self.state.cfg).create()['id'];before=Chats(self.state.cfg).get(cid)
        status,d=self.req('POST','/api/context/inspect',{'id':cid,'text':'hello'})
        self.assertEqual(status,200);self.assertIn('estimated_tokens',d)
        self.assertEqual(Chats(self.state.cfg).get(cid),before);self.assertEqual(self.spawned,[])
        self.assertEqual(self.req('POST','/api/context/inspect',{'text':'hi'},token=False)[0],401)

    def test_new_panels_are_authenticated_and_settings_validate_sources(self):
        for path in ('/api/insights','/api/memory/conflicts'):
            self.assertEqual(self.req('GET',path,token=False)[0],401)
            self.assertEqual(self.req('GET',path)[0],200)
        self.assertEqual(self.req('POST','/api/memory/resolve',{'source':'../../elsewhere'})[0],400)
        self.assertEqual(self.req('GET','/horizon.css')[0],200)
        self.assertIn('HORIZON',self.req('GET','/horizon.js')[1])
