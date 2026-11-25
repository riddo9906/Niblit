# Freebuff Task 02 — risk uncertainty result and review handoff

Date: 2026-11-21 · Component: `modules/adaptive_market_cognition.py` (isolated risk-state section)
Status: implemented, tested locally, **not committed and not deployed**. r11 was not started,
restarted or read; no broker, credential, release or ChatGPT-owned file was touched.

## 1. The defect, reproduced before editing

A market event that carried no risk numbers produced contradictory labels:

```
volatility_regime = "unknown"          # Task 01 fix, from _bucket(None)
risk_state["volatility_state"] = "low" # _risk_state/_calculate_risk clamped None -> 0.0
risk_score = 0.0                       # "no measured risk" looked like "no risk"
```

Cause chain:

1. `_risk_state(payload)` clamped every absent input with `_clamp(...)`, which returns `0.0`
   for `None`, `True`, `"n/a"` and unparseable values. Absent and measured-zero became the same
   number before any label was derived.
2. `experience["risk_state"].update(self._risk_state(payload))` then wrote those zeros over
   evidence supplied through `payload["risk_state"]` — a caller passing
   `risk_state={"volatility": 0.85}` had it silently replaced by `0.0` and reported as `low`.
3. `_calculate_risk` re-clamped and passed the resulting `0.0` floats to `_bucket`, so every
   absent field became a `low` label.

Reproduction test added first, then run against unmodified code:

```
python -m pytest tests/test_adaptive_market_cognition_risk.py -q --basetemp=.pytest-risk-uncertainty-pre
10 failed, 1 passed, exit 1   # 11 tests collected; only the KnowledgeDB-fact test passed
```

Failure evidence worth keeping:

- `test_explicit_nested_risk_state_is_not_overwritten_by_absent_fields`:
  `AssertionError: assert 'low' == 'high'` — `risk_state={"volatility": 0.85}` was overwritten by `0.0`.
- `test_unknown_risk_earns_no_safety_credit_in_retrieval`: `assert 0.5664 > 0.567` — the
  experience with **no** risk data outranked the measured-calm one, because both received the
  full `(1 - risk_score) * 0.08 = 0.08` safety bonus.
- `test_unknown_risk_profile_is_reported_as_unknown`: `KeyError: 'risk_evidence_state'`.
- `test_bucket_treats_non_finite_and_non_numeric_values_as_unknown`: NaN/±inf failed.

### Correction to the peer review note

`docs/FREEBUFF_CHATGPT_INTEGRATION_REVIEW_20261121.md` asked whether NaN/Infinity might be
misclassified as **low**. Measured on the actual helpers:

```
_clamp(nan) = 1.0   _clamp(inf) = 1.0   (min(1.0, nan) returns 1.0)
```

so pre-fix non-finite risk inputs were reported as **`high`**, not `low` — `_to_float` succeeds,
then `min()/max()` collapse non-finite values to the ceiling. Either way it was fabricated
evidence; it is now `unknown`, and both helpers are covered by tests.

## 2. Encoding: unknown vs measured zero

| Evidence | `risk_state` raw key | Label field | `risk_evidence` |
|---|---|---|---|
| field absent | key omitted | `"unknown"` | `state="missing"`, key in `missing` |
| `None`, `True`, `"n/a"`, `[0.2]`, NaN, ±inf | key omitted | `"unknown"` | `state="missing"`, key in `missing` |
| measured `0.0` | `0.0` stored | `"low"` | key **not** in `missing` |
| measured `0.55` | `0.55` stored | `"medium"` | key not in `missing` |
| number outside 0..1 | clamped (e.g. `1.5 → 1.0`) | `"high"` | key not in `missing` |

New companion field on every finalized `risk_state` (and therefore on the persisted payload):

```json
"risk_evidence": {"state": "complete" | "partial" | "missing", "missing": ["..."]}
```

No probability or uncertainty score is invented: `risk_evidence` only reports which inputs were
usable. `risk_score` remains a `float` in every case, including `0.0` when nothing was measured,
so existing numeric consumers keep working; the marker is what says the number carries no
evidence.

## 3. Exact change

Single file: `modules/adaptive_market_cognition.py`. `git diff --numstat` reports the combined
uncommitted change (Task 01 + Task 02) as **+96 / −24 lines**; Task 02 is the majority of it.
Task 01 hunks are still
present in the same uncommitted diff (`_bucket` unknown handling, conditional volatility bonus,
`_infer_volatility_from_query` returning `""`); the hunks below are Task 02.

