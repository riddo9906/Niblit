#!/usr/bin/env python3
"""
AUTONOMOUS LEARNING ENGINE
Runs continuously in the background to autonomously improve Niblit through:
1.  Research new topics (Serpex + Searchcode + SelfResearcher — NOT raw internet scraping)
2.  Generate ideas from research (self-idea via SelfIdeaImplementation)
3.  Implement ideas (self-implement via SelfImplementer)
4.  Learn from research (learn via SelfTeacher)
5.  Reflect on findings (reflect)
6.  Auto-run SLSA for knowledge generation
7.  Run evolution step (EvolveEngine)
8.  Code Research — Searchcode + Serpex + researcher fetch real language/code data → CodeGenerator
9.  Code Generation — idea_generator+implementer produce compilable code
10. Code Compilation — CodeCompiler compiles generated code and stores results
11. Code Reflection — ReflectModule studies compiled output so Niblit understands it
12. Software Study — SoftwareStudier analyzes code patterns/functions via structured sources
13. Command Awareness — catalogue all registered commands into KB
14. Command Execution — exercise safe diagnostic commands and store observations
15. Topic Seeding — derive new research topics from KB and feed them to all subsystems
16. Reasoning — ReasoningEngine builds knowledge graph, chains, and infers new facts
17. Metacognition — Metacognition evaluates self-knowledge and identifies learning gaps
18. Improvement Cycle — ImprovementIntegrator runs full 10-module self-improvement cycle
                        (throttled: executes every 3 cycles to prevent resource contention)
19. Self Scan — BuildScanner reads own source files and stores self-knowledge in KB
20. GitHub Push — GitHubSync pushes autonomously-generated files to GitHub
21. Binary Study — BinaryStudier seeds KB with binary/hex/firmware/kernel topics
22. Builds Update — indexes the builds/ directory into KB each cycle
23. Evolve Deploy — reads evolved/improvement_*.py, stores in KB, hot-reloads via LiveUpdater
24. Brain Training — BrainTrainer fine-tunes brain on research data, KB facts, and chat history
25. Cognitive Enhancement — research language/communication/reasoning/calculating/chat completions/responses
                          and register findings live in KB and BrainTrainer each cycle
26. GitHub Code Discovery — GitHubCodeSearch: pattern discovery, training datasets, refactoring hints
27. Serpex Research — niblit_agents.ResearchAgent uses Serpex API + relevance filter to gather
                      validated web research and feed it directly into KB, BrainTrainer, and Step 2
28. Searchcode Discovery — searchcode.com REST+MCP index for open-source code patterns

Cycle Efficiency Rules
----------------------
* ONE TOPIC PER CYCLE: a single research topic is selected at the start of each cycle
  via _select_next_topic() and pinned to _current_cycle_topic.  All research steps
  (SerpexResearch, Research) use this topic so the full pipeline — research, reflect,
  understand, store — focuses on one subject before moving to the next.
* After each external research step (SerpexResearch and Research) a 30-second
  interruptible pause (_RESEARCH_INGEST_WAIT) lets the ingestion → reflection →
  KB-store pipeline complete before any new fetch starts.
* Each step is wrapped in _run_step_with_timeout; a stalled step never blocks the cycle.
* A 3-second interruptible sleep between all other steps lets the OS process I/O.
* Step 18 (ImprovementCycle) is throttled to every 3 cycles — it is the most expensive step.
* Step 20 (GitHubPush) is throttled to every 5 cycles — network push; not needed every cycle.
* stop() wakes the engine from any inter-step or ingestion sleep immediately.

Research backends (preferred order, from SelfResearcher.search())
-----------------------------------------------------------------
1. Serpex (niblit_agents.ResearchAgent) — validated, relevance-filtered web results
2. Searchcode (SearchcodeSearch) — structured open-source code index
3. ResearcherEngine — semantic KB cache
4. InternetManager — direct web scrape (last-resort fallback only)
"""

import concurrent.futures
import os
import threading
import time
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

log = logging.getLogger("AutonomousLearning")
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s][%(name)s][%(levelname)s] %(message)s'
)

# Maximum characters stored from a failed code snippet in the KB / reflection queue.
_MAX_FAILED_CODE_SNIPPET_LENGTH: int = 400
# Maximum characters per research snippet collected from KB for code generation context.
_MAX_RESEARCH_SNIPPET_LENGTH: int = 300

# Topic strings containing any of these markers are noise (embedded result payloads)
# and must not enter the research queue.
_TOPIC_NOISE_MARKERS: tuple = (
    "insights:", "findings:", "research finding:", "no data found",
    "implementation plan", "auto-research topic:", "research query:",
)
# Maximum characters for code excerpt stored in learning facts.
_MAX_LEARNING_CODE_EXCERPT: int = 150

# Lazy singleton for TopicConstructor — imported on first use to avoid
# circular import if this module is loaded before modules/ is on sys.path.
_TOPIC_CONSTRUCTOR = None


def _get_topic_constructor():
    """Return a shared TopicConstructor instance, constructing it on first call."""
    global _TOPIC_CONSTRUCTOR
    if _TOPIC_CONSTRUCTOR is None:
        try:
            from modules.topic_constructor import TopicConstructor
            _TOPIC_CONSTRUCTOR = TopicConstructor()
        except Exception:
            pass
    return _TOPIC_CONSTRUCTOR


