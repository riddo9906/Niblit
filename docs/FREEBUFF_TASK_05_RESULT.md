# FREEBUFF TASK 05 — RESULT

**Market Cognition Evidence Integrity**
Repository `C:\Users\Riyaad\Documents\GitHub\Niblit`, branch `fix/exness-demo-readiness-20261118`, HEAD `301571f0`.
All line numbers refer to `modules/adaptive_market_cognition.py` after the Task 05 edits.

---

## 1. Findings and fixes

### F1 — Persisted summary reported unmeasured risk as `risk=0.0` (confirmed defect, fixed)

`_persist_experience` built its summary from the bare numeric field:

```
risk={record.get('risk_score')}
```

A record with no risk inputs stores `risk_score = 0.0` for numeric compatibility (`_calculate_risk`, line 595), so the memory text, the KnowledgeDB fact and the reflection memory all read `risk=0.0` — indistinguishable from a fully measured calm market. This was the Task 02 open item.

**Fix:** `_risk_evidence_label` (line 640) renders the score together with its evidence state, and `_persist_experience` (lines 862–876) now writes:

| Case | Summary fragment |
| --- | --- |
| no inputs measured | `risk=unmeasured (0/5 risk inputs measured)` |
| one input measured at 0.0 | `risk=0.0000 (partial, 1/5 risk inputs)` |
| all five measured at 0.0 | `risk=0.0000 (measured, 5/5 risk inputs)` |
| legacy record, no evidence field | `risk=<score> (evidence state unrecorded)` |

The same label is also embedded in the generated reflection (line 708), and both memory payloads now carry machine-readable `risk_evidence_state` and `risk_score_measured` (lines 889–891, 912–914) next to `dqi_score`/`dqi_policy`. The numeric `risk_score` contract is unchanged.

Measured (mocked cluster, same topic/evaluation):

```
risk=0.0000 (partial, 1/5 risk inputs) dqi=0.4903 dqi_policy=evidence-aware-v1 risk_evidence=partial outcome=mixed
risk=0.0000 (measured, 5/5 risk inputs) dqi=0.5973 dqi_policy=evidence-aware-v1 risk_evidence=complete outcome=mixed
```

### F2 — Reflection asserted unverified verdicts and mislabelled risk (confirmed defect, fixed)

`_build_reflection` previously produced:

```
worked=signal coherence held; failed=risk controls contained uncertainty;
assumption_correct=bull regime context mattered; assumption_wrong=ignore risk spikes;
confidence_calibration=<eval - confidence>; risk_awareness=<risk_score>.
```

Problems: "signal coherence" and "risk controls" were never measured; `assumption_correct` asserted verification that never happened; the signed difference `evaluation - confidence` was labelled calibration; and `risk_awareness` printed the risk score, which is the opposite quantity (the Task 02 mislabelling).

**Fix:** `_build_reflection` (line 671) emits four explicitly labelled sections, and `_verified_outcome_label` (line 661) refuses to upgrade an evaluation score into a verified result:

```
observed=[evaluation_score=0.5; confidence_score=0.405; risk_inputs_measured=0/5 (missing); retrievals=0];
inferred=[signal_coherence=not directly measured; confidence_calibration=-0.0950 (confidence within recorded evaluation);
          regime_context=bull (assumed from event, unverified)];
predicted=[none recorded for this episode];
verified_outcome=[none recorded (no realised result attached)];
risk=unmeasured (0/5 risk inputs measured).
```

- `observed` contains only values the episode carries plus the measured-input count.
- `inferred` states that coherence is not directly measured and that regime context is an unverified assumption.
- `predicted` reports recorded `signal_state.scenario_probabilities` if present, otherwise "none recorded"; predictions are marked `(recorded forecast, unverified)`.
- `verified_outcome` becomes a real value only when the caller supplies `realized_outcome`; `_outcome_state` (line 567) now stores `outcome_verified` / `realized_outcome` (lines 575–579) instead of letting the derived `_outcome_label` look verified.

**Ordering fix found by probing:** `_build_reflection` ran before `_derived_confidence`, so it reported `confidence_score=0.0` while the record stored 0.405. `_finalize_experience` now computes `evaluation_score` (significance merge) and the derived confidence *before* building the reflection (lines 443–451), so the reflection reports the value the episode actually carries.

### F3 — Unknown risk received no confidence penalty (confirmed design gap, fixed)

`_derived_confidence` was `base − 0.3 × risk_score`. When risk evidence was missing, `risk_score` was the 0.0 placeholder, so an unmeasured market received *more* confidence than the same market with low-but-measured risk.

**Fix:** `_derived_confidence` (line 711) keeps the measured-risk term and adds an evidence penalty proportional to the unmeasured share:

```
confidence = 0.35 + 0.35·evaluation + 0.04·retrievals
             − 0.3·risk_score      (omitted when nothing was measured)
             − 0.12·(1 − coverage)
```

with coverage from `_risk_evidence_coverage` (line 742, weighted by the documented `_RISK_WEIGHTS`, so partial evidence is charged proportionally). Legacy records without `risk_evidence` keep coverage 1.0 and the previous behaviour; no observation is invented in any branch.

Measured (no confidence supplied):

| Evidence | Confidence before | Confidence now | DQI now |
| --- | --- | --- | --- |
| missing (0/5) | 0.525 | **0.405** | 0.4453 |
| partial (1/5, measured 0.0) | 0.525 | **0.4386** | 0.4903 |
| complete (5/5, measured 0.0) | 0.525 | 0.525 (unchanged) | 0.5973 |

The complete-evidence path is bit-identical to the pre-Task-05 formula; only unmeasured/partial evidence is penalised.

### F4 — DQI, policy, evidence state and coherence consistency (fixed defects + verified invariants)

Changes:

- `_DQI_POLICY = "evidence-aware-v1"` (line 593) is now the single source for the record (line 470), the in-process DQI history entry (line 517), `status()` (line 400), both persisted payloads (lines 889, 912) and the retrieval snapshot (line 1041).
- `_dqi_snapshot` reported a real `0.0` DQI as the recent average: `float(latest.get("latest", avg) or avg)` treats `0.0` as falsy. It now checks for `None` explicitly and clamps (lines 1050–1057), and exposes `policy`, `latest_risk_awareness_state` and `latest_risk_awareness_measured` so retrieval can tell which evidence the score rests on.
- `_aggregate_risk` (line 979) averaged the placeholder `0.0` of missing-evidence records into the retrieval risk profile, dragging it towards calm. It now averages only records that measured risk, averages `regime_uncertainty` over real measurements, and reports `risk_inputs_measured` / `experiences_considered` alongside `risk_evidence_state` (lines 1000–1025).
- Verified invariant: record `dqi_score` = history `latest` = persisted `dqi_score` across episodic and reflection writes = snapshot `latest`; the risk term is the credit actually granted (`0.0` missing, `0.0392` partial 1/5, `0.14` complete in the probe), and the coherence projection remains independent — `coherence_score = max(0.3, dqi)` only when the record has no measured coherence, so a low DQI is not rewritten as "unstable memory" and coherence is not presented as DQI.

### F5 — `_clamp` turned non-finite input into 1.0 (confirmed defect, fixed)

`_clamp` used `max(0.0, min(1.0, float(value)))`. With `NaN`, both comparisons are false and the chain returns `1.0` — a missing/garbage measurement became maximum confidence/quality. A regression assertion proved it: `_clamp(float("nan")) == 1.0`.

**Fix:** `_clamp` (lines 56–62) substitutes the default for any non-finite value before clamping. `_optional_clamp` already returned `None` for NaN/inf/bools, so risk inputs were unaffected; this closes the gap for every other clamped field (`confidence`, `evaluation_score`, `quality_score`, signal strength, scenario probabilities).

---

## 2. Regression tests

New file `tests/test_adaptive_market_cognition_evidence.py`, 18 tests:

| Area | Tests |
| --- | --- |
| Missing vs measured-zero persistence | `test_persisted_summary_distinguishes_unmeasured_from_measured_zero`, `test_partial_evidence_summary_counts_measured_inputs` |
| Invalid / non-finite inputs | `test_invalid_risk_inputs_stay_unmeasured_in_the_persisted_summary`, `test_invalid_confidence_and_risk_inputs_yield_finite_confidence`, `test_unknown_risk_labels_are_bounded_and_clamped` |
| Reflection correctness | `test_reflection_labels_observed_inferred_predicted_and_verified_sections`, `test_reflection_reports_the_derived_confidence_the_episode_carries`, `test_reflection_reports_recorded_scenarios_as_unverified_predictions`, `test_reflection_reports_measured_risk_with_its_evidence_not_as_awareness`, `test_reflection_reports_unmeasured_risk_as_unmeasured`, `test_reflection_only_marks_outcomes_the_caller_supplied_as_verified` |
| Confidence behaviour | `test_unmeasured_risk_confidence_is_lower_than_measured_zero_risk`, `test_partial_evidence_confidence_sits_between_missing_and_complete`, `test_measured_risk_still_lowers_derived_confidence` |
| DQI / coherence / retrieval consistency | `test_dqi_policy_and_evidence_state_agree_across_record_history_status_and_memory`, `test_coherence_projection_stays_independent_of_a_low_dqi`, `test_dqi_snapshot_reports_a_recorded_zero_instead_of_substituting_the_average`, `test_retrieval_risk_profile_ignores_records_with_no_risk_evidence` |

