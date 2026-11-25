# Freebuff Task 03 — evidence-aware DQI and prediction usefulness

Date: 2026-11-21 · Component: `modules/adaptive_market_cognition.py` (quality-scoring section)
Status: implemented and tested locally, **not committed, not deployed and not live-tested**.
The r11 demo engine was not started, restarted or read; no broker, credential, release or
ChatGPT-owned file was touched.

## 1. Defects, reproduced before editing

Task 02 made risk *labels* honest but left two quality numbers claiming evidence that did not exist.

```
risk_evidence.state = "missing", risk_score = 0.0
  -> _compute_dqi: risk_awareness = 1 - 0.0 = 1.0  -> full 0.14 quality credit   (fabricated)
  -> _dqi_history: risk_awareness = 1.0            -> history asserts "fully aware" (contradicts record)
regime_uncertainty not measured (report 0.0)
  -> metaevaluation.prediction_usefulness = 1 - 0.0 = 1.0                        (fabricated)
```

Partial evidence had the same problem in weaker form: `volatility=0.0` measured alone received the
same 0.14 credit as five measured calm inputs, because the term only looked at `risk_score`.

Supporting artefact: `diagnostics/runtime-chain-fixed2-20261028/unified.json` (captured 2026-10-28,
older code) shows `"risk_awareness": 1.0` entries whose own reflection text says
`risk_awareness=0.0` — the reconcilability problem in real recorded output.

New file `tests/test_adaptive_market_cognition_quality.py` was written first and run against the
unmodified module:

```
python -m pytest tests/test_adaptive_market_cognition_quality.py -q --basetemp=.pytest-task03-pre
6 failed, 3 passed, exit 1     (9 collected)
```

Failure evidence:

- `test_missing_risk_evidence_earns_no_dqi_safety_credit`: `assert 0.5377 == 0.3977` — the
  no-evidence record carried the full `0.14` it had not earned.
- `test_partial_evidence_does_not_receive_complete_risk_credit`: partial and complete records with
  the same `risk_score` were indistinguishable.
- `test_unmeasured_regime_uncertainty_is_not_reported_as_useful`: `assert 1.0 is None`.
- `test_non_finite_regime_uncertainty_is_unmeasured_not_perfect`: NaN/±inf/`"n/a"`/`True` all
  produced `prediction_usefulness = 1.0`.
- `test_dqi_history_matches_the_computed_score_and_evidence_state`: `KeyError:
  'risk_awareness_state'`.
- `test_measured_zero_regime_uncertainty_is_a_real_measurement`: `KeyError:
  'prediction_usefulness_evidence'` (a measured `0.0` and an absent value were indistinguishable).

## 2. Policy adopted

**DQI is a documented composite process-quality index, not a calibrated probability of a correct
prediction.** Its seven weights sum to 1.0 and are unchanged:

```
signal 0.14 · confidence 0.17 · reflection 0.14 · evaluation 0.18
risk_awareness 0.14 · retrieval 0.10 · outcome 0.13
```

The only changed term is risk awareness. Instead of `(1 - risk_score) * 0.14` unconditionally:

| `risk_evidence.state` | coverage | credit applied | why |
|---|---|---|---|
| `complete` | 1.0 | `(1 - risk_score) * 0.14` | unchanged documented baseline |
| `partial` | measured weight share of the five inputs (e.g. volatility alone = 0.28) | `(1 - risk_score) * 0.14 * coverage` | credit only for what was measured; partial is not equated with complete |
| `missing` | 0.0 | `0.0` | no measurements, no safety credit |
| no `risk_evidence` key (legacy/caller record) | 1.0 | `(1 - risk_score) * 0.14` | previous behaviour, so old in-memory records do not silently drop |

Design notes:

- The other six components keep their documented fixed weights, so a record can never *gain*
  quality from missing evidence; it only forfeits the unearned share. A renormalise-everything
  variant was rejected because it can raise the score of an unmeasured record above a measured one.
- Coverage is the share of the five documented risk weights that were measured. It uses the same
  convex weights as `_calculate_risk`, so partial credit and partial risk scoring stay consistent.
- Credit is proportional, not binary: `partial` with only volatility measured cannot reach the
  complete-evidence term.

`metaevaluation.prediction_usefulness` now reports `1 - regime_uncertainty` **only when regime
uncertainty was actually measured**; otherwise it is `null` with
`"prediction_usefulness_evidence": "unmeasured"`. `null` was chosen over `0.0` (which would claim a
useless prediction) and over `0.5` (a fabricated midpoint). Measured `0.0` still yields `1.0` — that
is a real reading.

`_dqi_history` entries now report the credit the DQI actually applied plus its provenance:

```json
{"trace_id": "...", "topic": "...", "latest": 0.3977,
 "risk_awareness": 0.0, "risk_awareness_state": "missing",
 "risk_awareness_measured": false, "risk_evidence_coverage": 0.0,
 "outcome_quality": 0.5}
```

