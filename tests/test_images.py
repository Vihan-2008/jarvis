"""Image transport tests: fixed tiny fixture and fake agents, no screen or inference."""
import base64
import json
from pathlib import Path
from jcc import config,documents,image_inputs,sessions
from jcc.jobrunner import run_job
from jcc.jobs import JobLauncher
from jcc.vault import Vault,parse_frontmatter
from tests.helpers import EngineTestCase
from tests.test_projects import make_repo,overrides
from tests.test_gui import GuiTestCase

PNG='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a7TQAAAAASUVORK5CYII='


class ImageTests(EngineTestCase):
    def image(self,cfg):return documents.extract('sample.png',PNG,cfg)

    def test_images_are_local_hash_checked_and_not_text_or_vault_data(self):
        cfg=config.load();result=self.image(cfg);self.assertEqual((result['width'],result['height']),(1,1));self.assertNotIn('text',result)
        paths=image_inputs.validate(cfg,[result['image_id']]);self.assertEqual(len(paths),1);self.assertFalse((cfg.vault/'image-inputs').exists())
        paths[0].write_bytes(b'changed')
        with self.assertRaises(ValueError):image_inputs.validate(cfg,[result['image_id']])
        with self.assertRaises(ValueError):image_inputs.validate(cfg,['../../credentials.json'])

    def test_codex_and_claude_receive_only_scoped_image_paths(self):
        for provider in ('codex','claude'):
            cfg=config.load(overrides(make_repo(self.tmp/provider),levels=(provider,)));result=self.image(cfg);rid='20261111-040000-'+('abcd' if provider=='codex' else 'abce');work=cfg.jobs_root/rid;work.mkdir(parents=True);calls=[]
            def runner(argv,cwd,env,timeout):calls.append(argv);(cwd/'RESULT.md').write_text('Image answer');return 0,'done'
            spec={'id':rid,'kind':'chat','task':'Describe this uploaded image','project':None,'vault':str(cfg.vault),'image_ids':[result['image_id']]}
            outcome=run_job(cfg,spec,work,runner);self.assertEqual(outcome.status,'done',outcome.log);self.assertEqual(len(calls),1)
            image=work/'image-inputs'/result['image_id'];self.assertTrue(image.exists())
            joined=' '.join(calls[0]);self.assertIn(str(image),joined)
            if provider=='codex':self.assertIn('--image',calls[0]);self.assertIn('--',calls[0])
            else:self.assertIn('Read(',joined);self.assertIn('image-inputs',joined)
            self.assertNotIn(PNG,joined)

    def test_image_identity_changes_invalidate_a_reused_session(self):
        first={'context':'Same draft','image_ids':['a.png']};second={'context':'Same draft','image_ids':['b.png']}
        self.assertNotEqual(sessions.reference_hash(first),sessions.reference_hash(second))

    def test_queued_jobs_preserve_image_references_without_binary_archive(self):
        cfg=config.load(overrides(make_repo(self.tmp)));result=self.image(cfg)
        from dataclasses import replace
        for name,agent in list(cfg.agents.items()):cfg.agents[name]=replace(agent,enabled=False)
        rid='20261111-040001-abcd';outcome=JobLauncher(cfg,Vault(cfg.vault),spawner=lambda *a:None).launch(rid,'chat','Describe image','none',image_ids=[result['image_id']])
        self.assertEqual(outcome.status,'queued');text=(cfg.vault/'Jobs'/(rid+'.md')).read_text();fm,_=parse_frontmatter(text);self.assertEqual(fm['image_ids'],[result['image_id']]);self.assertNotIn(PNG,text)


class ImageApiTests(GuiTestCase):
    def test_followups_keep_image_context_and_new_topic_clears_it(self):
        _,image=self.req('POST','/api/attachments/extract',{'name':'sample.png','base64':PNG})
        _,chat=self.req('POST','/api/chats',{'title':'Image discussion'})
        status,first=self.req('POST','/api/chat/send',{'id':chat['id'],'text':'Describe the image','mode':'chat','uploads':[image]});self.assertEqual(status,200,first)
        status,second=self.req('POST','/api/chat/send',{'id':chat['id'],'text':'Explain the same diagram further','mode':'chat'});self.assertEqual(status,200,second)
        latest=next(m for m in reversed(second['messages']) if m['role']=='user');self.assertEqual(latest['image_ids'],[image['image_id']])
        status,third=self.req('POST','/api/chat/send',{'id':chat['id'],'text':'New topic: explain a loop','mode':'chat'});self.assertEqual(status,200,third)
        latest=next(m for m in reversed(third['messages']) if m['role']=='user');self.assertEqual(latest['image_ids'],[])

    def test_upload_and_dry_run_keep_image_local_until_send(self):
        status,result=self.req('POST','/api/attachments/extract',{'name':'sample.png','base64':PNG});self.assertEqual(status,200,result)
        status,plan=self.req('POST','/api/dry-run',{'text':'Describe this image','mode':'chat','uploads':[result]});self.assertEqual(status,200,plan);self.assertIn('Image token usage',plan['context']['text']);self.assertEqual(self.spawned,[])
        self.assertEqual(self.req('POST','/api/attachments/extract',{'name':'bad.png','base64':base64.b64encode(b'not png').decode()})[0],400)