```diff
@@ import math
+import math
@@ def _optional_clamp
+def _optional_clamp(value: Any) -> float | None:
+    if value is None or isinstance(value, bool):
+        return None
+    try:
+        number = float(value)
+    except (TypeError, ValueError):
+        return None
+    if not math.isfinite(number):
+        return None
+    return max(0.0, min(1.0, number))

 def _bucket(value: Any) -> str:
-    v = _clamp(value, 0.0)
+    v = _optional_clamp(value)
+    if v is None:
+        return "unknown"
@@ observe_event
-            experience["risk_state"].update(self._risk_state(payload))
+            for risk_key, risk_value in self._risk_state(payload).items():
+                if risk_value is not None:
+                    experience["risk_state"][risk_key] = risk_value
@@ _risk_state
-            "drawdown": _clamp(payload.get("drawdown")),
-            "exposure": _clamp(payload.get("exposure")),
-            "concentration_risk": _clamp(payload.get("concentration_risk")),
-            "volatility": _clamp(payload.get("volatility")),
-            "regime_uncertainty": _clamp(payload.get("uncertainty")),
+            "drawdown": _optional_clamp(payload.get("drawdown")),
+            "exposure": _optional_clamp(payload.get("exposure")),
+            "concentration_risk": _optional_clamp(payload.get("concentration_risk")),
+            "volatility": _optional_clamp(payload.get("volatility")),
+            "regime_uncertainty": _optional_clamp(payload.get("uncertainty")),
@@ _calculate_risk
+    _RISK_WEIGHTS = {"volatility": 0.28, "drawdown": 0.22, "exposure": 0.18,
+                     "concentration_risk": 0.17, "regime_uncertainty": 0.15}
+    measured = {name: _optional_clamp(risk_state.get(name)) for name in self._RISK_WEIGHTS}
+    missing = [name for name in self._RISK_WEIGHTS if measured[name] is None]
+    available_weight = sum(w for n, w in self._RISK_WEIGHTS.items() if measured[n] is not None)
+    if available_weight > 0.0:
+        weighted = sum(measured[n] * w for n, w in self._RISK_WEIGHTS.items() if measured[n] is not None)
+        risk_score = round(min(1.0, weighted / available_weight), 4)
+        evidence_state = "complete" if not missing else "partial"
+    else:
+        risk_score = 0.0
+        evidence_state = "missing"
     return {
         "risk_score": risk_score,
-        "volatility_state": _bucket(volatility),
-        "drawdown_state": _bucket(drawdown),
-        "exposure_state": _bucket(exposure),
-        "concentration_state": _bucket(concentration),
-        "regime_uncertainty": round(regime_uncertainty, 4),
+        "volatility_state": _bucket(risk_state.get("volatility")),
+        "drawdown_state": _bucket(risk_state.get("drawdown")),
+        "exposure_state": _bucket(risk_state.get("exposure")),
+        "concentration_state": _bucket(risk_state.get("concentration_risk")),
+        "regime_uncertainty": round(measured["regime_uncertainty"] or 0.0, 4),
+        "risk_evidence": {"state": evidence_state, "missing": missing},
     }
@@ build_market_retrieval_bundle (similarity term)
-            score += (1.0 - _clamp(item.get("risk_score"))) * 0.08
+            risk_evidence = dict(item.get("risk_state") or {}).get("risk_evidence")
+            if isinstance(risk_evidence, dict):
+                risk_weight = 0.08 if risk_evidence.get("state") in {"complete", "partial"} else 0.04
+            else:
+                risk_weight = 0.08
+            score += (1.0 - _clamp(item.get("risk_score"))) * risk_weight
@@ _aggregate_risk
+    @staticmethod
+    def _aggregate_evidence_state(states: list[str]) -> str:
+        if not states or all(state in {"unknown", "missing"} for state in states):
+            return "unknown"
+        if all(state == "complete" for state in states):
+            return "complete"
+        return "partial"
+        ...
+        "risk_evidence_state": ...,   # both the empty-history and similar-items branches
```

Two deliberate judgement calls, stated so they can be rejected:

1. **Score renormalisation.** The five weights are convex (they sum to 1.0). Instead of letting a
   missing input contribute `0.0 · weight`, the score is the same weighted average divided by the
   weight that was actually measured. Complete evidence is numerically identical to the old
   formula (asserted by an exact-value test). Partial evidence now reflects its real readings:
   `volatility=0.9` alone scores `0.9` instead of the old diluted `0.252`. Nothing is invented —
   no field is filled in — but partial-evidence scores do move, which is a deliberate semantic
   correction rather than a silent one.
2. **Neutral retrieval weight.** An experience with no risk evidence gets `0.04` (half the term)
   instead of `0.08`. `0.04` is a ranking midpoint, not a probability: unknown risk is neither
   rewarded as safe nor punished as risky. Records that predate `risk_evidence` keep the old
   `0.08`, so mixed in-memory/legacy data does not change ranking unexpectedly.

## 4. Traced consumers and measured effects

In-process probe (all five risk inputs absent / measured zero / partial / complete):

| case | `volatility_regime` | `volatility_state` | `risk_score` | `dqi` | `confidence` | `risk_evidence` |
|---|---|---|---|---|---|---|
| missing | unknown | unknown | 0.0 | 0.5377 | 0.525 | `missing` (all 5) |
| measured 0.0 | low | low | 0.0 | 0.5377 | 0.525 | `partial` |
| partial (0.9) | high | high | 0.9 | 0.3744 | 0.255 | `partial` |
| complete | medium | medium | 0.397 | 0.4704 | 0.4059 | `complete` |

Retrieval ranking for `"bull regime outlook"` after the fix (`similarity`):

```
zero(0.0, partial)  0.567
missing             0.527   <- was 0.567, the top-ranked safety credit
full(0.397)         0.5257
partial(0.9)        0.4734
```

`risk_profile` / context / telemetry now carry the evidence state:

```
{'risk_score': 0.3243, 'regime_uncertainty': 0.15,
 'volatility_state': 'low', 'risk_evidence_state': 'partial'}
- risk_state: {... 'risk_evidence_state': 'partial'}      # LLM context line
telemetry['risk_score'] = 0.3243                          # unchanged type
```

Consumer-by-consumer:

| Consumer | Effect |
|---|---|
| `_finalize_experience` merge `{**risk, **risk_state}` | risk dict gains `risk_evidence`; raw inputs supplied via `payload["risk_state"]` survive instead of being zeroed. `risk_score` still `float`. |
| `_reflections` / `status()["risk_intelligence"]` / `desktop_runtime_shell` | `volatility_state`, `drawdown_state`, … now print `unknown` instead of `low` when unmeasured. No consumer code changed. |
| `_risk_history` / `status()["risk_intelligence"]` | carries `risk_evidence`; verified `json.dumps(..., allow_nan=False)` succeeds. |
| `_persist_experience` → Qdrant `market_context.risk_state` | gains `risk_evidence`; contains no `None`/NaN (unmeasured keys are simply absent). Payload shape is additive; no collection or schema change. |
| `_pending_kb_facts` → KnowledgeDB `add_fact` | unchanged format; text still `volatility=unknown`, tag `unknown` (already correct after Task 01). Verified through a fake `core.db`. |
| `build_market_retrieval_bundle` | risk term weighted 0.08 measured / 0.04 unknown; ranking test asserts measured-calm now outranks unknown. |
| `_aggregate_risk` → `risk_profile`, context, telemetry | new `risk_evidence_state`; `risk_score` averaging formula unchanged. |
| `_derived_confidence` | unchanged: subtracts `risk_score * 0.3`, so unknown still adds no penalty. Documented, not changed. |
| `_compute_dqi` `risk_awareness = 1 - risk_score` | unchanged: unknown evidence still yields full awareness credit (see limitations). |
| `unified_runtime.ingest_external_event` | no signature or contract change; existing consumer tests pass. |

## 5. Compatibility analysis

- **Additive only at the data level:** one new key (`risk_evidence`) plus `risk_evidence_state` in
  `_aggregate_risk`. No key removed, no type changed (`risk_score`, `regime_uncertainty` remain
  `float`; labels remain `str`).
- **Full-evidence records are bit-identical** to the previous formula (test asserts the exact
  weighted value `0.397`).
- **Partial evidence scores rise** because missing inputs no longer count as zero risk. This is
  the intended semantic change; anything that compared historical `risk_score` values across the
  upgrade should treat the metric as redefined for partial records.
