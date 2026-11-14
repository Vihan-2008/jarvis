"""Master-roadmap regressions: isolated files, fake agents and localhost only."""
import base64
import io
import json
import os
import time
import zipfile
from pathlib import Path
from unittest.mock import patch
from jcc import budgets,config,documents,governor,history,library,operations,planning,privacy,project_policy,provenance,restorepoints,sessions,task_queue,retrieval,learning,release_health
from jcc.chats import Chats
from jcc.jobrunner import run_job
from jcc.jobs import JobLauncher
from jcc.vault import Vault,render_note
from tests.helpers import EngineTestCase
from tests.test_gui import GuiTestCase
from tests.test_projects import make_repo,overrides


class BudgetTests(EngineTestCase):
    def metric(self,cfg,rid,project='trading',seconds=60,tokens=100):
        path=cfg.jobs_root/rid/'metrics.json';path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps({'id':rid,'project':project,'updated_at':time.time(),'seconds':seconds,'runs':[{'input_tokens':tokens,'output_tokens':10}]}))

    def test_unknown_usage_is_not_reported_as_zero_and_projects_are_separate(self):
        cfg=config.load(overrides(make_repo(self.tmp)));self.metric(cfg,'a',tokens=None);self.metric(cfg,'b','other')
        row=budgets.usage(cfg,'trading');self.assertEqual(row['unmeasured_attempts'],1);self.assertEqual(row['measured_tokens'],0);self.assertEqual(row['jobs'],1)
        budgets.configure(cfg,{**budgets.DEFAULTS,'projects':{'trading':{'daily_seconds':30,'daily_tokens':0}}});self.assertTrue(budgets.reason(cfg,'trading'));self.assertIsNone(budgets.reason(cfg,'other'))

    def test_resumed_job_is_not_double_counted_and_time_is_bounded(self):
        cfg=config.load(overrides(make_repo(self.tmp)));self.metric(cfg,'job',seconds=80)
        budgets.configure(cfg,{**budgets.DEFAULTS,'daily_seconds':100,'reserve_percent':0})
        attempts=[{'seconds':80,'input_tokens':10,'output_tokens':1}]
        self.assertIsNone(budgets.reason(cfg,attempts=attempts,exclude_id='job'));self.assertEqual(budgets.remaining_seconds(cfg,attempts=attempts,exclude_id='job'),20)
        self.assertTrue(budgets.reason(cfg,attempts=attempts))

    def test_exhausted_launch_queues_without_spawning(self):
        cfg=config.load(overrides(make_repo(self.tmp)));self.metric(cfg,'used',seconds=100);budgets.configure(cfg,{**budgets.DEFAULTS,'daily_seconds':50})
        calls=[];result=JobLauncher(cfg,Vault(cfg.vault),spawner=lambda *args:calls.append(args)).launch('20261111-030000-abcd','job','Add a helper function','trading')
        self.assertEqual(result.status,'queued');self.assertEqual(calls,[])

    def test_task_budget_stops_repairs_and_preserves_work(self):
        repo=make_repo(self.tmp);cfg=config.load(overrides(repo));budgets.configure(cfg,{**budgets.DEFAULTS,'task_tokens':100})
        rid='20261111-030001-abcd';work=cfg.jobs_root/rid;work.mkdir(parents=True);calls=[]
        def runner(argv,cwd,env,timeout):
            calls.append(argv);(cwd/'src/pkg/__init__.py').write_text('VALUE=999\n');return 0,json.dumps({'type':'turn.completed','usage':{'input_tokens':110,'output_tokens':20,'cached_input_tokens':0}})
        result=run_job(cfg,{'id':rid,'kind':'job','task':'Fix helper function','vault':str(cfg.vault),'project':'trading','level':'medium'},work,runner)
        self.assertEqual(result.status,'paused',result.log);self.assertEqual(len(calls),1);self.assertTrue((work/'repo/src/pkg/__init__.py').exists());self.assertFalse(result.merged)

    def test_budget_values_are_validated(self):
        cfg=config.load()
        for value in (-1,True,100000001):
            with self.assertRaises(ValueError):budgets.configure(cfg,{**budgets.DEFAULTS,'daily_tokens':value})


