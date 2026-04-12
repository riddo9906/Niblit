"""modules/intent_parser.py — Enhanced intent parser for Niblit.

Understands user prompts across a wide range of intents: memory operations,
knowledge queries, system control, learning directives, and conversational chat.
``parse_intent`` is the primary entry point and returns a (intent_label, meta)
tuple.  ``understand_prompt`` extends this with topic extraction and confidence.
"""
from __future__ import annotations

import re
from typing import Dict, Optional, Tuple


# ── Pattern tables ────────────────────────────────────────────────────────────

# (pattern_or_prefix, intent_label, extraction_fn_name_or_None)
# Evaluated in order; first match wins.

_EXACT: Tuple[Tuple, ...] = (
    # system control
    ({"time", "what time is it", "current time", "what's the time"}, "time"),
    ({"help", "commands", "?", "/help"}, "help"),
    ({"status", "health", "health check", "system status"}, "status"),
    ({"shutdown", "exit", "quit", "bye", "goodbye"}, "shutdown"),
    ({"clear", "cls"}, "clear"),
    ({"notifications", "notif"}, "notifications"),
    ({"version"}, "version"),
)

_PREFIX: Tuple[Tuple, ...] = (
    # memory
    ("remember ", "remember"),
    ("forget ", "forget"),
    ("recall ", "recall"),
    # learning
    ("learn about ", "learn"),
    ("learn ", "learn"),
    ("research ", "research"),
    ("study ", "study"),
    # ideas
    ("ideas about ", "ideas"),
    ("ideas for ", "ideas"),
    ("brainstorm ", "ideas"),
    # questions / definitions
    ("what is ", "definition_query"),
    ("what are ", "definition_query"),
    ("define ", "definition_query"),
    ("explain ", "explain"),
    ("how does ", "process_query"),
    ("how do ", "process_query"),
    ("how is ", "process_query"),
    ("why is ", "reason_query"),
    ("why does ", "reason_query"),
    ("tell me about ", "explain"),
    ("describe ", "explain"),
    # system commands
    ("toggle-llm ", "toggle_llm"),
    ("/slsa ", "slsa"),
    ("implement ", "implement"),
    ("create ", "create"),
    ("build ", "build"),
    ("generate ", "generate"),
    ("write ", "write"),
    ("fix ", "fix"),
    ("debug ", "debug"),
    ("analyse ", "analyse"),
    ("analyze ", "analyse"),
    ("summarise ", "summarise"),
    ("summarize ", "summarise"),
    ("compare ", "compare"),
    ("translate ", "translate"),
    ("list ", "list"),
    ("show me ", "show"),
    ("find ", "search"),
    ("search for ", "search"),
    # weather / location
    ("weather in ", "weather"),
    ("weather for ", "weather"),
    ("weather ", "weather"),
    # trading
    ("trade ", "trade"),
    ("buy ", "trade"),
    ("sell ", "trade"),
    ("price of ", "price_query"),
)

_KEYWORD: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    # greeting
    (("hello", "hi", "hey", "howdy", "greetings"), "greeting"),
    # thanks
    (("thanks", "thank you", "cheers"), "thanks"),
    # weather
    (("weather", "forecast", "temperature", "rain", "sunny", "cloudy"), "weather"),
    # math
    (("calculate", "compute", "math", "plus", "minus", "multiply", "divide",
      "add", "subtract"), "calculation"),
    # trading
    (("bitcoin", "btc", "ethereum", "eth", "crypto", "stock", "trading", "price"), "trade"),
    # knowledge
    (("fact", "knowledge", "know", "knowledge base", "kb"), "knowledge_query"),
)


def _extract_topic(prefix: str, raw: str) -> str:
    """Remove *prefix* from *raw* and return the trimmed remainder."""
    return raw[len(prefix):].strip()


