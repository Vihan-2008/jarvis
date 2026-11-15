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


    def test_improve_message_writes_a_full_brief_for_something_to_build(self):
        cfg = config.load()
        seen = {}

        def agent(cfg_, spec, work, *a, **k):
            seen.update(spec)
            (work / 'RESULT.md').write_text('Build a four-player party game for the browser. ' + 'Section. ' * 900, 'utf-8')
            return JobResult(status='done', agent='claude', model='sonnet')
        with patch.object(prompt_master, 'run_job', agent):
            got = prompt_master.refine(cfg, 'make a party game my friends can join from their phones ' + 'x' * 2500)
        self.assertGreater(len(got['prompt']), 6000, 'a full brief is not cut to a few lines')
        brief = seen['task']
        for part in ('The defining experience', 'Build and verify that entire flow', 'hardest end-to-end test', 'remaining checks',
                     'Work autonomously through implementation, testing, and fixes. The deliverable is', 'short, precise prompt'):
            self.assertIn(part, brief)
        self.assertIn('make a party game my friends can join', brief, 'the rough message itself, all of it')
        self.assertEqual((seen['level'], seen['effort']), ('medium', 'medium'))
        with self.assertRaisesRegex(ValueError, 'up to 8000'):
            prompt_master.refine(cfg, 'y' * 8001)

    def test_what_the_ai_wrote_reads_as_it_meant_it(self):
        self.assertEqual(prompt_master.readable("\ufeffBuild it."), "Build it.")
        garbled = "Support 1\u20136 players \u2014 calm.".encode("utf-8").decode("cp1252")
        self.assertEqual(prompt_master.readable(garbled), "Support 1\u20136 players \u2014 calm.")
        self.assertEqual(prompt_master.readable("Caf\u00e9 \u2014 fine as it is"), "Caf\u00e9 \u2014 fine as it is")

    def test_a_copy_whose_data_was_moved_keeps_its_jobs_and_projects_with_it(self):
        import os
        quiet = {k: v for k, v in os.environ.items() if k not in ('JCC_JOBS_ROOT', 'JCC_STATE_DIR', 'JCC_PROJECTS_ROOT')}
        with patch.dict(os.environ, quiet, clear=True):
            moved = config.load({'paths': {'state_dir': str(self.tmp / 'second-jarvis')}})
            usual = config.load()
        self.assertEqual(moved.jobs_root, self.tmp / 'second-jarvis' / 'jobs')
        self.assertNotEqual(usual.jobs_root, moved.jobs_root)

    def test_a_concise_style_asks_for_a_short_prompt(self):
        from jcc import prompt_preferences
        cfg = config.load()
        prompt_preferences.configure(cfg, {'style': 'concise', 'template': '', 'review_all': True})
        seen = {}

        def agent(cfg_, spec, work, *a, **k):
            seen.update(spec)
            (work / 'RESULT.md').write_text('Add a dark mode switch to settings.', 'utf-8')
            return JobResult(status='done', agent='claude', model='sonnet')
        with patch.object(prompt_master, 'run_job', agent):
            prompt_master.refine(cfg, 'dark mode')
        self.assertIn('never a long brief', seen['task'])
        self.assertEqual(prompt_preferences.DEFAULTS['style'], 'detailed')


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