class PrivacyTests(EngineTestCase):
    def test_nested_private_and_credentials_are_excluded(self):
        cfg=config.load();self.note('Projects/demo/Private/Secret.md','DO NOT READ');self.note('credentials.json','{}')
        self.assertIsNone(privacy.note(cfg.vault/'Projects/demo/Private/Secret.md',cfg.vault));self.assertFalse(privacy.safe_path(cfg.vault/'credentials.json',cfg.vault))
        self.note('Notes/Hidden.md','---\nprivate: yes\n---\nSENSITIVE');self.assertIsNone(privacy.note(cfg.vault/'Notes/Hidden.md',cfg.vault))
        self.note('Notes/Excluded.md','---\nai_context: exclude\n---\nSENSITIVE');self.assertIsNone(privacy.note(cfg.vault/'Notes/Excluded.md',cfg.vault,explicit=True))

    def test_cloud_and_explicit_link_policies_remain_distinct(self):
        cfg=config.load();self.note('Notes/Local.md','---\ncloud_sync: false\n---\nLocal context')
        self.assertIsNotNone(privacy.note(cfg.vault/'Notes/Local.md',cfg.vault));self.assertIsNone(privacy.note(cfg.vault/'Notes/Local.md',cfg.vault,cloud=True))
        self.note('Notes/History.md','---\nai_context: explicit-links-only\n---\nReference')
        self.assertIsNone(privacy.note(cfg.vault/'Notes/History.md',cfg.vault));self.assertIsNotNone(privacy.note(cfg.vault/'Notes/History.md',cfg.vault,explicit=True))

    def test_private_source_revokes_mirrored_chat_and_cloud_context(self):
        cfg=config.load();self.note('Conversations/Imported/Claude/source.md','# Original source')
        history.mirror_chat(cfg,'Claude','source','Imported',[{'role':'user','content':'sensitive'}],'Conversations/Imported/Claude/source.md')
        chats=Chats(cfg);cid=chats.list()[0]['id'];self.note('Conversations/Imported/Claude/source.md','---\nprivate: true\n---\nPRIVATE BODY')
        with self.assertRaises(ValueError):chats.get(cid)
        self.assertEqual(chats.list(),[]);self.assertIsNone(privacy.note(cfg.vault/'Conversations'/(cid+'.md'),cfg.vault,cloud=True))

    def test_large_conversation_frontmatter_remains_eligible(self):
        cfg=config.load();chat=Chats(cfg).create();chat['messages']=[{'role':'user','content':'a'*20000}];Chats(cfg).save(chat)
        self.assertIsNotNone(privacy.note(cfg.vault/'Conversations'/(chat['id']+'.md'),cfg.vault,cloud=True))


class RestoreTests(EngineTestCase):
    def test_restore_roundtrip_checksums_and_credentials_stay_out(self):
        cfg=config.load();governor.configure(cfg,{**governor.DEFAULTS,'pause_background':True});(cfg.state_dir/'auth.json').write_text('DO NOT EXPORT')
        point=restorepoints.create(cfg);governor.configure(cfg,governor.DEFAULTS);plan=restorepoints.preview(cfg,point['id']);self.assertIn('resources.json',plan['changes'])
        result=restorepoints.apply(cfg,point['id'],plan['version']);self.assertEqual(result['status'],'restored');self.assertTrue(governor.settings(cfg)['pause_background'])
        with zipfile.ZipFile(io.BytesIO(restorepoints.portable(cfg,point['id']))) as archive:self.assertNotIn('auth.json',str(archive.namelist()));self.assertNotIn(b'DO NOT EXPORT',b''.join(archive.read(n) for n in archive.namelist()))

    def test_stale_preview_and_corrupted_snapshot_are_refused(self):
        cfg=config.load();governor.configure(cfg,governor.DEFAULTS);point=restorepoints.create(cfg);plan=restorepoints.preview(cfg,point['id']);governor.configure(cfg,{**governor.DEFAULTS,'pause_background':True})
        with self.assertRaises(ValueError):restorepoints.apply(cfg,point['id'],plan['version'])
        path=cfg.state_dir/'restore-points'/(point['id']+'.json');value=json.loads(path.read_text());value['files']['resources.json']['sha256']='bad';path.write_text(json.dumps(value))
        with self.assertRaises(ValueError):restorepoints.read(cfg,point['id'])

    def test_invalid_old_settings_never_replace_current_settings(self):
        cfg=config.load();governor.configure(cfg,governor.DEFAULTS);point=restorepoints.create(cfg);path=cfg.state_dir/'restore-points'/(point['id']+'.json');value=json.loads(path.read_text());invalid=json.dumps({**governor.DEFAULTS,'retention_days':-100});value['files']['resources.json']={'content':invalid,'sha256':restorepoints.digest(invalid)};path.write_text(json.dumps(value));plan=restorepoints.preview(cfg,point['id'])
        with self.assertRaises(ValueError):restorepoints.apply(cfg,point['id'],plan['version'])
        self.assertEqual(governor.settings(cfg),governor.DEFAULTS)


