# Freebuff Task 06 — Result

Decision Quality Index (DQI) scoring stabilization and evidence calibration.

## 1. Where generated text length was influencing cognition scores

| Location | Before | Used for | Status |
| --- | --- | --- | --- |
| `_compute_dqi` (`adaptive_market_cognition.py:1029`, was `:796`) | `reflection_quality = min(1.0, len(reflection.split()) / 40.0)`, weight 0.14 | 14% of every DQI score | **replaced** by the six-check labelled-evidence score |
| `_finalize_experience` metaevaluation (`:484`, was `:472`) | `reflection_usefulness = min(1.0, len(reflection.split()) / 50.0)` | `record["metaevaluation"]`, consumed by `global_cognitive_metrics` and `hypothesis_engine` | **replaced** by the same reasoning score, plus `reflection_usefulness_basis` / `..._checks` |
| `_risk_evidence_label` (`:657`) | Task 05 deliberately padded the missing-risk label so its word count matched the measured labels, because `words / 40` fed DQI | wording of every reflection | **constraint removed**; the label wording no longer affects the score (kept as-is, since it is now inert) |
| `_dqi_snapshot` (`:1271`) | averaged `dqi_score` across mixed scoring contracts | retrieval bundle, LLM context line, telemetry | **policy-filtered** (see §4) |
| `adaptive_retrieval_cognition.py:303` | `min(1.0, len(reflection.split()) / 50.0)`, weight 0.12 | that module's own retrieval-quality index | **not changed** (different layer, outside Task 06 file scope) — see §7 |
| `cognitive_episode.py:487` | `cb.get("reflection_confidence")` | episode metaevaluation | already not length-based; unaffected |

Two things made the old term worse than simple verbosity: it was **capped at 40 words**, so the
Task 05 evidence labels (39 → 54 words) moved typical records from `0.975` to `1.0` without any
new evidence; and it could be **saturated by padding**, because splitting on whitespace counts
repeated words.

## 2. New scoring term

`_reasoning_quality(experience, risk)` (`:730`) returns `(score, detail)` where the score is
`checks_passed / 6`. It reads the reflection's labelled sections (`_reflection_sections`, `:704`)
and compares them with the episode's recorded values. Repetition cannot help: only the first
occurrence of each label is read, and a section ends at the next label.

| Check | Question | Fails when |
| --- | --- | --- |
| `observations_grounded` | does `observed=[…]` report a value the episode recorded (evaluation, confidence, retrieval count, measured risk inputs)? | no observations, or only invented numbers |
| `predictions_separated` | does `predicted=[…]` reproduce the recorded scenario probabilities, or say none were recorded? | a probability is asserted for an episode that recorded no forecast |
| `outcomes_not_conflated` | does `verified_outcome=[…]` claim verification only when the record carries it? | "verified" without `outcome_verified`, a realised value that is missing, or a claimed realised value that differs |
| `assumptions_scoped` | is `inferred=[…]` marked as assumption/inference and consistent with the recorded regime? | unmarked assumptions, or a regime the episode never carried |
| `risk_evidence_reported` | does the risk statement match the evidence state? | missing evidence described as measured, partial described as complete |
| `decision_evaluated` | does the reflection name the decision it evaluates and report its recorded score? | generic prose that never identifies the episode |

Weights are unchanged and still sum to 1.0; only the 0.14 term's meaning changed. The term was
renamed from `reflection` to `reasoning` inside `_DQI_WEIGHTS` so the name cannot be mistaken
for a length measure.

`_dqi_breakdown` (`:965`) now returns the score, the term values, the weights and the reasoning
check detail; `_compute_dqi(experience, *, risk_credit=None, reasoning_quality=None)` keeps its
float contract and simply returns `["score"]`. Each finalized record carries
`record["dqi_components"]`, so a stored score can be re-explained without re-running the layer.

## 3. Before / after, identical evidence

Probe pinned `confidence=0.5` (so derived confidence could not move the numbers) and used the
default topic/regime/evaluation:

