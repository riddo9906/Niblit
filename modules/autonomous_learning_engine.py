#!/usr/bin/env python3
"""
AUTONOMOUS LEARNING ENGINE
Runs when Niblit is idle to autonomously improve itself through:
1.  Research new topics (self-research via SelfResearcher + internet)
2.  Generate ideas from research (self-idea via SelfIdeaImplementation)
3.  Implement ideas (self-implement via SelfImplementer)
4.  Learn from research (learn via SelfTeacher)
5.  Reflect on findings (reflect)
6.  Auto-run SLSA for knowledge generation
7.  Run evolution step (EvolveEngine)
8.  Code Research — researcher+internet fetch real language/code data → CodeGenerator
9.  Code Generation — idea_generator+implementer produce compilable code
10. Code Compilation — CodeCompiler compiles generated code and stores results
11. Code Reflection — ReflectModule studies compiled output so Niblit understands it
12. Software Study — SoftwareStudier analyzes code patterns/functions via internet data
13. Feed everything back into the knowledge base

Creates a continuous self-improvement loop.
Internet is the primary data-collection channel for steps 1, 8, 9, 12.
"""

import threading
import time
import logging
import random
from datetime import datetime
from typing import List, Optional, Dict, Any

log = logging.getLogger("AutonomousLearning")
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s][%(name)s][%(levelname)s] %(message)s'
)


