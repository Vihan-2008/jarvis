"""Reliability controls use temporary projects and never a real model."""
import io
import json
import os
import sys
import time
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from jcc import config,delivery,evaluations,handoffs,planning,project_policy,projects,validation
from jcc.jobrunner import run_job
from jcc.vault import render_note
from tests.helpers import EngineTestCase
from tests.test_projects import make_repo,overrides
from tests.test_gui import GuiTestCase


class PolicyTests(EngineTestCase):
    def test_preferences_add_checks_and_cannot_enable_merge(self):
        repo=make_repo(self.tmp);cfg=config.load(overrides(repo,auto_merge=False))
        project_policy.configure(cfg,'trading',{'conventions':'Use existing patterns.','checks':['compile'],'review':'inherit'})
        effective=project_policy.effective(cfg,cfg.projects['trading'])
        self.assertFalse(effective.auto_merge);self.assertEqual(effective.checks[0],cfg.projects['trading'].checks[0]);self.assertIn(project_policy.CHECKS['compile'],effective.checks)
        self.assertEqual(effective.no_auto_merge,cfg.projects['trading'].no_auto_merge)
        with self.assertRaises(ValueError):project_policy.configure(cfg,'trading',{'checks':['shell']})
        with self.assertRaises(ValueError):project_policy.configure(cfg,'missing',{})

    def test_project_review_holds_checked_changes_and_conventions_reach_prompt(self):
        repo=make_repo(self.tmp);cfg=config.load(overrides(repo));project_policy.configure(cfg,'trading',{'conventions':'Use existing naming.','review':'always'})
        rid='20261111-020000-abcd';work=cfg.jobs_root/rid;work.mkdir(parents=True)
        spec={'id':rid,'task':'Add a helper function','kind':'job','vault':str(cfg.vault),'project':'trading'};seen=[]
        def runner(argv,cwd,env,timeout):
            seen.append(' '.join(argv));(cwd/'src/pkg/__init__.py').write_text('VALUE = 1\n# helper\n');return 0,'done'
        result=run_job(cfg,spec,work,runner)
        self.assertFalse(result.merged);self.assertEqual(result.status,'needs_approval');self.assertIn('Use existing naming.',seen[0])
        self.assertEqual((repo/'src/pkg/__init__.py').read_text(),'VALUE = 1\n')

    def test_second_opinion_policy_applies_to_medium_tasks(self):
        repo=make_repo(self.tmp);cfg=config.load(overrides(repo));project_policy.configure(cfg,'trading',{'review':'second_opinion'})
        rid='20261111-020001-abcd';work=cfg.jobs_root/rid;work.mkdir(parents=True);items=delivery.criteria('Add a helper function')
        spec={'id':rid,'task':'Add a helper function','kind':'job','level':'medium','vault':str(cfg.vault),'project':'trading','delivery_version':1,'acceptance':items};calls=[]
        def runner(argv,cwd,env,timeout):
            calls.append(argv)
            if any(str(a).startswith('Review only the supplied') for a in argv):return 0,json.dumps({'status':'clear','findings':[]})
            (cwd/'src/pkg/__init__.py').write_text('VALUE = 1\n# helper\n');(cwd/delivery.report_name(rid)).write_text(json.dumps({'items':[{'id':'A1','status':'met','evidence':'src/pkg/__init__.py'}]}));return 0,'done'
        result=run_job(cfg,spec,work,runner)
        self.assertEqual(len(calls),2);self.assertEqual(result.status,'done',result.merge_note);self.assertTrue(result.merged)


