# Freebuff Task 04 — evidence-aware cognition consumer audit

Date: 2026-11-21 · Scope: read-only audit of every in-repo consumer of the Task 03 outputs
(`prediction_usefulness` nullable, `_dqi_history.risk_awareness` scaled to the applied credit,
`risk_awareness_state` / `risk_awareness_measured` / `risk_evidence_coverage`, corrected DQI).
**No production file was changed.** Source is uncommitted, not built, not deployed, not live-tested.
The r11/r12 engines, broker paths, credentials and the ChatGPT-owned memory-projection work were not
touched.

## 0. Method and evidence base

- Searches over the whole repository for `prediction_usefulness`, `metaevaluation`,
  `risk_awareness`, `risk_evidence`, `dqi_score`/`dqi_scores`/`dqi_snapshot`, `last_dqi`,
  `decision_quality`, `coherence_score` (excluding `diagnostics/` recorded JSON except as historical
  evidence).
- Direct reading of every producer and consumer listed below.
- Two read-only in-process probes (no network, no Qdrant, no broker):
  - `.pytest-task04-audit/probe.log` — consumer arithmetic, persistence payload, legacy branch,
    mixed historical snapshot, history shape.
  - `.pytest-task04-audit/probe2.log` — DQI → `coherence_score` → constitutional law →
    `governed_recall_allowed`.
- Focused regression run, `.pytest-task04-audit/pytest.log`.

Probe pattern: market experience with `evaluation_score=0.5`, `regime=bull`, no retrieval counts;
"missing" = no risk inputs; complete = all five risk inputs measured.

## 1. Compatibility matrix

Legend — **OK**: verified compatible, no action. **C**: confirmed defect (reproduced).
**S**: suspected incompatibility (no in-repo reader exists; an external consumer could break).
**H**: historical/mixed-data concern, not a code defect.

