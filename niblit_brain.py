#!/usr/bin/env python3
"""
NIBLIT BRAIN MODULE - Enhanced Edition

Handles thinking, learning, HFBrain integration, self modules, and router compatibility.

IMPORTANT: This module handles GENERAL CHAT ONLY.
Commands are handled by niblit_core.py via CommandRegistry.
Do NOT process commands here.

Enhancements:
1. Circuit breakers for fault tolerance
2. Telemetry and metrics tracking
3. Rate limiting on brain operations
4. Multi-level caching for thinking
5. Batch processing for learning
6. Event sourcing for audit trail
7. Structured logging with correlation IDs
8. Multi-Agent Internal Debate Layer (Phase 14)
"""

__all__ = [
    "NiblitBrain", "BrainTrainer", "NiblitCloudBrain",
    "get_niblit_cloud_brain", "set_cloud_brain_url", "hf_query",
    "get_brain_debate_status", "_update_brain_debate_trust",
    "BRAIN_DEBATE_ENABLED", "BRAIN_DEBATE_TRUST_LR",
]

import re
import sys
import os
import contextlib
import datetime
import logging
import asyncio
import threading
from typing import Any, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

log = logging.getLogger("NiblitBrain")

# ── KB text safety ────────────────────────────────────────────────────────────

# Maximum character length of a single KB text snippet injected into a prompt.
# At 16K ctx: 1500 chars ≈ 375 tokens gives richer per-fact context.
# Override with NIBLIT_KB_TEXT_MAX_CHARS (default 1500 at 16K, 512 for legacy).
_KB_TEXT_MAX_CHARS = int(os.environ.get("NIBLIT_KB_TEXT_MAX_CHARS", "1500"))

# Maximum total characters of KB context prepended to each think() prompt.
# At 16K ctx: 6000 chars ≈ 1500 tokens; leaves ample room for system prompt,
# chat history, user message, and response generation.
# Override with NIBLIT_BRAIN_CONTEXT_MAX_CHARS (default 6000 at 16K).
_CONTEXT_MAX_CHARS = int(os.environ.get("NIBLIT_BRAIN_CONTEXT_MAX_CHARS", "6000"))

# Chat-history injection into the local-brain (brain_router) path.
# At 16K ctx: 20 messages (10 exchanges) enables deeper long-horizon cognition.
# Override with NIBLIT_BRAIN_CHAT_HISTORY_LIMIT.
_CHAT_HISTORY_MSG_LIMIT: int = int(os.environ.get("NIBLIT_BRAIN_CHAT_HISTORY_LIMIT", "20"))
# Per-message character cap for history injection.  At 16K ctx: 800 chars
# allows richer message content while keeping the history block bounded.
# Override with NIBLIT_BRAIN_CHAT_HISTORY_CONTENT_CHARS.
_CHAT_HISTORY_CONTENT_CHARS: int = int(
    os.environ.get("NIBLIT_BRAIN_CHAT_HISTORY_CONTENT_CHARS", "800")
)
_DEFAULT_CLOUD_MAX_TOKENS: int = int(
    os.environ.get("NIBLIT_CLOUD_MAX_TOKENS", os.environ.get("NIBLIT_LOCAL_MAX_NEW", "512"))
)

# Control characters that corrupt GGUF tokenisers when injected into prompts.
# We keep \t (0x09) and \n (0x0a) which are meaningful for formatting.
_CONTROL_CHARS_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\x80-\x9f]"
)


def _sanitize_text(text: str, max_chars: int = _KB_TEXT_MAX_CHARS) -> str:
    """Strip control characters and truncate *text* to *max_chars*.

    Removes characters in the ranges 0x00–0x08, 0x0B–0x0C, 0x0E–0x1F, 0x7F,
    and 0x80–0x9F (C1 controls).  Horizontal tab (0x09) and newline (0x0A)
    are preserved as they carry formatting value.

    This prevents tokeniser collapse on small GGUF models when KB facts
    contain backspace characters (``\\x7f``) or other binary noise.
    """
    cleaned = _CONTROL_CHARS_RE.sub("", text or "")
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]
    return cleaned


# ── Casual-input detection ────────────────────────────────────────────────────

# Keywords that make a message non-casual even if it is short.
_NON_CASUAL_KEYWORDS = frozenset({
    "run", "fix", "recall", "learn", "search", "code", "status",
    "help", "teach", "research", "define", "explain", "calculate",
    "what", "why", "when", "where", "which",
    "generate", "write", "build", "create", "find", "show",
    "autonomous", "brain", "memory", "toggle", "knowledge",
})

# Compiled once at module level to avoid repeated re.compile() overhead.
_HOW_QUERY_RE = re.compile(r"\bhow\s+(do|does|to|can|could|should|would|is)\b")


def _is_casual_input(text: str) -> bool:
    """Return True when *text* looks like a casual greeting or short chat opener.

    A message is casual when:
    - It contains ≤ 6 words, AND
    - It contains no question mark (``?``), AND
    - None of its words are command / question keywords.

    Casual messages skip the full KB/RAG/SECA pipeline in ``think()`` and are
    answered directly by the local brain's lightweight chat prompt — avoiding
    ~900-token system-prompt overhead for simple greetings.
    """
    stripped = text.strip()
    if "?" in stripped:
        return False
    lowered = stripped.lower()
    words = lowered.split()
    if len(words) > 6:
        return False
    if _HOW_QUERY_RE.search(lowered):
        return False
    if any(w in _NON_CASUAL_KEYWORDS for w in words):
        return False
    return True

# ───────── Improvement Imports ─────────
# pylint: disable=invalid-name
try:
    from modules.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
except Exception as _e:
    log.debug(f"CircuitBreaker unavailable: {_e}")
    CircuitBreaker = None
    CircuitBreakerConfig = None

try:
    from modules.metrics_observability import TelemetryCollector
except Exception as _e:
    log.debug(f"TelemetryCollector unavailable: {_e}")
    TelemetryCollector = None

try:
    from modules.rate_limiting import RateLimiter
except Exception as _e:
    log.debug(f"RateLimiter unavailable: {_e}")
    RateLimiter = None

try:
    from modules.multi_level_caching import CacheStrategy
except Exception as _e:
    log.debug(f"CacheStrategy unavailable: {_e}")
    CacheStrategy = None

try:
    from modules.batch_processing import LearningBatcher
except Exception as _e:
    log.debug(f"LearningBatcher unavailable: {_e}")
    LearningBatcher = None

try:
    from modules.event_sourcing import EventStore, Event, EventType
except Exception as _e:
    log.debug(f"EventStore unavailable: {_e}")
    EventStore = None
    Event = None
    EventType = None

try:
    from modules.structured_logging import StructuredLogger, RequestContext
except Exception as _e:
    log.debug(f"StructuredLogger unavailable: {_e}")
    StructuredLogger = None
    RequestContext = None

# ───────── Local Modules ─────────
try:
    from modules.hf_brain import HFBrain
except Exception as _e:
    log.warning(f"HFBrain unavailable: {_e}")
    HFBrain = None

try:
    from modules.self_researcher import SelfResearcher
except Exception as _e:
    log.warning(f"SelfResearcher unavailable: {_e}")
    SelfResearcher = None

try:
    from modules.self_healer import SelfHealer
except Exception as _e:
    log.warning(f"SelfHealer unavailable: {_e}")
    SelfHealer = None

try:
    from modules.self_idea_implementation import SelfIdeaImplementation
except Exception as _e:
    log.warning(f"SelfIdeaImplementation unavailable: {_e}")
    SelfIdeaImplementation = None

try:
    from modules.reflect import ReflectModule
except Exception as _e:
    log.warning(f"ReflectModule unavailable: {_e}")
    ReflectModule = None

try:
    from modules.self_teacher import SelfTeacher
except Exception as _e:
    log.warning(f"SelfTeacher unavailable: {_e}")
    SelfTeacher = None

try:
    from modules.internet_manager import InternetManager
except Exception as _e:
    log.warning(f"InternetManager unavailable: {_e}")
    InternetManager = None

try:
    from niblit_tools.serpex_api import niblit_serpex_search as _niblit_serpex_search
    from niblit_tools.serpex_api import NIBLIT_SERPEX_TOOL as _NIBLIT_SERPEX_TOOL
    _SERPEX_TOOL_AVAILABLE = True
except Exception as _e:
    log.debug(f"niblit_serpex_search unavailable: {_e}")
    _niblit_serpex_search = None  # type: ignore[assignment]
    _NIBLIT_SERPEX_TOOL = None  # type: ignore[assignment]
    _SERPEX_TOOL_AVAILABLE = False

try:
    from niblit_memory import LocalDB, _writable_path as _mem_writable_path
except Exception as _e:
    log.warning(f"LocalDB unavailable: {_e}")
    LocalDB = None
    def _mem_writable_path(filename, _env_var=None):  # type: ignore[misc]
        return filename
# pylint: enable=invalid-name


# ── Phase 14: Multi-Agent Internal Debate Layer ───────────────────────────────
#
# Three internal agents (conservative / balanced / creative) each propose a
# response routing strategy for every think() call.  The agent with the highest
# accumulated trust score wins; its strategy is applied and its trust is updated
# via a simple TD rule after the response quality is scored.
#
# conservative — prefer local/offline brain; avoid external calls; shorter answers
# balanced     — default routing; unchanged baseline behaviour
# creative     — prefer cloud/RAG-augmented path; encourage richer answers
#
# Trust scores start at 0.5 and evolve within [0.05, 0.95].
# Set BRAIN_DEBATE_ENABLED=0 in the environment to bypass the debate layer.
# ---------------------------------------------------------------------------

BRAIN_DEBATE_ENABLED: bool = (
    os.environ.get("BRAIN_DEBATE_ENABLED", "1").lower() not in ("0", "false", "no")
)
BRAIN_DEBATE_TRUST_LR: float = float(os.environ.get("BRAIN_DEBATE_TRUST_LR", "0.05"))

_BRAIN_DEBATE_TRUST: Dict[str, float] = {
    "conservative": 0.5,
    "balanced": 0.5,
    "creative": 0.5,
}
_brain_debate_last_winner: str = ""
_brain_debate_lock = threading.Lock()


def _build_brain_debate_proposals(
    user_input: str,
    llm_enabled: bool,
) -> Dict[str, Dict[str, Any]]:
    """Build one routing-strategy proposal per internal debate agent.

    Each proposal is a dict of hint flags passed to :meth:`NiblitBrain.think`:

    conservative — prefer offline path (local brain / KB only); no cloud calls
    balanced     — use the default routing logic unchanged
    creative     — prefer cloud + RAG augmentation; richer context

    Returns ``{"conservative": {...}, "balanced": {...}, "creative": {...}}``.
    """
    base: Dict[str, Any] = {"llm_enabled": llm_enabled, "user_input": user_input}
    return {
        "conservative": {
            **base,
            "prefer_local": True,
            "use_rag": False,
            "rationale": f"DEBATE/conservative({user_input[:30]})",
        },
        "balanced": {
            **base,
            "prefer_local": False,
            "use_rag": True,
            "rationale": f"DEBATE/balanced({user_input[:30]})",
        },
        "creative": {
            **base,
            "prefer_local": False,
            "use_rag": True,
            "augment_context": True,
            "rationale": f"DEBATE/creative({user_input[:30]})",
        },
    }


