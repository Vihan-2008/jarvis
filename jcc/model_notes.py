"""What each AI model is good for, in one line: its strength, what to pick it for, and its catch (speed or cost).

Shown beside every model wherever one can be chosen: the model menu next to the message box, JARVIS's brain in
Settings > Models, each connected AI service's model list, and the older settings screens.

Every model JARVIS can reach gets a line, not only the ones listed on this PC: the Claude, GPT (Codex) and Grok models
of the coding apps, and every model of every AI service that can be connected (OpenAI, Gemini, Groq, OpenRouter's
hundreds, Mistral, DeepSeek, models on this PC with Ollama or LM Studio, ...). That cannot be a hand-written list, so:

1. the families everyone uses have lines written for them, tier by tier (FAMILIES);
2. any other model is read from its name: who makes it, how big it is ("8b", "mini", "pro", "large"), and what it is
   tuned for ("coder", "reasoning", "vision", web search) (compose);
3. only when the name says nothing useful, the service's own description of it is used, shortened.

A dated snapshot ("gpt-4o-2024-08-06") and an older version of a family are said to be so. Models on this PC are said
to be free and private.
"""
from __future__ import annotations

import re

# Not for chatting: never offered in a chat, but described if they are ever shown.
NOT_CHAT = [(r"embed", "Turns text into numbers for search; not for chatting."),
            (r"whisper|transcri|speech-to|stt\b", "Turns speech into text; not for chatting."),
            (r"\btts\b|text-to-speech|-tts|audio-preview|realtime", "For speaking and live voice; not for typed chat."),
            (r"moderation|guard|safety", "Checks text for harmful content; not for chatting."),
            (r"rerank", "Sorts search results; not for chatting."),
            (r"dall-e|image-gen|imagen|gpt-image|flux|stable-diffusion|sdxl", "Makes pictures; not for chatting.")]

# Perplexity's choices are depths of research, not model names.
DEPTHS = {"fast": "Quickest web search: a short answer with its sources, in seconds; the least thorough.",
          "low": "Light research: a few sources, quick and cheap; good for simple current facts.",
          "medium": "Balanced research: more sources and a fuller answer; a little slower.",
          "high": "Thorough research: many sources checked; slower and costlier.",
          "xhigh": "Very thorough research for hard questions; slow and costly.",
          "ultra": "The deepest research, a full report from many sources; the slowest and costliest."}

