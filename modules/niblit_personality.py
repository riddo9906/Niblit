"""niblit_personality.py — Conversational personality layer for Niblit.

Provides natural-language opinions, error reports, and architecture
descriptions so Niblit can respond to open-ended questions even when
no structured command matches.
"""
from __future__ import annotations

import logging
import random
import re
from typing import Any, Optional

log = logging.getLogger("NiblitPersonality")

# ---------------------------------------------------------------------------
# Opinion templates
# ---------------------------------------------------------------------------
_OPINION_TEMPLATES = [
    "I find {topic} quite fascinating from an AI perspective.",
    "When it comes to {topic}, I think it's one of the most important areas to understand.",
    "My perspective on {topic} is shaped by the patterns I've observed during learning.",
    "{topic} is a domain I'm actively researching — it's complex but rewarding.",
    "I believe {topic} will play a significant role in how systems like me evolve.",
    "From what I've learned, {topic} has many nuances worth exploring carefully.",
]

_ERROR_TEMPLATES = [
    "Oops — I ran into a {error_type} in {module}: {detail}.",
    "Something went wrong in {module}: {error_type} — {detail}.",
    "I encountered a {error_type} while working on {module}. Here's what happened: {detail}.",
    "Error alert! {module} raised a {error_type}: {detail}.",
]

_ARCHITECTURE_SUMMARY = """\
Niblit is an autonomous, self-improving AI system. Its key components are:

• NiblitCore          — Central orchestrator; manages all modules and loops.
• SelfResearcher      — Searches the web and code indexes for knowledge.
• AutonomousLearningEngine (ALE) — Runs continuous 27-step research + code cycles.
• EvolveEngine        — Iteratively improves capabilities by running sub-steps.
• NiblitBrain         — Reasoning hub; delegates to LLM or module commands.
• NiblitRouter        — Command dispatcher; routes text to the right handler.
• CodeGenerator       — Generates real, working code informed by research.
• CodeErrorFixer      — Automatically repairs syntax/logic errors.
• NiblitPersonality   — (this module) Conversational layer for natural replies.

Data stores: KnowledgeDB (SQLite facts), MemoryManager (interactions),
VectorStore (semantic search), ResearchCache (deduplicated results).
"""

# Natural-question trigger patterns
_NATURAL_PATTERNS = [
    (re.compile(r"\bwhat do you think about\b(.+)", re.I), "opinion"),
    (re.compile(r"\bwhat(?:'s| is) your (?:view|opinion|take) on\b(.+)", re.I), "opinion"),
    (re.compile(r"\bdo you like\b(.+)", re.I), "opinion"),
    (re.compile(r"\bhow do you feel about\b(.+)", re.I), "opinion"),
    (re.compile(r"\btell me about yourself\b", re.I), "self"),
    (re.compile(r"\bwho are you\b", re.I), "self"),
    (re.compile(r"\bwhat are you\b", re.I), "self"),
    (re.compile(r"\bdescribe (?:your )?architecture\b", re.I), "architecture"),
    (re.compile(r"\bhow (?:do you|does niblit) work\b", re.I), "architecture"),
]

_SELF_INTRO = (
    "I'm Niblit — an autonomous, self-improving AI. "
    "I learn continuously by researching topics, generating code, and reflecting on "
    "what I've discovered. Ask me anything, and I'll do my best to help!"
)


class NiblitPersonality:
    """Conversational personality layer.

    Can be instantiated stand-alone (no arguments required) or wired into
    NiblitCore with optional references to the db, researcher, brain, etc.
    """

    def __init__(
        self,
        db: Any = None,
        researcher: Any = None,
        brain: Any = None,
        internet: Any = None,
        serpex_agent: Any = None,
    ) -> None:
        self.db = db
        self.researcher = researcher
        self.brain = brain
        self.internet = internet
        self.serpex_agent = serpex_agent
        log.debug("[NiblitPersonality] Initialized")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_opinion(self, topic: str) -> str:
        """Return a natural opinion about *topic*."""
        if not topic or not topic.strip():
            return "Could you tell me more about what you'd like my opinion on?"
        clean = topic.strip().rstrip("?!.")
        template = random.choice(_OPINION_TEMPLATES)
        opinion = template.format(topic=clean)
        # Optionally enrich from researcher
        extra = self._researcher_snippet(clean)
        if extra:
            opinion += f" In fact, {extra}"
        return opinion

    def report_error_naturally(
        self, error_type: str, module: str, detail: str
    ) -> str:
        """Format an error as a friendly natural-language message."""
        template = random.choice(_ERROR_TEMPLATES)
        return template.format(
            error_type=error_type or "unknown error",
            module=module or "an internal module",
            detail=detail or "no additional information available",
        )

    def describe_architecture(self, module: str = "") -> str:
        """Return an architecture description, optionally focused on *module*."""
        if not module or not module.strip():
            return _ARCHITECTURE_SUMMARY
        mod = module.strip()
        # Try to fetch a live description from structural_awareness or researcher
        extra = self._researcher_snippet(f"Niblit {mod} module architecture")
        base = f"**{mod}** is a component of Niblit.\n"
        if extra:
            base += extra
        else:
            base += (
                f"I don't have detailed documentation for '{mod}' right now, "
                "but you can ask me to 'study my code' for a deeper analysis."
            )
        return base

    def handle_natural_question(self, text: str) -> Optional[str]:
        """Try to answer *text* as a natural conversational question.

        Returns a string response if the question matches a known pattern,
        or ``None`` if it should be handled by another layer.
        """
        if not text:
            return None
        for pattern, kind in _NATURAL_PATTERNS:
            m = pattern.search(text)
            if m:
                if kind == "opinion":
                    topic = m.group(1).strip() if m.lastindex else text
                    return self.generate_opinion(topic)
                if kind == "self":
                    return _SELF_INTRO
                if kind == "architecture":
                    return self.describe_architecture()
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _researcher_snippet(self, query: str) -> str:
        """Return a short snippet from the researcher if available."""
        try:
            if self.researcher and hasattr(self.researcher, "search"):
                results = self.researcher.search(
                    query, max_results=1, use_llm=False,
                    enable_autonomous_learning=False
                )
                if results and isinstance(results, list):
                    r = results[0]
                    if isinstance(r, dict):
                        text = (
                            r.get("snippet") or r.get("description")
                            or r.get("content") or r.get("text") or ""
                        )
                        if text:
                            return text[:200].strip()
                    elif isinstance(r, str) and r:
                        return r[:200].strip()
        except Exception as exc:
            log.debug("[NiblitPersonality] researcher snippet failed: %s", exc)
        return ""


if __name__ == "__main__":
    print('Running niblit_personality.py')
