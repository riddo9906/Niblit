#!/usr/bin/env python3
"""
NIBLIT ROUTER MODULE — PATCHED
Fully merged version with improved SelfResearcher integration.
Retains all original command handling and logic.
"""

import logging
import threading
import json
from datetime import datetime
from modules.slsa_manager import slsa_manager

log = logging.getLogger("NiblitRouter")
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s][%(name)s][%(levelname)s] %(message)s'
)

# ─────────────────────────────────────
def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def safe_call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception:
        log.exception(f"safe_call failed for {fn}")
        name = getattr(fn, "__name__", "unknown")
        return f"[ERROR::{name}]"

# ─────────────────────────────────────
class NiblitRouter:

    COMMAND_PREFIXES = (
        "toggle-llm","self-research","search","summary","remember","learn",
        "ideas","reflect","auto-reflect","self-idea","self-implement",
        "self-heal","status","health","time","help","commands",
        "evolve","exit","quit","shutdown",
        "start_slsa","stop_slsa","restart_slsa","slsa-status","status_slsa"
    )

    # ─────────────────────────────────
    def __init__(self, brain, memory, core=None):
        self.brain = brain
        self.memory = memory
        self.core = core

    # ─────────────────────────────────
    def start(self):
        log.info("NiblitRouter started.")

    # ─────────────────────────────────
    def log_event(self, msg):
        ts = timestamp()
        log.info(f"[ROUTER EVENT] {msg}")
        if hasattr(self.memory, "log_event"):
            safe_call(self.memory.log_event, f"{ts} - {msg}")

    # ─────────────────────────────────
    def _collect(self, user, response, source):
        if not self.core:
            return
        collector = getattr(self.core, "collector", None)
        if not collector:
            return
        entry = {
            "time": timestamp(),
            "input": user,
            "response": response,
            "source": source
        }
        if hasattr(collector, "add"):
            safe_call(collector.add, entry)
        elif hasattr(collector, "capture"):
            safe_call(collector.capture, user, response, source)

    # ─────────────────────────────────
    # DEDUPLICATION HELPER
    # ─────────────────────────────────
    def _deduplicate_results(self, items):
        """
        Order-preserving deduplication for mixed str/dict results.
        
        - Strings are keyed directly
        - Dicts are serialized via json.dumps(sort_keys=True)
        - Non-serializable objects fall back to str()
        - Returns list of strings by converting dicts to JSON strings
        """
        seen = set()
        result = []
        
        for item in items:
            if isinstance(item, str):
                key = item
                text = item
            elif isinstance(item, dict):
                try:
                    key = json.dumps(item, sort_keys=True)
                    text = json.dumps(item)
                except (TypeError, ValueError):
                    key = str(item)
                    text = str(item)
            else:
                key = str(item)
                text = str(item)
            
            if key not in seen:
                seen.add(key)
                result.append(text)
        
        return result

    # ─────────────────────────────────
    # INTERNET / SELF-RESEARCH
    # ─────────────────────────────────
    def _run_research(self, query):
        if not self.core:
            return "[Core missing]"

        researcher = getattr(self.core, "researcher", None)
        internet = getattr(self.core, "internet", None)

        if not researcher and not internet:
            return "[Researcher and InternetManager missing]"

        results = []

        # 1️⃣ Use researcher if available
        if researcher and hasattr(researcher, "search"):
            res = safe_call(researcher.search, query)
            if res:
                if isinstance(res, list):
                    results.extend(res)
                else:
                    results.append(res)

        # 2️⃣ Fallback: use internet directly if researcher missing or returned nothing
        if not results and internet:
            web_results = safe_call(internet.search, query, max_results=5) or []
            summary = safe_call(internet.quick_summary, query) or ""

            results.extend(web_results)
            if summary:
                results.append(summary)

        # 3️⃣ Collect results into memory (non-duplicative)
        for r in results:
            if hasattr(self.memory, "add_fact"):
                safe_call(self.memory.add_fact, f"research:{query}", r, ["research"])
            elif hasattr(self.memory, "store_learning"):
                safe_call(self.memory.store_learning, {
                    "time": timestamp(),
                    "input": query,
                    "response": r,
                    "source": "research"
                })

        # 4️⃣ Normalize return as string (with proper deduplication)
        if results:
            deduplicated = self._deduplicate_results(results)
            return "\n".join(deduplicated)

        return f"[No data found for '{query}']"

    # ─────────────────────────────────
    # SELF-IDEA IMPLEMENTATION
    # ─────────────────────────────────
    def _self_idea_implementation(self, prompt):
        plan = ""
        if hasattr(self.brain, "handle"):
            plan = safe_call(self.brain.handle, f"self-idea-plan: {prompt}")
        elif hasattr(self.brain, "think"):
            plan = safe_call(self.brain.think, f"self-idea-plan: {prompt}")

        if self.core and hasattr(self.memory, "store_learning"):
            safe_call(self.memory.store_learning, {
                "time": timestamp(),
                "input": f"self-idea: {prompt}",
                "response": plan,
                "source": "self_idea_implementation"
            })

        if self.core and getattr(self.core, "self_implementer", None):
            implementer = self.core.self_implementer
            if hasattr(implementer, "enqueue_plan"):
                safe_call(implementer.enqueue_plan, plan)
            else:
                if hasattr(implementer, "queue") and isinstance(implementer.queue, list):
                    implementer.queue.append(plan)

        return f"[Self-Idea Plan Generated]\n{plan}"

    # ─────────────────────────────────
    # MAIN PROCESS
    # ─────────────────────────────────
    def process(self, user_input):
        cleaned = user_input.strip()
        lower = cleaned.lower()

        self.log_event(f"Incoming: {cleaned}")

        cmd_word = lower.split(" ", 1)[0]

        if cmd_word in self.COMMAND_PREFIXES:
            resp = self.handle_command(cleaned)
            self._collect(cleaned, resp, "command")
            return resp

        if cleaned.startswith("/"):
            resp = self.handle_command(cleaned[1:])
            self._collect(cleaned, resp, "slash")
            return resp

        llm_enabled = getattr(self.core, "llm_enabled", True) if self.core else True

        if self.core and not llm_enabled:
            resp = "[LLM disabled for chat — system commands still work]"
            self._collect(cleaned, resp, "blocked")
            return resp

        if hasattr(self.brain, "think"):
            response = safe_call(self.brain.think, cleaned)
        else:
            response = safe_call(self.brain.handle, cleaned)

        log.info(f"[ROUTER RESPONSE] {response}")
        self._collect(cleaned, response, "brain")
        return response

    # ─────────────────────────────────
    # COMMAND HANDLER
    # ─────────────────────────────────
    def handle_command(self, cmd):
        ts = timestamp()
        lower = cmd.lower().strip()

        if lower.startswith("start_slsa"):
            parts = cmd.split(" ", 1)
            topics = parts[1].split(",") if len(parts) > 1 else None
            return slsa_manager.start(topics)

        if lower.startswith("stop_slsa"):
            return slsa_manager.stop()

        if lower.startswith("restart_slsa"):
            parts = cmd.split(" ", 1)
            topics = parts[1].split(",") if len(parts) > 1 else None
            return slsa_manager.restart(topics)

        if lower.startswith(("slsa-status", "status_slsa")):
            return slsa_manager.status()

        if lower in ("status", "health"):
            mem = 0
            try:
                if hasattr(self.memory, "recent_interactions"):
                    mem = len(safe_call(self.memory.recent_interactions) or [])
                elif self.core and hasattr(self.core, "db"):
                    mem = len(self.core.db.recent_interactions(500))
            except:
                mem = 0
            return f"{ts} 🧠 Niblit operational. Memory entries: {mem}"

        if lower in ("shutdown", "exit", "quit"):
            if self.core:
                threading.Thread(target=safe_call, args=(self.core.shutdown,), daemon=True).start()
            return "Shutdown scheduled."

        if lower.startswith("toggle-llm"):
            if not self.core:
                return "[Error] Core not available"
            state = lower.replace("toggle-llm", "").strip()
            if state in ("on", "true", "1"):
                self.core.llm_enabled = True
                return "LLM enabled."
            if state in ("off", "false", "0"):
                self.core.llm_enabled = False
                return "LLM disabled."
            return "Usage: toggle-llm on/off"

        if lower in ("help", "commands"):
            return self.help_text()

        if lower.startswith("self-research"):
            query = cmd[len("self-research"):].strip()
            return self._run_research(query) if query else "[Provide research query]"

        if lower.startswith("search "):
            return self._run_research(cmd[len("search "):].strip())

        if lower.startswith("summary "):
            return self._run_research(cmd[len("summary "):].strip())

        if lower.startswith("reflect "):
            if self.core and getattr(self.core, "reflect", None):
                text = cmd[len("reflect "):]
                return safe_call(self.core.reflect.collect_and_summarize, text)

        if lower.startswith("auto-reflect"):
            if self.core and getattr(self.core, "reflect", None):
                events = safe_call(self.memory.recent_interactions, 10) or []
                return safe_call(self.core.reflect.auto_reflect, events)

        if lower.startswith(("self-idea", "self-implement", "evolve")):
            prompt = cmd
            return self._self_idea_implementation(prompt)

        if lower.startswith("remember "):
            payload = cmd[len("remember "):].strip()
            if ":" in payload and self.core:
                k, v = payload.split(":", 1)
                safe_call(self.core.db.add_fact, k.strip(), v.strip())
                return f"Saved: {k.strip()}"
            return "Invalid remember format. Use remember key:value"

        if lower.startswith("learn "):
            topic = cmd[len("learn "):].strip()
            if self.core:
                safe_call(self.core.db.queue_learning, topic)
                return f"Learning queued → {topic}"

        if lower.startswith("ideas "):
            topic = cmd[len("ideas "):].strip()
            return f"Ideas for {topic}: Prototype → Test → Evolve"

        if lower.startswith("self-heal"):
            if self.core and getattr(self.core, "self_healer", None):
                return safe_call(self.core.self_healer.run) or "[Error]"
            return "[SelfHeal ERROR] SelfHealer unavailable"

        if lower in ("time", "what time is it", "current time"):
            return timestamp()

        if self.core:
            return safe_call(self.core.handle, cmd)

        log.warning(f"Unknown command: {cmd}")
        return f"Unknown command: {cmd}"

    # ─────────────────────────────────
    def help_text(self):
        commands = [
            "self-research <query>",
            "search <query>",
            "summary <query>",
            "self-idea <prompt>",
            "self-implement",
            "reflect <text>",
            "auto-reflect",
            "self-heal",
            "remember key:value",
            "learn topic",
            "ideas <topic>",
            "start_slsa [topic1,topic2]",
            "stop_slsa",
            "restart_slsa [topics]",
            "slsa-status",
            "toggle-llm on/off",
            "shutdown",
            "time / current time"
        ]
        return "[Niblit Commands]\n" + "\n".join(commands)


if __name__ == "__main__":
    print("Running fully patched niblit_router.py")