class ValidationTests(EngineTestCase):
    def graph(self):
        repo=make_repo(self.tmp)
        (repo/'src/pkg/a.py').write_text('VALUE=1\n');(repo/'src/pkg/b.py').write_text('VALUE=2\n')
        (repo/'tests/test_a.py').write_text('import unittest\nfrom pkg import a\nclass T(unittest.TestCase):\n def test_a(self): self.assertEqual(a.VALUE,1)\n')
        (repo/'tests/test_b.py').write_text('import unittest\nfrom pkg import b\nclass T(unittest.TestCase):\n def test_b(self): self.assertEqual(b.VALUE,2)\n')
        # Remove broad package import test so the graph can show a useful independent subset.
        (repo/'tests/test_value.py').unlink();projects.git(['add','-A'],repo);projects.git([*projects.GIT_ID,'commit','-qm','tests'],repo)
        cfg=config.load(overrides(repo));return repo,cfg.projects['trading']

    def test_transitive_dependency_subset_and_configuration_fallback(self):
        repo,project=self.graph();(repo/'src/pkg/a.py').write_text('VALUE=1\n# edited\n')
        checks,reason=validation.focused(project,repo);self.assertTrue(checks,reason);self.assertIn('tests.test_a',checks[0]);self.assertNotIn('tests.test_b',checks[0])
        (repo/'pyproject.toml').write_text('[tool.example]\n');self.assertEqual(validation.focused(project,repo)[0],[])

    def test_focused_success_still_runs_full_suite(self):
        repo,project=self.graph();(repo/'src/pkg/a.py').write_text('VALUE=1\n# edited\n');work=self.tmp/'work';work.mkdir();calls=[]
        def checks(p,*args,**kwargs):calls.append(p.checks);return [projects.CheckResult('tests',True,'ok')]
        with patch('jcc.validation.projects.run_checks',side_effect=checks):result=validation.run(project,repo,{},10,work,True)
        self.assertTrue(all(c.ok for c in result));self.assertEqual(len(calls),2);self.assertEqual(calls[-1],project.checks)
        self.assertTrue(json.loads((work/'validation.json').read_text())['full_ran'])

    def test_focused_failure_saves_full_suite_until_repair(self):
        repo,project=self.graph();(repo/'src/pkg/a.py').write_text('VALUE=3\n');work=self.tmp/'work';work.mkdir()
        with patch('jcc.validation.projects.run_checks',return_value=[projects.CheckResult('focused',False,'failure')]) as checks:result=validation.run(project,repo,{},10,work,True)
        self.assertEqual(checks.call_count,1);self.assertFalse(result[0].ok);self.assertFalse(json.loads((work/'validation.json').read_text())['full_ran'])

    def test_dynamic_import_falls_back_and_real_full_failure_blocks(self):
        repo,project=self.graph();(repo/'src/pkg/a.py').write_text('VALUE=1\n__import__("math")\n');self.assertEqual(validation.focused(project,repo)[0],[])
        (repo/'src/pkg/a.py').write_text('VALUE=1\n# edited\n');work=self.tmp/'work';work.mkdir()
        with patch('jcc.validation.projects.run_checks',side_effect=[[projects.CheckResult('focused',True,'ok')],[projects.CheckResult('full',False,'regression')]]):result=validation.run(project,repo,{},10,work,True)
        self.assertFalse(result[0].ok);self.assertEqual(result[0].name,'full')

    def test_actual_focused_commands_and_transitive_imports_work(self):
        repo,project=self.graph();(repo/'src/pkg/bridge.py').write_text('from pkg import a\n')
        (repo/'tests/test_a.py').write_text('import unittest\nfrom pkg import bridge\nclass T(unittest.TestCase):\n def test_a(self): self.assertEqual(bridge.a.VALUE,1)\n')
        projects.git(['add','-A'],repo);projects.git([*projects.GIT_ID,'commit','-qm','transitive'],repo)
        (repo/'src/pkg/a.py').write_text('VALUE=1\n# edited\n');work=self.tmp/'work';work.mkdir()
        result=validation.run(project,repo,dict(os.environ),20,work,True)
        self.assertTrue(all(c.ok for c in result),str(result));report=json.loads((work/'validation.json').read_text());self.assertEqual(report['strategy'],'focused_then_full');self.assertTrue(report['full_passed'])


class PreviewTests(EngineTestCase):
    def test_preview_creates_no_jobs_or_agent_calls(self):
        repo=make_repo(self.tmp);cfg=config.load(overrides(repo));before=projects.git(['status','--porcelain'],repo)
        with patch('jcc.jobs.detached_spawn',side_effect=AssertionError('must not spawn')):d=planning.preview(cfg,'Add a helper function','trading','code')
        self.assertTrue(d['dry_run']);self.assertEqual(d['project_key'],'trading');self.assertTrue(d['required_checks']);self.assertEqual(d['kind'],'job')
        self.assertFalse(cfg.jobs_root.exists());self.assertFalse((cfg.vault/'Jobs').exists());self.assertEqual(before,projects.git(['status','--porcelain'],repo))
        self.assertLessEqual(d['context']['characters'],d['context']['hard_budget'])

    def test_blocked_and_chat_routes_and_invalid_model(self):
        repo=make_repo(self.tmp);cfg=config.load(overrides(repo))
        self.assertTrue(planning.preview(cfg,'Deploy the trading bot','trading','code')['blocked_by'])
        self.assertEqual(planning.preview(cfg,'How does this helper work?','trading')['kind'],'chat')
        with self.assertRaises(ValueError):planning.preview(cfg,'Add helper','trading',manual_model='fake:model')
        self.assertIsNone(planning.preview(cfg,'/status','none')['model'])


class HandoffTests(EngineTestCase):
    def test_export_is_scoped_private_safe_and_download_validated(self):
        repo=make_repo(self.tmp);cfg=config.load(overrides(repo));self.note('Projects/trading/Memory.md','# Decisions\n\nUse existing patterns.')
        rid='20261111-020002-abcd';self.note('Jobs/'+rid+'.md',render_note({'project_key':'trading','status':'paused','task':'Add helper'},'raw transcript should not export'))
        self.note('Jobs/20261111-020003-abcd.md',render_note({'project_key':'other','task':'OTHER SECRET'},'other'))
        d=handoffs.export(cfg,'trading');data=handoffs.download(cfg,d['filename'])
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            text=archive.read('HANDOFF.md').decode();self.assertIn('Use existing patterns.',text);self.assertIn('Open:',text);self.assertNotIn('raw transcript',text);self.assertNotIn('OTHER SECRET',str(archive.read('manifest.json')))
            self.assertTrue(all('..' not in n and not n.startswith('/') for n in archive.namelist()))
        self.note('Projects/trading/Memory.md','---\nprivate: true\n---\nHIDDEN PERSONAL DETAIL')
        d=handoffs.export(cfg,'trading')
        with zipfile.ZipFile(io.BytesIO(handoffs.download(cfg,d['filename']))) as archive:self.assertNotIn('HIDDEN PERSONAL DETAIL',archive.read('HANDOFF.md').decode())
        with self.assertRaises(ValueError):handoffs.download(cfg,'../../auth.json')
        with self.assertRaises(ValueError):handoffs.export(cfg,'other')


