"""Deterministic orchestration regression cases; never call real AI providers."""
import hashlib
import ast
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from jcc.jobs import scrub_env
from jcc.lock import InstanceLock
from jcc.redact import redact
from jcc.vault import atomic_write

CASES={
 'Task size routing':'tests.test_projects.TestAgentSelection.test_levels',
 'Checked branch completion':'tests.test_projects.ProjectJobTest.test_passing_change_is_merged_and_cleaned_up',
 'Quota fallback':'tests.test_projects.ProjectJobTest.test_usage_limit_switches_agent_and_sets_cooldown',
 'Dirty checkout protection':'tests.test_projects.ProjectJobTest.test_dirty_checkout_is_not_merged_into',
 'Acceptance coverage':'tests.test_delivery.DeliveryTests.test_missing_acceptance_waits_even_when_tests_pass',
 'Context budgets':'tests.test_delivery.PlanningTests.test_adaptive_context_preserves_required_sources_and_expands_within_hard_cap',
 'Memory privacy':'tests.test_delivery.PlanningTests.test_work_history_keeps_sources_and_excludes_private_archives',
 'Queue dependencies':'tests.test_delivery.PlanningTests.test_priorities_dependencies_and_cycle_protection',
 'Crash recovery':'tests.test_horizon.ReliabilityTests.test_recovery_recognizes_merge_before_missing_receipt_and_never_replays',
 'Full validation gate':'tests.test_reliability.ValidationTests.test_focused_success_still_runs_full_suite',
 'Project preferences':'tests.test_reliability.PolicyTests.test_preferences_add_checks_and_cannot_enable_merge',
 'Dry run isolation':'tests.test_reliability.PreviewTests.test_preview_creates_no_jobs_or_agent_calls',
 'Budget preservation':'tests.test_master.BudgetTests.test_task_budget_stops_repairs_and_preserves_work',
 'Private mirror revocation':'tests.test_master.PrivacyTests.test_private_source_revokes_mirrored_chat_and_cloud_context',
 'Settings restoration':'tests.test_master.RestoreTests.test_restore_roundtrip_checksums_and_credentials_stay_out',
 'Chat branch isolation':'tests.test_master.LibraryTests.test_branch_does_not_copy_live_job_handles_or_change_original',
 'Fresh reference sessions':'tests.test_master.ContextTests.test_changed_references_reset_session_and_original_task_survives',
 'Document parser safety':'tests.test_master.DocumentTests.test_binary_and_xml_entities_are_rejected',
 'Scoped image transport':'tests.test_images.ImageTests.test_codex_and_claude_receive_only_scoped_image_paths',
 'Everyday interface delivery':'tests.test_everyday.EverydayApiTests.test_everyday_assets_are_served_and_apis_stay_authenticated'}


NOT_HERE = ("This copy of JARVIS was installed without its test files, so these checks are not run here. They are run, with "
            "every other test, on every change before a release is made.")


def available(root=None) -> bool:
    """Whether this copy has the test files the cases are taken from (a development copy has; an installed one has not)."""
    return (Path(root or Path(__file__).resolve().parents[1]) / 'tests' / '__init__.py').is_file()


def _not_here(result: dict) -> dict:
    return {'status': 'not available', 'reason': NOT_HERE, 'cases': [], 'expected_cases': len(CASES),
            'scope': 'Fixed orchestration regressions using fake agents and temporary repositories. They need the test files.'}


def fingerprint():
    root=Path(__file__).resolve().parents[1];digest=hashlib.sha256();latest=0
    for folder in ('jcc','tests'):
        for path in sorted((root/folder).rglob('*')):
            if path.suffix not in ('.py','.js','.html','.css') or '__pycache__' in path.parts:continue
            digest.update(path.relative_to(root).as_posix().encode());digest.update(path.read_bytes());latest=max(latest,path.stat().st_mtime)
    return digest.hexdigest(),latest


def status(cfg):
    path=cfg.state_dir/'evaluations.json'
    result=json.loads(path.read_text('utf-8')) if path.exists() else {'status':'not run','cases':[]}
    if not available():
        # (A copy without its test files, or a result written by one: every case "failed" only because its file was missing.
        # Two copies of JARVIS on one computer share this record.)
        return _not_here(result)
    catalog=CASES
    try:
        tree=ast.parse(Path(__file__).read_text('utf-8'))
        catalog=next(ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CASES' for t in node.targets))
    except (OSError,ValueError,SyntaxError,StopIteration):catalog={}
    result['expected_cases']=len(catalog)
    if result.get('build'):result['current_build']=result['build']==fingerprint()[0]
    if result.get('status')=='passed' and (len(result.get('cases',[]))!=len(catalog) or {r.get('name') for r in result.get('cases',[])}!=set(catalog)):
        result['status']='outdated';result['current_build']=False
    result['scope']='Fixed orchestration regressions using fake agents and temporary repositories. This does not measure live model quality or remaining subscription usage.'
    return result


def run(cfg):
    if not available():
        return status(cfg)
    lock=InstanceLock(cfg.state_dir/'evaluations.lock')
    if not lock.acquire():return status(cfg)
    path=cfg.state_dir/'evaluations.json';root=Path(__file__).resolve().parents[1]
    build,_=fingerprint();report={'status':'checking','at':time.time(),'build':build,'cases':[]};atomic_write(path,json.dumps(report))
    executable=str(Path(sys.executable).with_name('python.exe')) if Path(sys.executable).name.lower()=='pythonw.exe' else sys.executable
    try:
        env=scrub_env(dict(os.environ));env.update({'JCC_NO_CREDMAN':'1','PYTHONPATH':str(root),'PYTHONDONTWRITEBYTECODE':'1'})
        deadline=time.monotonic()+180
        for label,case in CASES.items():
            start=time.monotonic()
            try:
                remaining=deadline-start
                if remaining<=0:raise subprocess.TimeoutExpired('evaluation budget',180)
                result=subprocess.run([executable,'-m','unittest',case,'-q'],cwd=root,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',stdin=subprocess.DEVNULL,timeout=min(30,remaining),creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                row={'name':label,'passed':result.returncode==0,'seconds':round(time.monotonic()-start,2)}
                if result.returncode:row['error']=redact((result.stderr or result.stdout)[-1000:])
            except (OSError,subprocess.TimeoutExpired) as error:row={'name':label,'passed':False,'error':type(error).__name__}
            report['cases'].append(row);atomic_write(path,json.dumps(report))
        report['status']='passed' if all(c['passed'] for c in report['cases']) else 'failed'
    except Exception as error:
        report.update({'status':'failed','error':redact(str(error))[:300]})
    finally:
        report['finished_at']=time.time();atomic_write(path,json.dumps(report));lock.release()
    return status(cfg)


def after_update(cfg):
    if not available():
        return status(cfg)
    build,latest=fingerprint();previous=status(cfg)
    if previous.get('build')==build and (previous['status'] not in ('checking','outdated') or previous['status']=='checking' and time.time()-previous.get('at',0)<300):return previous
    if time.time()-latest<15:return previous
    return run(cfg)