| # | Reader | Expected type / range | Actual behaviour after Task 03 | Verdict |
|---|---|---|---|---|
| 1 | `_finalize_experience` → `record["dqi_score"]` — `modules/adaptive_market_cognition.py:450` | `float`, 0..1, documented 7-weight composite | 0.3977 for a no-evidence record (was 0.5377); complete-evidence records bit-identical (0.5377, 0.4704) | OK |
| 2 | `_dqi_history` writer — `adaptive_market_cognition.py:505-515` | entry with `latest` 0..1, `outcome_quality` 0..1 | adds `risk_awareness_state`, `risk_awareness_measured`, `risk_evidence_coverage`; `risk_awareness` is now 0..0.14 weighted credit (measured 0.0 missing / 0.14 complete) | C2/S1 |
| 3 | `status()["dqi_scores"]` — `adaptive_market_cognition.py:401` → `unified_runtime.py:929`, `:986` (`dqi_scores[-5:]` in telemetry) | list of dicts, JSON-serialisable | JSON-serialisable (status 5567 chars, `allow_nan=False`), passes through unchanged | OK |
| 4 | `render_command("market intelligence dqi")` — `adaptive_market_cognition.py:419` → registered in `niblit_core.py:2858` | JSON list to the CLI/operator | prints the new keys; no scale assertion anywhere | OK (S1 for human readers) |
| 5 | Desktop shell market panel — `modules/desktop_runtime_shell.py:859-892` (last_dqi `:870`, timeline `:874-878`, dqi_scores `:888-892`) | `telemetry.dqi_score` scalar; `latest` and `outcome_quality` per entry | reads only `latest`/`outcome_quality`/`dqi_score`; never reads `risk_awareness`, so the 0..1 → 0..0.14 scale change cannot affect rendering | OK |
| 6 | `_dqi_snapshot` — `adaptive_market_cognition.py:853-861` → context line `:300` → LLM context `unified_runtime.py:452` | three floats 0..1 | `latest 0.3977`, `recent_average 0.3977`, `similar_average 0.4677` in a mixed old/new probe; the context block also prints `dqi=0.54` (legacy) beside `dqi=0.40` (new) | H1 |
| 7 | `build_market_retrieval_bundle` similarity — `adaptive_market_cognition.py:245-283` (risk term `:277-283`) | float score 0..1 | unchanged logic; `risk_evidence_state` used only for the 0.08/0.04 weight; DQI is not a ranking term | OK |
| 8 | `bundle.telemetry["dqi_score"]` — `:344` → `unified_runtime.py:545`, desktop `:870`, `_retrieval_history` `:357` | `float` | still `float` (0.3977), no `None` possible | OK |
| 9 | `_persist_experience` → Qdrant `coherence_score` — `adaptive_market_cognition.py:716-760`, lines `:732` and `:751` | 0..1 "coherence" consumed by governance and ranking | **carries the DQI, which can now fall below governance thresholds** | **C1** |
| 10 | `memory_contracts.normalize_memory_payload` — `shared/governance_contract/memory_contracts.py:253-266` | 0..1 | maps `coherence_score` to both `coherence_score` and `stability_score`, then calls `constitutional_verdict` | **C1** |
| 11 | `constitutional_verdict` — `shared/governance_contract/constitutional_laws.py:25-33` | `stability_score >= 0.3`, `coherence_score >= 0.1` | DQI 0.2935 trips `law_1_preserve_system_integrity`; DQI < 0.1 additionally trips `law_6` | **C1** |
| 12 | `governed_recall_allowed` — `memory_contracts.py:385-403`, gate in `niblit_memory/governed_qdrant_memory.py:197` | `allowed: bool` | returns False for the DQI 0.2935 payload, so the market memory is dropped from `recall()` | **C1** |
| 13 | `memory_retrieval_score` — `memory_contracts.py:406-425` (`coherence_score * 0.15`) | 0..1 | measured `0.582655 → 0.561655` for `coherence_score` 0.5377 → 0.3977 (base 0.6) | OK / H1 |
| 14 | `EmbeddingRuntimeConfig.govern_score` — `modules/vector_store.py:168-186` (`coherence_factor * 0.15`) | 0..1 | measured `0.350655 → 0.329655` for the same pair | OK / H1 |
| 15 | `adaptive_retrieval_cognition._normalize_record` — `modules/adaptive_retrieval_cognition.py:290` | evaluation 0..1, falls back to `coherence_score` when no `evaluation_score` | for governed-memory rows without `evaluation_score`, the lower DQI becomes a lower "evaluation" quality (default 0.45 only when absent). No crash, but two different meanings share one field | S2 |
| 16 | `hypothesis_engine._confidence_signal` — `modules/hypothesis_engine.py:876-880`, `_impact_from_payload` `:882-893` | clamp to 0..1, floor 0.45; thresholds 0.68 / 0.4 | measured: 0.5377 → signal 0.5377, 0.4704 → 0.4704, 0.3977 → 0.45, 0.3643 → 0.45; **all four return `("unchanged", 0.0)`**, so no threshold flipped | OK |
| 17 | `record["metaevaluation"]["prediction_usefulness"]` — `adaptive_market_cognition.py:462-470` | was `float`; now `float or None` | `None` for a no-uncertainty probe, `1.0` for measured zero; `_persist_experience` does not persist `metaevaluation` at all (payload keys: `advisor_lineage, coherence_score, market_context, reflection_summary, replay_metadata, summary`), so null is confined to `status()` / command JSON | S3 |
| 18 | `CognitiveEpisode.metaevaluation: dict[str, float]` — `modules/cognitive_episode.py:58`, `:481` | its own float-only dict | independent computation (`runtime_coherence`, `market_interpretation_quality`, …); the market record's metaevaluation is never merged into it | OK |
| 19 | `_aggregate_risk` — `adaptive_market_cognition.py:816-846` | `risk_score` float, `risk_evidence_state` str | legacy item (no `risk_evidence`) → `risk_evidence_state: "unknown"`; no KeyError, no `None` leak | OK |
| 20 | `_risk_awareness_credit` legacy branch — `:630-659` | tuple `(credit, state, coverage)` | returns `(0.14, "unrecorded", 1.0)` for a record with no `risk_evidence`, and `(0.084, "unrecorded", 1.0)` for raw legacy risk keys | C2 (latent) |
| 21 | `_dqi_history[...]["risk_awareness_measured"]` — `:512` | `bool` meaning "a measurement exists" | `state != "missing"` makes `"unrecorded"` report `True` with `coverage 1.0` — claims a measurement that never happened. Not reachable through `observe_event` because `_calculate_risk` always stamps `risk_evidence` (`:601`); reachable for direct `_compute_dqi`/`_risk_awareness_credit` callers | C2 (latent) |
| 22 | `_persist_experience` summary string — `:717-721` | text `risk=<float>` | still prints `risk=0.0` for an unmeasured episode; the probe shows the stored summary retrieved back as `... risk=0.0 dqi=0.3977 ...` inside the LLM context block | S4 (known Task 02 item) |
| 23 | `_build_reflection` — `:605-613` | text | still prints `risk_awareness=<risk_score>` (0..1 risk score labelled as awareness) | S4 (known Task 02 item) |
| 24 | `update_runtime_outcome` — `:367-387` | mutates `_dqi_history[-1]["outcome_quality"]` | does not recompute `latest`; the stored DQI keeps the evaluation-based outcome. Pre-existing, unrelated to Task 03 | H2 |
| 25 | `_dqi_snapshot` fallback — `:853-861` | `latest: float` | `float(latest.get("latest", avg_similar) or avg_similar)`: a genuine `latest == 0.0` is replaced by `avg_similar` when similar records exist (measured 0.0 only when both are empty). Pre-existing | H2 |
| 26 | `strategy_manager.py` / `market_thesis.py` / `core_trading_sessions.py` | — | **zero** occurrences of `dqi`, `prediction_usefulness` or `risk_awareness`; no gate or threshold reads these fields | OK |
| 27 | Qdrant explanation surface — `governed_qdrant_memory.py:250` | copies `payload["coherence_score"]` into `explanation` | exposes the DQI value under a coherence label; numeric, no crash | H1 |

