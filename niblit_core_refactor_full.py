# niblit_core_refactor.py
import threading, time, logging
from datetime import datetime
import json

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
log = logging.getLogger("NiblitCoreRefactor")

# ── Optional legacy modules — import gracefully ──────────────────────────────
try:
    import niblit_net as niblit_network
except ImportError:
    niblit_network = None

try:
    import self_maintenance
except ImportError:
    self_maintenance = None

try:
    import niblit_sensors
except ImportError:
    niblit_sensors = None

try:
    import niblit_voice
except ImportError:
    niblit_voice = None

try:
    import collector
except ImportError:
    collector = None

try:
    import trainer
except ImportError:
    trainer = None

try:
    import generator
except ImportError:
    generator = None

try:
    import membrane
except ImportError:
    membrane = None

try:
    import healer
except ImportError:
    healer = None

try:
    import slsa_generator
except ImportError:
    slsa_generator = None

try:
    from niblit_memory import MemoryManager as _MemoryManager
except ImportError:
    _MemoryManager = None
# ─────────────────────────────────────────────────────────────────────────────


class niblitcore:
    def __init__(self):
        self.name = "Niblit"
        self.start_time = datetime.utcnow()

        log.info("Initializing Niblit core...")

        # Core modules — each wrapped so a missing module doesn't abort boot
        if niblit_network:
            try:
                self.network = niblit_network.network
            except AttributeError:
                try:
                    self.network = niblit_network.NiblitNetwork()
                except Exception as e:
                    log.warning(f"niblit_network unavailable: {e}")
                    self.network = None
        else:
            self.network = None

        self.sensors = niblit_sensors.NiblitSensors() if niblit_sensors else None
        self.self_maintenance = self_maintenance.SelfMaintenance() if self_maintenance else None
        self.voice = niblit_voice.NiblitVoice() if niblit_voice else None
        self.collector = collector.Collector() if collector else None
        self.trainer = trainer.Trainer(self.collector) if (trainer and self.collector) else None
        self.generator = generator.Generator() if generator else None
        self.membrane = membrane.Membrane() if membrane else None
        self.healer = healer
        self.slsa = slsa_generator
        self.memory = _MemoryManager() if _MemoryManager else None

        # Flags
        self.running = True

        # Interaction log for website output
        self.interactions = []

        # Background loop
        t = threading.Thread(target=self._background_loop, daemon=True)
        t.start()

        log.info("[INFO] NiblitCoreRefactor Initialized successfully.")

    # -------------------------------------------------------
    # Background thread (silent logging)
    def _background_loop(self):
        while self.running:
            try:
                # sensors
                if hasattr(self.sensors, "read_sensors"):
                    self.sensors.read_sensors()
                # self maintenance
                self.self_maintenance.diagnose()
                # training
                self.collector.flush_if_needed()
                self.trainer.step_if_needed()
            except Exception as e:
                log.debug(f"[Background Error] {e}")
            time.sleep(2)

    # -------------------------------------------------------
    # Core update for headless / web
    def update(self):
        try:
            if hasattr(self.sensors, "read_sensors"):
                self.sensors.read_sensors()
            self.memory.autosave()
        except Exception as e:
            log.debug(f"[Update Error] {e}")

    # -------------------------------------------------------
    # Core respond method
    def respond(self, prompt):
        prompt = prompt.strip()
        if not prompt:
            return "..."

        # store user input
        self.collector.add({"type": "utterance", "text": prompt})
        self.interactions.append({"role": "user", "text": prompt})

        # Time request
        if "time" in prompt.lower():
            response = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        # Weather request
        elif "weather" in prompt.lower():
            try:
                response = str(self.network.get_weather())
            except:
                response = "Weather service offline."
        # Memory store
        elif prompt.lower().startswith("remember "):
            try:
                _, rest = prompt.split(" ", 1)
                k, v = rest.split(":", 1)
                self.memory.set(k.strip(), v.strip())
                response = f"Remembered {k.strip()}."
            except:
                response = "Format: remember key: value"
        else:
            # Fallback / LLM response
            try:
                from modules.llm_adapter import LLMAdapter
                llm = LLMAdapter(self.memory)
                response = llm.query(prompt, context=self.interactions)
            except Exception as e:
                response = f"(No LLM) Echo: {prompt[:200]}"

        # Log assistant response
        self.interactions.append({"role": "assistant", "text": response})
        return response

    # -------------------------------------------------------
    # Health/status info
    def status(self):
        uptime = (datetime.utcnow() - self.start_time).total_seconds()
        return {
            "uptime_s": int(uptime),
            "memory_entries": len(self.memory.data) if hasattr(self.memory, "data") else 0,
            "network": "online" if getattr(self.network, "is_online", False) else "offline",
            "bridge": True,
            "persona_tone": "balanced"
        }

    # -------------------------------------------------------
    # Shutdown
    def shutdown(self):
        log.info("Shutting down Niblit...")
        self.running = False
        try:
            self.network.shutdown()
        except:
            pass
        log.info("Niblit Core shutdown complete.")

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] %(message)s")
    print("=== Niblit Core Refactor — interactive shell ===")
    print("Type 'status' for system info, 'time', 'weather', 'remember key: value',")
    print("or any message. 'exit' to quit.\n")
    core = niblitcore()
    while core.running:
        try:
            user = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if not user:
            continue
        if user.lower() in ("exit", "quit", "shutdown"):
            core.shutdown()
            break
        try:
            resp = core.respond(user)
            print(f"Niblit: {resp}")
        except Exception as e:
            print(f"[ERROR] {e}")