`risk_awareness` in history is therefore the applied weighted credit (0..0.14), not `1 - risk_score`
(0..1): the two numbers can no longer disagree, because there is only one. `risk_awareness_measured`
and `risk_awareness_state` separate a measurement from a numerical fallback.

## 3. Before/after numbers (measured in-process, not extrapolated)

Probe: one experience each, `evaluation_score = 0.5`, `regime = bull`, no retrieval counts.
`dqi_old` is the pre-fix value for the same record (observed for `missing`; derived arithmetically
from the documented formula for the others, since the module was already patched when the probe ran).

| case | risk_score | evidence | credit (new) | coverage | DQI new | DQI old | prediction_usefulness |
|---|---|---|---|---|---|---|---|
| no inputs | 0.0 | missing | 0.0 | 0.0 | **0.3977** | 0.5377 | `null` / unmeasured |
| volatility 0.9 only | 0.9 | partial | 0.0039 | 0.28 | **0.3643** | 0.3744 | `null` / unmeasured |
| volatility 0.0 only | 0.0 | partial | 0.0392 | 0.28 | **0.4370** | 0.5378 | `null` / unmeasured |
| all five 0.0 | 0.0 | complete | 0.14 | 1.0 | **0.5377** | 0.5377 | `1.0` / measured |
| mixed (0.5/0.2/0.4/0.3/0.6) | 0.397 | complete | 0.0844 | 1.0 | **0.4704** | 0.4704 | `0.4` / measured |

Reading of the table:

- **Complete records are bit-identical** to the previous formula (0.5377, 0.4704). No baseline moved.
- **No-evidence records lose exactly the 0.14 they never earned** (0.5377 → 0.3977).
- **Partial records keep a proportionate share** (0.28 of the term here), so a calm-but-thinly-measured
  record now sits below an equally calm fully-measured one (0.4370 vs 0.5377) instead of tying it.
- A record with *measured high risk* (`volatility 0.9`) scores 0.3643 — below the no-evidence record at
  0.3977. That ordering is intended: measured high risk is negative evidence, while no evidence is
  neither credit nor penalty beyond the forfeited credit.
- `regime_uncertainty` is missing in the first three cases because the probe sent no `uncertainty`
  field; measured `0.0` (calm) still yields `prediction_usefulness = 1.0`.

Telemetry after the five records: `dqi_snapshot = {'latest': 0.4704, 'recent_average': 0.4414,
'similar_average': 0.4414}`, `telemetry.dqi_score = 0.4704`, `json.dumps(status(),
allow_nan=False)` succeeds (27 188 chars), as does `render_command("market intelligence dqi")`.

## 4. Consumer trace and compatibility

| Consumer | Effect |
|---|---|
| `_finalize_experience` → `record["dqi_score"]` | unchanged type (`float`, 0..1); value drops only where credit was unearned. |
| `record["metaevaluation"]["prediction_usefulness"]` | `float` when measured, `null` when not; new sibling key `prediction_usefulness_evidence`. No in-repo reader exists (verified by search outside `diagnostics/`). |
| `_dqi_history` → `status()["dqi_scores"]` → `desktop_runtime_shell` | entry gains `risk_awareness_state`, `risk_awareness_measured`, `risk_evidence_coverage`; `risk_awareness` changes scale to the applied credit. The shell prints only `latest` and `outcome_quality`, so rendering is unaffected. |
| `_dqi_snapshot` → `bundle.dqi_snapshot` → `"decision_quality_index: …"` context line | logic unchanged; the newest `latest` can be lower for unmeasured episodes. The context line is a process index, not a probability. |
| `bundle.telemetry["dqi_score"]` → `desktop_runtime_shell` "last_dqi", `_retrieval_history` | unchanged shape and type. |
| `_persist_experience` → Qdrant `coherence_score`, KB fact `dqi=…` | carries the corrected value; payload keys unchanged. Summary text still prints `risk=0.0` for unmeasured risk (Task 02 follow-up, not touched here). |
| `hypothesis_engine._confidence_signal` (`_clamp(payload.get("dqi_score"), 0.0)`, fallback 0.45) | unaffected: still a finite float, no NaN possible. |
| `unified_runtime` status `dqi_scores[:5]` / `test_unified_runtime_architecture` | unaffected; assertions on presence only. |
| `_derived_confidence`, `_build_reflection`, retrieval similarity | unchanged. `_build_reflection` still prints `risk_awareness=<risk_score>`, a mislabel noted in Task 02 and left alone here. |

Compatibility summary:

- **Additive** metadata (`prediction_usefulness_evidence`, three `_dqi_history` keys) plus one
  **nullable** field (`prediction_usefulness`). Nothing was removed or renamed.
- **Historical scores are not comparable across the upgrade for incomplete-evidence records.**
  Complete-evidence scores did not move, so rankings among fully measured episodes are unchanged;
  episodes with missing/partial risk data now rank lower than before relative to measured ones.