| Evidence | Reflection words | v1 DQI | v2 DQI | Reasoning | Risk credit |
| --- | --- | --- | --- | --- | --- |
| missing (0/5 inputs) | 39 | 0.4615 | **0.4650** | 1.0 | 0.0 |
| partial (1/5) | 39 | 0.5007 | **0.5042** | 1.0 | 0.0392 |
| complete (5/5) | 39 | 0.6015 | **0.6050** | 1.0 | 0.14 |

The uniform `+0.0035` is exactly the old cap: v1 paid `39/40 = 0.975` for a complete labelled
reflection, v2 pays `6/6 = 1.0`. The evidence-based ordering (missing < partial < complete) is
unchanged and still driven by risk credit, not by text.

Verbosity and honesty, same record (partial, 0.4 volatility):

| Variant | Words | DQI | Effect |
| --- | --- | --- | --- |
| generated reflection | 39 | 0.4885 | baseline |
| same facts, padded prose | 74 | **0.4885** | no gain for +35 words |
| reflection repeated twice | 78 | **0.4885** | repetition adds nothing |
| 96 words, no evidence labels | 96 | **0.3485** | loses the whole 0.14 term |
| fabricated scenario probability | 44 | **0.4652** | −0.0233 (1/6) for an unsupported prediction |
| missing-risk record claimed as measured | 39 | −0.0233 | 1/6 lost for contradicting the evidence state |

A concise reflection that still labels the four sections, names the decision and states the
recorded risk evidence scores **exactly** the same as the verbose one (test
`test_identical_evidence_scores_the_same_short_and_long`).

## 4. Policy versioning and legacy records

`_DQI_POLICY = "evidence-aware-v2"` (`:610`). v1 scored reflection length, so v2 scores are not
comparable with v1 scores for the same evidence; the constant is now the single source of truth
for every stamp.

- **Record**: `record["dqi_policy"]` and `record["dqi_components"]["policy"]`.
- **History**: each `file.dqi_scores[...]` entry keeps `dqi_policy` and gains `reasoning_quality`.
- **Status**: `status()["dqi_policy"]` plus `status()["dqi_policy_versions"]`, a count per policy
  present in the in-memory history (`:406`).
- **Memory payloads**: `dqi_policy` is taken from the **record**, not from the current constant
  (`record_policy`, `:1093`), so persisting an old record cannot restamp it. A legacy record with
  `dqi_policy="evidence-aware-v1"` and `dqi_score=0.2935` is written back as v1/0.2935, and
  `dqi_reasoning_quality` stays `None` because no v2 term ever scored it. New records also write
  `dqi_reasoning_quality` (`:1118`, `:1142`).
- **Retrieval snapshot**: `_dqi_snapshot` (`:1271`) reports `policy`, `latest_policy`,
  `latest_is_current_policy`, `policies`, `similar_policies`, `legacy_records_excluded` and
  `legacy_similar_excluded`. Averages are computed **only** from current-policy entries; a legacy
  similar record is excluded when the store already holds current-policy scores, and the recent
  average is used instead of mixing contracts. A store with no v2 record at all still reports its
  own legacy numbers, flagged by `latest_is_current_policy: False`.

No stored memory is rescored, migrated or deleted.

## 5. Governance separation preserved

- `_persist_experience` still derives `coherence_score` independently: an explicit
  `coherence_score` wins, otherwise `max(0.3, dqi)`. The admissibility floor was not lowered.
- DQI is never used as the coherence field, and the two are asserted different in the new tests.
- `governed_recall_allowed` still passes for a low-DQI record whose coherence sits at the floor
  (`test_low_dqi_still_retrieves_through_governed_memory`), so a lower v2 score cannot block
  legitimate retrieval.
- No constitutional threshold, approval gate or `position_exit_policy` behaviour was touched.

## 6. Test map

