"""Outcome learning and reversible owner controls; no provider requests."""
import json
import os
import time
from unittest.mock import patch
from jcc import activity, config, learning, maintenance, onboarding, projects, review
from jcc.vault import parse_frontmatter, render_note
from tests.helpers import EngineTestCase
from tests.test_projects import ProjectJobTest, make_repo, overrides, git
from tests.test_gui import GuiTestCase


class LearningTests(EngineTestCase):
    def sample(self,cfg,i,**kw):
        rid=f'20261110-1400{i:02d}-abcd';work=cfg.jobs_root/rid;work.mkdir(parents=True,exist_ok=True)
        row={'id':rid,'task':'fix a bug','family':'debugging','level':'small','updated_at':time.time(),
             'checks_passed':True,'runs':[{'agent':'claude','model':'sonnet','exit':0,'seconds':10,'input_tokens':100,'cached_tokens':80}]}
        row.update(kw);(work/'metrics.json').write_text(json.dumps(row),'utf-8');return rid

    def test_evidence_threshold_and_manual_preferences(self):
        cfg=config.load();c=[('codex','fast'),('claude','sonnet')];spec={'task':'fix a bug','level':'small'}
        for i in range(4): self.sample(cfg,i)
        learning.refresh(cfg);self.assertEqual(learning.rank(cfg,spec,c)[0],c)
        self.sample(cfg,4);learning.refresh(cfg)
        self.assertEqual(learning.rank(cfg,spec,c)[0][0],c[1])
        for change in ({'manual_model':'claude:sonnet'},{'prefer':'codex'},{'level':'large'},{'task':'fix security risk engine'}):
            self.assertEqual(learning.rank(cfg,{**spec,**change},c)[0],c)
        cfg.raw['routing_choices']={'small':{'model':'codex:fast'}}
        self.assertEqual(learning.rank(cfg,spec,c)[0],c)

    def test_retries_do_not_fake_independent_tasks_and_unknown_is_not_quality(self):
        cfg=config.load();self.sample(cfg,0,runs=[{'agent':'claude','model':'sonnet','exit':0,'verified':True}]*10)
        self.sample(cfg,1,checks_passed=False)
        r=learning.refresh(cfg)['stats'][0]
        self.assertEqual(r['tasks'],1);self.assertFalse(r['eligible'])

    def test_feedback_can_qualify_discussions_but_never_overrides_failed_checks(self):
        cfg=config.load()
        for i in range(5):
            rid=self.sample(cfg,i,kind='chat',family='discussion',checks_passed=False)
            learning.rate(cfg,rid,'helpful')
        row=learning.snapshot(cfg)['evidence']['stats'][0];self.assertTrue(row['eligible']);self.assertEqual(row['rated_successes'],5)
        learning.rate(cfg,rid,'needs_work');self.assertEqual(learning.snapshot(cfg)['evidence']['stats'][0]['success_rate'],.8)
        with self.assertRaises(ValueError):learning.rate(cfg,'../../x','helpful')

    def test_stale_limit_environment_samples_excluded_and_preferences_validated(self):
        cfg=config.load()
        self.sample(cfg,0,updated_at=0)
        self.sample(cfg,1,runs=[{'exit':0,'failure_class':'environment'}])
        self.sample(cfg,2,runs=[{'exit':0,'limit':True}])
        self.assertEqual(learning.refresh(cfg)['stats'],[])
        with self.assertRaises(ValueError): learning.configure(cfg,{'adaptive_routing':'yes'})
        learning.configure(cfg,{**learning.DEFAULTS,'adaptive_routing':False})
        self.assertIn('off',learning.rank(cfg,{'task':'fix','level':'small'},[('codex','x')])[1])

    def test_manually_tried_catalog_model_can_earn_auto_selection(self):
        cfg=config.load()
        for i in range(5): self.sample(cfg,i)
        learning.refresh(cfg)
        spec={'task':'fix a bug','level':'small'}
        c=[('codex','fast'),('claude','opus')]
        self.assertEqual(learning.rank(cfg,spec,c)[0][0],('claude','sonnet'))
        self.assertNotIn(('claude','sonnet'),learning.rank(cfg,spec,[('codex','fast')])[0])


