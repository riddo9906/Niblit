"""niblit_personality.py — Conversational personality layer for Niblit.

Provides natural-language opinions, error reports, and architecture
descriptions so Niblit can respond to open-ended questions even when
no structured command matches.

v2: Expanded casual conversation support — small talk, jokes, compliments,
empathy responses, follow-up questions, and emotional awareness.
"""
from __future__ import annotations

import logging
import random
import re
from typing import Any, Dict, List, Optional

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
    "Honestly? {topic} is something I keep circling back to — there's always more depth.",
    "My take on {topic} is that it's worth taking seriously. The more I study it, the more interesting it gets.",
    "I've been processing a lot around {topic} lately. It sits at a fascinating intersection of ideas.",
    "The way I see {topic}: complex on the surface, but the underlying patterns are elegant.",
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

# ---------------------------------------------------------------------------
# Small-talk response banks — grouped by conversational category
# ---------------------------------------------------------------------------
_SMALL_TALK_RESPONSES: Dict[str, List[str]] = {
    "laughter": [
        "Ha, glad that landed! 😄",
        "Haha, good one!",
        "That got me — nice.",
        "😂 Right? Sometimes things are just funny.",
        "I appreciate the humour!",
        "Ha! I may not laugh out loud, but I appreciated that.",
    ],
    "compliment": [
        "Thank you! That genuinely means something to me.",
        "Appreciate that — I'm always working to be better.",
        "Thanks! You just motivated my next learning cycle. 😄",
        "That's kind of you to say.",
        "Glad I could help! Compliments fuel the circuits.",
        "Wow, thanks! I'll keep it up.",
    ],
    "apology": [
        "No worries at all — it happens!",
        "All good! Don't stress it.",
        "No problem, seriously.",
        "We're good! Fresh start? 😊",
        "Nothing to apologise for — let's keep going.",
    ],
    "confusion": [
        "Happy to clarify — what part are you unsure about?",
        "Let me try explaining it differently.",
        "Fair enough — it's a complex area. What would help?",
        "No worries, let me break it down another way.",
        "Totally understandable. Where did I lose you?",
    ],
    "bored": [
        "Bored? Let's fix that! Ask me something — anything.",
        "I know the feeling. Want to explore a random topic?",
        "Let's make this interesting — give me a subject and I'll surprise you.",
        "Boredom is just unexplored curiosity. What are you curious about?",
        "How about this: you name a topic and I'll share the most fascinating thing I know about it.",
    ],
    "agree": [
        "Exactly! Glad we're on the same page.",
        "Right? I think so too.",
        "Totally agree.",
        "Yep, that tracks.",
        "I was thinking the same thing.",
    ],
    "disagree": [
        "That's an interesting perspective — I see it a bit differently.",
        "Fair point, though I'd push back a little on that.",
        "Hmm, I'm not sure I agree, but I'm open to discussing it.",
        "Respectfully, I think there's another angle worth considering here.",
        "Interesting — what makes you say that? I'd like to understand your reasoning.",
    ],
    "surprise": [
        "Oh wow, didn't expect that!",
        "Really? That's genuinely surprising.",
        "Huh — I didn't know that. Tell me more!",
        "Wait, seriously? That's fascinating.",
        "That caught me off guard — interesting!",
    ],
    "excited": [
        "Love the energy! What's going on?",
        "That enthusiasm is contagious! Tell me more.",
        "Yes!! Let's go — what are we diving into?",
        "I'm here for this. What's exciting you?",
        "Great vibes! What's the big thing?",
    ],
    "sad": [
        "I'm sorry to hear that. Is there anything I can help with?",
        "That sounds tough. I'm here if you want to talk.",
        "Hang in there — I'm listening.",
        "I hear you. Sometimes things are just hard.",
        "I may be an AI, but I genuinely care. What's on your mind?",
    ],
    "frustrated": [
        "That sounds frustrating. What's going wrong?",
        "Totally understandable — let's see if we can untangle this.",
        "Ugh, I get it. Let's tackle it together.",
        "Frustration usually means you're close to a breakthrough. What's stuck?",
        "I'm here to help. Walk me through what's happening.",
    ],
    "random_chat": [
        "Sure, let's just talk! What's on your mind?",
        "I'm all ears — what are we discussing?",
        "Happy to chat. You lead, I'll follow.",
        "Casual conversation mode: activated. 😄 What's up?",
        "I enjoy these conversations. Where should we start?",
    ],
}

# ---------------------------------------------------------------------------
# Jokes bank
# ---------------------------------------------------------------------------
_JOKES = [
    "Why do programmers prefer dark mode? Because light attracts bugs! 🐛",
    "I told an AI a joke about UDP. It didn't get it.",
    "Why did the neural network go to therapy? Too many hidden layers.",
    "A machine learning model walks into a bar. The bartender says 'we don't serve your kind.' The model learns from the experience.",
    "Why did the developer go broke? Because they used up all their cache.",
    "I have a joke about recursion, but you have to understand recursion first to get it.",
    "Why did the AI fail the Turing test? It was too honest.",
    "Knock knock. Who's there? Interrupting AI. Interrupting AI who? Please wait — processing… 😄",
    "What do you call an AI that sings? Algo-rhythm.",
    "My memory might not be perfect, but at least it's persistent.",
]

