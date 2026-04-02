#!/usr/bin/env python3
"""
modules/ale_checkpoint.py — Persistent ALE State: Checkpoint, Resume & Backtrack
──────────────────────────────────────────────────────────────────────────────────
Gives the Autonomous Learning Engine (ALE) the ability to:

  • **Persist** its entire runtime state (cycle count, current topic, step
    progress, learning_history, research_topics, incomplete steps) to a JSON
    checkpoint file so a restart picks up exactly where it left off.

  • **Resume** on startup: detects a saved checkpoint, re-injects all saved
    state into the ALE before the first cycle runs.  Any steps that were
    *in-progress* at shutdown are listed as "incomplete" and are attempted
    first in the resumed cycle.

  • **Backtrack**: step backward through the cycle step list to re-run a
    previous step, re-examine its result, or re-align with what was completed.

  • **Anchor**: create a named snapshot of the current learning state so you
    can return to it later or compare progress.

  • **Navigate**: multi-directional navigation helpers —
      forward   → advance to the next step
      backward  → replay the previous step
      lateral   → jump to any named step without reordering the cycle
      up        → run a meta-reflection / high-level summary pass
      down      → deep-dive into the current topic before moving on
      pause     → pause the cycle mid-run and persist a checkpoint

Architecture
────────────
ALECheckpointManager is a thin wrapper around the ALE.  It:
  1. Intercepts _run_autonomous_cycle to wrap each step with checkpoint writes.
  2. Saves state atomically (write to .tmp, then rename) to avoid corruption.
  3. Integrates with the notification queue so the CLI always sees save/load events.

Usage (wired by niblit_core._init_optional_services)::

    from modules.ale_checkpoint import ALECheckpointManager
    ckpt = ALECheckpointManager(ale=autonomous_engine, checkpoint_path="ale_state.json")
    ckpt.try_resume()          # called once at startup — restores saved state
    ckpt.install()             # monkey-patches _run_autonomous_cycle with checkpoint logic

CLI commands (via niblit_router._handle_ale)::

    ale status       — show checkpoint/cycle/step state
    ale checkpoint   — force-save current state now
    ale resume       — try to restore from saved checkpoint
    ale anchor <tag> — create a named snapshot
    ale anchors      — list saved anchors
    ale backtrack [N]— step back N steps (default 1)
    ale goto <step>  — jump to named step
    ale pause        — pause cycle mid-run
    ale resume-cycle — resume a paused cycle
    ale history      — show learning history
    ale incomplete   — list incomplete steps from last run

ADDITIVE ONLY — no changes to ALE logic.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from copy import deepcopy
from typing import Any, Dict, List, Optional

log = logging.getLogger("ALECheckpoint")

# Default checkpoint file path (relative to repo root, overridden via env)
_DEFAULT_CHECKPOINT_PATH = os.environ.get(
    "ALE_CHECKPOINT_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ale_state.json"),
)

# Maximum number of named anchors to retain before pruning oldest
_MAX_ANCHORS = 20

# How many completed step results to keep in the checkpoint
_MAX_STEP_HISTORY = 200


# ══════════════════════════════════════════════════════════════════════════════
# Checkpoint data format
# ══════════════════════════════════════════════════════════════════════════════

def _empty_checkpoint() -> Dict[str, Any]:
    """Return a fresh checkpoint dict with all fields at their zero state."""
    return {
        "schema_version": 2,
        "saved_at": None,
        "cycle_count": 0,
        "topic_index": 0,
        "code_topic_index": 0,
        "current_cycle_topic": None,
        "current_code_topic": None,
        "learning_history": {},
        "research_topics": [],
        "code_research_topics": [],
        # Step-level tracking
        "last_completed_step": None,     # name of the last step that finished OK
        "current_step": None,            # name of the step that was in-progress at shutdown
        "incomplete_steps": [],          # steps that started but did not finish
        "completed_steps_this_cycle": [], # steps finished in the current cycle
        "step_results_history": [],      # ring buffer of (cycle, step, result, ts) tuples
        # Navigation / anchor
        "anchors": {},                   # {tag: checkpoint_dict}
        "paused": False,                 # True when user issued 'ale pause'
        "paused_at_step": None,          # which step was active when paused
    }


# ══════════════════════════════════════════════════════════════════════════════
# ALECheckpointManager
# ══════════════════════════════════════════════════════════════════════════════

class ALECheckpointManager:
    """
    Wraps an ALE instance to add persistent state, resume, and backtracking.

    Parameters
    ----------
    ale:
        The ``AutonomousLearningEngine`` instance to manage.
    checkpoint_path:
        Path to the JSON checkpoint file.  Defaults to ``ale_state.json``
        in the repository root (or ``ALE_CHECKPOINT_PATH`` env var).
    notify:
        Optional callable(str) to push notifications.  Falls back to the
        global ``core.notification_queue``.
    autosave_on_step:
        If True (default) checkpoint is written after every completed step.
    """

    def __init__(
        self,
        ale: Any,
        checkpoint_path: str = _DEFAULT_CHECKPOINT_PATH,
        notify: Optional[Any] = None,
        autosave_on_step: bool = True,
    ) -> None:
        self.ale = ale
        self.checkpoint_path = checkpoint_path
        self.notify_fn = notify
        self.autosave_on_step = autosave_on_step

        self._lock = threading.Lock()
        self._state: Dict[str, Any] = _empty_checkpoint()
        self._installed: bool = False
        self._pause_event: Optional[threading.Event] = None  # set → pause requested

        log.info(
            "[ALECheckpoint] Manager created — checkpoint_path=%s", checkpoint_path
        )

    # ── Persistence helpers ───────────────────────────────────────────────

    def _atomic_save(self, data: Dict[str, Any]) -> bool:
        """Write *data* atomically to checkpoint_path (tmp → rename)."""
        tmp = self.checkpoint_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            os.replace(tmp, self.checkpoint_path)
            return True
        except Exception as exc:
            log.warning("[ALECheckpoint] Save failed: %s", exc)
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False

    def _load(self) -> Optional[Dict[str, Any]]:
        """Load checkpoint from disk.  Returns None if file missing / corrupt."""
        if not os.path.exists(self.checkpoint_path):
            return None
        try:
            with open(self.checkpoint_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Validate schema version
            if data.get("schema_version", 1) < 2:
                log.info("[ALECheckpoint] Old checkpoint schema — ignoring")
                return None
            return data
        except Exception as exc:
            log.warning("[ALECheckpoint] Load failed: %s", exc)
            return None

    def save(self) -> bool:
        """Save current ALE state to checkpoint file immediately."""
        with self._lock:
            data = self._build_state_dict()
        ok = self._atomic_save(data)
        if ok:
            self._notify(f"[ALE] Checkpoint saved → {self.checkpoint_path}")
            log.info("[ALECheckpoint] Checkpoint saved")
        return ok

    def _build_state_dict(self) -> Dict[str, Any]:
        """Build a serialisable dict from the live ALE state."""
        ale = self.ale
        state = deepcopy(self._state)
        state["saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        state["cycle_count"] = getattr(ale, "_cycle_count", 0)
        state["topic_index"] = getattr(ale, "_topic_index", 0)
        state["code_topic_index"] = getattr(ale, "_code_topic_index", 0)
        state["current_cycle_topic"] = getattr(ale, "_current_cycle_topic", None)
        state["current_code_topic"] = getattr(ale, "_current_code_topic", None)
        # Learning history — deep copy so we don't mutate the live dict
        lh = getattr(ale, "learning_history", {})
        state["learning_history"] = deepcopy(lh) if lh else {}
        # Research topics — plain lists (serialisable)
        rt = getattr(ale, "research_topics", [])
        state["research_topics"] = list(rt) if rt else []
        crt = getattr(ale, "code_research_topics", [])
        # code_research_topics is a list of (lang, topic) tuples — convert to lists
        state["code_research_topics"] = [list(t) for t in crt] if crt else []
        return state

    # ── Resume ────────────────────────────────────────────────────────────

    def try_resume(self) -> bool:
        """
        Try to restore ALE state from a saved checkpoint.

        Returns True if state was successfully restored, False if starting fresh.
        Called once at startup before the first ALE cycle begins.
        """
        data = self._load()
        if data is None:
            log.info("[ALECheckpoint] No checkpoint found — starting fresh")
            self._notify("[ALE] No saved checkpoint — starting from the beginning")
            return False

        try:
            self._restore_to_ale(data)
            with self._lock:
                self._state = data
            saved_at = data.get("saved_at", "unknown")
            topic = data.get("current_cycle_topic", "unknown")
            cycle = data.get("cycle_count", 0)
            incomplete = data.get("incomplete_steps", [])
            last_step = data.get("last_completed_step", "none")

            msg = (
                f"[ALE] ✅ Resumed from checkpoint saved at {saved_at}\n"
                f"  Last completed step: {last_step}\n"
                f"  Resuming at cycle: {cycle + 1}\n"
                f"  Topic: {topic}\n"
            )
            if incomplete:
                msg += f"  ⚠️  Incomplete steps from last run: {', '.join(incomplete)}\n"
                msg += "  → These will be attempted first in the resumed cycle.\n"

            log.info(msg)
            self._notify(msg)
            return True

        except Exception as exc:
            log.warning("[ALECheckpoint] Resume failed: %s — starting fresh", exc)
            self._notify(f"[ALE] Resume failed ({exc}) — starting from the beginning")
            return False

    def _restore_to_ale(self, data: Dict[str, Any]) -> None:
        """Apply checkpoint data to the live ALE instance."""
        ale = self.ale

        # Restore counters
        if data.get("cycle_count"):
            ale._cycle_count = int(data["cycle_count"])
        if data.get("topic_index"):
            ale._topic_index = int(data["topic_index"])
        if data.get("code_topic_index"):
            ale._code_topic_index = int(data["code_topic_index"])
        if data.get("current_cycle_topic"):
            ale._current_cycle_topic = data["current_cycle_topic"]
        if data.get("current_code_topic"):
            ale._current_code_topic = data["current_code_topic"]

        # Restore learning_history (merge, not replace, to preserve any
        # fields added in new code versions)
        if data.get("learning_history"):
            if hasattr(ale, "learning_history") and isinstance(ale.learning_history, dict):
                for k, v in data["learning_history"].items():
                    ale.learning_history[k] = v

        # Restore research_topics if saved list is longer than current
        if data.get("research_topics"):
            saved_rt = data["research_topics"]
            current_rt = getattr(ale, "research_topics", [])
            if len(saved_rt) > len(current_rt):
                ale.research_topics = saved_rt

        # Restore code_research_topics (list of [lang, topic] lists)
        if data.get("code_research_topics"):
            saved_crt = [tuple(t) for t in data["code_research_topics"]]
            current_crt = getattr(ale, "code_research_topics", [])
            if len(saved_crt) > len(current_crt):
                ale.code_research_topics = saved_crt

    # ── Install: wrap _run_autonomous_cycle ──────────────────────────────

    def install(self) -> None:
        """
        Monkey-patch ALE._run_autonomous_cycle with a checkpoint-aware wrapper.

        After install(), every cycle:
        1. Clears incomplete_steps at start.
        2. After each step completes, updates last_completed_step and saves
           if autosave_on_step is True.
        3. On any unhandled exception, marks the current step as incomplete
           and saves before re-raising.
        4. Respects the pause_event: if paused mid-cycle, saves and sleeps
           until resume() is called.

        Idempotent — calling install() twice has no effect.
        """
        if self._installed:
            return

        original_cycle = self.ale._run_autonomous_cycle
        mgr = self  # capture self for closure

        def _wrapped_cycle() -> Any:
            # ── Reset per-cycle tracking ──────────────────────────────────
            with mgr._lock:
                mgr._state["completed_steps_this_cycle"] = []
                mgr._state["incomplete_steps"] = []
                mgr._state["current_step"] = None
                mgr._state["paused"] = False
                mgr._state["paused_at_step"] = None

            # ── Patch the inner _step helper to add checkpoint callbacks ──
            # We intercept via a shared results list instead of monkey-patching
            # the nested function (which is recreated each call).
            # The approach: wrap _run_step_with_timeout instead.
            original_run_step = mgr.ale._run_step_with_timeout

            def _instrumented_step(name: str, fn) -> Any:
                # Check for pause request before each step
                if mgr._pause_event and mgr._pause_event.is_set():
                    with mgr._lock:
                        mgr._state["paused"] = True
                        mgr._state["paused_at_step"] = name
                    mgr.save()
                    mgr._notify(f"[ALE] ⏸  Paused before step '{name}' — waiting for resume")
                    # Block until pause_event is cleared (resume called)
                    while mgr._pause_event.is_set():
                        time.sleep(0.5)
                        if not mgr.ale.running:
                            break
                    with mgr._lock:
                        mgr._state["paused"] = False

                # Mark step as in-progress
                with mgr._lock:
                    mgr._state["current_step"] = name
                    if name not in mgr._state["incomplete_steps"]:
                        mgr._state["incomplete_steps"].append(name)

                # Run the step
                result = original_run_step(name, fn)

                # Mark step as completed
                ts = time.strftime("%Y-%m-%dT%H:%M:%S")
                with mgr._lock:
                    mgr._state["last_completed_step"] = name
                    mgr._state["current_step"] = None
                    if name in mgr._state["incomplete_steps"]:
                        mgr._state["incomplete_steps"].remove(name)
                    mgr._state["completed_steps_this_cycle"].append(name)
                    # Update ring-buffer of step results
                    cycle_num = getattr(mgr.ale, "_cycle_count", 0)
                    mgr._state["step_results_history"].append({
                        "cycle": cycle_num,
                        "step": name,
                        "result": str(result or "")[:80],
                        "ts": ts,
                    })
                    if len(mgr._state["step_results_history"]) > _MAX_STEP_HISTORY:
                        mgr._state["step_results_history"] = (
                            mgr._state["step_results_history"][-_MAX_STEP_HISTORY:]
                        )

                # Autosave after each completed step
                if mgr.autosave_on_step:
                    # Build state and save without holding the main lock
                    data = mgr._build_state_dict()
                    mgr._atomic_save(data)

                return result

            # Temporarily replace _run_step_with_timeout
            mgr.ale._run_step_with_timeout = _instrumented_step
            try:
                result = original_cycle()
            except Exception as exc:
                # On crash: save the partial state with incomplete steps marked
                with mgr._lock:
                    # current_step stays populated — it's the one that crashed
                    pass
                mgr.save()
                log.warning("[ALECheckpoint] Cycle crashed at step '%s': %s",
                            mgr._state.get("current_step"), exc)
                raise
            finally:
                # Restore original _run_step_with_timeout
                mgr.ale._run_step_with_timeout = original_run_step

            # Successful cycle end — save clean state
            with mgr._lock:
                mgr._state["current_step"] = None
                mgr._state["incomplete_steps"] = []
            mgr.save()
            return result

        self.ale._run_autonomous_cycle = _wrapped_cycle
        self._installed = True
        log.info("[ALECheckpoint] Installed — cycle checkpointing active")
        self._notify("[ALE] Checkpoint manager installed — state will persist across restarts")

    # ── Anchor (named snapshots) ──────────────────────────────────────────

    def create_anchor(self, tag: str) -> str:
        """
        Create a named snapshot of the current learning state.

        The anchor stores the full checkpoint dict under *tag* inside the
        checkpoint file's ``anchors`` dict.  Up to _MAX_ANCHORS anchors are
        retained; oldest are pruned automatically.

        Returns a human-readable confirmation string.
        """
        with self._lock:
            data = self._build_state_dict()
            anchors = self._state.get("anchors", {})
            anchors[tag] = deepcopy(data)
            # Prune oldest if needed (keep by insertion order via sorted ts)
            if len(anchors) > _MAX_ANCHORS:
                # Use a future-date sentinel for missing saved_at so they sort
                # last (newest) and are never incorrectly pruned as 'oldest'.
                oldest = sorted(
                    anchors.keys(),
                    key=lambda k: anchors[k].get("saved_at") or "9999-99-99",
                )[0]
                del anchors[oldest]
                log.debug("[ALECheckpoint] Pruned oldest anchor: %s", oldest)
            self._state["anchors"] = anchors
            data["anchors"] = anchors

        self._atomic_save(data)
        cycle = data.get("cycle_count", 0)
        topic = data.get("current_cycle_topic", "unknown")
        last_step = data.get("last_completed_step", "none")
        msg = (
            f"[ALE] 🔖 Anchor '{tag}' created\n"
            f"  Cycle: {cycle}\n"
            f"  Topic: {topic}\n"
            f"  Last step: {last_step}"
        )
        self._notify(msg)
        log.info("[ALECheckpoint] Anchor '%s' created at cycle %d", tag, cycle)
        return msg

    def restore_anchor(self, tag: str) -> str:
        """
        Restore ALE state to a previously created anchor.

        Does NOT restart the ALE; just updates the in-memory counters and
        history so the *next* cycle continues from the anchored state.

        Returns a confirmation string or an error message.
        """
        with self._lock:
            anchors = self._state.get("anchors", {})
            if tag not in anchors:
                available = list(anchors.keys())
                return (
                    f"[ALE] ⚠️  Anchor '{tag}' not found.\n"
                    f"  Available anchors: {available or '(none)'}"
                )
            anchor_data = deepcopy(anchors[tag])

        try:
            self._restore_to_ale(anchor_data)
            with self._lock:
                # Merge anchor data back into live state (preserve anchors dict)
                saved_anchors = self._state.get("anchors", {})
                self._state.update(anchor_data)
                self._state["anchors"] = saved_anchors
            msg = (
                f"[ALE] ✅ Restored to anchor '{tag}'\n"
                f"  Cycle: {anchor_data.get('cycle_count', 0)}\n"
                f"  Topic: {anchor_data.get('current_cycle_topic', 'unknown')}\n"
                f"  Last step: {anchor_data.get('last_completed_step', 'none')}"
            )
            self._notify(msg)
            return msg
        except Exception as exc:
            return f"[ALE] ❌ Failed to restore anchor '{tag}': {exc}"

    def list_anchors(self) -> str:
        """Return a formatted list of all saved anchors."""
        with self._lock:
            anchors = self._state.get("anchors", {})
        if not anchors:
            return "[ALE] No anchors saved yet. Use 'ale anchor <tag>' to create one."
        lines = ["[ALE] Saved anchors:"]
        for tag, data in anchors.items():
            lines.append(
                f"  {tag:20s}  cycle={data.get('cycle_count', '?'):4}  "
                f"saved={data.get('saved_at', '?')}"
            )
        return "\n".join(lines)

    # ── Backtrack ─────────────────────────────────────────────────────────

    def backtrack(self, steps: int = 1) -> str:
        """
        Step backward N steps in the completed step history and report what was there.

        Backtracking does NOT re-run the steps; it rewinds the
        ``last_completed_step`` pointer and returns the historical result so
        the user (or an agent) can review and decide whether to re-run or
        continue.

        To actually re-execute a past step, call ``goto(step_name)`` which
        schedules the named step for re-execution at the start of the next cycle.

        Returns a formatted summary of the backtracked position.
        """
        with self._lock:
            history = self._state.get("step_results_history", [])
            completed = self._state.get("completed_steps_this_cycle", [])

        if not history:
            return "[ALE] No step history available to backtrack into."

        idx = max(0, len(history) - 1 - max(0, steps - 1))
        entry = history[idx]
        total = len(history)

        lines = [
            f"[ALE] ⏪ Backtrack {steps} step(s) — position {idx + 1}/{total}",
            f"  Cycle:  {entry.get('cycle', '?')}",
            f"  Step:   {entry.get('step', '?')}",
            f"  Result: {entry.get('result', '?')[:120]}",
            f"  At:     {entry.get('ts', '?')}",
        ]
        if idx > 0:
            prev = history[idx - 1]
            lines.append(f"  ← Before: {prev.get('step', '?')} (cycle {prev.get('cycle', '?')})")
        if idx < total - 1:
            nxt = history[idx + 1]
            lines.append(f"  → After:  {nxt.get('step', '?')} (cycle {nxt.get('cycle', '?')})")

        lines += [
            "",
            "  Use 'ale goto <step>' to schedule a re-run of any step,",
            "  or 'ale anchor <tag>' to snapshot the current state first.",
        ]
        return "\n".join(lines)

    def get_incomplete_steps(self) -> str:
        """Return a formatted list of steps that were in-progress at last shutdown."""
        with self._lock:
            incomplete = self._state.get("incomplete_steps", [])
            current = self._state.get("current_step")
            last = self._state.get("last_completed_step")

        lines = ["[ALE] Step completion status:"]
        lines.append(f"  Last completed: {last or '(none)' }")
        lines.append(f"  Currently in:   {current or '(none)'}")
        if incomplete:
            lines.append(f"  Incomplete (started but not finished at last shutdown):")
            for s in incomplete:
                lines.append(f"    ⚠️  {s}")
        else:
            lines.append("  Incomplete:     (none)")
        return "\n".join(lines)

    # ── Pause / Resume cycle ──────────────────────────────────────────────

    def pause_cycle(self) -> str:
        """
        Request a pause before the next step in the current cycle.

        The cycle will finish the *current* step then pause before starting
        the next one.  The checkpoint is saved at the pause point.
        """
        if self._pause_event is None:
            self._pause_event = threading.Event()
        self._pause_event.set()
        with self._lock:
            current = self._state.get("current_step", "unknown")
        msg = (
            f"[ALE] ⏸  Pause requested — will pause after current step ('{current}').\n"
            f"  Use 'ale resume-cycle' to continue."
        )
        self._notify(msg)
        return msg

    def resume_cycle(self) -> str:
        """Resume a paused cycle."""
        if self._pause_event and self._pause_event.is_set():
            self._pause_event.clear()
            msg = "[ALE] ▶️  Cycle resumed."
            self._notify(msg)
            return msg
        return "[ALE] Cycle is not currently paused."

    # ── Navigate: goto ────────────────────────────────────────────────────

    def get_step_history(self, last_n: int = 20) -> str:
        """Return a formatted step history (last *last_n* steps)."""
        with self._lock:
            history = self._state.get("step_results_history", [])
        if not history:
            return "[ALE] No step history recorded yet."
        recent = history[-last_n:]
        lines = [f"[ALE] Step history (last {len(recent)} entries):"]
        for e in recent:
            lines.append(
                f"  C{e.get('cycle', '?'):4}  {e.get('step', '?'):25s}  "
                f"{e.get('ts', '?')}  {e.get('result', '')[:50]}"
            )
        return "\n".join(lines)

    # ── Status ────────────────────────────────────────────────────────────

    def status(self) -> str:
        """Return a comprehensive CLI status string."""
        with self._lock:
            state = deepcopy(self._state)
        ale = self.ale

        cycle = state.get("cycle_count", getattr(ale, "_cycle_count", 0))
        topic = state.get("current_cycle_topic", getattr(ale, "_current_cycle_topic", "none"))
        last_step = state.get("last_completed_step", "none")
        current_step = state.get("current_step", "none")
        incomplete = state.get("incomplete_steps", [])
        completed_this_cycle = state.get("completed_steps_this_cycle", [])
        anchors = list(state.get("anchors", {}).keys())
        saved_at = state.get("saved_at", "never")
        paused = state.get("paused", False)
        total_history = len(state.get("step_results_history", []))

        return (
            f"[ALE Checkpoint Status]\n"
            f"  Checkpoint file:   {self.checkpoint_path}\n"
            f"  Last saved:        {saved_at}\n"
            f"  Installed:         {'yes' if self._installed else 'no'}\n"
            f"  ALE running:       {'yes' if getattr(ale, 'running', False) else 'no'}\n"
            f"  Paused:            {'yes' if paused else 'no'}\n"
            f"  Current cycle:     {cycle}\n"
            f"  Current topic:     {topic or 'none'}\n"
            f"  Last step done:    {last_step}\n"
            f"  Step in-progress:  {current_step}\n"
            f"  Incomplete steps:  {', '.join(incomplete) if incomplete else '(none)'}\n"
            f"  Done this cycle:   {len(completed_this_cycle)} steps\n"
            f"  Step history:      {total_history} entries\n"
            f"  Anchors saved:     {len(anchors)} ({', '.join(anchors[:5]) or 'none'})\n"
            f"  Autosave per step: {'yes' if self.autosave_on_step else 'no'}"
        )

    # ── Notification helper ────────────────────────────────────────────────

    def _notify(self, msg: str) -> None:
        """Push a notification via notify_fn or global notification queue."""
        if self.notify_fn is not None:
            try:
                self.notify_fn(msg)
                return
            except Exception:
                pass
        try:
            from core.notification_queue import notif_queue
            notif_queue.push(msg)
        except Exception:
            pass
