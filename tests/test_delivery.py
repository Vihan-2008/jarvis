"""Delivery controls verified with fake agents and temporary repositories."""
import json
import time
from dataclasses import replace
from unittest.mock import patch
from jcc import config,context_inspector,delivery,learning,projects,review,task_queue,work_history,routing_guard
from jcc.jobrunner import run_job,record
from jcc.vault import render_note,parse_frontmatter,Vault
from jcc.jobs import JobLauncher
from tests.helpers import EngineTestCase
from tests.test_projects import make_repo,overrides
from tests.test_gui import GuiTestCase


class DeliveryTests(EngineTestCase):
    def run_delivery(self,report=True,enabled=False,verdict='clear',maximum=4,large_diff=False,model_available=True,implementer='codex',pause_review=False,manual=False):
        repo=make_repo(self.tmp);cfg=config.load(overrides(repo,levels=(implementer,'claude' if implementer=='codex' else 'codex')));rid='20261111-010000-abcd';work=cfg.jobs_root/rid;work.mkdir(parents=True)
        delivery.configure(cfg,{**delivery.DEFAULTS,'review_enabled':enabled})
        if manual:
            from jcc import assistant
            assistant.configure(cfg,{'ask':'all'})        # Manual: a change waits for its owner
        if not model_available:cfg.agents['claude']=replace(cfg.agents['claude'],enabled=False)
        task='Add a helper. Preserve existing behavior.';items=delivery.criteria(task)
        spec={'id':rid,'task':task,'kind':'job','level':'large','vault':str(self.vault),'project':'trading','delivery_version':1,'acceptance':items,'max_attempts':maximum}
        calls=[]
        def runner(argv,cwd,env,seconds):
            calls.append((argv,seconds))
            if any(str(a).startswith('Review only the supplied') for a in argv):
                if pause_review:(work/'control.json').write_text(json.dumps({'action':'pause'}));return 130,'Paused'
                return 0,json.dumps({'status':verdict,'findings':[] if verdict=='clear' else ['Requested behavior is incomplete.']})
            (cwd/'src/pkg/__init__.py').write_text('VALUE = 1\n# helper\n'+('#'+('x'*15000)+'\n' if large_diff else ''))
            if report:(cwd/delivery.report_name(rid)).write_text(json.dumps({'items':[{'id':i['id'],'status':'met','evidence':'src/pkg/__init__.py and tests/test_value.py'} for i in items]}))
            return 0,'Implementation complete'
        result=run_job(cfg,spec,work,runner);record(cfg,spec,work,result,1)
        return cfg,rid,result,calls,repo

    def test_checklist_preserves_all_parts_and_adds_no_scope(self):
        text='Add a helper. Preserve behavior.\n- Add tests.'
        items=delivery.criteria(text);self.assertEqual(len(items),3)
        self.assertEqual(items[0]['requirement'],'Add a helper.')
        self.assertIn('.jcc-acceptance-',delivery.instructions(items))
        many=delivery.criteria('\n'.join('Requirement '+str(i) for i in range(20)))
        self.assertEqual(len(many),12);self.assertIn('Requirement 19',many[-1]['requirement'])

    def finished_but_unshown(self,manual):
        cfg,rid,res,calls,repo=self.run_delivery(report=False,manual=manual)
        self.assertEqual((res.status,res.unfinished,res.carry_kind),('paused',True,'requirements'),res.merge_note)
        self.assertTrue(all(c.ok for c in res.checks))
        self.assertTrue(res.merge_note.startswith('Not finished yet: 0 of 2 requirements are shown met.'),res.merge_note)
        self.assertNotIn('Done',res.merge_note)
        self.assertIn('A1: Add a helper.',res.carry_on);self.assertIn('A2: Preserve existing behavior.',res.carry_on)
        self.assertEqual((repo/'src/pkg/__init__.py').read_text(),'VALUE = 1\n','nothing is put into the project yet')
        self.assertEqual(review.details(cfg,rid)['acceptance']['items'][0]['claim'],'unreported')

    def test_missing_acceptance_is_not_finished_the_job_carries_on_with_what_is_left(self):
        self.finished_but_unshown(manual=False)

    def test_in_manual_too_the_job_carries_on_until_its_requirements_are_met(self):
        self.finished_but_unshown(manual=True)

    def test_after_its_rounds_it_says_what_is_left_and_is_never_called_done(self):
        with patch('jcc.jobrunner.REQUIREMENT_ROUNDS',0):
            cfg,rid,res,calls,repo=self.run_delivery(report=False)
        self.assertEqual((res.status,res.unfinished,res.carry_on),('paused',True,''),res.merge_note)
        self.assertTrue(res.merge_note.startswith('Not finished: 0 of 2 requirements are shown met. Still to do: A1: Add a helper.'),res.merge_note)
        self.assertIn('press Continue',res.merge_note)
        self.assertEqual((repo/'src/pkg/__init__.py').read_text(),'VALUE = 1\n','not put into the project unfinished')

    def test_in_manual_after_its_rounds_its_owner_decides(self):
        with patch('jcc.jobrunner.REQUIREMENT_ROUNDS',0):
            cfg,rid,res,calls,repo=self.run_delivery(report=False,manual=True)
        self.assertEqual(res.status,'needs_approval')

    def test_a_remark_in_the_request_is_not_a_requirement_left_undone(self):
        items=delivery.criteria('Fix the button. This is the error I get after clicking it.')
        rows=[{**items[0],'claim':'met','evidence':'app.js; tests pass'},{**items[1],'claim':'not_a_requirement','evidence':'It describes the error A1 fixes.'}]
        self.assertEqual(delivery.unmet({'items':rows}),[])
        rows[1]['evidence']=''
        self.assertEqual([r['id'] for r in delivery.unmet({'items':rows})],['A2'],'said why, or it is not taken')
        self.assertIn('not_a_requirement',delivery.instructions(items));self.assertIn('blocked',delivery.instructions(items))

    def test_in_auto_a_second_looks_findings_are_said_beside_the_change(self):
        cfg,rid,res,calls,repo=self.run_delivery(enabled=True,verdict='changes_needed')
        self.assertEqual(res.status,'done',res.merge_note);self.assertIn('Requested behavior is incomplete.',res.merge_note)

    def test_evidence_is_kept_outside_code_and_review_is_off_by_default(self):
        cfg,rid,res,calls,repo=self.run_delivery()
        self.assertEqual(res.status,'done',res.merge_note);self.assertEqual(len(calls),1)
        self.assertNotIn(delivery.report_name(rid),projects.git(['ls-files'],repo))
        self.assertEqual(review.details(cfg,rid)['acceptance']['items'][0]['claim'],'met')

    def test_independent_second_provider_review_is_bounded(self):
        cfg,rid,res,calls,repo=self.run_delivery(enabled=True)
        self.assertEqual(res.status,'done',res.merge_note);self.assertEqual(len(calls),2)
        self.assertLessEqual(calls[-1][1],90);self.assertEqual(res.attempts[-1]['kind'],'review')
        self.assertEqual(res.agent,'codex');self.assertEqual(res.attempts[-1]['agent'],'claude')
        self.assertIn('--disallowedTools',calls[-1][0])
        self.assertEqual(review.details(cfg,rid)['peer_review']['status'],'clear')
        metrics=json.loads((cfg.jobs_root/rid/'metrics.json').read_text());self.assertEqual(metrics['retries'],0)

    def test_critical_findings_keep_branch_and_owner_can_review_revision(self):
        cfg,rid,res,calls,repo=self.run_delivery(enabled=True,verdict='changes_needed',manual=True)
        self.assertEqual(res.status,'needs_approval')
        d=review.details(cfg,rid);review.approve(cfg,rid,d['revision'])
        self.assertIn('owner_approved_at',review.details(cfg,rid)['acceptance'])

    def test_review_never_exceeds_attempt_budget(self):
        _,_,res,calls,_=self.run_delivery(enabled=True,maximum=1,manual=True)
        self.assertEqual(len(calls),1);self.assertEqual(res.status,'needs_approval')

    def test_unavailable_second_provider_does_not_silently_skip_required_review(self):
        _,_,res,calls,_=self.run_delivery(enabled=True,model_available=False,manual=True)
        self.assertEqual(len(calls),1);self.assertEqual(res.status,'needs_approval')

    def test_truncated_diff_cannot_get_an_automatic_clear(self):
        cfg,rid,res,calls,_=self.run_delivery(enabled=True,large_diff=True,manual=True)
        self.assertEqual(res.status,'needs_approval');self.assertTrue(review.details(cfg,rid)['peer_review']['diff_truncated'])

    def test_malformed_review_and_invalid_settings_do_not_pass(self):
        self.assertEqual(delivery.parse_review('not JSON')['status'],'incomplete')
        self.assertEqual(delivery.parse_review('{"item":"invalid"}')['status'],'incomplete')
        self.assertEqual(delivery.parse_review('{"status":"clear","findings":["Critical bug"]}')['status'],'changes_needed')
        cfg=config.load()
        with self.assertRaises(ValueError):delivery.configure(cfg,{**delivery.DEFAULTS,'review_timeout_seconds':10000})

    def test_codex_reviewer_uses_readonly_sandbox_and_disables_web(self):
        _,_,res,calls,_=self.run_delivery(enabled=True,implementer='claude')
        self.assertEqual(res.status,'done');self.assertIn('read-only',calls[-1][0]);self.assertIn('web_search="disabled"',calls[-1][0])

    def test_pause_during_review_does_not_turn_into_merge_approval(self):
        _,_,res,calls,repo=self.run_delivery(enabled=True,pause_review=True)
        self.assertEqual(res.status,'paused');self.assertEqual((repo/'src/pkg/__init__.py').read_text(),'VALUE = 1\n')

    def test_existing_reserved_report_is_never_overwritten(self):
        repo=make_repo(self.tmp);cfg=config.load(overrides(repo));rid='20261111-010001-abcd'
        (repo/delivery.report_name(rid)).write_text('original project file');projects.commit_all(repo,'owner file')
        work=cfg.jobs_root/rid;work.mkdir(parents=True);calls=[]
        res=run_job(cfg,{'id':rid,'task':'add a helper','kind':'job','project':'trading','vault':str(self.vault),'delivery_version':1,'acceptance':delivery.criteria('add a helper')},work,lambda *args:calls.append(args))
        self.assertEqual(res.status,'needs_approval');self.assertEqual(calls,[]);self.assertEqual((repo/delivery.report_name(rid)).read_text(),'original project file')


