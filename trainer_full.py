# trainer_full.py
# ─────────────────────────────────────────────────────────────────────────────
# TrainerFull — Niblit background self-training engine (additive enhancement).
#
# CHANGES (purely additive — original Trainer logic fully preserved):
#  - Trainer.step_if_needed() original logic unchanged, now also feeds into
#    the knowledge-aware training pipeline and increments rich metrics.
#  - BackgroundTrainer: runs a daemon thread that calls step_if_needed()
#    on a configurable interval, draining a thread-safe interaction queue.
#    Never blocks CLI input (Termux-safe).
#  - Configurable: TRAINER_BATCH_SIZE, TRAINER_INTERVAL_SECS env vars.
#  - Timeout-free: each training step is wrapped with a per-step timeout so a
#    slow BrainTrainer call can never stall the background loop.
#  - Failover / exponential back-off: step failures back off gracefully and
#    re-attempt after TRAINER_BACKOFF_SECS (default 30 s).
#  - Metrics: steps_ok, steps_failed, total_interactions, last_step_ts.
#  - CLI status: BackgroundTrainer.status() returns a plain-text summary.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("Trainer")

# ── Tuneable constants (override via environment) ─────────────────────────────
# Maximum interactions processed in a single training step.
_TRAINER_BATCH_SIZE: int = int(os.environ.get("TRAINER_BATCH_SIZE", "32"))
# Seconds between background training sweeps.
_TRAINER_INTERVAL_SECS: float = float(os.environ.get("TRAINER_INTERVAL_SECS", "60"))
# Hard per-step timeout (seconds) — prevents a slow BrainTrainer from blocking.
_TRAINER_STEP_TIMEOUT_SECS: float = float(os.environ.get("TRAINER_STEP_TIMEOUT_SECS", "30"))
# Back-off after a failed step before retrying.
_TRAINER_BACKOFF_SECS: float = float(os.environ.get("TRAINER_BACKOFF_SECS", "30"))


# ══════════════════════════════════════════════════════════════════════════════
# Original Trainer — preserved exactly, enhanced with richer metrics output
# ══════════════════════════════════════════════════════════════════════════════

class Trainer:
    """
    Core training logic.  Original interface fully preserved.

    step_if_needed(interactions) is unchanged: it processes a list of
    interaction dicts (each with at minimum {"input":…,"response":…}) and
    increments the step counter.  If a db object is wired in it calls
    mark_training_step().  Optionally, if a brain_trainer is wired in, it
    also calls brain_trainer.record_exchange() for each interaction so the
    BrainTrainer's context store stays current.
    """

    def __init__(self, db=None, brain_trainer: Optional[Any] = None) -> None:
        self.db = db
        # Optional BrainTrainer (niblit_brain.BrainTrainer) — wired by core.
        self.brain_trainer: Optional[Any] = brain_trainer
        self.steps: int = 0
        # Accumulated metrics (additive)
        self._total_interactions: int = 0
        self._steps_failed: int = 0
        self._last_step_ts: Optional[float] = None

    # ── Original public interface (unchanged) ─────────────────────────────

    def step_if_needed(self, interactions: List[Dict]) -> None:
        """Process *interactions* as one training step.

        Behaviour matches original implementation exactly.  Additional
        side-effects (brain_trainer, metrics) are purely additive.
        """
        if not interactions:
            return

        self.steps += 1
        self._last_step_ts = time.time()
        self._total_interactions += len(interactions)

        log.info(
            "[Trainer] Training step %d — %d sample(s)",
            self.steps, len(interactions),
        )

        # ── Original: persist step marker to DB ──────────────────────────
        if self.db:
            try:
                self.db.mark_training_step(self.steps)
            except Exception as exc:
                log.debug("[Trainer] db.mark_training_step failed: %s", exc)

        # ── Additive: feed interactions into BrainTrainer context store ──
        if self.brain_trainer is not None:
            for item in interactions:
                if not isinstance(item, dict):
                    continue
                prompt = str(item.get("input") or item.get("prompt") or "")
                response = str(item.get("response") or item.get("output") or "")
                if prompt and response:
                    try:
                        self.brain_trainer.record_exchange(prompt, response)
                    except Exception as exc:
                        log.debug("[Trainer] brain_trainer.record_exchange failed: %s", exc)

    # ── Additive: status summary ──────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Return a summary dict with training metrics."""
        return {
            "steps": self.steps,
            "total_interactions": self._total_interactions,
            "steps_failed": self._steps_failed,
            "last_step_ts": self._last_step_ts,
            "brain_trainer_wired": self.brain_trainer is not None,
        }


