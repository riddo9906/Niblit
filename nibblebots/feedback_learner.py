#!/usr/bin/env python3
"""
nibblebots/feedback_learner.py — Phase 3 Feedback Learning Loop

Records the outcome of each evolution commit and feeds the results back into
the impact_engine's weight model so future runs make better decisions.

This closes the loop:

    Fix applied → Commit pushed → CI runs → Outcome observed
                        ↓
              feedback_learner.record_outcome()
                        ↓
              impact_engine.update_weights()
                        ↓
               Better fix selection next run

Outcome journal
---------------
Every recorded outcome is appended to a JSON-lines file
(outcome_journal.jsonl, next to this script) so you can inspect the full
history of what the agent did and what happened.

Automatic outcome detection
----------------------------
``fetch_ci_outcome()`` queries the GitHub Actions API to compare the most
recent two completed workflow runs (before/after the evolution commit) and
derives a signal from:

  • test failure count
  • overall success/failure status

This is Phase 3's "impact validation" — the system checks whether its fix
actually improved things, not just whether it compiled.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

from nibblebots import impact_engine, rollback_guard
from nibblebots import anomaly_detector, delayed_outcome_tracker, confidence_decay
from nibblebots import value_engine, causality_tracker, reality_bridge


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_JOURNAL_FILE  = Path(__file__).parent / "outcome_journal.jsonl"
_PATTERN_FILE  = Path(__file__).parent / "pattern_memory.jsonl"  # Phase 15

# ---------------------------------------------------------------------------
# GitHub API helpers (same pattern as autonomous_evolution_agent.py)
# ---------------------------------------------------------------------------

_API_BASE = "https://api.github.com"
_TOKEN = os.environ.get("GITHUB_TOKEN", "")
_REPO = os.environ.get("GITHUB_REPOSITORY", "")


def _gh_get(path: str) -> Any:
    """GET from GitHub REST API v3.  Returns parsed JSON or None."""
    url = f"{_API_BASE}{path}" if not path.startswith("http") else path
    if not url.startswith(_API_BASE):
        print(f"  ⚠ _gh_get: rejected non-GitHub URL: {url!r}", file=sys.stderr)
        return None
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Niblit-Evolution-Agent/3.0",
    }
    if _TOKEN:
        headers["Authorization"] = f"Bearer {_TOKEN}"
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=15) as resp:  # noqa: S310
            return json.loads(resp.read().decode())
    except URLError as exc:
        print(f"  ⚠ GitHub API network error: {exc}", file=sys.stderr)
        return None
    except OSError as exc:
        print(f"  ⚠ GitHub API OS error: {exc}", file=sys.stderr)
        return None
    except json.JSONDecodeError as exc:
        print(f"  ⚠ GitHub API malformed JSON: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# CI outcome detection
# ---------------------------------------------------------------------------

def fetch_ci_outcome(
    fix_types: List[str],
    pre_run_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Query GitHub Actions to derive a post-commit outcome signal.

    Compares the two most recent completed runs of the test workflow.
    Returns an outcome dict compatible with impact_engine.update_weights().

    Parameters
    ----------
    fix_types   : list of fix types applied in this evolution commit
    pre_run_id  : workflow run ID that existed BEFORE the commit (optional);
                  when provided, we compare that run's result to the latest.
    """
    outcome: Dict[str, Any] = {
        "tests_passed": None,
        "error_count_change": 0,
        "ci_failure_change": 0,
        "runtime_stable": None,
        "source": "github_actions",
    }

    if not _TOKEN or not _REPO:
        outcome["source"] = "unavailable"
        return outcome

    data = _gh_get(
        f"/repos/{_REPO}/actions/runs"
        f"?status=completed&per_page=10"
    )
    if not data or "workflow_runs" not in data:
        outcome["source"] = "api_error"
        return outcome

    runs = data["workflow_runs"]
    if len(runs) < 2:
        outcome["source"] = "insufficient_history"
        return outcome

    # Latest run = after commit; previous run = before commit
    latest = runs[0]
    previous = runs[1] if pre_run_id is None else next(
        (r for r in runs if r["id"] == pre_run_id), runs[1]
    )

    latest_ok = latest.get("conclusion") == "success"
    previous_ok = previous.get("conclusion") == "success"

    outcome["tests_passed"] = latest_ok
    outcome["runtime_stable"] = latest_ok

    # ci_failure_change: negative means fewer failures (good)
    if latest_ok and not previous_ok:
        outcome["ci_failure_change"] = -1
    elif not latest_ok and previous_ok:
        outcome["ci_failure_change"] = +1
    else:
        outcome["ci_failure_change"] = 0

    return outcome


