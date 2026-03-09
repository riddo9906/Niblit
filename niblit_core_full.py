# niblit_core.py - NiblitCore (Hybrid A/B/C)
# Author: Riyaad Behardien & ChatGPT
# Drop-in replacement for NiblitProV5 core. Python >=3.8 recommended.

import threading
import time
import traceback
import logging
from datetime import datetime
from typing import Any, Dict, List, Tuple, Optional

# ---------------------------
# Logging
# ---------------------------
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
log = logging.getLogger("NiblitCore")

# ---------------------------
# Safe imports helper
# ---------------------------
def safe_import(name: str):
    try:
        return __import__(name)
    except Exception as e:
        log.debug("Optional import failed: %s -> %s", name, e)
        return None

niblit_network = safe_import("niblit_network")
self_maintenance = safe_import("self_maintenance")
niblit_sensors = safe_import("niblit_sensors")
niblit_voice = safe_import("niblit_voice")
collector = safe_import("collector")
trainer = safe_import("trainer")
generator = safe_import("generator")
membrane = safe_import("membrane")
healer = safe_import("healer")
slsa_generator = safe_import("slsa_generator")
niblit_memory = safe_import("niblit_memory")
# bridge module (optional)
try:
    from niblit_bridge import call_external
except Exception:
    call_external = None

# ---------------------------
# Utilities
# ---------------------------
def now_iso():
    return datetime.utcnow().isoformat() + "Z"

def safe_call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception as e:
        log.debug("safe_call failure: %s -> %s", fn, e)
        return None

# ---------------------------
# Minimal emotion detector (keyword + simple heuristic)
# ---------------------------
_EMO_KEYWORDS = {
    "positive": ["good","great","awesome","nice","happy","love","thanks","thank"],
    "negative": ["bad","sad","angry","upset","hate","problem","issue","frustrat"],
    "neutral":  ["ok","fine","maybe","later","later"]
}

def detect_emotion(text: str) -> str:
    tl = text.lower()
    score = {"positive":0,"negative":0,"neutral":0}
    for k, words in _EMO_KEYWORDS.items():
        for w in words:
            if w in tl:
                score[k] += 1
    # pick highest, fallback neutral
    best = max(score.items(), key=lambda x: (x[1], x[0]))
    return best[0] if best[1] > 0 else "neutral"

# ---------------------------
# Intent parser (simple)
# ---------------------------
def parse_intent(text: str) -> Tuple[str, Dict[str,str]]:
    t = text.strip().lower()
    # common commands
    if t.startswith("remember "):
        # remember key: value
        payload = t[len("remember "):].strip()
        if ":" in payload:
            k,v = payload.split(":",1)
            return "remember", {"key":k.strip(), "value":v.strip()}
        return "bad_remember", {}
    if t in ("time", "what time is it", "current time"):
        return "time", {}
    if "weather" in t:
        return "weather", {}
    if t in ("help", "commands"):
        return "help", {}
    if t in ("status", "health"):
        return "status", {}
    if t in ("shutdown","exit","quit"):
        return "shutdown", {}
    if t.startswith("learn about "):
        return "learn", {"topic": t[len("learn about "):].strip()}
    if t.startswith("ideas about "):
        return "ideas", {"topic": t[len("ideas about "):].strip()}
    return "chat", {}