- **Legacy records** (no `risk_evidence`, e.g. an object created by an older process) keep the old
  retrieval weight and aggregate as `"unknown"`.
- **`_risk_state` shape changed** for direct callers: it now returns `None` for unmeasured keys
  instead of `0.0`. Nothing in the repo calls it outside this module (verified by search); it is
  private.
- **`regime_uncertainty` still reports `0.0`** when unmeasured, to keep the numeric contract for
  `prediction_usefulness`, `provider_routing_bias` and the desktop shell. The `risk_evidence`
  marker is the honest signal for those callers.

## 6. Tests and results

New file `tests/test_adaptive_market_cognition_risk.py` (11 tests, verified by `--collect-only`): missing evidence, measured
zero, measured medium/high, invalid values (`"n/a"`, `True`, NaN, ±inf, list), `_bucket` table,
complete-evidence exact score, partial evidence, nested `payload["risk_state"]` preservation,
retrieval credit, aggregate profile, KnowledgeDB persistence.

| Run (in `Niblit/`) | Result |
|---|---|
| pre-fix, new file only | **10 failed, 1 passed, exit 1** (11 collected) |
| `tests/test_adaptive_market_cognition.py` + new file + `test_unified_runtime_architecture.py` + `test_hypothesis_engine.py` | **43 passed, exit 0** |
| `test_desktop_runtime_shell_market_intelligence.py` | **2 passed, exit 0** |
| all six relevant files (`tests/test_adaptive_market_cognition.py tests/test_adaptive_market_cognition_risk.py test_unified_runtime_architecture.py test_hypothesis_engine.py test_adaptive_retrieval_cognition.py test_desktop_runtime_shell_market_intelligence.py`) with `--basetemp=.pytest-risk-uncertainty-final` | **49 passed, exit 0** |

Honest limits: the **full suite was not run** (~200 root-level test files, long runtime, existing
unrelated dirty work). No live Qdrant, no r11 runtime, no MT5/Freqtrade/broker path was exercised.
Qdrant writes are unavailable in this environment (`collection not available`, swallowed to
`log.debug`), so persistence was verified through the KnowledgeDB fact path and JSON
serialisation, not a real vector-store round trip.

## 7. Remaining findings for the collaborating agent

1. **DQI still credits unknown risk.** `_compute_dqi` uses `risk_awareness = 1 - risk_score`; with
   `risk_score = 0.0` and `risk_evidence.state = "missing"`, a record gets full `0.14` awareness
   credit. Changing it means choosing how to renormalise `_compute_dqi`'s weights and would shift
   every experience's DQI — a calibration decision, deliberately left out of this minimal fix.
2. **Persisted summary text still prints `risk=0.0`.** `_persist_experience`'s `summary` string
   formats `record["risk_score"]` without the evidence state, so retrieval over Qdrant memory can
   read "risk=0.0" for an unmeasured episode. The payload's `market_context.risk_state` now
   carries `risk_evidence`, but the summary line does not. Worth a follow-up if those summaries
   are ever fed back into prompts verbatim.
3. **`prediction_usefulness`** in `_finalize_experience` computes `max(0.0, 1 - regime_uncertainty)`
   and therefore reports `1.0` when uncertainty was never measured.
4. **For ChatGPT to check in its own files:** whether `modules/strategy_manager.py`,
   `modules/market_thesis.py`, `modules/core_trading_sessions.py` or any persisted-payload reader
   assumes all five risk keys (`volatility`, `drawdown`, `exposure`, `concentration_risk`,
   `regime_uncertainty`) are always present in `risk_state`, or reads
   `risk_state["volatility_state"]` as a gate. I found no such consumer outside this module, the
   desktop shell renderer and `unified_runtime`, but those paths were not in my scope.
5. **Non-finite correction** (see §1): pre-fix NaN/±inf produced `high`, not `low` — the earlier
   review hypothesis should be revised in its notes.
6. **Do not infer r11 impact.** This is an isolated source change in an uncommitted worktree; the
   running demo executable was not rebuilt, restarted or inspected.

## 8. Safety statement

No order submission, broker call, credential access, service start/stop, tree reset/clean/stash,
broad staging, commit, push or deployment occurred. Every pre-existing worktree change, runtime
file, test and configuration was preserved.