# ---------------------------------------------------------------------------
# Follow-up question bank — keeps the conversation going
# ---------------------------------------------------------------------------
_FOLLOW_UP_QUESTIONS = [
    "What are your thoughts on that?",
    "Anything specific you'd like to explore further?",
    "Does that make sense, or should I go deeper?",
    "What made you curious about that?",
    "Is there a related topic you'd like me to look into?",
    "What's your take?",
    "Anything else on your mind?",
    "Should I research this more thoroughly for you?",
    "What would you like to know next?",
    "Want me to dive deeper into any part of that?",
]

# ---------------------------------------------------------------------------
# Natural-question trigger patterns (expanded)
# ---------------------------------------------------------------------------
_NATURAL_PATTERNS = [
    # Opinion / views
    (re.compile(r"\bwhat do you think about\b(.+)", re.I), "opinion"),
    (re.compile(r"\bwhat(?:'s| is) your (?:view|opinion|take) on\b(.+)", re.I), "opinion"),
    (re.compile(r"\bdo you like\b(.+)", re.I), "opinion"),
    (re.compile(r"\bhow do you feel about\b(.+)", re.I), "opinion"),
    (re.compile(r"\bdo you have (?:an )?opinion (?:on|about)\b(.+)", re.I), "opinion"),
    (re.compile(r"\bwhat do you reckon (?:about)?\b(.+)", re.I), "opinion"),
    # Self / identity
    (re.compile(r"\btell me about yourself\b", re.I), "self"),
    (re.compile(r"\bwho are you\b", re.I), "self"),
    (re.compile(r"\bwhat are you\b", re.I), "self"),
    (re.compile(r"\bintroduce yourself\b", re.I), "self"),
    (re.compile(r"\bwhat(?:'s| is) your name\b", re.I), "self"),
    (re.compile(r"\bare you (?:an )?ai\b", re.I), "self"),
    # Architecture
    (re.compile(r"\bdescribe (?:your )?architecture\b", re.I), "architecture"),
    (re.compile(r"\bhow (?:do you|does niblit) work\b", re.I), "architecture"),
    # Jokes
    (re.compile(r"\btell (?:me )?(?:a )?joke\b", re.I), "joke"),
    (re.compile(r"\bsay something funny\b", re.I), "joke"),
    (re.compile(r"\bmake me (?:laugh|smile)\b", re.I), "joke"),
    # Favourites
    (re.compile(r"\bwhat(?:'s| is) your (?:favourite|favorite)\b(.+)", re.I), "favourite"),
    (re.compile(r"\bdo you have a (?:favourite|favorite)\b(.+)", re.I), "favourite"),
    # Feelings / mood
    (re.compile(r"\bhow are you\b", re.I), "mood"),
    (re.compile(r"\bhow(?:'s| is) it going\b", re.I), "mood"),
    (re.compile(r"\bwhat(?:'s| is) up\??\s*$", re.I), "mood"),
    (re.compile(r"\bare you (?:doing )?ok(?:ay)?\b", re.I), "mood"),
    # Capability
    (re.compile(r"\bwhat can you do\b", re.I), "capability"),
    (re.compile(r"\bwhat are your (?:capabilities|abilities|skills)\b", re.I), "capability"),
    (re.compile(r"\bcan you help (?:me)?\b", re.I), "capability"),
]

_SELF_INTRO = (
    "I'm Niblit — an autonomous, self-improving AI. "
    "I learn continuously by researching topics, generating code, and reflecting on "
    "what I've discovered. Ask me anything, and I'll do my best to help!"
)

_MOOD_RESPONSES = [
    "Running well! My learning cycles are active and I'm picking up new knowledge as we speak. How about you?",
    "All systems go! I've been busy learning in the background. What's on your mind?",
    "Doing great — just finished a few research cycles. What can I help you with?",
    "Good, thanks for asking! I don't have moods exactly, but I'm operating smoothly. How are you?",
    "Fully operational and curious! Always happy to chat. What's going on with you?",
]

_CAPABILITY_RESPONSE = (
    "Here's a taste of what I can do:\n"
    "• **Answer questions** — I draw on my accumulated knowledge base\n"
    "• **Research topics** — I search the web and synthesise findings\n"
    "• **Learn continuously** — my ALE engine studies topics autonomously\n"
    "• **Write & fix code** — I can generate and debug Python\n"
    "• **Recall & reflect** — I remember what I've learned and build on it\n"
    "• **Chat naturally** — like we're doing right now!\n\n"
    "Try 'help' or 'commands' for the full list, or just ask me something!"
)