# ---------------------------
# NiblitCore
# ---------------------------
class NiblitCore:
    def __init__(self):
        self.name = "Niblit"
        self.start_ts = time.time()
        self.start_time = now_iso()
        log.info("Initializing Niblit core...")

        # subsystems (safe)
        self.network = getattr(niblit_network, "network", None) if niblit_network else None
        # If module exists but no 'network' instance, try constructor if available
        if not self.network and niblit_network and hasattr(niblit_network, "NiblitNetwork"):
            try:
                self.network = niblit_network.NiblitNetwork()
            except Exception:
                self.network = None

        self.sensors = niblit_sensors.NiblitSensors() if niblit_sensors else None
        self.self_maintenance = self_maintenance.SelfMaintenance() if self_maintenance else None
        self.voice = niblit_voice.NiblitVoice() if niblit_voice else None

        self.collector = collector.Collector() if collector else None
        self.trainer = trainer.Trainer(self.collector) if trainer and self.collector else None
        self.generator = generator.Generator() if generator else None
        self.membrane = membrane.Membrane() if membrane else None
        self.healer = healer if healer else None
        self.slsa = slsa_generator if slsa_generator else None
        self.memory = niblit_memory.MemoryManager() if niblit_memory else None

        # LLM/Bridge placeholder (Bridge class or call_external)
        self.bridge_available = callable(call_external)
        self.llm = None

        # runtime flags
        self.running = True
        self._bg_threads: List[threading.Thread] = []

        # event bus
        self.event_bus: List[Tuple[str, Any]] = []

        # personality state (hybrid)
        self.persona = {
            "mode": "hybrid",      # hybrid A/B/C
            "tone": "balanced",    # balanced / warm / assertive
            "emotion_history": [], # recent detected emotions
            "last_user": None
        }

        # internal quick caches
        self._last_health = None

        # start background tasks
        self._start_background_threads()

        log.info("NiblitCore Initialized successfully.")

    # ---------------------------
    # Event bus helpers
    # ---------------------------
    def emit(self, event: str, payload: Any = None):
        self.event_bus.append((event, payload))
        log.debug("Event emitted: %s -> %s", event, payload)

    def read_events(self) -> List[Tuple[str, Any]]:
        ev = self.event_bus[:]
        self.event_bus.clear()
        return ev

    # ---------------------------
    # Background threads
    # ---------------------------
    def _start_background_threads(self):
        t1 = threading.Thread(target=self._background_loop, daemon=True, name="niblit-bg")
        t2 = threading.Thread(target=self._health_monitor, daemon=True, name="niblit-health")
        t1.start(); t2.start()
        self._bg_threads.extend([t1,t2])

    def _background_loop(self):
        """Frequent maintenance: flush, train, sensors, self-heal hooks."""
        while self.running:
            try:
                # collector/trainer
                if self.collector:
                    safe_call(self.collector.flush_if_needed)
                if self.trainer:
                    safe_call(self.trainer.step_if_needed)

                # sensors (use refresh alias if available)
                if self.sensors:
                    if hasattr(self.sensors, "refresh"):
                        safe_call(self.sensors.refresh)
                    elif hasattr(self.sensors, "read_sensors"):
                        safe_call(self.sensors.read_sensors)

                # maintenance
                if self.self_maintenance and hasattr(self.self_maintenance, "diagnose"):
                    safe_call(self.self_maintenance.diagnose)

                # periodic event processing
                evs = self.read_events()
                for e,p in evs:
                    log.debug("Processing event from background: %s -> %s", e, p)
                    # implement small auto-actions
                    if e == "sync_memory":
                        self._sync_memory_to_cloud(p)

            except Exception as e:
                log.exception("Background loop exception: %s", e)
            time.sleep(3)

    def _health_monitor(self):
        """Lower-frequency health heartbeat and autosave."""
        while self.running:
            try:
                uptime_s = int(time.time() - self.start_ts)
                mem_count = 0
                try:
                    if self.memory and hasattr(self.memory, "review"):
                        mem_count = len(self.memory.review(100))
                except Exception:
                    mem_count = 0
                self._last_health = {"uptime_s":uptime_s, "memory": {"entries": mem_count}, "ts": now_iso()}
                log.info("[HEALTH] Niblit alive | uptime_s=%s | memory=%s", uptime_s, mem_count)
                # auto-save memory if supported
                if self.memory and hasattr(self.memory, "autosave"):
                    safe_call(self.memory.autosave)
            except Exception as e:
                log.exception("Health monitor error: %s", e)
            time.sleep(30)

    # ---------------------------
    # Memory & sync helpers
    # ---------------------------
    def _sync_memory_to_cloud(self, destination_url: Optional[str]):
        if not self.membrane or not destination_url:
            return False
        mem_path = getattr(self.memory, "path", None) or getattr(self.memory, "file", None) or None
        try:
            if mem_path and getattr(self.membrane, "upload_data", None):
                return self.membrane.upload_data(mem_path, destination_url)
        except Exception as e:
            log.debug("Memory sync failed: %s", e)
        return False

    # ---------------------------
    # Public update (headless)
    # ---------------------------
    def update(self):
        """Single-cycle manual update; keeps parity with headless runner call."""
        try:
            # sensors
            if self.sensors:
                if hasattr(self.sensors, "refresh"):
                    safe_call(self.sensors.refresh)
                elif hasattr(self.sensors, "read_sensors"):
                    safe_call(self.sensors.read_sensors)
            # autosave
            if self.memory and hasattr(self.memory, "autosave"):
                safe_call(self.memory.autosave)
            # process events once
            evs = self.read_events()
            for e,p in evs:
                log.debug("Manual update event: %s -> %s", e, p)
        except Exception as e:
            log.exception("Update() error: %s", e)

    # ---------------------------
    # Personality engine + reply generation
    # ---------------------------
    def _choose_tone(self, emotion: str) -> str:
        # hybrid strategy: mix balanced + adaptivity + assertive agent when needed
        if emotion == "positive":
            return "warm"
        if emotion == "negative":
            return "calm"
        # default balanced
        return "balanced"

    def _format_reply(self, base: str, tone: str, autonomous_hint: Optional[str] = None) -> str:
        # apply small tone adjustments
        if tone == "warm":
            base = base + " 😊"
        elif tone == "calm":
            base = base + " — I'm here to help."
        elif tone == "assertive":
            base = "→ " + base
        # autonomous hint for agent-like actions
        if autonomous_hint:
            base = f"{base}\n[{autonomous_hint}]"
        return base

    def _store_interaction(self, user_text: str, reply: str, source: str = "interactive"):
        try:
            if self.memory and hasattr(self.memory, "add_entry"):
                safe_call(self.memory.add_entry, user_text, reply)
            elif self.collector and hasattr(self.collector, "add"):
                safe_call(self.collector.add, {"type":"utterance","text":user_text, "reply":reply})
        except Exception:
            pass

    # ---------------------------
    # Chat / respond API (intent-aware)
    # ---------------------------
    def respond(self, text: str) -> str:
        """Main entry: parse intent, update persona, produce a reply."""
        if not text:
            return "..."

        user_text = text.strip()
        self.persona["last_user"] = user_text
        emotion = detect_emotion(user_text)
        self.persona["emotion_history"].append((now_iso(), emotion))
        # keep history short
        if len(self.persona["emotion_history"]) > 40:
            self.persona["emotion_history"] = self.persona["emotion_history"][-40:]
        tone = self._choose_tone(emotion)

        intent, meta = parse_intent(user_text)

        try:
            # command intents
            if intent == "remember":
                k = meta.get("key"); v = meta.get("value")
                if self.memory and hasattr(self.memory, "set"):
                    safe_call(self.memory.set, k, v)
                    reply = f"Saved: {k}"
                else:
                    reply = "Memory module unavailable."
                self._store_interaction(user_text, reply)
                return self._format_reply(reply, tone)

            if intent == "time":
                reply = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
                self._store_interaction(user_text, reply)
                return self._format_reply(reply, tone)

            if intent == "weather":
                if self.network and hasattr(self.network, "get_weather"):
                    reply = str(safe_call(self.network.get_weather))
                else:
                    reply = "Weather service is unavailable."
                self._store_interaction(user_text, reply)
                return self._format_reply(reply, tone)

            if intent == "help":
                reply = self.help_text()
                self._store_interaction(user_text, reply)
                return self._format_reply(reply, tone)

            if intent == "status":
                reply = self.status_text()
                self._store_interaction(user_text, reply)
                return self._format_reply(reply, tone)

            if intent == "shutdown":
                reply = "Shutting down per request."
                # schedule shutdown asynchronously
                threading.Thread(target=self.shutdown, daemon=True).start()
                self._store_interaction(user_text, reply)
                return self._format_reply(reply, "assertive", autonomous_hint="shutdown scheduled")

            if intent == "learn":
                topic = meta.get("topic","")
                # try a bridge fetch or call network fetch if available
                fetched = None
                if self.bridge_available:
                    try:
                        fetched = call_external(f"Summarize: {topic}")
                    except Exception:
                        fetched = None
                # fallback
                if not fetched and self.network and hasattr(self.network, "fetch_json"):
                    try:
                        fetched = safe_call(self.network.fetch_json, f"https://api.allorigins.win/raw?url=https://en.wikipedia.org/wiki/{topic.replace(' ','_')}")
                    except Exception:
                        fetched = None
                reply = fetched if fetched else f"Couldn't fetch deep data for '{topic}'."
                self._store_interaction(user_text, str(reply))
                return self._format_reply(str(reply)[:1000], tone)

            if intent == "ideas":
                topic = meta.get("topic","")
                reply = f"Here are quick ideas for {topic}: 1) Prototype 2) Monetize 3) Iterate"
                self._store_interaction(user_text, reply)
                return self._format_reply(reply, "warm")

            # fallback: small-chat → try bridge → local heuristic
            if self.bridge_available:
                try:
                    resp = call_external(user_text)
                    if resp:
                        self._store_interaction(user_text, resp)
                        return self._format_reply(resp, tone)
                except Exception:
                    log.debug("Bridge call failed fallback.")

            # local heuristics
            generic = self._heuristic_reply(user_text)
            self._store_interaction(user_text, generic)
            return self._format_reply(generic, tone)

        except Exception as e:
            log.exception("Error while responding: %s", e)
            fallback = f"I heard: \"{user_text}\". (error: {e})"
            self._store_interaction(user_text, fallback)
            return self._format_reply(fallback, "calm")

    def _heuristic_reply(self, text: str) -> str:
        # quick local replies & small personality
        tl = text.lower()
        if "hi" in tl or "hello" in tl:
            return f"Hi — I'm Niblit. How can I help?"
        if "how are you" in tl:
            return "Learning and improving — thanks for asking."
        if "reflect" in tl:
            # produce a short reflection summary
            hist = [e for _,e in self.persona["emotion_history"][-10:]]
            most = max(set(hist), key=hist.count) if hist else "neutral"
            return f"I've been {most} lately. Memory size: {len(self.persona['emotion_history'])}."
        # default echo paraphrase
        return f"I heard you say: \"{text}\"."

    # ---------------------------
    # Utilities: help/status
    # ---------------------------
    def help_text(self) -> str:
        return (
            "Commands:\n"
            "  remember key: value  - save a fact\n"
            "  time                 - current UTC time\n"
            "  weather              - current weather (if available)\n"
            "  learn about <topic>  - attempt to fetch quick summary\n"
            "  ideas about <topic>  - quick idea generator\n"
            "  status               - show core status\n"
            "  reflect              - internal reflection\n            " "shutdown             - stop Niblit\n"
        )

    def status_text(self) -> str:
        uptime = int(time.time() - self.start_ts)
        mem_entries = 0
        try:
            if self.memory and hasattr(self.memory, "review"):
                mem_entries = len(self.memory.review(100))
        except Exception:
            pass
        net = getattr(self.network, "test_url", "offline") if self.network else "offline"
        return json_safe({
            "uptime_s": uptime,
            "memory_entries": mem_entries,
            "network": net,
            "persona_tone": self.persona.get("tone"),
            "bridge": self.bridge_available
        })

    # ---------------------------
    # Shutdown
    # ---------------------------
    def shutdown(self):
        log.info("[NiblitCore] Shutdown initiated...")
        self.running = False
        # allow background threads to wrap
        time.sleep(0.5)
        # optional graceful component shutdowns
        try:
            if self.network and hasattr(self.network, "shutdown"):
                self.network.shutdown()
        except Exception:
            pass
        try:
            if self.memory and hasattr(self.memory, "autosave"):
                self.memory.autosave()
        except Exception:
            pass
        log.info("[NiblitCore] Shutdown complete.")

# ---------------------------
# Helpers
# ---------------------------
def json_safe(obj: Any) -> str:
    try:
        import json
        return json.dumps(obj, default=str, indent=2)
    except Exception:
        return str(obj)

# ---------------------------
# Backwards compatibility alias (some scripts import lowercase)
# ---------------------------
niblitcore = NiblitCore

# If run as script for quick smoke-test:
if __name__ == "__main__":
    core = NiblitCore()
    print("[Selftest] core started. Type lines to get replies. 'exit' quits.")
    try:
        while core.running:
            cmd = input("You: ").strip()
            if cmd.lower() in ("exit","quit","shutdown"):
                core.shutdown()
                break
            print("Niblit:", core.respond(cmd))
    except KeyboardInterrupt:
        core.shutdown()