## 2. Confirmed defects (reproduced)

### C1 — Corrected DQI can now exclude a market memory from governed recall

Chain (all in-repo, each step read):

```
adaptive_market_cognition.py:450  dqi_score = _compute_dqi(...)
adaptive_market_cognition.py:732  payload["coherence_score"] = record["dqi_score"]
memory_contracts.py:253-266       coherence_score -> stability_score -> constitutional_verdict
constitutional_laws.py:25-33      stability_score < 0.3 -> law_1; coherence_score < 0.1 -> law_6
memory_contracts.py:393-394       allowed == False -> governed_recall_allowed() False
governed_qdrant_memory.py:197     recall() skips the record
```

Measured (`probe2.log`), missing risk evidence in every row:

| eval / conf | DQI new | old-equivalent DQI (+0.14) | violated law | recall allowed new | recall allowed old |
|---|---|---|---|---|---|
| 0.20 / 0.20 | 0.3090 | 0.4490 | — | True | True |
| 0.30 / 0.30 | 0.3400 | 0.4800 | — | True | True |
| **0.15 / 0.15** | **0.2935** | **0.4335** | **law_1** | **False** | **True** |
| 0.25 / 0.25 | 0.3245 | 0.4645 | — | True | True |
| 0.10 / 0.95 | 0.1370 | 0.2770 | law_1 | False | False |

So Task 03's honest credit can move a low-quality, no-evidence episode across the 0.3 governance
boundary, making a memory that was previously recallable permanently ineligible. The root cause is
older than Task 03 — a decision-quality composite is used as a *temporal coherence* / *stability*
score — but Task 03 is what makes the boundary reachable for records that never measured risk.

Severity: medium. It only affects episodes whose other quality components are already low
(DQI < 0.3), and it fails safe (memory withheld, no order or execution effect). It is still a silent
loss of evidence from retrieval, and it contradicts the intent of the Task 03 change.

