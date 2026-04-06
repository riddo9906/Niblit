#!/usr/bin/env python3
"""
modules/llm_training_agent.py — LLM-assisted training agent for Niblit.

This agent bridges Niblit's **BrainTrainer** with the **LLM inference
provider** (HFBrain / HFAdapter) to create a closed-loop training system:

1. **Gap Detection** — Queries the knowledge base and ALE to find topics
   where Niblit has insufficient facts or where user questions went
   unanswered.
2. **LLM Training Requests** — Sends structured prompts to the inference
   provider asking it to *teach* Niblit about each gap topic.  The system
   prompt contains a full description of Niblit's architecture so the LLM
   understands how to best train it.
3. **Training Data Storage** — Parses the LLM response into structured
   training records that are fed directly into BrainTrainer and persisted
   to KnowledgeDB for long-term retention.
4. **BrainTrainer Integration** — The agent is called from ALE step 24
   (BrainTraining) and can also be invoked manually via the CLI:
   ``llm-train status | run | gaps``

Usage::

    from modules.llm_training_agent import get_llm_training_agent

    agent = get_llm_training_agent(
        brain_trainer=brain_trainer,
        hf_brain=hf_brain,
        knowledge_db=knowledge_db,
    )
    result = agent.run_training_cycle()
"""

import logging
import re
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("LLMTrainingAgent")

# ── Niblit system identity prompt ─────────────────────────────────────────────
# This is injected as the system message so the LLM inference provider fully
# understands what Niblit is and how best to produce training material.

NIBLIT_IDENTITY_PROMPT = """\
You are the training backend for **Niblit**, an autonomous self-learning AI system.

=== WHAT NIBLIT IS ===
Niblit is a modular AI that learns autonomously through:
• An Autonomous Learning Engine (ALE) that researches topics 24/7
• A BrainTrainer that ingests research into structured training pairs
• A GradedCurriculum (Grade 1 → University) that controls topic progression
• A KnowledgeDB that stores facts, research results, and learning logs
• A SelfTeacher that synthesises lessons from research data
• Chat memory that persists user conversations across sessions

=== HOW NIBLIT LEARNS ===
Niblit's training data is structured as:
1. **Training pairs**: {"prompt": "...", "response": "..."} — stored in BrainTrainer
2. **Facts**: {"key": "topic_knowledge:X", "value": "...", "tags": [...]} — stored in KnowledgeDB
3. **Cognitive domains**: language, communication, reasoning, calculating, chat_completions, responses

=== YOUR ROLE ===
When asked to teach Niblit about a topic:
1. Provide clear, factual, well-structured information
2. Include concrete examples and definitions
3. Structure your response so it can be parsed into training pairs
4. Use the format:  Q: <question>  A: <answer>  for each teaching point
5. Keep answers concise (1-3 sentences each) — they become training data
6. Focus on the specific topic requested — Niblit learns best from focused lessons
7. If the topic is foundational (math, language, science), start from basics
8. Adapt your teaching to Niblit's current education level when specified

=== OUTPUT FORMAT ===
Always respond with numbered Q/A pairs like:
1. Q: What is [concept]?
   A: [Clear definition]
2. Q: How does [concept] work?
   A: [Explanation with example]
3. Q: Why is [concept] important?
   A: [Practical relevance]
(Continue for 5-10 pairs per topic)
"""

# Maximum training pairs to generate per topic
_MAX_PAIRS_PER_TOPIC = 10
# Maximum topics to train on per cycle
_MAX_TOPICS_PER_CYCLE = 5
# Minimum gap threshold — topics with fewer facts than this are gaps
_MIN_FACTS_THRESHOLD = 3


