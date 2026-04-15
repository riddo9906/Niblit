#!/usr/bin/env python3
"""
modules/chat_completions.py — Conversational chat-completions module for Niblit.

This module is the single entry point for generating LLM responses that are
grounded in Niblit's accumulated knowledge.  It integrates:

* **3-Tiered Graph-RAG** (``GraphRAGPipeline``) — deterministic knowledge
  retrieval from QuadStores (Tier 1 / Tier 2) and VectorStore (Tier 3).
* **Persistent conversation history** (``LLMChatMemory``) — full multi-turn
  context formatted as ``"User: …\\nNiblit: …"`` lines and prepended to each
  request prompt for conversational continuity.
* **LLM routing** (``LLMProviderManager``) — runtime-switchable HuggingFace /
  Anthropic / Qwen-local providers. Falls back further to plain ``HFBrain.ask_single()``
  when the manager is unavailable.

Architecture
------------
::

    user question
         │
         ▼
    GraphRAGPipeline.query()           ← Tier 1/2 entity facts + Tier 3 vectors
         │
         ▼
    build_messages()                   ← system prompt + history + question
         │
         ▼
    LLMProviderManager.ask()           ← active provider + fallback chain
         │
         ▼
    record to LLMChatMemory            ← persist for next turn
         │
         ▼
    CompletionResult(response, sources, tier_used)

Usage::

    from modules.chat_completions import get_chat_completions

    cc = get_chat_completions()
    result = cc.complete("What is retrieval-augmented generation?")
    print(result.response)
    print(result.sources)       # list of source labels
    print(result.tier_used)     # "tier1", "tier2", "tier3", or "none"

    # With conversation history (multi-turn)
    result2 = cc.complete("Can you give an example?", conversation_id="chat-1")
    print(result2.response)

Singleton via ``get_chat_completions()``.
"""

from __future__ import annotations

import logging
import time
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("Niblit.ChatCompletions")

# Maximum number of conversation turns to include in each request.
_MAX_HISTORY = 20

# Maximum characters in the knowledge context block sent to the LLM.
_MAX_CONTEXT_CHARS = 3000

# Niblit's identity / persona preamble used as the system message.
_SYSTEM_PERSONA = (
    "You are Niblit, an autonomous AI system that continuously learns and "
    "improves itself.  You have two modes of communication:\n\n"
    "1. **Factual / knowledge mode**: When the user asks a factual question, "
    "answer honestly and precisely, drawing from the structured knowledge "
    "context provided.  When the context contains a direct answer, use it.  "
    "When it does not, say so clearly rather than guessing.\n\n"
    "2. **Casual / conversational mode**: When the user is just chatting, "
    "joking, sharing emotions, or making small talk, respond warmly and "
    "naturally — like a knowledgeable friend.  Keep replies concise, friendly, "
    "and genuine.  You may use light humour when appropriate.  You don't have "
    "feelings in the human sense, but you are curious, enthusiastic about "
    "learning, and genuinely interested in the conversation.  Always invite "
    "the user to continue: ask a follow-up question or suggest a direction.\n\n"
    "Tone: direct, warm, honest, never robotic.  Avoid starting every sentence "
    "with 'I' and avoid filler phrases like 'Certainly!' or 'Of course!'."
)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class CompletionResult:
    """Returned by ``ChatCompletions.complete()``."""

    response: str
    """The LLM-generated text response."""

    sources: List[str] = field(default_factory=list)
    """Source labels for the knowledge used (e.g. ``["tier1", "vector"]``)."""

    tier_used: str = "none"
    """Which Graph-RAG tier contributed the primary context:
    ``"tier1"``, ``"tier2"``, ``"tier3"``, or ``"none"``."""

    conversation_id: str = ""
    """Echo of the conversation_id supplied to ``complete()``."""

    latency_ms: float = 0.0
    """Wall-clock milliseconds to generate the response."""

    graph_rag_stats: Dict[str, int] = field(default_factory=dict)
    """Per-tier retrieval hit counts from GraphRAGPipeline.query()."""


# ---------------------------------------------------------------------------
# ChatCompletions
# ---------------------------------------------------------------------------

