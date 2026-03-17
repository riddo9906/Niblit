#!/usr/bin/env python3
"""
ENHANCED SELF-RESEARCHER MODULE
Autonomous learning + Knowledge-based conversation without LLM

Research priority order
-----------------------
1. Serpex (niblit_agents.ResearchAgent) — validated, relevance-filtered web results
2. Searchcode (SearchcodeSearch) — structured code search (for code-related queries)
3. ResearcherEngine — semantic KB cache
4. Internet (InternetManager) — direct scrape, used only as last-resort fallback
5. History cache — previously seen results

Auto-research can be paused/resumed via ``stop_auto_research()`` /
``start_auto_research()``, which map to the ``auto-research stop/start``
CLI commands.
"""

from datetime import datetime
import json
import math
import html
import re
import time
import logging
from typing import List, Dict, Tuple, Optional, Any

log = logging.getLogger("SelfResearcher")
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s][%(name)s][%(levelname)s] %(message)s'
)

try:
    from niblit_agents.research_agent import is_relevant, should_reflect
except ImportError:  # pragma: no cover – graceful degradation
    def is_relevant(query: str, text: str, threshold: float = 0.5) -> bool:  # type: ignore[misc]
        query_terms = set(query.lower().split())
        if not query_terms:
            return True
        text_lower = text.lower()
        overlap = sum(1 for term in query_terms if term in text_lower)
        return (overlap / len(query_terms)) >= threshold

    def should_reflect(results: list) -> bool:  # type: ignore[misc]
        return len(results) > 0


class IntentAnalyzer:
    """Analyzes user queries to understand intent without LLM"""

    INTENT_PATTERNS = {
        "question": [r"^what\s+", r"^how\s+", r"^why\s+", r"^when\s+", r"^where\s+", r"^who\s+", r"\?$"],
        "request": [r"^(give|show|tell|explain|describe|list)\s+", r"^can\s+you\s+", r"^please\s+"],
        "comparison": [r"^(compare|difference|vs|versus|between)", r"^what's\s+the\s+difference"],
        "definition": [r"^what\s+is\s+", r"^define\s+", r"^meaning\s+of"],
        "recommendation": [r"^(recommend|suggest|best|better|alternative)", r"^what\s+should"],
        "technical": [r"(error|bug|issue|problem|fix|debug|crash)", r"(code|function|class|method|api)"],
        "how_to": [r"^how\s+to\s+", r"^(steps|guide|tutorial)\s+"],
        "opinion": [r"^(do\s+you\s+think|what\s+do\s+you\s+think|opinion\s+on)", r"^your\s+view"],
        "learning": [r"^(teach|learn|understand)\s+", r"^explain\s+(how|why|what)"],
    }

    @staticmethod
    def extract_intent(query: str) -> Tuple[str, Dict[str, Any]]:
        """
        Analyze query and extract intent + metadata
        Returns: (intent_type, metadata)
        """
        query_lower = query.lower().strip()
        keywords = re.findall(r'\b\w{3,}\b', query_lower)

        # Detect intent type
        intent_type = "general_question"
        for itype, patterns in IntentAnalyzer.INTENT_PATTERNS.items():
            if any(re.search(p, query_lower) for p in patterns):
                intent_type = itype
                break

        # Extract subject/topic
        subject = None
        if "what is" in query_lower:
            subject = query_lower.split("what is", 1)[1].strip().rstrip("?").strip()
        elif "how to" in query_lower:
            subject = query_lower.split("how to", 1)[1].strip().rstrip("?").strip()
        elif intent_type == "question":
            # Extract noun phrase after question word
            match = re.search(r'^(?:what|how|why|when|where|who)\s+(?:is|are|do|does|can|should|would|could)?\s+(.+?)\??$', query_lower)
            subject = match.group(1) if match else None

        return intent_type, {
            "subject": subject,
            "keywords": keywords[:5],
            "is_technical": any(kw in keywords for kw in ["error", "bug", "code", "api", "function", "debug"]),
            "is_definition": intent_type == "definition",
            "is_how_to": intent_type == "how_to",
            "raw_query": query
        }