class AutonomousLearningEngine:
    """
    Orchestrates autonomous learning across ALL Niblit modules.
    Runs in background when system is idle.
    """

    # Throttle constants — increase these numbers to reduce frequency of expensive steps.
    # ImprovementCycle (step 18) runs every N cycles (10 sub-modules; resource-intensive).
    _IMPROVEMENT_CYCLE_EVERY: int = 3
    # GitHubPush (step 20) runs every N cycles (network push; not needed every cycle).
    _GITHUB_PUSH_EVERY: int = 5
    # Additive: run self-improvement via Phase-2 agents every N cycles.
    # Override by setting autonomous_engine._SELF_IMPROVE_CYCLE_EVERY = N.
    _SELF_IMPROVE_CYCLE_EVERY: int = 10
    # Additive: minimum facts per topic before coverage is considered "adequate".
    # Topics with fewer stored facts than this are flagged as knowledge gaps.
    _MIN_COVERAGE_THRESHOLD: int = 3
    # Seconds to sleep between consecutive steps for I/O breathing room.
    _INTER_STEP_SLEEP: float = 3.0
    # Seconds to wait after the unified research step so the full ingestion →
    # reflection → KB-store pipeline has time to settle before the next query.
    # 60 s gives every backend (Serpex, Searchcode, Qdrant, SQLite) time to
    # write and index the results before the next research call begins.
    _RESEARCH_INGEST_WAIT: float = 60.0
    _CODE_TOPIC_INGEST_WAIT: float = 30.0

    def __init__(self, core, researcher=None, idea_generator=None,
                 reflect_module=None, self_teacher=None, slsa_manager=None,
                 knowledge_db=None, idle_threshold=300, poll_interval=60,
                 evolve_engine=None, self_implementer=None, idea_implementation=None,
                 code_generator=None, code_compiler=None, software_studier=None,
                 internet=None, reasoning_engine=None, metacognition=None,
                 improvement_integrator=None, github_sync=None, build_scanner=None,
                 binary_studier=None, brain_trainer=None, llm=None,
                 github_code_search=None,
                 stackoverflow_search=None, pypi_search=None,
                 searchcode_search=None,
                 serpex_research_agent=None,
                 scrapy_research_agent=None,
                 semantic_agent=None,
                 claude_engine=None,
                 builds_integrator=None,
                 step_timeout=120,
                 hybrid_manager=None,
                 self_monitor=None,
                 kernel=None):
        """
        Args:
            core: NiblitCore instance
            researcher: SelfResearcher module
            idea_generator: SelfIdeaImplementation or SelfIdeaGenerator module
            reflect_module: ReflectModule
            self_teacher: SelfTeacher module
            slsa_manager: SLSAManager for SLSA auto-run
            knowledge_db: KnowledgeDB for persistence
            idle_threshold: Time (sec) before considering system idle
            poll_interval: How often to check for idle state
            evolve_engine: EvolveEngine for self-evolution step
            self_implementer: SelfImplementer for plan execution
            idea_implementation: SelfIdeaImplementation for idea generation + implementation
            code_generator: CodeGenerator — generates compilable code from internet data
            code_compiler: CodeCompiler — compiles and executes generated code
            software_studier: SoftwareStudier — analyzes software patterns via internet
            internet: InternetManager — primary data collection channel (required for code research)
            reasoning_engine: ReasoningEngine — builds knowledge graphs and reasoning chains
            metacognition: Metacognition — evaluates self-knowledge and identifies learning gaps
            improvement_integrator: ImprovementIntegrator — runs full 10-module improvement cycle
            github_sync: GitHubSync — pushes self-updates to GitHub
            build_scanner: BuildScanner — scans own source files for self-knowledge
            binary_studier: BinaryStudier — autonomous binary/hex/dex/firmware/kernel study
            brain_trainer: BrainTrainer — fine-tunes brain on research data and learned material
            llm:          LLM adapter (e.g. HFLLMAdapter) — used to synthesise real code from research
            github_code_search: GitHubCodeSearch — code pattern discovery, training datasets, refactoring
            stackoverflow_search: StackOverflowSearch — bug solutions and code-pattern lookup via SO API
            pypi_search: PyPISearch — PyPI package intelligence for dependency graphs and new libraries
            searchcode_search: SearchcodeSearch — open-source code-search via searchcode.com REST API
                               and/or its MCP endpoint (https://api.searchcode.com/v1/mcp)
            serpex_research_agent: niblit_agents.ResearchAgent — Serpex-backed web search with
                                   relevance filtering (is_relevant) and automatic KnowledgeStore
                                   + Qdrant persistence (step 27).  Falls back to lazy construction
                                   from SERPEX_API_KEY env var when None.
            scrapy_research_agent: niblit_agents.ScrapyResearchAgent — direct Scrapy/DuckDuckGo
                                   research backend (no SerpexAPI shim, no API key required).
                                   Runs as a dedicated ALE step (ScrapyResearch) each cycle.
            semantic_agent: niblit_agents.SemanticAgent — vector-store backed knowledge storage
                            and retrieval.  When provided, every research step embeds its results
                            into the vector store for semantic retrieval.
            claude_engine: niblit_models.ClaudeEngine — Anthropic Claude with context injection.
                           When available, used to generate richer summaries from research data.
            builds_integrator: BuildsIntegrator — unified wrapper around the builds/python scripts.
                               Provides NLP processing, binary inspection, JSONL data-structure
                               handling, and chat-session management.  Used by steps 21, 22, 23
                               and the new step 29 (BuildsIntegration).
            step_timeout: Maximum seconds a single ALE step may run before being skipped (default 120)
        """
        self.core = core
        self.researcher = researcher
        self.idea_generator = idea_generator
        self.reflect = reflect_module
        self.self_teacher = self_teacher
        self.slsa_manager = slsa_manager
        self.knowledge_db = knowledge_db
        self.evolve_engine = evolve_engine
        self.self_implementer = self_implementer
        self.idea_implementation = idea_implementation
        self.code_generator = code_generator
        self.code_compiler = code_compiler
        self.software_studier = software_studier
        self.internet = internet
        self.reasoning_engine = reasoning_engine
        self.metacognition = metacognition
        self.improvement_integrator = improvement_integrator
        self.github_sync = github_sync
        self.build_scanner = build_scanner
        self.binary_studier = binary_studier
        self.brain_trainer = brain_trainer
        self.llm = llm
        self.github_code_search = github_code_search
        self.stackoverflow_search = stackoverflow_search
        self.pypi_search = pypi_search
        self.searchcode_search = searchcode_search
        self.serpex_research_agent = serpex_research_agent
        self.scrapy_research_agent = scrapy_research_agent
        self.semantic_agent = semantic_agent
        self.claude_engine = claude_engine
        self.builds_integrator = builds_integrator
        self.step_timeout = step_timeout
        self.hybrid_manager = hybrid_manager
        self.self_monitor = self_monitor
        self.kernel = kernel

        self.idle_threshold = idle_threshold
        self.poll_interval = poll_interval

        self.running = False
        self.last_user_interaction = datetime.utcnow()
        self.learning_thread = None
        # Event used to wake up the inter-cycle sleep early (e.g. on stop())
        self._stop_event = threading.Event()

        # Topics to autonomously research (grows over time)
        self.research_topics = [
            # ── TOP PRIORITY: code structure & quality ──────────────────────
            "code indentation and structure best practices",
            "proper code formatting standards for all languages",
            "code syntax correctness and linting",
            # ── cognitive / language / communication ─────────────────────────
            "natural language understanding and generation",
            "language model prompt engineering and chat completions",
            "conversational AI response quality and fluency",
            "human communication styles and pragmatics",
            "language grammar syntax and semantics",
            "multilingual language translation techniques",
            "dialogue management and context tracking",
            "question answering and information retrieval",
            "text summarization and generation best practices",
            "sentiment analysis and tone detection",
            # ── reasoning / logic / mathematics ──────────────────────────────
            "logical reasoning and deductive inference",
            "mathematical reasoning and arithmetic problem solving",
            "symbolic AI planning and constraint solving",
            "common-sense reasoning and world knowledge",
            "causal reasoning and counterfactual thinking",
            "chain-of-thought prompting and multi-step reasoning",
            "numerical computation and floating point arithmetic",
            "algebra calculus and statistical mathematics",
            "probabilistic reasoning and Bayesian inference",
            "formal verification and theorem proving",
            # ── chat completions / response quality ──────────────────────────
            "chat completion API design and usage patterns",
            "LLM response formatting and structured output",
            "context window management and long conversation handling",
            "retrieval-augmented generation and knowledge grounding",
            "response coherence consistency and factual accuracy",
            "instruction following and alignment techniques",
            # ── low-level / systems ─────────────────────────────────────────
            "binary file formats ELF DEX PE Mach-O",
            "hexadecimal binary number systems and conversions",
            "assembly language x86-64 and ARM programming",
            "Linux kernel module development",
            "firmware and embedded systems programming",
            "BIOS UEFI bootloader development",
            "Android internals DEX smali ART",
            "networking TCP IP sockets protocols",
            "operating system internals process memory scheduling",
            "kernel driver development char block network devices",
            "binary exploitation and reverse engineering fundamentals",
            "cross-compilation toolchains and build systems",
            # ── general AI/ML topics ────────────────────────────────────────
            "artificial intelligence advances",
            "machine learning techniques",
            "data science trends",
            "automation systems",
            "neural networks",
            "natural language processing",
            "computer vision",
            "knowledge graphs",
            "reasoning systems",
            "multi-agent systems",
            "system optimization",
            "performance tuning",
            "error handling best practices",
            "code quality metrics",
            "software architecture patterns",
        ]

        # Code-literacy research topics (used by _autonomous_code_research)
        self.code_research_topics = [
            # ── TOP PRIORITY: structure/indentation ─────────────────────────
            ("python", "code structure and indentation"),
            ("bash", "proper script structure and indentation"),
            ("javascript", "code structure and formatting"),
            # ── cognitive / language / NLP ───────────────────────────────────
            ("python", "natural language processing with NLTK and spaCy"),
            ("python", "text generation with transformers and language models"),
            ("python", "chat completion API client implementations"),
            ("python", "conversation history management and context windows"),
            ("python", "tokenization stemming and lemmatization"),
            ("python", "reasoning chains and multi-step problem solving"),
            ("python", "arithmetic and mathematical expression evaluation"),
            ("python", "string formatting and template rendering"),
            ("javascript", "chat UI components and streaming responses"),
            ("typescript", "LLM API integration and response handling"),
            # ── compiled / systems languages ─────────────────────────────────
            ("java", "object-oriented design patterns"),
            ("java", "Android development best practices"),
            ("c", "memory management and pointers"),
            ("c", "system calls and POSIX API"),
            ("cpp", "RAII and smart pointers"),
            ("cpp", "template metaprogramming"),
            ("rust", "ownership and borrowing"),
            ("rust", "async programming and tokio"),
            ("go", "goroutines and channels"),
            ("go", "error handling patterns"),
            ("kotlin", "coroutines and Android development"),
            ("typescript", "type system and generics"),
            ("assembly", "x86-64 system call interface"),
            ("assembly", "ARM Cortex-M bare metal programming"),
            # ── networking & systems ──────────────────────────────────────────
            ("python", "socket programming and networking"),
            ("c", "Linux socket and epoll networking"),
            ("bash", "network diagnostic scripting"),
            # ── binary / low-level ───────────────────────────────────────────
            ("python", "binary file parsing with struct"),
            ("python", "ELF and DEX format analysis"),
            ("c", "kernel module and device driver programming"),
            ("c", "firmware bare-metal embedded programming"),
            # ── existing topics ─────────────────────────────────────────────
            ("python", "data structures"),
            ("python", "algorithms"),
            ("python", "design patterns"),
            ("python", "async programming"),
            ("python", "error handling"),
            ("javascript", "async patterns"),
            ("javascript", "functional programming"),
            ("bash", "scripting best practices"),
        ]

        # Software study categories (rotated each idle cycle)
        self.software_study_categories = [
            # ── systems & low-level ─────────────────────────────────────────
            "binary_analysis",
            "kernel_development",
            "firmware_embedded",
            "bios_uefi",
            "android_internals",
            "networking_protocols",
            "operating_systems",
            "assembly_programming",
            # ── high-level / general ────────────────────────────────────────
            "ai_ml_systems",
            "web_applications",
            "databases",
            "security",
            "distributed_systems",
            "cloud_native",
            "cross_platform_development",
            "reverse_engineering",
        ]

        # Ideas generated (to implement)
        self.pending_ideas = []

        # Raw research results from the last _autonomous_research call, forwarded to Step 4
        self._last_research_results: List[Any] = []

        # Recently compiled code snippets waiting for reflection
        self._pending_compiled: List[Dict[str, Any]] = []

        # Compiled code records queued for the reflect step (populated by _autonomous_code_compilation)
        self._compiled_for_reflection: List[Dict[str, Any]] = []

        # Learning history
        self.learning_history = {
            "research_completed": 0,
            "ideas_generated": 0,
            "ideas_implemented": 0,
            "reflections_conducted": 0,
            "slsa_runs": 0,
            "evolve_steps": 0,
            "code_researched": 0,
            "code_generated": 0,
            "code_compiled": 0,
            "code_reflected": 0,
            "software_studied": 0,
            "command_awareness_cycles": 0,
            "command_executions": 0,
            "self_learn_sequences": 0,
            "evolve_sequences": 0,
            "topic_seedings": 0,
            "reasoning_cycles": 0,
            "metacognition_cycles": 0,
            "improvement_cycles": 0,
            "self_scan_cycles": 0,
            "github_push_cycles": 0,
            "binary_study_cycles": 0,
            "builds_update_cycles": 0,
            "evolve_deploy_cycles": 0,
            "builds_integration_cycles": 0,
            "brain_training_cycles": 0,
            "cognitive_enhancement_cycles": 0,
            "serpex_research_cycles": 0,
            "scrapy_research_cycles": 0,
            "last_research_topic": None,
            "last_serpex_query": None,
            "last_idea": None,
            "last_language_studied": None,
            "last_software_category": None,
            "last_commands_studied": None,
            "last_seeded_topics": None,
            "last_reasoning_inferences": 0,
            "last_metacognition_confidence": None,
            "learning_rate": 0.0,
            "start_time": datetime.utcnow().isoformat()
        }

        # Internal cycle counter used for step throttling (e.g. ImprovementCycle).
        self._cycle_count: int = 0

        # Topic rotation: every cycle dedicates itself to ONE topic so all steps
        # research, reflect, and store knowledge about the same subject before
        # moving on.  _topic_index advances by 1 at the start of each cycle.
        self._topic_index: int = 0
        self._current_cycle_topic: Optional[str] = None

        # Code-step topic lock: all code steps 8-12 share one topic per cycle
        self._code_topic_index: int = 0
        self._current_code_topic: Optional[str] = None

        log.info("✅ AutonomousLearningEngine initialized")

    # ─────────────────────────────────────────────
    def is_idle(self) -> bool:
        """Check if system is idle (no recent user interaction)"""
        time_since_interaction = (datetime.utcnow() - self.last_user_interaction).total_seconds()
        is_idle = time_since_interaction > self.idle_threshold
        if is_idle:
            log.debug(f"[IDLE] System idle for {time_since_interaction:.0f}s (threshold: {self.idle_threshold}s)")
        return is_idle

    # ─────────────────────────────────────────────
    def update_last_interaction(self):
        """Called when user interacts with system"""
        self.last_user_interaction = datetime.utcnow()
        if self.running:
            log.debug("[INTERACTION] User activity detected - resetting idle timer")

    # ─────────────────────────────────────────────
    def _select_next_topic(self) -> str:
        """Select the next research topic for this cycle.

        Priority order:
        1. Topics with detected knowledge gaps (fewer than _MIN_COVERAGE_THRESHOLD
           facts in the KB) — these are studied first so Niblit fills holes in its
           own knowledge before cycling through well-covered topics again.
        2. Sequential round-robin across all research_topics (original behaviour).

        Using gap-first selection ensures the autonomous loop converges on a
        complete KB rather than endlessly re-researching well-known subjects.
        """
        if not self.research_topics:
            return "autonomous learning"

        # Check for gap topics (quick scan, non-blocking)
        try:
            gaps = self.detect_knowledge_gaps(max_gaps=3)
            if gaps:
                # Pick the first gap that is actually in our topic list; fall
                # through to round-robin if none match.
                for gap in gaps:
                    if gap in self.research_topics:
                        log.info("[ALE] Gap-driven topic selected: %r", gap)
                        tc = _get_topic_constructor()
                        return tc.build(gap) if tc else gap
        except Exception:
            pass

        # Fallback: sequential rotation
        idx = self._topic_index % len(self.research_topics)
        raw = self.research_topics[idx]
        self._topic_index = (idx + 1) % len(self.research_topics)
        tc = _get_topic_constructor()
        return tc.build(raw) if tc else raw

    def _select_next_code_topic(self) -> Tuple[str, str]:
        """Rotate through code_research_topics sequentially (one per cycle)."""
        if not self.code_research_topics:
            return ("python", "best practices")
        topic = self.code_research_topics[self._code_topic_index % len(self.code_research_topics)]
        self._code_topic_index += 1
        return topic

    # ─────────────────────────────────────────────
    def _autonomous_research(self) -> str:
        """Step 1: Autonomously research the current cycle topic.

        Uses the topic selected at the start of this cycle (_current_cycle_topic)
        so all downstream steps in the same cycle work on the same subject.
        Falls back to the Serpex ResearchAgent when SelfResearcher is absent
        or returns empty results.  Results are forwarded to Step 4 (reflection)
        and also used by Steps 2-6 in the current cycle.
        """
        if not self.researcher and not self._get_serpex_agent():
            return "[Researcher unavailable]"

        try:
            # Use the topic pinned for this cycle (set in _run_autonomous_cycle)
            topic = self._current_cycle_topic or self._select_next_topic()

            log.info(f"🔍 [AUTONOMOUS RESEARCH] Starting: {topic}")

            results = []

            # Primary: SelfResearcher (semantic search + KB cache + internet)
            if self.researcher:
                try:
                    results = self.researcher.search(
                        topic,
                        max_results=5,
                        use_history=True,
                        synthesize=True,
                        enable_autonomous_learning=True
                    )
                    try:
                        results = list(results) if results else []
                    except TypeError:
                        results = [results] if results else []
                except Exception as exc:
                    log.debug("[RESEARCH] SelfResearcher failed: %s", exc)

            # Fallback / enrichment: Serpex ResearchAgent (relevance-filtered)
            if not results:
                agent = self._get_serpex_agent()
                if agent:
                    try:
                        serpex_results = agent.search_web(topic)
                        for r in (serpex_results or []):
                            if isinstance(r, dict) and "error" not in r:
                                snippet = r.get("snippet", "")
                                if snippet:
                                    results.append(snippet)
                    except Exception as exc:
                        log.debug("[RESEARCH] Serpex fallback failed: %s", exc)

            self.learning_history["research_completed"] += 1
            self.learning_history["last_research_topic"] = topic

            # Forward raw results to Step 4 (reflection) so it has full content.
            self._last_research_results = results

            # Log to knowledge base
            if self.knowledge_db:
                try:
                    self.knowledge_db.log_event(
                        f"Autonomous research completed: {topic} ({len(results)} results)"
                    )
                    # Store structured acquired data fact with clean text only
                    def _rtext(r):
                        if isinstance(r, dict):
                            return (r.get("snippet") or r.get("text") or r.get("description")
                                    or r.get("content") or r.get("summary") or str(r))
                        return str(r)
                    all_text = "\n---\n".join(_rtext(r)[:400] for r in results[:5])
                    self.knowledge_db.add_fact(
                        f"ale_research:{topic.replace(' ', '_')}:{int(time.time())}",
                        {
                            "topic": topic,
                            "results_count": len(results),
                            "summary": _rtext(results[0])[:300] if results else "no results",
                            "full_text": all_text[:800],
                            "step": "step1_research",
                        },
                        tags=["ale_step1", "research", "autonomous", topic.split()[0].lower()],
                    )
                except Exception as e:
                    log.debug(f"Knowledge DB logging failed: {e}")

            log.info(f"✅ [AUTONOMOUS RESEARCH] Completed: {topic} ({len(results)} results)")

            # ── Semantic storage ─────────────────────────────────────────────
            sa = self._get_semantic_agent()
            if sa and results:
                try:
                    docs = [
                        {"snippet": str(r)[:600]} if not isinstance(r, dict) else r
                        for r in results
                        if r
                    ]
                    sa.store_knowledge(docs, source="ale_research", query=topic)
                except Exception as _se:
                    log.debug("[RESEARCH] SemanticAgent store failed: %s", _se)

            # ── HybridQdrantManager upsert (additive) ────────────────────────────────
            if self.hybrid_manager and results:
                try:
                    result = results[0] if results else None
                    rtext = (result.get("snippet") or result.get("text") or result.get("description")
                             or result.get("content") or result.get("summary") or str(result)) if isinstance(result, dict) else str(result)
                    self.hybrid_manager.upsert(
                        rtext[:2000],
                        {"type": "research", "topic": self._current_cycle_topic, "cycle": self._cycle_count},
                        collection="niblit_research"
                    )
                except Exception as _hq_e:
                    log.debug("[ALE] hybrid_manager upsert failed: %s", _hq_e)
            if self.self_monitor:
                try:
                    self.self_monitor.log_event("LEARNING", f"Research: {self._current_cycle_topic}", outcome="success")
                except Exception:
                    pass

            return f"Researched: {topic}"

        except Exception as e:
            log.error(f"❌ Autonomous research failed: {e}")
            return f"[Research error: {e}]"

    # ─────────────────────────────────────────────
    def _autonomous_idea_generation(self) -> str:
        """Step 2: Generate ideas based on research using SelfIdeaImplementation when available."""
        topic = self.learning_history.get("last_research_topic") or "system improvement"
        prompt = f"Generate an innovative idea based on research about: {topic}"

        log.info(f"💡 [AUTONOMOUS IDEAS] Generating idea: {prompt[:60]}")

        # Prefer SelfIdeaImplementation (richer: research + implement + SLSA + memory)
        if self.idea_implementation and hasattr(self.idea_implementation, "implement_idea"):
            try:
                result = self.idea_implementation.implement_idea(prompt)
                idea_text = str(result)[:200] if result else None
                if idea_text:
                    self.pending_ideas.append(idea_text)
                    self.learning_history["ideas_generated"] += 1
                    self.learning_history["last_idea"] = idea_text[:100]
                    if self.knowledge_db:
                        try:
                            self.knowledge_db.log_event(f"Autonomous idea (SelfIdeaImpl): {idea_text[:50]}")
                            self.knowledge_db.add_fact(
                                f"ale_idea:{int(time.time())}",
                                {"topic": topic, "idea": idea_text[:300], "generator": "SelfIdeaImpl",
                                 "step": "step2_ideas"},
                                tags=["ale_step2", "ideas", "autonomous"],
                            )
                        except Exception as _db_e:
                            log.debug(f"Knowledge DB log_event failed: {_db_e}")
                    log.info(f"✅ [AUTONOMOUS IDEAS] SelfIdeaImpl generated: {idea_text[:50]}")
                    return f"Idea generated (SelfIdeaImpl): {idea_text[:100]}"
            except Exception as e:
                log.debug(f"SelfIdeaImplementation idea failed: {e}")

        # Fallback: legacy idea_generator (SelfIdeaGenerator or similar)
        if self.idea_generator:
            try:
                idea = None
                if hasattr(self.idea_generator, "generate_plan"):
                    idea = self.idea_generator.generate_plan(prompt)
                elif hasattr(self.idea_generator, "generate_idea"):
                    idea = self.idea_generator.generate_idea(prompt)
                elif hasattr(self.idea_generator, "generate_ideas"):
                    ideas = self.idea_generator.generate_ideas(prompt, count=1)
                    idea = ideas[0] if ideas else None

                if idea:
                    idea_str = str(idea)[:200]
                    self.pending_ideas.append(idea_str)
                    self.learning_history["ideas_generated"] += 1
                    self.learning_history["last_idea"] = idea_str[:100]
                    if self.knowledge_db:
                        try:
                            self.knowledge_db.log_event(f"Autonomous idea generated: {idea_str[:50]}")
                            self.knowledge_db.add_fact(
                                f"ale_idea:{int(time.time())}",
                                {"topic": topic, "idea": idea_str[:300], "generator": "legacy",
                                 "step": "step2_ideas"},
                                tags=["ale_step2", "ideas", "autonomous"],
                            )
                        except Exception:
                            pass
                    log.info(f"✅ [AUTONOMOUS IDEAS] Generated: {idea_str[:50]}")
                    return f"Idea generated: {idea_str[:100]}"
            except Exception as e:
                log.error(f"❌ Autonomous idea generation failed: {e}")
                return f"[Idea generation error: {e}]"

        return "[Idea generator unavailable]"

    # ─────────────────────────────────────────────
    def _autonomous_implementation(self) -> str:
        """Step 3: Implement pending ideas using SelfImplementer when available."""
        if not self.pending_ideas:
            return "[No ideas to implement]"

        idea = self.pending_ideas.pop(0)
        idea_str = str(idea)

        log.info(f"🚀 [AUTONOMOUS IMPLEMENT] Implementing: {idea_str[:50]}...")

        # Prefer SelfImplementer.enqueue_plan (runs plans in background thread)
        if self.self_implementer and hasattr(self.self_implementer, "enqueue_plan"):
            try:
                self.self_implementer.enqueue_plan(idea_str)
                self.learning_history["ideas_implemented"] += 1
                if self.knowledge_db:
                    try:
                        self.knowledge_db.log_event(f"Autonomous implement queued: {idea_str[:50]}")
                        self.knowledge_db.add_fact(
                            f"ale_implementation:{int(time.time())}",
                            {"idea": idea_str[:300], "method": "SelfImplementer.enqueue_plan",
                             "step": "step3_implementation"},
                            tags=["ale_step3", "implementation", "autonomous"],
                        )
                    except Exception:
                        pass
                log.info(f"✅ [AUTONOMOUS IMPLEMENT] Enqueued to SelfImplementer")
                return f"Idea enqueued to SelfImplementer: {idea_str[:50]}"
            except Exception as e:
                log.debug(f"SelfImplementer enqueue failed: {e}")

        # Fallback: legacy idea_generator
        if self.idea_generator:
            try:
                plan = None
                if hasattr(self.idea_generator, "implement_idea"):
                    plan = self.idea_generator.implement_idea(idea_str)
                elif hasattr(self.idea_generator, "generate_plan"):
                    plan = self.idea_generator.generate_plan(idea_str)

                if plan:
                    self.learning_history["ideas_implemented"] += 1
                    if self.knowledge_db:
                        try:
                            self.knowledge_db.log_event(f"Autonomous implementation: {idea_str[:50]}")
                            self.knowledge_db.add_fact(
                                f"ale_implementation:{int(time.time())}",
                                {"idea": idea_str[:300], "plan": str(plan)[:200],
                                 "method": "legacy", "step": "step3_implementation"},
                                tags=["ale_step3", "implementation", "autonomous"],
                            )
                        except Exception:
                            pass
                    log.info(f"✅ [AUTONOMOUS IMPLEMENT] Executed")
                    return f"Idea implemented: {idea_str[:50]}"
            except Exception as e:
                log.error(f"❌ Autonomous implementation failed: {e}")
                return f"[Implementation error: {e}]"

        return "[No implementation module available]"

    # ─────────────────────────────────────────────
    def _autonomous_reflection(self) -> str:
        """Step 4: Reflect on the actual research content and store as memory."""
        if not self.reflect:
            return "[Reflect module unavailable]"

        try:
            last_topic = self.learning_history.get("last_research_topic") or "system learning"
            last_idea = self.learning_history.get("last_idea") or "system improvement"

            # Primary source: raw results forwarded directly from Step 1 this cycle.
            # These contain the full text returned by the researcher, not a truncated summary.
            raw_content = ""
            if self._last_research_results:
                raw_content = "\n---\n".join(
                    str(r)[:400] for r in self._last_research_results[:5]
                )

            # Fallback: pull from KB when raw results aren't available (e.g. engine restarted)
            if not raw_content and self.knowledge_db:
                try:
                    # list_facts() returns newest-first; first match is most recent.
                    facts = (
                        self.knowledge_db.list_facts(20)
                        if hasattr(self.knowledge_db, "list_facts") else []
                    )
                    for f in (facts or []):
                        if isinstance(f, dict):
                            key = str(f.get("key", ""))
                            if "ale_research:" in key or "ale_internet_code:" in key:
                                val = f.get("value", {})
                                if isinstance(val, dict):
                                    # Prefer full_text when available, else summary
                                    raw_content = (
                                        str(val.get("full_text") or val.get("summary", ""))[:600]
                                    )
                                else:
                                    raw_content = str(val)[:600]
                                if raw_content:
                                    break
                except Exception:
                    pass

            # Build a content-rich reflection prompt so the module has real data to work with
            reflection_text = (
                f"Research topic: {last_topic}\n\n"
                f"Research findings:\n{raw_content or '(no findings available)'}\n\n"
                f"Generated idea: {last_idea}\n\n"
                f"Research count: {self.learning_history['research_completed']} | "
                f"Implementations: {self.learning_history['ideas_implemented']} | "
                f"Reflections: {self.learning_history['reflections_conducted']}"
            )

            log.info(f"🧠 [AUTONOMOUS REFLECT] Reflecting on '{last_topic}'...")

            # Use reflect_on_research(topic, findings, idea) when available so
            # only the clean topic string is forwarded to self_teacher, not the
            # full compound "Research topic: ...\n\nFindings: ..." blob.
            research_text = raw_content[:500] if raw_content else "(no research findings)"
            if hasattr(self.reflect, "reflect_on_research"):
                result = self.reflect.reflect_on_research(last_topic, research_text, last_idea or "")
            else:
                result = self.reflect.collect_and_summarize(last_topic)

            self.learning_history["reflections_conducted"] += 1

            # Build a condensed, recallable research+reflection record
            reflection_output = str(result or "")[:400]

            # Persist to knowledge base
            if self.knowledge_db:
                try:
                    ts = int(time.time())
                    self.knowledge_db.log_event(
                        f"Autonomous reflection completed: '{last_topic}'"
                    )
                    # Detailed reflection record (step-tagged for ALE tracing)
                    self.knowledge_db.add_fact(
                        f"ale_reflection:{ts}",
                        {
                            "topic": last_topic,
                            "idea": last_idea,
                            "research": research_text,
                            "reflection": reflection_output,
                            "step": "step4_reflection",
                        },
                        tags=["ale_step4", "reflection", "autonomous"],
                    )
                    # ale_learned — the consolidated memory entry that 'recall' queries return.
                    # This is the primary long-term storage for each research cycle.
                    # Use millisecond timestamp to avoid key collisions within the same second.
                    topic_tag = last_topic.split()[0].lower() if last_topic.split() else "general"
                    self.knowledge_db.add_fact(
                        f"ale_learned:{last_topic.replace(' ', '_')}:{ts}",
                        {
                            "topic": last_topic,
                            "research": research_text,
                            "reflection": reflection_output,
                            "idea": last_idea,
                            "source": "ale_step4_reflection",
                        },
                        tags=["ale_learned", "memory", "autonomous", topic_tag],
                    )
                    # Update the per-topic learning ledger — single authoritative
                    # entry per topic kept current across every research cycle.
                    # Uses a plain-text value so _get_kb_response can display it
                    # directly without needing to unpack a nested dict.
                    ledger_text = (
                        f"{reflection_output or research_text[:300]}"
                    ).strip()
                    if ledger_text:
                        self.knowledge_db.add_fact(
                            f"topic_knowledge:{last_topic}",
                            ledger_text,
                            tags=["knowledge", "ledger", "autonomous", topic_tag],
                        )
                except Exception as e:
                    log.debug(f"Knowledge DB logging failed: {e}")

            # Clear forwarded results now that they've been reflected on
            self._last_research_results = []

            log.info(f"✅ [AUTONOMOUS REFLECT] '{last_topic}' — stored in ale_learned")

            # ── Additive: self-completing gap detection ───────────────────────
            # After every reflection cycle, check for under-covered topics and
            # submit research tasks to fill them autonomously (non-blocking).
            try:
                self.submit_agent_tasks_for_gaps()
            except Exception as _gap_exc:
                log.debug("[ALE] Gap detection post-reflection error: %s", _gap_exc)

            # ── HybridQdrantManager upsert (additive) ────────────────────────────────
            if self.hybrid_manager and result:
                try:
                    self.hybrid_manager.upsert(
                        str(result)[:2000],
                        {"type": "reflection", "cycle": self._cycle_count},
                        collection="niblit_reflections"
                    )
                except Exception as _hq_e:
                    log.debug("[ALE] hybrid_manager reflect upsert failed: %s", _hq_e)

            return str(result) if result is not None else "[No reflection result]"

        except Exception as e:
            log.error(f"❌ Autonomous reflection failed: {e}")
            return f"[Reflection error: {e}]"

    # ─────────────────────────────────────────────
    def _autonomous_slsa_run(self) -> str:
        """Step 5: Run SLSA engine to generate knowledge artifacts"""
        if not self.slsa_manager:
            return "[SLSA manager unavailable]"

        try:
            # Check if SLSA is already running
            status = self.slsa_manager.status()
            if "running" in status.lower():
                log.info("ℹ️  [AUTONOMOUS SLSA] SLSA already running, skipping...")
                return "SLSA already running"

            # Pick random topics for SLSA
            topics = random.sample(self.research_topics, min(3, len(self.research_topics)))

            log.info(f"🔄 [AUTONOMOUS SLSA] Starting with topics: {topics}")

            self.slsa_manager.start(topics)

            self.learning_history["slsa_runs"] += 1

            # Log to knowledge base
            if self.knowledge_db:
                try:
                    self.knowledge_db.log_event(f"Autonomous SLSA started with topics: {topics}")
                    self.knowledge_db.add_fact(
                        f"ale_slsa:{int(time.time())}",
                        {"topics": topics, "step": "step5_slsa"},
                        tags=["ale_step5", "slsa", "autonomous"],
                    )
                except Exception as e:
                    log.debug(f"Knowledge DB logging failed: {e}")

            log.info(f"✅ [AUTONOMOUS SLSA] Started")
            return "SLSA engine started autonomously"

        except Exception as e:
            log.error(f"❌ Autonomous SLSA run failed: {e}")
            return f"[SLSA error: {e}]"

    # ─────────────────────────────────────────────
    def _autonomous_learning(self) -> str:
        """Step 6: Feed learning to self-teacher with spaced review and richer logging"""
        if not self.self_teacher:
            return "[Self-teacher unavailable]"

        try:
            outputs = []

            # 1. Teach the most recent research topic as before
            last_topic = self.learning_history.get("last_research_topic") or "system knowledge"
            log.info(f"📚 [AUTONOMOUS LEARN] Teaching about: {last_topic}")
            result = self.self_teacher.teach(last_topic)
            outputs.append(result)

            # 2. Teach or review an older topic (spaced repetition)
            reviews = self.self_teacher.spaced_review(count=1)
            outputs.extend(reviews)

            # 3. Log BOTH results to knowledge base (as before, but now richer)
            if self.knowledge_db:
                try:
                    # Log main teaching on new topic
                    self.knowledge_db.log_event(f"Autonomous teaching: {last_topic} + {len(reviews)} reviewed")
                    self.knowledge_db.add_fact(
                        f"ale_learning:{last_topic.replace(' ', '_')}:{int(time.time())}",
                        {
                            "topic": last_topic,
                            "result": str(result or "")[:300],
                            "step": "step6_learning",
                            "spaced_reviewed": [str(r)[:150] for r in reviews],
                        },
                        tags=["ale_step6", "learning", "autonomous"],
                    )
                except Exception as e:
                    log.debug(f"Knowledge DB logging failed: {e}")

            # Spaced repetition reviews
            review_count = 0
            try:
                due_topics = self.self_teacher.get_due_reviews(max_items=2)
                for due_topic in due_topics:
                    review_result = self.self_teacher.teach_review(due_topic)
                    review_count += 1
                    log.info(f"🔁 [AUTONOMOUS LEARN] Review: {str(review_result or '')[:80]}")
                    if self.knowledge_db:
                        try:
                            self.knowledge_db.add_fact(
                                f"ale_review:{due_topic.replace(' ', '_')}:{int(time.time())}",
                                {"topic": due_topic, "result": str(review_result or "")[:300],
                                 "step": "step6_review"},
                                tags=["ale_step6", "review", "autonomous"],
                            )
                        except Exception as e:
                            log.debug(f"Knowledge DB review logging failed: {e}")
            except Exception as e:
                log.debug(f"Spaced repetition review failed: {e}")

            if self.knowledge_db and review_count:
                try:
                    self.knowledge_db.add_fact(
                        f"ale_review_count:{int(time.time())}",
                        {"review_count": review_count},
                        tags=["ale_step6", "review-count", "autonomous"],
                    )
                except Exception as e:
                    log.debug(f"Knowledge DB review count logging failed: {e}")

            log.info(f"✅ [AUTONOMOUS LEARN] {str(result or '')[:50]} | reviews={review_count}")
            return str(result) if result is not None else "[No learning result]"

        except Exception as e:
            log.error(f"❌ Autonomous learning failed: {e}")
            return f"[Learning error: {e}]"

    # ─────────────────────────────────────────────
    # PROGRAMMING LITERACY LOOP (steps 8-12)
    # Uses internet as the primary data-collection channel.
    # ─────────────────────────────────────────────

    def _get_internet(self):
        """Return internet manager — pull from core lazily if not set at init."""
        if not self.internet and self.core:
            self.internet = getattr(self.core, "internet", None)
        return self.internet

    def _get_code_generator(self):
        """Lazily resolve CodeGenerator from core."""
        if not self.code_generator and self.core:
            self.code_generator = getattr(self.core, "code_generator", None)
        return self.code_generator

    def _get_code_compiler(self):
        """Lazily resolve CodeCompiler from core."""
        if not self.code_compiler and self.core:
            self.code_compiler = getattr(self.core, "code_compiler", None)
        return self.code_compiler

    def _get_llm(self):
        """Lazily resolve LLM adapter from core."""
        if not self.llm and self.core:
            self.llm = getattr(self.core, "llm", None)
        return self.llm

    def _get_github_code_search(self):
        """Lazily resolve GitHubCodeSearch from core."""
        if not self.github_code_search and self.core:
            self.github_code_search = getattr(self.core, "github_code_search", None)
        return self.github_code_search

    def _get_stackoverflow_search(self):
        """Lazily resolve StackOverflowSearch from core."""
        if not self.stackoverflow_search and self.core:
            self.stackoverflow_search = getattr(self.core, "stackoverflow_search", None)
        return self.stackoverflow_search

    def _get_pypi_search(self):
        """Lazily resolve PyPISearch from core."""
        if not self.pypi_search and self.core:
            self.pypi_search = getattr(self.core, "pypi_search", None)
        return self.pypi_search

    def _get_searchcode_search(self):
        """Lazily resolve SearchcodeSearch from core."""
        if not self.searchcode_search and self.core:
            self.searchcode_search = getattr(self.core, "searchcode_search", None)
        return self.searchcode_search

    def _get_serpex_agent(self):
        """Lazily resolve or construct the niblit_agents.ResearchAgent (Serpex-backed).

        Resolution order:
        1. self.serpex_research_agent (injected at construction time)
        2. core.serpex_research_agent (set by niblit_core)
        3. Lazy construction from SERPEX_API_KEY env var (silent on failure)
        """
        if self.serpex_research_agent:
            return self.serpex_research_agent
        if self.core:
            agent = getattr(self.core, "serpex_research_agent", None)
            if agent:
                self.serpex_research_agent = agent
                return agent
        # Attempt lazy construction — only succeeds when SERPEX_API_KEY is set.
        # is_configured() always returns True since Scrapy needs no key, so
        # check the env var directly to preserve the original gating behaviour.
        if not os.getenv("SERPEX_API_KEY"):
            return None
        try:
            from niblit_agents.research_agent import ResearchAgent
            agent = ResearchAgent()
            self.serpex_research_agent = agent
            return agent
        except Exception:
            pass
        return None

    def _autonomous_serpex_research(self) -> str:
        """Step 27: Use niblit_agents.ResearchAgent (Serpex + relevance filter) for validated research.

        This step:
        1. Uses _current_cycle_topic (set at the start of every cycle) so Serpex
           data deepens the same subject that all other steps are researching.
        2. Calls ResearchAgent.search_web() which applies is_relevant() filtering so only
           semantically related snippets reach the knowledge base.
        3. Stores each validated snippet in the knowledge DB with 'ale_serpex_research:' prefix.
        4. Feeds validated snippets to BrainTrainer.ingest_research() so they immediately
           improve response quality.
        5. Appends the validated text to self._last_research_results so Steps 2-6 in the
           *current* cycle are boosted by the freshly-gathered, relevance-checked data.
        6. Adds any new topic titles found in result titles to the research queue.
        """
        agent = self._get_serpex_agent()
        if not agent:
            return "[SerpexResearch skipped — niblit_agents.ResearchAgent unavailable or no API key]"

        # Use the cycle's pinned topic so Serpex data is about the same subject
        # as all other research steps in this cycle.
        topic = (
            self._current_cycle_topic
            or self.learning_history.get("last_research_topic")
            or (self._select_next_topic() if self.research_topics else None)
        )
        if not topic:
            return "[SerpexResearch skipped — no research topics]"

        log.info("🌐 [SERPEX RESEARCH] Querying: %r", topic)

        try:
            results = agent.search_web(topic)
        except Exception as exc:
            log.debug("[SERPEX RESEARCH] search_web failed: %s", exc)
            return f"[SerpexResearch error: {exc}]"

        # Filter out error-only responses
        valid = [r for r in (results or []) if isinstance(r, dict) and "error" not in r]
        if not valid:
            return f"[SerpexResearch] No valid results for {topic!r}"

        stored = 0
        for item in valid:
            snippet = item.get("snippet", "")
            title = item.get("title", "")
            url = item.get("url", "")
            if not snippet:
                continue

            # Persist to knowledge DB
            if self.knowledge_db:
                try:
                    self.knowledge_db.add_fact(
                        f"ale_serpex_research:{topic.replace(' ', '_')}:{int(time.time())}",
                        {
                            "topic": topic,
                            "title": title,
                            "url": url,
                            "snippet": snippet[:500],
                            "step": "step27_serpex_research",
                        },
                        tags=["ale_step27", "serpex", "research", "autonomous",
                              topic.split()[0].lower()],
                    )
                    stored += 1
                except Exception as exc:
                    log.debug("[SERPEX RESEARCH] KB store failed: %s", exc)

            # Feed to BrainTrainer for immediate training improvement
            bt = self.brain_trainer or (
                getattr(self.core, "brain", None) and
                getattr(self.core.brain, "brain_trainer", None)
            )
            if bt and hasattr(bt, "ingest_research"):
                try:
                    bt.ingest_research(topic, snippet[:400])
                except Exception as exc:
                    log.debug("[SERPEX RESEARCH] BrainTrainer ingest failed: %s", exc)

            # Boost downstream steps (2-6) with validated content
            self._last_research_results.append(snippet[:400])

            # Enqueue fresh topic titles as new research seeds
            if title and title not in self.research_topics:
                self.add_research_topic(title)

        self.learning_history["serpex_research_cycles"] = (
            self.learning_history.get("serpex_research_cycles", 0) + 1
        )
        self.learning_history["last_serpex_query"] = topic

        log.info("✅ [SERPEX RESEARCH] %r — %d snippet(s) stored", topic, stored)

        # ── Semantic storage — embed all validated snippets into vector store ──
        if self.semantic_agent and valid:
            try:
                self.semantic_agent.store_knowledge(valid, source="ale_serpex", query=topic)
                log.debug("[SERPEX RESEARCH] %d snippet(s) pushed to SemanticAgent", len(valid))
            except Exception as exc:
                log.debug("[SERPEX RESEARCH] SemanticAgent store failed: %s", exc)

        return f"SerpexResearch: {topic!r} — {stored}/{len(valid)} snippet(s) validated + stored"

    # ─────────────────────────────────────────────────────────────────────────
    # SCRAPY RESEARCH AGENT helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _get_scrapy_agent(self):
        """Lazily resolve or construct the niblit_agents.ScrapyResearchAgent.

        Resolution order:
        1. self.scrapy_research_agent (injected at construction time)
        2. core.scrapy_research_agent (set by niblit_core)
        3. Lazy on-demand construction (ScrapySearchEngine needs no API key)
        """
        if self.scrapy_research_agent:
            return self.scrapy_research_agent
        if self.core:
            agent = getattr(self.core, "scrapy_research_agent", None)
            if agent:
                self.scrapy_research_agent = agent
                return agent
        # Attempt lazy construction — always succeeds when Scrapy is installed
        try:
            from niblit_agents.scrapy_research_agent import ScrapyResearchAgent
            agent = ScrapyResearchAgent()
            if agent.is_configured():
                self.scrapy_research_agent = agent
                return agent
        except Exception:
            pass
        return None

    def _autonomous_scrapy_research(self) -> str:
        """ScrapyResearch step: use ScrapyResearchAgent for direct DuckDuckGo research.

        This step:
        1. Uses ``_current_cycle_topic`` so Scrapy data deepens the same subject
           that all other steps are researching this cycle.
        2. Calls ``ScrapyResearchAgent.search_web()`` which applies relevance
           filtering so only semantically related snippets reach the knowledge base.
        3. Stores each validated snippet in the knowledge DB under the
           ``ale_scrapy_research:`` key prefix.
        4. Feeds validated snippets to ``BrainTrainer.ingest_research()`` for
           immediate quality improvement.
        5. Appends validated text to ``self._last_research_results`` so Steps 2-6
           in the current cycle are boosted by the freshly-gathered data.
        6. Adds any new topic titles found in result titles to the research queue.
        """
        agent = self._get_scrapy_agent()
        if not agent:
            return "[ScrapyResearch skipped — niblit_agents.ScrapyResearchAgent unavailable]"

        topic = (
            self._current_cycle_topic
            or self.learning_history.get("last_research_topic")
            or (self._select_next_topic() if self.research_topics else None)
        )
        if not topic:
            return "[ScrapyResearch skipped — no research topics]"

        log.info("🕷️ [SCRAPY RESEARCH] Querying: %r", topic)

        try:
            results = agent.search_web(topic)
        except Exception as exc:
            log.debug("[SCRAPY RESEARCH] search_web failed: %s", exc)
            return f"[ScrapyResearch error: {exc}]"

        valid = [r for r in (results or []) if isinstance(r, dict) and "error" not in r]
        if not valid:
            return f"[ScrapyResearch] No valid results for {topic!r}"

        stored = 0
        for item in valid:
            snippet = item.get("snippet", "")
            title = item.get("title", "")
            url = item.get("url", "")
            if not snippet:
                continue

            if self.knowledge_db:
                try:
                    self.knowledge_db.add_fact(
                        f"ale_scrapy_research:{topic.replace(' ', '_')}:{int(time.time())}",
                        {
                            "topic": topic,
                            "title": title,
                            "url": url,
                            "snippet": snippet[:500],
                            "step": "scrapy_research",
                        },
                        tags=["ale_scrapy", "scrapy", "research", "autonomous",
                              topic.split()[0].lower()],
                    )
                    stored += 1
                except Exception as exc:
                    log.debug("[SCRAPY RESEARCH] KB store failed: %s", exc)

            bt = self.brain_trainer or (
                getattr(self.core, "brain", None) and
                getattr(self.core.brain, "brain_trainer", None)
            )
            if bt and hasattr(bt, "ingest_research"):
                try:
                    bt.ingest_research(topic, snippet[:400])
                except Exception as exc:
                    log.debug("[SCRAPY RESEARCH] BrainTrainer ingest failed: %s", exc)

            self._last_research_results.append(snippet[:400])

            if title and title not in self.research_topics:
                self.add_research_topic(title)

        self.learning_history["scrapy_research_cycles"] = (
            self.learning_history.get("scrapy_research_cycles", 0) + 1
        )
        self.learning_history["last_scrapy_query"] = topic

        log.info("✅ [SCRAPY RESEARCH] %r — %d snippet(s) stored", topic, stored)

        if self.semantic_agent and valid:
            try:
                self.semantic_agent.store_knowledge(valid, source="ale_scrapy", query=topic)
                log.debug("[SCRAPY RESEARCH] %d snippet(s) pushed to SemanticAgent", len(valid))
            except Exception as exc:
                log.debug("[SCRAPY RESEARCH] SemanticAgent store failed: %s", exc)

        return f"ScrapyResearch: {topic!r} — {stored}/{len(valid)} snippet(s) stored"

    # ─────────────────────────────────────────────
    # UNIFIED RESEARCH (replaces separate SerpexResearch + Research steps)
    # ─────────────────────────────────────────────

    def _unified_research(self) -> str:
        """Unified research step — calls ALL research backends in parallel for ONE topic.

        This replaces the former two-step approach (Step 27 = SerpexResearch,
        Step 1 = Research) with a single, unified call that fans out to every
        available backend simultaneously:

            1. niblit_agents.ResearchAgent (Serpex + relevance filter)
            2. SelfResearcher (semantic KB cache → Searchcode → internet fallback)
            3. SearchcodeSearch (open-source code patterns)
            4. GitHubCodeSearch (idiomatic patterns, datasets, refactoring)
            5. SemanticAgent / Qdrant vector store (vector-similarity retrieval)

        All results are merged, de-duplicated, and stored under a single
        ``ale_unified_research:{topic}:{ts}`` key so every downstream step
        (Ideas → Learning → Implementation → Reflection) works from a
        consistently enriched knowledge base.

        A single 60-second ``_RESEARCH_INGEST_WAIT`` pause follows so the
        full ingestion → vector-embedding → KB-store pipeline settles before
        the cycle advances to the next step.
        """
        topic = self._current_cycle_topic or self._select_next_topic()
        if not topic:
            return "[UnifiedResearch skipped — no research topics]"

        log.info("🔍 [UNIFIED RESEARCH] Topic: %r  (all backends active)", topic)

        collected_snippets: List[str] = []
        backend_summaries: List[str] = []
        ts = int(time.time())

        # ── 1. Serpex ResearchAgent ────────────────────────────────────────
        agent = self._get_serpex_agent()
        if agent:
            try:
                results = agent.search_web(topic) or []
                valid = [r for r in results if isinstance(r, dict) and "error" not in r]
                for item in valid:
                    snippet = item.get("snippet", "")
                    if snippet:
                        collected_snippets.append(snippet[:500])
                        if self.knowledge_db:
                            try:
                                self.knowledge_db.add_fact(
                                    f"ale_serpex_research:{topic.replace(' ', '_')}:{ts}",
                                    {"topic": topic, "snippet": snippet[:500],
                                     "title": item.get("title", ""),
                                     "url": item.get("url", ""),
                                     "step": "unified_research_serpex"},
                                    tags=["ale_unified", "serpex", "research",
                                          topic.split()[0].lower()],
                                )
                            except Exception:
                                pass
                    title = item.get("title", "")
                    if title and title not in self.research_topics:
                        self.add_research_topic(title)
                if valid:
                    backend_summaries.append(f"Serpex({len(valid)})")
                    log.debug("[UNIFIED] Serpex: %d results", len(valid))
            except Exception as exc:
                log.debug("[UNIFIED] Serpex failed: %s", exc)

        # ── 2. SelfResearcher ─────────────────────────────────────────────
        if self.researcher:
            try:
                sr_results = self.researcher.search(
                    topic,
                    max_results=5,
                    use_history=True,
                    synthesize=True,
                    enable_autonomous_learning=True,
                ) or []
                try:
                    sr_results = list(sr_results)
                except TypeError:
                    sr_results = [sr_results] if sr_results else []
                for r in sr_results:
                    text = str(r)[:500] if r else ""
                    if text:
                        collected_snippets.append(text)
                if sr_results:
                    backend_summaries.append(f"SelfResearcher({len(sr_results)})")
                    log.debug("[UNIFIED] SelfResearcher: %d results", len(sr_results))
            except Exception as exc:
                log.debug("[UNIFIED] SelfResearcher failed: %s", exc)

        # ── 3. SearchcodeSearch ────────────────────────────────────────────
        sc = self._get_searchcode_search()
        if sc:
            try:
                sc_results = sc.discover_patterns("python", topic.split()[0], max_results=3) or []
                for r in sc_results:
                    text = r.get("text", "") if isinstance(r, dict) else str(r)
                    if text and len(text) > 20:
                        collected_snippets.append(text[:400])
                if sc_results:
                    backend_summaries.append(f"Searchcode({len(sc_results)})")
                    log.debug("[UNIFIED] Searchcode: %d results", len(sc_results))
            except Exception as exc:
                log.debug("[UNIFIED] Searchcode failed: %s", exc)

        # ── 4. GitHubCodeSearch ────────────────────────────────────────────
        gcs = self._get_github_code_search()
        if gcs and hasattr(gcs, "research_for_code_generation"):
            try:
                gh_results = gcs.research_for_code_generation(topic, max_results=3) or []
                for r in gh_results:
                    text = r.get("text", "") if isinstance(r, dict) else str(r)
                    if text and len(text) > 20:
                        collected_snippets.append(text[:400])
                if gh_results:
                    backend_summaries.append(f"GitHub({len(gh_results)})")
                    log.debug("[UNIFIED] GitHub: %d results", len(gh_results))
            except Exception as exc:
                log.debug("[UNIFIED] GitHub failed: %s", exc)

        # ── 5. SemanticAgent (Qdrant vector retrieval) ─────────────────────
        sa = self._get_semantic_agent()
        if sa and hasattr(sa, "retrieve_knowledge"):
            try:
                sa_results = sa.retrieve_knowledge(topic, top_k=3) or []
                for r in sa_results:
                    text = r.get("snippet", "") if isinstance(r, dict) else str(r)
                    if text and len(text) > 20:
                        collected_snippets.append(text[:400])
                if sa_results:
                    backend_summaries.append(f"Qdrant({len(sa_results)})")
                    log.debug("[UNIFIED] SemanticAgent: %d results", len(sa_results))
            except Exception as exc:
                log.debug("[UNIFIED] SemanticAgent retrieve failed: %s", exc)

        # ── Merge + de-duplicate snippets ─────────────────────────────────
        seen: set = set()
        deduped: List[str] = []
        for s in collected_snippets:
            key = s[:100]
            if key not in seen:
                seen.add(key)
                deduped.append(s)

        # ── Persist merged results to KB ───────────────────────────────────
        if deduped and self.knowledge_db:
            try:
                all_text = "\n---\n".join(deduped[:6])
                self.knowledge_db.add_fact(
                    f"ale_unified_research:{topic.replace(' ', '_')}:{ts}",
                    {
                        "topic": topic,
                        "results_count": len(deduped),
                        "backends": backend_summaries,
                        "summary": deduped[0][:300] if deduped else "",
                        "full_text": all_text[:1000],
                        "step": "unified_research",
                    },
                    tags=["ale_unified", "research", "autonomous",
                          topic.split()[0].lower()],
                )
                self.knowledge_db.log_event(
                    f"Unified research: {topic!r} — "
                    f"{len(deduped)} snippets from {len(backend_summaries)} backends"
                )
            except Exception as exc:
                log.debug("[UNIFIED] KB store failed: %s", exc)

        # ── Forward results to downstream steps ───────────────────────────
        self._last_research_results = deduped
        self.learning_history["research_completed"] += 1
        self.learning_history["last_research_topic"] = topic
        self.learning_history["serpex_research_cycles"] = (
            self.learning_history.get("serpex_research_cycles", 0) + 1
        )

        # ── Feed to BrainTrainer ───────────────────────────────────────────
        bt = self.brain_trainer or (
            getattr(self.core, "brain", None)
            and getattr(self.core.brain, "brain_trainer", None)
        )
        if bt and hasattr(bt, "ingest_research"):
            for snippet in deduped[:3]:
                try:
                    bt.ingest_research(topic, snippet[:400])
                except Exception:
                    pass

        # ── Push all results to SemanticAgent vector store ────────────────
        if sa and deduped:
            try:
                docs = [{"snippet": s} for s in deduped if s]
                sa.store_knowledge(docs, source="ale_unified_research", query=topic)
            except Exception as exc:
                log.debug("[UNIFIED] SemanticAgent store failed: %s", exc)

        total = len(deduped)
        summary_str = ", ".join(backend_summaries) if backend_summaries else "no backends"
        log.info(
            "✅ [UNIFIED RESEARCH] %r — %d unique snippet(s) from [%s]",
            topic, total, summary_str,
        )
        return (
            f"UnifiedResearch: {topic!r} — "
            f"{total} snippet(s) from [{summary_str}]"
        )

    def _get_semantic_agent(self):
        """Lazily resolve SemanticAgent from core."""
        if not self.semantic_agent and self.core:
            self.semantic_agent = getattr(self.core, "semantic_agent", None)
        return self.semantic_agent

    def _get_claude_engine(self):
        """Lazily resolve ClaudeEngine from core."""
        if not self.claude_engine and self.core:
            self.claude_engine = getattr(self.core, "claude_engine", None)
        return self.claude_engine

    def _get_software_studier(self):
        """Lazily resolve SoftwareStudier from core."""
        if not self.software_studier and self.core:
            self.software_studier = getattr(self.core, "software_studier", None)
        return self.software_studier

    def _get_reasoning_engine(self):
        """Lazily resolve ReasoningEngine from core."""
        if not self.reasoning_engine and self.core:
            self.reasoning_engine = getattr(self.core, "reasoning_engine", None)
        return self.reasoning_engine

    def _get_metacognition(self):
        """Lazily resolve Metacognition from core."""
        if not self.metacognition and self.core:
            self.metacognition = getattr(self.core, "metacognition", None)
        return self.metacognition

    def _get_improvement_integrator(self):
        """Lazily resolve ImprovementIntegrator from core."""
        if not self.improvement_integrator and self.core:
            self.improvement_integrator = getattr(self.core, "improvements", None)
        return self.improvement_integrator

    # ─────────────────────────────────────────────
    # IMPROVEMENT INTEGRATOR STEP (step 18)
    # ─────────────────────────────────────────────

    def _autonomous_improvement_cycle(self) -> str:
        """Step 18: Run the full 10-module improvement cycle via ImprovementIntegrator.

        This integrates parallel learning, reasoning, gap analysis, synthesis,
        prediction, memory optimization, adaptive learning, metacognition, and
        collaborative learning into one atomic pass — executed on every ALE
        background cycle so the improvements run *constantly*, not just once.

        Results from every sub-module are stored in KnowledgeDB under the tag
        ``ale_step18`` so they can be recalled, reasoned over, and acted on by
        subsequent cycles.
        """
        integrator = self._get_improvement_integrator()
        if not integrator:
            return "[Improvement cycle skipped — ImprovementIntegrator not available]"

        log.info("🔧 [IMPROVEMENT CYCLE] Starting 10-module improvement cycle...")

        try:
            results = integrator.run_full_improvement_cycle()

            # Count successes
            successful = sum(
                1 for v in results.values()
                if isinstance(v, dict) and str(v.get("status", "")).startswith("✅")
            )
            total = len(results)

            # Persist cycle summary to KB
            if self.knowledge_db:
                try:
                    self.knowledge_db.add_fact(
                        f"ale_improvement_cycle:{int(time.time())}",
                        {
                            "results": {k: str(v)[:200] for k, v in results.items()},
                            "successful": successful,
                            "total": total,
                            "step": "step18_improvement_cycle",
                        },
                        tags=["ale_step18", "improvement_cycle", "autonomous"],
                    )
                    self.knowledge_db.log_event(
                        f"Autonomous improvement cycle: {successful}/{total} modules succeeded"
                    )
                except Exception as exc:
                    log.debug(f"[IMPROVEMENT CYCLE] KB store failed: {exc}")

            log.info(f"✅ [IMPROVEMENT CYCLE] {successful}/{total} modules succeeded")
            return (
                f"Improvement cycle: {successful}/{total} modules succeeded — "
                + ", ".join(
                    f"{k}={'✅' if isinstance(v, dict) and str(v.get('status','')).startswith('✅') else '⚠️'}"
                    for k, v in results.items()
                    if k != "cycle_summary"
                )
            )

        except Exception as exc:
            log.error(f"❌ Autonomous improvement cycle failed: {exc}")
            return f"[Improvement cycle error: {exc}]"

    def _autonomous_code_research(self) -> str:
        """Step 8: Researcher + Internet + Serpex fetch real programming-language data.

        Internet is the primary source.  self_researcher provides semantic
        search / caching on top.  The niblit_agents.ResearchAgent (Serpex,
        with relevance filtering) adds a validated web-search layer.
        Results are stored in the knowledge DB so CodeGenerator can produce
        more informed code in step 9.
        """
        internet = self._get_internet()
        researcher = self.researcher
        code_gen = self._get_code_generator()
        gcs = self._get_github_code_search()
        serpex = self._get_serpex_agent()

        if not internet and not researcher and not gcs and not serpex:
            return "[Code research skipped — no internet, researcher, GitHub Code Search, or Serpex]"

        # Rotate through code research topics
        if not self.code_research_topics:
            return "[No code research topics configured]"

        self._current_code_topic = self._select_next_code_topic()
        lang, topic = self._current_code_topic
        query = f"{lang} {topic} programming best practices examples"

        log.info(f"💻 [CODE RESEARCH] Fetching: {query}")

        snippets: List[str] = []

        # 0. Serpex ResearchAgent — relevance-filtered, validated web search (new source)
        if serpex:
            try:
                serpex_results = serpex.search_web(query)
                for r in (serpex_results or []):
                    if isinstance(r, dict) and "error" not in r:
                        snippet = r.get("snippet", "")
                        if snippet and len(snippet) > 20:
                            snippets.append(snippet[:_MAX_RESEARCH_SNIPPET_LENGTH])
                            if self.knowledge_db:
                                try:
                                    self.knowledge_db.add_fact(
                                        f"ale_serpex_code:{lang}:{topic}:{int(time.time())}",
                                        snippet[:500],
                                        tags=["code", "serpex", lang, "validated"],
                                    )
                                except Exception:
                                    pass
            except Exception as exc:
                log.debug(f"Serpex code research failed: {exc}")

        # 1. Researcher (semantic search + KB cache)
        if researcher and hasattr(researcher, "research_code_and_feed_generator"):
            try:
                result = researcher.research_code_and_feed_generator(
                    lang, topic, code_generator=code_gen
                )
                if result:
                    snippets.append(str(result)[:300])
                    self.learning_history["last_language_studied"] = lang
            except Exception as exc:
                log.debug(f"Researcher code research failed: {exc}")

        # 2. Direct internet search (always run — it is the primary source)
        if internet:
            try:
                results = internet.search(query, max_results=3)
                for r in (results or []):
                    text = r.get("text", str(r)) if isinstance(r, dict) else str(r)
                    if text and len(text) > 30:
                        snippets.append(text[:300])
                        # Feed each internet snippet into the knowledge DB so CodeGenerator
                        # can draw on it when generating code (use db directly to avoid
                        # touching CodeGenerator internals).
                        if self.knowledge_db:
                            try:
                                self.knowledge_db.add_fact(
                                    f"ale_internet_code:{lang}:{topic}:{int(time.time())}",
                                    text[:500],
                                    tags=["code", "internet", lang],
                                )
                            except Exception:
                                pass
            except Exception as exc:
                log.debug(f"Internet code research failed: {exc}")

        # 3. GitHub Code Search — idiomatic patterns from real open-source repos
        gcs = self._get_github_code_search()
        if gcs:
            try:
                gh_results = gcs.research_for_code_generation(lang, topic, max_results=3)
                for r in (gh_results or []):
                    text = r.get("text", "") if isinstance(r, dict) else str(r)
                    if text and len(text) > 20:
                        snippets.append(text[:_MAX_RESEARCH_SNIPPET_LENGTH])
                        if self.knowledge_db:
                            try:
                                self.knowledge_db.add_fact(
                                    f"ale_github_code:{lang}:{topic}:{int(time.time())}",
                                    text[:500],
                                    tags=["code", "github", lang, "pattern"],
                                )
                            except Exception:
                                pass
            except Exception as exc:
                log.debug(f"GitHub code research failed: {exc}")

        # 4. Stack Overflow — bug solutions and code explanations
        so = self._get_stackoverflow_search()
        if so:
            try:
                so_results = so.research_for_code_generation(lang, topic, max_results=3)
                for r in (so_results or []):
                    text = r.get("text", "") if isinstance(r, dict) else str(r)
                    if text and len(text) > 20:
                        snippets.append(text[:_MAX_RESEARCH_SNIPPET_LENGTH])
                        if self.knowledge_db:
                            try:
                                self.knowledge_db.add_fact(
                                    f"ale_so_code:{lang}:{topic}:{int(time.time())}",
                                    text[:500],
                                    tags=["code", "stackoverflow", lang, "pattern"],
                                )
                            except Exception:
                                pass
            except Exception as exc:
                log.debug(f"Stack Overflow code research failed: {exc}")

        # 5. PyPI — package intelligence (Python only)
        if lang == "python":
            pypi = self._get_pypi_search()
            if pypi:
                try:
                    pypi_results = pypi.research_for_code_generation(lang, topic, max_results=3)
                    for r in (pypi_results or []):
                        text = r.get("text", "") if isinstance(r, dict) else str(r)
                        if text and len(text) > 20:
                            snippets.append(text[:_MAX_RESEARCH_SNIPPET_LENGTH])
                            if self.knowledge_db:
                                try:
                                    self.knowledge_db.add_fact(
                                        f"ale_pypi_code:{lang}:{topic}:{int(time.time())}",
                                        text[:500],
                                        tags=["code", "pypi", lang, "library"],
                                    )
                                except Exception:
                                    pass
                except Exception as exc:
                    log.debug(f"PyPI code research failed: {exc}")

        if not snippets:
            return f"[No code research results for {lang}/{topic}]"

        # Persist combined findings
        combined = "\n---\n".join(snippets[:3])
        if self.knowledge_db:
            try:
                self.knowledge_db.add_fact(
                    f"ale_code_research:{lang}:{topic}",
                    combined,
                    tags=["code", "research", "autonomous", lang]
                )
                self.knowledge_db.queue_learning(f"{lang} {topic} advanced patterns")
            except Exception as exc:
                log.debug(f"DB store failed: {exc}")

        self.learning_history["code_researched"] = self.learning_history.get("code_researched", 0) + 1
        # Store the most-recently researched topic so generation can use it
        self.learning_history["last_topic_researched"] = topic
        active_sources = []
        if internet:
            active_sources.append("internet")
        if gcs:
            active_sources.append("GitHub")
        if so:
            active_sources.append("StackOverflow")
        if lang == "python" and self._get_pypi_search():
            active_sources.append("PyPI")
        sources = ", ".join(active_sources) if active_sources else "researcher"
        log.info(f"✅ [CODE RESEARCH] {lang}/{topic}: {len(snippets)} snippet(s) collected")
        return f"Code research: {lang}/{topic} — {len(snippets)} snippet(s) via {sources}"

    def _autonomous_code_generation(self) -> str:
        """Step 9: Generate real code from research, using LLM when available.

        Collects all recent research findings stored in the KB during step 8,
        builds a rich context string, then:

        1. Attempts LLM-powered code synthesis via
           ``CodeGenerator.generate_with_llm()`` — produces actual logic
           informed by the research.
        2. Falls back to structural template generation when the LLM is
           unavailable or returns nothing useful.

        Uses knowledge collected in step 8 to generate well-informed, real code
        (not stub templates) by passing the full research text to
        ``CodeGenerator.generate_from_research()``.  The resulting code contains
        working constants, utility functions, and class methods derived from what
        was actually researched.  It is queued for compilation in step 10.
        """
        code_gen = self._get_code_generator()
        llm = self._get_llm()

        if not code_gen:
            return "[Code generation skipped — CodeGenerator not available]"

        lang = self.learning_history.get("last_language_studied") or "python"

        # ── Pull the actual research topic + full text from the KB ──────────
        research_topic = "autonomous improvement"
        research_text = ""
        if self.knowledge_db:
            try:
                facts = (
                    self.knowledge_db.list_facts(20)
                    if hasattr(self.knowledge_db, "list_facts")
                    else []
                )
                # Walk facts newest-first to find the most recent code-research entry
                for f in reversed(facts):
                    if not isinstance(f, dict):
                        continue
                    key = f.get("key", "")
                    if key.startswith("ale_code_research:") or key.startswith("ale_internet_code:"):
                        # Key format: ale_code_research:{lang}:{topic}
                        parts = key.split(":", 2)
                        if len(parts) >= 3:
                            research_topic = parts[2].replace(":", " ").replace("_", " ")
                            # Also restore the researched lang if it differs
                            if len(parts) >= 2 and parts[1]:
                                lang = parts[1]
                        research_text = str(f.get("value", ""))
                        if research_text:
                            break
            except Exception as exc:
                log.debug("KB research-text lookup failed: %s", exc)

        # If no KB research found, fall back to learning history topic
        if not research_text:
            research_topic = self.learning_history.get("last_topic_researched", research_topic)

        # ── Generate real, functional code via generate_from_research() ──────
        try:
            if hasattr(code_gen, "generate_from_research"):
                result = code_gen.generate_from_research(
                    lang,
                    research_topic,
                    research_text,
                )
                snippet_key = result.get("snippet_key", "generic")
                log.info(
                    "[CODE GEN] Research-driven generation — lang=%s topic=%r pattern=%s",
                    lang, research_topic, snippet_key,
                )
            elif hasattr(code_gen, "generate_with_validation"):
                # Fallback: template-based with research as docstring
                safe_topic = research_topic.replace(" ", "_")[:30]
                result = code_gen.generate_with_validation(
                    lang,
                    "module",
                    name=f"ale_{lang}_{safe_topic}",
                    classname="".join(
                        w.capitalize()
                        for w in f"ale_{lang}_{safe_topic}".split("_")
                    ),
                    docstring=f"{research_topic}: {research_text[:120]}",
                )
            else:
                result = code_gen.generate_niblit_module(
                    name=f"ale_{lang}_module",
                    docstring=research_topic,
                )

            code = result.get("code", "")
            if not result.get("success") or not code:
                return f"[Code generation failed: {result.get('error', 'unknown')}]"

            # Queue the generated code for compilation
            self._pending_compiled.append({
                "language": lang,
                "code": code,
                "topic": research_topic,
            })

            self.learning_history["code_generated"] = (
                self.learning_history.get("code_generated", 0) + 1
            )
            log.info("✅ [CODE GEN] Generated %s code (%d chars) for '%s'",
                     lang, len(code), research_topic)

            # Use the module name already derived inside generate_from_research
            # (returned in result["name"]) to ensure save paths are consistent.
            module_name = result.get("name") or f"ale_{lang}_module"

            # Save generated .py to the Niblit deploy path so it can be
            # hot-reloaded and pushed to GitHub via GitHubSync.
            deploy_note = ""
            if hasattr(code_gen, "save_to_deploy") and lang == "python":
                try:
                    save_result = code_gen.save_to_deploy(module_name, code)
                    if save_result.get("success"):
                        deploy_note = f" → saved to {save_result['path']}"
                        log.info("[CODE GEN] Saved generated module to deploy path: %s",
                                 save_result["path"])
                except Exception as exc:
                    log.debug("save_to_deploy failed: %s", exc)

            # Save all generated code to the structured builds/ folder.
            build_note = ""
            if hasattr(code_gen, "save_to_builds"):
                try:
                    build_result = code_gen.save_to_builds(lang, module_name, code)
                    if build_result.get("success"):
                        build_note = f" → builds/{lang}/"
                except Exception as exc:
                    log.debug("save_to_builds failed: %s", exc)

            return (
                f"Code generated: {lang} '{research_topic}' "
                f"({len(code)} chars) — queued for compilation"
                f"{deploy_note}{build_note}"
            )

        except Exception as exc:
            log.error("❌ Autonomous code generation failed: %s", exc)
            return f"[Code generation error: {exc}]"

    def _autonomous_code_compilation(self) -> str:
        """Step 10: Syntax-test then compile generated code; store results.

        Workflow (mirrors codeSL tester):
          1. syntax_test  — fast, no side-effects (bash -n / ast / node --check)
          2. If syntax fails → log, store failure record, skip execution
          3. If syntax passes → code_compiler.run() (full execution)
        """
        code_compiler = self._get_code_compiler()

        if not code_compiler:
            return "[Code compilation skipped — CodeCompiler not available]"

        if not self._pending_compiled:
            # Generate a minimal test snippet if queue is empty
            self._pending_compiled.append({
                "language": "python",
                "code": "# ALE health-check\nprint('ALE compile check OK')\n",
                "topic": "health_check",
            })

        item = self._pending_compiled.pop(0)
        lang = item.get("language", "python")
        code = item.get("code", "")
        topic = item.get("topic", "unknown")

        if not code.strip():
            return "[Empty code — skipped compilation]"

        # Languages that CodeCompiler can execute directly.
        _EXECUTABLE_LANGS = {"python", "python3", "bash", "sh", "javascript", "js"}

        # For languages that require a native toolchain (e.g. rustc, javac, gcc)
        # which may not be present, save the source to the builds/ folder so the
        # program is available for later use in a Termux environment.
        if lang not in _EXECUTABLE_LANGS:
            build_note = ""
            code_gen = self._get_code_generator()
            if code_gen and hasattr(code_gen, "save_to_builds"):
                try:
                    save_result = code_gen.save_to_builds(lang, topic, code)
                    if save_result.get("success"):
                        build_note = f" → saved to builds/{lang}/"
                        log.info("[CODE COMPILE] %s/%s source saved to builds/%s/", lang, topic, lang)
                except Exception as exc:
                    log.debug(f"save_to_builds in compilation step failed: {exc}")
            # Store a record for reflection — mark as source-saved rather than executed
            saved_record = {
                "language": lang,
                "topic": topic,
                "code": code[:400],
                "output": "",
                "error": "",
                "success": True,
                "saved_only": True,  # source saved to builds/, not executed
            }
            self._compiled_for_reflection.append(saved_record)
            if self.knowledge_db:
                try:
                    key = f"ale_compiled:{lang}:{topic}:{int(time.time())}"
                    self.knowledge_db.add_fact(key, str(saved_record), tags=["compiled", "autonomous", lang, "source_saved"])
                except Exception:
                    pass
            self.learning_history["code_compiled"] = self.learning_history.get("code_compiled", 0) + 1
            return f"Code compiled: {lang}/{topic}: ✅ source saved{build_note}"

        try:
            # ── Phase 1: syntax-test; auto-fix on failure ─────────────────
            syntax_result = (
                code_compiler.syntax_test(lang, code)
                if hasattr(code_compiler, "syntax_test")
                else {"valid": True, "error": None}
            )
            if not syntax_result.get("valid", True):
                syntax_err = syntax_result.get("error", "syntax error")
                log.warning(f"⚙️ [CODE SYNTAX] {lang}/{topic}: ❌ {syntax_err} — attempting auto-fix")

                # ── Auto-fix via CodeErrorFixer ───────────────────────────
                fix_applied = False
                fix_explanation = ""
                try:
                    from modules.code_error_fixer import CodeErrorFixer  # pylint: disable=import-outside-toplevel
                    fixer = CodeErrorFixer(db=self.knowledge_db)
                    fixed_code, fix_ok, fix_explanation = fixer.fix_syntax_errors(
                        lang, code, syntax_err, code_compiler
                    )
                    if fix_ok:
                        log.info(f"🔧 [AUTO-FIX] {lang}/{topic}: fixed — {fix_explanation}")
                        code = fixed_code
                        fix_applied = True
                    else:
                        log.warning(f"🔧 [AUTO-FIX] {lang}/{topic}: fix failed — {fix_explanation}")
                except Exception as fix_exc:
                    log.debug(f"CodeErrorFixer unavailable: {fix_exc}")

                if not fix_applied:
                    failed_record = {
                        "language": lang,
                        "topic": topic,
                        "code": code[:_MAX_FAILED_CODE_SNIPPET_LENGTH],
                        "output": "",
                        "error": f"SyntaxError: {syntax_err}"[:200],
                        "success": False,
                    }
                    if self.knowledge_db:
                        try:
                            key = f"ale_syntax_fail:{lang}:{topic}:{int(time.time())}"
                            self.knowledge_db.add_fact(key, str(failed_record), tags=["syntax_fail", "autonomous", lang])
                        except Exception:
                            pass
                    self._compiled_for_reflection.append(failed_record)
                    return f"Code compiled: {lang}/{topic}: ❌ syntax failed | error: {syntax_err[:80]}"

            # ── Phase 2: full execution via compile_with_autofix ──────────
            if hasattr(code_compiler, "compile_with_autofix"):
                exec_result = code_compiler.compile_with_autofix(lang, code)
            else:
                exec_result = code_compiler.run(lang, code)
            success = getattr(exec_result, "success", False)
            output = getattr(exec_result, "stdout", "") or ""
            error = getattr(exec_result, "error", "") or getattr(exec_result, "stderr", "") or ""

            status = "✅ success" if success else "❌ failed"
            log.info(f"⚙️ [CODE COMPILE] {lang}/{topic}: {status}")

            # Store result for reflection (step 11)
            compiled_record = {
                "language": lang,
                "topic": topic,
                "code": code[:400],
                "output": output[:300],
                "error": error[:200],
                "success": success,
            }

            # Persist to KB
            if self.knowledge_db:
                try:
                    key = f"ale_compiled:{lang}:{topic}:{int(time.time())}"
                    self.knowledge_db.add_fact(key, str(compiled_record), tags=["compiled", "autonomous", lang])
                except Exception as exc:
                    log.debug(f"DB store compiled failed: {exc}")

            # Queue for reflection
            if not success:
                self._pending_compiled.insert(0, compiled_record)
            # Store a copy for reflect step (attribute initialized in __init__)
            self._compiled_for_reflection.append(compiled_record)

            self.learning_history["code_compiled"] = self.learning_history.get("code_compiled", 0) + 1

            summary = f"{lang}/{topic}: {status}"
            if output:
                summary += f" | output: {output[:60]}"
            if error and not success:
                summary += f" | error: {error[:60]}"
            return f"Code compiled: {summary}"

        except Exception as exc:
            log.error(f"❌ Autonomous code compilation failed: {exc}")
            return f"[Compilation error: {exc}]"

    def _autonomous_code_reflection(self) -> str:
        """Step 11: ReflectModule studies compiled output and stores actionable learnings.

        Beyond just recording what happened, this step extracts actionable
        learnings (e.g. which patterns worked, which errors occurred) and stores
        them under ``ale_code_learning:{lang}:`` keys so that
        :meth:`_autonomous_code_generation` (step 9) can pull them in the next
        cycle as research context and produce progressively better code.
        """
        if not self.reflect:
            return "[Code reflection skipped — ReflectModule not available]"

        if not self._compiled_for_reflection:
            return "[No compiled code queued for reflection]"

        record = self._compiled_for_reflection.pop(0)
        lang = record.get("language", "python")
        topic = record.get("topic", "unknown")
        code = record.get("code", "")
        output = record.get("output", "")
        error = record.get("error", "")
        success = record.get("success", False)

        reflection_text = (
            f"Compiled {lang} code for '{topic}'. "
            f"Success: {success}. "
            f"Output: {output[:150] if output else 'none'}. "
            f"Error: {error[:100] if error else 'none'}. "
            f"Code snippet: {code[:200]}"
        )

        try:
            if hasattr(self.reflect, "collect_and_summarize"):
                result = self.reflect.collect_and_summarize(reflection_text)
            elif hasattr(self.reflect, "reflect"):
                result = self.reflect.reflect(reflection_text)
            else:
                result = f"[Reflect method unavailable — stored: {reflection_text[:60]}]"

            # Feed full reflection back into the knowledge DB (existing behaviour)
            if self.knowledge_db:
                try:
                    key = f"ale_code_reflection:{lang}:{topic}:{int(time.time())}"
                    self.knowledge_db.add_fact(
                        key,
                        str(result or reflection_text),
                        tags=["reflection", "code", lang],
                    )
                except Exception as exc:
                    log.debug(f"DB store reflection failed: {exc}")

            # ── Store actionable learnings for next generation cycle ────────
            # Tag as ale_code_learning so _autonomous_code_generation can find
            # them when building its research context for the LLM prompt.
            if self.knowledge_db:
                try:
                    if success and output:
                        # Successful run: record what the code produced
                        learning = (
                            f"Successful {lang} pattern for '{topic}': "
                            f"output='{output[:120]}'. "
                            f"Code excerpt: {code[:_MAX_LEARNING_CODE_EXCERPT]}"
                        )
                    elif not success and error:
                        # Failed run: record the error so future code avoids it
                        learning = (
                            f"Fix needed for {lang} '{topic}': error='{error[:120]}'. "
                            f"Avoid pattern: {code[:_MAX_LEARNING_CODE_EXCERPT]}"
                        )
                    else:
                        learning = None

                    if learning:
                        learn_key = f"ale_code_learning:{lang}:{topic}:{int(time.time())}"
                        self.knowledge_db.add_fact(
                            learn_key,
                            learning,
                            tags=["code_learning", "autonomous", lang],
                        )
                        log.debug("[CODE REFLECT] Stored learning: %s", learning[:80])
                except Exception as exc:
                    log.debug(f"DB store learning failed: {exc}")

            self.learning_history["code_reflected"] = self.learning_history.get("code_reflected", 0) + 1
            log.info(f"🔍 [CODE REFLECT] {lang}/{topic} — reflection + learning stored")
            return f"Code reflection: {lang}/{topic} — {'OK' if success else 'studied error'}"

        except Exception as exc:
            log.error(f"❌ Autonomous code reflection failed: {exc}")
            return f"[Code reflection error: {exc}]"

    def _autonomous_software_study(self) -> str:
        """Step 12: SoftwareStudier analyzes code functions/patterns via internet data.

        Uses internet to enrich its understanding beyond the static KB,
        making Niblit progressively more software- and language-literate.
        """
        studier = self._get_software_studier()
        internet = self._get_internet()

        if not studier and not internet:
            return "[Software study skipped — SoftwareStudier and internet not available]"

        # Pick a category to study
        if not self.software_study_categories:
            return "[No software study categories configured]"

        category = random.choice(self.software_study_categories)
        log.info(f"📖 [SOFTWARE STUDY] Studying: {category}")

        result_parts: List[str] = []

        # 1. SoftwareStudier built-in analysis
        if studier and hasattr(studier, "study_category"):
            try:
                study_result = studier.study_category(category)
                if study_result:
                    result_parts.append(study_result[:300])
                    self.learning_history["last_software_category"] = category
            except Exception as exc:
                log.debug(f"SoftwareStudier.study_category failed: {exc}")

        # 2. Internet enrichment — get up-to-date info about the category
        if internet:
            query = f"{category.replace('_', ' ')} software architecture patterns 2024"
            try:
                web_results = internet.search(query, max_results=2)
                for r in (web_results or []):
                    text = r.get("text", str(r)) if isinstance(r, dict) else str(r)
                    if text and len(text) > 30:
                        result_parts.append(text[:250])
            except Exception as exc:
                log.debug(f"Internet software study failed: {exc}")

        # 3. Analyze code patterns from the last compiled item for this category
        if self._compiled_for_reflection:
            last = self._compiled_for_reflection[-1] if self._compiled_for_reflection else {}
            code_snippet = last.get("code", "")
            if code_snippet:
                if studier and hasattr(studier, "analyze_architecture"):
                    try:
                        arch_result = studier.analyze_architecture("modular")
                        result_parts.append(arch_result[:200])
                    except Exception:
                        pass

        if not result_parts:
            return f"[No software study results for '{category}']"

        combined = "\n".join(result_parts[:2])

        # Persist to KB for future language-literacy lookups
        if self.knowledge_db:
            try:
                key = f"ale_software_study:{category}:{int(time.time())}"
                self.knowledge_db.add_fact(key, combined, tags=["software_study", "autonomous", category])
                self.knowledge_db.queue_learning(f"{category} software engineering principles")
            except Exception as exc:
                log.debug(f"DB store software study failed: {exc}")

        self.learning_history["software_studied"] = self.learning_history.get("software_studied", 0) + 1
        log.info(f"✅ [SOFTWARE STUDY] '{category}' complete — {len(result_parts)} source(s)")
        return f"Software study: '{category}' — {len(result_parts)} source(s) via internet+KB"

    # ─────────────────────────────────────────────
    # COMMAND AWARENESS & EXECUTION (steps 13 & 14)
    # ─────────────────────────────────────────────

    def _get_structural_awareness(self):
        """Lazily resolve StructuralAwareness from core."""
        if self.core:
            return getattr(self.core, "structural_awareness", None)
        return None

    def _autonomous_command_awareness(self) -> str:
        """Step 13: Study all registered commands, understand their purpose, store in KB.

        Collects every command from the CommandRegistry (and router COMMAND_PREFIXES)
        via StructuralAwareness.command_awareness_report().  Each command is stored as
        a structured fact so Niblit can recall *what commands it has* during reflection
        and planning.
        """
        sa = self._get_structural_awareness()
        router = getattr(self.core, "router", None) if self.core else None

        log.info("📋 [COMMAND AWARENESS] Studying registered commands...")

        # Build awareness dict
        if sa and hasattr(sa, "command_awareness_report"):
            awareness = sa.command_awareness_report(router=router)
        elif router and hasattr(router, "COMMAND_PREFIXES"):
            awareness = {
                "total": len(router.COMMAND_PREFIXES),
                "commands": [{"name": c, "description": "", "category": "router"}
                             for c in router.COMMAND_PREFIXES],
                "by_category": {"router": list(router.COMMAND_PREFIXES)},
                "categories": ["router"],
            }
        else:
            return "[Command awareness skipped — StructuralAwareness and router unavailable]"

        total = awareness.get("total", 0)
        if total == 0:
            return "[No commands found for command awareness]"

        # Persist to knowledge base
        if self.knowledge_db:
            try:
                # Store the full inventory once (keyed by timestamp to allow history)
                self.knowledge_db.add_fact(
                    f"ale_command_awareness:{int(time.time())}",
                    {
                        "total_commands": total,
                        "categories": awareness.get("categories", []),
                        "by_category": awareness.get("by_category", {}),
                        "step": "step13_command_awareness",
                    },
                    tags=["ale_step13", "command_awareness", "autonomous"],
                )
                # Also store each category summary as a searchable fact
                for cat, names in awareness.get("by_category", {}).items():
                    self.knowledge_db.add_fact(
                        f"ale_cmd_cat:{cat}",
                        {"category": cat, "commands": names, "count": len(names)},
                        tags=["ale_step13", "commands", cat],
                    )
                self.knowledge_db.log_event(
                    f"Command awareness: catalogued {total} commands in "
                    f"{len(awareness.get('categories', []))} categories"
                )
            except Exception as exc:
                log.debug(f"Command awareness DB store failed: {exc}")

        self.learning_history["command_awareness_cycles"] = (
            self.learning_history.get("command_awareness_cycles", 0) + 1
        )
        self.learning_history["last_commands_studied"] = total

        log.info(f"✅ [COMMAND AWARENESS] {total} commands catalogued across "
                 f"{len(awareness.get('categories', []))} categories")
        return (f"Command awareness: {total} commands catalogued in "
                f"{len(awareness.get('categories', []))} categories")

    # ─────────────────────────────────────────────
    def _autonomous_command_execution(self) -> str:
        """Step 14: Autonomously execute a selection of safe diagnostic commands.

        After studying commands in step 13, Niblit runs a curated set of
        *read-only* / *diagnostic* commands through the core or router to
        observe their output, validate they work, and store results in KB.
        This closes the loop: study → understand → verify.
        """
        core = self.core
        router = getattr(core, "router", None) if core else None

        # Safe, read-only commands to execute autonomously
        SAFE_COMMANDS: List[Dict[str, str]] = [
            {"cmd": "status",           "label": "system_status"},
            {"cmd": "health",           "label": "health_check"},
            {"cmd": "my structure",     "label": "component_inventory"},
            {"cmd": "my loops",         "label": "loop_status"},
            {"cmd": "my threads",       "label": "thread_status"},
            {"cmd": "my modules",       "label": "loaded_modules"},
            {"cmd": "my commands",      "label": "command_list"},
            {"cmd": "resource usage",   "label": "resource_usage"},
            {"cmd": "autonomous-learn status", "label": "ale_status"},
            {"cmd": "knowledge stats",  "label": "knowledge_summary"},
            {"cmd": "ale processes",    "label": "ale_process_awareness"},
        ]

        results: List[Dict[str, Any]] = []
        handler = None
        if core and hasattr(core, "handle"):
            handler = core.handle
        elif router and hasattr(router, "process"):
            handler = router.process

        if not handler:
            return "[Command execution skipped — no core.handle or router.process available]"

        log.info(f"⚡ [COMMAND EXEC] Executing {len(SAFE_COMMANDS)} diagnostic commands...")

        for entry in SAFE_COMMANDS:
            cmd = entry["cmd"]
            label = entry["label"]
            try:
                output = handler(cmd)
                snippet = str(output or "")[:200]
                results.append({"command": cmd, "label": label, "ok": True, "output": snippet})
                log.debug(f"  ✅ {cmd}: {snippet[:60]}")
            except Exception as exc:
                results.append({"command": cmd, "label": label, "ok": False, "error": str(exc)[:120]})
                log.debug(f"  ❌ {cmd}: {exc}")

        # Persist full execution report to KB
        ok_count = sum(1 for r in results if r.get("ok"))
        if self.knowledge_db:
            try:
                self.knowledge_db.add_fact(
                    f"ale_command_execution:{int(time.time())}",
                    {
                        "executed": len(results),
                        "ok": ok_count,
                        "failed": len(results) - ok_count,
                        "results": results,
                        "step": "step14_command_execution",
                    },
                    tags=["ale_step14", "command_execution", "autonomous"],
                )
                self.knowledge_db.log_event(
                    f"Autonomous command execution: {ok_count}/{len(results)} commands succeeded"
                )
            except Exception as exc:
                log.debug(f"Command execution DB store failed: {exc}")

        self.learning_history["command_executions"] = (
            self.learning_history.get("command_executions", 0) + 1
        )

        log.info(f"✅ [COMMAND EXEC] {ok_count}/{len(results)} commands succeeded")
        return f"Command execution: {ok_count}/{len(results)} safe commands executed successfully"

    # ─────────────────────────────────────────────
    # AUTONOMOUS TOPIC SEEDING (step 15)
    # ─────────────────────────────────────────────

    def _derive_topics_from_kb(self, max_topics: int = 10) -> List[str]:
        """Extract fresh topic candidates from recent KnowledgeDB facts.

        Pulls keywords from the keys and values of the most recent ALE facts
        so that Niblit's research scope grows organically from what it already
        knows rather than staying frozen on the initial hard-coded list.
        """
        candidates: List[str] = []

        # 1. Recent researched topics stored as ale_step1 facts (requires KB)
        if self.knowledge_db:
            try:
                if hasattr(self.knowledge_db, "list_facts"):
                    facts = self.knowledge_db.list_facts(30)
                    for f in (facts or []):
                        if not isinstance(f, dict):
                            continue
                        key = str(f.get("key", ""))
                        val = f.get("value", {})
                        # Extract topic from research facts
                        if "ale_research:" in key or "ale_code_research:" in key:
                            parts = key.split(":")
                            if len(parts) >= 2:
                                raw = parts[1].replace("_", " ")
                                if raw and raw not in candidates:
                                    candidates.append(raw)
                        if isinstance(val, dict):
                            t = val.get("topic", "")
                            if t and t not in candidates:
                                candidates.append(str(t))
                            # Programming-literacy lang/topic combos
                            lang = val.get("language", "")
                            if lang and f"advanced {lang}" not in candidates:
                                candidates.append(f"advanced {lang}")
            except Exception as exc:
                log.debug(f"Topic derivation from facts failed: {exc}")

        # 2. Derive from the last research/idea (always runs, KB-independent)
        last_topic = self.learning_history.get("last_research_topic") or ""
        if last_topic:
            words = [w for w in last_topic.split() if len(w) > 4]
            for w in words:
                variation = f"{w} techniques"
                if variation not in candidates:
                    candidates.append(variation)

        # 3. Derive from code-research language list (always runs)
        for lang, topic in self.code_research_topics[:5]:
            combo = f"{lang} {topic}"
            if combo not in candidates:
                candidates.append(combo)

        # 4. Derive from software study categories (always runs)
        for cat in self.software_study_categories[:5]:
            human = cat.replace("_", " ")
            if human not in candidates:
                candidates.append(human)

        # Deduplicate and skip topics already in the research list
        existing = set(self.research_topics)
        fresh = [t for t in candidates if t and t not in existing]

        # Trim to max_topics
        return fresh[:max_topics]

    def _autonomous_topic_seeding(self) -> str:
        """Step 15: Derive new topics from knowledge and feed them to every
        topic-accepting subsystem.

        Topics are added to:
          • ALE research queue (`add_research_topic`)
          • KnowledgeDB learning queue (`queue_learning`)
          • SLSA engine (`slsa_manager.add_topics` — no restart required)
        """
        log.info("🌱 [TOPIC SEEDING] Deriving new topics from KB...")

        # 1. Derive candidate topics
        new_topics = self._derive_topics_from_kb(max_topics=10)

        if not new_topics:
            log.info("[TOPIC SEEDING] No new topics derived this cycle")
            return "Topic seeding: no new topics derived this cycle"

        seeded_ale: List[str] = []
        seeded_kb: List[str] = []
        seeded_slsa: List[str] = []

        for topic in new_topics:
            # a. ALE research queue
            if self.add_research_topic(topic):
                seeded_ale.append(topic)

            # b. KnowledgeDB learning queue
            if self.knowledge_db:
                try:
                    self.knowledge_db.queue_learning(topic)
                    seeded_kb.append(topic)
                except Exception as exc:
                    log.debug(f"KB queue_learning failed for '{topic}': {exc}")

        # c. SLSA — add topics (prefers add_topics to avoid restart)
        if self.slsa_manager:
            try:
                slsa_result = self.slsa_manager.add_topics(new_topics)
                seeded_slsa = new_topics
                log.debug(f"SLSA topic seeding: {slsa_result}")
            except Exception as exc:
                # Fallback: restart with merged topics
                try:
                    merged = list(set(self.slsa_manager.get_topics() + new_topics))
                    self.slsa_manager.restart(merged)
                    seeded_slsa = new_topics
                except Exception:
                    log.debug(f"SLSA topic seeding failed: {exc}")

        # Persist record of what was seeded
        if self.knowledge_db:
            try:
                self.knowledge_db.add_fact(
                    f"ale_topic_seeding:{int(time.time())}",
                    {
                        "new_topics": new_topics,
                        "seeded_ale": seeded_ale,
                        "seeded_kb": seeded_kb,
                        "seeded_slsa": seeded_slsa,
                        "step": "step15_topic_seeding",
                    },
                    tags=["ale_step15", "topic_seeding", "autonomous"],
                )
                self.knowledge_db.log_event(
                    f"Autonomous topic seeding: {len(seeded_ale)} → ALE, "
                    f"{len(seeded_kb)} → KB, {len(seeded_slsa)} → SLSA"
                )
            except Exception as exc:
                log.debug(f"Topic seeding DB store failed: {exc}")

        self.learning_history["topic_seedings"] = (
            self.learning_history.get("topic_seedings", 0) + 1
        )
        self.learning_history["last_seeded_topics"] = new_topics[:5]

        log.info(
            f"✅ [TOPIC SEEDING] {len(seeded_ale)} → ALE | "
            f"{len(seeded_kb)} → KB queue | {len(seeded_slsa)} → SLSA"
        )
        return (
            f"Topic seeding: {len(seeded_ale)} new topics → ALE research, "
            f"{len(seeded_kb)} → KB queue, {len(seeded_slsa)} → SLSA "
            f"({', '.join(new_topics[:3])}{'...' if len(new_topics) > 3 else ''})"
        )

    # ─────────────────────────────────────────────
    # INTELLIGENT REASONING (step 16)
    # ─────────────────────────────────────────────

    def _autonomous_reasoning(self) -> str:
        """Step 16: Use ReasoningEngine to build a knowledge graph from recent facts,
        create reasoning chains, and infer new knowledge.

        The inferred facts are stored back into KnowledgeDB so every subsequent
        cycle benefits from the connected understanding built here.
        """
        engine = self._get_reasoning_engine()
        if not engine:
            return "[Reasoning skipped — ReasoningEngine not available]"

        log.info("🧠 [REASONING] Starting intelligent reasoning step...")

        # Pull recent facts from knowledge DB to reason over
        facts: List[Dict] = []
        if self.knowledge_db:
            try:
                raw = (
                    self.knowledge_db.list_facts(50)
                    if hasattr(self.knowledge_db, "list_facts")
                    else []
                )
                for f in (raw or []):
                    if isinstance(f, dict):
                        facts.append({"key": str(f.get("key", "")), "value": str(f.get("value", ""))})
                    elif isinstance(f, (list, tuple)) and len(f) >= 2:
                        facts.append({"key": str(f[0]), "value": str(f[1])})
            except Exception as exc:
                log.debug(f"[REASONING] Failed to load facts from KB: {exc}")

        if not facts:
            # Nothing to reason over yet — seed with learning history
            topic = self.learning_history.get("last_research_topic") or "artificial intelligence"
            facts = [{"key": f"ale_seed:{topic}", "value": topic, "tags": ["ale"]}]

        try:
            # 1. Build knowledge graph
            graph = engine.build_knowledge_graph(facts)
            graph_size = len(graph)

            # 2. Create reasoning chains from a starting concept
            start_concept = (
                self.learning_history.get("last_research_topic") or
                next(iter(graph), "learning")
            )
            chain = engine.create_reasoning_chain(start_concept, depth=4)

            # 3. Infer new knowledge
            inferences = engine.infer_new_knowledge()
            inference_count = len(inferences)

            # Store graph summary and inferences in KB
            if self.knowledge_db:
                try:
                    self.knowledge_db.add_fact(
                        f"ale_reasoning:{int(time.time())}",
                        {
                            "graph_concepts": graph_size,
                            "chain": chain,
                            "inferences_count": inference_count,
                            "sample_inferences": inferences[:3],
                            "step": "step16_reasoning",
                        },
                        tags=["ale_step16", "reasoning", "autonomous"],
                    )
                    # Store each inference as a searchable fact
                    for i, inference in enumerate(inferences[:5]):
                        self.knowledge_db.add_fact(
                            f"ale_inference:{int(time.time())}_{i}",
                            inference,
                            tags=["ale_step16", "inference", "reasoning"],
                        )
                    self.knowledge_db.log_event(
                        f"Autonomous reasoning: {graph_size} concepts, "
                        f"{len(chain)}-step chain, {inference_count} inferences"
                    )
                except Exception as exc:
                    log.debug(f"[REASONING] KB store failed: {exc}")

            self.learning_history["reasoning_cycles"] = (
                self.learning_history.get("reasoning_cycles", 0) + 1
            )
            self.learning_history["last_reasoning_inferences"] = inference_count

            log.info(
                f"✅ [REASONING] Graph: {graph_size} concepts | "
                f"Chain: {' → '.join(chain)} | Inferences: {inference_count}"
            )
            return (
                f"Reasoning: {graph_size} concepts in graph, "
                f"{len(chain)}-step chain from '{start_concept}', "
                f"{inference_count} new inferences stored"
            )

        except Exception as exc:
            log.error(f"❌ Autonomous reasoning failed: {exc}")
            return f"[Reasoning error: {exc}]"

    # ─────────────────────────────────────────────
    # METACOGNITION (step 17)
    # ─────────────────────────────────────────────

    def _autonomous_metacognition(self) -> str:
        """Step 17: Use Metacognition to evaluate Niblit's own knowledge,
        identify boundaries/gaps, and store the self-assessment in KB.

        The evaluation guides which topics future ALE cycles should prioritise.
        """
        meta = self._get_metacognition()
        if not meta:
            return "[Metacognition skipped — Metacognition module not available]"

        log.info("🔮 [METACOGNITION] Starting self-knowledge evaluation...")

        # Pull facts for metacognitive analysis
        facts: List[Dict] = []
        if self.knowledge_db:
            try:
                raw = (
                    self.knowledge_db.list_facts(100)
                    if hasattr(self.knowledge_db, "list_facts")
                    else []
                )
                for f in (raw or []):
                    if isinstance(f, dict):
                        facts.append(f)
                    elif isinstance(f, (list, tuple)) and len(f) >= 2:
                        facts.append({"key": str(f[0]), "value": str(f[1])})
            except Exception as exc:
                log.debug(f"[METACOGNITION] Failed to load facts from KB: {exc}")

        # Topics attempted by the ALE so far — built in steps to keep it readable
        recent_topics = [
            self.learning_history.get("last_research_topic"),
            self.learning_history.get("last_language_studied"),
            self.learning_history.get("last_software_category"),
        ]
        recent_topics.extend(self.research_topics[:5])
        attempted_topics = list(dict.fromkeys(t for t in recent_topics if t))

        try:
            # 1. Build knowledge map
            knowledge_map = meta.build_knowledge_map(facts) if facts else {}

            # 2. Identify knowledge boundaries
            boundaries = meta.identify_knowledge_boundaries(attempted_topics)

            # 3. Self-evaluate overall understanding
            evaluation = meta.evaluate_understanding()

            confidence = evaluation.get("overall_confidence", "unknown")
            total_items = evaluation.get("total_knowledge_items", 0)
            unknown_count = len(boundaries.get("unknown", []))
            poorly_understood = boundaries.get("poorly_understood", [])

            # Feed gaps back into ALE research queue so they get studied
            for gap_topic in poorly_understood[:3]:
                self.add_research_topic(gap_topic)
                if self.knowledge_db:
                    try:
                        self.knowledge_db.queue_learning(gap_topic)
                    except Exception:
                        pass

            # Persist self-assessment to KB
            if self.knowledge_db:
                try:
                    self.knowledge_db.add_fact(
                        f"ale_metacognition:{int(time.time())}",
                        {
                            "total_facts_assessed": total_items,
                            "overall_confidence": confidence,
                            "high_confidence": evaluation.get("high_confidence_facts", 0),
                            "medium_confidence": evaluation.get("medium_confidence_facts", 0),
                            "low_confidence": evaluation.get("low_confidence_facts", 0),
                            "unknown_topics": unknown_count,
                            "gaps_queued": poorly_understood[:3],
                            "step": "step17_metacognition",
                        },
                        tags=["ale_step17", "metacognition", "autonomous"],
                    )
                    self.knowledge_db.log_event(
                        f"Autonomous metacognition: {confidence} confidence over "
                        f"{total_items} items; {unknown_count} unknown topics"
                    )
                except Exception as exc:
                    log.debug(f"[METACOGNITION] KB store failed: {exc}")

            self.learning_history["metacognition_cycles"] = (
                self.learning_history.get("metacognition_cycles", 0) + 1
            )
            self.learning_history["last_metacognition_confidence"] = confidence

            log.info(
                f"✅ [METACOGNITION] Confidence: {confidence} | "
                f"Total items: {total_items} | Gaps queued: {len(poorly_understood[:3])}"
            )
            return (
                f"Metacognition: {confidence} overall confidence over {total_items} items; "
                f"{unknown_count} unknown topics; {len(poorly_understood[:3])} gaps queued for research"
            )

        except Exception as exc:
            log.error(f"❌ Autonomous metacognition failed: {exc}")
            return f"[Metacognition error: {exc}]"

    # ─────────────────────────────────────────────
    # STEP TIMEOUT HELPER
    # ─────────────────────────────────────────────

    def _run_step_with_timeout(self, step_name: str, step_fn) -> str:
        """Run a single ALE step in a thread pool with a timeout.

        If the step does not complete within *self.step_timeout* seconds the
        main cycle continues without waiting further. The worker thread is a
        daemon thread (inherits from the ALE background thread) and will be
        collected by the OS when the process exits. This prevents any single
        stalled network call or slow module from blocking the entire ALE cycle
        while still allowing all other steps to run on schedule.
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(step_fn)
            try:
                result = future.result(timeout=self.step_timeout)
                # ── Kernel health reporting (additive) ───────────────────────────────────
                if self.kernel:
                    try:
                        self.kernel.report_success("ALE", f"Step: {step_name}")
                    except Exception:
                        pass
                return result
            except concurrent.futures.TimeoutError:
                log.warning(
                    f"⏱️ [ALE] Step '{step_name}' timed out after {self.step_timeout}s — skipping"
                )
                return f"[{step_name} timed out after {self.step_timeout}s]"
            except Exception as exc:
                log.error(f"❌ [ALE] Step '{step_name}' raised: {exc}")
                if self.kernel:
                    try:
                        self.kernel.report_error("ALE", f"Step: {step_name}", error=str(exc))
                    except Exception:
                        pass
                return f"[{step_name} error: {exc}]"

    # ─────────────────────────────────────────────
    # INTERRUPTIBLE SLEEP HELPER
    # ─────────────────────────────────────────────

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep for *seconds* but wake up immediately if stop() is called."""
        self._stop_event.wait(timeout=seconds)

    # ─────────────────────────────────────────────
    # PUBLIC SEQUENCES (callable on-demand or from cycle)
    # ─────────────────────────────────────────────

    def run_self_learn_sequence(self) -> str:
        """
        On-demand self-learn sequence: study architecture → study commands →
        run all diagnostic commands → reflect on results.

        This is the 'structural self-learning' cycle — Niblit reads its own
        blueprint, studies what it can do, exercises each capability, and
        stores everything back into the knowledge base.
        """
        log.info("🎓 [SELF-LEARN SEQUENCE] Starting...")
        steps = []

        # 1. Architecture / structural snapshot
        sa = self._get_structural_awareness()
        if sa:
            try:
                arch = sa.component_report(self.core)
                if self.knowledge_db:
                    self.knowledge_db.add_fact(
                        f"self_learn_architecture:{int(time.time())}",
                        arch[:800],
                        tags=["self_learn", "architecture"],
                    )
                steps.append("Architecture ✅")
            except Exception as exc:
                steps.append(f"Architecture ❌ ({exc})")
        else:
            steps.append("Architecture — SA unavailable")

        # 2. Operational flow
        if sa:
            try:
                flow = sa.operational_flow()
                if self.knowledge_db:
                    self.knowledge_db.add_fact(
                        f"self_learn_flow:{int(time.time())}",
                        flow[:800],
                        tags=["self_learn", "operational_flow"],
                    )
                steps.append("Operational flow ✅")
            except Exception as exc:
                steps.append(f"Operational flow ❌ ({exc})")
        else:
            steps.append("Operational flow — SA unavailable")

        # 3. Command awareness
        awareness_result = self._autonomous_command_awareness()
        steps.append(f"Command awareness: {awareness_result[:60]}")

        # 4. Command execution
        exec_result = self._autonomous_command_execution()
        steps.append(f"Command execution: {exec_result[:60]}")

        # 5. Reflection on what was learned
        if self.reflect:
            reflection_prompt = (
                "Self-learn sequence complete. "
                f"Steps: {'; '.join(steps)}. "
                "What did Niblit learn about its own structure and commands?"
            )
            try:
                if hasattr(self.reflect, "collect_and_summarize"):
                    refl = self.reflect.collect_and_summarize(reflection_prompt)
                elif hasattr(self.reflect, "reflect"):
                    refl = self.reflect.reflect(reflection_prompt)
                else:
                    refl = reflection_prompt
                if self.knowledge_db:
                    self.knowledge_db.add_fact(
                        f"self_learn_reflection:{int(time.time())}",
                        str(refl or "")[:600],
                        tags=["self_learn", "reflection"],
                    )
                steps.append("Reflection ✅")
            except Exception as exc:
                steps.append(f"Reflection ❌ ({exc})")
        else:
            steps.append("Reflection — module unavailable")

        self.learning_history["self_learn_sequences"] = (
            self.learning_history.get("self_learn_sequences", 0) + 1
        )

        # 6. Topic seeding — grow the research frontier from what was just learned
        seed_result = self._autonomous_topic_seeding()
        steps.append(f"Topic seeding: {seed_result[:60]}")

        summary = "\n".join(f"  • {s}" for s in steps)
        log.info(f"✅ [SELF-LEARN SEQUENCE] Complete:\n{summary}")
        return f"🎓 Self-learn sequence complete:\n{summary}"

    def run_evolve_sequence(self) -> str:
        """
        Structured evolve sequence: study architecture and all commands →
        run each command to understand what it does → evolve based on findings.

        Order:
          1. Component snapshot (what modules exist)
          2. Command awareness (what commands exist + their purposes)
          3. Command execution (run each safe command, observe output)
          4. Research (pick one topic to deepen understanding)
          5. Reflection (synthesise what was learned)
          6. Evolution step (EvolveEngine acts on the new knowledge)
        """
        log.info("🧬 [EVOLVE SEQUENCE] Starting structured evolve sequence...")
        steps = []

        # 1. Structural snapshot
        sa = self._get_structural_awareness()
        if sa:
            try:
                snapshot = sa.component_report(self.core)
                if self.knowledge_db:
                    self.knowledge_db.add_fact(
                        f"evolve_seq_snapshot:{int(time.time())}",
                        snapshot[:800],
                        tags=["evolve_sequence", "snapshot"],
                    )
                steps.append("Snapshot ✅")
            except Exception as exc:
                steps.append(f"Snapshot ❌ ({exc})")
        else:
            steps.append("Snapshot — SA unavailable")

        # 2. Command awareness
        awareness_result = self._autonomous_command_awareness()
        steps.append(f"Command awareness: {awareness_result[:60]}")

        # 3. Command execution — exercise all safe commands
        exec_result = self._autonomous_command_execution()
        steps.append(f"Command execution: {exec_result[:60]}")

        # 4. Research a topic related to last findings
        research_result = self._autonomous_research()
        steps.append(f"Research: {research_result[:60]}")

        # 5. Reflection
        if self.reflect:
            prompt = (
                "Evolve sequence in progress. "
                f"Component snapshot taken. Commands studied and executed. "
                f"Recent research: {self.learning_history.get('last_research_topic', 'general')}. "
                "What self-improvements should be prioritised?"
            )
            try:
                if hasattr(self.reflect, "collect_and_summarize"):
                    refl = self.reflect.collect_and_summarize(prompt)
                elif hasattr(self.reflect, "reflect"):
                    refl = self.reflect.reflect(prompt)
                else:
                    refl = prompt
                if self.knowledge_db:
                    self.knowledge_db.add_fact(
                        f"evolve_seq_reflection:{int(time.time())}",
                        str(refl or "")[:600],
                        tags=["evolve_sequence", "reflection"],
                    )
                steps.append("Reflection ✅")
            except Exception as exc:
                steps.append(f"Reflection ❌ ({exc})")
        else:
            steps.append("Reflection — module unavailable")

        # 6. Evolution step
        evolve_result = self._autonomous_evolve_step()
        steps.append(f"Evolution: {evolve_result[:60]}")

        # 7. Topic seeding — feed new topics into ALE + SLSA + KB queue
        seed_result = self._autonomous_topic_seeding()
        steps.append(f"Topic seeding: {seed_result[:60]}")

        self.learning_history["evolve_sequences"] = (
            self.learning_history.get("evolve_sequences", 0) + 1
        )

        summary = "\n".join(f"  • {s}" for s in steps)
        log.info(f"✅ [EVOLVE SEQUENCE] Complete:\n{summary}")
        return f"🧬 Evolve sequence complete:\n{summary}"

    # ─────────────────────────────────────────────
    def _autonomous_evolve_step(self) -> str:
        if not self.evolve_engine:
            # Try to get from core
            if self.core:
                self.evolve_engine = getattr(self.core, "evolve_engine", None)
        if not self.evolve_engine:
            return "[EvolveEngine unavailable]"

        try:
            log.info("🧬 [AUTONOMOUS EVOLVE] Running evolution step...")
            record = self.evolve_engine.step()
            self.learning_history["evolve_steps"] += 1
            actions_count = len(record.get("actions", []))

            if self.knowledge_db:
                try:
                    self.knowledge_db.log_event(
                        f"Autonomous evolve step {record.get('iteration', '?')}: "
                        f"{record.get('direction', '')} ({actions_count} actions)"
                    )
                    self.knowledge_db.add_fact(
                        f"ale_evolve:{int(time.time())}",
                        {"iteration": record.get("iteration", "?"),
                         "direction": record.get("direction", ""),
                         "actions_count": actions_count,
                         "step": "step7_evolve"},
                        tags=["ale_step7", "evolve", "autonomous"],
                    )
                except Exception:
                    pass

            log.info(f"✅ [AUTONOMOUS EVOLVE] Step {record.get('iteration', '?')}: {actions_count} actions")
            return f"Evolution step {record.get('iteration', '?')}: {record.get('direction', '')} ({actions_count} actions)"

        except Exception as e:
            log.error(f"❌ Autonomous evolve step failed: {e}")
            return f"[Evolve error: {e}]"

    # ─────────────────────────────────────────────
    # SELF SCAN (step 19)
    # ─────────────────────────────────────────────

    def _autonomous_self_scan(self) -> str:
        """Step 19: BuildScanner reads Niblit's own source files for self-knowledge.

        Scans the Niblit build directory, reads a sample of Python files,
        and stores concise summaries in KnowledgeDB so subsequent reasoning
        and metacognition steps can incorporate that self-understanding.
        """
        scanner = self.build_scanner
        if not scanner:
            # Try to get scanner from core
            if self.core and hasattr(self.core, "build_scanner"):
                scanner = self.core.build_scanner

        if not scanner:
            return "[Self-scan skipped — BuildScanner not available]"

        log.info("🔍 [SELF SCAN] Scanning Niblit build directory…")

        try:
            summary = scanner.summarize()
            log.info("[SELF SCAN] %s", summary.splitlines()[0] if summary else "(empty)")

            # Read a few Python files and store their summaries
            scan_result = scanner.scan()
            if scan_result.get("error"):
                return f"[Self-scan error: {scan_result['error']}]"

            py_files = [f for f in scan_result.get("files", []) if f["ext"] == ".py"]
            # Pick up to 3 files at random to keep the cycle fast
            import random as _random
            sample = _random.sample(py_files, min(3, len(py_files))) if py_files else []

            files_read = []
            for finfo in sample:
                read_result = scanner.read_file(finfo["path"])
                if read_result.get("success"):
                    files_read.append(finfo["name"])
                    # Store a fact summarising the file
                    if self.knowledge_db:
                        try:
                            self.knowledge_db.add_fact(
                                f"ale_self_scan:{finfo['name']}:{int(time.time())}",
                                read_result["content"][:400],
                                tags=["self_scan", "source", "ale_step19"],
                            )
                        except Exception:
                            pass

            self.learning_history["self_scan_cycles"] = (
                self.learning_history.get("self_scan_cycles", 0) + 1
            )
            files_info = f", read {len(files_read)} file(s): {', '.join(files_read)}" if files_read else ""
            log.info("✅ [SELF SCAN] Completed — %d total entries%s", scan_result["total"], files_info)
            return f"Self-scan: {scan_result['total']} entries in build dir{files_info}"

        except Exception as exc:
            log.error("❌ Autonomous self-scan failed: %s", exc)
            return f"[Self-scan error: {exc}]"

    # ─────────────────────────────────────────────
    # GITHUB PUSH (step 20)
    # ─────────────────────────────────────────────

    def _autonomous_github_push(self) -> str:
        """Step 20: GitHubSync pushes autonomously-generated files to GitHub.

        Runs every cycle but only commits when there are actual changes
        (git reports nothing-to-commit otherwise).  The commit message
        includes a timestamp and the current cycle's learning highlights.
        """
        sync = self.github_sync
        if not sync:
            if self.core and hasattr(self.core, "github_sync"):
                sync = self.core.github_sync

        if not sync:
            return "[GitHub push skipped — GitHubSync not available]"

        log.info("🐙 [GITHUB PUSH] Pushing self-updates to GitHub…")

        try:
            last_topic = self.learning_history.get("last_research_topic") or "autonomous learning"
            msg = (
                f"Niblit autonomous self-update: {last_topic} "
                f"(cycle {self.learning_history.get('self_scan_cycles', 0)})"
            )
            result = sync.push(msg)
            self.learning_history["github_push_cycles"] = (
                self.learning_history.get("github_push_cycles", 0) + 1
            )
            log.info("✅ [GITHUB PUSH] %s", result.splitlines()[0])
            return result
        except Exception as exc:
            log.error("❌ Autonomous GitHub push failed: %s", exc)
            return f"[GitHub push error: {exc}]"

    # ─────────────────────────────────────────────
    # BINARY / HEX / DEX / FIRMWARE / KERNEL STUDY (step 21)
    # ─────────────────────────────────────────────

    def _autonomous_binary_study(self) -> str:
        """Step 21: Binary domain study — seeds KB with binary/hex/firmware/kernel topics.

        Workflow:
          1. If a BinaryStudier instance is available, seed its topic list into KB.
          2. If internet is available, fetch one random binary topic for deeper research.
          3. If CodeGenerator is available, generate a binary utility Python module.
        """
        internet = self._get_internet()
        code_gen = self._get_code_generator()

        # Binary study topics sampled per cycle
        binary_topics = [
            "ELF binary format sections and segments",
            "DEX Dalvik bytecode format and smali",
            "hexadecimal binary number conversions",
            "Linux kernel module init exit macros",
            "ARM Cortex-M bare-metal firmware structure",
            "BIOS UEFI boot sequence and EFI applications",
            "Android APK structure and DEX files",
            "TCP IP socket programming in C",
            "networking epoll and async I/O",
            "assembly language x86-64 calling conventions",
            "cross-compilation for embedded targets",
            "binary patching and dynamic instrumentation",
        ]

        results: List[str] = []

        # 1. Seed BinaryStudier topics into KB
        binary_studier = self.binary_studier
        if not binary_studier and self.core:
            binary_studier = getattr(self.core, "binary_studier", None)

        if binary_studier and hasattr(binary_studier, "seed_topics"):
            try:
                count = binary_studier.seed_topics()
                if count:
                    results.append(f"seeded {count} binary topics")
            except Exception as exc:
                log.debug(f"BinaryStudier.seed_topics failed: {exc}")

        # 2. Research a random binary topic via internet
        topic = random.choice(binary_topics)
        if internet:
            try:
                res = internet.search(f"{topic} tutorial guide", max_results=2)
                snippets = []
                for r in (res or []):
                    text = r.get("text", str(r)) if isinstance(r, dict) else str(r)
                    if text and len(text) > 30:
                        snippets.append(text[:300])
                if snippets and self.knowledge_db:
                    try:
                        self.knowledge_db.add_fact(
                            f"ale_binary_study:{topic.replace(' ', '_')}:{int(time.time())}",
                            "\n---\n".join(snippets[:2]),
                            tags=["binary", "study", "autonomous"],
                        )
                    except Exception:
                        pass
                results.append(f"researched '{topic}' ({len(snippets)} snippet(s))")
            except Exception as exc:
                log.debug(f"Binary internet research failed: {exc}")

        # 3. Queue the topic for further KB-based learning
        if self.knowledge_db:
            try:
                self.knowledge_db.queue_learning(topic)
            except Exception:
                pass

        # 4. Generate a binary-utility Python module
        if code_gen and hasattr(code_gen, "generate_with_validation"):
            try:
                gen_result = code_gen.generate_with_validation(
                    "binary",
                    "reader",
                    name="ale_binary_util",
                    docstring=f"Auto-generated binary utility — {topic}",
                )
                if gen_result.get("success"):
                    results.append("generated binary utility module")
                    # Queue for compilation
                    self._pending_compiled.append({
                        "language": "python",
                        "code": gen_result.get("code", ""),
                        "topic": "binary_utility",
                    })
            except Exception as exc:
                log.debug(f"Binary module generation failed: {exc}")

        # 5. Use BuildsIntegrator binary parser to inspect any .so/.dll/.bin files
        #    found in the builds directory and store format knowledge in KB.
        bi = self.builds_integrator
        if bi is None and self.core:
            bi = getattr(self.core, "builds_integrator", None)
        if bi is not None and self.knowledge_db:
            try:
                from modules.code_generator import NIBLIT_LOCAL_BUILDS_PATH
                _bin_exts = {".so", ".dll", ".bin", ".elf", ".dex", ".o"}
                for _fpath in sorted(NIBLIT_LOCAL_BUILDS_PATH.rglob("*")):
                    if _fpath.suffix.lower() in _bin_exts and _fpath.is_file():
                        try:
                            info = bi.inspect_binary(str(_fpath))
                            if info and "format" in info:
                                self.knowledge_db.add_fact(
                                    f"ale_binary_inspect:{_fpath.name}:{int(time.time())}",
                                    {
                                        "path": info.get("path", ""),
                                        "format": info.get("format", "unknown"),
                                        "size": info.get("size", 0),
                                    },
                                    tags=["binary", "builds", "format", "autonomous"],
                                )
                                results.append(f"inspected {_fpath.name} ({info.get('format')})")
                        except Exception as _e:
                            log.debug("[BINARY STUDY] Inspect %s failed: %s", _fpath.name, _e)
            except Exception as _be:
                log.debug("[BINARY STUDY] BuildsIntegrator binary scan failed: %s", _be)

        self.learning_history["binary_study_cycles"] = (
            self.learning_history.get("binary_study_cycles", 0) + 1
        )

        summary = "; ".join(results) if results else "no external resources available"
        log.info("✅ [BINARY STUDY] %s", summary)
        return f"Binary study: {summary}"

    # ─────────────────────────────────────────────
    # BUILDS UPDATE (step 22)
    # ─────────────────────────────────────────────

    def _autonomous_builds_update(self) -> str:
        """Step 22: Index the builds/ directory into KB each cycle.

        Scans every language sub-directory under the local ``builds/`` folder,
        reads recently modified files, and stores compact summaries in the
        KnowledgeDB so Niblit can reason about what programs it has built.
        When a BuildsIntegrator is available the file content is also
        NLP-processed so keywords and bigrams are stored as additional KB facts
        for richer reasoning and topic seeding.
        """
        try:
            from modules.code_generator import NIBLIT_LOCAL_BUILDS_PATH
        except Exception:
            return "[Builds update skipped — NIBLIT_LOCAL_BUILDS_PATH unavailable]"

        if not NIBLIT_LOCAL_BUILDS_PATH.exists():
            return "[Builds update skipped — builds/ directory not found]"

        # Resolve BuildsIntegrator (injected or from core)
        bi = self.builds_integrator
        if bi is None and self.core:
            bi = getattr(self.core, "builds_integrator", None)

        indexed: List[str] = []
        try:
            for lang_dir in sorted(NIBLIT_LOCAL_BUILDS_PATH.iterdir()):
                if not lang_dir.is_dir():
                    continue
                for fpath in sorted(lang_dir.iterdir()):
                    if fpath.name.startswith("."):
                        continue
                    if not fpath.is_file():
                        continue
                    try:
                        snippet = fpath.read_text(encoding="utf-8", errors="replace")[:300]
                    except OSError:
                        continue
                    if self.knowledge_db:
                        try:
                            self.knowledge_db.add_fact(
                                f"ale_builds:{lang_dir.name}:{fpath.stem}:{int(time.time())}",
                                snippet,
                                tags=["builds", "autonomous", lang_dir.name],
                            )
                        except Exception:
                            pass

                    # NLP enrichment — extract keywords and bigrams for richer KB facts
                    if bi is not None and self.knowledge_db:
                        try:
                            enriched = bi.enrich_content(snippet, topic=fpath.stem)
                            keywords = enriched.get("keywords", [])
                            bigrams = enriched.get("bigrams", [])
                            if keywords:
                                self.knowledge_db.add_fact(
                                    f"ale_builds_nlp:{lang_dir.name}:{fpath.stem}",
                                    {
                                        "keywords": keywords,
                                        "bigrams": bigrams[:5],
                                        "token_count": enriched.get("token_count", 0),
                                        "file": fpath.name,
                                        "lang": lang_dir.name,
                                    },
                                    tags=["builds", "keywords", "nlp", lang_dir.name],
                                )
                        except Exception as _nlp_exc:
                            log.debug("[BUILDS UPDATE] NLP enrichment failed for %s: %s",
                                      fpath.name, _nlp_exc)

                    indexed.append(f"{lang_dir.name}/{fpath.name}")
        except Exception as exc:
            log.debug("[BUILDS UPDATE] Scan failed: %s", exc)

        self.learning_history["builds_update_cycles"] = (
            self.learning_history.get("builds_update_cycles", 0) + 1
        )
        count = len(indexed)
        nlp_note = " (NLP-enriched)" if bi is not None else ""
        log.info("✅ [BUILDS UPDATE] Indexed %d file(s) from builds/%s", count, nlp_note)
        return f"Builds update: indexed {count} file(s) from builds/{nlp_note}"

    # ─────────────────────────────────────────────
    # EVOLVE DEPLOY (step 23)
    # ─────────────────────────────────────────────

    def _autonomous_evolve_deploy(self) -> str:
        """Step 23: Read, understand, and hot-reload evolution improvements.

        Scans the ``evolved/`` directory (inside the deploy path or the repo
        root), reads ``improvement_*.py`` files, stores their content as
        self-knowledge in the KB, and attempts to apply them via LiveUpdater
        so improvements take effect in the current running process.
        """
        # Locate the evolved/ directory: prefer deploy path, fall back to repo root
        evolved_dir = None

        if self.evolve_engine:
            dp = getattr(self.evolve_engine, "deploy_path", None)
            if dp:
                candidate = Path(dp) / "evolved"
                if candidate.exists():
                    evolved_dir = candidate

        if evolved_dir is None:
            try:
                from modules.code_generator import NIBLIT_LOCAL_BUILDS_PATH
                repo_root = NIBLIT_LOCAL_BUILDS_PATH.parent
                candidate = repo_root / "evolved"
                if candidate.exists():
                    evolved_dir = candidate
            except Exception:
                pass

        if evolved_dir is None:
            return "[Evolve deploy skipped — no evolved/ directory found]"

        # Resolve live_updater
        live_updater = getattr(self, "live_updater", None) or (
            getattr(self.core, "live_updater", None) if self.core else None
        )

        deployed: List[str] = []
        understood: List[str] = []
        # Track unique improvement directions for topic seeding
        directions: List[str] = []

        try:
            for step_dir in sorted(evolved_dir.iterdir()):
                if not step_dir.is_dir():
                    continue
                for fpath in sorted(step_dir.glob("improvement_*.py")):
                    try:
                        content = fpath.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue

                    # Extract metadata from the evolved stub header (Direction / Timestamp)
                    direction = ""
                    timestamp = ""
                    step_num = ""
                    for line in content.splitlines()[:8]:
                        line = line.strip()
                        if line.startswith("# Direction:"):
                            direction = line[len("# Direction:"):].strip()
                        elif line.startswith("# Timestamp:"):
                            timestamp = line[len("# Timestamp:"):].strip()
                        elif line.startswith("# Auto-generated by EvolveEngine step"):
                            step_num = line.split("step")[-1].strip()

                    # Store richer fact including extracted metadata
                    if self.knowledge_db:
                        try:
                            self.knowledge_db.add_fact(
                                f"ale_evolve_deploy:{step_dir.name}:{fpath.stem}:{int(time.time())}",
                                {
                                    "content": content[:400],
                                    "direction": direction,
                                    "timestamp": timestamp,
                                    "step": step_num,
                                    "file": fpath.name,
                                    "dir": step_dir.name,
                                },
                                tags=["evolve", "deploy", "improvement", "autonomous"],
                            )
                        except Exception:
                            pass

                    if direction:
                        directions.append(direction)
                        # Queue each improvement direction as a research topic
                        if self.knowledge_db:
                            try:
                                self.knowledge_db.queue_learning(direction)
                            except Exception:
                                pass

                    understood.append(fpath.name)

                    # Attempt hot-reload via apply_patch
                    if live_updater and hasattr(live_updater, "apply_patch"):
                        module_key = f"evolved.{step_dir.name}.{fpath.stem}"
                        try:
                            result = live_updater.apply_patch(module_key, content)
                            if result.get("success"):
                                deployed.append(fpath.name)
                                log.info("[EVOLVE DEPLOY] Applied patch: %s", fpath.name)
                        except Exception as exc:
                            log.debug("[EVOLVE DEPLOY] apply_patch failed for %s: %s", fpath.name, exc)
        except Exception as exc:
            log.debug("[EVOLVE DEPLOY] Directory scan failed: %s", exc)

        # Store catalog of all unique improvement directions as a single KB fact
        unique_dirs = list(dict.fromkeys(directions))  # deduped, order-preserving
        if unique_dirs and self.knowledge_db:
            try:
                self.knowledge_db.add_fact(
                    f"ale_evolve_directions:{int(time.time())}",
                    {"directions": unique_dirs, "total": len(unique_dirs)},
                    tags=["evolve", "directions", "catalog", "autonomous"],
                )
            except Exception:
                pass

        self.learning_history["evolve_deploy_cycles"] = (
            self.learning_history.get("evolve_deploy_cycles", 0) + 1
        )

        summary = (
            f"read {len(understood)} improvement(s)"
            + (f", {len(unique_dirs)} unique direction(s)" if unique_dirs else "")
            + (f", deployed {len(deployed)}" if deployed else "")
        )
        log.info("✅ [EVOLVE DEPLOY] %s", summary)
        return f"Evolve deploy: {summary}"

    # ─────────────────────────────────────────────
    # BRAIN TRAINING (step 24)
    # ─────────────────────────────────────────────

    def _autonomous_brain_training(self) -> str:
        """
        Step 24: Autonomous brain trainer — fine-tune brain on research data.

        - Wires the current KnowledgeDB and optional SelfTeacher into the BrainTrainer.
        - Feeds recent autonomous research results into the BrainTrainer as fresh facts.
        - Activates full self-teaching and knowledge ingestion pipeline.
        - Increments training cycle count.
        - Returns a training summary string for metrics/history.
        """
        if not self.brain_trainer:
            return "BrainTraining: no brain_trainer available"

        try:
            # Sync knowledge_db if not already set
            if self.knowledge_db and not self.brain_trainer.knowledge_db:
                self.brain_trainer.knowledge_db = self.knowledge_db

            # Also wire the latest SelfTeacher, if present
            if hasattr(self, "self_teacher") and not getattr(self.brain_trainer, "self_teacher", None):
                self.brain_trainer.self_teacher = self.self_teacher

            # Feed in recent research results from last ALE research step
            last_results = getattr(self, "_last_research_results", None)
            if last_results:
                if isinstance(last_results, list):
                    for item in last_results[:20]:
                        topic = str(item.get("topic", "research")) if isinstance(item, dict) else "research"
                        text = str(item.get("content", item)) if isinstance(item, dict) else str(item)
                        self.brain_trainer.ingest_research(topic, text)
                elif isinstance(last_results, str):
                    self.brain_trainer.ingest_research("research", last_results[:600])

            # Run the main (self-teaching + ingestion) training cycle
            summary = self.brain_trainer.run_training_cycle()

            self.learning_history["brain_training_cycles"] = (
                self.learning_history.get("brain_training_cycles", 0) + 1
            )
            log.info("[ALE] Autonomous brain training cycle complete.")
            return summary

        except Exception as exc:
            log.debug("[BRAIN TRAINING] step failed: %s", exc)
            return f"BrainTraining: error — {exc}"

    # ─────────────────────────────────────────────
    # COGNITIVE ENHANCEMENT (step 25)
    # ─────────────────────────────────────────────

    # Cognitive domains researched and continuously updated in the brain
    _COGNITIVE_DOMAINS = [
        "language",
        "communication",
        "reasoning",
        "calculating",
        "chat_completions",
        "responses",
    ]

    # Detailed research queries for each cognitive domain
    _COGNITIVE_QUERIES = {
        "language": [
            "natural language understanding grammar syntax semantics",
            "language model tokenization vocabulary techniques",
            "multilingual translation and language detection",
            "linguistic pragmatics and discourse analysis",
        ],
        "communication": [
            "effective conversational AI communication patterns",
            "human computer interaction dialogue design",
            "active listening and empathetic response generation",
            "tone style and register in AI communication",
        ],
        "reasoning": [
            "logical deductive inductive reasoning AI",
            "chain-of-thought reasoning in language models",
            "causal and counterfactual reasoning techniques",
            "common sense reasoning and world knowledge",
        ],
        "calculating": [
            "numerical reasoning and arithmetic problem solving AI",
            "mathematical expression parsing and evaluation",
            "algebra calculus symbolic computation",
            "probabilistic and statistical reasoning",
        ],
        "chat_completions": [
            "chat completion API best practices and prompt design",
            "context window management in LLM conversations",
            "system prompt design for AI assistants",
            "retrieval augmented generation for chat",
        ],
        "responses": [
            "LLM response quality coherence and factual accuracy",
            "response formatting structured output generation",
            "hallucination reduction in AI responses",
            "instruction following and alignment in AI responses",
        ],
    }

    def _autonomous_cognitive_enhancement(self) -> str:
        """Step 25: Cognitive enhancement — research language, communication,
        reasoning, calculating, chat completions, and responses, then register
        the findings live in both KnowledgeDB and BrainTrainer.

        This step ensures that Niblit continuously improves its core cognitive
        capabilities during every autonomous cycle, with all learned data
        persisted to storage immediately.
        """
        updated_domains = []
        errors = []

        for domain in self._COGNITIVE_DOMAINS:
            try:
                queries = self._COGNITIVE_QUERIES.get(domain, [domain])
                query = random.choice(queries)

                # ── Fetch data via internet if available ──────────────────
                research_text = ""
                if self.internet:
                    try:
                        result = self.internet.search(query)
                        if isinstance(result, list):
                            research_text = " ".join(str(r) for r in result[:3])[:800]
                        elif isinstance(result, str):
                            research_text = result[:800]
                    except Exception as _e:
                        log.debug("[COGNITIVE] internet search failed for %s: %s", domain, _e)

                # ── Fallback: use researcher if available ─────────────────
                if not research_text and self.researcher:
                    try:
                        result = self.researcher.search(query)
                        if isinstance(result, list):
                            research_text = " ".join(str(r) for r in result[:3])[:800]
                        elif isinstance(result, str):
                            research_text = result[:800]
                    except Exception as _e:
                        log.debug("[COGNITIVE] researcher failed for %s: %s", domain, _e)

                # ── Always generate a minimal structural entry ────────────
                if not research_text:
                    research_text = (
                        f"Core cognitive domain: {domain}. "
                        f"Research query: {query}. "
                        f"This domain covers the ability to {domain.replace('_', ' ')} "
                        f"effectively in AI-driven conversational systems."
                    )

                ts = int(time.time())

                # ── Persist to KnowledgeDB immediately ───────────────────
                if self.knowledge_db:
                    try:
                        fact_key = f"cognitive:{domain}:{ts}"
                        self.knowledge_db.add_fact(
                            fact_key,
                            research_text,
                            tags=["cognitive", domain, "brain_core", "ale_learned"],
                        )
                    except Exception as _e:
                        log.debug("[COGNITIVE] KB store failed for %s: %s", domain, _e)

                # ── Feed into BrainTrainer immediately ────────────────────
                if self.brain_trainer:
                    try:
                        self.brain_trainer.update_cognitive_domain(domain, research_text)
                    except Exception as _e:
                        log.debug("[COGNITIVE] BrainTrainer update failed for %s: %s", domain, _e)

                updated_domains.append(domain)
                log.info("[COGNITIVE] ✅ Updated domain: %s", domain)

            except Exception as exc:
                errors.append(f"{domain}:{exc}")
                log.debug("[COGNITIVE] domain update failed %s: %s", domain, exc)

        self.learning_history["cognitive_enhancement_cycles"] = (
            self.learning_history.get("cognitive_enhancement_cycles", 0) + 1
        )

        summary = (
            f"CognitiveEnhancement: updated {len(updated_domains)}/{len(self._COGNITIVE_DOMAINS)} domains"
            + (f" (errors: {len(errors)})" if errors else "")
        )
        log.info("✅ [COGNITIVE] %s", summary)
        return summary

    # ─────────────────────────────────────────────
    # GITHUB CODE DISCOVERY (step 26)
    # Code pattern discovery · training datasets · automated refactoring
    # ─────────────────────────────────────────────

    # Rotate through these (language, pattern_type) pairs for pattern discovery
    _GCS_PATTERN_TOPICS: List[Tuple[str, str]] = [
        ("python",     "decorator"),
        ("python",     "context_manager"),
        ("python",     "async"),
        ("python",     "error_handling"),
        ("python",     "type_hints"),
        ("python",     "generator"),
        ("python",     "dataclass"),
        ("javascript", "async"),
        ("javascript", "error_handling"),
        ("typescript", "type_hints"),
        ("go",         "error_handling"),
        ("rust",       "error_handling"),
    ]

    # Training dataset topics to cycle through
    _GCS_DATASET_TOPICS: List[str] = [
        "nlp text classification",
        "code generation pairs",
        "question answering",
        "sentiment analysis",
        "named entity recognition",
        "machine translation",
        "conversational ai dialogue",
    ]

    # (language, technique) pairs for refactoring discovery
    _GCS_REFACTOR_TOPICS: List[Tuple[str, str]] = [
        ("python", "list_comprehension"),
        ("python", "dict_comprehension"),
        ("python", "fstring"),
        ("python", "pathlib"),
        ("python", "type_annotations"),
        ("python", "dataclass_migration"),
        ("python", "async_migration"),
        ("python", "exception_chaining"),
    ]

    def _autonomous_github_code_discovery(self) -> str:
        """Step 26: GitHub Code Search — patterns, training data, refactoring.

        On each cycle one sub-task from each of the three categories is run:

        * **Code pattern discovery** — finds idiomatic real-world patterns for a
          language/pattern-type pair and stores them under
          ``ale_github_pattern:{lang}:{pattern_type}:`` KB keys.  The ALE
          code-generation step picks these up in the next cycle so generated
          code uses idioms from high-quality open-source repos.

        * **Training datasets** — locates annotated dataset files and starred
          dataset repos; stored under ``ale_github_dataset:{topic}:`` keys so
          the brain-trainer and self-teacher can extend their training corpora.

        * **Automated refactoring** — discovers best-practice rewrites (e.g.
          f-string migration, list comprehension, type annotation) stored under
          ``ale_github_refactor:{lang}:{technique}:`` keys so the code-reflection
          step can improve generated code quality.
        """
        gcs = self._get_github_code_search()
        if not gcs:
            return "[GitHub code discovery skipped — GitHubCodeSearch not available]"

        collected: List[str] = []
        errors: List[str] = []
        ts = int(time.time())

        # ── 1. Code pattern discovery ─────────────────────────────────────
        try:
            pattern_topics = self._GCS_PATTERN_TOPICS
            lang, pattern_type = pattern_topics[
                ts % len(pattern_topics)
            ]
            pattern_results = gcs.discover_patterns(lang, pattern_type, max_results=4)
            stored_count = 0
            for r in pattern_results:
                text = r.get("text", "")
                if text and len(text) > 20:
                    if self.knowledge_db:
                        try:
                            self.knowledge_db.add_fact(
                                f"ale_github_pattern:{lang}:{pattern_type}:{ts}",
                                text[:500],
                                tags=["github", "pattern", lang, pattern_type, "ale_step26"],
                            )
                            stored_count += 1
                        except Exception:
                            pass
            if pattern_results:
                collected.append(f"patterns:{lang}/{pattern_type}({stored_count})")
                log.info("[GH DISCOVERY] Patterns %s/%s: %d results", lang, pattern_type, len(pattern_results))
        except Exception as exc:
            errors.append(f"pattern:{exc}")
            log.debug("[GH DISCOVERY] Pattern discovery failed: %s", exc)

        # ── 2. Training dataset discovery ─────────────────────────────────
        try:
            dataset_topics = self._GCS_DATASET_TOPICS
            dataset_topic = dataset_topics[ts % len(dataset_topics)]
            dataset_results = gcs.find_training_data(dataset_topic, max_results=4)
            stored_ds = 0
            for r in dataset_results:
                text = r.get("text", "")
                if text and len(text) > 20:
                    if self.knowledge_db:
                        try:
                            self.knowledge_db.add_fact(
                                f"ale_github_dataset:{dataset_topic}:{ts}",
                                text[:500],
                                tags=["github", "dataset", "training", "ale_step26"],
                            )
                            stored_ds += 1
                        except Exception:
                            pass
                    # Feed richer training corpora into the brain trainer
                    if self.brain_trainer:
                        try:
                            self.brain_trainer.ingest_research(text[:300])
                        except Exception:
                            pass
            if dataset_results:
                collected.append(f"datasets:{dataset_topic}({stored_ds})")
                log.info("[GH DISCOVERY] Datasets %r: %d results", dataset_topic, len(dataset_results))
        except Exception as exc:
            errors.append(f"dataset:{exc}")
            log.debug("[GH DISCOVERY] Dataset discovery failed: %s", exc)

        # ── 3. Refactoring pattern discovery ──────────────────────────────
        try:
            refactor_topics = self._GCS_REFACTOR_TOPICS
            r_lang, technique = refactor_topics[ts % len(refactor_topics)]
            refactor_results = gcs.find_refactoring_patterns(r_lang, technique, max_results=4)
            stored_rf = 0
            for r in refactor_results:
                text = r.get("text", "")
                if text and len(text) > 20:
                    if self.knowledge_db:
                        try:
                            self.knowledge_db.add_fact(
                                f"ale_github_refactor:{r_lang}:{technique}:{ts}",
                                text[:500],
                                tags=["github", "refactor", r_lang, technique, "ale_step26"],
                            )
                            stored_rf += 1
                        except Exception:
                            pass
            if refactor_results:
                collected.append(f"refactor:{r_lang}/{technique}({stored_rf})")
                log.info("[GH DISCOVERY] Refactor %s/%s: %d results", r_lang, technique, len(refactor_results))
        except Exception as exc:
            errors.append(f"refactor:{exc}")
            log.debug("[GH DISCOVERY] Refactoring discovery failed: %s", exc)

        self.learning_history["github_code_discovery_cycles"] = (
            self.learning_history.get("github_code_discovery_cycles", 0) + 1
        )

        if not collected:
            return "[GitHub code discovery — no results this cycle]"

        summary = "GitHubCodeDiscovery: " + ", ".join(collected)
        if errors:
            summary += f" (errors: {len(errors)})"
        log.info("✅ [GH DISCOVERY] %s", summary)
        return summary

    # ── SEARCHCODE DISCOVERY (step 28) ────────────────────────────────────────

    # Topics for searchcode pattern discovery — (language, pattern_type) pairs
    _SC_PATTERN_TOPICS = [
        ("python", "decorator"),
        ("python", "context_manager"),
        ("python", "async"),
        ("python", "error_handling"),
        ("python", "type_hints"),
        ("python", "generator"),
        ("javascript", "async"),
        ("javascript", "factory"),
        ("java", "singleton"),
        ("go", "error_handling"),
        ("rust", "error_handling"),
    ]

    def _autonomous_searchcode_discovery(self) -> str:
        """Step 28: Searchcode.com — code-pattern discovery via REST API and/or MCP.

        Queries the searchcode.com public code-search index (which covers
        GitHub, Bitbucket, GitLab, Google Code and more) for idiomatic language
        patterns.  Results are stored in the knowledge base under
        ``ale_searchcode:{lang}:{pattern_type}:{ts}`` keys, making them
        available to the code-generation and code-reflection steps in the next
        cycle.

        The searchcode MCP endpoint (``https://api.searchcode.com/v1/mcp``)
        is tried first; the public REST API is used as a fallback so the step
        works even in offline/restricted environments.
        """
        sc = self._get_searchcode_search()
        if not sc:
            return "[Searchcode discovery skipped — SearchcodeSearch not available]"

        collected: List[str] = []
        errors: List[str] = []
        ts = int(time.time())
        _sc_results_for_semantic: List[dict] = []
        _sc_lang = ""
        _sc_pattern_type = ""

        try:
            pattern_topics = self._SC_PATTERN_TOPICS
            lang, pattern_type = pattern_topics[ts % len(pattern_topics)]
            _sc_lang = lang
            _sc_pattern_type = pattern_type
            results = sc.discover_patterns(lang, pattern_type, max_results=4)
            _sc_results_for_semantic = results or []
            stored = 0
            for r in results:
                text = r.get("text", "")
                if text and len(text) > 20:
                    if self.knowledge_db:
                        try:
                            self.knowledge_db.add_fact(
                                f"ale_searchcode:{lang}:{pattern_type}:{ts}",
                                text[:500],
                                tags=["searchcode", "pattern", lang, pattern_type, "ale_step28"],
                            )
                            stored += 1
                        except Exception:
                            pass
            if stored:
                collected.append(f"patterns:{lang}/{pattern_type}({stored})")
            log.info("[SC DISCOVERY] Patterns %s/%s: %d stored", lang, pattern_type, stored)
        except Exception as exc:
            errors.append(f"patterns:{exc}")
            log.debug("[SC DISCOVERY] Pattern discovery failed: %s", exc)

        self.learning_history["searchcode_discovery_cycles"] = (
            self.learning_history.get("searchcode_discovery_cycles", 0) + 1
        )

        # ── Semantic storage ─────────────────────────────────────────────────
        sa = self._get_semantic_agent()
        if sa and _sc_results_for_semantic and _sc_lang:
            try:
                for item in _sc_results_for_semantic:
                    text = item.get("text", "") if isinstance(item, dict) else str(item)
                    if text and len(text) > 20:
                        sa.store_knowledge(
                            [{"snippet": text[:500]}],
                            source="ale_searchcode",
                            query=f"{_sc_lang} {_sc_pattern_type}",
                        )
            except Exception as _se:
                log.debug("[SC DISCOVERY] SemanticAgent store failed: %s", _se)

        if not collected:
            return "[Searchcode discovery — no results this cycle]"

        summary = "SearchcodeDiscovery: " + ", ".join(collected)
        if errors:
            summary += f" (errors: {len(errors)})"
        log.info("✅ [SC DISCOVERY] %s", summary)
        return summary

    # ─────────────────────────────────────────────
    # BUILDS INTEGRATION (step 29)
    # ─────────────────────────────────────────────

    def _autonomous_builds_integration(self) -> str:
        """Step 29: Run all available builds/python scripts and ingest their output.

        Uses the BuildsIntegrator to:
        1. Execute each compiled builds script's ``.run()`` statistics method
           and store the results as self-knowledge facts in the KB.
        2. Apply the NLP processor to the current cycle topic so keyword and
           bigram metadata is stored alongside the regular research facts.
        3. Optionally load the repo's ``events.jsonl`` via the data-structures
           module so JSONL event records flow into FusedMemory for richer
           vector retrieval.
        """
        bi = self.builds_integrator
        if bi is None and self.core:
            bi = getattr(self.core, "builds_integrator", None)

        if bi is None:
            return "[BuildsIntegration skipped — BuildsIntegrator not available]"

        results: List[str] = []

        # 1. Run all builds scripts and store their status facts
        try:
            run_results = bi.run_all()
            if run_results and self.knowledge_db:
                try:
                    self.knowledge_db.add_fact(
                        f"ale_builds_run:{int(time.time())}",
                        run_results,
                        tags=["builds", "run", "status", "autonomous"],
                    )
                    results.append(f"ran {len(run_results)} script(s)")
                except Exception:
                    pass
        except Exception as exc:
            log.debug("[BUILDS INTEGRATION] run_all failed: %s", exc)

        # 2. NLP-process the current cycle topic to generate keyword enrichment
        topic = self._current_cycle_topic or ""
        if topic and self.knowledge_db:
            try:
                enriched = bi.enrich_content(topic, topic=topic)
                keywords = enriched.get("keywords", [])
                if keywords:
                    self.knowledge_db.add_fact(
                        f"ale_builds_nlp_topic:{topic.replace(' ', '_')}:{int(time.time())}",
                        {
                            "topic": topic,
                            "keywords": keywords,
                            "bigrams": enriched.get("bigrams", [])[:5],
                        },
                        tags=["builds", "nlp", "topic", "keywords", "autonomous"],
                    )
                    results.append(f"NLP enriched topic '{topic[:40]}' ({len(keywords)} kw)")
                    # Seed the extracted keywords as new research topics
                    for kw in keywords[:3]:
                        if len(kw) > 3 and kw not in self.research_topics:
                            self.research_topics.append(kw)
            except Exception as exc:
                log.debug("[BUILDS INTEGRATION] NLP topic enrichment failed: %s", exc)

        # 3. Process any recent KB research results through the NLP pipeline
        if self._last_research_results and self.knowledge_db:
            try:
                combined = " ".join(
                    str(r)[:200] for r in self._last_research_results[:5] if r
                )
                if combined:
                    enriched = bi.enrich_content(combined, topic=topic)
                    keywords = enriched.get("keywords", [])
                    if keywords:
                        self.knowledge_db.add_fact(
                            f"ale_builds_nlp_research:{int(time.time())}",
                            {"keywords": keywords, "topic": topic},
                            tags=["builds", "nlp", "research", "keywords"],
                        )
                        results.append(f"NLP-enriched research ({len(keywords)} keywords)")
            except Exception as exc:
                log.debug("[BUILDS INTEGRATION] NLP research enrichment failed: %s", exc)

        # 4. Load events.jsonl into fused memory via data-structures module
        try:
            from modules.code_generator import NIBLIT_LOCAL_BUILDS_PATH
            events_path = NIBLIT_LOCAL_BUILDS_PATH.parent / "events.jsonl"
            if events_path.exists():
                count = bi.load_jsonl(str(events_path))
                if count:
                    results.append(f"loaded {count} event record(s) via data-structures")
        except Exception as exc:
            log.debug("[BUILDS INTEGRATION] events.jsonl load failed: %s", exc)

        self.learning_history["builds_integration_cycles"] = (
            self.learning_history.get("builds_integration_cycles", 0) + 1
        )

        summary = "; ".join(results) if results else "no actionable builds outputs"
        log.info("✅ [BUILDS INTEGRATION] %s", summary)
        return f"BuildsIntegration: {summary}"

    def _run_autonomous_cycle(self):
        """Execute one complete autonomous learning cycle (29 steps).

        Design principles
        -----------------
        * ONE TOPIC PER CYCLE: a single topic is selected at the start of each
          cycle via _select_next_topic() and pinned to self._current_cycle_topic.
          The topic is run through TopicConstructor so it is always safe for
          search APIs (no 403 errors or timeouts from overly long queries).
        * Step 1 is now ONE unified research step (``UnifiedResearch``) that
          fans out to ALL available research backends simultaneously:
          Serpex, SelfResearcher, SearchcodeSearch, GitHubCodeSearch, and
          SemanticAgent/Qdrant.  This replaces the former separate
          SerpexResearch (step 27) + Research (step 1) pair.
        * After the unified research a single 60-second ``_RESEARCH_INGEST_WAIT``
          pause lets the full ingestion → vector-embedding → KB-store pipeline
          settle before the next query begins — one new query per minute.
        * Every step is wrapped in _run_step_with_timeout (default 120 s) so a
          stalled network call can never freeze the whole cycle.
        * A 3-second interruptible sleep between all other steps gives the OS
          time to process network I/O between calls, reducing contention.
        * Steps proceed sequentially: 1 → 2 → 3 → … → 27, just like counting.
        * Step 18 (ImprovementCycle) is throttled to every 3 cycles.
        * Step 20 (GitHubPush) is throttled to every 5 cycles.
        * stop() wakes the engine from any inter-step sleep immediately.

        Cycle sequence
        --------------
        Step  1: UnifiedResearch      — all backends, ONE topic, 60 s ingest wait
        Step  2: Ideas                — SelfIdeaImplementation / IdeaGenerator
        Step  3: Learning             — SelfTeacher internalises results
        Step  4: Implementation       — SelfImplementer executes enqueued plans
        Step  5: Reflection           — ReflectModule summarises + stores
        Step  6: SLSA                 — SLSA knowledge artifact generation
        Step  7: Evolve               — EvolveEngine self-evolves
        Step  8: CodeResearch         — Searchcode + GitHub + researcher → CodeGenerator
        Step  9: CodeGeneration       — idea + implementer produce compilable code
        Step 10: CodeCompilation      — CodeCompiler runs the generated code
        Step 11: CodeReflection       — ReflectModule studies compiled output (30 s wait)
        Step 12: SoftwareStudy        — SoftwareStudier learns patterns
        Step 13: CommandAwareness     — catalogue all commands into KB
        Step 14: CommandExecution     — exercise safe diagnostic commands
        Step 15: TopicSeeding         — derive + enqueue new research topics
        Step 16: Reasoning            — ReasoningEngine builds knowledge graph
        Step 17: Metacognition        — evaluate self-knowledge, identify gaps
        Step 18: ImprovementCycle     — 10-module improvement (throttled: every 3)
        Step 19: SelfScan             — BuildScanner reads own source files
        Step 20: GitHubPush           — push generated files (throttled: every 5)
        Step 21: BinaryStudy          — seed KB with binary/hex/firmware topics
        Step 22: BuildsUpdate         — index builds/ directory
        Step 23: EvolveDeploy         — hot-reload evolved improvements
        Step 24: BrainTraining        — fine-tune on research data
        Step 25: CognitiveEnhancement — research language/reasoning/chat quality
        Step 26: GitHubCodeDiscovery  — pattern discovery, datasets, refactoring
        Step 27: SearchcodeDiscovery  — searchcode.com code-pattern index
        """
        self._cycle_count += 1
        cycle = self._cycle_count

        # ── Pin the research topic for this entire cycle ───────────────────
        self._current_cycle_topic = self._select_next_topic()
        log.info("=" * 70)
        log.info("🔄 [AUTONOMOUS CYCLE #%d] Topic: %r", cycle, self._current_cycle_topic)
        log.info("=" * 70)

        results = []

        def _step(name: str, fn) -> None:
            if not self.running:
                return
            result = self._run_step_with_timeout(name, fn)
            results.append((name, result))
            self._interruptible_sleep(self._INTER_STEP_SLEEP)

        def _research_step(name: str, fn) -> None:
            """Like _step but adds the ingestion-wait after the research completes."""
            if not self.running:
                return
            result = self._run_step_with_timeout(name, fn)
            results.append((name, result))
            self._interruptible_sleep(self._INTER_STEP_SLEEP)
            if self._RESEARCH_INGEST_WAIT > 0 and self.running:
                log.info(
                    "⏳ [%s] Waiting %.0fs for ingestion pipeline to settle "
                    "(new query in ~%.0fs)...",
                    name, self._RESEARCH_INGEST_WAIT, self._RESEARCH_INGEST_WAIT,
                )
                self._interruptible_sleep(self._RESEARCH_INGEST_WAIT)

        # ── Step 1: Unified research — ONE call, ALL backends, ONE topic ───
        # Replaces former Step 27 (SerpexResearch) + Step 1 (Research).
        # A 60-second ingest wait ensures data is fully written before cycle
        # continues — exactly one new research query per minute.
        _research_step("UnifiedResearch", self._unified_research)

        # ── Steps 2-7: Core learning loop ─────────────────────────────────
        _step("Ideas",          self._autonomous_idea_generation)
        _step("Learning",       self._autonomous_learning)
        _step("Implementation", self._autonomous_implementation)
        _step("Reflection",     self._autonomous_reflection)
        _step("SLSA",           self._autonomous_slsa_run)
        _step("Evolve",         self._autonomous_evolve_step)

        # ── Steps 8-12: Programming-literacy loop ──────────────────────────
        _step("CodeResearch",    self._autonomous_code_research)
        _step("CodeGeneration",  self._autonomous_code_generation)
        _step("CodeCompilation", self._autonomous_code_compilation)
        _research_step("CodeReflection",  self._autonomous_code_reflection)
        _step("SoftwareStudy",   self._autonomous_software_study)

        # ── Steps 13-14: Structural self-awareness ─────────────────────────
        _step("CommandAwareness", self._autonomous_command_awareness)
        _step("CommandExecution", self._autonomous_command_execution)

        # ── Step 15: Topic seeding ─────────────────────────────────────────
        _step("TopicSeeding", self._autonomous_topic_seeding)

        # ── Step 16: Intelligent reasoning ────────────────────────────────
        _step("Reasoning", self._autonomous_reasoning)

        # ── Step 17: Metacognition ─────────────────────────────────────────
        _step("Metacognition", self._autonomous_metacognition)

        # ── Step 18: ImprovementCycle — throttled every 3 cycles ──────────
        if cycle % self._IMPROVEMENT_CYCLE_EVERY == 0:
            _step("ImprovementCycle", self._autonomous_improvement_cycle)
        else:
            log.debug("[AUTONOMOUS CYCLE] ImprovementCycle skipped (cycle %d/%d)", cycle, self._IMPROVEMENT_CYCLE_EVERY)

        # ── Step 19: Self-scan ────────────────────────────────────────────
        _step("SelfScan", self._autonomous_self_scan)

        # ── Step 20: GitHub push — throttled every 5 cycles ───────────────
        if cycle % self._GITHUB_PUSH_EVERY == 0:
            _step("GitHubPush", self._autonomous_github_push)
        else:
            log.debug("[AUTONOMOUS CYCLE] GitHubPush skipped (cycle %d/%d)", cycle, self._GITHUB_PUSH_EVERY)

        # ── Step 21: Binary study ─────────────────────────────────────────
        _step("BinaryStudy", self._autonomous_binary_study)

        # ── Step 22: Builds update ────────────────────────────────────────
        _step("BuildsUpdate", self._autonomous_builds_update)

        # ── Step 23: Evolve deploy ────────────────────────────────────────
        _step("EvolveDeploy", self._autonomous_evolve_deploy)

        # ── Step 24: Brain training ───────────────────────────────────────
        _step("BrainTraining", self._autonomous_brain_training)

        # ── Step 25: Cognitive enhancement ───────────────────────────────
        _step("CognitiveEnhancement", self._autonomous_cognitive_enhancement)

        # ── Step 26: GitHub Code Discovery ───────────────────────────────
        _step("GitHubCodeDiscovery", self._autonomous_github_code_discovery)

        # ── Step 27: Searchcode Discovery ────────────────────────────────
        _step("SearchcodeDiscovery", self._autonomous_searchcode_discovery)

        # ── ScrapyResearch: direct DuckDuckGo research via ScrapyResearchAgent ──
        _step("ScrapyResearch", self._autonomous_scrapy_research)

        # ── Step 29: Builds Integration ───────────────────────────────────
        _step("BuildsIntegration", self._autonomous_builds_integration)

        # ── Step 30: Self-agent task generation (additive) ───────────────────
        # Every N cycles, submit a self-improvement plan to the Phase-2 agent
        # architecture so the system continuously enhances itself.  Runs in the
        # background (non-blocking) — tasks are dispatched by the RuntimeManager.
        if cycle % self._SELF_IMPROVE_CYCLE_EVERY == 0:
            try:
                self.self_improve_via_agents()
            except Exception as _sie:
                log.debug("[ALE] self_improve_via_agents error: %s", _sie)

        # ── Log cycle summary ─────────────────────────────────────────────
        summary = "\n".join([f"  {step}: {str(result or '')[:60]}" for step, result in results])
        log.info("=" * 70)
        log.info(f"✅ [AUTONOMOUS CYCLE #{cycle}] Summary:\n{summary}")
        log.info("=" * 70)

        # Update learning rate — count every discrete learning action
        elapsed = (datetime.utcnow() - datetime.fromisoformat(self.learning_history["start_time"])).total_seconds()
        total_actions = sum(self.learning_history.get(k, 0) for k in (
            "research_completed", "ideas_generated", "ideas_implemented",
            "reflections_conducted", "slsa_runs", "evolve_steps",
            "code_researched", "code_generated", "code_compiled",
            "code_reflected", "software_studied",
            "command_awareness_cycles", "command_executions",
            "topic_seedings", "reasoning_cycles", "metacognition_cycles",
            "improvement_cycles", "self_scan_cycles", "github_push_cycles",
            "brain_training_cycles", "cognitive_enhancement_cycles",
            "github_code_discovery_cycles", "searchcode_discovery_cycles",
            "serpex_research_cycles", "builds_integration_cycles",
            "scrapy_research_cycles",
        ))
        self.learning_history["learning_rate"] = total_actions / max(1, elapsed)

        # Log stats to knowledge base
        if self.knowledge_db:
            try:
                self.knowledge_db.set("learning_stats", self.learning_history)
            except Exception as e:
                log.debug(f"Knowledge DB stats update failed: {e}")

        return results

    # ─────────────────────────────────────────────
    def background_loop(self):
        """Main background loop - runs autonomously, continuously.

        Runs a full learning cycle on every iteration regardless of idle state.
        When the system is *active* (user is interacting), a shorter wait is
        used between cycles so the engine is always progressing.  When the
        system is *idle*, the cycle runs immediately with the normal inter-cycle
        pause.

        Uses *_interruptible_sleep* for all waits so that stop() wakes the
        loop immediately instead of waiting for the next poll tick.
        """
        log.info("🚀 [BACKGROUND LOOP] Started — continuous autonomous learning active")
        cycle_count = 0

        while self.running:
            try:
                idle = self.is_idle()
                log.info(
                    f"🔄 [BACKGROUND LOOP] Starting cycle #{cycle_count + 1} "
                    f"({'idle' if idle else 'active'} system)..."
                )
                self._run_autonomous_cycle()
                cycle_count += 1

                # Wait before next cycle.
                # During idle: longer pause (5× poll_interval) — no rush when no
                # user is present, conserves resources.
                # During active use: shorter pause (2× poll_interval) — keep the
                # improvement loop responsive while the user is working.
                # All waits are interruptible so stop() takes effect immediately.
                wait = self.poll_interval * 5 if idle else self.poll_interval * 2
                self._interruptible_sleep(wait)

            except Exception as e:
                log.error(f"❌ Background loop error: {e}")
                self._interruptible_sleep(self.poll_interval)

        log.info(f"[BACKGROUND LOOP] Stopped after {cycle_count} cycles")

    # ─────────────────────────────────────────────
    def start(self):
        """Start the autonomous learning engine"""
        if self.running:
            log.warning("⚠️  Autonomous learning engine already running")
            return False

        self._stop_event.clear()
        self.running = True
        self.learning_thread = threading.Thread(
            target=self.background_loop, daemon=True, name="ALE-BackgroundLoop"
        )
        self.learning_thread.start()

        log.info("✅ Autonomous learning engine started")
        return True

    # ─────────────────────────────────────────────
    def stop(self):
        """Stop the autonomous learning engine"""
        self.running = False
        self._stop_event.set()  # Wake any sleeping background loop immediately
        if self.learning_thread:
            self.learning_thread.join(timeout=10)

        log.info("✅ Autonomous learning engine stopped")
        return True

    # ─────────────────────────────────────────────
    def get_current_topic(self) -> Optional[str]:
        """Return the research topic pinned to the current (or last) cycle."""
        return self._current_cycle_topic

    def get_research_ingest_wait(self) -> float:
        """Return the configured ingestion-wait duration in seconds."""
        return self._RESEARCH_INGEST_WAIT

    # ─────────────────────────────────────────────
    def get_learning_stats(self) -> Dict[str, Any]:
        """Get learning statistics"""
        uptime = 0
        start_time_str = self.learning_history.get("start_time") or ""
        if start_time_str:
            try:
                start_dt = datetime.fromisoformat(start_time_str)
                uptime = int((datetime.utcnow() - start_dt).total_seconds())
            except Exception:
                uptime = 0
        return {
            "running": self.running,
            "is_idle": self.is_idle(),
            "cycle_count": self._cycle_count,
            "stats": self.learning_history,
            "pending_ideas": len(self.pending_ideas),
            "research_topics": len(self.research_topics),
            "code_research_topics": len(self.code_research_topics),
            "software_study_categories": len(self.software_study_categories),
            "pending_compilations": len(getattr(self, "_pending_compiled", [])),
            "pending_reflections": len(getattr(self, "_compiled_for_reflection", [])),
            "uptime_seconds": uptime,
            "slsa_topics": self.slsa_manager.get_topics() if self.slsa_manager else [],
            "modules_available": {
                "researcher": bool(self.researcher),
                "reflect": bool(self.reflect),
                "self_teacher": bool(self.self_teacher),
                "evolve_engine": bool(self.evolve_engine),
                "self_implementer": bool(self.self_implementer),
                "idea_implementation": bool(self.idea_implementation),
                "code_generator": bool(self._get_code_generator()),
                "code_compiler": bool(self._get_code_compiler()),
                "software_studier": bool(self._get_software_studier()),
                "internet": bool(self._get_internet()),
                "structural_awareness": bool(self._get_structural_awareness()),
                "slsa_manager": bool(self.slsa_manager),
                "reasoning_engine": bool(self._get_reasoning_engine()),
                "metacognition": bool(self._get_metacognition()),
                "improvement_integrator": bool(self._get_improvement_integrator()),
                "github_sync": bool(self.github_sync or (self.core and getattr(self.core, "github_sync", None))),
                "build_scanner": bool(self.build_scanner or (self.core and getattr(self.core, "build_scanner", None))),
                "binary_studier": bool(self.binary_studier or (self.core and getattr(self.core, "binary_studier", None))),
                "github_code_search": bool(self._get_github_code_search()),
                "searchcode_search": bool(self._get_searchcode_search()),
                "serpex_research_agent": bool(self._get_serpex_agent() or self._get_scrapy_agent()),
                "scrapy_research_agent": bool(self._get_scrapy_agent()),
            },
        }

    # ─────────────────��───────────────────────────
    def add_research_topic(self, topic: str):
        """Add new topic to autonomous research list.

        Rejects compound strings (containing newlines or payload keywords like
        'Insights:', 'Findings:', 'Research finding:') and very short fragments
        so that blob noise never enters the research queue.
        """
        if not topic or not isinstance(topic, str):
            return False
        # Reject multi-line compound strings (results / reflection blobs)
        if "\n" in topic:
            return False
        # Reject strings that look like embedded result payloads
        topic_lower = topic.lower()
        if any(marker in topic_lower for marker in _TOPIC_NOISE_MARKERS):
            return False
        # Reject very short fragments (single words < 4 chars)
        if len(topic.strip()) < 4:
            return False
        if topic not in self.research_topics:
            self.research_topics.append(topic)
            log.info(f"✅ Added research topic: {topic}")
            return True
        return False

    # ─────────────────────────────────────────────
    def add_research_topics(self, topics: List[str]):
        """Add multiple topics"""
        added = []
        for topic in topics:
            if self.add_research_topic(topic):
                added.append(topic)
        return added

    # ─────────────────────────────────────────────
    def update_research_topics(self, new_topics: List[str]) -> None:
        """Replace (or extend) the active research-topic list with *new_topics*.

        Called by DynamicTopicManager / BackgroundTopicRefresh to inject fresh
        topics so ALE does not keep repeating the same queries.  New topics are
        appended to the existing list rather than replacing it entirely, which
        preserves any user-added topics while still surfacing novel ones.
        """
        if not new_topics:
            return
        added = self.add_research_topics(new_topics)
        if added:
            log.info("[ALE] update_research_topics: injected %d new topics (%s…)",
                     len(added), added[0])

    # ─────────────────────────────────────────────
    def detect_knowledge_gaps(self, max_gaps: int = 5) -> List[str]:
        """Additive: scan the KnowledgeDB for under-covered topics.

        Returns a list of research topic strings for which fewer than
        :attr:`_MIN_COVERAGE_THRESHOLD` facts are stored.  These gaps are then
        fed back into the research queue so the ALE self-completes its own
        knowledge base autonomously.

        Called automatically by :meth:`_run_autonomous_cycle` and can also be
        triggered manually via ``agents submit architecture_analysis``.
        """
        gaps: List[str] = []
        if not self.knowledge_db or not self.research_topics:
            return gaps
        for topic in self.research_topics[:30]:
            try:
                # Try both search() and recall() APIs
                results = None
                for method in ("search", "recall"):
                    fn = getattr(self.knowledge_db, method, None)
                    if fn:
                        results = fn(topic, limit=self._MIN_COVERAGE_THRESHOLD)
                        break
                count = len(results) if results else 0
                if count < self._MIN_COVERAGE_THRESHOLD:
                    gaps.append(topic)
                    if len(gaps) >= max_gaps:
                        break
            except Exception:
                pass
        if gaps:
            log.info("[ALE] Knowledge gaps detected (%d): %s", len(gaps), gaps[:3])
        return gaps

    def submit_agent_tasks_for_gaps(self) -> int:
        """Additive: submit research tasks for detected knowledge gaps.

        Enqueues a 'research' task for each gap topic into the RuntimeManager's
        task queue (if the core exposes one).  This is the core hook that makes
        Niblit a *self-completing* AI — gaps trigger automatic research.

        Returns the number of tasks submitted.
        """
        gaps = self.detect_knowledge_gaps()
        if not gaps:
            return 0

        # Get the runtime manager from core
        rm = getattr(self.core, "runtime_manager", None) if self.core else None
        submitted = 0
        for topic in gaps:
            if rm is not None:
                try:
                    rm.submit_task(
                        "research",
                        payload={
                            "topic": topic,
                            "context": "ale_gap_fill",
                            "language": "python",
                        },
                        priority="normal",
                        source="ale_gap_detection",
                    )
                    submitted += 1
                except Exception as exc:
                    log.debug("[ALE] Gap task submit failed for %r: %s", topic, exc)
            else:
                # Fallback: just add to research topics for next ALE cycle
                self.add_research_topic(topic)
                submitted += 1

        if submitted:
            log.info("[ALE] Submitted %d gap-fill agent tasks", submitted)
            try:
                from core.notification_queue import notif_queue as _nq
                _nq.push(f"[ALE] Submitted {submitted} gap-fill research task(s): {gaps[:3]}")
            except Exception:
                pass
        return submitted

    def self_improve_via_agents(self, goal: str = "") -> str:
        """Additive: submit a full self-improvement plan to the Phase-2 agents.

        Creates a 'plan_improvement' task in the RuntimeManager so the
        PlannerAgent decomposes it into research → coding → testing →
        reflection sub-tasks.  Returns a status string.
        """
        rm = getattr(self.core, "runtime_manager", None) if self.core else None
        if rm is None:
            return "[ALE] RuntimeManager not available for self-improve"
        goal = goal or f"Improve Niblit capabilities based on {self.get_current_topic() or 'recent research'}"
        try:
            rm.submit_task(
                "plan_improvement",
                payload={"goal": goal, "context": "ale_self_improvement"},
                priority="high",
                source="ale_self_improve",
            )
            log.info("[ALE] Self-improvement task submitted: %s", goal[:60])
            return f"✅ Self-improvement task submitted: {goal[:60]}"
        except Exception as exc:
            return f"[ALE] self_improve_via_agents error: {exc}"


