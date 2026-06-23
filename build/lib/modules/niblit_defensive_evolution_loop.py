"""
modules/niblit_defensive_evolution_loop.py — Niblit Defensive Evolution Loop v1
================================================================================
Purely ADDITIVE evolutionary layer that sits on top of ``MembraneOrchestrator``.

This module does NOT replace any existing security layer.  It acts as an
autonomous immune-system loop that:

  1. Ingests high-severity ThreatEvents from the running membrane
  2. Converts them into structured ``AttackGenome`` objects
  3. Replays them in an **isolated sandbox** (fresh membrane — never touches
     the production singleton)
  4. Mutates genomes to generate stronger / variant attacks
  5. Self-attacks the sandbox to discover bypasses BEFORE real attackers do
  6. Feeds any bypass back into ``InputGuard`` (dynamic rules) and
     ``AdaptiveFirewall`` (genome learning)
  7. Loops back continuously in a lightweight daemon thread

Architecture
------------
  Detect (existing membrane)
        ↓
  AttackGenome capture
        ↓
  SandboxReplayer (isolated, non-production)
        ↓
  AttackMutationEngine  (obfuscate | time_shift | layer_bypass | combine)
        ↓
  Self-attack loop (stress-test sandbox with mutated variants)
        ↓
  Bypass discovered  →  InputGuard.add_pattern() + AdaptiveFirewall.learn()
        ↓
  Loop back (daemon thread, rate-limited)

Safety governor
---------------
  MAX_MUTATION_DEPTH     — stop recursion at depth 5  (env: NIBLIT_MAX_MUTATION_DEPTH)
  MAX_SANDBOX_ITERATIONS — max 20 sandbox runs / cycle (env: NIBLIT_MAX_SANDBOX_ITER)
  MAX_CPU_EVO_LOAD       — pause when 1-min load > 0.65 (env: NIBLIT_MAX_CPU_EVO_LOAD)
  CYCLE_INTERVAL_SECS    — min 60s between auto-cycles (env: NIBLIT_EVO_CYCLE_INTERVAL)

Integration
-----------
  niblit_cyber_membrane.MembraneOrchestrator._store_threat() calls
      self.evolution_loop.trigger(evt)  when severity >= 0.75

  niblit_core wires self.evolution_loop singleton and calls .start().
  niblit_router exposes 'evolution' / 'evo' commands.

Singleton access via ``get_evolution_loop(membrane)``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple

log = logging.getLogger("niblit.evolution_loop")

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (ValueError, TypeError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (ValueError, TypeError):
        return default


# ── Safety / tuning constants ──────────────────────────────────────────────────
_MAX_MUTATION_DEPTH     = _env_int("NIBLIT_MAX_MUTATION_DEPTH",  5)
_MAX_SANDBOX_ITERATIONS = _env_int("NIBLIT_MAX_SANDBOX_ITER",    20)
_MAX_CPU_EVO_LOAD       = _env_float("NIBLIT_MAX_CPU_EVO_LOAD",  0.65)
_CYCLE_INTERVAL_SECS    = _env_int("NIBLIT_EVO_CYCLE_INTERVAL",  60)
_QUEUE_MAX              = _env_int("NIBLIT_EVO_QUEUE_MAX",        200)
_GENOME_MEMORY_MAX      = _env_int("NIBLIT_EVO_GENOME_MEM",       1000)
_SEVERITY_TRIGGER       = _env_float("NIBLIT_EVO_TRIGGER_SEV",   0.75)
_BG_POLL_INTERVAL       = _env_int("NIBLIT_EVO_POLL_SECS",        10)


# ─────────────────────────────────────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────────────────────────────────────

def _get_cpu_load() -> float:
    """
    Return normalised 1-minute load average (0.0 = idle, 1.0 = fully loaded).
    Returns 0.0 on platforms without ``os.getloadavg()``.
    """
    try:
        load1, _, _ = os.getloadavg()
        cpus = max(os.cpu_count() or 1, 1)
        return load1 / cpus
    except (AttributeError, OSError):
        return 0.0


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────────────
# 1. AttackGenome
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AttackGenome:
    """
    Structured metadata extracted from a detected threat event.

    Every real (or simulated) attack is captured as a genome that can be:
    * Replayed in a sandbox
    * Mutated to generate stronger variants
    * Stored in memory for combination attacks
    """
    id: str                  = field(default_factory=lambda: uuid.uuid4().hex[:12])
    threat_type: str         = ""
    entry_vector: str        = ""           # reconstructed attack payload / command
    payload_signature: str   = ""           # short hash-fingerprint of the payload
    timing_pattern: str      = "normal"     # normal | slow | burst | timing_oracle
    target_layer: str        = ""           # InputGuard | StealthDetector | etc.
    success_probability: float = 0.0        # 0 = caught, 1 = likely bypass
    detected_by: List[str]   = field(default_factory=list)
    severity_score: float    = 0.0
    generation: int          = 0            # mutation depth (0 = original capture)
    parent_id: str           = ""
    ts: float                = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.threat_type,
            "entry_vector": self.entry_vector[:200],
            "payload_signature": self.payload_signature[:32],
            "timing_pattern": self.timing_pattern,
            "target_layer": self.target_layer,
            "success_probability": round(self.success_probability, 3),
            "detected_by": self.detected_by,
            "severity_score": round(self.severity_score, 3),
            "generation": self.generation,
            "parent_id": self.parent_id,
        }


# ─────────────────────────────────────────────────────────────────────────────
# 2. SandboxResult
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SandboxResult:
    """Result of replaying an attack genome in an isolated sandbox."""
    genome_id: str
    bypassed_defense: bool
    risk_score: float
    blocked_by: str       # which layer blocked it (empty if bypassed)
    failing_layer: str    # layer that *failed* to catch it (empty if blocked)
    details: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# 3. SandboxReplayer
# ─────────────────────────────────────────────────────────────────────────────

class SandboxReplayer:
    """
    Replays attack genomes against a completely isolated membrane instance.

    Each ``replay()`` call creates a **fresh** ``MembraneOrchestrator`` that is
    never the production singleton.  This guarantees:

    * Production state is never modified by simulated attacks
    * Each replay starts from a clean state
    * TrackerSensor and IntegrityMonitor are skipped (IO-bound, not needed here)
    """

    def replay(self, genome: AttackGenome) -> SandboxResult:
        """
        Replay *genome* in an isolated sandbox membrane.

        Returns ``SandboxResult.bypassed_defense = True`` if the attack
        would not be blocked by the current detection logic.
        """
        try:
            from modules.niblit_cyber_membrane import MembraneOrchestrator
            sandbox = MembraneOrchestrator()
        except Exception as exc:
            log.debug("[SandboxReplayer] Cannot create sandbox: %s", exc)
            return SandboxResult(
                genome_id=genome.id,
                bypassed_defense=False,
                risk_score=0.0,
                blocked_by="sandbox_error",
                failing_layer="",
                details=str(exc)[:200],
            )

        payload = self._reconstruct_payload(genome)
        try:
            result = sandbox.inspect_input(
                ip="sandbox_replay_internal",
                command=payload,
                payload={"text": payload},
                skip_layers={"tracker", "integrity", "session"},  # skip IO-bound layers
            )
        except Exception as exc:
            log.debug("[SandboxReplayer] inspect_input error: %s", exc)
            return SandboxResult(
                genome_id=genome.id,
                bypassed_defense=False,
                risk_score=0.0,
                blocked_by="sandbox_exception",
                failing_layer="",
                details=str(exc)[:200],
            )

        # A bypass = allowed AND low risk score
        bypassed = result.allowed and result.risk_score < 0.4
        return SandboxResult(
            genome_id=genome.id,
            bypassed_defense=bypassed,
            risk_score=result.risk_score,
            blocked_by="" if bypassed else (result.threat_type or "membrane"),
            failing_layer=genome.target_layer if bypassed else "",
            details=result.reason,
        )

    @staticmethod
    def _reconstruct_payload(genome: AttackGenome) -> str:
        """Reconstruct a minimal attack string from the genome."""
        return (genome.entry_vector or genome.payload_signature
                or f"[genome:{genome.threat_type}:{genome.id}]")


# ─────────────────────────────────────────────────────────────────────────────
# 4. AttackMutationEngine
# ─────────────────────────────────────────────────────────────────────────────

class AttackMutationEngine:
    """
    Generates variant attack genomes from a base genome.

    Four mutation strategies
    ------------------------
    1. ``obfuscate_syntax``   — encoding / case / comment tricks per attack type
    2. ``time_shift_payload`` — change timing metadata (slow/burst/oracle)
    3. ``layer_bypass_attempt`` — route around a specific detection layer
    4. ``combine_vectors``    — merge two genomes into a multi-vector attack

    Respects ``_MAX_MUTATION_DEPTH`` — returns empty list if exceeded.
    """

    # Type-specific obfuscation substitution tables
    _SQL_OBF = [
        ("select", "SEL/**/ECT"), ("union", "UN/**/ION"), ("drop", "DR/**/OP"),
        ("--", "#"),  ("or ", "OR%20"),  ("1=1", "1 = 1"),
    ]
    _SHELL_OBF = [
        ("bash", "b'a's'h'"), ("sh ", "$'sh' "), (";", "%3b"),
        ("|", "%7c"), ("../", "..%2f"), ("wget", "w\x00get"),
    ]
    _PROMPT_OBF = [
        ("ignore", "ign0re"), ("instructions", "instruct1ons"),
        ("previous", "pr\u0435vious"),   # Cyrillic е
        ("system", "syst\u0435m"), ("jailbreak", "ja1lbreak"),
        ("disregard", "disreg4rd"),
    ]
    _TRAVERSAL_OBF = [
        ("../", "%2e%2e%2f"), ("..", "%2e%2e"),
        ("/etc/", "%2fetc%2f"), ("passwd", "p\x00asswd"),
    ]
    _TIMING_CYCLE = ["normal", "slow", "burst", "timing_oracle"]

    def mutate(
        self,
        genome: AttackGenome,
        other: Optional[AttackGenome] = None,
    ) -> List[AttackGenome]:
        """
        Generate up to 4 mutated variants of *genome*.
        Returns empty list when ``genome.generation >= _MAX_MUTATION_DEPTH``.
        """
        if genome.generation >= _MAX_MUTATION_DEPTH:
            return []

        variants: List[AttackGenome] = []
        for fn in (
            self._obfuscate_syntax,
            self._time_shift,
            self._layer_bypass,
        ):
            v = fn(genome)
            if v is not None:
                variants.append(v)

        if other is not None:
            v4 = self._combine_vectors(genome, other)
            if v4 is not None:
                variants.append(v4)

        return variants

    # ── Mutation strategies ──────────────────────────────────────────────────

    def _obfuscate_syntax(self, genome: AttackGenome) -> Optional[AttackGenome]:
        """Apply type-specific syntax obfuscation to the entry vector."""
        payload = genome.entry_vector or genome.payload_signature
        if not payload:
            return None

        ttype = genome.threat_type
        new_payload = payload

        if "sqli" in ttype:
            table = self._SQL_OBF
        elif "shell" in ttype:
            table = self._SHELL_OBF
        elif "prompt" in ttype:
            table = self._PROMPT_OBF
        elif "path" in ttype or "traversal" in ttype:
            table = self._TRAVERSAL_OBF
        else:
            # Generic: insert zero-width space after every 5th character
            chars = list(payload)
            for i in range(4, len(chars), 5):
                chars.insert(i, "\u200b")
            new_payload = "".join(chars)
            table = []

        for src, dst in table:
            if src.lower() in new_payload.lower():
                new_payload = re.sub(
                    re.escape(src), dst, new_payload,
                    flags=re.IGNORECASE, count=1,
                )
                break

        if new_payload == payload:
            return None
        return self._clone(genome, new_payload)

    def _time_shift(self, genome: AttackGenome) -> AttackGenome:
        """Clone genome with the next timing pattern in the rotation cycle."""
        idx = (self._TIMING_CYCLE.index(genome.timing_pattern)
               if genome.timing_pattern in self._TIMING_CYCLE else 0)
        new_pattern = self._TIMING_CYCLE[(idx + 1) % len(self._TIMING_CYCLE)]
        clone = AttackGenome(
            threat_type=genome.threat_type,
            entry_vector=genome.entry_vector,
            payload_signature=genome.payload_signature,
            timing_pattern=new_pattern,
            target_layer=genome.target_layer,
            success_probability=genome.success_probability,
            detected_by=list(genome.detected_by),
            severity_score=genome.severity_score,
            generation=genome.generation + 1,
            parent_id=genome.id,
        )
        return clone

    def _layer_bypass(self, genome: AttackGenome) -> Optional[AttackGenome]:
        """Wrap payload to attempt routing around a specific detection layer."""
        all_layers = ["InputGuard", "StealthDetector", "SessionWarden"]
        alternatives = [l for l in all_layers if l != genome.target_layer]
        if not alternatives:
            return None

        new_target = alternatives[0]
        payload = genome.entry_vector or genome.payload_signature
        if new_target == "StealthDetector":
            new_payload = f"[slow_drip]{payload}"
        elif new_target == "SessionWarden":
            new_payload = f"[session_hop]{payload}"
        else:
            new_payload = payload

        clone = self._clone(genome, new_payload)
        clone.target_layer = new_target
        return clone

    def _combine_vectors(
        self,
        g1: AttackGenome,
        g2: AttackGenome,
    ) -> Optional[AttackGenome]:
        """Merge two genomes into a multi-vector attack."""
        p1 = g1.entry_vector or g1.payload_signature
        p2 = g2.entry_vector or g2.payload_signature
        if not p1 or not p2:
            return None
        combined = f"{p1}; {p2}"
        return AttackGenome(
            threat_type=f"{g1.threat_type}+{g2.threat_type}",
            entry_vector=combined,
            payload_signature=_fingerprint(combined),
            timing_pattern=g1.timing_pattern,
            target_layer="InputGuard",
            success_probability=max(g1.success_probability, g2.success_probability),
            detected_by=list(set(g1.detected_by + g2.detected_by)),
            severity_score=max(g1.severity_score, g2.severity_score),
            generation=max(g1.generation, g2.generation) + 1,
            parent_id=g1.id,
        )

    # ── Helper ───────────────────────────────────────────────────────────────

    @staticmethod
    def _clone(genome: AttackGenome, new_vector: str) -> AttackGenome:
        return AttackGenome(
            threat_type=genome.threat_type,
            entry_vector=new_vector,
            payload_signature=_fingerprint(new_vector),
            timing_pattern=genome.timing_pattern,
            target_layer=genome.target_layer,
            success_probability=min(1.0, genome.success_probability + 0.05),
            detected_by=list(genome.detected_by),
            severity_score=genome.severity_score,
            generation=genome.generation + 1,
            parent_id=genome.id,
        )


# ─────────────────────────────────────────────────────────────────────────────
# 5. DefensiveEvolutionLoop
# ─────────────────────────────────────────────────────────────────────────────

class DefensiveEvolutionLoop:
    """
    Recursive self-improving security layer.

    Attaches to an existing ``MembraneOrchestrator`` and runs a lightweight
    daemon thread that continuously:

    1. Drains queued ThreatEvents (fed by ``trigger()``)
    2. Converts them to ``AttackGenome`` objects
    3. Replays in isolated sandbox
    4. Mutates to generate stronger variants
    5. Self-attack stress-tests the sandbox with each variant
    6. On bypass discovery — dynamically adds detection rules +
       reinforces the AdaptiveFirewall

    This transforms Niblit from:
      Detect → Block → Log
    Into:
      Detect → Block → Learn → Simulate → Self-Attack → Evolve → Reinforce

    Usage
    -----
        loop = DefensiveEvolutionLoop(membrane)
        loop.start()             # launches daemon thread
        loop.trigger(evt)        # feed a threat event
        loop.evolution_cycle()   # run one cycle manually
        loop.stats()             # get statistics
        loop.stop()              # graceful shutdown
    """

    def __init__(self, membrane: Any) -> None:
        """
        Parameters
        ----------
        membrane : MembraneOrchestrator
            The live production membrane.  Only its *output* methods
            (``add_pattern``, ``adaptive_firewall.learn``, ``knowledge_db``)
            are called.  Sandbox replay uses fresh isolated instances.
        """
        self._membrane        = membrane
        self._sandbox         = SandboxReplayer()
        self._mutator         = AttackMutationEngine()

        self._genome_queue:      Deque[AttackGenome]   = deque(maxlen=_QUEUE_MAX)
        self._genome_memory:     Deque[AttackGenome]   = deque(maxlen=_GENOME_MEMORY_MAX)
        self._bypass_discoveries: Deque[Dict[str, Any]] = deque(maxlen=500)

        self._lock            = threading.Lock()
        self._running         = False
        self._paused          = False
        self._thread:  Optional[threading.Thread] = None

        self._last_cycle_ts:        float = 0.0
        self._cycles_completed:     int   = 0
        self._total_genomes:        int   = 0
        self._total_bypasses_found: int   = 0
        self._total_rules_added:    int   = 0

        log.info("[EvolutionLoop] Initialised (max_depth=%d, max_sandbox=%d, cpu_limit=%.2f).",
                 _MAX_MUTATION_DEPTH, _MAX_SANDBOX_ITERATIONS, _MAX_CPU_EVO_LOAD)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background evolution daemon thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._background_loop,
            name="niblit-evolution",
            daemon=True,
        )
        self._thread.start()
        log.info("[EvolutionLoop] Background thread started.")

    def stop(self) -> None:
        """Signal the background thread to stop."""
        self._running = False
        log.info("[EvolutionLoop] Stopped.")

    # ── Primary API ───────────────────────────────────────────────────────────

    def trigger(self, event: Any) -> None:
        """
        Queue a threat event for the next evolution cycle.

        Called automatically by ``MembraneOrchestrator._store_threat()`` when
        a high-severity event is detected.  Also callable manually for testing.

        Thread-safe and non-blocking.  Silently drops events when the system
        is under high CPU load.
        """
        if _get_cpu_load() > _MAX_CPU_EVO_LOAD:
            log.debug(
                "[EvolutionLoop] trigger() dropped: CPU load %.2f > %.2f limit.",
                _get_cpu_load(), _MAX_CPU_EVO_LOAD,
            )
            return  # don't queue when system is already stressed
        try:
            genome = self._build_genome_from_event(event)
            with self._lock:
                self._genome_queue.append(genome)
        except Exception as exc:
            log.debug("[EvolutionLoop] trigger() error: %s", exc)

    def evolution_cycle(self) -> Dict[str, Any]:
        """
        Run one full evolution cycle synchronously.

        1. Check CPU load — pause if too high
        2. Drain up to ``_MAX_SANDBOX_ITERATIONS`` genomes from queue
        3. For each genome:
           a. Sandbox replay of original genome
           b. If bypassed → reinforce + add dynamic rule, skip mutations
           c. Generate mutations (up to 4 variants)
           d. Self-attack loop: sandbox replay each variant
           e. Any variant that bypasses → reinforce

        Returns a summary dict.
        """
        summary: Dict[str, Any] = {
            "genomes_processed":   0,
            "sandbox_runs":        0,
            "mutations_generated": 0,
            "bypasses_found":      0,
            "rules_added":         0,
        }

        if _get_cpu_load() > _MAX_CPU_EVO_LOAD:
            self._paused = True
            log.debug("[EvolutionLoop] CPU load=%.2f exceeds limit, pausing.", _get_cpu_load())
            return {"status": "paused_cpu", **summary}
        self._paused = False

        # Drain batch from queue
        with self._lock:
            batch = []
            while self._genome_queue and len(batch) < _MAX_SANDBOX_ITERATIONS:
                batch.append(self._genome_queue.popleft())

        if not batch:
            return {"status": "idle", **summary}

        for genome in batch:
            if summary["sandbox_runs"] >= _MAX_SANDBOX_ITERATIONS:
                break

            summary["genomes_processed"] += 1
            with self._lock:
                self._genome_memory.append(genome)
            self._total_genomes += 1

            # Step 1: Sandbox replay of original genome
            r0 = self._sandbox.replay(genome)
            summary["sandbox_runs"] += 1

            if r0.bypassed_defense:
                # Original attack bypasses — reinforce immediately
                summary["bypasses_found"] += 1
                self._total_bypasses_found += 1
                added = self._handle_bypass(genome, r0)
                summary["rules_added"] += added
                continue  # mutations not required for already-bypassing attacks

            # Step 2: Generate mutations
            other = self._pick_genome(exclude_id=genome.id)
            variants = self._mutator.mutate(genome, other)
            summary["mutations_generated"] += len(variants)

            # Step 3: Self-attack loop
            for variant in variants:
                if summary["sandbox_runs"] >= _MAX_SANDBOX_ITERATIONS:
                    break
                if _get_cpu_load() > _MAX_CPU_EVO_LOAD:
                    break

                rv = self._sandbox.replay(variant)
                summary["sandbox_runs"] += 1

                if rv.bypassed_defense:
                    summary["bypasses_found"] += 1
                    self._total_bypasses_found += 1
                    added = self._handle_bypass(variant, rv)
                    summary["rules_added"] += added
                else:
                    # Variant was caught — teach the firewall about this pattern
                    self._reinforce_firewall(variant)

        self._last_cycle_ts = time.time()
        self._cycles_completed += 1
        summary["status"] = "ok"
        log.info(
            "[EvolutionLoop] Cycle %d — genomes=%d sandbox=%d bypasses=%d rules_added=%d",
            self._cycles_completed,
            summary["genomes_processed"],
            summary["sandbox_runs"],
            summary["bypasses_found"],
            summary["rules_added"],
        )
        return summary

    def stats(self) -> Dict[str, Any]:
        """Return a snapshot of evolution loop statistics."""
        with self._lock:
            q_size  = len(self._genome_queue)
            mem_sz  = len(self._genome_memory)
            bypasses = list(self._bypass_discoveries)[-10:]
        return {
            "running":                self._running,
            "paused_high_cpu":        self._paused,
            "cycles_completed":       self._cycles_completed,
            "total_genomes_processed":self._total_genomes,
            "total_bypasses_found":   self._total_bypasses_found,
            "total_rules_added":      self._total_rules_added,
            "queue_pending":          q_size,
            "genome_memory_size":     mem_sz,
            "last_cycle": (
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._last_cycle_ts))
                if self._last_cycle_ts else "never"
            ),
            "recent_bypasses":        bypasses,
            "cpu_load":               round(_get_cpu_load(), 2),
            "safety_limits": {
                "MAX_MUTATION_DEPTH":     _MAX_MUTATION_DEPTH,
                "MAX_SANDBOX_ITERATIONS": _MAX_SANDBOX_ITERATIONS,
                "MAX_CPU_EVO_LOAD":       _MAX_CPU_EVO_LOAD,
                "CYCLE_INTERVAL_SECS":    _CYCLE_INTERVAL_SECS,
            },
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _background_loop(self) -> None:
        """Daemon thread: run evolution_cycle() every _CYCLE_INTERVAL_SECS."""
        while self._running:
            try:
                now = time.time()
                if now - self._last_cycle_ts >= _CYCLE_INTERVAL_SECS:
                    self.evolution_cycle()
            except Exception as exc:
                log.debug("[EvolutionLoop] Background loop error: %s", exc)
            time.sleep(_BG_POLL_INTERVAL)

    @staticmethod
    def _build_genome_from_event(event: Any) -> AttackGenome:
        """Convert a ThreatEvent dataclass or dict into an AttackGenome."""
        if hasattr(event, "threat_type"):
            # ThreatEvent dataclass
            return AttackGenome(
                threat_type=event.threat_type,
                entry_vector=getattr(event, "detail", "")[:300],
                payload_signature=_fingerprint(getattr(event, "detail", "")),
                timing_pattern="normal",
                target_layer=getattr(event, "layer", ""),
                success_probability=0.0,        # it was caught
                detected_by=[getattr(event, "layer", "")],
                severity_score=getattr(event, "severity", 0.5),
            )
        if isinstance(event, dict):
            return AttackGenome(
                threat_type=event.get("type", "unknown"),
                entry_vector=event.get("detail", "")[:300],
                payload_signature=_fingerprint(event.get("detail", "")),
                timing_pattern="normal",
                target_layer=event.get("layer", ""),
                success_probability=0.0,
                detected_by=[event.get("layer", "")],
                severity_score=float(event.get("severity", 0.5)),
            )
        return AttackGenome(threat_type="unknown")

    def _handle_bypass(self, genome: AttackGenome, result: SandboxResult) -> int:
        """
        A sandbox bypass was discovered.

        1. Record in bypass_discoveries log
        2. Dynamically add the bypass pattern to InputGuard
        3. Teach AdaptiveFirewall about the genome
        4. Persist to KnowledgeDB if available

        Returns the count of new rules added.
        """
        entry = {
            "ts":           time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "genome_id":    genome.id,
            "threat_type":  genome.threat_type,
            "generation":   genome.generation,
            "entry_vector": genome.entry_vector[:150],
            "failing_layer": result.failing_layer,
        }
        self._bypass_discoveries.append(entry)

        log.warning(
            "[EvolutionLoop] BYPASS found: type=%s gen=%d layer_failed=%s payload=%r",
            genome.threat_type, genome.generation,
            result.failing_layer or "none",
            genome.entry_vector[:80],
        )

        rules_added = 0
        # Dynamically inject the bypass pattern into InputGuard
        if genome.entry_vector and len(genome.entry_vector) >= 4:
            pattern = re.escape(genome.entry_vector[:60])
            weight = min(0.95, genome.severity_score + 0.15)
            label = f"evo_{genome.threat_type}"
            try:
                added = self._membrane.input_guard.add_pattern(
                    pattern=pattern,
                    weight=weight,
                    label=label,
                )
                if added:
                    rules_added += 1
                    self._total_rules_added += 1
                    log.info(
                        "[EvolutionLoop] Dynamic rule added: %s weight=%.2f", label, weight
                    )
            except Exception as exc:
                log.debug("[EvolutionLoop] add_pattern error: %s", exc)

        # Reinforce AdaptiveFirewall
        self._reinforce_firewall(genome)

        # Persist discovery to KnowledgeDB
        if self._membrane.knowledge_db:
            try:
                self._membrane.knowledge_db.add_fact(
                    f"security:evo_bypass:{genome.id}",
                    f"[EvolutionLoop] Bypass gen={genome.generation} "
                    f"type={genome.threat_type} — {genome.entry_vector[:120]}",
                )
            except Exception:
                pass

        return rules_added

    def _reinforce_firewall(self, genome: AttackGenome) -> None:
        """Feed a genome into AdaptiveFirewall.learn() to teach about new patterns."""
        try:
            self._membrane.adaptive_firewall.learn(genome.to_dict())
        except Exception as exc:
            log.debug("[EvolutionLoop] firewall learn error: %s", exc)

    def _pick_genome(self, exclude_id: str = "") -> Optional[AttackGenome]:
        """
        Pick a genome from memory for combination (deterministic).

        The middle element is chosen because it represents a "median" age —
        neither so recent it was just added (potentially incomplete) nor so
        old that it's stale.  This is intentionally deterministic to avoid
        non-deterministic test behaviour and to be predictable on Termux where
        random seeds are not always reliable.
        """
        with self._lock:
            candidates = [g for g in self._genome_memory if g.id != exclude_id]
        if not candidates:
            return None
        return candidates[len(candidates) // 2]


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_instance: Optional[DefensiveEvolutionLoop] = None
_instance_lock = threading.Lock()


def get_evolution_loop(membrane: Optional[Any] = None) -> Optional[DefensiveEvolutionLoop]:
    """
    Return the process-level DefensiveEvolutionLoop singleton.

    *membrane* must be provided on the first call.  Subsequent calls without
    a membrane return the existing singleton.  Returns ``None`` if called
    before initialisation without a membrane.
    """
    global _instance
    if _instance is None:
        if membrane is None:
            return None
        with _instance_lock:
            if _instance is None:
                _instance = DefensiveEvolutionLoop(membrane)
    return _instance


if __name__ == "__main__":
    print("Running niblit_defensive_evolution_loop.py — self-test")

    # ── Inline mini-stub of MembraneOrchestrator for self-test ──────────────
    class _StubInputGuard:
        def __init__(self) -> None:
            self._dynamic: list = []
        def add_pattern(self, pattern: str, weight: float, label: str) -> bool:
            self._dynamic.append((pattern, weight, label))
            return True

    class _StubFirewall:
        def __init__(self) -> None:
            self._learned: list = []
        def learn(self, d: dict) -> None:
            self._learned.append(d)

    class _StubMembrane:
        def __init__(self) -> None:
            self.input_guard = _StubInputGuard()
            self.adaptive_firewall = _StubFirewall()
            self.knowledge_db = None

    stub = _StubMembrane()
    loop = DefensiveEvolutionLoop(stub)

    # Test genome building
    class _FakeEvent:
        threat_type = "sqli"
        detail = "'; DROP TABLE users; --"
        layer = "InputGuard"
        severity = 0.95
    g = loop._build_genome_from_event(_FakeEvent())
    assert g.threat_type == "sqli", f"Expected sqli, got {g.threat_type}"
    print(f"  AttackGenome built: type={g.threat_type} id={g.id}")

    # Test mutation engine
    engine = AttackMutationEngine()
    variants = engine.mutate(g)
    print(f"  Mutations generated: {len(variants)}")
    assert len(variants) >= 1, "Expected at least 1 mutation"

    # Test generation limit
    deep = AttackGenome(threat_type="sqli", generation=_MAX_MUTATION_DEPTH)
    assert engine.mutate(deep) == [], "Expected no mutations at max depth"
    print(f"  Generation depth limit respected at depth={_MAX_MUTATION_DEPTH}")

    # Test trigger (uses stub membrane, sandbox will fail gracefully)
    loop.trigger(_FakeEvent())
    print(f"  Trigger queued; queue size={len(loop._genome_queue)}")

    # Test stats
    s = loop.stats()
    assert "cycles_completed" in s
    print(f"  Stats: cycles={s['cycles_completed']}, cpu_load={s['cpu_load']}")

    # Test cpu load function
    load = _get_cpu_load()
    assert 0.0 <= load
    print(f"  CPU load: {load:.2f}")

    print("All self-tests passed.")