class LibraryTests(EngineTestCase):
    def test_organization_search_and_saved_views(self):
        cfg=config.load();store=Chats(cfg);chat=store.create('Decision');store.update(chat['id'],message={'role':'user','content':'Use SQLite for the cache'})
        library.organize(cfg,chat['id'],{'folder':'Engineering','tags':['storage'],'pinned':True})
        rows=library.query(cfg,{'q':'SQLite','tag':'storage','pinned':True});self.assertEqual(rows['total'],1);self.assertIn('SQLite',rows['chats'][0]['snippet'])
        library.save_view(cfg,'Storage',{'tag':'storage'});self.assertEqual(library.query(cfg)['views'][0]['name'],'Storage')

    def test_branch_does_not_copy_live_job_handles_or_change_original(self):
        cfg=config.load();store=Chats(cfg);chat=store.create();store.update(chat['id'],message={'role':'user','content':'Original','receipt':'20261111-030002-abcd'});store.update(chat['id'],message={'role':'assistant','content':'Answer','status':'done','receipt':'20261111-030002-abcd'})
        original=store.get(chat['id']);branch=library.branch(cfg,chat['id'],0)
        self.assertNotEqual(branch['id'],chat['id']);self.assertEqual(len(branch['messages']),1);self.assertNotIn('receipt',branch['messages'][0]);self.assertEqual(store.get(chat['id']),original)
        with self.assertRaises(ValueError):library.branch(cfg,chat['id'],-1)


class ContextTests(EngineTestCase):
    def test_changed_references_reset_session_and_original_task_survives(self):
        cfg=config.load();store=Chats(cfg);cid=store.create()['id'];cwd=self.tmp/'session';cwd.mkdir();spec={'id':'20261111-030003-abcd','chat_id':cid,'kind':'chat','task':'Explain the helper','context':'Reference A'}
        sessions.remember(cfg,spec,'codex','model',cwd,{'session_id':'11111111-2222-3333-4444-555555555555'})
        self.assertIsNotNone(sessions.get(cfg,spec,'codex','model',cwd));self.assertIsNone(sessions.get(cfg,{**spec,'context':'Reference B'},'codex','model',cwd));self.assertEqual(spec['task'],'Explain the helper')

    def test_source_versions_are_reference_only_and_private_sources_revoke_access(self):
        cfg=config.load();self.note('Projects/demo/Memory.md','# Decision\nUse SQLite.');provenance.audit(cfg);self.note('Projects/demo/Memory.md','# Decision\nUse SQLite with WAL.');provenance.audit(cfg)
        rows=provenance.versions(cfg,'Projects/demo/Memory');self.assertEqual(len(rows['versions']),2);self.assertEqual((cfg.vault/'Projects/demo/Memory.md').read_text(),'# Decision\nUse SQLite with WAL.')
        self.note('Projects/demo/Memory.md','---\nprivate: true\n---\nPrivate')
        with self.assertRaises(PermissionError):provenance.versions(cfg,'Projects/demo/Memory')

    def test_milestones_cover_original_acceptance_without_starting_jobs(self):
        cfg=config.load();plan=planning.preview(cfg,'Add a helper function. Preserve existing behavior.','none','code')
        covered=[a for m in plan['milestones'] for a in m['requirements']];self.assertEqual(set(covered),{i['id'] for i in plan['acceptance']});self.assertFalse(cfg.jobs_root.exists())


