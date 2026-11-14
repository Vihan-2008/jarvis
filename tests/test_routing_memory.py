import json
from unittest.mock import patch
from jcc import config, routing, models, cloud_memory, prompt_master
from jcc.jobrunner import JobResult
from jcc.vault import parse_frontmatter
from tests.helpers import EngineTestCase
from tests.test_gui import GuiTestCase


class PreferenceTests(EngineTestCase):
    def test_custom_route_then_auto_resets_and_survives_reload(self):
        cfg = config.load()
        original = list(cfg.levels['small'])
        catalog = [{"id": "claude:test", "provider": "claude", "model": "test", "efforts": ["high"]}]
        values = {s: {"model": "auto", "effort": "auto"} for s in ('small', 'medium', 'large')}
        with patch.object(models, 'catalog', return_value=catalog):
            routing.save(cfg, {**values, 'small': {'model': 'claude:test', 'effort': 'high'}})
            self.assertEqual(cfg.levels['small'][0], 'claude')
            self.assertEqual(config.load().agents['claude'].models['small'], 'test')
            routing.save(cfg, values)
        self.assertEqual(cfg.levels['small'], original)
        self.assertEqual(config.load().levels['small'], original)
        self.assertEqual(routing.choices(cfg)['small']['model'], 'auto')

    def test_prompt_refinement_limits_never_enqueue_blank_work(self):
        cfg = config.load()
        with patch.object(prompt_master, 'run_job', return_value=JobResult(status='queued')):
            with self.assertRaisesRegex(ValueError, 'draft is unchanged'):
                prompt_master.refine(cfg, 'make a useful calculator')
        notes = list((self.vault / 'Jobs').glob('*.md'))
        self.assertEqual(len(notes), 1)
        fm, _ = parse_frontmatter(notes[0].read_text('utf-8'))
        self.assertEqual(fm['status'], 'failed')
        self.assertEqual(fm['kind'], 'rewrite')


class CloudMemoryTests(EngineTestCase):
    def test_sync_deduplicates_and_revokes_private_notes(self):
        cfg = config.load()
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state/'cloud-memory.json').write_text(json.dumps({'enabled': True, 'endpoint': 'https://example.supabase.co/functions/v1/jarvis-brain'}))
        self.note('Notes/Visible.md', '# Visible\n\n' + 'context ' * 400)
        self.note('Private/Secret.md', 'never upload')
        self.note('Conversations/Imported/Claude/duplicate.md', 'duplicate')
        calls = []
        def post(endpoint, key, body):
            calls.append(body)
            return {'ok': True}
        with patch.object(cloud_memory.secrets, 'get', return_value='test-key'):
            status = cloud_memory.sync(cfg, post)
            self.assertEqual(status['status'], 'synced')
            self.assertEqual(status['indexed_notes'], 1)
            self.assertTrue(all(c['path']=='Notes/Visible.md' for c in calls))
            count = len(calls)
            cloud_memory.sync(cfg, post)
            self.assertEqual(len(calls), count)
            self.note('Notes/Visible.md', '---\nprivate: true\n---\nsecret')
            cloud_memory.sync(cfg, post)
            self.assertEqual(calls[-1]['action'], 'forget')

    def test_endpoint_rejects_other_hosts(self):
        cfg = config.load()
        with self.assertRaises(ValueError):
            cloud_memory.configure(cfg, 'https://evil.example/functions/v1/jarvis-brain', 'x'*40)

    def test_appended_history_reuses_unchanged_passages(self):
        cfg = config.load()
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state/'cloud-memory.json').write_text(json.dumps({'enabled': True, 'endpoint': 'https://example.supabase.co/functions/v1/jarvis-brain'}))
        self.note('Notes/Chat.md', 'a'*2400)
        calls=[]
        def post(endpoint,key,body):
            calls.append(body)
            return {'ok':True}
        with patch.object(cloud_memory.secrets,'get',return_value='test-key'):
            cloud_memory.sync(cfg,post)
            calls.clear()
            self.note('Notes/Chat.md','a'*2400+'b'*500)
            cloud_memory.sync(cfg,post)
        ordinals=[c['chunks'][0]['ordinal'] for c in calls if c.get('chunks')]
        self.assertEqual(ordinals,[2])


class CloudApiTests(GuiTestCase):
    def test_pairing_is_authenticated_and_secrets_not_in_state(self):
        self.assertEqual(self.req('POST','/api/cloud',{'action':'pairing'},token=False)[0],401)
        with patch.object(cloud_memory,'pairing',return_value={'env':'test-secret','query_key':'test-query'}):
            self.assertEqual(self.req('POST','/api/cloud',{'action':'pairing'})[1]['query_key'],'test-query')
            self.assertNotIn('test-secret',json.dumps(self.req('GET','/api/state')[1]))