def parse_intent(text: str) -> Tuple[str, Dict]:
    """Parse *text* and return ``(intent_label, metadata)``.

    Parameters
    ----------
    text:
        Raw user input string.

    Returns
    -------
    Tuple[str, dict]
        ``intent_label`` — a short snake_case identifier (e.g. ``"learn"``,
        ``"definition_query"``, ``"chat"``).
        ``metadata`` — extra extracted values such as ``topic``, ``key``,
        ``value``, ``state``, ``query``.  Always a dict (never ``None``).
    """
    t = text.strip()
    lower = t.lower()

    # ── Memory: remember <key>: <value> ───────────────────────────────────
    if lower.startswith("remember "):
        payload = t[len("remember "):].strip()
        if ":" in payload:
            k, v = payload.split(":", 1)
            return "remember", {"key": k.strip(), "value": v.strip()}
        return "remember", {"value": payload}

    if lower.startswith("forget "):
        return "forget", {"key": t[len("forget "):].strip()}

    if lower.startswith("recall "):
        return "recall", {"key": t[len("recall "):].strip()}

    # ── Exact matches ─────────────────────────────────────────────────────
    for match_set, label in _EXACT:
        if lower in match_set:
            return label, {}

    # ── Prefix matches ────────────────────────────────────────────────────
    for prefix, label in _PREFIX:
        if lower.startswith(prefix):
            topic = _extract_topic(prefix, t)
            meta: Dict = {}
            if topic:
                if label in ("learn", "research", "study", "ideas",
                              "definition_query", "explain", "process_query",
                              "reason_query"):
                    meta["topic"] = topic
                elif label == "toggle_llm":
                    meta["state"] = topic.lower()
                elif label == "slsa":
                    meta["topic"] = topic
                else:
                    meta["query"] = topic
            return label, meta

    # ── Keyword scan ──────────────────────────────────────────────────────
    for keywords, label in _KEYWORD:
        if any(kw in lower for kw in keywords):
            return label, {"query": t}

    # ── Greeting heuristic ────────────────────────────────────────────────
    if re.match(r"^(hi|hey|hello|howdy|sup|yo)\b", lower):
        return "greeting", {}

    # ── Fallback ─────────────────────────────────────────────────────────
    return "chat", {"query": t}


def understand_prompt(text: str) -> Dict:
    """Return a richer understanding dict for *text*.

    Returns
    -------
    dict with keys:
        ``intent``      — string label from :func:`parse_intent`.
        ``topic``       — extracted topic/query string (may be empty).
        ``confidence``  — float 0.0–1.0 estimate of parse confidence.
        ``metadata``    — raw metadata dict from :func:`parse_intent`.
        ``question_type`` — one of ``"definition"``, ``"process"``,
                            ``"reason"``, ``"factual"``, ``"command"``,
                            ``"conversational"``, ``"greeting"``.
    """
    intent, meta = parse_intent(text)
    lower = text.strip().lower()

    topic = meta.get("topic") or meta.get("query") or meta.get("key") or ""
    confidence = _estimate_confidence(intent, lower)
    question_type = _classify_question_type(intent, lower)

    return {
        "intent": intent,
        "topic": topic,
        "confidence": confidence,
        "metadata": meta,
        "question_type": question_type,
    }


def _estimate_confidence(intent: str, lower: str) -> float:
    """Heuristic confidence: command-style intents score higher than 'chat'."""
    if intent == "chat":
        return 0.40
    if intent in ("greeting", "thanks"):
        return 0.95
    if intent in ("time", "help", "status", "shutdown", "clear", "version", "notifications"):
        return 0.99
    if intent in ("remember", "forget", "recall"):
        return 0.95
    if intent in ("learn", "research", "study", "ideas"):
        return 0.90
    if intent in ("definition_query", "explain", "process_query", "reason_query"):
        return 0.85
    if intent in ("weather", "trade", "price_query", "calculation"):
        return 0.80
    return 0.70


def _classify_question_type(intent: str, lower: str) -> str:
    """Map an intent label to a broad question-type category."""
    if intent in ("greeting", "thanks", "chat"):
        return "conversational"
    if intent == "greeting":
        return "greeting"
    if intent in ("definition_query", "explain"):
        return "definition"
    if intent in ("process_query",):
        return "process"
    if intent in ("reason_query",):
        return "reason"
    if intent in ("knowledge_query", "search", "recall"):
        return "factual"
    return "command"


if __name__ == "__main__":
    _samples = [
        "hi",
        "what is photosynthesis",
        "learn about quantum computing",
        "remember mood: happy",
        "how does recursion work",
        "weather in London",
        "status",
        "buy 0.1 BTC",
        "calculate 5 * 8",
        "just chatting here",
    ]
    for s in _samples:
        print(understand_prompt(s))
