#!/usr/bin/env python3
"""
modules/global_code_intelligence/knowledge_reasoner.py

Answer architecture and pattern questions by traversing the global code graph
and augmenting LLM prompts with retrieved context.

Reasoning pipeline::

    query
      ↓
    graph traversal (PatternGraphBuilder)
      ↓
    semantic search  (CodeEmbeddingIndex)
      ↓
    pattern aggregation
      ↓
    LLM explanation (optional, via niblit LLM adapter)

Usage::

    from modules.global_code_intelligence.knowledge_reasoner import KnowledgeReasoner
    reasoner = KnowledgeReasoner(graph=pgb, index=idx)
    answer = reasoner.answer("Which architecture works best for real-time chat?")
    examples = reasoner.find_examples("transformer architecture")
"""

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("KnowledgeReasoner")


class KnowledgeReasoner:
    """
    Reason over the GCIM knowledge graph to answer architecture questions.

    Args:
        graph:  PatternGraphBuilder instance.
        index:  CodeEmbeddingIndex instance.
        llm:    Optional LLM adapter (must have .generate(prompt) → str).
    """

    def __init__(
        self,
        graph: Optional[Any] = None,
        index: Optional[Any] = None,
        llm: Optional[Any] = None,
    ) -> None:
        self._graph = graph
        self._index = index
        self._llm = llm

    # ── public API ────────────────────────────────────────────────────────────

    def answer(self, question: str, top_k: int = 5) -> Dict[str, Any]:
        """
        Answer a software architecture or pattern question.

        Returns dict with keys:
            question, architectures, examples, explanation
        """
        result: Dict[str, Any] = {
            "question": question,
            "architectures": [],
            "examples": [],
            "explanation": "",
        }

        # 1 — Graph traversal for relevant architectures
        if self._graph is not None:
            try:
                archs = self._graph.find_architectures_for(question)
                result["architectures"] = archs
            except Exception as exc:  # noqa: BLE001
                log.debug("KnowledgeReasoner: graph traversal failed: %s", exc)

        # 2 — Semantic search for code examples
        if self._index is not None:
            try:
                hits = self._index.search(question, top_k=top_k)
                result["examples"] = [h.get("text", "") for h in hits if h.get("text")]
            except Exception as exc:  # noqa: BLE001
                log.debug("KnowledgeReasoner: index search failed: %s", exc)

        # 3 — LLM explanation (optional)
        if self._llm is not None and (result["architectures"] or result["examples"]):
            try:
                context = self._build_context(result)
                prompt = f"""You are a software architecture expert.

Question: {question}

Relevant architectures: {', '.join(result['architectures'])}

Code examples:
{chr(10).join(result['examples'][:3])}

Provide a concise, actionable answer in 3–5 sentences."""
                result["explanation"] = self._llm.generate(prompt) or ""
            except Exception as exc:  # noqa: BLE001
                log.debug("KnowledgeReasoner: LLM explanation failed: %s", exc)

        if not result["explanation"] and result["architectures"]:
            result["explanation"] = (
                f"Recommended architectures for '{question}': "
                + ", ".join(result["architectures"])
                + "."
            )

        return result

    def find_examples(self, concept: str, top_k: int = 5) -> List[str]:
        """Return code examples related to *concept* from the index."""
        if self._index is None:
            return []
        try:
            hits = self._index.search(concept, top_k=top_k)
            return [h.get("text", "") for h in hits if h.get("text")]
        except Exception as exc:  # noqa: BLE001
            log.debug("KnowledgeReasoner.find_examples: %s", exc)
            return []

    def find_related(self, concept: str, depth: int = 2) -> List[str]:
        """Return concepts related to *concept* via graph traversal."""
        if self._graph is None:
            return []
        try:
            return self._graph.related_concepts(concept, depth=depth)
        except Exception as exc:  # noqa: BLE001
            log.debug("KnowledgeReasoner.find_related: %s", exc)
            return []

    def augment_prompt(self, base_prompt: str, context_query: str, top_k: int = 3) -> str:
        """
        Augment *base_prompt* with retrieved architecture patterns.

        Used by the code generator to inject relevant patterns before calling
        the LLM.
        """
        examples = self.find_examples(context_query, top_k=top_k)
        related = self.find_related(context_query, depth=1)

        lines = [base_prompt, ""]
        if related:
            lines.append(f"Related concepts: {', '.join(related[:8])}")
        if examples:
            lines.append("Relevant patterns:")
            for ex in examples:
                lines.append(f"  - {ex[:200]}")
        return "\n".join(lines)

    # ── internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _build_context(result: Dict[str, Any]) -> str:
        parts = []
        if result["architectures"]:
            parts.append("Architectures: " + ", ".join(result["architectures"]))
        if result["examples"]:
            parts.append("Examples:\n" + "\n".join(result["examples"][:3]))
        return "\n".join(parts)


if __name__ == "__main__":
    print('Running knowledge_reasoner.py')