# Hand-written lines, checked in order against the model's name (and label), lower case. The first match wins.
FAMILIES: list[tuple[str, str]] = [
    # Claude (the Claude Code app, or through a service such as OpenRouter)
    (r"fable", "Claude's most capable model: the hardest builds, tricky bugs and deep thinking; the slowest and costliest to use."),
    (r"opus", "Very capable Claude: complex coding, planning and careful reviews; slower and pricier than Sonnet."),
    (r"sonnet", "Claude's balanced all-rounder: most coding, writing and questions; quick, at a moderate cost."),
    (r"haiku", "Claude's fastest and lightest: quick questions, small edits and summaries; the cheapest, weaker on hard problems."),
    (r"^default$|default \(recommended\)", "The coding app's own pick: a sensible all-rounder when you would rather not choose."),
    # GPT through the Codex app (its families)
    (r"astra", "GPT's frontier model: the most demanding work and hardest problems; slower, and the costliest GPT."),
    (r"\bsol\b|-sol\b", "GPT's everyday workhorse: strong at coding and most tasks; a good default, at a moderate cost."),
    (r"terra", "Balanced GPT: straightforward coding and writing for less allowance than Sol; not for the hardest problems."),
    (r"luna", "GPT's fastest and lightest: easy tasks and quick edits; the cheapest, weaker on hard problems."),
    # OpenAI through an API key
    (r"gpt-oss-?120b", "OpenAI's large open model: strong reasoning and coding, very fast on Groq or Cerebras; less polished than GPT."),
    (r"gpt-oss-?20b", "OpenAI's small open model: quick and cheap for simple questions; weaker on hard problems."),
    (r"(^|/)o\d(-pro)?\b(?!.*mini)", "OpenAI reasoning model: thinks step by step first, for maths, logic and hard code; slow and costly."),
    (r"(^|/)o\d-mini", "Small OpenAI reasoning model: careful step-by-step answers at a lower cost; slower than a plain GPT."),
    (r"gpt-[\d.]+o?-?nano|gpt-.*-nano", "OpenAI's tiniest GPT: the fastest and cheapest, for very simple jobs; often misses nuance."),
    (r"gpt-[\d.]+o?-?mini|gpt-.*-mini", "Small, fast GPT: everyday questions at a low cost; less capable on hard problems."),
    (r"gpt-[\d.]+-pro", "OpenAI's top-tier GPT: the hardest questions, thinking longest; slow and very costly."),
    (r"chatgpt-4o|gpt-4o", "OpenAI's GPT-4o: a capable all-rounder that also reads pictures; costlier than the mini versions."),
    (r"gpt-[\d.]+", "OpenAI's GPT: a capable all-rounder for writing, coding and questions; costlier than the mini versions."),
    # Gemini and Gemma (Google)
    (r"gemini.*flash-lite|gemini.*flash-8b", "Google's lightest Gemini: very quick and the cheapest (free key works); for simple questions."),
    (r"gemini.*flash", "Google's fast Gemini: everyday questions, long documents and pictures at low cost (free key works); less deep than Pro."),
    (r"gemini.*pro", "Google's strongest Gemini: hard questions, long documents and coding; slower and costlier than Flash."),
    (r"gemini.*(ultra|deep-?think)", "Google's top Gemini for the hardest problems; slow and costly."),
    # Grok (xAI)
    (r"grok.*code", "Grok tuned for code: quick coding help; less suited to general questions."),
    (r"grok.*mini", "Small Grok: quick answers at a low cost; weaker on hard problems."),
    (r"grok.*fast", "Grok's fast version: quicker replies; priced differently from the standard Grok, so check its cost."),
    (r"grok", "xAI's Grok: strong at hard questions and coding, with a style of its own; costlier than its fast version."),
    # Search-first models (Perplexity's Sonar, wherever offered)
    (r"sonar-deep-research|deep-research", "Deep research: searches widely and writes a full report with sources; slow and the most costly."),
    (r"sonar-reasoning", "Web search with step-by-step reasoning: sourced answers to tricky questions; slower."),
    (r"sonar-pro", "Thorough web search: fuller sourced answers; slower and costlier than plain Sonar."),
    (r"sonar", "Searches the web first and answers with its sources: good for current facts; short answers."),
    # DeepSeek
    (r"deepseek.*(reasoner|r1)", "DeepSeek's reasoning model: thinks step by step for maths, logic and tricky code; slower to answer."),
    (r"deepseek.*coder", "DeepSeek tuned for code: writing and fixing programs at a very low cost."),
    (r"deepseek", "DeepSeek's general model: strong coding and everyday answers for very little cost; can be slow at busy times."),
    # Mistral
    (r"magistral", "Mistral's reasoning model: careful step-by-step answers; slower."),
    (r"codestral|devstral", "Mistral tuned for code: writing, completing and fixing programs; less suited to general chat."),
    (r"pixtral", "Mistral that also reads pictures: screenshots, photos and documents."),
    (r"ministral", "Mistral's tiny model: very fast and cheap for simple jobs; weak on hard ones."),
    (r"mistral.*large", "Mistral's strongest: hard questions, writing and coding; slower and costlier than Medium."),
    (r"mistral.*medium", "Mistral's balanced model: good everyday quality at a fair cost."),
    (r"mistral.*small|mistral-7b|open-mistral", "Mistral's small model: fast and cheap for everyday questions; weaker on hard problems."),
    (r"mixtral", "Mixtral (Mistral's open mix of experts): quick, decent everyday answers; older than Mistral's newer models."),
    # Moonshot, Cohere
    (r"kimi.*thinking", "Kimi in thinking mode: works through hard problems step by step; slower."),
    (r"kimi|moonshot", "Moonshot's Kimi: long documents and multi-step coding tasks; a little slower than the smallest models."),
    (r"command-a", "Cohere's strongest Command: business writing, documents and tools; costlier than Command R."),
    (r"command-r-?plus|command-r\+", "Cohere's Command R+: long documents and answers with citations; slower than Command R."),
    (r"command-r7b", "Cohere's smallest Command: very fast and cheap for simple jobs."),
    (r"command", "Cohere's Command: documents and answers with citations; a fair balance of speed and cost."),
    # Routers
    (r"openrouter/auto|(^|/)auto$", "Picks a model for each question for you: convenient, but the model (and cost) varies."),
]

