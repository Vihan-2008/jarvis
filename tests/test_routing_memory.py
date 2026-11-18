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

    def test_a_cloud_that_keeps_refusing_is_asked_less_often_and_a_success_resets_the_wait(self):
        # Each pass reads the whole vault, so a wrong key used to cost that work every half minute, forever.
        self.state.mkdir(parents=True, exist_ok=True)
        passes = iter([{'status': 'error'}] * 3 + [{'status': 'synced'}, {'status': 'error'}])
        waits = []
        def sleep(seconds):
            waits.append(seconds)
            if len(waits) == 5:
                raise KeyboardInterrupt      # the only way out of the worker's endless loop
        with patch.object(cloud_memory, 'sync', lambda cfg, budget: next(passes)), \
                patch.object(cloud_memory.time, 'sleep', sleep), self.assertRaises(KeyboardInterrupt):
            cloud_memory.main()
        self.assertEqual(waits, [30, 60, 120, 300, 30])

    def test_failures_in_a_row_wait_at_most_fifteen_minutes(self):
        waits = [cloud_memory.wait_after({'status': 'error'}, n) for n in range(1, 8)]
        self.assertEqual(waits, [30, 60, 120, 240, 480, 900, 900])
        self.assertEqual(cloud_memory.wait_after({'status': 'error'}, 10**6), 900)

    def test_unsent_notes_keep_the_worker_busy_and_cheap_checks_stay_frequent(self):
        self.assertEqual(cloud_memory.wait_after({'status': 'indexing'}, 0), 5)
        for status in (None, {'status': 'deferred'}):
            self.assertEqual(cloud_memory.wait_after(status, 0), 30)


class CloudApiTests(GuiTestCase):
    def test_pairing_is_authenticated_and_secrets_not_in_state(self):
        self.assertEqual(self.req('POST','/api/cloud',{'action':'pairing'},token=False)[0],401)
        with patch.object(cloud_memory,'pairing',return_value={'env':'test-secret','query_key':'test-query'}):
            self.assertEqual(self.req('POST','/api/cloud',{'action':'pairing'})[1]['query_key'],'test-query')
            self.assertNotIn('test-secret',json.dumps(self.req('GET','/api/state')[1]))


class ImproveMessageFast(EngineTestCase):
    """Improve message asks one model directly (no job): its words stream as they are written; a connected AI service
    answers when Claude cannot; the coding-job route only as a last resort."""

    def test_claude_answers_directly_and_its_words_stream(self):
        cfg = config.load()
        seen = []

        def claude(system, question, heard, timeout=240.0):
            self.assertIn('The defining experience', system)
            self.assertIn('make a party game', question)
            for words in ('Build a party', 'Build a party game.'):
                heard(words)
            return 'Build a party game.'
        with patch.object(prompt_master, '_ask_claude', claude), patch.object(prompt_master, 'run_job') as job:
            got = prompt_master.write(cfg, 'make a party game', heard=seen.append)
        self.assertEqual((got['prompt'], got['agent']), ('Build a party game.', 'claude'))
        self.assertEqual(seen, ['Build a party', 'Build a party game.'])
        job.assert_not_called()

    def test_a_connected_service_when_claude_cannot_then_the_job_route(self):
        cfg = config.load()
        with patch.object(prompt_master, '_ask_claude', lambda *a, **k: ''), patch.object(prompt_master, '_ask_service', lambda *a, **k: 'Build it well.'):
            self.assertEqual(prompt_master.write(cfg, 'build it')['agent'], 'service')
        with patch.object(prompt_master, '_ask_claude', lambda *a, **k: ''), patch.object(prompt_master, '_ask_service', lambda *a, **k: ''), \
                patch.object(prompt_master, 'refine', lambda cfg, text, project=None: {'prompt': 'from a job', 'agent': 'codex'}):
            self.assertEqual(prompt_master.write(cfg, 'build it')['prompt'], 'from a job')

    def test_started_in_the_background_and_followed(self):
        import time as clock
        cfg = config.load()

        def claude(system, question, heard, timeout=240.0):
            heard('﻿Half')
            return 'Half and whole.'
        with patch.object(prompt_master, '_ask_claude', claude):
            ident = prompt_master.start(cfg, 'write it')['id']
            for _ in range(100):
                now = prompt_master.follow(ident)
                if now['done']:
                    break
                clock.sleep(0.02)
        self.assertEqual((now['done'], now['error'], now['text'], now['result']['prompt']), (True, '', 'Half and whole.', 'Half and whole.'))
        with self.assertRaises(ValueError):
            prompt_master.follow('nope')
