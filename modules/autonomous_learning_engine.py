#!/usr/bin/env python3
"""
AUTONOMOUS LEARNING ENGINE
Runs when Niblit is idle to autonomously improve itself through:
1. Research new topics (self-research)
2. Generate ideas (self-idea)
3. Implement ideas (self-implement)
4. Learn from research (learn)
5. Reflect on findings (reflect)
6. Auto-run SLSA for knowledge generation
7. Feed everything back into the knowledge base

Creates a continuous self-improvement loop.
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
    Orchestrates autonomous learning across all Niblit modules.
    Runs in background when system is idle.
    """

    def __init__(self, core, researcher=None, idea_generator=None,
                 reflect_module=None, self_teacher=None, slsa_manager=None,
                 knowledge_db=None, idle_threshold=300, poll_interval=60):
        """
        Args:
            core: NiblitCore instance
            researcher: SelfResearcher module
            idea_generator: SelfIdeaImplementation module
            reflect_module: ReflectModule
            self_teacher: SelfTeacher module
            slsa_manager: SLSAManager for SLSA auto-run
            knowledge_db: KnowledgeDB for persistence
            idle_threshold: Time (sec) before considering system idle
            poll_interval: How often to check for idle state
        """
        self.core = core
        self.researcher = researcher
        self.idea_generator = idea_generator
        self.reflect = reflect_module
        self.self_teacher = self_teacher
        self.slsa_manager = slsa_manager
        self.knowledge_db = knowledge_db

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

        # Ideas generated (to implement)
        self.pending_ideas = []

        # Learning history
        self.learning_history = {
            "research_completed": 0,
            "ideas_generated": 0,
            "ideas_implemented": 0,
            "reflections_conducted": 0,
            "slsa_runs": 0,
            "last_research_topic": None,
            "last_idea": None,
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
                except Exception as e:
                    log.debug(f"Knowledge DB logging failed: {e}")

            log.info(f"✅ [AUTONOMOUS RESEARCH] Completed: {topic}")
            return f"Researched: {topic}"

        except Exception as e:
            log.error(f"❌ Autonomous research failed: {e}")
            return f"[Research error: {e}]"

    # ─────────────────────────────────────────────
    def _autonomous_idea_generation(self) -> str:
        """Step 2: Generate ideas based on research"""
        if not self.idea_generator:
            return "[Idea generator unavailable]"

        try:
            # Generate idea based on recent research
            topic = self.learning_history.get("last_research_topic") or "system improvement"
            prompt = f"Generate an innovative idea for: {topic}"

            log.info(f"💡 [AUTONOMOUS IDEAS] Generating idea: {prompt}")

            idea = None
            if hasattr(self.idea_generator, "generate_idea"):
                idea = self.idea_generator.generate_idea(prompt)
            elif hasattr(self.idea_generator, "generate_ideas"):
                ideas = self.idea_generator.generate_ideas(prompt, count=1)
                idea = ideas[0] if ideas else None

            if idea:
                self.pending_ideas.append(idea)
                self.learning_history["ideas_generated"] += 1
                self.learning_history["last_idea"] = idea[:100] if isinstance(idea, str) else str(idea)[:100]

                # Log to knowledge base
                if self.knowledge_db:
                    try:
                        self.knowledge_db.log_event(f"Autonomous idea generated: {str(idea or '')[:50]}")
                    except Exception as e:
                        log.debug(f"Knowledge DB logging failed: {e}")

                log.info(f"✅ [AUTONOMOUS IDEAS] Generated: {str(idea or '')[:50]}...")
                return f"Idea generated: {str(idea or '')[:100]}"

            return "[No idea generated]"

        except Exception as e:
            log.error(f"❌ Autonomous idea generation failed: {e}")
            return f"[Idea generation error: {e}]"

    # ─────────────────────────────────────────────
    def _autonomous_implementation(self) -> str:
        """Step 3: Implement pending ideas"""
        if not self.idea_generator or not self.pending_ideas:
            return "[No ideas to implement]"

        try:
            idea = self.pending_ideas.pop(0)

            log.info(f"🚀 [AUTONOMOUS IMPLEMENT] Implementing: {str(idea or '')[:50]}...")

            plan = None
            # Try implement_idea first, then generate_plan as fallback
            if hasattr(self.idea_generator, "implement_idea"):
                plan = self.idea_generator.implement_idea(idea)
            elif hasattr(self.idea_generator, "generate_plan"):
                plan = self.idea_generator.generate_plan(str(idea))
            elif hasattr(self.idea_generator, "enqueue_plan"):
                self.idea_generator.enqueue_plan(str(idea))
                plan = f"Queued: {str(idea)[:50]}"

            if plan:
                self.learning_history["ideas_implemented"] += 1

                # Store plan in knowledge DB
                if self.knowledge_db:
                    try:
                        self.knowledge_db.log_event(f"Autonomous implementation executed: {str(idea or '')[:50]}")
                    except Exception as e:
                        log.debug(f"Knowledge DB logging failed: {e}")

                log.info(f"✅ [AUTONOMOUS IMPLEMENT] Executed")
                return f"Idea implemented: {str(idea or '')[:50]}..."

            return "[Implementation generated no plan]"

        except Exception as e:
            log.error(f"❌ Autonomous implementation failed: {e}")
            return f"[Implementation error: {e}]"

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
                except Exception as e:
                    log.debug(f"Knowledge DB logging failed: {e}")

            log.info(f"✅ [AUTONOMOUS LEARN] {str(result or '')[:50]}")
            return str(result) if result is not None else "[No learning result]"

        except Exception as e:
            log.error(f"❌ Autonomous learning failed: {e}")
            return f"[Learning error: {e}]"

    # ─────────────────────────────────────────────
    def _run_autonomous_cycle(self):
        """Execute one complete autonomous learning cycle"""
        log.info("=" * 70)
        log.info("🔄 [AUTONOMOUS CYCLE] Starting complete learning cycle...")
        log.info("=" * 70)

        results = []

        # Execute in order
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

        # Log cycle summary — str() wraps any non-string results to prevent slice errors
        summary = "\n".join([f"  {step}: {str(result or '')[:60]}" for step, result in results])
        log.info("=" * 70)
        log.info(f"✅ [AUTONOMOUS CYCLE] Summary:\n{summary}")
        log.info("=" * 70)

        # Update learning rate
        elapsed = (datetime.utcnow() - datetime.fromisoformat(self.learning_history["start_time"])).total_seconds()
        total_actions = (self.learning_history["research_completed"] +
                        self.learning_history["ideas_implemented"] +
                        self.learning_history["reflections_conducted"])
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
            "uptime_seconds": uptime,
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
                                 slsa_manager=None, knowledge_db=None) -> AutonomousLearningEngine:
    """Initialize and return singleton engine"""
    global _autonomous_engine

    _autonomous_engine = AutonomousLearningEngine(
        core=core,
        researcher=researcher,
        idea_generator=idea_generator,
        reflect_module=reflect_module,
        self_teacher=self_teacher,
        slsa_manager=slsa_manager,
        knowledge_db=knowledge_db
    )

    log.info("✅ AutonomousLearningEngine factory initialized")
    return _autonomous_engine


# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("Running autonomous_learning_engine.py")
    print("This module should be initialized from NiblitCore")