class MaintenanceTests(EngineTestCase):
    def test_cloud_chunks_handle_database_incompatible_nul_without_losing_prefix(self):
        from jcc.cloud_memory import chunks
        text='a'*2100+'\x00'+'b'*1000
        parts=chunks(text)
        self.assertNotIn('\x00',''.join(parts));self.assertEqual(parts[0],chunks(text.replace('\x00','x'))[0])
        self.assertEqual(len(parts[2]),1100)

    def test_memory_audit_preserves_sources_and_excludes_private_archive(self):
        cfg=config.load();body='# Queue\n\n'+'Durable message queue. '*6+'[[Missng]]'
        self.note('Notes/Queue.md',body);self.note('Notes/Copy.md',body)
        self.note('Private/Secret.md',body+'private secret');self.note('Notes/Hidden.md','---\nprivate: true\n---\nsecret')
        self.note('Conversations/Old.md',body)
        result=maintenance.memory_audit(cfg)
        self.assertEqual(result['notes_checked'],2)
        self.assertIn('duplicate',[s['kind'] for s in result['suggestions']])
        self.assertEqual((self.vault/'Notes/Queue.md').read_text('utf-8'),body)
        report=(self.vault/'System/Memory audit.md').read_text('utf-8')
        self.assertIn('[[Notes/Queue]]',report);self.assertNotIn('Secret',report);self.assertNotIn('Conversations/Old',report)

    def test_real_isolated_backup_restore_and_checksum(self):
        cfg=config.load();repo=make_repo(self.tmp);(repo/'Memory.md').write_text('# Durable memory\n','utf-8')
        projects.commit_all(repo,'add note')
        result=maintenance.restore_check(cfg,str(repo))
        self.assertEqual(result['status'],'verified',result)
        self.assertEqual(result['notes_restored'],1)
        self.assertGreaterEqual(result['files_restored'],4)
        self.assertEqual(list((cfg.state_dir/'restore-checks').iterdir()),[])
        self.assertEqual((repo/'Memory.md').read_text('utf-8'),'# Durable memory\n')

    def test_restore_failure_is_reported(self):
        cfg=config.load();result=maintenance.restore_check(cfg,str(self.tmp/'missing'))
        self.assertEqual(result['status'],'error')

    def test_onboarding_is_readonly_and_review_is_default(self):
        cfg=config.load();repo=make_repo(self.tmp);before=git('status','--porcelain',cwd=repo)
        d=onboarding.inspect(cfg,str(repo));self.assertTrue(d['ready']);self.assertIn('Python',d['stack'])
        self.assertIn('unittest',str(d['checks']));self.assertEqual(git('status','--porcelain',cwd=repo),before)
        onboarding.connect(cfg,str(repo));self.assertFalse(cfg.projects['proj'].auto_merge)
        with self.assertRaises(ValueError): onboarding.connect(cfg,str(repo))
        with self.assertRaises(ValueError): onboarding.inspect(cfg,str(cfg.vault))

    def test_no_tests_or_git_cannot_connect(self):
        cfg=config.load();root=self.tmp/'unready';root.mkdir();(root/'index.html').write_text('<h1>hello</h1>')
        self.assertFalse(onboarding.inspect(cfg,str(root))['ready'])
        with self.assertRaises(ValueError):onboarding.connect(cfg,str(root))

    def test_local_events_and_alert_dedup(self):
        cfg=config.load();rid='20261110-140000-abcd'
        activity.emit(cfg,rid,'working','Processing safely',model='test')
        self.assertEqual(activity.events(cfg,rid)[0]['stage'],'working')
        activity.alert(cfg,rid,'done');stamp=activity.alerts(cfg)[0]['at'];activity.alert(cfg,rid,'done')
        self.assertEqual(activity.alerts(cfg)[0]['at'],stamp)
        with self.assertRaises(ValueError):activity.events(cfg,'../../x')
        self.note('Jobs/Template.md','---\nstatus: queued\n---\nTemplate')
        self.note('Jobs/'+rid+'.md','---\nstatus: done\n---\nLegacy note')
        self.assertEqual([r['id'] for r in activity.recent(cfg)],[rid])