def _brain_debate_vote(
    proposals: Dict[str, Dict[str, Any]],
    agent_trust: Dict[str, float],
) -> tuple:
    """Select the winning proposal by highest agent trust.

    ``balanced`` is the tiebreaker when scores are equal.
    Returns ``(winner_name, winning_proposal)``.
    """
    if not proposals:
        return ("balanced", {"rationale": "DEBATE: no proposals"})

    best_agent = max(
        proposals.keys(),
        key=lambda a: (agent_trust.get(a, 0.5), a == "balanced"),
    )
    winner = proposals[best_agent]

    votes_summary = " | ".join(
        f"{a}={agent_trust.get(a, 0.5):.3f}" for a in sorted(proposals.keys())
    )
    winner["rationale"] = (
        f"DEBATE_WIN/{best_agent}[{votes_summary}]→{winner.get('rationale', '')}"
    )
    return (best_agent, winner)


def _update_brain_debate_trust(winner: str, outcome: float) -> None:
    """Update *winner*'s trust score using a TD-style rule.

    ``outcome`` should be in ``[0, 1]``; 1.0 = excellent response,
    0.0 = poor or failed response.  Values near 0.5 leave trust unchanged.

    ``new_trust = clamp(old_trust + BRAIN_DEBATE_TRUST_LR × (outcome − 0.5))``
    """
    global _brain_debate_last_winner  # pylint: disable=global-statement
    with _brain_debate_lock:
        old = _BRAIN_DEBATE_TRUST.get(winner, 0.5)
        new = max(0.05, min(0.95, old + BRAIN_DEBATE_TRUST_LR * (outcome - 0.5)))
        _BRAIN_DEBATE_TRUST[winner] = round(new, 4)
        _brain_debate_last_winner = ""  # consumed


def get_brain_debate_status() -> Dict[str, Any]:
    """Return a dict summarising the current debate-layer state."""
    return {
        "debate_enabled": BRAIN_DEBATE_ENABLED,
        "brain_debate_trust_lr": BRAIN_DEBATE_TRUST_LR,
        "debate_agent_trust": dict(_BRAIN_DEBATE_TRUST),
        "last_debate_winner": _brain_debate_last_winner,
    }


# ─────────────────────────────────────────────────────────────────────────────

# ───────── Memory Adapter ─────────
class _DBMemoryAdapter:
    """Adapter for backward compatibility with old memory interfaces."""

    def __init__(self, memory, db_path=""):
        self._memory = memory
        _path = db_path or _mem_writable_path("niblit.db")
        self._db = LocalDB(_path) if LocalDB else None

    def __getattr__(self, name):
        return getattr(self._memory, name)

    def store_learning(self, entry):
        """Store a learning entry, delegating to memory or local DB."""
        if hasattr(self._memory, "store_learning"):
            return self._memory.store_learning(entry)
        if self._db:
            self._db.add_entry("learning", entry)
        return None

    def recall(self, query, limit=5):
        """Recall entries matching *query* from memory or local DB."""
        if hasattr(self._memory, "recall"):
            return self._memory.recall(query, limit)
        if not self._db:
            return []
        results = []
        for item in reversed(self._db.get_log()):
            val = str(item.get("value", ""))
            if query.lower() in val.lower():
                results.append(item)
            if len(results) >= limit:
                break
        return results

    def get_preferences(self):
        """Return stored user preferences."""
        if hasattr(self._memory, "get_preferences"):
            return self._memory.get_preferences()
        return {}

    def store_preferences(self, prefs):
        """Persist user preferences, delegating to memory."""
        if hasattr(self._memory, "store_preferences"):
            return self._memory.store_preferences(prefs)
        return None


# ───────── NiblitCloudBrain ─────────

