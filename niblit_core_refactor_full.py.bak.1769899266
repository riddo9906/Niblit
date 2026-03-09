# niblit_core_refactor.py
import threading, time, logging
from datetime import datetime
import json

# Modules
import niblit_network, self_maintenance, niblit_sensors, niblit_voice
import collector, trainer, generator, membrane, healer, slsa_generator, niblit_memory

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
log = logging.getLogger("NiblitCoreRefactor")

class niblitcore:
    def __init__(self):
        self.name = "Niblit"
        self.start_time = datetime.utcnow()

        log.info("Initializing Niblit core...")

        # Core modules
        try:
            self.network = niblit_network.network
        except:
            self.network = niblit_network.NiblitNetwork()

        self.sensors = niblit_sensors.NiblitSensors()
        self.self_maintenance = self_maintenance.SelfMaintenance()
        self.voice = niblit_voice.NiblitVoice()

        self.collector = collector.Collector()
        self.trainer = trainer.Trainer(self.collector)
        self.generator = generator.Generator()
        self.membrane = membrane.Membrane()
        self.healer = healer
        self.slsa = slsa_generator
        self.memory = niblit_memory.MemoryManager()

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