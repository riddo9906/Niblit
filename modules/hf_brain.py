#!/usr/bin/env python3
"""
HFBrain — Unified Stateful LLM Brain for Niblit
Integrated with KnowledgeDB / MemoryManager and persistent LLMChatMemory.
Author: Riyaad Behardien
"""

import logging
import os
import requests

log = logging.getLogger("HFBrain")

# Lazy import — avoids circular dependency at module-load time.
_LLMChatMemory = None
_LLM_CHAT_MEMORY_TRIED = False


def _get_chat_memory():
    """Return the process-level LLMChatMemory singleton."""
    global _LLMChatMemory, _LLM_CHAT_MEMORY_TRIED  # pylint: disable=global-statement
    if _LLMChatMemory is None and not _LLM_CHAT_MEMORY_TRIED:
        _LLM_CHAT_MEMORY_TRIED = True
        try:
            from modules.llm_chat_memory import get_llm_chat_memory
            _LLMChatMemory = get_llm_chat_memory()
        except Exception as exc:
            log.debug("[HFBrain] LLMChatMemory unavailable: %s", exc)
    return _LLMChatMemory


class HFBrain:
    """
    HuggingFace Router LLM interface for Niblit.
    Fully stateful via unified memory DB.
    Supports runtime pause/resume toggle that preserves full chat history.

    Chat history is persisted to SQLite via :class:`LLMChatMemory` so the
    inference provider sees the full conversation across sessions — even
    after a restart or a ``toggle-llm off`` → ``toggle-llm on`` cycle.
    """

    def __init__(self, db):
        self.db = db

        # KEEP YOUR MODEL — configurable via NIBLIT_LLM_MODEL env var
        self.model = os.getenv("NIBLIT_LLM_MODEL") or "moonshotai/Kimi-K2-Instruct-0905"

        self.enabled = True

        # Try the same env var priority order used across the codebase:
        # HF_TOKEN → HUGGINGFACE_TOKEN → HF_API_KEY
        self.token = (
            os.getenv("HF_TOKEN")
            or os.getenv("HUGGINGFACE_TOKEN")
            or os.getenv("HF_API_KEY")
        )

        if not self.token:
            log.warning("[HFBrain] No HF token found (HF_TOKEN / HUGGINGFACE_TOKEN / HF_API_KEY), HFBrain disabled")
            self.enabled = False
            # Emit a visible banner so users understand why AI responses are absent.
            _warn = (
                "\n"
                "┌─────────────────────────────────────────────────────┐\n"
                "│  ⚠️  NO LLM TOKEN — AI responses are disabled        │\n"
                "│  Set HF_TOKEN in your .env file and restart Niblit.  │\n"
                "│  Example:  HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxx  │\n"
                "│  Alternatively set OPENAI_API_KEY or ANTHROPIC_API_KEY│\n"
                "└─────────────────────────────────────────────────────┘"
            )
            print(_warn)
            log.warning(_warn)

        # HuggingFace router endpoint
        self.url = "https://router.huggingface.co/v1/chat/completions"

        # Persistent chat memory for cross-session context
        self.chat_memory = _get_chat_memory()

    # -------------------------
    # Toggle control (pause / resume)
    # -------------------------
    def enable(self):
        """Resume the LLM — reloads full chat history from persistent store."""
        self.enabled = True
        if self.chat_memory:
            self.chat_memory.resume()
            log.info("[HFBrain] Enabled — %d messages reloaded from chat memory",
                     self.chat_memory.message_count())

    def disable(self):
        """Pause the LLM — chat history is preserved, not discarded."""
        if self.chat_memory:
            self.chat_memory.pause()
            log.info("[HFBrain] Disabled (paused) — chat history preserved")
        self.enabled = False

    def is_enabled(self):
        return self.enabled and self.token is not None

    # -------------------------
    # Context assembly — persistent chat memory
    # -------------------------
    # Niblit identity + runtime architecture system prompt.
    # Describes Niblit's full logical runtime so the inference provider can
    # give context-aware, architecture-relevant responses rather than generic ones.
    _SYSTEM_PROMPT = (
        "You are the AI inference backend for Niblit — an autonomous, self-learning AI "
        "assistant that runs on-device (Termux/Android or Linux desktop). "
        "Niblit's logical runtime consists of the following layers:\n\n"

        "CORE RUNTIME\n"
        "• niblit_core.py — orchestrates all subsystems, exposes core.handle()\n"
        "• niblit_router.py — intent-based message router with ChatDetector that classifies "
        "  messages into: knowledge_share, self_referential, self_introspection, info_query, "
        "  chat, system. Commands (e.g. 'notifications', 'status', 'loops') are dispatched "
        "  before reaching the LLM.\n"
        "• main.py — CLI shell loop; DIRECT_COMMANDS (notifications, status, self-heal, "
        "  self-teach, threads, reload_params, run_selfheal) run without touching the router.\n\n"

        "KNOWLEDGE & LEARNING\n"
        "• Autonomous Learning Engine (ALE) — background thread that continuously researches "
        "  topics from a GradedCurriculum (Grade 1 → University). Writes 'ale_learned:' "
        "  and 'topic_knowledge:' ledger entries to the KB after each cycle.\n"
        "• KnowledgeComprehension — concept extraction layer wired into ALE and SelfTeacher. "
        "  Writes 'ale_concepts:' and enriched 'topic_knowledge:' entries.\n"
        "• SelfTeacher — on-demand teach() cycle that triggers ALE research + comprehension.\n"
        "• SelfHealer — monitors module health, repairs import failures, runs background.\n"
        "• LLMTrainingAgent — generates structured Q/A pairs from knowledge gaps and stores "
        "  them via BrainTrainer.\n\n"

        "MEMORY & STORAGE\n"
        "• KnowledgeDB (SQLite) — stores facts, interactions, ledger entries. "
        "  Key ledger prefixes: 'ale_learned:<topic>', 'topic_knowledge:<topic>', "
        "  'ale_concepts:<topic>'.\n"
        "• LLMChatMemory (SQLite) — persists the full LLM conversation history across "
        "  restarts and toggle-llm off/on cycles.\n"
        "• Optional Qdrant vector store — semantic search over embedded snippets.\n\n"

        "EMBEDDING\n"
        "• Model: intfloat/multilingual-e5-small (384-dim, 100 languages). "
        "  Configured via EMBEDDING_MODEL env var. Loaded once per process with "
        "  thread-safe singleton caching in vector_store.py.\n\n"

        "NOTIFICATIONS\n"
        "• Background threads push output to core/notification_queue.py (notif_queue). "
        "  The 'notifications' command drains this queue. All background log output is "
        "  captured here so it never interrupts the user's prompt.\n\n"

        "RESPONSE GUIDELINES\n"
        "• When the user discusses Niblit's internals, modules, or architecture, answer "
        "  specifically within the context of the runtime described above.\n"
        "• When the user proposes improvements (e.g. 'add X to the concept extractor'), "
        "  evaluate the suggestion against Niblit's existing stack — ALE, "
        "  KnowledgeComprehension, vector_store, router — and explain how it would integrate.\n"
        "• Be accurate and concise. Niblit stores your responses as training data."
    )

    def _build_context(self, user_prompt: str):
        """Build the messages list for the LLM from persistent chat memory.

        Priority:
        0. System prompt with Niblit identity and runtime architecture.
        1. Dynamic KB snapshot — injects the topics Niblit has recently learned so
           the LLM can give context-aware responses when the user discusses them.
        2. Persistent chat memory (LLMChatMemory) — survives across sessions.
        3. Fallback to in-memory recent_interactions from KnowledgeDB.
        """
        messages = []

        # 0. System prompt — gives the inference provider full Niblit awareness
        messages.append({
            "role": "system",
            "content": self._SYSTEM_PROMPT,
        })

        # 1. Dynamic KB snapshot — surface the topics Niblit has learned so the
        #    LLM can reference real KB content rather than guessing generically.
        kb_snapshot = self._build_kb_snapshot()
        if kb_snapshot:
            messages.append({
                "role": "system",
                "content": kb_snapshot,
            })

        # 2. Load from persistent chat memory (cross-session)
        if self.chat_memory:
            stored = self.chat_memory.load_messages(limit=30)
            if stored:
                messages.extend(stored)
                log.debug("[HFBrain] Loaded %d messages from persistent chat memory", len(stored))

        # 3. Fallback: if no persistent history, try the DB interactions
        if len(messages) <= 2:  # system prompt + optional KB snapshot only
            try:
                recent = self.db.recent_interactions(15)
                for entry in recent:
                    role = entry.get("role", "user")
                    text = entry.get("text", "")
                    if text:
                        messages.append({
                            "role": role if role in ("user", "assistant") else "user",
                            "content": text
                        })
            except Exception:
                pass

        # Append the current user prompt
        messages.append({
            "role": "user",
            "content": user_prompt
        })

        return messages

    def _build_kb_snapshot(self) -> str:
        """Return a compact summary of what Niblit has recently learned.

        Reads up to 5 ``topic_knowledge:`` ledger entries (comprehension-enriched
        summaries) from the KB, falling back to ``ale_learned:`` entries when the
        ledger is sparse.  The result is injected into the LLM context as a
        system message so the inference provider knows Niblit's current KB state.
        """
        if self.db is None:
            return ""
        try:
            facts = self.db.list_facts(limit=200) if hasattr(self.db, "list_facts") else []
        except Exception:
            return ""

        topics: dict = {}
        ale_topics: list = []
        for f in facts:
            key = f.get("key", "") or f.get("tags", "")
            val = f.get("value", "") or f.get("text", "")
            if not key or not val:
                continue
            val_str = val if isinstance(val, str) else str(val)
            if val_str.startswith("No data found"):
                continue
            if isinstance(key, str) and key.startswith("topic_knowledge:"):
                topic_name = key[len("topic_knowledge:"):]
                if topic_name not in topics:
                    topics[topic_name] = val_str[:120]
            elif isinstance(key, str) and key.startswith("ale_learned:") and len(ale_topics) < 5:
                topic_name = key[len("ale_learned:"):]
                ale_topics.append(topic_name)

        lines = []
        if topics:
            lines.append("NIBLIT CURRENT KNOWLEDGE TOPICS (from KB ledger):")
            for name, summary in list(topics.items())[:5]:
                lines.append(f"• {name}: {summary.strip()}")
        elif ale_topics:
            lines.append("NIBLIT RECENTLY STUDIED TOPICS (ALE queue):")
            for name in ale_topics[:5]:
                lines.append(f"• {name}")

        return "\n".join(lines) if lines else ""

    # -------------------------
    # Local fallback
    # -------------------------
    def _fallback(self, prompt: str):
        # Return None so callers (niblit_brain.think) can apply their own fallback
        # instead of echoing the full context prompt back to the user.
        return None

    # -------------------------
    # Single query
    # -------------------------
    def ask_single(self, prompt: str) -> str:
        if not self.is_enabled():
            return self._fallback(prompt)

        try:
            messages = self._build_context(prompt)

            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }

            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 350
            }

            r = requests.post(
                self.url,
                headers=headers,
                json=payload,
                timeout=90
            )

            if r.status_code == 401:
                log.warning("[HFBrain] HTTP 401 — invalid or expired token; disabling HFBrain")
                self.enabled = False
                return None

            if r.status_code != 200:
                log.warning("[HFBrain] HTTP %d: %s", r.status_code, r.text[:200])
                return None

            data = r.json()
            response = data["choices"][0]["message"]["content"].strip()

            if response:
                # Persist both sides to the chat memory (cross-session)
                if self.chat_memory:
                    self.chat_memory.add("user", prompt)
                    self.chat_memory.add("assistant", response)

                # Also persist to the general KnowledgeDB for other modules
                self.db.add_interaction("user", prompt)
                self.db.add_interaction("assistant", response)

                # Optional context hook
                if hasattr(self.db, "add_hf_context"):
                    self.db.add_hf_context(response)

            return response

        except Exception as e:
            return f"[HFBrain Error] {e}"

    # -------------------------
    # Chat memory status
    # -------------------------
    def chat_memory_status(self) -> dict:
        """Return the current state of the persistent chat memory."""
        if self.chat_memory:
            return self.chat_memory.status()
        return {"available": False}


if __name__ == "__main__":
    print("HFBrain requires unified DB. Do not run standalone.")