| Requirement | Test |
| --- | --- |
| policy stamped on record/history/status/memory + breakdown | `test_records_carry_the_new_policy_and_a_breakdown` |
| legacy records not restamped or rescored | `test_legacy_scores_are_persisted_without_being_restamped_or_rescored` |
| short vs long identical evidence | `test_identical_evidence_scores_the_same_short_and_long` |
| repeated / padded text | `test_repeating_the_reflection_does_not_raise_dqi`, `test_long_evidence_free_reflection_earns_no_reasoning_credit` |
| unsupported prediction | `test_unsupported_prediction_lowers_dqi` |
| verified vs unverified outcome | `test_unverified_outcome_cannot_be_described_as_verified`, `test_verified_and_unverified_outcomes_stay_distinguishable` |
| missing evidence never measured | `test_missing_risk_evidence_cannot_be_reported_as_measured`, `test_missing_evidence_never_outscores_the_same_measured_evidence` |
| NaN / inf / invalid inputs | `test_non_finite_and_invalid_inputs_stay_finite` |
| determinism | `test_scoring_is_deterministic_across_repeated_evaluations` |
| historical DQI records | `test_legacy_scores_are_excluded_from_current_policy_averages`, `test_a_purely_legacy_store_still_reports_its_scores` |
| retrieval snapshot compatibility | `test_retrieval_bundle_exposes_the_scoring_policy` |
| governed Qdrant memory | `test_low_dqi_still_retrieves_through_governed_memory` |

`tests/test_adaptive_market_cognition_dqi.py` holds all 15; the earlier Task 01–05 cognition and
quality tests still pass unchanged apart from the three literal-policy comparisons and the
`_documented_dqi` reconstruction noted in STATUS.

## 7. Compatibility risks and remaining issues

1. **Absolute DQI values moved.** For the same complete evidence, v2 scores `+0.0035` above v1
   because a 39-word reflection no longer loses 2.5% of the reasoning term. Dashboards that
   compare v2 to a v1 baseline must filter on `dqi_policy`/`policy` — the snapshot now publishes
   the counts needed to do that. Do not average v1 and v2 in a single series.
2. **v1 is still reachable.** A layer process running the old code, or any stored v1 payload,
   keeps writing v1. `policies`/`legacy_records_excluded` surface that; nothing is migrated
   automatically.
3. **`adaptive_retrieval_cognition.py:303` is still verbosity-scored.** Its index uses
   `min(1, words/50) * 0.12` for a different composite. It was outside the Task 06 scope and is
   called out here so it can be scheduled; a padded reflection can still raise that module's
   score.
4. **The reasoning checks are a structural heuristic.** A caller that supplies its own
   `reflection_summary` (via `observe_event`) instead of the generated reflection now scores the
   reasoning term on that text: a prose summary earns 0.0 even if it is accurate, and a summary
   that happens to reproduce the labels scores 1.0. This is deliberate — unevidenced prose gets
   no credit — but integrations that inject their own reflections will see lower DQI than before
   and should either adopt the labelled format or accept the penalty.
5. **`metaevaluation.reflection_usefulness` changed basis.** It is now 0.0–1.0 in 1/6 steps
   instead of a smooth word ratio. `global_cognitive_metrics` and `hypothesis_engine` treat it as
   a bounded float, so the contract holds, but any downstream calibration tuned to the old
   distribution should be re-checked.
6. **`hypothesis_engine._confidence_signal`** still folds `dqi_score` into a `max()` alongside
   evaluation/confidence, so a v2 DQI drop of 0.02 can only matter when DQI is the largest input.
   No change was needed, but the v1→v2 shift should be considered when interpreting hypothesis
   confidence.
7. **`dqi_snapshot["similar_average"]`** falls back to `recent_average` when every similar record
   is legacy and current-policy history exists. It is never a silent legacy mix, but it is an
   average of a different population than the field name suggests; the
   `legacy_similar_excluded` count is the signal to read alongside it.
8. **No live-store verification.** Persistence was exercised only against the fake
   `write_memory` cluster; the live Qdrant collection reports `collection not available` on this
   host, so payload acceptance by a real collection is unverified.
9. **Pre-existing, unrelated failure**:
   `tests/test_runtime_stream_responsiveness.py::test_websocket_snapshot_runs_off_the_request_loop[server]`
   fails with `'Socket' object has no attribute 'query_params'` at `server.py:2747`. `server.py`
   belongs to concurrent trading-desk work and was not edited here.

## 8. Boundaries honoured

`modules/position_exit_policy.py`, MT5/Freqtrade configuration, execution permissions, broker
adapters, release manifests and deployment scripts were not modified. No order, build, restart,
commit, push or deploy was performed. The r12 Core process was not touched.