class ResourceTests(EngineTestCase):
    def test_battery_metered_and_foreground_deferral(self):
        cfg=config.load()
        with patch('jcc.governor.power',return_value={'on_battery':True,'percent':20}):self.assertIn('battery',governor.reason(cfg))
        governor.configure(cfg,{**governor.DEFAULTS,'battery_saver':False,'metered_network':True});self.assertTrue(governor.reason(cfg,True));self.assertIsNone(governor.reason(cfg,False))
        self.note('Jobs/20261111-030004-abcd.md',render_note({'status':'running'},'Job'));self.assertIn('foreground',governor.reason(cfg))

    def test_retention_moves_only_expired_handoff_downloads(self):
        cfg=config.load();folder=cfg.state_dir/'exports';folder.mkdir(parents=True);name='handoff-0123456789abcdef.zip';(folder/name).write_bytes(b'test');os.utime(folder/name,(0,0));(folder/'important.txt').write_text('keep')
        self.assertEqual(governor.cleanup(cfg),1);self.assertTrue((cfg.state_dir/'retained-exports'/name).exists());self.assertTrue((folder/'important.txt').exists())


class DocumentTests(EngineTestCase):
    def encoded(self,data):return base64.b64encode(data).decode()
    def test_text_and_docx_are_extracted_without_writing_files(self):
        self.assertEqual(documents.extract('notes.txt',self.encoded(b'Hello'))['text'],'Hello');buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as archive:archive.writestr('word/document.xml','<doc><p>Hello document</p></doc>')
        result=documents.extract('notes.docx',self.encoded(buffer.getvalue()));self.assertIn('Hello document',result['text']);self.assertTrue(result['notes']);self.assertFalse(self.jobs_root.exists())

    def test_binary_and_xml_entities_are_rejected(self):
        with self.assertRaises(ValueError):documents.extract('image.png',self.encoded(b'PNG'))
        with self.assertRaises(ValueError):documents.extract('bad.txt',self.encoded(b'\x00binary'))
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as archive:archive.writestr('word/document.xml','<!DOCTYPE doc [<!ENTITY x "secret">]><doc>&x;</doc>')
        with self.assertRaises(ValueError):documents.extract('bad.docx',self.encoded(buffer.getvalue()))


class ArchiveTests(EngineTestCase):
    def test_repeat_import_is_deduplicated_and_owner_flags_are_preserved(self):
        cfg=config.load();data=json.dumps([{'uuid':'source','name':'History','chat_messages':[{'sender':'human','text':'Hello'}]}]).encode();first=history.import_data(cfg,data,'archive.json');second=history.import_data(cfg,data,'archive.json');self.assertEqual(first['conversations'],1);self.assertTrue(second['deduplicated'])

    def test_chat_metadata_does_not_parse_messages_and_still_rechecks_privacy(self):
        cfg=config.load();store=Chats(cfg);chat=store.create();chat['messages']=[{'role':'user','content':'a'*20000}];store.save(chat)
        with patch.object(Chats,'get',side_effect=AssertionError('Full history should not be loaded')):self.assertEqual(len(store.list()),1)
        path=cfg.vault/'Conversations'/(chat['id']+'.md');stamp=path.stat();text=path.read_text();path.write_text(text.replace('has_local_work: false','private: true\nhas_local_work: false'));os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns));self.assertEqual(store.list(),[])


class RetrievalTests(EngineTestCase):
    def test_cloud_results_are_checked_against_current_private_safe_sources(self):
        cfg=config.load();self.note('Projects/demo/Memory.md','# Memory\nUse SQLite for local decisions.')
        result=retrieval.search(cfg,'local decisions',include_cloud=True,searcher=lambda *args:[{'path':'Projects/demo/Memory.md','content':'Use SQLite for local decisions.'},{'path':'Private/Secret.md','content':'LEAK'}]);self.assertEqual(result['cloud'],'available');self.assertEqual(len(result['results']),1);self.assertEqual(result['filtered_cloud_matches'],1)
        self.note('Projects/demo/Memory.md','---\nprivate: true\n---\nUse SQLite for local decisions.')
        result=retrieval.search(cfg,'local decisions',include_cloud=True,searcher=lambda *args:[{'path':'Projects/demo/Memory.md','content':'Use SQLite for local decisions.'}]);self.assertEqual(result['results'],[])

    def test_stale_cloud_content_is_not_returned_and_cloud_failure_preserves_local(self):
        cfg=config.load();self.note('Projects/demo/Memory.md','# Memory\nUse current SQLite decisions.')
        result=retrieval.search(cfg,'SQLite decisions',include_cloud=True,searcher=lambda *args:[{'path':'Projects/demo/Memory.md','content':'OLD PRIVATE CONTENT'}]);self.assertNotIn('OLD PRIVATE CONTENT',str(result['results']));self.assertEqual(result['filtered_cloud_matches'],1)
        with patch('jcc.retrieval.cloud',side_effect=OSError('offline')):result=retrieval.search(cfg,'SQLite decisions',include_cloud=True)
        self.assertTrue(result['results']);self.assertIn('local results preserved',result['cloud'])