class KnowledgeBasedResponder:
    """Generates responses using stored knowledge + internet without LLM"""

    def __init__(self, db, internet=None):
        self.db = db
        self.internet = internet

    def _search_knowledge_base(self, query: str, max_results: int = 5) -> List[str]:
        """Search internal knowledge base for relevant facts"""
        results = []
        try:
            if hasattr(self.db, "search_facts"):
                results = self.db.search_facts(query, max_results) or []
            elif hasattr(self.db, "list_facts"):
                all_facts = self.db.list_facts() or []
                # Simple keyword matching
                query_words = set(re.findall(r'\b\w{3,}\b', query.lower()))
                for fact in all_facts:
                    fact_key = str(fact.get("key", "")).lower()
                    fact_value = str(fact.get("value", "")).lower()
                    if any(word in fact_key or word in fact_value for word in query_words):
                        results.append(fact.get("value"))
                        if len(results) >= max_results:
                            break
        except Exception as e:
            log.debug(f"Knowledge base search failed: {e}")

        return results[:max_results]

    def _search_learning_log(self, query: str, max_results: int = 3) -> List[str]:
        """Search learning history for relevant information"""
        results = []
        try:
            if hasattr(self.db, "get_learning_log"):
                log_entries = self.db.get_learning_log() or []
                query_words = set(re.findall(r'\b\w{3,}\b', query.lower()))

                for entry in log_entries:
                    entry_text = str(entry.get("input", "") + " " + entry.get("response", "")).lower()
                    if any(word in entry_text for word in query_words):
                        results.append(entry.get("response"))
                        if len(results) >= max_results:
                            break
        except Exception as e:
            log.debug(f"Learning log search failed: {e}")

        return results[:max_results]

    def generate_response(self, query: str, intent_meta: Dict) -> Optional[str]:
        """
        Generate response using:
        1. Stored knowledge base
        2. Learning history
        3. Internet search
        4. Knowledge synthesis
        """
        # Step 1: Search knowledge base
        kb_results = self._search_knowledge_base(query, max_results=3)

        # Step 2: Search learning log
        learning_results = self._search_learning_log(query, max_results=2)

        # Step 3: Search internet if needed
        internet_results = []
        if self.internet and not kb_results:
            try:
                internet_results = self.internet.search(query, max_results=3) or []
            except Exception as e:
                log.debug(f"Internet search failed: {e}")

        # Step 4: Combine all sources
        all_results = kb_results + learning_results + internet_results
        if not all_results:
            return None

        # Step 5: Build response based on intent
        return self._synthesize_response(query, intent_meta, all_results)

    def _synthesize_response(self, query: str, intent_meta: Dict, sources: List[Any]) -> str:
        """Synthesize final response from multiple sources"""
        subject = intent_meta.get("subject", "topic")
        intent_type = intent_meta.get("intent_type", "question")

        # Convert all sources to strings
        source_texts = []
        for src in sources:
            if isinstance(src, dict):
                src_text = src.get("text", src.get("summary", str(src)))
            else:
                src_text = str(src)
            source_texts.append(src_text[:200])  # Limit each source to 200 chars

        # Build response based on intent
        if intent_type == "definition":
            response = f"Based on stored knowledge and research:\n\n{source_texts[0]}"
        elif intent_type == "how_to":
            response = f"Here's what I've learned about {subject}:\n\n" + "\n".join([f"• {t}" for t in source_texts[:3]])
        elif intent_type == "comparison":
            response = "Based on my knowledge:\n\n" + "\n".join([f"• {t}" for t in source_texts[:2]])
        elif intent_type == "technical":
            response = "Technical information:\n\n" + "\n".join(source_texts[:2])
        else:
            response = "From my knowledge base:\n\n" + source_texts[0]

        # Add confidence note
        if not sources:
            response += "\n\n[No relevant information found]"

        return response