class PlanningTests(EngineTestCase):
    def queued(self,rid,status='queued'):
        self.note('Jobs/'+rid+'.md',render_note({'id':rid,'task':'add a helper','kind':'job','project_key':'trading','status':status},'# Job'))

    def test_priorities_dependencies_and_cycle_protection(self):
        cfg=config.load();a='20261111-011000-abcd';b='20261111-011001-abcd'
        self.queued(a);self.queued(b)
        task_queue.update(cfg,b,1,[a]);self.assertEqual(task_queue.ordered(cfg)[0]['id'],b)
        d=task_queue.snapshot(cfg);self.assertEqual(d['next'],a);self.assertEqual(d['tasks'][0]['display_status'],'blocked')
        with self.assertRaises(ValueError):task_queue.update(cfg,a,0,[b])
        self.queued(a,'done');self.assertFalse(task_queue.blocked(cfg,b))
        with self.assertRaises(ValueError):task_queue.update(cfg,a,0,[])
        with self.assertRaises(ValueError):task_queue.update(cfg,b,0,[{}])

    def test_blocked_job_cannot_bypass_dependency_via_direct_launcher(self):
        repo=make_repo(self.tmp);cfg=config.load(overrides(repo));a='20261111-011002-abcd';b='20261111-011003-abcd'
        self.queued(a);self.queued(b);task_queue.update(cfg,b,1,[a]);spawn=[]
        launcher=JobLauncher(cfg,Vault(self.vault),spawner=lambda *args:spawn.append(args))
        out=launcher.launch(b,'job','add a helper','trading')
        self.assertEqual(out.status,'queued');self.assertEqual(spawn,[])

    def test_dispatcher_uses_priority_and_does_not_launch_blocked_high_task(self):
        repo=make_repo(self.tmp);settings=overrides(repo);settings['tier3']['max_running']=1
        engine=self.make_engine(settings)
        a='20261111-011004-abcd';b='20261111-011005-abcd';self.queued(a);self.queued(b)
        task_queue.update(engine.cfg,b,1,[a]);engine.retry_queued()
        self.assertEqual(len(self.spawned),1);self.assertIn(a,str(self.spawned[0][0]))

    def test_adaptive_context_preserves_required_sources_and_expands_within_hard_cap(self):
        repo=make_repo(self.tmp);cfg=config.load(overrides(repo))
        self.note('Projects/trading/Memory.md','Required behavior. '*90)
        self.note('Notes/Required.md','Explicit requirement. '*70)
        self.note('Notes/Optional.md','helper detail '*200)
        task='Add helper [[Notes/Required]].'
        small=context_inspector.inspect(cfg,'trading',task,'Attached: important file\n'+('x'*700))
        self.assertIn('Explicit requirement',small['text']);self.assertIn('Required behavior',small['text'])
        self.assertLessEqual(small['budget'],small['hard_budget'])
        self.assertGreaterEqual(len(context_inspector.compose(cfg,'trading',task,'Attached: important file\n'+('x'*700),expand=True)),small['characters'])
        self.assertLess(context_inspector.inspect(cfg,None,'Add a small helper')['budget'],6000)

    def test_work_history_keeps_sources_and_excludes_private_archives(self):
        cfg=config.load();self.note('Projects/demo/Memory.md','## Decisions\n- Database: SQLite for portability.')
        self.note('Private/Private.md','SQLite private secret')
        self.note('Projects/demo/Hidden.md','---\nprivate: true\n---\nSQLite hidden secret')
        self.note('Conversations/Imported/History.md','SQLite archive secret')
        d=work_history.search(cfg,'Why did we choose SQLite?')
        self.assertEqual(len(d['results']),1);self.assertEqual(d['results'][0]['source'],'Projects/demo/Memory')
        self.assertIn('portability',d['results'][0]['snippet'])

    def test_failed_checks_expand_context_once_without_changing_original_task(self):
        repo=make_repo(self.tmp);cfg=config.load(overrides(repo));rid='20261111-011006-abcd';work=cfg.jobs_root/rid;work.mkdir(parents=True)
        task='Add a small helper. Preserve behavior.';items=delivery.criteria(task);calls=[]
        with patch('jcc.workspace.memory',return_value='Historical reference. '*400):
            original=context_inspector.compose(cfg,None,task)
            spec={'id':rid,'task':task,'kind':'job','project':'trading','reference_project':'trading','level':'small','vault':str(self.vault),'delivery_version':1,'acceptance':items,'context':original,'context_source':''}
            def runner(argv,cwd,env,timeout):
                calls.append(next(str(x) for x in argv if 'TASK:' in str(x)))
                (cwd/'src/pkg/__init__.py').write_text('VALUE = '+('2' if len(calls)==1 else '1')+'\n# helper\n')
                (cwd/delivery.report_name(rid)).write_text(json.dumps({'items':[{'id':i['id'],'status':'met','evidence':'tests/test_value.py'} for i in items]}));return 0,'Completed'
            res=run_job(cfg,spec,work,runner)
        self.assertEqual(res.status,'done');self.assertEqual(len(calls),2);self.assertGreater(len(calls[1]),len(calls[0]));self.assertIn(task,calls[1]);self.assertTrue(spec['context_expanded']);self.assertLessEqual(len(spec['context']),6000)

    def test_recent_decline_withdraws_only_learned_preference_and_does_not_extend_on_refresh(self):
        cfg=config.load()
        for i in range(25):
            rid=f'20261111-0120{i:02d}-abcd';work=cfg.jobs_root/rid;work.mkdir(parents=True)
            good=i<23
            row={'id':rid,'task':'fix a bug','level':'small','updated_at':time.time()-100+i,'checks_passed':good,'runs':[{'agent':'claude','model':'sonnet','effort':'low','exit':0,'seconds':10,'checks_failed':not good,'verified':good}]}
            (work/'metrics.json').write_text(json.dumps(row))
        d=learning.refresh(cfg);r=d['stats'][0];self.assertGreater(r['success_rate'],.8);self.assertFalse(r['eligible']);self.assertIn('suspended_until',r)
        until=r['suspended_until'];self.assertEqual(learning.refresh(cfg)['stats'][0]['suspended_until'],until)
        choices=[('codex','fast'),('claude','sonnet')]
        self.assertEqual(learning.rank(cfg,{'task':'fix a bug','level':'small'},choices)[0],choices)
        self.assertIn('Manual',learning.rank(cfg,{'task':'fix a bug','level':'small','prefer':'claude'},choices)[1])
        with patch('time.time',return_value=time.time()+8*86400):self.assertTrue(learning.refresh(cfg)['stats'][0]['eligible'])


class DeliveryApiTests(GuiTestCase):
    def test_routes_are_authenticated_and_plan_is_local(self):
        for path in ('/api/task-queue','/api/delivery/settings','/api/work-history?q=queue'):
            self.assertEqual(self.req('GET',path,token=False)[0],401)
            self.assertEqual(self.req('GET',path)[0],200)
        status,value=self.req('POST','/api/delivery/plan',{'text':'Add a helper. Preserve behavior.'})
        self.assertEqual(status,200);self.assertEqual(len(value['items']),2);self.assertEqual(self.spawned,[])
        self.assertEqual(self.req('POST','/api/task-queue',{'id':'../../x','priority':0,'dependencies':[]})[0],400)
        self.assertEqual(self.req('GET','/delivery.js')[0],200)