### C2 — `"unrecorded"` legacy branch reports `risk_awareness_measured: True`

`adaptive_market_cognition.py:512` computes `risk_awareness_measured` as `state != "missing"`, so the
`"unrecorded"` state yields `True` while `risk_evidence_coverage` is `1.0` — i.e. a legacy record with
no evidence metadata is described as fully measured. Probe: `_risk_awareness_credit({"risk_score": 0.0,
"risk_state": {}})` → `(0.14, 'unrecorded', 1.0)`.

Not reachable through `observe_event` today (`_calculate_risk` at `:601` always stamps `risk_evidence`),
so this is a latent inconsistency for direct/private callers and for future refactors. Severity: low.

## 3. Historical / mixed-data concerns (no code defect, needs a policy decision)

### H1 — Old and new DQI coexist in one average

`_dqi_snapshot` (`:853-861`) averages `dqi_score` across in-memory experiences with no scoring-version
filter. Probe with one legacy record (0.5377, no `risk_evidence`) and one new record (0.3977, missing
evidence):

```
dqi_snapshot: {'latest': 0.3977, 'recent_average': 0.3977, 'similar_average': 0.4677}
context: "- decision_quality_index: {... 'similar_average': 0.4677}"
         "  • regime=bull vol=unknown conf=0.50 risk=0.00 dqi=0.54 outcome=unknown"
         "  • regime=bull vol=unknown conf=0.53 risk=0.00 dqi=0.40 outcome=mixed"
```

The LLM sees two DQI numbers produced by different formulas in the same block. `_aggregate_risk`
already labels legacy evidence as `"unknown"`; DQI has no equivalent marker, which is exactly the
`dqi_policy` gap Task 03 documented.

### H2 — Pre-existing snapshot/outcome quirks (unchanged, listed for completeness)

- `_dqi_snapshot`'s `latest` uses `or avg_similar`, so a real `0.0` latest is masked when similar
  records exist.
- `update_runtime_outcome` rewrites only `outcome_quality`, never `latest`, so an episode's DQI does
  not reflect its final response quality.

Neither is caused by Task 03 and neither was changed.

## 4. Suspected incompatibilities (no in-repo reader; verify outside this tree)

| # | Surface | Risk | Evidence |
|---|---|---|---|
| S1 | `_dqi_history[...]["risk_awareness"]` | an external dashboard/CSV/notebook that averaged it as a 0..1 "awareness" now averages a 0..0.14 credit (7× smaller). In this repo only `status()`/`render_command` expose it and the desktop shell does not print it | full-repo search: the only readers are docs and the Task 03 tests |
| S2 | Persisted `coherence_score` as "temporal coherence" | BI dashboards, Qdrant payload schemas (`qdrant_cluster_logic/payload_schemas/schema_v2_memory_payload.json`) and `adaptive_retrieval_cognition:290` treat it as coherence/evaluation; it is a DQI and now drops for unmeasured risk | probe: `coherence 0.5377 → 0.3977` changes `memory_retrieval_score` by −0.021 and `govern_score` by −0.021 |
| S3 | `metaevaluation.prediction_usefulness == null` | any external JSON consumer that formats it as a float (`f"{x:.2f}"`, pandas mean, TS number type) will error or coerce. Not persisted to Qdrant/KB in this repo; only `status()` and the `market intelligence` command emit it | probe: payload keys contain no `metaevaluation` |
| S4 | Retrieval text still says `risk=0.0` | memory summaries fed back into prompts keep claiming zero risk for unmeasured episodes; with DQI now honest, the pair (`dqi=0.3977`, `risk=0.0`) is internally inconsistent | probe: stored summary retrieved as `... risk=0.0 dqi=0.3977 ...` |

## 5. Safe correction recommendations (not implemented here)

Task 04 is analysis-only, and `_persist_experience` / memory contracts sit in the memory-projection
area owned by the parallel r12 work, so nothing was edited. Recommendations in priority order:

