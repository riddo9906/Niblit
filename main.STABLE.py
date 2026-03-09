#!/usr/bin/env python3

"""
NIBLIT AIOS — MAIN BOOTSTRAP FILE
RIYAAD BEHARDIEN EDITION
Fully Modular • Self-Healing • Device Adaptive
"""

import traceback

from niblit_identity import NiblitIdentity
from niblit_router import NiblitRouter
from niblit_brain import NiblitBrain
from niblit_memory import MemoryManager
from niblit_io import NiblitIO
from niblit_guard import NiblitGuard
from niblit_learning import NiblitLearning
from niblit_tasks import NiblitTasks


# ─────────────────────────────────────────────────────
#  BOOTSTRAP SYSTEM
# ─────────────────────────────────────────────────────

def boot():
    io = NiblitIO()

    io.out("===========================================")
    io.out("      NIBLIT OS v5 — AIOS RUNTIME")
    io.out("    Neural Internal BIOS Logic System")
    io.out("===========================================")

    # 1. IDENTITY CHECK
    identity = NiblitIdentity()
    if identity.verify():
        io.out("[IDENTITY] Verified system identity ✔")
    else:
        io.error("[IDENTITY] Verification FAILED ❌")
        io.error("System continuing in SAFE MODE.")

    # 2. INITIALIZE CORE MODULES (ORDER MATTERS)
    memory = MemoryManager()
    brain = NiblitBrain(memory)
    router = NiblitRouter(brain, memory)

    guard = NiblitGuard()
    learning = NiblitLearning(memory)
    tasks = NiblitTasks(brain, memory)

    # 3. START BACKGROUND SYSTEMS
    tasks.start()
    router.start()

    io.out("[BOOT] Core modules online ✔")
    io.out("[BOOT] Brain ready ✔")
    io.out("[BOOT] Router ready ✔")
    io.out("[BOOT] Memory loaded ✔")
    io.out("[BOOT] Learning online ✔")
    io.out("[BOOT] Tasks active ✔\n")

    return router, io


# ─────────────────────────────────────────────────────
#  INTERACTIVE SHELL
# ─────────────────────────────────────────────────────

def run_shell(router, io):
    io.out("Type 'exit' to quit.\n")

    while True:
        try:
            user_input = input("Niblit > ").strip()

            if user_input.lower() in ["exit", "quit"]:
                io.out("Shutting down Niblit OS…")
                return

            router.process(user_input)

        except KeyboardInterrupt:
            io.out("\n[CTRL+C] Interrupt received.")
            io.out("Type 'exit' to close.")
        except Exception as e:
            io.error("[RUNTIME ERROR] " + str(e))
            traceback.print_exc()


# ─────────────────────────────────────────────────────
#  MAIN ENTRY
# ─────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        router, io = boot()
        run_shell(router, io)
    except Exception as e:
        print("[FATAL BOOT ERROR]", e)
        traceback.print_exc()
        print("System attempting fallback self-heal…")