Adjusted existing test: `tests/test_adaptive_market_cognition_quality.py::test_missing_risk_evidence_earns_no_dqi_safety_credit` now pins `confidence=0.5` on both records, because derived confidence is evidence-aware. The assertion (risk term differs by exactly `0.14` with identical evaluation/confidence) is unchanged and still strict. All other Task 01–03 tests pass unmodified.

### Exact results

```
python -m pytest tests/test_adaptive_market_cognition.py tests/test_adaptive_market_cognition_risk.py \
  tests/test_adaptive_market_cognition_quality.py tests/test_adaptive_market_cognition_evidence.py \
  test_adaptive_retrieval_cognition.py test_unified_runtime_architecture.py test_hypothesis_engine.py \
  test_desktop_runtime_shell_market_intelligence.py test_governed_qdrant_memory.py \
  --basetemp=.pytest-task05-audit/tmp
=> 86 passed in 61.10s, exit 0

python -m pytest tests/test_market_memory_quality_governance_r12.py --basetemp=.pytest-task05-audit/tmp
=> 3 passed in 5.63s, exit 0
```

No test was skipped, weakened or marked xfail.

---

## 3. Remaining integration concerns for ChatGPT

1. **DQI is not comparable across the Task 04/05 boundary.** `reflection_quality` is `min(1, words/40)` and the labelled reflection is longer (~54 words vs ~30), so previously capped-at-<1 reflection terms now reach 1.0 and DQI rises slightly for the same evidence. The risk term and weights are unchanged, and `dqi_policy` now identifies the contract, but stored Task 03-era scores should not be averaged with new ones in a dashboard or replay without filtering. Suggested follow-up (not done): score reflection quality from structured sections rather than raw word count.
2. **Desktop rendering still prints bare risk numbers.** `modules/desktop_runtime_shell.py` lines 878, 886 and 898 print `risk={item.get('risk_score')}`, reproducing the misleading `risk=0.0` for unmeasured records. That file was outside Task 05's allowed edit scope; adopting `_risk_evidence_label` (or the new payload fields) there is a one-line-per-site follow-up.
3. **0.0 vs unreported confidence remains ambiguous upstream.** `_confidence_state` clamps a missing confidence to 0.0 and `_finalize_experience` treats `<= 0.0` as "not supplied", so a caller that genuinely reports zero confidence is overridden by a derived value. This predates Task 05 and was not changed; a sentinel or explicit `confidence_evidence` flag would resolve it.
4. **No upstream realised-outcome producer exists yet.** `outcome_verified` / `realized_outcome` are honoured and tested, but no in-repo caller supplies them, so reflections will honestly say `verified_outcome=[none recorded ...]` until execution/outcome reporting is wired. Do not substitute `evaluation_score` for verification.
5. **Legacy records keep old behaviour by design.** Experiences lacking `risk_evidence` still receive full retrieval risk weight, full DQI risk credit and no confidence evidence penalty. This avoids retroactive penalisation, but means pre-Task-03 records mixed into the 180-record window still read as full-evidence records. They age out; no re-scoring was attempted.
6. **KnowledgeDB tags do not carry evidence state.** The fact text now says `risk_evidence=<state>`, but tags are still `market_cognition/<regime>/<volatility>/<symbol>`, so tag-only filters cannot separate measured from unmeasured records.
7. **Persistence was verified with a mocked cluster.** The live cluster currently answers `collection not available (niblit_episodic_memory)`, swallowed to `log.debug`; the real Qdrant insert/recall path is unchanged and was not exercised.
8. **Verification-environment quirk:** a single pytest invocation combining the nine-file set above with `tests/test_market_memory_quality_governance_r12.py` exited 4 before collection ("no tests ran"), while each set passes independently. Cause not investigated; both suites pass as reported.

---

## 4. Constraints honoured

- Only `modules/adaptive_market_cognition.py` and cognition tests were edited; no manifests, scripts, broker adapters, permissions or trading engines.
- Uncommitted Task 01–04 work preserved (`git diff --numstat` grew from 181/38 to 380/55; nothing removed).
- Public APIs preserved: `observe_event`, `build_market_retrieval_bundle`, `update_runtime_outcome`, `status`, `render_command`, `_compute_dqi(experience, *, risk_credit)`, `_derived_confidence(experience, risk)`, `_build_reflection(experience, risk)`, `_persist_experience(record)` signatures unchanged; numeric `risk_score` and `confidence_score` remain floats.
- Nothing committed, staged, deployed, built, restarted, or connected to a broker/Qdrant.