class AutonomousLearningEngine:
    """
    Orchestrates autonomous learning across ALL Niblit modules.
    Runs in background when system is idle.
    """

    def __init__(self, core, researcher=None, idea_generator=None,
                 reflect_module=None, self_teacher=None, slsa_manager=None,
                 knowledge_db=None, idle_threshold=300, poll_interval=60,
                 evolve_engine=None, self_implementer=None, idea_implementation=None,
                 code_generator=None, code_compiler=None, software_studier=None,
                 internet=None):
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

        self.idle_threshold = idle_threshold
        self.poll_interval = poll_interval

        self.running = False
        self.last_user_interaction = datetime.utcnow()
        self.learning_thread = None

        # Topics to autonomously research (grows over time)
        self.research_topics = [
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
            "ai_ml_systems",
            "web_applications",
            "databases",
            "operating_systems",
            "networking",
            "security",
            "distributed_systems",
            "cloud_native",
        ]

        # Ideas generated (to implement)
        self.pending_ideas = []

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
            "last_research_topic": None,
            "last_idea": None,
            "last_language_studied": None,
            "last_software_category": None,
            "last_commands_studied": None,
            "last_seeded_topics": None,
            "learning_rate": 0.0,
            "start_time": datetime.utcnow().isoformat()
        }

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
    def _autonomous_research(self) -> str:
        """Step 1: Autonomously research interesting topics"""
        if not self.researcher:
            return "[Researcher unavailable]"

        try:
            # Pick random or trending topic
            topic = random.choice(self.research_topics)

            log.info(f"🔍 [AUTONOMOUS RESEARCH] Starting: {topic}")

            # Run research with autonomous learning enabled
            results = self.researcher.search(
                topic,
                max_results=5,
                use_history=True,
                synthesize=True,
                enable_autonomous_learning=True
            )

            self.learning_history["research_completed"] += 1
            self.learning_history["last_research_topic"] = topic

            # Log to knowledge base
            if self.knowledge_db:
                try:
                    self.knowledge_db.log_event(
                        f"Autonomous research completed: {topic} ({len(results) if results else 0} results)"
                    )
                    # Store structured acquired data fact
                    self.knowledge_db.add_fact(
                        f"ale_research:{topic.replace(' ', '_')}:{int(time.time())}",
                        {
                            "topic": topic,
                            "results_count": len(results) if results else 0,
                            "summary": str(results[0])[:300] if results else "no results",
                            "step": "step1_research",
                        },
                        tags=["ale_step1", "research", "autonomous", topic.split()[0].lower()],
                    )
                except Exception as e:
                    log.debug(f"Knowledge DB logging failed: {e}")

            log.info(f"✅ [AUTONOMOUS RESEARCH] Completed: {topic}")
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
        """Step 4: Reflect on learning"""
        if not self.reflect:
            return "[Reflect module unavailable]"

        try:
            last_topic = self.learning_history.get("last_research_topic") or "system learning"
            last_idea = self.learning_history.get("last_idea") or "system improvement"

            reflection_text = f"""
Autonomous Learning Summary:
- Researched: {last_topic}
- Generated Idea: {last_idea}
- Research Count: {self.learning_history['research_completed']}
- Implementation Count: {self.learning_history['ideas_implemented']}
- Reflection Count: {self.learning_history['reflections_conducted']}
            """

            log.info(f"🧠 [AUTONOMOUS REFLECT] Reflecting...")

            result = self.reflect.collect_and_summarize(reflection_text)

            self.learning_history["reflections_conducted"] += 1

            # Log to knowledge base
            if self.knowledge_db:
                try:
                    self.knowledge_db.log_event("Autonomous reflection completed")
                    self.knowledge_db.add_fact(
                        f"ale_reflection:{int(time.time())}",
                        {"topic": last_topic, "idea": last_idea,
                         "summary": str(result or reflection_text)[:400],
                         "step": "step4_reflection"},
                        tags=["ale_step4", "reflection", "autonomous"],
                    )
                except Exception as e:
                    log.debug(f"Knowledge DB logging failed: {e}")

            log.info(f"✅ [AUTONOMOUS REFLECT] {str(result or '')[:50]}")
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
        """Step 6: Feed learning to self-teacher"""
        if not self.self_teacher:
            return "[Self-teacher unavailable]"

        try:
            last_topic = self.learning_history.get("last_research_topic") or "system knowledge"

            log.info(f"📚 [AUTONOMOUS LEARN] Teaching about: {last_topic}")

            result = self.self_teacher.teach(last_topic)

            # Log to knowledge base
            if self.knowledge_db:
                try:
                    self.knowledge_db.log_event(f"Autonomous teaching: {last_topic}")
                    self.knowledge_db.add_fact(
                        f"ale_learning:{last_topic.replace(' ', '_')}:{int(time.time())}",
                        {"topic": last_topic, "result": str(result or "")[:300],
                         "step": "step6_learning"},
                        tags=["ale_step6", "learning", "autonomous"],
                    )
                except Exception as e:
                    log.debug(f"Knowledge DB logging failed: {e}")

            log.info(f"✅ [AUTONOMOUS LEARN] {str(result or '')[:50]}")
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

    def _get_software_studier(self):
        """Lazily resolve SoftwareStudier from core."""
        if not self.software_studier and self.core:
            self.software_studier = getattr(self.core, "software_studier", None)
        return self.software_studier

    def _autonomous_code_research(self) -> str:
        """Step 8: Researcher + Internet fetch real programming-language data → feed CodeGenerator.

        Internet is the primary source.  self_researcher provides semantic
        search / caching on top.  Results are stored in the knowledge DB so
        CodeGenerator can produce more informed code in step 9.
        """
        internet = self._get_internet()
        researcher = self.researcher
        code_gen = self._get_code_generator()

        if not internet and not researcher:
            return "[Code research skipped — no internet or researcher]"

        # Rotate through code research topics
        if not self.code_research_topics:
            return "[No code research topics configured]"

        lang, topic = random.choice(self.code_research_topics)
        query = f"{lang} {topic} programming best practices examples"

        log.info(f"💻 [CODE RESEARCH] Fetching: {query}")

        snippets: List[str] = []

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
        log.info(f"✅ [CODE RESEARCH] {lang}/{topic}: {len(snippets)} snippet(s) collected")
        return f"Code research: {lang}/{topic} — {len(snippets)} snippet(s) via internet"

    def _autonomous_code_generation(self) -> str:
        """Step 9: idea_generator + implementer produce compilable code from internet research.

        Uses knowledge collected in step 8 to generate well-informed code
        snippets.  The resulting code is queued for compilation in step 10.
        """
        code_gen = self._get_code_generator()
        internet = self._get_internet()

        if not code_gen:
            return "[Code generation skipped — CodeGenerator not available]"

        lang = self.learning_history.get("last_language_studied") or "python"
        topic = "autonomous_improvement"

        # Derive a richer docstring from recent internet research stored in KB
        docstring = f"Auto-generated by Niblit ALE — {lang} module for {topic}"
        if self.knowledge_db:
            try:
                # Pull most recent internet research snippet for context
                facts = self.knowledge_db.list_facts(10) if hasattr(self.knowledge_db, "list_facts") else []
                for f in reversed(facts):
                    if isinstance(f, dict) and f.get("key", "").startswith("ale_code_research:"):
                        docstring = f"Based on internet research: {str(f.get('value', ''))[:120]}"
                        break
            except Exception:
                pass

        try:
            # Generate a module skeleton
            result = code_gen.generate_niblit_module(
                name=f"ale_{lang}_{topic}",
                docstring=docstring,
            )
            code = result.get("code", "")
            if not result.get("success") or not code:
                return f"[Code generation failed: {result.get('error', 'unknown')}]"

            # Also attempt idea-driven generation via implementer
            if self.idea_implementation and hasattr(self.idea_implementation, "implement_idea"):
                try:
                    idea_prompt = f"Generate a {lang} utility for: {topic}"
                    impl_result = self.idea_implementation.implement_idea(idea_prompt)
                    if impl_result:
                        code += f"\n# Idea-driven addition:\n# {str(impl_result)[:200]}"
                except Exception as exc:
                    log.debug(f"Idea-driven generation failed: {exc}")

            # Queue the generated code for compilation
            self._pending_compiled.append({"language": lang, "code": code, "topic": topic})

            self.learning_history["code_generated"] = self.learning_history.get("code_generated", 0) + 1
            log.info(f"✅ [CODE GEN] Generated {lang} code ({len(code)} chars)")

            # Also enrich with internet context if available
            if internet:
                try:
                    internet.search(f"{lang} module best practices", max_results=1)
                except Exception:
                    pass

            return f"Code generated: {lang} module ({len(code)} chars) — queued for compilation"

        except Exception as exc:
            log.error(f"❌ Autonomous code generation failed: {exc}")
            return f"[Code generation error: {exc}]"

    def _autonomous_code_compilation(self) -> str:
        """Step 10: CodeCompiler compiles the generated code and stores results."""
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

        try:
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
        """Step 11: ReflectModule studies compiled output so Niblit understands code."""
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

            # Feed reflection back into the knowledge DB
            if self.knowledge_db:
                try:
                    key = f"ale_code_reflection:{lang}:{topic}:{int(time.time())}"
                    self.knowledge_db.add_fact(key, str(result or reflection_text), tags=["reflection", "code", lang])
                except Exception as exc:
                    log.debug(f"DB store reflection failed: {exc}")

            self.learning_history["code_reflected"] = self.learning_history.get("code_reflected", 0) + 1
            log.info(f"🔍 [CODE REFLECT] {lang}/{topic} — reflection stored")
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
    def _run_autonomous_cycle(self):
        """Execute one complete autonomous learning cycle"""
        log.info("=" * 70)
        log.info("🔄 [AUTONOMOUS CYCLE] Starting complete learning cycle...")
        log.info("=" * 70)

        results = []

        # Core learning loop
        results.append(("Research", self._autonomous_research()))
        time.sleep(2)

        results.append(("Ideas", self._autonomous_idea_generation()))
        time.sleep(2)

        results.append(("Learning", self._autonomous_learning()))
        time.sleep(2)

        results.append(("Implementation", self._autonomous_implementation()))
        time.sleep(2)

        results.append(("Reflection", self._autonomous_reflection()))
        time.sleep(2)

        results.append(("SLSA", self._autonomous_slsa_run()))
        time.sleep(2)

        results.append(("Evolve", self._autonomous_evolve_step()))
        time.sleep(2)

        # Programming-literacy loop (uses internet as primary data source)
        results.append(("CodeResearch", self._autonomous_code_research()))
        time.sleep(2)

        results.append(("CodeGeneration", self._autonomous_code_generation()))
        time.sleep(2)

        results.append(("CodeCompilation", self._autonomous_code_compilation()))
        time.sleep(2)

        results.append(("CodeReflection", self._autonomous_code_reflection()))
        time.sleep(2)

        results.append(("SoftwareStudy", self._autonomous_software_study()))
        time.sleep(2)

        # Structural self-awareness loop (steps 13-14)
        results.append(("CommandAwareness", self._autonomous_command_awareness()))
        time.sleep(2)

        results.append(("CommandExecution", self._autonomous_command_execution()))
        time.sleep(2)

        # Topic seeding loop (step 15)
        results.append(("TopicSeeding", self._autonomous_topic_seeding()))

        # Log cycle summary
        summary = "\n".join([f"  {step}: {str(result or '')[:60]}" for step, result in results])
        log.info("=" * 70)
        log.info(f"✅ [AUTONOMOUS CYCLE] Summary:\n{summary}")
        log.info("=" * 70)

        # Update learning rate — count every discrete learning action
        elapsed = (datetime.utcnow() - datetime.fromisoformat(self.learning_history["start_time"])).total_seconds()
        total_actions = sum(self.learning_history.get(k, 0) for k in (
            "research_completed", "ideas_generated", "ideas_implemented",
            "reflections_conducted", "slsa_runs", "evolve_steps",
            "code_researched", "code_generated", "code_compiled",
            "code_reflected", "software_studied",
            "command_awareness_cycles", "command_executions",
            "topic_seedings",
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
        """Main background loop - runs autonomously when idle"""
        log.info("🚀 [BACKGROUND LOOP] Started")
        cycle_count = 0

        while self.running:
            try:
                if self.is_idle():
                    log.info(f"😴 System idle. Starting autonomous learning cycle #{cycle_count + 1}...")
                    self._run_autonomous_cycle()
                    cycle_count += 1

                    # Wait before next cycle
                    time.sleep(self.poll_interval * 5)
                else:
                    log.debug("System active, skipping autonomous cycle")
                    time.sleep(self.poll_interval)

            except Exception as e:
                log.error(f"❌ Background loop error: {e}")
                time.sleep(self.poll_interval)

        log.info(f"[BACKGROUND LOOP] Stopped after {cycle_count} cycles")

    # ─────────────────────────────────────────────
    def start(self):
        """Start the autonomous learning engine"""
        if self.running:
            log.warning("⚠️  Autonomous learning engine already running")
            return False

        self.running = True
        self.learning_thread = threading.Thread(target=self.background_loop, daemon=True)
        self.learning_thread.start()

        log.info("✅ Autonomous learning engine started")
        return True

    # ─────────────────────────────────────────────
    def stop(self):
        """Stop the autonomous learning engine"""
        self.running = False
        if self.learning_thread:
            self.learning_thread.join(timeout=5)

        log.info("✅ Autonomous learning engine stopped")
        return True

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
            },
        }

    # ─────────────────��───────────────────────────
    def add_research_topic(self, topic: str):
        """Add new topic to autonomous research list"""
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
                                 software_studier=None, internet=None) -> AutonomousLearningEngine:
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
    )

    log.info("✅ AutonomousLearningEngine factory initialized")
    return _autonomous_engine


# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("Running autonomous_learning_engine.py")
    print("This module should be initialized from NiblitCore")