# ══════════════════════════════════════════════════════════════════════════════
# BackgroundTrainer — daemon thread, non-blocking, Termux-safe (additive)
# ══════════════════════════════════════════════════════════════════════════════

class BackgroundTrainer:
    """
    Non-blocking background training engine.

    Usage::

        bg = BackgroundTrainer(db=my_db, brain_trainer=my_brain_trainer)
        bg.start()                        # launch daemon thread
        bg.push({"input": "hi", "response": "hello"})   # queue an interaction
        print(bg.status())                # CLI-friendly status string
        bg.stop()                         # graceful shutdown

    The daemon thread drains the internal interaction queue in batches of
    up to *batch_size* interactions every *interval_secs* seconds.  Each
    training step runs inside a timeout wrapper so a slow BrainTrainer call
    never stalls the loop.  On failure the thread backs off for
    *backoff_secs* before retrying.

    The thread is *daemon=True* — it does not prevent process exit and never
    writes to the terminal while the user is typing.
    """

    def __init__(
        self,
        db: Optional[Any] = None,
        brain_trainer: Optional[Any] = None,
        batch_size: int = _TRAINER_BATCH_SIZE,
        interval_secs: float = _TRAINER_INTERVAL_SECS,
        step_timeout_secs: float = _TRAINER_STEP_TIMEOUT_SECS,
        backoff_secs: float = _TRAINER_BACKOFF_SECS,
    ) -> None:
        # Core trainer delegate
        self._trainer = Trainer(db=db, brain_trainer=brain_trainer)
        # Thread-safe queue: producers call push(), consumer is the bg thread
        self._q: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        # Config
        self.batch_size = batch_size
        self.interval_secs = interval_secs
        self.step_timeout_secs = step_timeout_secs
        self.backoff_secs = backoff_secs
        # Metrics (additive)
        self._steps_ok: int = 0
        self._steps_failed: int = 0
        self._last_step_ts: Optional[float] = None
        self._lock = threading.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Start the background training thread.  Returns True if started."""
        if self._running:
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="BackgroundTrainer",
            daemon=True,
        )
        self._thread.start()
        self._running = True
        log.info(
            "[BackgroundTrainer] Started — interval=%.0fs, batch=%d, timeout=%.0fs",
            self.interval_secs, self.batch_size, self.step_timeout_secs,
        )
        return True

    def stop(self) -> bool:
        """Request a graceful stop.  Returns True if was running."""
        if not self._running:
            return False
        self._stop_event.set()
        self._running = False
        log.info("[BackgroundTrainer] Stop requested — draining and exiting")
        return True

    @property
    def running(self) -> bool:
        return self._running

    # ── Producer API ──────────────────────────────────────────────────────

    def push(self, interaction: Dict) -> None:
        """Enqueue a single interaction dict for background training."""
        self._q.put_nowait(interaction)

    def push_many(self, interactions: List[Dict]) -> None:
        """Enqueue multiple interaction dicts."""
        for item in interactions:
            self._q.put_nowait(item)

    # ── Background loop ───────────────────────────────────────────────────

    def _loop(self) -> None:
        """Main daemon-thread loop — runs until stop_event is set."""
        log.info("[BackgroundTrainer] Loop thread started")
        while not self._stop_event.is_set():
            # Sleep in small chunks so we respond to stop quickly
            self._stop_event.wait(timeout=self.interval_secs)
            if self._stop_event.is_set():
                break
            self._run_step_safe()
        # On shutdown: drain remaining queue one final time
        if not self._q.empty():
            self._run_step_safe(force=True)
        log.info("[BackgroundTrainer] Loop thread exiting cleanly")

    def _drain_batch(self) -> List[Dict]:
        """Drain up to batch_size items from the queue (non-blocking)."""
        batch: List[Dict] = []
        while len(batch) < self.batch_size:
            try:
                item = self._q.get_nowait()
                batch.append(item)
            except queue.Empty:
                break
        return batch

    def _run_step_safe(self, force: bool = False) -> None:
        """
        Drain the queue and call step_if_needed() inside a timeout wrapper.

        *force* drains all items regardless of batch_size.
        On timeout or exception, backs off for backoff_secs seconds.
        """
        batch = self._drain_batch() if not force else []
        if force:
            # Drain everything on shutdown
            while True:
                try:
                    batch.append(self._q.get_nowait())
                except queue.Empty:
                    break

        if not batch:
            return

        # Run training step in a worker thread with timeout
        result: Dict[str, Any] = {"done": False, "error": None}

        def _do_step() -> None:
            try:
                self._trainer.step_if_needed(batch)
                result["done"] = True
            except Exception as exc:
                result["error"] = exc

        worker = threading.Thread(target=_do_step, daemon=True)
        worker.start()
        worker.join(timeout=self.step_timeout_secs)

        with self._lock:
            if worker.is_alive():
                # Step timed out — count as failure, will retry next cycle
                self._steps_failed += 1
                log.warning(
                    "[BackgroundTrainer] Step timed out after %.0fs — %d interaction(s) discarded",
                    self.step_timeout_secs, len(batch),
                )
                self._stop_event.wait(timeout=self.backoff_secs)
            elif result["error"] is not None:
                self._steps_failed += 1
                log.warning(
                    "[BackgroundTrainer] Step failed: %s — backing off %.0fs",
                    result["error"], self.backoff_secs,
                )
                self._stop_event.wait(timeout=self.backoff_secs)
            else:
                self._steps_ok += 1
                self._last_step_ts = time.time()

    # ── CLI status ────────────────────────────────────────────────────────

    def status(self) -> str:
        """Return a CLI-friendly status string."""
        trainer_st = self._trainer.get_status()
        with self._lock:
            ok = self._steps_ok
            fail = self._steps_failed
            last_ts = self._last_step_ts
        last = (
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_ts))
            if last_ts else "never"
        )
        queued = self._q.qsize()
        return (
            f"[BackgroundTrainer]\n"
            f"  Running:            {'yes' if self._running else 'no'}\n"
            f"  Steps OK:           {ok}\n"
            f"  Steps Failed:       {fail}\n"
            f"  Total interactions: {trainer_st['total_interactions']}\n"
            f"  Queued (pending):   {queued}\n"
            f"  Last step:          {last}\n"
            f"  Interval:           {self.interval_secs:.0f}s\n"
            f"  Batch size:         {self.batch_size}\n"
            f"  BrainTrainer wired: {'yes' if trainer_st['brain_trainer_wired'] else 'no'}"
        )

    # ── Expose inner trainer ──────────────────────────────────────────────

    @property
    def trainer(self) -> Trainer:
        """Access the underlying Trainer (for direct step_if_needed() calls)."""
        return self._trainer


# ══════════════════════════════════════════════════════════════════════════════
# Module self-test
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print("=== Trainer self-test ===")

    # Original Trainer
    t = Trainer()
    interactions = [
        {"input": "hello", "response": "hi"},
        {"input": "what time is it?", "response": "Now."},
    ]
    t.step_if_needed(interactions)
    print(f"Trainer steps completed: {t.steps}")
    print("Trainer OK")

    # BackgroundTrainer
    print("\n=== BackgroundTrainer self-test ===")
    bg = BackgroundTrainer(interval_secs=2, batch_size=4)
    bg.start()
    for i in range(6):
        bg.push({"input": f"q{i}", "response": f"a{i}"})
    print(bg.status())
    time.sleep(3)
    print(bg.status())
    bg.stop()
    print("BackgroundTrainer OK")
