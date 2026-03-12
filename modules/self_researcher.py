#!/usr/bin/env python3
"""
ENHANCED SELF-RESEARCHER MODULE
Autonomous learning + Knowledge-based conversation without LLM
"""

from datetime import datetime
import json
import math
import html
import json
import math
import re
import logging
from typing import List, Dict, Tuple, Optional, Any

log = logging.getLogger("SelfResearcher")
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s][%(name)s][%(levelname)s] %(message)s'
)


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
        embedding = self.llm.embed(query) if self.llm else None
        
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
        if not self.llm:
            return []
        query_embedding = self.llm.embed(query)
        relevant = []
        for entry in reversed(self.history):
            sim = self._compute_similarity(query_embedding, entry.get("embedding"))
            if sim >= self.relevance_threshold:
                relevant.extend(entry["results"])
        return relevant

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

    # ─────────────────────────────────────────────
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
        
        if self.llm:
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
    # MAIN SEARCH WITH AUTONOMOUS LEARNING
    # ─────────────────────────────────────────────
    def search(self, query, max_results=5, use_llm=True, learn_in_background=True,
               use_history=True, synthesize=True, enable_autonomous_learning=True):
        """Enhanced search with autonomous learning"""
        if not query:
            return []

        collected_results = []

        # 1️⃣ HISTORY
        if use_history:
            collected_results.extend(self._check_history(query))

        # 2️⃣ ENGINE
        if self.engine:
            try:
                r = self.engine.run(query)
                if isinstance(r, dict):
                    r = r.get("summary")
                if r:
                    collected_results.append(r)
            except Exception as e:
                log.debug(f"Engine search failed: {e}")

        # 3️⃣ INTERNET
        if self._internet:
            try:
                web_results = self._internet.search(query, max_results=max_results * 3)
                if web_results:
                    collected_results.extend(web_results)
            except Exception as e:
                log.debug(f"Internet search failed: {e}")

        # Remove duplicates
        collected_results = self._deduplicate(collected_results)

        # 4️⃣ SYNTHESIZE
        if synthesize and collected_results and use_llm and self.llm:
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

        # 5️⃣ FALLBACK
        if not collected_results:
            collected_results = [f"No data found for '{query}'"]

        # ✨ 6️⃣ AUTONOMOUS LEARNING LOOP
        if enable_autonomous_learning and collected_results:
            self._feed_to_reflection(query, collected_results)
            self._feed_to_teacher(query, results=collected_results)
            self._store_research_in_knowledge_db(query, collected_results)

        # 7️⃣ AUTO-LEARN
        try:
            for r in collected_results[:max_results]:
                self.db.add_fact(f"research:{query}", r, tags=["research", "web"])
                try:
                    self.db.add_fact(f"research_response:{query}", r, tags=["research", "response"])
                except Exception:
                    pass
        except Exception as e:
            log.debug(f"Learning storage failed: {e}")

        # 8️⃣ UPDATE HISTORY
        self._update_history(query, collected_results[:max_results])

        # 9️⃣ BACKGROUND LEARNING
        if learn_in_background and self.llm:
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


# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("Running enhanced self_researcher.py with knowledge-based responses")