- **No migration of stored records was performed.** Qdrant/KB entries written before this change
  keep their old DQI and `coherence_score`; they cannot be corrected without re-scoring. If a
  comparative historical series is needed, the recommended migration is a `dqi_policy` stamp on
  new records (e.g. `"evidence-aware-v1"`) and a reader-side filter — documented here rather than
  implemented, because that touches the persisted schema and is a calibration decision.
- Legacy in-memory records without `risk_evidence` keep the previous full-weight credit and are
  labelled `risk_awareness_state: "unrecorded"`, so they are distinguishable in telemetry.

## 5. Tests and exact results

New file `tests/test_adaptive_market_cognition_quality.py` (9 tests): no-evidence credit, complete
baseline equality with the documented formula, partial vs complete credit, measured-zero vs missing
regime uncertainty, non-finite uncertainty, `_dqi_history`/score consistency, JSON serialisation of
status and the DQI command, and bound checks for extreme inputs.

| Run (in `Niblit/`) | Result |
|---|---|
| `python -m pytest tests/test_adaptive_market_cognition_quality.py -q --basetemp=.pytest-task03-pre` (before the patch) | **6 failed, 3 passed, exit 1** (9 collected) |
| `python -m pytest tests/test_adaptive_market_cognition_quality.py -q --basetemp=.pytest-task03-post2` | **9 passed, exit 0** |
| `python -m pytest tests/test_adaptive_market_cognition.py tests/test_adaptive_market_cognition_risk.py tests/test_adaptive_market_cognition_quality.py test_unified_runtime_architecture.py test_hypothesis_engine.py test_adaptive_retrieval_cognition.py test_desktop_runtime_shell_market_intelligence.py -q --basetemp=.pytest-task03-regress` | **58 passed, exit 0** |

`--basetemp` is required on this host (the default temp root raises `WinError 5`); temp directories
live inside the workspace and earlier ones (`.pytest-risk-uncertainty-*`, `.pytest-task03-pre`,
`.pytest-task03-post1`) were not deleted. `.pytest-task03-post1` was an intermediate failing run
(2 failures) caused by two test expectations, corrected before the final run.

Honest limits:

- **The full suite was not run.** The worktree is dirty with unrelated changes from parallel work.
- **Not compiled into, started by, or compared against the r11 engine.** Source is uncommitted; the
  running demo binary predates it. Nothing here demonstrates runtime or trading behaviour.
- **No live Qdrant round trip.** The Qdrant collection is unavailable in this environment
  (`collection not available`, swallowed to `log.debug`); persistence was checked through the KB fact
  path and JSON serialisation only.
- **No migration of historical scores**, no scoring-version stamp, no UI verification beyond the
  desktop-shell unit test that already existed.
- DQI remains a heuristic composite; nothing here calibrates it against outcomes, and no claim of
  improved predictive accuracy is made or implied.

## 6. Handoff for ChatGPT / Desktop Commander

1. Review `_risk_awareness_credit` and the `_DQI_WEIGHTS` table together with Task 02's
   `_RISK_WEIGHTS`: the two weight sets are intentionally independent (DQI is process quality, risk
   scoring is market exposure).
2. Decide the **scoring-version question**: whether new records should carry a `dqi_policy` stamp
   and whether stored Qdrant `coherence_score` values should be re-scored, filtered, or accepted as a
   mixed series. This is the only open design decision; the code change is complete.
3. Check your files for readers of `metaevaluation.prediction_usefulness` or
   `_dqi_history[...]["risk_awareness"]` (scale change 0..1 → 0..0.14). None exists in this
   repository outside `diagnostics/`, but broker/desktop code outside this tree was not inspected.
4. Verify `modules/strategy_manager.py` and `market_thesis.py` do not threshold on `dqi_score` in a
   way that assumes the old inflated value for unmeasured episodes. A 0.14 drop for no-evidence
   records is the intended effect; any gate tuned to the old number will shift.
5. Remaining Task 02 findings still open and untouched: `_persist_experience` summary prints
   `risk=0.0` for unmeasured risk; `_build_reflection` labels `risk_score` as `risk_awareness`;
   `_derived_confidence` gives unknown risk no penalty.
6. Do not infer r11 impact. This work must be built and run by you before any claim about the demo.

## 7. Changed files

- `modules/adaptive_market_cognition.py` — Task 03 hunks: `_DQI_WEIGHTS`,
  `_risk_awareness_credit`, `_compute_dqi(..., risk_credit=…)`, credit + history wiring and the
  prediction-usefulness guard in `_finalize_experience`. (`git diff --numstat` shows +165/−36 for
  this file, cumulative for Tasks 01–03, uncommitted.)
- `tests/test_adaptive_market_cognition_quality.py` — new, 9 tests.
- `docs/FREEBUFF_TASK_03_STATUS.md`, `docs/FREEBUFF_TASK_03_RESULT.md` — this handoff.

## 8. Safety statement

No order, broker call, credential access, service start/stop, tree reset/clean/stash/checkout,
broad staging, commit, push, build or deployment occurred. Every pre-existing worktree change,
runtime file, test and configuration was preserved. Work stopped within the 90-minute budget.
