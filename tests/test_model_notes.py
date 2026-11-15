"""Every model says what it is good for, wherever one can be chosen; and "On this PC" only for model apps that are."""
import json
import os
from unittest import mock

from jcc import model_notes, models, providers
from tests.helpers import EngineTestCase
from tests.test_gui import GuiTestCase


class EveryModelSaysWhatItIsGoodFor(EngineTestCase):
    def test_each_family_has_its_strength_and_its_catch(self):
        said = {name: model_notes.about(name, provider) for provider, name in [
            ("claude", "fable"), ("claude", "opus"), ("claude", "sonnet"), ("claude", "haiku"),
            ("codex", "gpt-6-astra"), ("codex", "gpt-6.1-sol"), ("codex", "gpt-6.1-terra"), ("codex", "gpt-6-luna")]}
        self.assertIn("most capable", said["fable"]); self.assertIn("costliest", said["fable"])
        self.assertIn("cheapest", said["haiku"]); self.assertIn("weaker on hard problems", said["haiku"])
        self.assertIn("balanced", said["sonnet"])
        self.assertIn("frontier", said["gpt-6-astra"]); self.assertIn("fastest", said["gpt-6-luna"])
        self.assertEqual(len(set(said.values())), len(said), "each says something of its own")

    def test_any_model_of_any_service_gets_a_line_from_its_name(self):
        cases = {("openrouter", "meta-llama/llama-3.1-8b-instruct"): "small and fast",
                 ("together", "meta-llama/Llama-3.3-70B-Instruct-Turbo"): "large",
                 ("openrouter", "qwen/qwen-2.5-coder-32b-instruct"): "code",
                 ("openrouter", "deepseek/deepseek-r1"): "step by step",
                 ("gemini", "gemini-2.5-flash"): "free key",
                 ("gemini", "gemini-2.5-pro"): "strongest",
                 ("openai", "o4-mini"): "reasoning",
                 ("perplexity", "ultra"): "deepest research",
                 ("openrouter", "perplexity/sonar"): "sources",
                 ("openai", "text-embedding-3-small"): "not for chatting",
                 ("openrouter", "openrouter/auto"): "Picks a model"}
        for (provider, name), word in cases.items():
            self.assertIn(word, model_notes.about(name, provider), name)
        self.assertNotIn("very small", model_notes.about("microsoft/phi-4"), '"micro" in Microsoft is not a size')
        self.assertNotIn("::", model_notes.about("meta-llama/llama-3.1-8b-instruct").replace(": ", ":"))

    def test_when_the_name_says_nothing_the_services_own_words_are_used(self):
        self.assertEqual(model_notes.about("acme/zephyr", "openrouter", given="Great at poems. Also other things."), "Great at poems.")
        self.assertIn("does not say more", model_notes.about("acme/zephyr", "openrouter"))

    def test_older_versions_snapshots_and_models_on_this_pc_say_so(self):
        self.assertTrue(model_notes.about("claude-opus-4-8", "claude", "Opus 4.8", older=True).startswith("Older version"))
        self.assertIn("dated snapshot (2024-08-06)", model_notes.about("gpt-4o-2024-08-06", "openai"))
        self.assertIn("free and private", model_notes.about("qwen2.5:7b", "ollama", local=True))

    def test_the_catalog_marks_the_older_one_of_a_family(self):
        with mock.patch.object(models, "read_json", lambda path, default: {"models": [
                {"value": "opus", "displayName": "Opus 5.5"}, {"value": "claude-opus-4-8", "displayName": "Opus 4.8"}]}
                if "quota-claude" in str(path) else default):
            rows = {m["label"]: m["about"] for m in models.catalog(self.cfg) if m["provider"] == "claude"}
        self.assertFalse(rows["Opus 5.5"].startswith("Older"))
        self.assertTrue(rows["Opus 4.8"].startswith("Older version"))
        self.assertTrue(all(rows.values()), "every model has its line")

    @property
    def cfg(self):
        from jcc import config
        return config.load()


class OnThisPC(GuiTestCase):
    def test_on_this_pc_only_for_the_model_apps_that_are_on_it(self):
        with mock.patch("shutil.which", lambda c: None), mock.patch.object(providers, "installed", lambda ident, *a, **k: False):
            listed = {s["id"]: s for s in providers.listing(self.state.cfg)}
        self.assertFalse(listed["ollama"]["on_pc"]); self.assertFalse(listed["lmstudio"]["on_pc"])
        self.assertEqual(listed["ollama"]["name"], "Ollama", "its name no longer says it is on this PC")
        with mock.patch.object(providers, "installed", lambda ident, *a, **k: ident == "ollama"):
            listed = {s["id"]: s for s in providers.listing(self.state.cfg)}
        self.assertTrue(listed["ollama"]["on_pc"]); self.assertFalse(listed["lmstudio"]["on_pc"])
        self.assertFalse(listed["openai"]["on_pc"], "a service on the internet is never on this PC")

    def test_installed_looks_in_the_usual_places_and_on_the_path(self):
        nothing = lambda p: False
        self.assertFalse(providers.installed("ollama", which=lambda c: None, exists=nothing))
        self.assertTrue(providers.installed("ollama", which=lambda c: "C:/x/ollama.exe" if c == "ollama" else None, exists=nothing))
        found = os.path.expanduser("~/.lmstudio/bin/lms")
        self.assertTrue(providers.installed("lmstudio", which=lambda c: None, exists=lambda p: os.path.normpath(p) == os.path.normpath(found)))

    def test_a_services_models_come_with_what_each_is_good_for(self):
        with mock.patch.object(providers, "models", lambda cfg, ident, refresh=False: ["gemini-2.5-flash", "gemini-2.5-pro"]):
            got = providers.models_about(self.state.cfg, "gemini")
        self.assertEqual(got["models"], ["gemini-2.5-flash", "gemini-2.5-pro"])
        self.assertIn("fast", got["about"]["gemini-2.5-flash"]); self.assertIn("strongest", got["about"]["gemini-2.5-pro"])
        self.assertTrue(json.dumps(got))