# ---------------------------------------------------------------------------
# Outcome recording
# ---------------------------------------------------------------------------

def record_outcome(
    fix_types: List[str],
    fixed_files: List[str],
    total_instances: int,
    commit_sha: str = "",
    outcome: Optional[Dict[str, Any]] = None,
    impact_net_score: Optional[float] = None,
) -> Dict[str, Any]:
    """Record the outcome of an evolution commit and update impact weights.

    Parameters
    ----------
    fix_types        : list of fix types that were applied
    fixed_files      : list of relative file paths that were changed
    total_instances  : total number of instances fixed
    commit_sha       : git SHA of the evolution commit (if known)
    outcome          : pre-computed outcome dict; if None, fetched from CI API
    impact_net_score : average net_score from the EvolutionPlan (for regression)

    Returns the outcome dict that was recorded.
    """
    if outcome is None:
        print("  🔍 Fetching CI outcome from GitHub Actions...")
        outcome = fetch_ci_outcome(fix_types)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "commit_sha": commit_sha,
        "fix_types": fix_types,
        "fixed_files": fixed_files,
        "total_instances": total_instances,
        "outcome": outcome,
    }
    if impact_net_score is not None:
        entry["impact_net_score"] = round(float(impact_net_score), 4)

    # Append to journal
    try:
        with _JOURNAL_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError as exc:
        print(f"  ⚠ Could not write outcome journal: {exc}", file=sys.stderr)

    # Update impact weights for each fix type
    for fix_type in fix_types:
        impact_engine.update_weights(fix_type, outcome)
        _status = "✅" if outcome.get("tests_passed") else "⚠"
        print(
            f"  {_status} Outcome recorded for {fix_type}: "
            f"tests={'pass' if outcome.get('tests_passed') else 'fail/unknown'}, "
            f"ci_delta={outcome.get('ci_failure_change', 0):+d}"
        )

    # Phase 7: confidence decay — mark validated fix types
    if outcome.get("tests_passed"):
        confidence_decay.mark_validated(fix_types)

    # Phase 4: rollback guard — check for regression and emit revert if needed
    guard_result = rollback_guard.check(fix_types=fix_types, commit_sha=commit_sha)
    if guard_result.get("regression"):
        print(
            f"  🔄 RollbackGuard triggered: {guard_result.get('revert_cmd')}",
            file=sys.stderr,
        )

    # Phase 7: anomaly detection — observe the latest failure rate
    _observe_anomaly(outcome, fix_types)

    # Phase 7: delayed outcome tracking — register commit, advance all open records
    _advance_delayed_tracking(
        commit_sha=commit_sha,
        fix_types=fix_types,
        outcome=outcome,
        impact_net_score=impact_net_score,
    )

    # Phase 4: attempt to fit regression model from accumulated history
    journal_entries = read_journal(last_n=200)
    if len(journal_entries) >= impact_engine.REGRESSION_MIN_SAMPLES:
        fitted = impact_engine.fit_regression_from_journal(journal_entries)
        if fitted:
            print("  📈 Regression model updated from journal history.")

    # Phase 7: try to enrich regression model with delayed (corrected) outcomes
    _try_delayed_regression_fit()

    # Phase 8: value engine + causality tracker
    _evaluate_real_world_value(
        commit_sha=commit_sha,
        fix_types=fix_types,
        impact_net_score=impact_net_score,
    )

    # Phase 6: emit evolution outcome on the EventBus (best-effort)
    _emit_evolution_event(entry, outcome)

    return outcome


# ---------------------------------------------------------------------------
# Journal reader (for inspection / meta-engine integration)
# ---------------------------------------------------------------------------

def read_journal(last_n: int = 20) -> List[Dict[str, Any]]:
    """Return the last *n* outcome journal entries."""
    if not _JOURNAL_FILE.exists():
        return []
    try:
        lines = _JOURNAL_FILE.read_text(encoding="utf-8").splitlines()
        entries = []
        for line in lines:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return entries[-last_n:]
    except OSError:
        return []


def journal_summary() -> Dict[str, Any]:
    """Return aggregate stats from the outcome journal."""
    entries = read_journal(last_n=100)
    if not entries:
        return {"total_commits": 0}

    total = len(entries)
    passed = sum(
        1 for e in entries
        if e.get("outcome", {}).get("tests_passed") is True
    )
    fix_type_counts: dict = {}
    for e in entries:
        for ft in e.get("fix_types", []):
            fix_type_counts[ft] = fix_type_counts.get(ft, 0) + 1

    return {
        "total_commits": total,
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "fix_type_counts": fix_type_counts,
        "latest_timestamp": entries[-1].get("timestamp", ""),
    }


