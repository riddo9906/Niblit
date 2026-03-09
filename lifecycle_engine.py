#!/usr/bin/env python3
"""
Lifecycle Engine for Niblit
Integrates Trainer, Tasks, and Orchestrator as living services
with heartbeat, phase tracking, and identity invariants
"""

import threading
import time
from datetime import datetime

# Import your existing scripts
from trainer_full import Trainer
from niblit_tasks import NiblitTasks
from niblit_orchestrator import (
    run_audit,
    run_self_heal,
    generate_fix_guide,
    execute_fix_guide,
    verify_imports,
    hf_task_example,
)
from niblit_memory import MemoryManager

# ─────────────────────────────
# IDENTITY INVARIANTS
# ─────────────────────────────
IDENTITY = {
    "name": "Niblit",
    "version": "1.0.0",
    "core_purpose": "Autonomous AI Orchestrator",
    "author": "Riyaad Behardien",
    "creation_date": "2026-02-09"
}

# ─────────────────────────────
# LIFECYCLE PHASES
# ─────────────────────────────
PHASES = [
    "INIT",             # boot, load modules
    "AUDIT",            # repo audit
    "SELF_HEAL",        # repair inconsistencies
    "TRAIN",            # training phase
    "TASKS",            # task execution & reflection
    "OPTIMIZE",         # preference & config optimization
    "REFLECT",          # memory-based reflection
    "MAINTAIN",         # self-maintenance & lifecycle upkeep
    "IDLE",             # minimal activity, await new tasks
]

# Heartbeat interval in seconds
HEARTBEAT_INTERVAL = 1

class LifecycleEngine:
    def __init__(self):
        self.phase_index = 0
        self.phase = PHASES[self.phase_index]

        # Initialize memory, trainer, and tasks
        self.memory = MemoryManager()
        self.trainer = Trainer(db=self.memory)
        self.tasks = NiblitTasks(brain=None, memory=self.memory)  # Brain integration optional

        self.running = False
        self.lock = threading.Lock()

    # ─────────────────────────────
    # PHASE MANAGEMENT
    # ─────────────────────────────
    def advance_phase(self):
        with self.lock:
            self.phase_index = (self.phase_index + 1) % len(PHASES)
            self.phase = PHASES[self.phase_index]
            self.memory.log_event(f"[Lifecycle] Advanced to phase: {self.phase}")
            print(f"[Lifecycle] Phase: {self.phase}")

    # ─────────────────────────────
    # MAIN LIFECYCLE LOOP
    # ─────────────────────────────
    def heartbeat(self):
        while self.running:
            print(f"[Heartbeat] Current Phase: {self.phase} | Time: {datetime.utcnow().isoformat()}")
            
            # Phase-based behavior
            if self.phase == "INIT":
                # Initialization tasks
                run_audit()
                self.advance_phase()
            
            elif self.phase == "AUDIT":
                # Already handled in INIT
                self.advance_phase()
            
            elif self.phase == "SELF_HEAL":
                run_self_heal()
                self.advance_phase()
            
            elif self.phase == "TRAIN":
                self.trainer.step_if_needed()
                self.advance_phase()
            
            elif self.phase == "TASKS":
                # Run idle thinking if no tasks
                self.tasks.idle_think()
                self.advance_phase()
            
            elif self.phase == "OPTIMIZE":
                # Optimize preferences from memory
                prefs = self.memory.get_preferences()
                prefs["tone"] = "adaptive"
                self.memory.store_preferences(prefs)
                self.memory.log_event("[Lifecycle] Preferences optimized.")
                self.advance_phase()
            
            elif self.phase == "REFLECT":
                # Trigger reflection
                logs = self.memory.get_learning_log()
                if logs:
                    self.memory.log_event("[Lifecycle] Reflection complete.")
                self.advance_phase()
            
            elif self.phase == "MAINTAIN":
                # Generate fix guide & verify imports
                fix_guide = generate_fix_guide()
                execute_fix_guide(fix_guide)
                verify_imports()
                self.advance_phase()
            
            elif self.phase == "IDLE":
                # Heartbeat idle
                time.sleep(1)
                self.advance_phase()
            
            time.sleep(HEARTBEAT_INTERVAL)

    # ─────────────────────────────
    # START / STOP
    # ─────────────────────────────
    def start(self):
        self.running = True
        print("[Lifecycle] Engine starting...")
        t = threading.Thread(target=self.heartbeat, daemon=True)
        t.start()
        self.tasks.start()  # Start task handling
        print("[Lifecycle] Tasks thread started.")

    def stop(self):
        self.running = False
        self.tasks.stop()
        print("[Lifecycle] Engine stopped.")

# ─────────────────────────────
# RUN
# ─────────────────────────────
if __name__ == "__main__":
    engine = LifecycleEngine()
    engine.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        engine.stop()
