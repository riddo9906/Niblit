#!/usr/bin/env python3
"""
agents/coding_agent.py — Code generation agent.

Handles ``task_type="code_generation"`` tasks.  Uses the available LLM
adapters (HF → OpenAI → Anthropic) and the CodeGenerator template engine
as a fallback.

Architecture role (Phase 2)
---------------------------
    ResearchAgent (stores KB facts)
           │
           ▼
    CodingAgent (reads KB → generates code → saves to builds/)
           │
           ▼
    TestingAgent (validates)
"""

import logging
from typing import Any, Dict, List, Optional

from agents.base_agent import BaseAgent
from core.event_bus import Event, EventBus, EventType
from core.task_queue import Task

log = logging.getLogger("CodingAgent")


class CodingAgent(BaseAgent):
    """
    Generates code from research context using the best available LLM.

    LLM priority: HFLLMAdapter → OpenAIAdapter → AnthropicAdapter → template fallback.

    Args:
        hf_llm:         modules.llm_module.HFLLMAdapter instance.
        openai_adapter: modules.openai_adapter.OpenAIAdapter instance.
        anthropic_adapter: modules.anthropic_adapter.AnthropicAdapter instance.
        code_generator: modules.code_generator.CodeGenerator instance.
        knowledge_db:   KB instance to read research facts from.
    """

    HANDLED_TASK_TYPES = ["code_generation", "generate_code", "code_improvement"]

    def __init__(
        self,
        hf_llm: Optional[Any] = None,
        openai_adapter: Optional[Any] = None,
        anthropic_adapter: Optional[Any] = None,
        code_generator: Optional[Any] = None,
        knowledge_db: Optional[Any] = None,
    ) -> None:
        super().__init__("coding")
        self._hf_llm = hf_llm
        self._openai = openai_adapter
        self._anthropic = anthropic_adapter
        self._code_gen = code_generator
        self._kb = knowledge_db

    # ── execution ─────────────────────────────────────────────────────────────

    def _execute(self, task: Task, event_bus: EventBus) -> Dict[str, Any]:
        language = task.payload.get("language", "python")
        purpose = task.payload.get("purpose", "")
        context = task.payload.get("context", "")
        topic = task.payload.get("topic", purpose)

        if not purpose and not topic:
            return {"error": "No purpose/topic provided", "code": ""}

        # Pull research context from KB
        research_text = self._gather_research(topic or purpose, language)
        combined_context = "\n".join(filter(None, [context, research_text]))[:600]

        code = ""
        # Try LLMs in priority order
        llm = self._best_llm()
        if llm is not None:
            try:
                code = llm.generate_code(language, purpose or topic, combined_context) or ""
            except Exception as exc:
                self._log.debug("LLM code gen failed: %s", exc)

        # Fallback to template engine
        if not code and self._code_gen is not None:
            try:
                result = self._code_gen.generate(language, purpose or topic)
                code = result.get("code", "") if isinstance(result, dict) else str(result)
            except Exception as exc:
                self._log.debug("template code gen failed: %s", exc)

        if not code:
            code = f"# TODO: implement {purpose or topic} in {language}\npass\n"

        output = {
            "language": language,
            "purpose": purpose or topic,
            "code": code,
            "success": bool(code.strip()),
        }
        self._publish(event_bus, EventType.CODE_GENERATION_COMPLETED, {
            "language": language, "length": len(code)
        })
        return output

    # ── helpers ───────────────────────────────────────────────────────────────

    def _best_llm(self) -> Optional[Any]:
        """Return first available LLM adapter."""
        for adapter in (self._hf_llm, self._openai, self._anthropic):
            if adapter is not None:
                try:
                    if hasattr(adapter, "is_online") and not adapter.is_online():
                        continue
                    if hasattr(adapter, "is_available") and not adapter.is_available():
                        continue
                    return adapter
                except Exception:
                    continue
        return None

    def _gather_research(self, topic: str, language: str) -> str:
        """Pull research snippets from KB related to topic."""
        if self._kb is None:
            return ""
        try:
            prefix = f"ale_research:{topic}"
            facts = self._kb.search(prefix, limit=3)
            if not facts:
                facts = self._kb.search(f"ale_github_code:{language}:{topic}", limit=3)
            snippets = []
            for f in (facts or []):
                val = f.get("value") or f.get("text", "") if isinstance(f, dict) else str(f)
                if val:
                    snippets.append(val[:200])
            return " | ".join(snippets)
        except Exception:
            return ""