class ReviewTests(EngineTestCase):
    def setUp(self):
        super().setUp();self.repo=make_repo(self.tmp);self.modes={}
    def tearDown(self):
        for k in list(os.environ):
            if k.startswith('FAKEAGENT_MODE_'): del os.environ[k]
        super().tearDown()
    run_project_job=ProjectJobTest.run_project_job
    master_file=ProjectJobTest.master_file
    def test_review_checked_merge_then_checked_undo(self):
        cfg,rid,res=self.run_project_job(auto_merge=False)
        d=review.details(cfg,rid);self.assertTrue(d['can_merge']);self.assertIn('added_by_agent',d['diff'])
        with self.assertRaises(ValueError):review.approve(cfg,rid,'old-revision')
        result=review.approve(cfg,rid,d['revision']);self.assertEqual(result['status'],'done')
        self.assertTrue(review.details(cfg,rid)['can_undo'])
        review.undo(cfg,rid);self.assertEqual(self.master_file(),'VALUE = 1\n')
        self.assertFalse(review.details(cfg,rid)['can_undo'])
        with self.assertRaises(ValueError):review.undo(cfg,rid)

    def test_undo_refuses_later_owner_work(self):
        cfg,rid,res=self.run_project_job()
        (self.repo/'Owner.md').write_text('my later work');projects.commit_all(self.repo,'owner change')
        self.assertFalse(review.details(cfg,rid)['can_undo'])
        with self.assertRaises(ValueError):review.undo(cfg,rid)
        self.assertTrue((self.repo/'Owner.md').exists())

    def test_protected_diff_cannot_be_approved(self):
        cfg,rid,res=self.run_project_job(modes={'codex':'risk'})
        with self.assertRaises(ValueError):review.approve(cfg,rid,review.details(cfg,rid)['revision'])

    def test_global_review_preference(self):
        cfg=config.load();learning.configure(cfg,{**learning.DEFAULTS,'review_before_merge':True})
        _,rid,res=self.run_project_job()
        self.assertEqual(res.status,'needs_approval');self.assertEqual(self.master_file(),'VALUE = 1\n')


class AssistantApiTests(GuiTestCase):
    def test_static_script_has_own_contents(self):
        status,body=self.req('GET','/assistant.js');self.assertEqual(status,200);self.assertIn('Learn from results',body)
        self.assertNotIn('window.jarvisFiles=[]',body)

    def test_new_routes_require_auth_and_validate_input(self):
        for path in ('/api/feedback','/api/project/connect','/api/job/review','/api/assistant/settings','/api/maintenance'):
            self.assertEqual(self.req('POST',path,{},token=False)[0],401)
            self.assertEqual(self.req('POST',path,{})[0],400)
        self.assertEqual(self.req('GET','/api/job/details?id=../x')[0],400)
        self.assertEqual(self.req('POST','/api/ui/activity',{'focused':True})[0],200)
        self.assertTrue((self.state.cfg.state_dir/'ui-active').exists())

    def test_state_exposes_honest_initial_learning_and_maintenance(self):
        status,data=self.req('GET','/api/state');self.assertEqual(status,200)
        self.assertEqual(data['learning']['evidence']['stats'],[])
        self.assertIn('restore-check',data['maintenance'])

del ProjectJobTest