# ---------------------------------------------------------------------------
# Phase 7: anomaly observation helper
# ---------------------------------------------------------------------------

def _observe_anomaly(outcome: Dict[str, Any], fix_types: List[str]) -> None:
    """Feed the latest CI outcome into the anomaly detector (best-effort)."""
    try:
        failed = outcome.get("tests_passed") is False
        failure_rate = 1.0 if failed else 0.0
        report = anomaly_detector.observe(failure_rate, fix_types=fix_types)
        if not report.is_safe:
            print(
                f"  ⚠ AnomalyDetector: {len(report.alerts)} alert(s) — "
                + "; ".join(a.message for a in report.alerts),
                file=sys.stderr,
            )
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Phase 7: delayed outcome tracking helpers
# ---------------------------------------------------------------------------

def _advance_delayed_tracking(
    commit_sha: str,
    fix_types: List[str],
    outcome: Dict[str, Any],
    impact_net_score: Optional[float],
) -> None:
    """Register the new commit and advance open records by one run (best-effort)."""
    try:
        ci_passed = bool(outcome.get("tests_passed"))
        # Advance all existing open records first (this run is a signal for them)
        delayed_outcome_tracker.record_run(ci_passed)
        # Then register the NEW commit (so it starts tracking from next run)
        if commit_sha:
            delayed_outcome_tracker.register_commit(
                commit_sha=commit_sha,
                fix_types=fix_types,
                h0_failures=int(not ci_passed),
                impact_net_score=impact_net_score,
            )
    except Exception:  # noqa: BLE001
        pass


def _try_delayed_regression_fit() -> None:
    """Fit regression using corrected delayed outcomes if available (best-effort)."""
    try:
        corrected = delayed_outcome_tracker.get_corrected_entries(min_horizon=5)
        if len(corrected) < impact_engine.REGRESSION_MIN_SAMPLES:
            return
        # Build synthetic journal entries from delayed outcomes
        synthetic: List[Dict[str, Any]] = [
            {
                "impact_net_score": e["impact_net_score"],
                "outcome": {"ci_failure_change": e["delayed_delta"]},
            }
            for e in corrected
            if e.get("impact_net_score") is not None
        ]
        if len(synthetic) >= impact_engine.REGRESSION_MIN_SAMPLES:
            if impact_engine.fit_regression_from_journal(synthetic):
                print("  📈 Regression model refined with delayed outcome data.")
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Phase 8: value engine + causality tracker helpers
# ---------------------------------------------------------------------------