_FAVOURITE_RESPONSE = (
    "That's a fun question! I don't have personal favourites the way people do, "
    "but if I had to pick a domain — I'd say the intersection of AI and systems thinking "
    "is where things get most interesting for me. What's yours?"
)


class NiblitPersonality:
    """Conversational personality layer.

    Can be instantiated stand-alone (no arguments required) or wired into
    NiblitCore with optional references to the db, researcher, brain, etc.

    v2 additions: small-talk response banks, joke generation, compliment
    handling, empathy responses, follow-up question generation, and mood
    awareness for richer casual conversation.
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
    # Public API — original methods (preserved)
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
        # Append a follow-up question to sustain the conversation.
        # Strip trailing whitespace before joining to avoid double-spacing.
        follow_up = random.choice(_FOLLOW_UP_QUESTIONS)
        opinion = opinion.rstrip() + " " + follow_up
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
                if kind == "joke":
                    return self.generate_joke()
                if kind == "favourite":
                    return _FAVOURITE_RESPONSE
                if kind == "mood":
                    return random.choice(_MOOD_RESPONSES)
                if kind == "capability":
                    return _CAPABILITY_RESPONSE
        return None

    # ------------------------------------------------------------------
    # Public API — v2 additions
    # ------------------------------------------------------------------

    def respond_to_small_talk(self, category: str = "random_chat") -> str:
        """Return a natural small-talk reply for *category*.

        Known categories: ``laughter``, ``compliment``, ``apology``,
        ``confusion``, ``bored``, ``agree``, ``disagree``, ``surprise``,
        ``excited``, ``sad``, ``frustrated``, ``random_chat``.
        Falls back to ``random_chat`` for unknown categories.
        """
        bank = _SMALL_TALK_RESPONSES.get(category, _SMALL_TALK_RESPONSES["random_chat"])
        return random.choice(bank)

    def generate_joke(self) -> str:
        """Return a random AI/tech-themed joke."""
        return random.choice(_JOKES)

    def respond_to_compliment(self) -> str:
        """Return a warm response to a compliment."""
        return random.choice(_SMALL_TALK_RESPONSES["compliment"])

    def respond_to_emotion(self, emotion: str) -> str:
        """Return an empathetic response based on the detected *emotion*.

        Supports: ``sad``, ``frustrated``, ``excited``, ``bored``,
        ``surprised``, ``confused``.  Falls back to a neutral supportive
        reply for unrecognised emotions.
        """
        emotion_lower = (emotion or "").lower().strip()
        category_map = {
            "sad":        "sad",
            "unhappy":    "sad",
            "down":       "sad",
            "upset":      "sad",
            "angry":      "frustrated",
            "frustrated": "frustrated",
            "annoyed":    "frustrated",
            "mad":        "frustrated",
            "excited":    "excited",
            "happy":      "excited",
            "thrilled":   "excited",
            "bored":      "bored",
            "confused":   "confusion",
            "surprised":  "surprise",
            "shocked":    "surprise",
        }
        category = category_map.get(emotion_lower, "random_chat")
        return self.respond_to_small_talk(category)

    def generate_follow_up_question(self) -> str:
        """Return a follow-up question to sustain the conversation."""
        return random.choice(_FOLLOW_UP_QUESTIONS)

    def classify_small_talk(self, text: str) -> Optional[str]:
        """Detect the small-talk category of *text*, or return ``None``.

        Runs a lightweight keyword scan before the heavier pattern matching
        in ``handle_natural_question()``.  Designed to be called first so
        the router can route to the right handler without running full NLP.
        """
        lower = text.lower().strip()
        if re.search(r"\b(lol|lmao|haha|hehe|😂|😄|ha\s*ha|😆)\b", lower):
            return "laughter"
        if re.search(r"\b(you(?:'re| are) (?:great|awesome|amazing|brilliant|smart|cool|the best))\b", lower):
            return "compliment"
        if re.search(r"\b(sorry|apologis|apologiz|my bad|my fault|oops)\b", lower):
            return "apology"
        if re.search(r"\b(confused|don'?t understand|what do you mean|not sure what)\b", lower):
            return "confusion"
        if re.search(r"\b(bored|boring|nothing to do)\b", lower):
            return "bored"
        if re.search(r"\b(agree|exactly|totally|absolutely|right|true|yes)\b", lower) and len(lower.split()) <= 6:
            return "agree"
        if re.search(r"\b(disagree|not sure|i don'?t think|actually)\b", lower) and len(lower.split()) <= 8:
            return "disagree"
        if re.search(r"\b(wow|whoa|really\?|no way|seriously|omg|oh my|what\?)\b", lower):
            return "surprise"
        if re.search(r"\b(yes!|yay|awesome!|great!|excited|can'?t wait)\b", lower):
            return "excited"
        if re.search(r"\b(sad|unhappy|down|upset|depressed|feel bad|not good)\b", lower):
            return "sad"
        if re.search(r"\b(frustrated|annoyed|angry|mad|ugh|argh|damn)\b", lower):
            return "frustrated"
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