**R1 (addresses C1, one line each, backward compatible).** In `_persist_experience`
(`adaptive_market_cognition.py:732` and `:751`), stop publishing the DQI as `coherence_score`:

```python
"coherence_score": max(0.3, float(record.get("dqi_score", 0.0) or 0.0)),
"dqi_score": record.get("dqi_score"),          # explicit, additive
```

The floor keeps every market memory above the law-1 stability boundary (behaviour for records that
were already ≥ 0.3 is unchanged) while the true DQI stays available under its own name. Alternative:
`"coherence_score": 1.0` — cleanest semantically (the DQI is not a temporal-coherence measurement) but
it raises the ranking contribution of every market memory by up to 0.15·0.6, which changes recall
order more than the floor does. **Recommendation: the floor plus the explicit `dqi_score` key.** This
should be applied by whoever owns the memory projection, not by a Task 03 follow-up.

**R2 (addresses C2, one line).** `adaptive_market_cognition.py:512`:
`"risk_awareness_measured": risk_awareness_state in {"complete", "partial"}`.
Additive in effect; only the meaning of the boolean becomes truthful.

**R3 (addresses H1, schema decision).** Stamp new histories/records with
`"dqi_policy": "evidence-aware-v1"` (in `_dqi_history` at `:505-515` and in the persisted payload) and
filter same-policy entries in `_dqi_snapshot` before averaging, falling back to the unfiltered list
when no stamp exists. Do **not** re-score stored Qdrant values without an explicit decision: the Qdrant
collection is unavailable here and stored payloads predating Task 02 lack `risk_evidence`, so a
recomputation would invent evidence.

**R4 (addresses S4, small).** Add the evidence state to the persisted summary
(`:717-721`), e.g. `risk={record.get('risk_score')} risk_evidence={(risk_state.get('risk_evidence') or {}).get('state', 'unrecorded')}`,
and change `_build_reflection` (`:611`) to `risk_awareness_state=...` instead of printing
`risk_score` under the `risk_awareness` label.

**R5 (documentation only).** The context line at `:300` could read
`decision_quality_index (process-quality composite, 0-1, not a probability)`. It prevents an LLM from
treating the number as a calibrated confidence, which was Task 03's explicit caution.

Nothing above requires renaming or removing a field, so the compatibility surface stays additive.

## 6. Historical migration considerations

- **Stored scores are not comparable across the Task 03 upgrade for incomplete-evidence records.**
  Complete-evidence records are unchanged, so rankings inside a fully measured cohort are stable. An
  episode with missing/partial risk data now sits up to 0.14 lower.
- Three options, in order of safety:
  1. **Accept a mixed series and never average across versions.** Requires R3's stamp and a reader
     filter. No data rewrite, no invented evidence. Recommended.
  2. **Treat pre-upgrade `coherence_score` values as legacy** and exclude them from governance
     thresholds (e.g. skip the constitutional check when the payload has no `dqi_policy`), which
     avoids C1 for old records but keeps the series mixed.
  3. **Recompute stored DQI** from historical payloads. Not recommended: pre-Task-02 payloads have no
     `risk_evidence`, so the input needed to apply the honest policy is absent; recomputing would
     fabricate evidence, and the live Qdrant collection was unavailable for verification.
- No migration of this kind can be validated in this environment (Qdrant `collection not available`,
  swallowed to `log.debug`). The r11 release candidate predates all of Tasks 01–03 and was not read,
  started or compared.

## 7. Tests and exact results

| Run (in `Niblit/`) | Result |
|---|---|
| probe 1 (consumer arithmetic, persistence payload, legacy branch, mixed snapshot, history shape) | completed, exit 0 — `.pytest-task04-audit/probe.log` |
| probe 2 (DQI → `coherence_score` → constitutional gate → recall) | completed, exit 0 — `.pytest-task04-audit/probe2.log` |
| `python -m pytest tests/test_adaptive_market_cognition.py tests/test_adaptive_market_cognition_risk.py tests/test_adaptive_market_cognition_quality.py test_unified_runtime_architecture.py test_hypothesis_engine.py test_adaptive_retrieval_cognition.py test_desktop_runtime_shell_market_intelligence.py test_governed_qdrant_memory.py -q --basetemp=.pytest-task04-audit/tmp` | **68 passed, exit 0** |

