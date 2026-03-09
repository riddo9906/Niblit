#!/usr/bin/env python3
# modules/self_implementer.py — Internal queue + auto-queue loop

import threading
import time
import logging

log = logging.getLogger("SelfImplementer")


class SelfImplementer:
    """
    Persistent execution engine for self-generated plans.
    Consumes implementation plans from DB and internal queue.
    """

    def __init__(self, db, core=None):
        self.db = db
        self.core = core
        self.running = True
        self.poll_interval = 15  # seconds for execution loop
        self.queue = []  # internal queue for dynamic plans
        self.queue_lock = threading.Lock()
        self.auto_queue_interval = 60  # seconds
        self._start_auto_queue_loop()

    # ------------------------------------------
    # MAIN LOOP
    # ------------------------------------------

    def run_loop(self):
        log.info("SelfImplementer loop started.")
        while self.running:
            try:
                self._process_queue_plans()
                self._process_pending_db_plans()
            except Exception as e:
                log.error(f"Execution loop error: {e}")
            time.sleep(self.poll_interval)

    # ------------------------------------------
    # INTERNAL QUEUE
    # ------------------------------------------

    def enqueue_plan(self, plan_text):
        """Add a plan dynamically to the internal queue."""
        with self.queue_lock:
            self.queue.append({
                "key": f"queue:{int(time.time())}",
                "value": plan_text,
                "tags": ["queued"]
            })
        log.info(f"Plan enqueued: {plan_text[:120]}")

    def _process_queue_plans(self):
        with self.queue_lock:
            if not self.queue:
                return
            plans_to_execute = self.queue[:5]
            self.queue = self.queue[5:]  # remove executed batch

        for plan in plans_to_execute:
            self._execute_plan(plan, is_queue=True)

    # ------------------------------------------
    # DB-DRIVEN PLANS
    # ------------------------------------------

    def _process_pending_db_plans(self):
        if not hasattr(self.db, "list_facts"):
            return

        plans = [
            f for f in self.db.list_facts(500)
            if f.get("key", "").startswith("impl:")
            and "executed" not in (f.get("tags") or [])
        ]

        for plan in plans[:5]:
            self._execute_plan(plan, is_queue=False)

    # ------------------------------------------
    # PLAN EXECUTION
    # ------------------------------------------

    def _execute_plan(self, plan, is_queue=False):
        try:
            plan_text = plan.get("value", "")
            log.info(f"Executing plan: {plan_text[:120]}")

            new_tags = (plan.get("tags") or []) + ["executed", "auto_executed"]

            if self.db and not is_queue:
                # Save executed DB plans back to DB
                self.db.add_fact(
                    f"executed:{plan['key']}",
                    plan_text,
                    tags=new_tags
                )
            else:
                # Optionally store executed queue plans to DB
                if self.db:
                    self.db.add_fact(
                        f"executed:{plan['key']}",
                        plan_text,
                        tags=new_tags + ["from_queue"]
                    )
        except Exception as e:
            log.error(f"Plan execution failed: {e}")

    # ------------------------------------------
    # AUTO QUEUE LOOP
    # ------------------------------------------

    def _start_auto_queue_loop(self):
        """Start a background thread that scans DB for new plans and queues them."""
        def auto_queue():
            while self.running:
                try:
                    if hasattr(self.db, "list_facts"):
                        plans = [
                            f for f in self.db.list_facts(500)
                            if (f.get("key", "").startswith("impl:") or f.get("key", "").startswith("idea:"))
                            and "queued" not in (f.get("tags") or [])
                        ]
                        for plan in plans[:10]:
                            self.enqueue_plan(plan.get("value", ""))
                            # mark plan as queued to avoid double enqueue
                            plan["tags"] = (plan.get("tags") or []) + ["queued"]
                except Exception as e:
                    log.error(f"Auto-queue loop error: {e}")
                time.sleep(self.auto_queue_interval)

        t = threading.Thread(target=auto_queue, daemon=True)
        t.start()
        log.info("SelfImplementer auto-queue loop started.")

    # ------------------------------------------
    # STOP LOOP
    # ------------------------------------------

    def stop(self):
        self.running = False
        log.info("SelfImplementer loop stopped.")