class SelfResearcher:
    # Seconds to wait between consecutive auto-research queries so the full
    # ingestion → reflection → KB-store pipeline has time to settle before a
    # new topic is fetched.
    _AUTO_RESEARCH_INGEST_WAIT: float = 30.0

    def __init__(self, db, modules_registry=None, research_engine=None, llm_adapter=None,
                 max_history=100, relevance_threshold=0.7):
        self.db = db
        self.registry = modules_registry or {}

        # Internal Internet holder (dynamic wiring support)
        self._internet = None
        if "internet" in self.registry:
            self._internet = self.registry["internet"]
        elif hasattr(db, "internet"):
            self._internet = db.internet

        # ── Modern research backends (preferred over raw internet scraping) ──
        # These can be injected post-init via the property setters or directly
        # from the modules registry.  niblit_core injects them after init.
        self._serpex_agent = self.registry.get("serpex_agent")
        self._searchcode_search = self.registry.get("searchcode_search")
        # SemanticAgent for vector-store backed knowledge storage/retrieval
        self._semantic_agent = self.registry.get("semantic_agent")

        # Optional modules
        self.engine = research_engine
        self.llm = llm_adapter
        self.reflect = self.registry.get("reflect")
        self.self_teacher = self.registry.get("self_teacher")
        self.knowledge_db = db

        # Memory / history
        self.history = []
        self.responses = []
        self.max_history = max_history
        self.relevance_threshold = relevance_threshold

        # Autonomous learning tracking
        self.learning_patterns = {}
        self.query_feedback = {}

        # Auto-research enable/disable flag (start/stop commands)
        self._auto_research_enabled: bool = True

        # Knowledge-based responder
        self.knowledge_responder = KnowledgeBasedResponder(db, self._internet)

        # Intent analyzer
        self.intent_analyzer = IntentAnalyzer()

        log.info("✅ SelfResearcher initialized with knowledge-based responses + autonomous learning")

    # ─────────────────────────────────────────────
    @property
    def internet(self):
        return self._internet

    @internet.setter
    def internet(self, value):
        self._internet = value
        self.knowledge_responder.internet = value

    @property
    def serpex_agent(self):
        return self._serpex_agent

    @serpex_agent.setter
    def serpex_agent(self, value):
        self._serpex_agent = value

    @property
    def searchcode_search(self):
        return self._searchcode_search

    @searchcode_search.setter
    def searchcode_search(self, value):
        self._searchcode_search = value

    @property
    def semantic_agent(self):
        return self._semantic_agent

    @semantic_agent.setter
    def semantic_agent(self, value):
        self._semantic_agent = value

    def _ensure_serpex_agent(self) -> None:
        """Lazy-construct a ResearchAgent if one was not injected at init time."""
        if self._serpex_agent is not None:
            return
        try:
            from niblit_agents.research_agent import ResearchAgent as _RA
            self._serpex_agent = _RA()
            log.debug("[SelfResearcher] Lazily constructed ResearchAgent (Serpex)")
        except Exception as _e:
            log.debug("[SelfResearcher] ResearchAgent unavailable: %s", _e)

    # ─────────────────────────────────────────────
    # AUTO-RESEARCH CONTROL
    # ─────────────────────────────────────────────
    def start_auto_research(self) -> str:
        """Re-enable automatic research after a previous stop."""
        if self._auto_research_enabled:
            return "ℹ️  Auto-research is already running"
        self._auto_research_enabled = True
        log.info("[AUTO-RESEARCH] Enabled")
        return "✅ Auto-research started"

    def stop_auto_research(self) -> str:
        """Pause automatic research (manual ``search()`` calls still work)."""
        if not self._auto_research_enabled:
            return "ℹ️  Auto-research is already stopped"
        self._auto_research_enabled = False
        log.info("[AUTO-RESEARCH] Disabled")
        return "⏹️  Auto-research stopped"

    def auto_research_status(self) -> str:
        """Return a one-line status string."""
        state = "running ✅" if self._auto_research_enabled else "stopped ⏹️"
        backends = []
        if self._serpex_agent:
            backends.append("Serpex")
        if self._searchcode_search:
            backends.append("Searchcode")
        if self._internet:
            backends.append("Internet")
        if self._semantic_agent and self._semantic_agent.is_available():
            backends.append("SemanticStore")
        return (
            f"Auto-research: {state} | "
            f"Backends: {', '.join(backends) or 'none'} | "
            f"Ingest wait: {self._AUTO_RESEARCH_INGEST_WAIT}s"
        )

    # ─────────────────────────────────────────────
    def _compute_similarity(self, vec1, vec2):
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0
        dot = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot / (norm1 * norm2)

    # ─────────────────────────────────────────────
    def _deduplicate(self, items):
        """Order-preserving deduplication for mixed str/dict items"""
        seen = set()
        result = []

        for item in items:
            if isinstance(item, str):
                key = item
            elif isinstance(item, dict):
                try:
                    key = json.dumps(item, sort_keys=True)
                except (TypeError, ValueError):
                    key = str(item)
            else:
                key = str(item)

            if key not in seen:
                seen.add(key)
                result.append(item)

        return result

    # ─────────────────────────────────────────────
    def _update_history(self, query, results):
        timestamp = datetime.utcnow().isoformat()
        embedding = self.llm.embed(query) if self.llm and hasattr(self.llm, "embed") else None

        entry = {
            "query": query,
            "results": results,
            "timestamp": timestamp,
            "embedding": embedding
        }

        self.history.append(entry)
        self.responses.append({
            "query": query,
            "response": results,
            "timestamp": timestamp
        })

        self._track_learning_pattern(query, results)

        if len(self.history) > self.max_history:
            self.history.pop(0)

        if len(self.responses) > self.max_history:
            self.responses.pop(0)

    # ─────────────────────────────────────────────
    def _track_learning_pattern(self, query, results):
        """Track learning patterns for autonomous improvement"""
        if not results:
            return

        keywords = set(word.lower() for word in re.findall(r'\b\w{4,}\b', query))
        pattern_key = "_".join(sorted(keywords))

        if pattern_key not in self.learning_patterns:
            self.learning_patterns[pattern_key] = {
                "queries": [],
                "results_summary": [],
                "frequency": 0,
                "avg_quality": 0.0
            }

        self.learning_patterns[pattern_key]["queries"].append(query)
        self.learning_patterns[pattern_key]["results_summary"].extend(results[:2])
        self.learning_patterns[pattern_key]["frequency"] += 1

        avg_len = sum(len(str(r)) for r in results) / len(results) if results else 0
        self.learning_patterns[pattern_key]["avg_quality"] = avg_len

    # ─────────────────────────────────────────────
    def _check_history(self, query):
        """Check if similar query was answered before"""
        if not self.llm or not hasattr(self.llm, "embed"):
            return []

        try:
            query_embedding = self.llm.embed(query)
            relevant = []
            for entry in reversed(self.history):
                if entry.get("embedding"):
                    sim = self._compute_similarity(query_embedding, entry.get("embedding"))
                    if sim >= self.relevance_threshold:
                        relevant.extend(entry["results"])
            return relevant
        except Exception as e:
            log.debug(f"History check failed: {e}")
            return []

    # ─────────────────────────────────────────────
    def _feed_to_reflection(self, query, results):
        """Feed research findings to reflection module"""
        if not self.reflect:
            return

        try:
            insights = self._extract_insights(query, results)
            reflection = self.reflect.collect_and_summarize(
                f"Research Query: {query}\n\nInsights: {insights}"
            )
            log.info(f"[REFLECT] Reflection triggered: {reflection}")
        except Exception as e:
            log.debug(f"Reflection feedback skipped: {e}")

    # ─────────────────────────────────────────────
    def _feed_to_teacher(self, query, results):
        """Feed research findings to self-teacher"""
        if not self.self_teacher:
            return

        try:
            learning_content = self._synthesize_learning(query, results)
            self.self_teacher.teach(learning_content)
            log.info(f"[TEACHER] Self-teaching triggered for: {query}")
        except Exception as e:
            log.debug(f"Teacher feedback skipped: {e}")

    # ────────────────────────────────────────────��
    def _extract_insights(self, query, results):
        """Extract key insights from research results"""
        insights = []
        for result in results[:3]:
            result_str = str(result)
            sentences = re.split(r'[.!?]+', result_str)
            important = [s.strip() for s in sentences if len(s.strip()) > 20][:2]
            insights.extend(important)
        return " ".join(insights[:5])

    # ─────────────────────────────────────────────
    def _synthesize_learning(self, query, results):
        """Synthesize research into learnable content"""
        if not results:
            return query

        if self.llm and hasattr(self.llm, "generate"):
            try:
                learning_text = " ".join(str(r) for r in results[:3])
                synthesized = self.llm.generate(
                    f"Summarize the key learning point from this research for '{query}':\n{learning_text}",
                    max_tokens=200
                )
                return synthesized if synthesized else query
            except Exception:
                pass

        return " ".join(str(r) for r in results[:2])

    # ─────────────────────────────────────────────
    def _store_research_in_knowledge_db(self, query, results):
        """Store research results in knowledge database"""
        if not self.knowledge_db:
            return

        try:
            for result in results:
                self.knowledge_db.add_fact(
                    f"research:{query}",
                    result,
                    tags=["research", "web", "autonomous"]
                )

            if hasattr(self.knowledge_db, "log_event"):
                self.knowledge_db.log_event(
                    f"Research completed: {query} ({len(results)} results)"
                )

            log.info(f"[KnowledgeDB] Stored {len(results)} results for query: {query}")
        except Exception as e:
            log.debug(f"KnowledgeDB storage skipped: {e}")

    # ─────────────────────────────────────────────
    # MAIN SEARCH METHOD - FLEXIBLE PARAMETERS
    # ─────────────────────────────────────────────
    def search(self, query, max_results=5, **kwargs):
        """Enhanced search that prefers Serpex and Searchcode over raw internet scraping.

        Source priority
        ---------------
        1. History cache — previously seen results (no network cost)
        2. Serpex (niblit_agents.ResearchAgent) — validated, relevance-filtered web results
        3. Searchcode (SearchcodeSearch) — open-source code index (code-related queries)
        4. ResearcherEngine — semantic KB cache / local research engine
        5. InternetManager — direct web scrape (last-resort fallback only)

        The auto-research ingestion pipeline (reflection → KB store → teacher)
        runs after results are collected so every successful search immediately
        enriches the knowledge base.

        Args:
            query: Search query string
            max_results: Maximum results to return
            **kwargs: Optional flags
                - use_llm (bool): Use LLM synthesis (default True)
                - learn_in_background (bool): Background LLM learning (default True)
                - use_history (bool): Check history first (default True)
                - synthesize (bool): Synthesise results via LLM (default True)
                - enable_autonomous_learning (bool): Run ingestion pipeline (default True)

        Returns:
            List of search results
        """
        if not query:
            return []

        self._ensure_serpex_agent()
        use_llm = kwargs.get('use_llm', True)
        learn_in_background = kwargs.get('learn_in_background', True)
        use_history = kwargs.get('use_history', True)
        synthesize = kwargs.get('synthesize', True)
        enable_autonomous_learning = kwargs.get('enable_autonomous_learning', True)

        collected_results = []

        # Helper: extract the most meaningful text from a result dict
        def _result_text(r: Any) -> str:
            if isinstance(r, dict):
                return (
                    r.get("snippet")
                    or r.get("description")
                    or r.get("content")
                    or r.get("text")
                    or r.get("summary")
                    or str(r)
                )
            return str(r)

        # 1️⃣ HISTORY (zero network cost)
        if use_history:
            collected_results.extend(self._check_history(query))

        # 2️⃣ SERPEX — primary modern research backend
        if self._serpex_agent and hasattr(self._serpex_agent, "search_web"):
            try:
                serpex_results = self._serpex_agent.search_web(query)
                valid = [r for r in (serpex_results or [])
                         if isinstance(r, dict) and "error" not in r]
                for r in valid:
                    snippet = r.get("snippet", "") or r.get("text", "")
                    if snippet and is_relevant(query, snippet):
                        collected_results.append(snippet)
                if valid:
                    log.debug("[SEARCH] Serpex: %d relevant result(s) for %r", len(valid), query)
            except Exception as exc:
                log.debug("Serpex search failed: %s", exc)

        # 3️⃣ SEARCHCODE — code-specific open-source index
        # Run for all queries so code patterns enrich general research too.
        if self._searchcode_search and hasattr(self._searchcode_search, "search_code"):
            try:
                sc_results = self._searchcode_search.search_code(query, max_results=max_results)
                for r in (sc_results or []):
                    if isinstance(r, dict):
                        text = r.get("text", "") or r.get("snippet", "")
                        if text and len(text) > 20 and is_relevant(query, text):
                            collected_results.append(text[:500])
                if sc_results:
                    log.debug("[SEARCH] Searchcode: %d result(s) for %r", len(sc_results), query)
            except Exception as exc:
                log.debug("Searchcode search failed: %s", exc)

        # 4️⃣ ENGINE (ResearcherEngine — semantic KB cache)
        if self.engine and hasattr(self.engine, "run"):
            try:
                r = self.engine.run(query)
                if isinstance(r, dict):
                    r = r.get("summary")
                if r:
                    collected_results.append(r)
            except Exception as e:
                log.debug(f"Engine search failed: {e}")

        # 5️⃣ INTERNET — fallback only when modern backends returned nothing
        if not collected_results and self._internet and hasattr(self._internet, "search"):
            try:
                web_results = self._internet.search(query, max_results=max_results * 3)
                if web_results:
                    relevant_web = [
                        r for r in web_results
                        if is_relevant(query, _result_text(r))
                    ]
                    if not relevant_web:
                        log.warning(
                            "[REFLECT] Skipped due to low-quality data — no relevant web results for %r",
                            query,
                        )
                    collected_results.extend(relevant_web)
            except Exception as e:
                log.debug(f"Internet search failed: {e}")

        # Remove duplicates
        collected_results = self._deduplicate(collected_results)

        # 6️⃣ SYNTHESIZE
        if synthesize and collected_results and use_llm and self.llm and hasattr(self.llm, "generate"):
            try:
                combined_text = " ".join(str(item) for item in collected_results)
                synthesized = self.llm.generate(
                    f"Using these multiple sources, provide a coherent answer to: {query}\n{combined_text}",
                    max_tokens=400
                )
                if synthesized:
                    collected_results = [synthesized]
            except Exception as e:
                log.debug(f"LLM synthesis failed: {e}")

        # 7️⃣ FALLBACK
        if not collected_results:
            collected_results = [f"No data found for '{query}'"]

        # ✨ 8️⃣ AUTONOMOUS LEARNING LOOP (ingestion → reflection → KB)
        if enable_autonomous_learning and self._auto_research_enabled:
            if should_reflect(collected_results):
                self._feed_to_reflection(query, collected_results)
                self._feed_to_teacher(query, results=collected_results)
                self._store_research_in_knowledge_db(query, collected_results)
            else:
                log.warning("[REFLECT] Skipped due to low-quality data for query %r", query)

        # ✨ SEMANTIC STORAGE — persist into vector store for future semantic retrieval
        if self._semantic_agent and collected_results:
            try:
                # Convert mixed results (str/dict) to store-compatible format
                docs = []
                for r in collected_results:
                    if isinstance(r, str) and r:
                        docs.append({"snippet": r})
                    elif isinstance(r, dict):
                        docs.append(r)
                if docs:
                    self._semantic_agent.store_knowledge(docs, source="self_researcher", query=query)
            except Exception as _e:
                log.debug("[SEARCH] SemanticAgent storage failed: %s", _e)

        # 9️⃣ AUTO-LEARN (persist every result to KB)
        try:
            for r in collected_results[:max_results]:
                self.db.add_fact(f"research:{query}", r, tags=["research", "web"])
                try:
                    self.db.add_fact(f"research_response:{query}", r, tags=["research", "response"])
                except Exception:
                    pass
        except Exception as e:
            log.debug(f"Learning storage failed: {e}")

        # 🔟 UPDATE HISTORY
        self._update_history(query, collected_results[:max_results])

        # 11. BACKGROUND LEARNING
        if learn_in_background and self.llm and hasattr(self.llm, "background_learning"):
            try:
                for r in collected_results:
                    self.llm.background_learning(r)
            except Exception as e:
                log.debug(f"Background learning failed: {e}")

        return collected_results[:max_results]

    # ─────────────────────────────────────────────
    # LLM-FREE RESPONSE GENERATION (NEW)
    # ─────────────────────────────────────────────
    def answer_without_llm(self, query: str) -> str:
        """
        Generate response using knowledge base + internet
        WITHOUT LLM - for when LLM is disabled
        """
        log.info(f"🧠 [NO-LLM] Answering: {query}")

        # Step 1: Analyze intent
        intent_type, intent_meta = self.intent_analyzer.extract_intent(query)
        log.info(f"[INTENT] Type: {intent_type} | Subject: {intent_meta.get('subject')}")

        # Step 2: Generate knowledge-based response
        response = self.knowledge_responder.generate_response(query, {
            "intent_type": intent_type,
            **intent_meta
        })

        if response:
            # Store for future learning
            try:
                self.db.add_fact(f"llm_free_response:{query}", response, tags=["no_llm", "knowledge"])
                self.db.add_fact(f"intent_type:{query}", intent_type, tags=["intent", "no_llm"])
            except Exception:
                pass

            return response

        # Fallback: Simple keyword-based response
        keywords = intent_meta.get("keywords", [])
        return f"I don't have specific information about '{query}', but I can research it for you. Key topics: {', '.join(keywords)}"

    # ─────────────────────────────────────────────
    @property
    def recent_queries(self):
        return [h["query"] for h in self.history[-self.max_history:]]

    @property
    def memory_summary(self):
        return [{"query": h["query"], "timestamp": h["timestamp"]} for h in self.history]

    @property
    def stored_responses(self):
        return self.responses

    @property
    def learning_insights(self):
        return {
            "total_patterns": len(self.learning_patterns),
            "most_researched": max(self.learning_patterns.items(),
                                  key=lambda x: x[1]["frequency"],
                                  default=("None", {}))[0],
            "patterns": self.learning_patterns
        }

    # ── Fused Memory API ─────────────────────────────────────────────────────

    def log_finding(
        self,
        research_id: str,
        data: Dict[str, Any],
        embedding: Optional[List[float]] = None,
    ) -> None:
        """Persist an autonomous research finding via the fused memory backend.

        Writes the structured *data* dict to SQLite and, when *embedding* is
        provided, also upserts the vector into Qdrant/FAISS for later
        similarity-based retrieval.

        Args:
            research_id: Unique identifier for this research finding.
            data:        Arbitrary result/finding dict.
            embedding:   Optional pre-computed float embedding.
        """
        fused = getattr(self.db, "fused_memory", None)
        if fused is not None:
            try:
                fused.insert_record(research_id, data)
                if embedding:
                    fused.insert_vector(research_id, embedding, payload=data)
                return
            except Exception as exc:
                log.debug("[SelfResearcher] fused log_finding failed: %s", exc)
        # Fallback: store via existing learning-log path
        if hasattr(self.db, "store_learning"):
            self.db.store_learning({"research_id": research_id, **data})

    def get_finding(self, research_id: str) -> Dict[str, Any]:
        """Retrieve a previously stored research finding by ID.

        Args:
            research_id: Unique finding identifier.

        Returns:
            Finding dict, or empty dict when not found.
        """
        fused = getattr(self.db, "fused_memory", None)
        if fused is not None:
            try:
                rec = fused.get_record(research_id)
                if rec is not None:
                    return rec
            except Exception as exc:
                log.debug("[SelfResearcher] fused get_finding failed: %s", exc)
        return {}

    def query_past_findings(
        self,
        embedding: List[float],
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Find stored research findings similar to *embedding*.

        Queries the fused Qdrant/FAISS vector index.  Returns at most *top_k*
        results ordered by similarity.  Falls back to an empty list when the
        fused backend is unavailable.

        Args:
            embedding: Query float vector.
            top_k:     Maximum results.

        Returns:
            List of result dicts.
        """
        fused = getattr(self.db, "fused_memory", None)
        if fused is not None:
            try:
                return fused.query_vector(embedding, top_k=top_k)
            except Exception as exc:
                log.debug("[SelfResearcher] fused query_past_findings failed: %s", exc)
        return []

    # ─────────────────────────────────────────────
    # CODE RESEARCHER — feeds CodeGenerator with real data
    # ─────────────────────────────────────────────
    def research_code(self, language: str, topic: str = "best practices") -> Dict[str, Any]:
        """Research programming language information, preferring Searchcode over internet scraping.

        Source priority for code research:
        1. SearchcodeSearch.research_for_code_generation() — structured open-source index
        2. SearchcodeSearch.discover_patterns() — curated code-pattern queries
        3. Generic search() fallback (which tries Serpex → engine → internet)

        Args:
            language: programming language (e.g., "python", "bash", "javascript")
            topic: specific topic (e.g., "best practices", "design patterns", "stdlib")

        Returns:
            dict with keys: language, topic, snippets, idioms, sources
        """
        all_snippets: List[str] = []
        sources: List[str] = []

        # 1. Searchcode — structured code search (preferred for code queries)
        if self._searchcode_search:
            try:
                sc_results = self._searchcode_search.research_for_code_generation(
                    language, topic, max_results=5
                )
                for r in (sc_results or []):
                    if isinstance(r, dict):
                        text = r.get("text", "") or r.get("snippet", "")
                        if text and len(text) > 20:
                            all_snippets.append(text[:500])
                            sources.append(f"searchcode:{language}:{topic}")
                log.debug("[CODE RESEARCH] Searchcode: %d snippet(s) for %s/%s",
                          len(all_snippets), language, topic)
            except Exception as exc:
                log.debug("Searchcode code research failed: %s", exc)

        # 2. Searchcode pattern discovery (additional patterns if above returned few)
        if self._searchcode_search and len(all_snippets) < 3:
            try:
                pat_results = self._searchcode_search.discover_patterns(language, topic[:30])
                for r in (pat_results or []):
                    if isinstance(r, dict):
                        text = r.get("text", "") or r.get("snippet", "")
                        if text and len(text) > 20 and text not in all_snippets:
                            all_snippets.append(text[:500])
                            sources.append(f"searchcode_pattern:{language}")
            except Exception as exc:
                log.debug("Searchcode pattern discovery failed: %s", exc)

        # 3. Fallback: generic search (Serpex → engine → internet)
        if len(all_snippets) < 2:
            queries = [
                f"{language} {topic} code examples",
                f"{language} programming best practices",
            ]
            for q in queries[:2]:
                results = self.search(
                    q,
                    max_results=3,
                    use_llm=False,
                    learn_in_background=False,
                    use_history=True,
                    synthesize=False,
                    enable_autonomous_learning=True,
                )
                for r in results:
                    if r and isinstance(r, str) and len(r) > 20:
                        all_snippets.append(r)
                        sources.append(q)

        # Store in KB for future use
        if all_snippets and self.db:
            combined = "\n".join(all_snippets[:5])
            try:
                self.db.add_fact(
                    f"code_research:{language}:{topic}",
                    combined,
                    tags=["code", "research", language, "searchcode"]
                )
                self.db.queue_learning(f"{language} {topic} programming patterns")
            except Exception as e:
                log.debug(f"Code research store failed: {e}")

        log.info(f"[CODE RESEARCH] {language}/{topic}: found {len(all_snippets)} snippet(s)")

        return {
            "language": language,
            "topic": topic,
            "snippets": all_snippets[:5],
            "idioms": all_snippets[:3],
            "sources": list(set(sources)),
            "count": len(all_snippets),
        }

    def research_code_and_feed_generator(
        self,
        language: str,
        topic: str = "best practices",
        code_generator=None,
    ) -> str:
        """
        Research a language from the internet, then feed the result to
        CodeGenerator so it learns from real, up-to-date information.

        Returns a summary string of what was researched and stored.
        """
        research = self.research_code(language, topic)
        snippets = research.get("snippets", [])

        if not snippets:
            return f"No code research results found for {language}/{topic}"

        # Feed into CodeGenerator knowledge if available
        if code_generator and hasattr(code_generator, "_store"):
            for i, snippet in enumerate(snippets[:3]):
                code_generator._store(  # pylint: disable=protected-access
                    language, "internet_research", snippet, f"{language}_{topic}_{i}"
                )

        # Also queue for deep learning
        if self.db:
            try:
                self.db.queue_learning(f"{language} advanced programming techniques")
                self.db.queue_learning(f"{language} stdlib reference")
            except Exception:
                pass

        summary = (
            f"✅ Researched {language} {topic}: {len(snippets)} result(s) fetched.\n"
            f"First result: {snippets[0][:120] if snippets else 'none'}..."
        )
        log.info(f"[CODE RESEARCH→GENERATOR] {summary[:80]}")
        return summary


# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("Running enhanced self_researcher.py with knowledge-based responses")