Key probe values worth keeping:

```
hypothesis: 0.5377 -> ("unchanged", 0.0); 0.3977 -> signal 0.45, ("unchanged", 0.0)
memory_retrieval_score(base 0.6): coherence 0.5377 -> 0.582655 ; 0.3977 -> 0.561655
vector govern_score(0.6):          0.350655 -> 0.329655
persisted payload keys: advisor_lineage, coherence_score, market_context,
                        reflection_summary, replay_metadata, summary
coherence_score == dqi: 0.3977 0.3977   metaevaluation persisted: False
_risk_awareness_credit({risk_score:0.0, risk_state:{}}) -> (0.14, 'unrecorded', 1.0)
_aggregate_risk(legacy item) -> risk_evidence_state 'unknown'
history: missing {risk_awareness 0.0, state 'missing', measured False, coverage 0.0}
         complete {risk_awareness 0.14, state 'complete', measured True, coverage 1.0}
json.dumps(status(), allow_nan=False) -> 5567 chars, OK
metaevaluation(missing) -> prediction_usefulness None / 'unmeasured'
```

Honest limits:

- **Nothing was executed against the live runtime.** No r11/r12 engine start, no broker, no credentials,
  no deployment. There is no claim that the demo behaves differently.
- **No live Qdrant round trip**, so C1 is demonstrated through `normalize_memory_payload` +
  `governed_recall_allowed` with the exact payload `_persist_experience` builds, not through a real
  collection insert/query.
- **The full suite was not run**; 68 focused tests is the whole verification surface for this audit.
- The `poetry`/CLI command output (`market intelligence dqi`) was checked for JSON serialisability by
  probe, not by running the interactive shell.
- C1 severity assumes a market episode can genuinely reach DQI < 0.3; the probe constructs such an
  episode (`eval=0.15`, `conf=0.15`, no risk inputs) rather than observing one in recorded production
  data. `diagnostics/runtime-chain-fixed2-20261028/unified.json` shows old-code DQI values around
  0.4556–0.4736, i.e. above the boundary, so this is a plausible-but-not-observed-in-capture case.

## 8. Handoff for ChatGPT / Desktop Commander

1. Decide R1 before publishing r12: publishing the corrected DQI as `coherence_score` can withhold
   low-quality market memories from governed recall via `law_1`. The floor `max(0.3, dqi)` plus an
   explicit `dqi_score` payload key is the smallest change that preserves recall while keeping the
   honest DQI.
2. Adopt or reject R2 (boolean meaning) — it is one line and purely semantic.
3. Decide the `dqi_policy` stamp (R3) as part of the r12 memory projection, since it changes the
   persisted schema. The Task 03 code change itself is complete; this is the only open scoring-version
   decision.
4. If any external dashboard or API reads `coherence_score`, `risk_awareness` or
   `prediction_usefulness`, re-check those readers against S1–S3 — they are not in this repository.
5. Still open from earlier tasks and untouched here: `_persist_experience` summary `risk=0.0`,
   `_build_reflection` mislabel, `_derived_confidence` giving unknown risk no penalty.
6. Do not infer r11 impact from this audit. The running demo binary predates Tasks 01–03 and was not
   rebuilt, restarted or inspected.

## 9. Safety statement

No production file was edited, no test was added or modified, no order, broker call or credential
access occurred, no service was started/stopped/restarted, no reset/clean/stash/checkout, no staging,
commit, push, build or deployment. Every pre-existing worktree change was preserved. The only new
files are this document, `docs/FREEBUFF_TASK_04_STATUS.md` and the ignored probe artefacts under
`.pytest-task04-audit/`.