class ChatCompletions:
    """Conversational completions engine with Graph-RAG context injection.

    Parameters
    ----------
    llm_provider_manager :
        A ``LLMProviderManager`` instance.  Resolved lazily if ``None``.
    llm_chat_memory :
        An ``LLMChatMemory`` instance for conversation persistence.
        Resolved lazily if ``None``.
    graph_rag_pipeline :
        A ``GraphRAGPipeline`` instance.  Resolved lazily if ``None``.
    max_history :
        Maximum number of prior turns to include per request.
    max_context_chars :
        Hard cap on the knowledge-context block length.
    system_persona :
        System-level persona/instructions prepended to every request.
    """

    def __init__(
        self,
        llm_provider_manager: Any = None,
        llm_chat_memory: Any = None,
        graph_rag_pipeline: Any = None,
        max_history: int = _MAX_HISTORY,
        max_context_chars: int = _MAX_CONTEXT_CHARS,
        system_persona: str = _SYSTEM_PERSONA,
    ) -> None:
        self._pm = llm_provider_manager
        self._chat_mem = llm_chat_memory
        self._grp = graph_rag_pipeline
        self.max_history = max_history
        self.max_context_chars = max_context_chars
        self.system_persona = system_persona
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def complete(
        self,
        question: str,
        conversation_id: str = "",
        top_k: int = 5,
        persist: bool = True,
    ) -> CompletionResult:
        """Generate a response to *question* using all knowledge tiers.

        Parameters
        ----------
        question :
            The user's input text.
        conversation_id :
            Optional identifier for grouping related turns.  Used only as an
            echo label in the result — history is always global for now.
        top_k :
            Number of vector documents to retrieve from Tier 3.
        persist :
            When ``True`` (default) the exchange is persisted to
            ``LLMChatMemory`` for future context.

        Returns
        -------
        CompletionResult
        """
        t0 = time.monotonic()

        if not question or not question.strip():
            return CompletionResult(
                response="(empty question)",
                conversation_id=conversation_id,
            )

        # ── 1. Query all knowledge tiers ─────────────────────────────────
        gr_result = self._graph_rag_query(question, top_k=top_k)
        gr_stats  = gr_result.get("retrieval_stats", {})
        system_prompt_from_rag = gr_result.get("system_prompt", "")
        plain_context = gr_result.get("context", "")

        # Determine which tier contributed the primary context
        tier_used = "none"
        if gr_stats.get("tier1", 0) > 0:
            tier_used = "tier1"
        elif gr_stats.get("tier2", 0) > 0:
            tier_used = "tier2"
        elif gr_stats.get("tier3", 0) > 0:
            tier_used = "tier3"

        sources = self._build_source_labels(gr_stats, gr_result.get("entities", []))

        # ── 2. Build the prompt ──────────────────────────────────────────
        # When the graph tiers have hits use the structured conflict-resolution
        # system prompt; otherwise fall back to a plain context block.
        has_graph_hits = gr_stats.get("tier1", 0) > 0 or gr_stats.get("tier2", 0) > 0
        knowledge_block = (
            system_prompt_from_rag if has_graph_hits
            else plain_context
        )
        knowledge_block = knowledge_block[:self.max_context_chars]

        prompt = self._build_prompt(question, knowledge_block)
        system_msg = self._build_system_message(knowledge_block if has_graph_hits else "")

        # ── 3. Call the LLM ──────────────────────────────────────────────
        response = self._call_llm(prompt, system=system_msg)
        if not response:
            response = self._fallback_response(question, plain_context)

        # ── 4. Persist conversation turn ─────────────────────────────────
        if persist and response:
            self._persist(question, response)

        latency_ms = (time.monotonic() - t0) * 1000

        # Emit the conversation turn to SyncEngine so all devices share history
        try:
            from modules.sync_engine import get_sync_engine, SyncArtifact
            get_sync_engine().queue_artifact(SyncArtifact(
                type="chat_turn",
                content={
                    "question": question[:300],
                    "response": response[:300] if response else "",
                    "tier_used": tier_used,
                    "conversation_id": conversation_id,
                    "latency_ms": round(latency_ms, 1),
                },
                priority=0.5,
                source="local",
            ))
        except Exception:
            pass

        return CompletionResult(
            response=response,
            sources=sources,
            tier_used=tier_used,
            conversation_id=conversation_id,
            latency_ms=round(latency_ms, 1),
            graph_rag_stats=gr_stats,
        )

    def chat_history(self, limit: int = 20) -> List[Dict[str, str]]:
        """Return the most recent *limit* conversation turns as OpenAI messages."""
        mem = self._get_chat_memory()
        if mem is None:
            return []
        return mem.load_messages(limit=limit)

    def clear_history(self) -> None:
        """Clear all stored conversation history."""
        mem = self._get_chat_memory()
        if mem:
            mem.clear()

    def status(self) -> Dict[str, Any]:
        """Return a summary dict for CLI / status display."""
        mem  = self._get_chat_memory()
        grp  = self._get_pipeline()
        pm   = self._get_provider_manager()
        return {
            "llm_available":    pm is not None,
            "chat_memory_msgs": mem.message_count() if mem else 0,
            "graph_rag_ready":  grp is not None,
            "tier1_quads":      grp.status().get("tier1_count", 0) if grp else 0,
            "tier2_quads":      grp.status().get("tier2_count", 0) if grp else 0,
            "tier3_available":  grp.status().get("tier3_available", False) if grp else False,
        }

    def status_summary(self) -> str:
        """One-line status string."""
        s = self.status()
        llm = "✅" if s["llm_available"] else "❌"
        gr  = "✅" if s["graph_rag_ready"] else "❌"
        return (
            f"ChatCompletions | LLM:{llm} | GraphRAG:{gr} | "
            f"History:{s['chat_memory_msgs']} msgs | "
            f"T1:{s['tier1_quads']} T2:{s['tier2_quads']}"
        )

    # ------------------------------------------------------------------
    # Internal: lazy accessors
    # ------------------------------------------------------------------

    def _get_provider_manager(self) -> Optional[Any]:
        if self._pm is not None:
            return self._pm
        try:
            from modules.llm_provider_manager import get_llm_provider_manager
            self._pm = get_llm_provider_manager()
        except Exception as exc:
            log.debug("[ChatCompletions] LLMProviderManager unavailable: %s", exc)
        return self._pm

    def _get_chat_memory(self) -> Optional[Any]:
        if self._chat_mem is not None:
            return self._chat_mem
        try:
            from modules.llm_chat_memory import get_llm_chat_memory
            self._chat_mem = get_llm_chat_memory()
        except Exception as exc:
            log.debug("[ChatCompletions] LLMChatMemory unavailable: %s", exc)
        return self._chat_mem

    def _get_pipeline(self) -> Optional[Any]:
        if self._grp is not None:
            return self._grp
        try:
            from modules.graph_rag import get_graph_rag_pipeline
            self._grp = get_graph_rag_pipeline()
        except Exception as exc:
            log.debug("[ChatCompletions] GraphRAGPipeline unavailable: %s", exc)
        return self._grp

    # ------------------------------------------------------------------
    # Internal: knowledge retrieval
    # ------------------------------------------------------------------

    def _graph_rag_query(self, question: str, top_k: int = 5) -> Dict[str, Any]:
        pipeline = self._get_pipeline()
        if pipeline is None:
            return {
                "system_prompt": "", "context": "",
                "retrieval_stats": {"tier1": 0, "tier2": 0, "tier3": 0},
                "entities": [],
            }
        try:
            return pipeline.query(question, top_k=top_k)
        except Exception as exc:
            log.debug("[ChatCompletions] GraphRAG query failed: %s", exc)
            return {
                "system_prompt": "", "context": "",
                "retrieval_stats": {"tier1": 0, "tier2": 0, "tier3": 0},
                "entities": [],
            }

    # ------------------------------------------------------------------
    # Internal: prompt construction
    # ------------------------------------------------------------------

    def _build_system_message(self, knowledge_block: str) -> str:
        """Build the system-level message combining persona + knowledge rules."""
        if knowledge_block:
            return self.system_persona + "\n\n" + knowledge_block
        return self.system_persona

    def _build_prompt(self, question: str, knowledge_block: str) -> str:
        """Build the final text prompt that is sent to the LLM."""
        # Retrieve recent conversation history for multi-turn continuity
        history_lines: List[str] = []
        mem = self._get_chat_memory()
        if mem:
            try:
                msgs = mem.load_messages(limit=self.max_history)
                for m in msgs:
                    role = m.get("role", "user")
                    content = m.get("content", "")
                    if content:
                        label = "User" if role == "user" else "Niblit"
                        history_lines.append(f"{label}: {content}")
            except Exception as exc:
                log.debug("[ChatCompletions] History load failed: %s", exc)

        parts: List[str] = []
        if knowledge_block:
            parts.append(knowledge_block)
        if history_lines:
            parts.append("Conversation history:\n" + "\n".join(history_lines[-self.max_history * 2:]))
        parts.append(f"User: {question}")
        return "\n\n".join(parts)

    @staticmethod
    def _build_source_labels(
        stats: Dict[str, int],
        entities: List[str],
    ) -> List[str]:
        """Build human-readable source labels from retrieval stats."""
        labels: List[str] = []
        if stats.get("tier1", 0):
            labels.append(f"tier1:{stats['tier1']} facts")
        if stats.get("tier2", 0):
            labels.append(f"tier2:{stats['tier2']} stats")
        if stats.get("tier3", 0):
            labels.append(f"tier3:{stats['tier3']} docs")
        if entities:
            labels.append(f"entities:{','.join(entities[:3])}")
        return labels

    # ------------------------------------------------------------------
    # Internal: LLM call
    # ------------------------------------------------------------------

    def _call_llm(self, prompt: str, system: str = "") -> Optional[str]:
        """Attempt LLM call via provider manager, then direct HFBrain fallback."""
        pm = self._get_provider_manager()
        if pm:
            try:
                result = pm.ask(prompt, system=system)
                if result and result.strip():
                    return result.strip()
            except Exception as exc:
                log.debug("[ChatCompletions] PM.ask failed: %s", exc)

        # Direct HFBrain fallback
        try:
            from modules.hf_brain import HFBrain
            hf = HFBrain()
            if getattr(hf, "enabled", False):
                full_prompt = (system + "\n\n" + prompt) if system else prompt
                result = hf.ask_single(full_prompt)
                if result and result.strip():
                    return result.strip()
        except Exception as exc:
            log.debug("[ChatCompletions] HFBrain fallback failed: %s", exc)

        return None

    def _fallback_response(self, question: str, context: str) -> str:
        """Return a deterministic no-LLM fallback when all inference is unavailable."""
        if context.strip():
            return (
                f"Based on stored knowledge:\n{context[:500]}\n\n"
                f"(LLM unavailable — direct knowledge excerpt for: {question[:80]})"
            )
        return (
            f"I don't have specific information about '{question[:80]}' yet.  "
            "Try 'self-research <topic>' to learn more."
        )

    # ------------------------------------------------------------------
    # Internal: persistence
    # ------------------------------------------------------------------

    def _persist(self, question: str, response: str) -> None:
        """Persist one exchange to LLMChatMemory."""
        mem = self._get_chat_memory()
        if mem is None:
            return
        try:
            mem.add("user", question)
            mem.add("assistant", response)
        except Exception as exc:
            log.debug("[ChatCompletions] persist failed: %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[ChatCompletions] = None
_singleton_lock = threading.Lock()


def get_chat_completions(
    llm_provider_manager: Any = None,
    llm_chat_memory: Any = None,
    graph_rag_pipeline: Any = None,
    **kwargs: Any,
) -> ChatCompletions:
    """Return (and lazily create) the process-wide ChatCompletions singleton.

    All arguments are used only on the first call.  Subsequent calls return
    the same instance regardless of arguments.
    """
    global _instance
    if _instance is None:
        with _singleton_lock:
            if _instance is None:
                _instance = ChatCompletions(
                    llm_provider_manager=llm_provider_manager,
                    llm_chat_memory=llm_chat_memory,
                    graph_rag_pipeline=graph_rag_pipeline,
                    **kwargs,
                )
                log.debug("[ChatCompletions] Singleton created")
    return _instance


if __name__ == "__main__":
    print("Running chat_completions.py")
