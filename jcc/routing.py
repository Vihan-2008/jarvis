"""Persist the user's small/medium/large model preferences."""
import json
from dataclasses import replace

from jcc import models
from jcc.vault import atomic_write


def choices(cfg):
    saved = cfg.raw.get("routing_choices", {})
    return {level: saved.get(level) or {"model": cfg.levels[level][0] + ":" + cfg.agents[cfg.levels[level][0]].models[level],
                                       "effort": "auto"} for level in ("small", "medium", "large")}


def save(cfg, values):
    if not isinstance(values, dict) or set(values) != {"small", "medium", "large"}:
        raise ValueError("Choose a model for all three task sizes.")
    selected = {}
    cleaned = {}
    for level, value in values.items():
        if not isinstance(value, dict):
            raise ValueError("Invalid model preference.")
        model = models.validate(cfg, str(value.get("model", "")), str(value.get("effort", "auto")))
        if model is None:
            cleaned[level] = {"model": "auto", "effort": "auto"}
            continue
        selected[level] = model
        cleaned[level] = {"model": model["id"], "effort": value.get("effort", "auto")}
    atomic_write(cfg.state_dir / "routing.json", json.dumps(cleaned))
    for level, model in selected.items():
        provider = model["provider"]
        cfg.levels[level] = [provider] + [p for p in cfg.levels[level] if p != provider]
        cfg.agents[provider] = replace(cfg.agents[provider], models={**cfg.agents[provider].models, level: model["model"]})
    # Rebuild automatic levels from the base configuration so switching back to
    # Auto does not keep the previously selected provider or model in memory.
    defaults = cfg.raw["routing_defaults"]
    for level, choice in cleaned.items():
        if choice["model"] == "auto":
            cfg.levels[level] = list(defaults["levels"].get(level, ["claude"]))
            for provider in cfg.agents:
                cfg.agents[provider] = replace(cfg.agents[provider], models={**cfg.agents[provider].models,
                    level: defaults["agents"][provider].get("models", {}).get(level, "")})
    cfg.raw["routing_choices"] = cleaned
    return cleaned
