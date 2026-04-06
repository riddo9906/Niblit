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


def _get_chat_memory():
    """Return the process-level LLMChatMemory singleton."""
    global _LLMChatMemory  # pylint: disable=global-statement
    if _LLMChatMemory is None:
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
    def _build_context(self, user_prompt: str):
        """Build the messages list for the LLM from persistent chat memory.

        Priority:
        1. Persistent chat memory (LLMChatMemory) — survives across sessions.
        2. Fallback to in-memory recent_interactions from KnowledgeDB.
        """
        messages = []

        # 1. Load from persistent chat memory (cross-session)
        if self.chat_memory:
            stored = self.chat_memory.load_messages(limit=30)
            if stored:
                messages.extend(stored)
                log.debug("[HFBrain] Loaded %d messages from persistent chat memory", len(stored))

        # 2. Fallback: if no persistent history, try the DB interactions
        if not messages:
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