# Who makes a model (for names the lines above do not cover), read from its name.
MAKERS = [(r"llama", "Meta's open Llama"), (r"qwen|qwq", "Alibaba's open Qwen"), (r"gemma", "Google's open Gemma"),
          (r"phi-?\d", "Microsoft's small Phi"), (r"granite", "IBM's Granite"), (r"nemotron", "NVIDIA's Nemotron"),
          (r"glm|chatglm", "Zhipu's GLM"), (r"yi-", "01.AI's Yi"), (r"minimax", "MiniMax's"), (r"hermes", "Nous Research's Hermes"),
          (r"jamba", "AI21's Jamba"), (r"nova-", "Amazon's Nova"), (r"olmo", "AI2's open OLMo"), (r"smollm", "Hugging Face's tiny SmolLM"),
          (r"dolphin", "the uncensored Dolphin"), (r"wizard", "WizardLM"), (r"starcoder", "BigCode's StarCoder"), (r"falcon", "TII's Falcon"),
          (r"ernie", "Baidu's ERNIE"), (r"hunyuan", "Tencent's Hunyuan"), (r"doubao|seed-", "ByteDance's Seed"), (r"lfm", "Liquid's LFM")]


def _size(name: str) -> str:
    """tiny / small / medium / large, from the name ("8b", "mini", "pro", ...), or "" when it does not say."""
    found = re.findall(r"(?<![\d.])(\d+(?:\.\d+)?)\s*b\b", name)
    if found:
        biggest = max(float(n) for n in found)
        return "tiny" if biggest < 5 else "small" if biggest < 12 else "medium" if biggest < 60 else "large"
    word = lambda words: re.search(r"(?<![a-z])(?:" + words + r")(?![a-z])", name)      # whole words only ("micro", not "microsoft")
    if word(r"tiny|nano|micro") or re.search(r"mini-?lm", name):
        return "tiny"
    if word(r"mini|small|lite|instant|light|haiku|fast|turbo|flash"):
        return "small"
    if word(r"large|pro|ultra|max|plus|opus|maverick|heavy|xl|xxl"):
        return "large"
    if word(r"medium|scout"):
        return "medium"
    return ""


# The size, then what that means: "Meta's open Llama, small and fast: quick questions at a low cost; ..."
SIZES = {"tiny": ("very small", "the quickest and cheapest, for simple jobs; often misses nuance"),
         "small": ("small and fast", "quick questions at a low cost; weaker on hard problems"),
         "medium": ("mid-sized", "good everyday quality at a fair speed"),
         "large": ("large", "among the strongest of its kind, for hard questions and long writing; slower and costlier")}


def compose(name: str) -> str:
    """A line for a model no hand-written line covers, from what its name says. "" when it says nothing useful."""
    maker = next((who for pattern, who in MAKERS if re.search(pattern, name)), "")
    size = _size(name)
    tuned = ("thinks step by step first, for maths, logic and tricky code, so it is slower" if re.search(r"\br1\b|-r1|reason|think|qwq", name)
             else "tuned for writing and fixing code, less for general chat" if re.search(r"coder|code|starcoder", name)
             else "also reads pictures" if re.search(r"vision|-vl\b|\bvl\b|llava|multimodal", name)
             else "searches the web for its answers" if re.search(r"online|search", name)
             else "")
    if not (maker or size or tuned):
        return ""
    adjective, meaning = SIZES.get(size, ("", ""))
    head = (maker or "A model") + (", " + adjective if adjective and maker else " that is " + adjective if adjective else "")
    body = "; ".join(part for part in (meaning, tuned) if part) or "a general model for everyday questions"
    return head + ": " + body + "."


def _plain(text: str) -> str:
    """A service's own description, cut to one sentence a person can read in a list."""
    text = re.sub(r"\s+", " ", re.sub(r"[#*_`\[\]()]|https?://\S+", " ", str(text or ""))).strip()
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return (first[:157] + "...") if len(first) > 160 else first


def about(name: str, provider: str = "", label: str = "", given: str = "", older: bool = False, local: bool = False) -> str:
    """One line on what this model is good for. name: its id; provider: the service or app it comes through; label: its
    shown name; given: what the service itself says about it; older: a newer one of its family is offered too; local: it
    runs on this PC."""
    raw = str(name or "")
    text = (raw + " " + str(label or "")).lower().strip()
    if provider == "perplexity" and raw in DEPTHS:
        return DEPTHS[raw]
    for pattern, line in NOT_CHAT:
        if re.search(pattern, text):
            return line
    line = next((line for pattern, line in FAMILIES if re.search(pattern, text)), "") or compose(text)
    if not line:
        line = (_plain(given) or "A general model for everyday questions; its service does not say more.")
    snapshot = re.search(r"(?<!\d)(20\d\d)-?(\d\d)-?(\d\d)(?!\d)", raw)
    if older or re.search(r"\b(legacy|deprecated)\b", text):
        line = "Older version (the newer one is usually better). " + line
    elif snapshot:
        line += (" A dated snapshot (" + "-".join(snapshot.groups()) + "): it never changes, while the plain name moves to the newest.")
    if local:
        line += " Runs on this PC: free and private; its speed depends on your computer."
    return line