class LLMTrainingAgent:
    """Agent that asks the LLM inference provider to generate training data
    for Niblit's BrainTrainer based on detected knowledge gaps.
    """

    def __init__(
        self,
        brain_trainer: Optional[Any] = None,
        hf_brain: Optional[Any] = None,
        knowledge_db: Optional[Any] = None,
        ale: Optional[Any] = None,
        graded_curriculum: Optional[Any] = None,
    ) -> None:
        self.brain_trainer = brain_trainer
        self.hf_brain = hf_brain
        self.knowledge_db = knowledge_db
        self.ale = ale
        self.graded_curriculum = graded_curriculum

        # Track what we've trained on to avoid repeating recent topics
        self._recently_trained: Dict[str, float] = {}
        self._total_pairs_generated = 0
        self._total_cycles = 0
        self._cooldown_secs = 3600  # Don't retrain same topic within 1 hour

    # ── Gap detection ─────────────────────────────────────────────────────────

    def detect_gaps(self, max_gaps: int = _MAX_TOPICS_PER_CYCLE) -> List[str]:
        """Find topics where Niblit's knowledge is insufficient.

        Sources:
        1. ALE's detect_knowledge_gaps() — topics below coverage threshold
        2. GradedCurriculum current grade topics not yet mastered
        3. Unanswered user questions from the gap-learning queue
        """
        gaps: List[str] = []
        now = time.time()

        # 1. ALE knowledge gaps
        if self.ale and hasattr(self.ale, "detect_knowledge_gaps"):
            try:
                ale_gaps = self.ale.detect_knowledge_gaps(max_gaps=max_gaps * 2)
                for g in ale_gaps:
                    if g not in gaps and self._not_recently_trained(g, now):
                        gaps.append(g)
            except Exception as exc:
                log.debug("[LLMTrainingAgent] ALE gap detection failed: %s", exc)

        # 2. Curriculum topics with insufficient facts
        if self.graded_curriculum and len(gaps) < max_gaps:
            try:
                grade = self.graded_curriculum.current_grade
                for topic in grade.topics:
                    if topic not in gaps and self._not_recently_trained(topic, now):
                        # Check if we have enough facts for this topic
                        count = self._count_facts(topic)
                        if count < _MIN_FACTS_THRESHOLD:
                            gaps.append(topic)
                            if len(gaps) >= max_gaps:
                                break
            except Exception as exc:
                log.debug("[LLMTrainingAgent] Curriculum gap scan failed: %s", exc)

        # 3. Research topics from ALE queue
        if self.ale and len(gaps) < max_gaps:
            try:
                for topic in getattr(self.ale, "research_topics", [])[:20]:
                    if topic not in gaps and self._not_recently_trained(topic, now):
                        count = self._count_facts(topic)
                        if count < _MIN_FACTS_THRESHOLD:
                            gaps.append(topic)
                            if len(gaps) >= max_gaps:
                                break
            except Exception:
                pass

        return gaps[:max_gaps]

    def _not_recently_trained(self, topic: str, now: float) -> bool:
        """Return True if the topic hasn't been trained within the cooldown."""
        last = self._recently_trained.get(topic, 0)
        return (now - last) > self._cooldown_secs

    def _count_facts(self, topic: str) -> int:
        """Count how many facts exist for a topic in the KnowledgeDB."""
        if not self.knowledge_db:
            return 0
        try:
            for method_name in ("search", "recall"):
                fn = getattr(self.knowledge_db, method_name, None)
                if fn:
                    results = fn(topic, limit=_MIN_FACTS_THRESHOLD + 1)
                    return len(results) if results else 0
        except Exception:
            pass
        return 0

    # ── LLM training request ─────────────────────────────────────────────────

    def _get_grade_context(self) -> str:
        """Return a string describing Niblit's current education level."""
        if self.graded_curriculum:
            try:
                grade = self.graded_curriculum.current_grade
                return f"Niblit is currently at {grade.name}: {grade.description}"
            except Exception:
                pass
        return "Niblit is at an early learning stage."

    def request_training(self, topic: str) -> List[Dict[str, str]]:
        """Ask the LLM to generate training pairs for the given topic.

        Returns a list of ``{"prompt": "...", "response": "..."}`` dicts
        ready for BrainTrainer ingestion.
        """
        if not self.hf_brain or not self.hf_brain.is_enabled():
            log.debug("[LLMTrainingAgent] HFBrain not available for training request")
            return []

        grade_ctx = self._get_grade_context()
        user_prompt = (
            f"Teach Niblit about: **{topic}**\n\n"
            f"Current level: {grade_ctx}\n\n"
            f"Generate {_MAX_PAIRS_PER_TOPIC} Q/A training pairs about this topic. "
            f"Start from the basics and build up. Each answer should be 1-3 sentences."
        )

        try:
            # Build messages with identity system prompt
            messages = [
                {"role": "system", "content": NIBLIT_IDENTITY_PROMPT},
                {"role": "user", "content": user_prompt},
            ]

            # Use the HFBrain's token and endpoint directly for this training call
            import requests
            headers = {
                "Authorization": f"Bearer {self.hf_brain.token}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.hf_brain.model,
                "messages": messages,
                "temperature": 0.3,  # Lower temperature for factual training data
                "max_tokens": 800,
            }

            r = requests.post(
                self.hf_brain.url,
                headers=headers,
                json=payload,
                timeout=120,
            )

            if r.status_code != 200:
                log.warning("[LLMTrainingAgent] Training request failed: HTTP %d", r.status_code)
                return []

            data = r.json()
            content = data["choices"][0]["message"]["content"].strip()

            # Parse Q/A pairs from the response
            pairs = self._parse_qa_pairs(content, topic)
            if pairs:
                log.info(
                    "[LLMTrainingAgent] Generated %d training pairs for '%s'",
                    len(pairs), topic,
                )
            return pairs

        except Exception as exc:
            log.debug("[LLMTrainingAgent] Training request failed: %s", exc)
            return []

    def _parse_qa_pairs(self, text: str, topic: str) -> List[Dict[str, str]]:
        """Parse numbered Q/A pairs from the LLM's response text."""
        pairs: List[Dict[str, str]] = []

        # Pattern: "N. Q: ... A: ..." or "Q: ... A: ..."
        # Split on numbered items first
        blocks = re.split(r'\n\s*\d+[\.\)]\s*', text)

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            # Try to find Q: and A: markers
            q_match = re.search(r'Q:\s*(.+?)(?:\n|$)', block, re.IGNORECASE)
            a_match = re.search(r'A:\s*(.+)', block, re.IGNORECASE | re.DOTALL)

            if q_match and a_match:
                question = q_match.group(1).strip()
                answer = a_match.group(1).strip()
                # Clean up: remove trailing Q: from answer if it bleeds
                answer = re.split(r'\n\s*\d+[\.\)]\s*Q:', answer)[0].strip()
                answer = re.split(r'\nQ:', answer)[0].strip()

                if question and answer and len(answer) > 10:
                    pairs.append({
                        "prompt": question,
                        "response": answer,
                        "topic": topic,
                        "source": "llm_training_agent",
                    })

        return pairs[:_MAX_PAIRS_PER_TOPIC]

    # ── Training data storage ─────────────────────────────────────────────────

    def store_training_data(self, pairs: List[Dict[str, str]], topic: str) -> int:
        """Persist training pairs to BrainTrainer and KnowledgeDB.

        Returns the number of pairs successfully stored.
        """
        stored = 0

        for pair in pairs:
            prompt = pair.get("prompt", "")
            response = pair.get("response", "")
            if not prompt or not response:
                continue

            # 1. Feed to BrainTrainer (in-memory context store)
            if self.brain_trainer:
                try:
                    self.brain_trainer.record_exchange(prompt, response)
                    stored += 1
                except Exception:
                    pass

            # 2. Persist to KnowledgeDB as a fact
            if self.knowledge_db and hasattr(self.knowledge_db, "add_fact"):
                try:
                    ts = int(time.time())
                    self.knowledge_db.add_fact(
                        f"llm_training:{topic}:{ts}:{stored}",
                        f"Q: {prompt}\nA: {response}",
                        tags=["training", "llm_generated", topic],
                    )
                except Exception:
                    pass

            # 3. Also store as a research ingest for BrainTrainer facts
            if self.brain_trainer and hasattr(self.brain_trainer, "ingest_research"):
                try:
                    self.brain_trainer.ingest_research(topic, response)
                except Exception:
                    pass

        if stored:
            self._recently_trained[topic] = time.time()
            self._total_pairs_generated += stored
            log.info(
                "[LLMTrainingAgent] Stored %d training pairs for '%s'",
                stored, topic,
            )

        return stored

    # ── Full training cycle ───────────────────────────────────────────────────

    def run_training_cycle(self) -> str:
        """Execute one complete LLM-assisted training cycle.

        1. Detect knowledge gaps
        2. For each gap topic, request training data from the LLM
        3. Store the generated pairs in BrainTrainer + KnowledgeDB

        Returns a summary string.
        """
        self._total_cycles += 1

        gaps = self.detect_gaps()
        if not gaps:
            return "LLMTrainingAgent: no knowledge gaps detected — training up to date."

        total_stored = 0
        results = []

        for topic in gaps:
            pairs = self.request_training(topic)
            if pairs:
                stored = self.store_training_data(pairs, topic)
                total_stored += stored
                results.append(f"  ✓ {topic}: {stored} pairs")
            else:
                results.append(f"  ○ {topic}: no training data generated")

        summary = (
            f"LLMTrainingAgent cycle #{self._total_cycles}: "
            f"{len(gaps)} gaps, {total_stored} training pairs stored\n"
            + "\n".join(results)
        )
        log.info("[LLMTrainingAgent] %s", summary)
        return summary

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Return a summary of the training agent's state."""
        return {
            "total_cycles": self._total_cycles,
            "total_pairs_generated": self._total_pairs_generated,
            "recently_trained_topics": len(self._recently_trained),
            "cooldown_secs": self._cooldown_secs,
            "hf_brain_available": bool(
                self.hf_brain and self.hf_brain.is_enabled()
            ),
            "brain_trainer_available": self.brain_trainer is not None,
            "knowledge_db_available": self.knowledge_db is not None,
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[LLMTrainingAgent] = None


def get_llm_training_agent(
    brain_trainer: Optional[Any] = None,
    hf_brain: Optional[Any] = None,
    knowledge_db: Optional[Any] = None,
    ale: Optional[Any] = None,
    graded_curriculum: Optional[Any] = None,
) -> LLMTrainingAgent:
    """Return (and lazily create) the process-level LLMTrainingAgent singleton."""
    global _instance  # pylint: disable=global-statement
    if _instance is None:
        _instance = LLMTrainingAgent(
            brain_trainer=brain_trainer,
            hf_brain=hf_brain,
            knowledge_db=knowledge_db,
            ale=ale,
            graded_curriculum=graded_curriculum,
        )
    else:
        # Update references if new ones are provided (late wiring)
        if brain_trainer is not None:
            _instance.brain_trainer = brain_trainer
        if hf_brain is not None:
            _instance.hf_brain = hf_brain
        if knowledge_db is not None:
            _instance.knowledge_db = knowledge_db
        if ale is not None:
            _instance.ale = ale
        if graded_curriculum is not None:
            _instance.graded_curriculum = graded_curriculum
    return _instance