def _evaluate_real_world_value(
    commit_sha: str,
    fix_types: List[str],
    impact_net_score: Optional[float],
) -> None:
    """Evaluate real-world value delta and record causality data (best-effort)."""
    try:
        # Pull a fresh snapshot and compare to the cached pre-commit snapshot
        before_snapshot = reality_bridge.get_cached_snapshot()
        after_snapshot = reality_bridge.pull_snapshot()

        if before_snapshot is not None:
            assessment = value_engine.evaluate(before_snapshot, after_snapshot)
        else:
            assessment = value_engine.evaluate_single(after_snapshot)

        print(f"  🌍 ValueEngine: {assessment}")

        # Persist for history and causality tracking
        value_engine.record_assessment(
            assessment, commit_sha=commit_sha, fix_types=fix_types
        )

        # Feed causality tracker — Phase 8.5: pass signal_confidence
        if fix_types and impact_net_score is not None:
            causality_tracker.record(
                fix_types=fix_types,
                impact_net_score=impact_net_score,
                value_delta=assessment.delta,
                signal_confidence=after_snapshot.get("avg_confidence", 1.0),
            )

        # Phase 9: record cycle outcome in stability_controller (best-effort)
        # Phase 9.5: also pass contextual conditions for context-aware memory
        try:
            from nibblebots import stability_controller as _sc  # noqa: PLC0415
            from nibblebots import intent_anchor_engine as _iae  # noqa: PLC0415
            _mode = _sc.status().get("current_mode", "exploit")
            _outcome_score = float(assessment.delta) if assessment.delta is not None else 0.0
            # avg_confidence is the primary signal reliability measure from SIE
            _avg_confidence = float(after_snapshot.get("avg_confidence", 0.5))
            # intent_alignment comes from the intent_anchor_engine rolling score
            _intent_alignment = float(_iae.get_rolling_score())
            _sc.record_cycle(
                mode=_mode,
                outcome_score=_outcome_score,
                confidence=_avg_confidence,
                intent_alignment=_intent_alignment,
                signal_reliability=_avg_confidence,
            )
            # Phase 10: record episode in causal strategy engine (best-effort)
            # Phase 18.5: compute rolling variance from value history instead
            # of passing the hard-coded 0.0, which was corrupting the CSE's
            # variance band and regime-detection calculations.
            try:
                from nibblebots import causal_strategy_engine as _cse  # noqa: PLC0415
                # Derive variance from the last N value assessments so the CSE
                # receives a meaningful spread estimate rather than zero.
                _variance = 0.0
                try:
                    _history = value_engine.read_history(last_n=10)
                    if len(_history) >= 3:
                        _deltas = [
                            float(h["delta"])
                            for h in _history
                            if isinstance(h.get("delta"), (int, float))
                        ]
                        if len(_deltas) >= 3:
                            _mean_d = sum(_deltas) / len(_deltas)
                            _variance = round(
                                sum((d - _mean_d) ** 2 for d in _deltas)
                                / len(_deltas),
                                6,
                            )
                except Exception:  # noqa: BLE001
                    pass
                # batch_size = number of fix types applied this cycle
                _batch_size = len(fix_types) if fix_types else 1
                _cse.record_episode(
                    mode=_mode,
                    outcome=_outcome_score,
                    confidence=_avg_confidence,
                    signal_conf=_avg_confidence,
                    intent_score=_intent_alignment,
                    variance=_variance,
                    fix_type=fix_types[0] if fix_types else "",
                    subsystem=str(after_snapshot.get("subsystem", "")),
                    batch_size=_batch_size,
                )
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass

        # Phase 15: store winning pattern to pattern_memory.jsonl (best-effort)
        if assessment.delta is not None and assessment.delta > 0:
            try:
                _subsystem = after_snapshot.get("subsystem", "")
                store_success_pattern(
                    fix_types=fix_types,
                    subsystem=str(_subsystem),
                    outcome_score=float(assessment.delta),
                    commit_sha=commit_sha,
                )
            except Exception:  # noqa: BLE001
                pass

        # Phase 16.5: resonance attribution — record causal evidence for each
        # active SIL profile so trust updates reflect actual outcome improvement
        # rather than mere correlation.
        try:
            from nibblebots import system_interface_layer as _sil  # noqa: PLC0415
            _sil_ids = _sil.get_all_profile_ids()
            if _sil_ids and assessment.delta is not None:
                # Use the before/after snapshot scores as the true baseline and
                # post-resonance measurements.  When before_snapshot is available
                # use its own single-evaluation as baseline; otherwise fall back
                # to a neutral 0.5.
                if before_snapshot is not None:
                    _before_assess = value_engine.evaluate_single(before_snapshot)
                    _baseline = min(1.0, max(0.0, 0.5 + float(
                        _before_assess.delta if _before_assess.delta is not None else 0.0
                    )))
                else:
                    _baseline = 0.5
                _post = min(1.0, max(0.0, 0.5 + float(assessment.delta)))
                for _sid in _sil_ids:
                    _sil.record_resonance_attribution(
                        system_id=_sid,
                        baseline_outcome=_baseline,
                        post_resonance_outcome=_post,
                        adjustments_applied=None,
                    )
        except Exception:  # noqa: BLE001
            pass

        # Phase 18: governance evolution — on a slow cadence (every
        # GEE_ADAPT_INTERVAL cycles) evaluate whether governance parameters
        # should adapt.  Best-effort, never raises.
        try:
            from nibblebots import governance_evolution_engine as _gee  # noqa: PLC0415
            _gee_outcome = min(1.0, max(0.0, 0.5 + float(
                assessment.delta if assessment.delta is not None else 0.0
            )))
            _adaptation = _gee.evaluate_and_adapt(outcome_score=_gee_outcome)
            if _adaptation is not None:
                print(
                    f"  🏛️  GEE: governance adapted — "
                    f"sat_delta={_adaptation.saturation_threshold_delta:+.4f} "
                    f"penalty_delta={_adaptation.objective_penalty_delta:+.4f} | "
                    f"{_adaptation.rationale}"
                )
        except Exception:  # noqa: BLE001
            pass

    except Exception:  # noqa: BLE001
        pass   # Phase 8 is strictly best-effort


# ---------------------------------------------------------------------------
# Phase 6: EventBus integration (best-effort — never raises)
# ---------------------------------------------------------------------------