# ─────────────────────────────────────────────
# SINGLETON INSTANCE & INITIALIZATION
# ─────────────────────────────────────────────
_autonomous_engine = None


def get_autonomous_engine() -> Optional[AutonomousLearningEngine]:
    """Get singleton instance"""
    global _autonomous_engine
    return _autonomous_engine


def initialize_autonomous_engine(core, researcher=None, idea_generator=None,
                                 reflect_module=None, self_teacher=None,
                                 slsa_manager=None, knowledge_db=None,
                                 evolve_engine=None, self_implementer=None,
                                 idea_implementation=None,
                                 code_generator=None, code_compiler=None,
                                 software_studier=None, internet=None,
                                 reasoning_engine=None, metacognition=None,
                                 improvement_integrator=None,
                                 github_sync=None, build_scanner=None,
                                 binary_studier=None, llm=None,
                                 github_code_search=None,
                                 stackoverflow_search=None,
                                 pypi_search=None,
                                 serpex_research_agent=None,
                                 scrapy_research_agent=None) -> AutonomousLearningEngine:
    """Initialize and return singleton engine"""
    global _autonomous_engine

    _autonomous_engine = AutonomousLearningEngine(
        core=core,
        researcher=researcher,
        idea_generator=idea_generator,
        reflect_module=reflect_module,
        self_teacher=self_teacher,
        slsa_manager=slsa_manager,
        knowledge_db=knowledge_db,
        evolve_engine=evolve_engine,
        self_implementer=self_implementer,
        idea_implementation=idea_implementation,
        code_generator=code_generator,
        code_compiler=code_compiler,
        software_studier=software_studier,
        internet=internet,
        reasoning_engine=reasoning_engine,
        metacognition=metacognition,
        improvement_integrator=improvement_integrator,
        github_sync=github_sync,
        build_scanner=build_scanner,
        binary_studier=binary_studier,
        llm=llm,
        github_code_search=github_code_search,
        stackoverflow_search=stackoverflow_search,
        pypi_search=pypi_search,
        serpex_research_agent=serpex_research_agent,
        scrapy_research_agent=scrapy_research_agent,
    )

    log.info("✅ AutonomousLearningEngine factory initialized")
    return _autonomous_engine


# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("Running autonomous_learning_engine.py")
    print("This module should be initialized from NiblitCore")