class EvaluationTests(EngineTestCase):
    def test_old_in_memory_catalog_cannot_certify_new_source(self):
        cfg=config.load();self.state.mkdir(parents=True,exist_ok=True)
        (self.state/'evaluations.json').write_text(json.dumps({'build':'current','status':'passed','cases':[{'name':'Old runtime case','passed':True}]}))
        with patch.dict(evaluations.CASES,{'Old runtime case':'old.test'},clear=True),patch('jcc.evaluations.fingerprint',return_value=('current',0)):
            report=evaluations.status(cfg);self.assertEqual(report['status'],'outdated');self.assertGreater(report['expected_cases'],1)

    def test_older_case_catalog_cannot_certify_the_current_build(self):
        cfg=config.load();self.state.mkdir(parents=True,exist_ok=True)
        (self.state/'evaluations.json').write_text(json.dumps({'build':'current','status':'passed','cases':[{'name':'Only an older case','passed':True}]}))
        with patch('jcc.evaluations.fingerprint',return_value=('current',0)):
            report=evaluations.status(cfg)
            self.assertEqual(report['status'],'outdated');self.assertFalse(report['current_build'])
            with patch('jcc.evaluations.run') as run:evaluations.after_update(cfg);run.assert_called_once()

    def test_fixed_cases_run_isolated_and_failure_is_reported(self):
        cfg=config.load();fake=type('Result',(),{'returncode':1,'stderr':'regression','stdout':''})
        with patch.dict(evaluations.CASES,{'Only fixed test':'tests.test_projects.TestAgentSelection.test_levels'},clear=True),patch('jcc.evaluations.subprocess.run',return_value=fake) as run:
            result=evaluations.run(cfg)
        self.assertEqual(result['status'],'failed');self.assertFalse(result['cases'][0]['passed']);argv=run.call_args.args[0];self.assertEqual(argv[1:3],['-m','unittest']);self.assertEqual(run.call_args.kwargs['env']['JCC_NO_CREDMAN'],'1');self.assertIn('fake agents',result['scope'])

    def test_after_update_runs_once_per_stable_build(self):
        cfg=config.load();self.state.mkdir(parents=True,exist_ok=True);(self.state/'evaluations.json').write_text(json.dumps({'build':'current','status':'passed','cases':[{'name':name,'passed':True} for name in evaluations.CASES]}))
        with patch('jcc.evaluations.fingerprint',return_value=('current',0)),patch('jcc.evaluations.run') as run:evaluations.after_update(cfg);run.assert_not_called()
        with patch('jcc.evaluations.fingerprint',return_value=('new',time.time())),patch('jcc.evaluations.run') as run:evaluations.after_update(cfg);run.assert_not_called()
        with patch('jcc.evaluations.fingerprint',return_value=('new',0)),patch('jcc.evaluations.run') as run:evaluations.after_update(cfg);run.assert_called_once()


class ReliabilityApiTests(GuiTestCase):
    def test_new_routes_require_auth_and_preview_has_no_side_effects(self):
        for route in ('/api/dry-run','/api/project/preferences','/api/evaluations','/api/handoff'):
            self.assertEqual(self.req('POST',route,{},token=False)[0],401)
        self.assertEqual(self.req('GET','/api/evaluations',token=False)[0],401)
        before=self.state.cfg.jobs_root.exists();status,d=self.req('POST','/api/dry-run',{'text':'Explain a helper','mode':'chat','project':'none'})
        self.assertEqual(status,200,d);self.assertTrue(d['dry_run']);self.assertEqual(self.spawned,[]);self.assertEqual(self.state.cfg.jobs_root.exists(),before)
        self.assertEqual(self.req('POST','/api/handoff',{'project':'missing'})[0],400)
        self.assertEqual(self.req('GET','/api/handoff/download?name=../../auth.json')[0],400)

    def test_project_preferences_and_export_api_roundtrip(self):
        repo=make_repo(self.tmp);self.state.cfg=config.load(overrides(repo))
        status,d=self.req('POST','/api/project/preferences',{'project':'trading','preferences':{'review':'always','checks':['compile'],'conventions':'Follow existing names.'}})
        self.assertEqual(status,200,d);self.assertFalse(d['auto_merge'])
        status,d=self.req('GET','/api/project/preferences?project=trading');self.assertEqual(status,200);self.assertEqual(d['preferences']['review'],'always')
        status,d=self.req('POST','/api/handoff',{'project':'trading'});self.assertEqual(status,200,d);self.assertTrue((self.state.cfg.state_dir/'exports'/d['filename']).is_file())
