# orchestrator.py
# NiblitOS v5.1 — Unified Orchestration Layer
# Handles: module loading, token load, routing, evolve, fallback, repair, adapter control.

import importlib
import os
import json
import logging

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        pass  # python-dotenv not installed — env vars loaded from environment

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("NiblitOS")

# --------------------------------------------------------
# Load tokens from .env or environment variables
# --------------------------------------------------------
def load_tokens():
    load_dotenv()
    tokens = {
        "HF_TOKEN": os.getenv("HF_TOKEN", None),
        "HF_API": os.getenv("HF_API", "https://api-inference.huggingface.co/models"),
        "OPENAI_KEY": os.getenv("OPENAI_API_KEY", None),
        "LOCAL_MODEL_PATH": os.getenv("LOCAL_MODEL_PATH", None)
    }

    for key, value in tokens.items():
        if value:
            log.info(f"[OK] {key} loaded.")
        else:
            log.warning(f"[MISSING] {key} not found.")

    return tokens

TOKENS = load_tokens()

# --------------------------------------------------------
# Safe Module Loader (Auto repair + fallback to stubs)
# --------------------------------------------------------
def load_module(name, fallback=None):
    try:
        module = importlib.import_module(name)
        log.info(f"Loaded {name}")
        return module
    except Exception as e:
        log.warning(f"Module {name} not found or failed to load: {e}")
        if fallback:
            log.info(f"Using fallback stub for {name}.")
            return fallback
        return None

# --------------------------------------------------------
# Import internal modules (auto fallback)
# --------------------------------------------------------
repo_audit = load_module("tools.repo_audit")
structural_helper = load_module("tools.structural_helper")
evolve_engine = load_module("modules.evolve")
hf_adapter = load_module("modules.llm_adapter")
internet_manager = load_module("modules.internet_manager")
self_heal = load_module("tools.self_heal_auto")
fixgen = load_module("tools.FixGuideGenerator")
researcher = load_module("modules.researcher_engine")

# --------------------------------------------------------
# COMMAND ROUTER — The heart of the system
# --------------------------------------------------------
class NiblitRouter:

    def __init__(self):
        self.context = []
        self.memory = load_module("niblit_memory", fallback=None)
        self.tokens = TOKENS
        self.llm = hf_adapter if hf_adapter else None
        self.net = internet_manager if internet_manager else None
        self.evolver = evolve_engine if evolve_engine else None
        self.research = researcher if researcher else None

    # Send request to best available LLM
    def ask_llm(self, text, mode="general"):
        if self.llm:
            return self.llm.query(text, mode=mode)
        return {"error": "No LLM adapter available."}

    # Use researcher engine
    def research_query(self, topic):
        if self.research:
            return self.research.run(topic)
        return {"error": "Research module missing."}

    # Run evolve cycle
    def evolve(self):
        if self.evolver:
            return self.evolver.step()
        return {"error": "Evolve engine missing."}

    # Auto fix system
    def repair(self):
        if self_heal:
            return self_heal.repair_all()

        return {"error": "Self-heal module missing."}

    # Process CLI commands
    def handle(self, cmd):
        cmd = cmd.strip().lower()

        if cmd == "help":
            return """
Commands:
    ask <text>           — Query the LLM
    research <topic>     — Deep research engine
    evolve               — Start evolve cycle
    repair               — Auto system repair
    context              — Show memory context
    clear                — Clear screen
    exit                 — Quit Niblit
"""

        if cmd.startswith("ask "):
            text = cmd[4:]
            return self.ask_llm(text)

        if cmd.startswith("research "):
            topic = cmd[len("research "):]
            return self.research_query(topic)

        if cmd == "evolve":
            return self.evolve()

        if cmd == "repair":
            return self.repair()

        if cmd == "context":
            return self.context

        if cmd == "exit":
            return "exit"

        return {"error": "Unknown command"}

# --------------------------------------------------------
# BOOTSTRAP — Called by main.py
# --------------------------------------------------------
def boot():
    print("""
NIBLIT OS v5.1 — Neural Internal BIOS Logic & Integrated Thinking OS
Self-Learning Neural Runtime • Modular • Expandable • Device-Adaptive
-------------------------------------------------------------------
    """)
    return NiblitRouter()


if __name__ == "__main__":
    import sys
    print("=== Niblit Orchestrator (NiblitOS v5.1) ===")
    tokens = load_tokens()
    hf_ok = bool(tokens.get("HF_TOKEN"))
    print(f"HF token present: {hf_ok}")
    print("Booting NiblitRouter via orchestrator...")
    router = boot()
    print(f"Router ready: {router.__class__.__name__}")
    print("\nType a message, 'help' for commands, or 'exit' to quit.\n")
    while True:
        try:
            user = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if not user:
            continue
        response = router.handle(user)
        if response == "exit":
            print("Bye.")
            break
        if isinstance(response, dict):
            import json as _json
            print("Niblit:", _json.dumps(response, indent=2, default=str))
        else:
            print("Niblit:", response)