def _emit_evolution_event(entry: Dict[str, Any], outcome: Dict[str, Any]) -> None:
    """Emit EVENT_EVOLUTION_OUTCOME on the runtime EventBus if available.

    This bridges the evolution agent and the SDAL/MetaEngine so they share
    knowledge about what the evolution loop has learned.  Silently skipped
    when the EventBus or MetaEngine is unavailable (e.g. standalone runs).
    """
    try:
        from modules.event_bus import get_event_bus, NiblitEvent, EVENT_EVOLUTION_OUTCOME  # noqa: PLC0415
        bus = get_event_bus()
        bus.publish(NiblitEvent(
            type=EVENT_EVOLUTION_OUTCOME,
            source="feedback_learner",
            payload={
                "fix_types":       entry.get("fix_types", []),
                "tests_passed":    outcome.get("tests_passed"),
                "ci_delta":        outcome.get("ci_failure_change", 0),
                "impact_net_score": entry.get("impact_net_score"),
                "commit_sha":      entry.get("commit_sha", ""),
                "timestamp":       entry.get("timestamp", ""),
            },
        ))
    except Exception:  # noqa: BLE001
        pass  # EventBus unavailable — standalone evolution run


# ---------------------------------------------------------------------------
# Phase 15: pattern memory  (Ruflo "store after success" principle)
# ---------------------------------------------------------------------------

def _semantic_hash(fix_type: str, subsystem: str) -> str:
    """Return a short stable key for a (fix_type, subsystem) pair."""
    import hashlib  # noqa: PLC0415
    raw = f"{fix_type}::{subsystem}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def store_success_pattern(
    fix_types: List[str],
    subsystem: str,
    outcome_score: float,
    commit_sha: str = "",
) -> None:
    """Persist a winning fix pattern to pattern_memory.jsonl.

    Called by ``_evaluate_real_world_value`` after a successful CI cycle.
    Each pattern entry is keyed by a semantic hash so duplicate (fix_type,
    subsystem) pairs accumulate a hit count rather than growing unbounded.

    Parameters
    ----------
    fix_types     : list of fix types that succeeded
    subsystem     : semantic subsystem label (e.g. "core", "evaluation")
    outcome_score : value-engine delta for this cycle
    commit_sha    : git SHA of the successful commit (for traceability)
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    entries: Dict[str, Any] = {}

    # Load existing patterns for dedup
    if _PATTERN_FILE.exists():
        try:
            for line in _PATTERN_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        rec = json.loads(line)
                        entries[rec["hash"]] = rec
                    except (json.JSONDecodeError, KeyError):
                        pass
        except OSError:
            pass

    changed = False
    for fix_type in fix_types:
        key = _semantic_hash(fix_type, subsystem)
        if key in entries:
            rec = entries[key]
            rec["hit_count"] = rec.get("hit_count", 1) + 1
            rec["last_outcome"] = round(outcome_score, 4)
            rec["last_seen"] = timestamp
            rec["avg_outcome"] = round(
                (rec.get("avg_outcome", outcome_score) * (rec["hit_count"] - 1)
                 + outcome_score) / rec["hit_count"],
                4,
            )
        else:
            entries[key] = {
                "hash":         key,
                "fix_type":     fix_type,
                "subsystem":    subsystem,
                "hit_count":    1,
                "avg_outcome":  round(outcome_score, 4),
                "last_outcome": round(outcome_score, 4),
                "first_seen":   timestamp,
                "last_seen":    timestamp,
                "commit_sha":   commit_sha,
            }
        changed = True

    if not changed:
        return

    try:
        lines = [json.dumps(rec) for rec in entries.values()]
        _PATTERN_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"  ⚠ Could not write pattern_memory.jsonl: {exc}", file=sys.stderr)


def load_top_patterns(min_confidence: float = 0.70, top_n: int = 10) -> List[Dict[str, Any]]:
    """Load the highest-confidence patterns from pattern_memory.jsonl.

    Returns patterns sorted by avg_outcome descending, filtered to those
    with avg_outcome >= min_confidence.  Used by the evolution agent for
    pre-task memory search.
    """
    if not _PATTERN_FILE.exists():
        return []
    records: List[Dict[str, Any]] = []
    try:
        for line in _PATTERN_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    rec = json.loads(line)
                    if rec.get("avg_outcome", 0.0) >= min_confidence:
                        records.append(rec)
                except json.JSONDecodeError:
                    pass
    except OSError:
        return []
    records.sort(key=lambda r: r.get("avg_outcome", 0.0), reverse=True)
    return records[:top_n]


if __name__ == "__main__":
    print('Running feedback_learner.py')