class NiblitCloudBrain:
    """Wrapper for a remote Niblit cloud-server inference endpoint.

    Connects to a niblit-cloud-server instance (a dedicated Niblit deployment
    configured for inference) and proxies LLM generation requests to it.

    The wrapper tries endpoints in this order for each request:

    1. ``POST /v1/chat/completions`` — OpenAI-compatible format (returned by
       the ``/v1/chat/completions`` route added to ``app.py``).
    2. ``POST /chat/completions`` — alternate OpenAI path.
    3. ``POST /chat`` — Niblit native API (``{"text": "..."}`` →
       ``{"reply": "..."}``) exposed by all Niblit deployments.

    Designed for Fly.io deployments where:
    - Main Niblit app runs on port 8080 (uvicorn / ``app.py``).
    - niblit-cloud-server provides inference at ``NIBLIT_LLAMA_SERVER_URL``
      (default ``http://0.0.0.0:8000``).

    Environment variables
    ---------------------
    NIBLIT_CLOUD_SERVER_URL
        Base URL of the cloud server.
        Default: ``https://niblit-cloud-server.fly.dev``
    NIBLIT_LLAMA_SERVER_TIMEOUT
        Per-request HTTP timeout in seconds.
        Default: ``300``
    NIBLIT_API_KEY
        Optional API key forwarded as ``X-API-Key`` header.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
        api_key: Optional[str] = None,
    ) -> None:
        import urllib.request as _ur  # noqa: F401 — ensure available in methods

        self.base_url = (
            base_url
            or os.environ.get(
                "NIBLIT_CLOUD_SERVER_URL",
                os.environ.get("NIBLIT_LLAMA_SERVER_URL", "http://127.0.0.1:8000"),
            )
        ).rstrip("/")
        self.timeout = int(
            timeout
            if timeout is not None
            else os.environ.get("NIBLIT_LLAMA_SERVER_TIMEOUT", "60")
        )
        self.api_key = api_key or os.environ.get("NIBLIT_API_KEY", "")
        self._available: Optional[bool] = None

    # ── Connectivity ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Return ``True`` if the cloud server is reachable at ``/health``."""
        if self._available is None:
            self._available = self._probe()
        return bool(self._available)

    def reset_probe(self) -> None:
        """Force re-probe on the next :meth:`is_available` call."""
        self._available = None

    def _probe(self) -> bool:
        import urllib.request
        try:
            req = urllib.request.Request(self.base_url + "/health", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return 200 <= resp.status < 400
        except Exception:
            return False

    # ── Headers ───────────────────────────────────────────────────────────────

    def _headers(self) -> Dict[str, str]:
        h: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["X-API-Key"] = self.api_key
        return h

    # ── Generation ───────────────────────────────────────────────────────────

    def chat(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = _DEFAULT_CLOUD_MAX_TOKENS,
    ) -> str:
        """Send a generation request to the cloud server and return the text.

        Tries ``POST /v1/chat/completions`` (OpenAI format), then
        ``POST /chat/completions``, then ``POST /chat`` (Niblit native).
        Returns an error string on failure — never raises.
        """
        # pylint: disable=too-many-locals
        import json as _json
        import urllib.error
        import urllib.request

        messages: list = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        openai_payload = _json.dumps(
            {"model": "niblit", "messages": messages, "max_tokens": max_tokens}
        ).encode("utf-8")

        for path in ("/v1/chat/completions", "/chat/completions"):
            req = urllib.request.Request(
                self.base_url + path,
                data=openai_payload,
                method="POST",
                headers=self._headers(),
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = _json.loads(resp.read().decode("utf-8"))
                content = data["choices"][0]["message"]["content"]
                log.debug("[NiblitCloudBrain] %s → %r", path, content[:60])
                return content.strip() or "[NiblitCloudBrain: empty response]"
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    continue
                log.debug("[NiblitCloudBrain] %s HTTPError: %s", path, exc)
                return "[NiblitCloudBrain error: HTTP error on inference endpoint]"
            except Exception:
                pass

        # Niblit native /chat fallback
        text_input = (system_prompt + "\n\n" + prompt) if system_prompt else prompt
        niblit_payload = _json.dumps({"text": text_input}).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/chat",
            data=niblit_payload,
            method="POST",
            headers=self._headers(),
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            reply = (
                data.get("reply")
                or data.get("response")
                or data.get("content")
                or data.get("text")
                or ""
            )
            log.debug("[NiblitCloudBrain] /chat → %r", reply[:60])
            return reply.strip() or "[NiblitCloudBrain: empty reply]"
        except Exception as exc:
            log.debug("[NiblitCloudBrain] /chat error: %s", exc)
            return "[NiblitCloudBrain error: unexpected error calling /chat]"

    def ask(
        self,
        prompt: str,
        context: str = "",
        system_prompt: Optional[str] = None,
        max_tokens: int = _DEFAULT_CLOUD_MAX_TOKENS,
    ) -> str:
        """Convenience wrapper: prepend *context* then call :meth:`chat`."""
        full = (context.strip() + "\n\n" + prompt.strip()) if context.strip() else prompt
        return self.chat(full, system_prompt=system_prompt, max_tokens=max_tokens)


# Lazily initialised singleton for callers that import NiblitCloudBrain.
_cloud_brain_instance: Optional[NiblitCloudBrain] = None
_cloud_brain_lock = threading.Lock()


def get_niblit_cloud_brain() -> NiblitCloudBrain:
    """Return the process-wide :class:`NiblitCloudBrain` singleton."""
    global _cloud_brain_instance  # pylint: disable=global-statement
    if _cloud_brain_instance is None:
        with _cloud_brain_lock:
            if _cloud_brain_instance is None:
                _cloud_brain_instance = NiblitCloudBrain()
    return _cloud_brain_instance


def set_cloud_brain_url(url: str) -> NiblitCloudBrain:
    """Switch the cloud-brain server URL at runtime.

    Updates ``NIBLIT_CLOUD_SERVER_URL`` in the environment and re-points
    (or recreates) the :class:`NiblitCloudBrain` singleton to *url*.
    The new URL is also written to the environment so that any child
    processes inherit it.

    Parameters
    ----------
    url:
        Base URL of the target server (e.g. ``"https://niblit-cloud-server.fly.dev"``).

    Returns
    -------
    The updated :class:`NiblitCloudBrain` singleton.
    """
    global _cloud_brain_instance  # pylint: disable=global-statement

    url = url.strip().rstrip("/")
    os.environ["NIBLIT_CLOUD_SERVER_URL"] = url

    with _cloud_brain_lock:
        if _cloud_brain_instance is None:
            _cloud_brain_instance = NiblitCloudBrain(base_url=url)
        else:
            _cloud_brain_instance.base_url = url
            _cloud_brain_instance.reset_probe()

    log.info("[NiblitCloudBrain] server URL updated to %s", url)
    return _cloud_brain_instance


# ───────── BrainTrainer ─────────
class BrainTrainer:
    # pylint: disable=too-many-instance-attributes
    """
    Autonomous Brain Trainer and Updater.

    Collects research data and learned interactions from autonomous_learning
    and stores them as LLM training context. Enriches every brain query with
    relevant accumulated knowledge so the brain continuously improves without
    requiring a GPU fine-tuning run.

    Key capabilities:
    - Record chat exchanges (user prompt + assistant response) as training pairs
    - Ingest research data and KB facts from AutonomousLearningEngine
    - Build a dynamic system-prompt context from accumulated training data
    - Provide topic-specific context snippets for each incoming query
    - Live update and persist cognitive domain improvements (language,
      communication, reasoning, calculating, chat completions, responses)
    - Persist all training data to memory for use across sessions
    """

    _TRAINING_KEY = "brain_trainer:llm_data"
    _MAX_PAIRS = 500          # cap stored pairs to avoid unbounded growth
    _CONTEXT_PAIRS = 8        # pairs injected into each think() call
    _CONTEXT_FACTS = 5        # knowledge facts injected per query

    # Core cognitive domains tracked and improved during autonomous runtime
    COGNITIVE_TOPICS = [
        "language",
        "communication",
        "reasoning",
        "calculating",
        "chat_completions",
        "responses",
    ]

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(self, memory, knowledge_db=None, self_teacher=None,
                 hybrid_manager=None, self_monitor=None, kernel=None,
                 evaluation_engine=None, quality_feedback=None,
                 provider_manager=None, runtime_telemetry_provider=None):
        self.memory = memory
        self.knowledge_db = knowledge_db
        self.self_teacher = self_teacher
        self.hybrid_manager = hybrid_manager
        self.self_monitor = self_monitor
        self.kernel = kernel
        self.evaluation_engine = evaluation_engine
        self.quality_feedback = quality_feedback
        self.provider_manager = provider_manager
        self.runtime_telemetry_provider = runtime_telemetry_provider
        self._pairs: list = []          # in-memory training pairs
        self._facts: list = []          # in-memory knowledge facts
        # Per-domain cognitive data store: domain → list of update dicts
        self._cognitive: dict = {d: [] for d in self.COGNITIVE_TOPICS}
        self._lock = threading.Lock()
        self._load_from_memory()

    # ── Persistence ──────────────────────────────────────────────────────
    def _load_from_memory(self):
        """Restore training data from persistent memory on start-up."""
        try:
            if self.memory and hasattr(self.memory, "recall"):
                items = self.memory.recall(self._TRAINING_KEY, limit=self._MAX_PAIRS)
                for item in items:
                    if isinstance(item, dict):
                        p = item.get("value") or item.get("input")
                        if isinstance(p, dict) and "prompt" in p and "response" in p:
                            self._pairs.append(p)
        except Exception as _e:
            log.debug(f"[BrainTrainer] load failed: {_e}")

    def _persist_pair(self, pair: dict):
        """Persist a single training pair to memory."""
        try:
            if self.memory and hasattr(self.memory, "store_learning"):
                self.memory.store_learning({
                    "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "input": self._TRAINING_KEY,
                    "value": pair,
                    "source": "brain_trainer",
                })
        except Exception as _e:
            log.debug(f"[BrainTrainer] persist failed: {_e}")

    # ── Training data ingestion ───────────────────────────────────────────
    def record_exchange(self, user_prompt: str, assistant_response: str):
        """Store a chat exchange as a training pair."""
        pair = {
            "prompt": str(user_prompt)[:500],
            "response": str(assistant_response)[:500],
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        with self._lock:
            self._pairs.append(pair)
            if len(self._pairs) > self._MAX_PAIRS:
                self._pairs = self._pairs[-self._MAX_PAIRS:]
        self._persist_pair(pair)
        # ── HybridQdrantManager upsert (additive) ────────────────────────────────
        if self.hybrid_manager:
            try:
                combined = f"User: {user_prompt[:500]}\nAssistant: {assistant_response[:500]}"
                self.hybrid_manager.upsert(
                    combined,
                    {"type": "exchange"},
                    collection="niblit_brain_training"
                )
            except Exception as _hq_e:
                log.debug("[BrainTrainer] exchange hybrid upsert failed: %s", _hq_e)

    def ingest_research(self, topic: str, text: str):
        """Ingest a research snippet from autonomous_learning into training data."""
        # Sanitize: strip control chars and cap length so KB noise never
        # corrupts GGUF tokeniser input downstream.
        fact = {
            "topic": _sanitize_text(str(topic), max_chars=120),
            "text": _sanitize_text(str(text), max_chars=_KB_TEXT_MAX_CHARS),
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        with self._lock:
            self._facts.append(fact)
            if len(self._facts) > self._MAX_PAIRS:
                self._facts = self._facts[-self._MAX_PAIRS:]
        try:
            if self.memory and hasattr(self.memory, "store_learning"):
                self.memory.store_learning({
                    "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "input": f"brain_trainer:fact:{topic}",
                    "value": fact,
                    "source": "brain_trainer:research",
                })
        except Exception as _e:
            log.debug(f"[BrainTrainer] ingest_research persist failed: {_e}")
        # ── HybridQdrantManager upsert (additive) ────────────────────────────────
        if self.hybrid_manager:
            try:
                self.hybrid_manager.upsert(
                    text[:2000],
                    {"type": "brain_training", "topic": topic},
                    collection="niblit_brain_training"
                )
            except Exception as _hq_e:
                log.debug("[BrainTrainer] hybrid_manager upsert failed: %s", _hq_e)

    def ingest_knowledge_db(self, limit: int = 50):
        """Pull recent facts from KnowledgeDB into the trainer's fact store."""
        if not self.knowledge_db:
            return
        try:
            if hasattr(self.knowledge_db, "get_acquired_data"):
                items = self.knowledge_db.get_acquired_data("ale_learned", limit=limit)
            elif hasattr(self.knowledge_db, "recall"):
                items = self.knowledge_db.recall("ale_learned", limit=limit)
            else:
                return
            for item in (items or []):
                if isinstance(item, dict):
                    text = item.get("value") or item.get("content") or item.get("input") or ""
                    topic = item.get("key") or item.get("topic") or "knowledge"
                    if text:
                        self.ingest_research(str(topic), str(text))
        except Exception as _e:
            log.debug(f"[BrainTrainer] ingest_knowledge_db failed: {_e}")

    # ── Context generation ────────────────────────────────────────────────

    # Map query keywords to cognitive domains for targeted context
    _DOMAIN_KEYWORDS: Dict[str, List[str]] = {
        "language":        ["language", "grammar", "syntax", "word", "text", "linguistic"],
        "communication":   ["communicat", "talk", "convers", "speak", "tell", "explain"],
        "reasoning":       ["reason", "logic", "infer", "deduc", "analyz", "think", "why", "how"],
        "calculating":     ["calculat", "math", "number", "add", "subtract", "multipl",
                            "divid", "equat", "sum", "total", "percent"],
        "chat_completions": ["chat", "complet", "prompt", "llm", "model", "api", "gpt"],
        "responses":       ["respond", "response", "answer", "reply", "output", "generat"],
    }

    def _get_cognitive_context_lines(self, q_lower: str) -> List[str]:
        """Return context lines for matching cognitive domains."""
        try:
            with self._lock:
                matches = [
                    (domain, self._cognitive[domain][-1])
                    for domain, keywords in self._DOMAIN_KEYWORDS.items()
                    if any(kw in q_lower for kw in keywords)
                    and self._cognitive.get(domain)
                ]
            if not matches:
                return []
            lines = ["[Cognitive knowledge]"]
            for domain, entry in matches:
                data = _sanitize_text(entry.get("data", ""), max_chars=200)
                lines.append(f"- {domain}: {data}")
            lines.append("")
            return lines
        except Exception:
            return []

    def _get_facts_context_lines(self, q_lower: str) -> List[str]:
        """Return context lines for relevant knowledge facts."""
        try:
            prefix = q_lower[:20]
            with self._lock:
                relevant = [
                    f for f in self._facts
                    if q_lower in f.get("topic", "").lower()
                    or prefix in f.get("text", "").lower()
                ]
                relevant = relevant[-self._CONTEXT_FACTS:]
            if not relevant:
                return []
            lines = ["[Learned knowledge]"]
            for f in relevant:
                topic = _sanitize_text(f.get("topic", ""), max_chars=80)
                text = _sanitize_text(f.get("text", ""), max_chars=200)
                lines.append(f"- {topic}: {text}")
            lines.append("")
            return lines
        except Exception:
            return []

    def _get_pairs_context_lines(self) -> List[str]:
        """Return context lines for recent conversation exchanges."""
        try:
            with self._lock:
                recent = self._pairs[-self._CONTEXT_PAIRS:]
            if not recent:
                return []
            lines = ["[Recent conversations]"]
            for p in recent:
                prompt = _sanitize_text(p.get("prompt", ""), max_chars=200)
                response = _sanitize_text(p.get("response", ""), max_chars=200)
                lines.append(f"User: {prompt}")
                lines.append(f"Assistant: {response}")
            lines.append("")
            return lines
        except Exception:
            return []

    def get_context_for(self, query: str) -> str:
        """
        Build a context prefix for the given query using stored training data.

        Includes relevant knowledge facts, cognitive domain data, and recent
        conversation exchanges.  Returns an empty string when no data matches.

        The total output is capped at ``_CONTEXT_MAX_CHARS`` characters so that
        small GGUF models (0.5B) are never given more context than their context
        window can accommodate alongside the system prompt and user message.
        """
        q_lower = query.lower()
        lines: List[str] = []
        lines.extend(self._get_cognitive_context_lines(q_lower))
        lines.extend(self._get_facts_context_lines(q_lower))
        lines.extend(self._get_pairs_context_lines())
        if not lines:
            return ""
        result = "\n".join(lines)
        # Apply total context budget: truncate at a line boundary to avoid
        # sending a partial line that could confuse the tokeniser.
        if len(result) > _CONTEXT_MAX_CHARS:
            _JOINER_LEN = 1  # one "\n" character inserted between lines by str.join
            truncated_lines: List[str] = []
            budget = _CONTEXT_MAX_CHARS
            for line in lines:
                needed = len(line) + _JOINER_LEN
                if budget - needed < 0:
                    break
                truncated_lines.append(line)
                budget -= needed
            result = "\n".join(truncated_lines)
        return result

    def get_llm_data_summary(self) -> dict:
        """Return a summary of the accumulated LLM training data."""
        with self._lock:
            cognitive_counts = {d: len(v) for d, v in self._cognitive.items()}
            return {
                "training_pairs": len(self._pairs),
                "knowledge_facts": len(self._facts),
                "cognitive_domains": cognitive_counts,
                "latest_pair_ts": self._pairs[-1].get("ts") if self._pairs else None,
                "latest_fact_ts": self._facts[-1].get("ts") if self._facts else None,
            }

    # ── Cognitive domain live updates ─────────────────────────────────────
    def update_cognitive_domain(self, domain: str, data: str):
        """
        Register and persist a live improvement for the given cognitive domain.

        Called by ALE step 25 (CognitiveEnhancement) during each autonomous
        cycle to immediately register language, communication, reasoning,
        calculating, chat_completions, and responses improvements in the brain.

        The update is:
        1. Stored in the in-memory `_cognitive` store for fast context retrieval.
        2. Ingested into `_facts` so `get_context_for()` can use it.
        3. Persisted to memory storage so it survives restarts.
        """
        domain = str(domain).lower().replace(" ", "_")
        entry = {
            "domain": domain,
            "data": str(data)[:600],
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        with self._lock:
            if domain not in self._cognitive:
                self._cognitive[domain] = []
            self._cognitive[domain].append(entry)
            # Cap per-domain history to 100 entries
            if len(self._cognitive[domain]) > 100:
                self._cognitive[domain] = self._cognitive[domain][-100:]

        # Also push to general facts store so context retrieval sees it
        self.ingest_research(f"cognitive:{domain}", data)

        # Persist to memory immediately
        try:
            if self.memory and hasattr(self.memory, "store_learning"):
                self.memory.store_learning({
                    "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "input": f"brain_trainer:cognitive:{domain}",
                    "value": entry,
                    "source": "brain_trainer:cognitive",
                })
        except Exception as _e:
            log.debug(f"[BrainTrainer] cognitive persist failed for {domain}: {_e}")

        log.debug("[BrainTrainer] cognitive domain updated live: %s", domain)

    def ingest_evaluation_feedback(
        self,
        query: str,
        response: str,
        quality_score: float,
        *,
        provider: str = "",
        telemetry: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Feed evaluation/telemetry outcomes back into learning memory."""
        score = max(0.0, min(1.0, float(quality_score)))
        record = {
            "query": _sanitize_text(query, max_chars=200),
            "response": _sanitize_text(response, max_chars=200),
            "quality_score": score,
            "provider": str(provider or "unknown"),
            "telemetry": telemetry or {},
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        self.ingest_research("evaluation_feedback", str(record))
        if self.knowledge_db and hasattr(self.knowledge_db, "add_fact"):
            try:
                self.knowledge_db.add_fact(
                    f"brain_trainer:evaluation:{int(datetime.datetime.now().timestamp())}",
                    record,
                    tags=["brain_trainer", "evaluation", "quality_feedback"],
                )
            except Exception:
                pass
        if provider:
            self.update_cognitive_domain(
                "responses",
                f"provider={provider} quality={score:.2f}",
            )

    def get_cognitive_summary(self) -> dict:
        """Return per-domain counts and latest update timestamps."""
        with self._lock:
            return {
                domain: {
                    "updates": len(entries),
                    "latest_ts": entries[-1].get("ts") if entries else None,
                }
                for domain, entries in self._cognitive.items()
            }

    def _apply_cognitive_kb_item(self, domain: str, item: Any) -> None:
        """Apply a single KnowledgeDB item to the cognitive domain store."""
        if not isinstance(item, dict):
            return
        text = (
            item.get("value") or item.get("content")
            or item.get("input") or ""
        )
        if text:
            self.update_cognitive_domain(domain, str(text)[:400])

    def _sync_cognitive_kb_domains(self) -> None:
        """Refresh cognitive-domain memories from KnowledgeDB without altering flow."""
        if not self.knowledge_db:
            return
        for domain in self.COGNITIVE_TOPICS:
            try:
                if hasattr(self.knowledge_db, "recall"):
                    items = self.knowledge_db.recall(f"cognitive:{domain}", limit=20)
                    for item in (items or []):
                        self._apply_cognitive_kb_item(domain, item)
            except Exception as exc:
                log.debug("[BrainTrainer] cognitive KB pull failed for %s: %s", domain, exc)

    def _ingest_latest_evaluation_feedback(self) -> None:
        """Mirror the latest evaluation signal into trainer memory."""
        try:
            if self.evaluation_engine and hasattr(self.evaluation_engine, "get_history"):
                history = self.evaluation_engine.get_history()
                if history:
                    latest = history[-1]
                    self.ingest_evaluation_feedback(
                        latest.get("user_input", ""),
                        "",
                        float(latest.get("quality_score", 0.5)),
                        provider=str(latest.get("chosen_advisor", "")),
                    )
        except Exception as exc:
            log.debug("[BrainTrainer] evaluation ingest failed: %s", exc)

    def _ingest_quality_feedback(self) -> None:
        """Publish recent quality scores into the reasoning cognitive domain."""
        try:
            if self.quality_feedback and hasattr(self.quality_feedback, "status"):
                q_status = self.quality_feedback.status()
                self.update_cognitive_domain(
                    "reasoning",
                    (
                        f"quality_recent_avg={q_status.get('recent_avg_score')} "
                        f"total={q_status.get('total_scores')}"
                    ),
                )
        except Exception as exc:
            log.debug("[BrainTrainer] quality feedback ingest failed: %s", exc)

    def _ingest_runtime_telemetry(self) -> None:
        """Capture runtime telemetry as communication-domain cognition."""
        try:
            if self.runtime_telemetry_provider and hasattr(self.runtime_telemetry_provider, "status"):
                telemetry = self.runtime_telemetry_provider.status()
                self.update_cognitive_domain(
                    "communication",
                    f"runtime_telemetry={_sanitize_text(str(telemetry), max_chars=180)}",
                )
        except Exception as exc:
            log.debug("[BrainTrainer] runtime telemetry ingest failed: %s", exc)

    def run_training_cycle(self) -> str:
        """
        Execute one training cycle: pull from knowledge_db and refresh all data.

        Called by AutonomousLearningEngine step 24 (BrainTraining).
        Returns a summary string.
        """
        if self.self_teacher:
            self.run_self_teaching(topics_limit=20)

        self.ingest_selfteach(limit=20)
        before = len(self._pairs) + len(self._facts)
        self.ingest_knowledge_db(limit=100)
        self._sync_cognitive_kb_domains()

        after = len(self._pairs) + len(self._facts)
        added = after - before
        cognitive_total = sum(len(v) for v in self._cognitive.values())
        self._ingest_latest_evaluation_feedback()
        self._ingest_quality_feedback()
        self._ingest_runtime_telemetry()
        summary = (
            f"BrainTrainer cycle: {added} new items ingested, "
            f"total={after}, cognitive_updates={cognitive_total}"
        )
        log.info("[BrainTrainer] %s", summary)
        return summary

    def ingest_selfteach(self, limit=20):
        """
        Ingest self-teaching facts and quizzes from knowledge_db.
        Teaches BrainTrainer from self_teach_summary: / self_teach_quiz: KB keys.
        """
        if not self.knowledge_db:
            return 0
        count = 0
        try:
            facts = []
            if hasattr(self.knowledge_db, "recall"):
                facts.extend(self.knowledge_db.recall("self_teach_summary", limit=limit))
                facts.extend(self.knowledge_db.recall("self_teach_quiz", limit=limit))
            elif hasattr(self.knowledge_db, "list_facts"):
                all_facts = self.knowledge_db.list_facts(limit*2)
                for f in all_facts:
                    key = f.get("key", "") if isinstance(f, dict) else ""
                    if key.startswith("self_teach_summary:") or key.startswith("self_teach_quiz:"):
                        facts.append(f)
            for item in facts:
                text = (
                    (item.get("value") or item.get("summary") or item.get("content") or "")
                    if isinstance(item, dict) else str(item)
                )
                topic = item.get("key") or item.get("topic") or "" if isinstance(item, dict) else ""
                if text:
                    self.ingest_research(topic, text)
                    count += 1
        except Exception as e:
            log.debug(f"[BrainTrainer] ingest_selfteach failed: {e}")
        return count

    def run_self_teaching(self, topics_limit=20):
        """
        Uses SelfTeacher to deeply learn each unique topic in memory/knowledge_db.

        Steps:
        - Gathers recent unique topics from facts in the knowledge DB.
        - Passes each topic to SelfTeacher to generate and ingest a lesson/summary.
        - Handles KB namespace prefixes (e.g. "self_teach_summary:topic:timestamp").
        - Skips duplicate or empty topics.
        - Limits number of taught topics per cycle.
        - Logs outcomes for each topic.
        - Returns a concise summary string for diagnostics or UI.
        """
        logger = logging.getLogger("BrainTrainer")
        if not self.self_teacher or not self.knowledge_db:
            msg = "SelfTeacher or knowledge_db unavailable."
            logger.warning(msg)
            return msg

        # 1. Gather facts from the KB/factbase
        try:
            if hasattr(self.knowledge_db, "list_facts"):
                facts = self.knowledge_db.list_facts(limit=100)
            elif hasattr(self.knowledge_db, "recall"):
                facts = self.knowledge_db.recall("", limit=100)
            else:
                facts = []
        except Exception as e:
            msg = f"Failed to load facts: {e}"
            logger.error(msg)
            return msg

        # 2. Select unique, non-empty topics (strip prefix if present)
        seen = set()
        taught = []
        for fact in facts:
            topic = ""
            if isinstance(fact, dict):
                topic = fact.get("topic") or fact.get("key") or ""
                if topic:
                    topic = topic.split(":")[-1]
            if not topic or topic in seen:
                continue
            seen.add(topic)

            # 3. Teach about this topic using SelfTeacher
            try:
                summary = self.self_teacher.teach(topic)
                result_line = f"✓ {topic}: {summary[:80]}"
                logger.info(f"[SelfTeaching] {result_line}")
            except Exception as ex:
                result_line = f"✗ {topic}: fail ({ex})"
                logger.warning(f"[SelfTeaching] {result_line}")
            taught.append(result_line)

            if len(taught) >= topics_limit:
                break

        msg = f"Self-teaching: {len(taught)} topic(s) completed."
        logger.info(msg)
        if taught:
            msg += "\n" + "\n".join(taught)
        return msg

# ───────── NiblitBrain ─────────
class NiblitBrain:
    """
    NiblitBrain with production improvements.

    IMPORTANT: This module handles GENERAL CHAT ONLY.
    Commands are routed to niblit_core.py.

    Features:
    - Circuit breakers for fault tolerance
    - Telemetry and metrics
    - Rate limiting
    - Multi-level caching
    - Batch learning
    - Event sourcing
    - Structured logging
    - 100% backward compatible
    """
    # pylint: disable=too-many-instance-attributes

    def __init__(self, memory, llm_enabled=True, internet=None, enable_improvements=True):
        # pylint: disable=too-many-branches,too-many-statements,too-many-locals
        self.memory = memory
        self.llm_enabled = llm_enabled
        self.enable_improvements = enable_improvements

        # Wrap memory if LocalDB exists
        if LocalDB and memory is not None:
            try:
                self.memory = _DBMemoryAdapter(memory)
            except Exception as e:
                log.warning(f"DB adapter attach failed: {e}")

        # Preferences
        try:
            prefs = self.memory.get_preferences()
            if not prefs:
                prefs = {"tone": "neutral", "interaction_style": "casual"}
            self.memory.store_preferences(prefs)
        except AttributeError:
            prefs = {"tone": "neutral", "interaction_style": "casual"}
        self.preferences = prefs

        # HFBrain
        try:
            if HFBrain:
                self.hf_brain = HFBrain(self.memory)
                log.debug("HFBrain loaded successfully")
            else:
                self.hf_brain = None
        except RuntimeError as e:
            log.warning(f"HFBrain failed to initialize: {e}")
            self.hf_brain = None

        # InternetManager injection
        self.internet = internet or (InternetManager(db=self.memory) if InternetManager else None)

        # Self Modules (for command handling via core)
        self.self_researcher = SelfResearcher(self.memory) if SelfResearcher else None
        if self.self_researcher:
            self.self_researcher.internet = self.internet

        self.self_healer = SelfHealer(self.memory) if SelfHealer else None

        try:
            if SelfIdeaImplementation and self.memory:
                self.self_idea = SelfIdeaImplementation(self.memory)
                # Wire in researcher and internet to self_idea
                if hasattr(self.self_idea, 'researcher'):
                    self.self_idea.researcher = self.self_researcher
                if hasattr(self.self_idea, 'internet'):
                    self.self_idea.internet = self.internet
                log.debug("SelfIdeaImplementation loaded and wired successfully")
            else:
                self.self_idea = None
        except Exception as e:
            log.warning(f"Failed to init SelfIdeaImplementation: {e}")
            self.self_idea = None

        self.reflect = ReflectModule(self.memory) if ReflectModule else None
        if self.reflect:
            log.debug("ReflectModule loaded successfully")

        # SelfTeacher Wiring
        self.self_teacher = None
        if SelfTeacher:
            self.self_teacher = SelfTeacher(
                db=self.memory,
                researcher=self.self_researcher,
                reflector=self.reflect,
                learner=self.self_idea
            )
            log.debug("SelfTeacher loaded successfully")

        # Inject teacher + learner into ReflectModule
        if self.reflect:
            if self.self_teacher:
                self.reflect.self_teacher = self.self_teacher
            if self.self_idea:
                self.reflect.learner = self.self_idea

        # ─────── IMPROVEMENTS INITIALIZATION ───────
        if self.enable_improvements:
            self._init_improvements()

        # ─────── BRAIN TRAINER ───────
        # Pass memory as knowledge_db if it supports add_fact / recall (e.g. KnowledgeDB adapter)
        _kdb = self.memory if (self.memory and hasattr(self.memory, "add_fact")) else None
        self.brain_trainer = BrainTrainer(self.memory, knowledge_db=_kdb, self_teacher=self.self_teacher)
        log.debug("[BRAIN] BrainTrainer initialized")

        # ─────── SERPEX TOOL ───────
        # Expose niblit_serpex_search() as a callable tool and its GPT definition
        # so that the brain (or an orchestrator) can invoke or register it.
        self.serpex_tool_fn = _niblit_serpex_search
        self.serpex_tool_def = _NIBLIT_SERPEX_TOOL
        if _SERPEX_TOOL_AVAILABLE:
            log.debug("[BRAIN] niblit_serpex_search tool registered")

        # ─────── QDRANT INFERENCE PIPELINE ───────
        # SemanticAgent — vector-store backed knowledge retrieval
        self.semantic = None
        try:
            from niblit_agents.semantic_agent import SemanticAgent as _SemanticAgent
            self.semantic = _SemanticAgent()
            log.debug("[BRAIN] SemanticAgent ready (available=%s)", self.semantic.is_available())
        except Exception as _e:
            log.debug("[BRAIN] SemanticAgent unavailable: %s", _e)

        # ClaudeEngine — Anthropic Claude with context injection
        self.claude = None
        try:
            from niblit_models.claude_engine import ClaudeEngine as _ClaudeEngine
            self.claude = _ClaudeEngine()
            log.debug("[BRAIN] ClaudeEngine ready (available=%s)", self.claude.is_available())
        except Exception as _e:
            log.debug("[BRAIN] ClaudeEngine unavailable: %s", _e)

        # LLMProviderManager — routes HF ↔ Anthropic ↔ Qwen with runtime switching
        self.llm_provider_manager = None
        try:
            from modules.llm_provider_manager import get_llm_provider_manager
            self.llm_provider_manager = get_llm_provider_manager()
            self.llm_provider_manager.wire(
                hf_brain=self.hf_brain,
                claude=self.claude,
            )
            log.debug("[BRAIN] LLMProviderManager wired (active=%s)", self.llm_provider_manager.active)
        except Exception as _e:
            log.debug("[BRAIN] LLMProviderManager unavailable: %s", _e)

        # ─────── LOCAL BRAIN (Qwen2.5-0.5B) ───────
        # Primary brain when toggle-llm is off or NIBLIT_BRAIN_MODE=local/offline.
        # Lazy-loaded on first use so startup is not blocked by model download.
        self.local_brain = None
        try:
            from modules.local_brain import get_local_brain
            self.local_brain = get_local_brain()
            log.info("[BRAIN] QwenLocalBrain registered (lazy load on first use)")
        except Exception as _lb_e:
            log.debug("[BRAIN] QwenLocalBrain unavailable: %s", _lb_e)

        if self.llm_provider_manager and self.local_brain is not None:
            try:
                self.llm_provider_manager.wire(local_brain=self.local_brain)
            except Exception as _pm_wire_e:
                log.debug("[BRAIN] LLMProviderManager local brain wire failed: %s", _pm_wire_e)

        # ─────── BRAIN ROUTER ───────
        # Wraps local + cloud brains behind an intelligent routing policy.
        # Cloud callable: try LLMProviderManager, fall back to HFBrain direct.
        self.brain_router = None
        try:
            from modules.brain_router import get_brain_router, reset_brain_router
            reset_brain_router()  # ensure singleton is re-wired with current brains

            _pm  = self.llm_provider_manager
            _hfb = self.hf_brain

            def _cloud_fn(p: str) -> str:
                if _pm:
                    try:
                        return _pm.ask(p) or ""
                    except Exception:
                        pass
                if _hfb:
                    try:
                        return _hfb.ask_single(p) or ""
                    except Exception:
                        pass
                # NiblitCloudBrain: forward to niblit-cloud-server if configured.
                try:
                    _ncb = get_niblit_cloud_brain()
                    if _ncb.is_available():
                        result = _ncb.chat(p)
                        if result and not result.startswith("[NiblitCloudBrain"):
                            return result
                except Exception:
                    pass
                return ""

            def _memory_fn(q: str) -> str:
                try:
                    from modules.graph_rag import get_graph_rag_pipeline
                    res = get_graph_rag_pipeline().query(q, top_k=3)
                    return res.get("context", "") or res.get("system_prompt", "")
                except Exception:
                    return ""

            self.brain_router = get_brain_router(
                local_brain=self.local_brain,
                cloud_brain=_cloud_fn,
                memory_retriever=_memory_fn,
            )
            log.info("[BRAIN] BrainRouter initialised (mode=%s)", self.brain_router.mode)
        except Exception as _br_e:
            log.debug("[BRAIN] BrainRouter init failed: %s", _br_e)

    def get_tools(self):
        """
        Return a list of GPT tool definition dicts for all registered tool functions.

        Returns all tools registered in the module-level :class:`ToolRegistry`
        singleton (``niblit_tools.get_registry()``), which always includes at
        minimum the built-in ``niblit_serpex_search`` tool.  Additional tools
        registered via the ``@tool`` decorator are included automatically.

        Returns:
            List of tool definition dicts suitable for passing to an OpenAI
            chat completion ``tools`` parameter.
        """
        try:
            from niblit_tools.tool_registry import get_registry as _get_registry
            return _get_registry().list_tools()
        except Exception as _exc:
            log.debug("[BRAIN] Failed to get tools from registry: %s", _exc)
        # Fallback: legacy single-tool path
        tools = []
        if self.serpex_tool_def is not None:
            tools.append(self.serpex_tool_def)
        return tools

    def call_tool(self, tool_call: dict) -> str:
        """Dispatch an LLM tool-call response to the matching registered tool.

        Accepts the OpenAI / LangChain tool-call format::

            {
                "name": "niblit_serpex_search",
                "arguments": {"query": "AI news"}
            }

        The ``"arguments"`` value may be a JSON string or a plain dict.

        Args:
            tool_call: Dict with at least a ``"name"`` key and an optional
                       ``"arguments"`` key.

        Returns:
            The tool's return value converted to a string.  A tool that
            returns ``None`` yields an empty string ``""``.  Dispatch
            failures return an error message starting with ``"[ToolError]"``.
        """
        try:
            from niblit_tools.tool_registry import get_registry as _get_registry
            result = _get_registry().dispatch_tool_call(tool_call)
            return str(result) if result is not None else ""
        except KeyError as exc:
            log.warning("[BRAIN] call_tool: unknown tool %s", exc)
            return f"[ToolError] Unknown tool: {exc}"
        except Exception as exc:
            log.warning("[BRAIN] call_tool failed: %s", exc)
            return f"[ToolError] {exc}"

    def process_query(self, query: str) -> dict:
        """
        Full Qdrant inference pipeline: retrieve semantic context then generate
        a response with Claude (falls back to ``think()`` when Claude is unavailable).

        Flow::

            1. SemanticAgent.retrieve_context(query) → context from Qdrant
            2. ClaudeEngine.generate(query, context)  → grounded response
            3. Fallback to self.think(query)           → HF / rule-based response

        Args:
            query: The user's question or task.

        Returns:
            Dict with keys ``"query"``, ``"context_used"``, and ``"response"``.
        """
        context_used = []
        response = ""

        # Step 1: Retrieve semantic memory
        if self.semantic:
            try:
                context_used = self.semantic.retrieve_context(query) or []
            except Exception as _e:
                log.debug("[BRAIN] process_query: context retrieval failed: %s", _e)

        # Step 2: Claude generation with context injection
        if self.claude and self.claude.is_available():
            try:
                response = self.claude.generate(query, context=context_used) or ""
            except Exception as _e:
                log.debug("[BRAIN] process_query: Claude generation failed: %s", _e)

        # Step 3: Fallback to existing think() when Claude unavailable / empty
        if not response:
            try:
                response = self.think(query) or ""
            except Exception as _e:
                log.debug("[BRAIN] process_query: think() fallback failed: %s", _e)

        return {
            "query": query,
            "context_used": context_used,
            "response": response,
        }

    def _init_improvements(self):
        """Initialize all production improvements."""
        # pylint: disable=too-many-branches,too-many-statements
        log.info("[BRAIN-IMPROVEMENTS] Initializing enhancements...")

        # 1. Circuit Breakers for fault tolerance
        try:
            if CircuitBreaker:
                if CircuitBreakerConfig:
                    cb_config = CircuitBreakerConfig(
                        failure_threshold=5,
                        success_threshold=2,
                        timeout_seconds=30,
                    )
                    self.cb_think = CircuitBreaker("brain_think", config=cb_config)
                else:
                    self.cb_think = CircuitBreaker("brain_think", failure_threshold=5)
                log.debug("[BRAIN] Circuit breaker initialized")
            else:
                self.cb_think = None
        except Exception as e:
            log.warning(f"[BRAIN] Circuit breaker init failed: {e}")
            self.cb_think = None

        # 2. Telemetry
        try:
            if TelemetryCollector:
                self.telemetry = TelemetryCollector()
                log.debug("[BRAIN] Telemetry initialized")
            else:
                self.telemetry = None
        except Exception as e:
            log.warning(f"[BRAIN] Telemetry init failed: {e}")
            self.telemetry = None

        # 3. Rate Limiting
        try:
            if RateLimiter:
                self.rate_limiter = RateLimiter(max_requests_per_sec=50)
                log.debug("[BRAIN] Rate limiter initialized")
            else:
                self.rate_limiter = None
        except Exception as e:
            log.warning(f"[BRAIN] Rate limiter init failed: {e}")
            self.rate_limiter = None

        # 4. Multi-level Caching
        try:
            if CacheStrategy:
                self.cache = CacheStrategy()
                log.debug("[BRAIN] Multi-level cache initialized")
            else:
                self.cache = None
        except Exception as e:
            log.warning(f"[BRAIN] Cache strategy init failed: {e}")
            self.cache = None

        # 5. Batch Learning
        try:
            if LearningBatcher:
                self.learning_batcher = LearningBatcher(batch_size=32, flush_interval_seconds=5)
                log.debug("[BRAIN] Learning batcher initialized")
            else:
                self.learning_batcher = None
        except Exception as e:
            log.warning(f"[BRAIN] Learning batcher init failed: {e}")
            self.learning_batcher = None

        # 6. Event Sourcing
        try:
            if EventStore:
                self.event_store = EventStore()
                log.debug("[BRAIN] Event store initialized")
            else:
                self.event_store = None
        except Exception as e:
            log.warning(f"[BRAIN] Event store init failed: {e}")
            self.event_store = None

        # 7. Structured Logging for cognitive trace
        try:
            if StructuredLogger:
                self.structured_log = StructuredLogger("NiblitBrain")
                log.debug("[BRAIN] Structured logger initialized")
            else:
                self.structured_log = None
        except Exception as e:
            log.warning(f"[BRAIN] Structured logger init failed: {e}")
            self.structured_log = None

    # ───────── Learning ─────────
    def learn(self, user_input):
        """
        Store learning with batch processing support.

        Uses LearningBatcher if available for efficient bulk operations.
        """
        # pylint: disable=too-many-branches,too-many-statements,too-many-nested-blocks
        try:
            if hasattr(self.memory, "store_learning"):
                # If InternetManager structured search results exist, store them
                if isinstance(user_input, dict) and "structured_search" in user_input:
                    structured_results = user_input.get("structured_search", [])
                    if isinstance(structured_results, list):
                        for res in structured_results:
                            try:
                                # Handle mixed types (dict or string)
                                if isinstance(res, dict):
                                    learning_entry = {
                                        "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                        "input": res.get("text", ""),
                                        "source": res.get("source", ""),
                                        "url": res.get("url", "")
                                    }
                                else:
                                    # Fallback for string results
                                    learning_entry = {
                                        "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                        "input": str(res),
                                        "source": "search"
                                    }

                                # Use batcher if available - sync method to avoid event loop issues
                                if hasattr(self, 'learning_batcher') and self.learning_batcher:
                                    try:
                                        if hasattr(self.learning_batcher, 'add_sync'):
                                            self.learning_batcher.add_sync(learning_entry)
                                        else:
                                            self.memory.store_learning(learning_entry)
                                    except Exception as e:
                                        log.debug(f"Batcher failed, using direct store: {e}")
                                        self.memory.store_learning(learning_entry)
                                else:
                                    self.memory.store_learning(learning_entry)

                            except Exception as e:
                                log.debug(f"Failed to store structured result: {e}")
                else:
                    # Regular string input
                    learning_entry = {
                        "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "input": str(user_input) if not isinstance(user_input, str) else user_input
                    }
                    if hasattr(self, 'learning_batcher') and self.learning_batcher:
                        try:
                            if hasattr(self.learning_batcher, 'add_sync'):
                                self.learning_batcher.add_sync(learning_entry)
                            else:
                                self.memory.store_learning(learning_entry)
                        except Exception as e:
                            log.debug(f"Batcher failed, using direct store: {e}")
                            self.memory.store_learning(learning_entry)
                    else:
                        self.memory.store_learning(learning_entry)

        except Exception as e:
            log.debug(f"Learning failed: {e}")

        # Emit learning event if event_store and EventType are available
        try:
            if hasattr(self, 'event_store') and self.event_store and EventType and Event:
                import uuid as _uuid
                evt = Event(
                    timestamp=datetime.datetime.now(datetime.timezone.utc).timestamp(),
                    event_type=EventType.LEARNING_TRIGGERED,
                    source="NiblitBrain.learn",
                    data={"input_type": type(user_input).__name__},
                    correlation_id=str(_uuid.uuid4()),
                )
                try:
                    self.event_store.append_event(evt)
                except Exception:
                    pass
        except Exception:
            pass

    # ───────── Thinking (GENERAL CHAT ONLY) ─────────
    def think(self, user_input):
        """
        Think with circuit breaker protection and caching.

        IMPORTANT: This is for GENERAL CHAT ONLY.
        Commands are handled by niblit_core.py.

        Features:
        - Fault tolerance via circuit breaker
        - Automatic retry
        - Response caching
        - Telemetry
        - Structured request tracing
        """
        # pylint: disable=too-many-branches,too-many-statements,too-many-nested-blocks,too-many-locals,too-many-return-statements
        # ── Phase 14: Multi-Agent Internal Debate Layer ───────────────────────
        # Before executing the main think() pipeline, the three internal debate
        # agents vote on a routing strategy.  The winning agent's preferences are
        # stored and its trust updated after the response is obtained.
        _debate_winner: str = "balanced"
        _debate_prefer_local: bool = False
        _debate_augment_context: bool = False
        if BRAIN_DEBATE_ENABLED:
            global _brain_debate_last_winner  # pylint: disable=global-statement
            with _brain_debate_lock:
                _proposals = _build_brain_debate_proposals(user_input, self.llm_enabled)
                _debate_winner, _winning_proposal = _brain_debate_vote(
                    _proposals, _BRAIN_DEBATE_TRUST
                )
                _brain_debate_last_winner = _debate_winner
                _debate_prefer_local = bool(_winning_proposal.get("prefer_local", False))
                _debate_augment_context = bool(_winning_proposal.get("augment_context", False))
                log.debug("[BRAIN/DEBATE] winner=%s prefer_local=%s augment=%s",
                          _debate_winner, _debate_prefer_local, _debate_augment_context)
        # ─────────────────────────────────────────────────────────────────────

        # ── Adaptive System Interface — mirror + resonance ───────────────────
        # When the user input arrives from an external system (prefixed with
        # "SYS:<system_id>:") we mirror the signal context and establish
        # resonance so the brain's routing adapts to that system's style.
        # External callers tag their inputs using the prefix convention:
        #   "SYS:tickerbot: rsi_oversold=1 volume_spike=1"
        # For normal user chat, this block is a no-op.
        _sil_resonance_hint: str = ""
        try:
            _sil_prefix_match = re.match(
                r"^SYS:([A-Za-z0-9_\-]+):\s*(.*)", user_input, re.DOTALL
            )
            if _sil_prefix_match:
                _sil_system_id = _sil_prefix_match.group(1)
                _sil_payload_str = _sil_prefix_match.group(2).strip()
                # Parse simple key=value pairs from the payload
                _sil_data: dict = {}
                for _kv in _sil_payload_str.replace(",", " ").split():
                    if "=" in _kv:
                        _k, _, _v = _kv.partition("=")
                        try:
                            _sil_data[_k] = float(_v)
                        except ValueError:
                            log.debug(
                                "[BRAIN/SIL] non-numeric value for key %r: %r — "
                                "stored as string",
                                _k, _v,
                            )
                            _sil_data[_k] = _v
                if _sil_data:
                    from nibblebots import system_interface_layer as _sil_mod  # noqa: PLC0415
                    _sil_profile = _sil_mod.mirror_system(
                        _sil_system_id, _sil_data
                    )
                    _sil_cfg = _sil_mod.establish_resonance(_sil_profile)
                    _sil_resonance_hint = (
                        f"[SIL] {_sil_cfg.rationale}"
                    )
                    log.debug(
                        "[BRAIN/SIL] mirrored %s → %s",
                        _sil_system_id,
                        _sil_cfg.rationale,
                    )
                    # Strip the SYS prefix so the brain sees clean content
                    user_input = _sil_payload_str
        except Exception as _sil_err:  # noqa: BLE001
            log.debug("[BRAIN/SIL] mirror+resonance skipped: %s", _sil_err)
        # ─────────────────────────────────────────────────────────────────────

        _exit_stack = contextlib.ExitStack()
        try:
            # Structured request tracing
            if RequestContext and hasattr(self, 'structured_log') and self.structured_log:
                try:
                    _exit_stack.enter_context(RequestContext("brain_think"))
                except Exception:
                    pass

            # Rate limiting check - skip if already in event loop
            if hasattr(self, 'rate_limiter') and self.rate_limiter:
                try:
                    try:
                        asyncio.get_running_loop()
                        log.debug("[BRAIN] Skipping rate limit check (already in event loop)")
                    except RuntimeError:
                        asyncio.run(self.rate_limiter.acquire())
                except Exception as e:
                    log.debug(f"Rate limit check failed: {e}")

            # Check cache - skip if already in event loop
            if hasattr(self, 'cache') and self.cache:
                try:
                    try:
                        asyncio.get_running_loop()
                        log.debug("[BRAIN] Skipping cache lookup (already in event loop)")
                    except RuntimeError:
                        cached = asyncio.run(self.cache.get(f"think:{user_input[:50]}"))
                        if cached:
                            log.debug("[BRAIN] Cache hit on think")
                            _exit_stack.close()
                            return cached
                except Exception as e:
                    log.debug(f"Cache lookup failed: {e}")

            # ── Casual shortcut: skip KB/RAG/SECA for short chat openers ─────────
            # Short messages with no question mark and no command keywords
            # (e.g. "hi", "hello there", "hey") are answered directly by the
            # local brain using the minimal chat system prompt.  This avoids
            # injecting ~900 tokens of copilot system prompt + KB context for
            # a simple greeting, which would overflow a 0.5B model's context.
            if _is_casual_input(user_input):
                log.debug("[BRAIN] Casual input detected — skipping KB pipeline")
                # Prefer local brain with the compact chat prompt
                _casual_lb = getattr(self, "local_brain", None)
                if _casual_lb is None and getattr(self, "brain_router", None):
                    _casual_lb = getattr(self.brain_router, "local_brain", None)
                if _casual_lb is not None and _casual_lb.is_available():
                    try:
                        _casual_resp = _casual_lb.chat(user_input)
                        if _casual_resp and not _casual_resp.startswith("[LocalBrain"):
                            _exit_stack.close()
                            return _casual_resp
                    except Exception as _casual_err:
                        log.debug("[BRAIN] Casual local brain failed: %s", _casual_err)
                # Fallback: personality / static chat response (no LLM needed)
                try:
                    from modules.niblit_personality import NiblitPersonality
                    _cp = NiblitPersonality(brain=self)
                    _st_cat = _cp.classify_small_talk(user_input)
                    if _st_cat:
                        _st_resp = _cp.respond_to_small_talk(_st_cat)
                        if _st_resp:
                            _exit_stack.close()
                            return _st_resp
                except Exception:
                    pass
                # Last resort: continue through normal path
                log.debug("[BRAIN] Casual shortcut: no fast-path available, continuing")
            # ─────────────────────────────────────────────────────────────────────

            self.learn(user_input)
            context = ""

            try:
                if hasattr(self.memory, "recall"):
                    recalled = self.memory.recall(user_input)
                    if recalled:
                        context = "Based on previous knowledge:\n"
                        for r in recalled:
                            if isinstance(r, dict):
                                context += f"- {r.get('input', '')}\n"
                            else:
                                context += f"- {str(r)}\n"
                        context += "\n"
            except Exception:
                context = ""

            # Augment context with brain trainer knowledge if available
            if hasattr(self, 'brain_trainer') and self.brain_trainer:
                try:
                    trainer_ctx = self.brain_trainer.get_context_for(user_input)
                    if trainer_ctx:
                        context = trainer_ctx + context
                except Exception as _e:
                    log.debug(f"[BRAIN] Brain trainer context failed: {_e}")

            # ── SECA: inject multi-hop graph context ─────────────────────────
            _seca_snippets: list = []
            _seca_node_ids: list = []
            try:
                from modules.knowledge_comprehension import get_knowledge_comprehension
                _kc = get_knowledge_comprehension()
                _hits = _kc.search_graph(user_input, top_k=3, depth=2)
                if _hits:
                    _seca_snippets = [h.get("text", "") for h in _hits if h.get("text")]
                    _seca_node_ids = [h["id"] for h in _hits if h.get("id")]
                    _graph_ctx = "Relevant knowledge (multi-hop retrieval):\n" + "\n".join(
                        f"- {s}" for s in _seca_snippets[:3]
                    ) + "\n"
                    context = _graph_ctx + context
            except Exception as _seca_err:
                log.debug("[BRAIN] SECA graph retrieval skipped: %s", _seca_err)
            # ─────────────────────────────────────────────────────────────────

            # ── RAG Pipeline: dense vector retrieval augmentation ─────────────
            try:
                from modules.rag_pipeline import get_rag_pipeline
                _rag = get_rag_pipeline()
                _rag_result = _rag.query(user_input, top_k=3, graph_depth=1)
                _rag_ctx = _rag_result.get("context", "")
                if _rag_ctx and _rag_ctx not in context:
                    context = _rag_ctx + context
            except Exception as _rag_err:
                log.debug("[BRAIN] RAG pipeline augmentation skipped: %s", _rag_err)
            # ─────────────────────────────────────────────────────────────────

            # ── Graph-RAG: 3-Tiered deterministic retrieval ───────────────────
            # Tier 1 (absolute facts) > Tier 2 (stats) > Tier 3 (vector docs).
            # When any graph tier has relevant hits the structured system prompt
            # replaces the plain context prefix so the LLM follows explicit
            # conflict-resolution rules instead of guessing.
            _graph_rag_prefix = ""
            try:
                from modules.graph_rag import get_graph_rag_pipeline
                _grp = get_graph_rag_pipeline()
                _gr_result = _grp.query(user_input, top_k=3)
                _gr_stats = _gr_result.get("retrieval_stats", {})
                _has_graph_hits = (
                    _gr_stats.get("tier1", 0) > 0 or _gr_stats.get("tier2", 0) > 0
                )
                if _has_graph_hits:
                    # Use the structured tiered system prompt as the leading context
                    _graph_rag_prefix = _gr_result.get("system_prompt", "")
                elif _gr_stats.get("tier3", 0) > 0:
                    # Only vector hits — use the plain context fallback
                    _graph_rag_prefix = _gr_result.get("context", "")
                if _graph_rag_prefix:
                    context = _graph_rag_prefix + context
            except Exception as _gr_err:
                log.debug("[BRAIN] Graph-RAG augmentation skipped: %s", _gr_err)
            # ─────────────────────────────────────────────────────────────────

            prompt = context + user_input

            # ── Kernel v3: memory-grounded pre-think (runs every cycle) ──────
            # This ensures every `think()` call exercises the fused v1+v2+KCB
            # pipeline, writes to kernel memory, scores agents via RewardEngine,
            # and queues a sync artifact — regardless of LLM availability.
            _kv3_response: str = ""
            try:
                from modules.niblit_kernel_v3 import get_niblit_kernel_v3
                _kv3 = get_niblit_kernel_v3()
                _kv3_result = _kv3.run_cognitive_loop(
                    user_input,
                    context={"context": context[:400]} if context else None,
                    use_agents=False,  # agents run only on explicit orchestrate() call
                )
                _kv3_response = _kv3_result.response or ""
            except Exception as _kv3_err:
                log.debug("[BRAIN] KernelV3 pre-think skipped: %s", _kv3_err)
            # ─────────────────────────────────────────────────────────────────

            if not self.llm_enabled:
                log.debug("[BRAIN] toggle-llm off — routing through local brain first")
                # ── 1. Qwen local brain (primary when LLM is toggled off) ──────
                if getattr(self, "brain_router", None):
                    try:
                        _lb_resp = self.brain_router._local_first(  # pylint: disable=protected-access
                            user_input, context=context
                        )
                        if _lb_resp and not _lb_resp.startswith("[LocalBrain unavailable"):
                            _exit_stack.close()
                            return _lb_resp
                    except Exception as _lb_err:
                        log.debug("[BRAIN] LocalBrain via router failed: %s", _lb_err)
                elif getattr(self, "local_brain", None) and self.local_brain.is_available():
                    try:
                        _lb_direct = self.local_brain.ask(user_input, context=context)
                        if _lb_direct and not _lb_direct.startswith("[LocalBrain unavailable"):
                            _exit_stack.close()
                            return _lb_direct
                    except Exception as _lbd_err:
                        log.debug("[BRAIN] LocalBrain direct failed: %s", _lbd_err)
                # ── 2. Academic / language module ─────────────────────────────
                try:
                    from modules.academic_study_module import get_academic_study_module
                    _asm_b = get_academic_study_module()
                    _asm_answer = _asm_b.answer_question(user_input)
                    if _asm_answer:
                        _exit_stack.close()
                        return _asm_answer
                except Exception as _asm_err:
                    log.debug("[BRAIN] AcademicStudy fallback failed: %s", _asm_err)
                # ── 3. Kernel v3 local reasoning (no LLM required) ────────────
                if _kv3_response and not _kv3_response.startswith("No strong"):
                    _exit_stack.close()
                    return _kv3_response
                # ── 4. Language module on assembled context ────────────────────
                if context.strip():
                    try:
                        from modules.language_module import get_language_module
                        _lm_b = get_language_module()
                        _topic_b = _lm_b.extract_topic(user_input)
                        _entry_b = _lm_b.lookup(_topic_b) if _topic_b else None
                        if _entry_b:
                            _exit_stack.close()
                            return _lm_b.format_definition_answer(_topic_b, _entry_b["definition"])
                    except Exception:
                        pass
                _exit_stack.close()
                return f"[Local brain: Qwen not yet loaded — run 'brain status'] '{user_input}'"

            response = None

            # ── Chat history injection for local brain ──────────────────────
            # When brain_router routes to QwenLocalBrain, it bypasses the
            # ChatCompletions engine that normally injects LLMChatMemory turns.
            # Load the last few conversation turns here so Qwen has continuity
            # without sending the full (possibly large) history.
            _chat_history_prefix = ""
            try:
                from modules.llm_chat_memory import get_llm_chat_memory
                _chat_mem_br = get_llm_chat_memory()
                _recent_msgs = _chat_mem_br.load_messages(limit=_CHAT_HISTORY_MSG_LIMIT)
                if _recent_msgs:
                    _hist_lines = []
                    for _m in _recent_msgs:
                        _role = _m.get("role", "")
                        _content = _m.get("content", "")
                        if _role and _content:
                            _truncated = _content[:_CHAT_HISTORY_CONTENT_CHARS]
                            _suffix = "…" if len(_content) > _CHAT_HISTORY_CONTENT_CHARS else ""
                            _hist_lines.append(
                                f"{_role.capitalize()}: {_truncated}{_suffix}"
                            )
                    if _hist_lines:
                        _chat_history_prefix = (
                            "Recent conversation:\n"
                            + "\n".join(_hist_lines)
                            + "\n\n"
                        )
            except Exception as _ch_err:
                log.debug("[BRAIN] Chat history injection skipped: %s", _ch_err)

            # ── BrainRouter: intelligent multi-brain routing ──────────────────
            # Replaces the direct LLMProviderManager call with a routed strategy
            # that picks the best intelligence source (local/memory/cloud/hybrid)
            # based on prompt complexity and the active NIBLIT_BRAIN_MODE.
            # The context already assembled above (SECA/RAG/Graph-RAG) plus the
            # recent conversation history prefix are passed as memory context so
            # the local brain has both knowledge and conversation continuity.
            #
            # Phase 14 debate integration: the conservative agent biases toward
            # the local-brain path; the creative agent appends an extra hint to
            # encourage the router toward richer, augmented responses.
            _extra_context_stripped = (_chat_history_prefix + context).strip()
            if _debate_augment_context and _extra_context_stripped:
                _extra_context_stripped += "\n[Debate/creative: prefer augmented response]"
            if getattr(self, "brain_router", None):
                try:
                    # Conservative agent: use local-first path when available
                    if _debate_prefer_local and hasattr(self.brain_router, "_local_first"):
                        _local_resp = self.brain_router._local_first(  # pylint: disable=protected-access
                            user_input, context=_extra_context_stripped
                        )
                        if _local_resp and not _local_resp.startswith("[LocalBrain"):
                            response = _local_resp
                            log.debug("[BRAIN/DEBATE] conservative local-first path selected")
                    if not response:
                        _br_response = self.brain_router.route(
                            user_input,
                            context=_extra_context_stripped,
                        )
                        if _br_response and isinstance(_br_response, str) and \
                                not _br_response.startswith("[LocalBrain unavailable") and \
                                not _br_response.startswith("[LocalBrain error"):
                            response = _br_response
                            log.debug("[BRAIN] BrainRouter response (mode=%s)",
                                      self.brain_router.mode)
                            # Persist this exchange to LLMChatMemory so future requests
                            # see it as part of conversation history.  ChatCompletions is
                            # skipped when brain_router produces a result, so we persist
                            # here to keep chat history consistent.
                            try:
                                from modules.llm_chat_memory import get_llm_chat_memory
                                _cm_persist = get_llm_chat_memory()
                                _cm_persist.add("user", user_input)
                                _cm_persist.add("assistant", _br_response)
                            except Exception as _cm_err:
                                log.debug("[BRAIN] Chat memory persist skipped: %s", _cm_err)
                except Exception as _br_err:
                    log.debug("[BRAIN] BrainRouter.route failed: %s", _br_err)

            # ── ChatCompletions engine: preferred cloud response path ─────────
            # Uses GraphRAGPipeline + LLMChatMemory + LLMProviderManager in one
            # unified call so conversation history and tiered knowledge are
            # always injected together.
            if not response:
                try:
                    from modules.chat_completions import get_chat_completions
                    _cc = get_chat_completions(
                        llm_provider_manager=self.llm_provider_manager,
                    )
                    _cc_result = _cc.complete(user_input, persist=True)
                    if _cc_result.response and not _cc_result.response.startswith("("):
                        response = _cc_result.response
                        log.debug(
                            "[BRAIN] ChatCompletions response via tier=%s sources=%s",
                            _cc_result.tier_used, _cc_result.sources,
                        )
                except Exception as _cc_err:
                    log.debug("[BRAIN] ChatCompletions skipped: %s", _cc_err)

            # Route through LLMProviderManager (active provider + fallback chain)
            if not response and self.llm_provider_manager:
                try:
                    response = self.llm_provider_manager.ask(prompt)
                except Exception as _pm_err:
                    log.debug("[BRAIN] LLMProviderManager.ask failed: %s", _pm_err)

            # Legacy fallback: direct HFBrain if manager not available
            if not response and self.hf_brain:
                try:
                    response = self.hf_brain.ask_single(prompt)
                except Exception as _hf_err:
                    log.debug("[BRAIN] HFBrain direct fallback failed: %s", _hf_err)

            if response and isinstance(response, str):
                response = response.strip()

                # Feed successful response back to brain trainer for learning
                if hasattr(self, 'brain_trainer') and self.brain_trainer:
                    try:
                        self.brain_trainer.record_exchange(user_input, response)
                    except Exception:
                        pass

                # ── SECA: reward feedback ────────────────────────────────────
                try:
                    from modules.reward_model import get_reward_model
                    from modules.memory_graph import get_memory_graph
                    _rm = get_reward_model()
                    _mg = get_memory_graph()
                    _rm.record_feedback(
                        query=user_input,
                        answer=response,
                        snippets=_seca_snippets,
                        node_ids=_seca_node_ids or None,
                        memory_graph=_mg if _seca_node_ids else None,
                    )
                except Exception as _rf_err:
                    log.debug("[BRAIN] Reward feedback skipped: %s", _rf_err)
                # ─────────────────────────────────────────────────────────────

                # Cache the response - skip if already in event loop
                if hasattr(self, 'cache') and self.cache:
                    try:
                        try:
                            asyncio.get_running_loop()
                            log.debug("[BRAIN] Skipping cache store (already in event loop)")
                        except RuntimeError:
                            asyncio.run(self.cache.set(f"think:{user_input[:50]}", response))
                    except Exception as e:
                        log.debug(f"Cache store failed: {e}")

                # Record telemetry
                if hasattr(self, 'telemetry') and self.telemetry:
                    self.telemetry.increment_counter("brain_think_success")

                # ── Phase 14: update debate agent trust on successful response ──
                if BRAIN_DEBATE_ENABLED and _debate_winner:
                    # Score the outcome as 0.7 (above neutral) for any non-empty
                    # response; callers may call _update_brain_debate_trust() with
                    # a more precise outcome if explicit feedback is available.
                    _update_brain_debate_trust(_debate_winner, outcome=0.7)
                # ─────────────────────────────────────────────────────────────

                _exit_stack.close()
                return response

            if hasattr(self, 'telemetry') and self.telemetry:
                self.telemetry.increment_counter("brain_think_failure")

            # ── Phase 14: update debate agent trust on failed response ─────────
            if BRAIN_DEBATE_ENABLED and _debate_winner:
                _update_brain_debate_trust(_debate_winner, outcome=0.3)
            # ─────────────────────────────────────────────────────────────────

            _exit_stack.close()
            # ── Gap-learning trigger: when HFBrain has no answer, queue research ──
            self._trigger_gap_learning(user_input)

            # ── Local knowledge fallback when HFBrain is offline ──
            # Priority: AcademicStudyModule → LanguageModule → context facts → generic
            try:
                from modules.academic_study_module import get_academic_study_module
                _asm_offline = get_academic_study_module()
                _asm_offline_answer = _asm_offline.answer_question(user_input)
                if _asm_offline_answer:
                    return _asm_offline_answer
            except Exception:
                pass

            if context:
                # Try language module on context first
                try:
                    from modules.language_module import get_language_module
                    _lm_off = get_language_module()
                    _facts_from_ctx = [
                        ln.lstrip("- ").strip()
                        for ln in context.splitlines()
                        if ln.strip() and not ln.strip().startswith("[")
                    ]
                    _formatted = _lm_off.format_factual_answer(user_input, _facts_from_ctx)
                    if _formatted:
                        return _formatted
                except Exception:
                    pass

                facts = [
                    ln.lstrip("- ").strip()
                    for ln in context.splitlines()
                    if ln.strip().startswith("-") and ln.strip() != "-"
                ]
                if facts:
                    summary = "; ".join(facts[:3])
                    return (
                        f"[HFBrain offline — set HF_TOKEN (or HF_API_KEY) to enable AI responses]\n"
                        f"From local knowledge: {summary}"
                    )
            return (
                f"[No response available — check HF_TOKEN / NIBLIT_LLAMA_SERVER_URL or try again]\n"
                f"Received: {user_input}"
            )

        except Exception as e:
            log.error(f"Think failed: {e}")
            if hasattr(self, 'telemetry') and self.telemetry:
                self.telemetry.increment_counter("brain_think_error")
            return f"[Error] {str(e)}"

    # ───────── Command Handling (DEPRECATED - Use niblit_core.py instead) ─────────
    def handle_command(self, command: str):
        """
        DEPRECATED: Commands are now handled by niblit_core.py via CommandRegistry.

        This method is kept for backward compatibility only.
        Commands should route through niblit_core.handle() instead.
        """
        # pylint: disable=too-many-branches,too-many-statements,too-many-return-statements
        cmd = command.strip()
        lcmd = cmd.lower()

        # Special command handling for modules
        if lcmd.startswith("self-research"):
            topic = cmd[len("self-research"):].strip() or "general"
            if self.self_researcher:
                try:
                    structured_results = self.self_researcher.search(topic)
                    self.learn({"structured_search": structured_results})
                    return structured_results
                except Exception as e:
                    log.debug(f"self-research failed: {e}")
                    return f"Research failed: {e}"
            return "SelfResearcher module not available."

        if lcmd.startswith("self-heal"):
            if self.self_healer:
                try:
                    return self.self_healer.repair()
                except Exception as e:
                    log.debug(f"self-heal failed: {e}")
                    return f"Heal failed: {e}"
            return "SelfHealer module not available."

        if lcmd.startswith("self-idea"):
            if self.self_idea:
                prompt = cmd[len("self-idea"):].strip()
                try:
                    result = self.self_idea.implement_idea(prompt)
                    self.learn(result)
                    return result
                except Exception as e:
                    log.debug(f"self-idea failed: {e}")
                    return f"Idea failed: {e}"
            return "SelfIdeaImplementation not available."

        if lcmd.startswith("self-implement"):
            if self.self_idea:
                try:
                    return self.self_idea.implement_ideas()
                except Exception as e:
                    log.debug(f"self-implement failed: {e}")
                    return f"Implement failed: {e}"
            return "SelfIdeaImplementation not available."

        if lcmd.startswith("reflect"):
            if self.reflect:
                text = cmd[len("reflect"):].strip()
                try:
                    return self.reflect.collect_and_summarize(text)
                except Exception as e:
                    log.debug(f"reflect failed: {e}")
                    return f"Reflect failed: {e}"
            return "Reflect module not available."

        if lcmd.startswith("auto-reflect"):
            if self.reflect and hasattr(self.memory, "recall"):
                try:
                    recent = [str(x) for x in self.memory.recall("", 5)]
                    return self.reflect.auto_reflect(recent)
                except Exception as e:
                    log.debug(f"auto-reflect failed: {e}")
                    return f"Auto reflect failed: {e}"
            return "Auto reflection unavailable."

        return self.think(command)

    # ───────── Router-Compatible Handle ─────────
    def handle(self, text: str) -> str:
        """
        Router compatibility wrapper.

        Routes to handle_command() for known commands, else to think().

        IMPORTANT: This is for backward compatibility.
        Commands should be handled by niblit_core.py instead.
        """
        if not getattr(self, "llm_enabled", True):
            return f"[LLM disabled] '{text}'"

        ltext = text.lower().strip()

        known_commands = (
            "self-research", "self-heal", "self-idea", "self-implement",
            "reflect", "auto-reflect"
        )

        if any(ltext.startswith(cmd) for cmd in known_commands):
            return self.handle_command(text)

        return self.think(text)

    def _trigger_gap_learning(self, topic: str) -> None:
        """Queue *topic* for autonomous background research when the brain
        has no answer.  Works on Vercel (lightweight: just adds to ALE topics).
        Also notifies the LLMTrainingAgent so the inference provider can
        generate structured training data for this gap.
        """
        if not topic or len(topic.strip()) < 3:
            return
        # Try ALE research_topics (always available)
        try:
            ale = getattr(self, "_ale", None) or getattr(self, "autonomous_engine", None)
            if ale and hasattr(ale, "research_topics"):
                if topic not in ale.research_topics:
                    ale.research_topics.append(topic)
                    log.debug("[Brain] Gap-learning: queued ALE topic '%s'", topic)
        except Exception:
            pass
        # Fallback: try SelfResearcher.add_topic
        try:
            sr = getattr(self, "self_researcher", None) or getattr(self, "researcher", None)
            if sr and hasattr(sr, "add_topic"):
                sr.add_topic(topic)
                log.debug("[Brain] Gap-learning: queued researcher topic '%s'", topic)
        except Exception:
            pass

    def get_stats(self) -> Dict[str, Any]:
        """Get brain statistics from all improvements."""
        stats = {
            "llm_enabled": self.llm_enabled,
            "improvements_enabled": self.enable_improvements,
        }

        if hasattr(self, 'telemetry') and self.telemetry:
            stats["telemetry"] = self.telemetry.get_stats()

        if hasattr(self, 'event_store') and self.event_store:
            stats["events"] = self.event_store.get_stats()

        if hasattr(self, 'cache') and self.cache:
            stats["cache"] = self.cache.get_stats()

        if hasattr(self, 'learning_batcher') and self.learning_batcher:
            stats["learning_batcher"] = self.learning_batcher.get_stats()

        if getattr(self, "local_brain", None):
            stats["local_brain"] = self.local_brain.status()

        if getattr(self, "brain_router", None):
            stats["brain_router"] = self.brain_router.stats()

        # Phase 14: include debate-layer status
        if BRAIN_DEBATE_ENABLED:
            stats["debate"] = get_brain_debate_status()

        return stats

    # ── Fused Memory API ─────────────────────────────────────────────────────

    def save_knowledge(
        self,
        knowledge_id: str,
        knowledge_data: dict,
        embedding: Optional[List[float]] = None,
    ) -> None:
        """Store structured knowledge and an optional embedding via fused memory.

        Writes *knowledge_data* to the SQLite records table and, when
        *embedding* is provided, also upserts the vector into Qdrant/FAISS.

        Args:
            knowledge_id:   Unique identifier for this piece of knowledge.
            knowledge_data: Arbitrary dict payload.
            embedding:      Optional pre-computed float vector.
        """
        fused = getattr(self.memory, "fused_memory", None)
        if fused is not None:
            try:
                fused.insert_record(knowledge_id, knowledge_data)
                if embedding:
                    fused.insert_vector(knowledge_id, embedding, payload=knowledge_data)
                return
            except Exception as exc:
                log.debug("[NiblitBrain] fused save_knowledge failed: %s", exc)
        # Fallback: store_learning
        if hasattr(self.memory, "store_learning"):
            self.memory.store_learning({"knowledge_id": knowledge_id, **knowledge_data})

    def load_knowledge(self, knowledge_id: str) -> dict:
        """Retrieve a piece of knowledge from the fused memory backend.

        Args:
            knowledge_id: Unique identifier.

        Returns:
            Knowledge dict, or empty dict when not found.
        """
        fused = getattr(self.memory, "fused_memory", None)
        if fused is not None:
            try:
                rec = fused.get_record(knowledge_id)
                if rec is not None:
                    return rec
            except Exception as exc:
                log.debug("[NiblitBrain] fused load_knowledge failed: %s", exc)
        return {}

    def retrieve_similar(
        self,
        embedding: List[float],
        top_k: int = 5,
    ) -> List[dict]:
        """Find knowledge entries semantically similar to *embedding*.

        Queries the fused Qdrant/FAISS vector index.  Falls back to an empty
        list when the fused backend is unavailable.

        Args:
            embedding: Query float vector.
            top_k:     Maximum results.

        Returns:
            List of result dicts ordered by similarity (most similar first).
        """
        fused = getattr(self.memory, "fused_memory", None)
        if fused is not None:
            try:
                return fused.query_vector(embedding, top_k=top_k)
            except Exception as exc:
                log.debug("[NiblitBrain] fused retrieve_similar failed: %s", exc)
        return []


# ─────────── HF Shortcut ───────────
def hf_query(prompt: str, memory=None, llm_enabled=True):
    """
    Execute a HuggingFace model query with optional memory context.

    Exposed at module level for orchestrator and direct use.

    Args:
        prompt: The query prompt
        memory: Optional memory manager for context (auto-loads if None)
        llm_enabled: Whether LLM is enabled (default: True)

    Returns:
        Response string from HF model or fallback message
    """
    try:
        if memory is None:
            try:
                from niblit_memory import MemoryManager
                memory = MemoryManager()
            except Exception as _e:
                log.debug(f"niblit_memory unavailable in hf_query, proceeding without memory: {_e}")
                memory = None

        brain = NiblitBrain(memory, llm_enabled=llm_enabled)
        result = brain.think(prompt)
        return result if result else "[No response]"
    except Exception as e:
        log.debug(f"hf_query failed: {e}")
        return f"[HF query failed: {e}]"


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    print("=== NiblitBrain self-test ===")
    _mem = None
    try:
        from niblit_memory import MemoryManager as _MemoryManager  # pylint: disable=ungrouped-imports
        _mem = _MemoryManager()
    except Exception as e:  # pylint: disable=broad-except
        print(f"[WARN] Memory unavailable ({e}), using None.")
    _brain = NiblitBrain(_mem, llm_enabled=False)
    _response = _brain.think("What is 2 + 2?")
    print(f"Brain response: {_response!r}")
    _stats = _brain.get_stats()
    print(f"Brain stats: {_stats}")
    print("NiblitBrain OK")