class AdditionalSafetyTests(EngineTestCase):
    def test_current_build_failure_holds_new_coding_jobs(self):
        cfg=config.load(overrides(make_repo(self.tmp)));cfg.state_dir.mkdir(parents=True,exist_ok=True);(cfg.state_dir/'evaluations.json').write_text(json.dumps({'status':'failed','cases':[]}));calls=[]
        result=JobLauncher(cfg,Vault(cfg.vault),spawner=lambda *args:calls.append(args)).launch('20261111-030008-abcd','job','Add a helper function','trading');self.assertEqual(result.status,'queued');self.assertEqual(calls,[])

    def test_deadlines_order_equal_priority_and_can_be_cleared(self):
        cfg=config.load();a='20261111-030009-abcd';b='20261111-030010-abcd'
        for rid in (a,b):self.note('Jobs/'+rid+'.md',render_note({'id':rid,'status':'queued','task':'Task'},'# Task'))
        task_queue.update(cfg,a,0,[],time.time()+1000);task_queue.update(cfg,b,0,[],time.time()+100);self.assertEqual(task_queue.ordered(cfg)[0]['id'],b);task_queue.update(cfg,b,0,[],0);self.assertEqual(task_queue.ordered(cfg)[0]['id'],a)

    def test_hidden_and_credential_attachments_are_rejected(self):
        for name in ('.env','auth.json','credentials.json'):
            with self.assertRaises(ValueError):documents.extract(name,base64.b64encode(b'{}').decode())

    def test_future_settings_schema_is_not_silently_downgraded(self):
        cfg=config.load();cfg.state_dir.mkdir(parents=True,exist_ok=True);(cfg.state_dir/'settings-schema.json').write_text(json.dumps({'schema':999}))
        with self.assertRaises(ValueError):release_health.initialize(cfg)

    def test_old_model_evidence_is_not_automatically_promoted(self):
        cfg=config.load(overrides(make_repo(self.tmp)));cfg.state_dir.mkdir(parents=True,exist_ok=True)
        for index in range(5):
            path=cfg.jobs_root/('old-'+str(index))/'metrics.json';path.parent.mkdir(parents=True);path.write_text(json.dumps({'id':str(index),'task':'Fix a bug','kind':'job','level':'small','updated_at':time.time()-45*86400,'checks_passed':True,'runs':[{'agent':'codex','model':'old','exit':0,'verified':True,'seconds':1}]}))
        result=learning.refresh(cfg);self.assertEqual(result['stats'][0]['tasks'],5);self.assertFalse(result['stats'][0]['eligible']);self.assertGreater(result['stats'][0]['evidence_age_days'],30)


class MasterApiTests(GuiTestCase):
    def test_new_routes_are_authenticated_and_default_controls_are_local(self):
        for route in ('/api/operations','/api/controls','/api/timeline?id=bad','/api/restorepoints/download?id=bad'):
            self.assertEqual(self.req('GET',route,token=False)[0],401)
        for route in ('/api/library','/api/provenance','/api/controls','/api/restorepoints','/api/diagnostics/export','/api/attachments/extract'):
            self.assertEqual(self.req('POST',route,{},token=False)[0],401)
        status,row=self.req('GET','/api/operations');self.assertEqual(status,200,row);self.assertFalse(row['screen_access']['enabled']);self.assertEqual(self.spawned,[])

    def test_settings_back_up_automatically_and_diagnostics_exclude_task_text(self):
        status,d=self.req('POST','/api/controls',{'section':'resources','settings':governor.DEFAULTS});self.assertEqual(status,200,d);self.assertTrue(restorepoints.listing(self.state.cfg))
        status,d=self.req('POST','/api/diagnostics/export',{});self.assertEqual(status,200);self.assertNotIn('tasks',d);self.assertIn('counts',d)
