# Niblit manual UI audit — 29 October 2026

Tested the running `latest-20261028-memory-refined` release. Native keyboard
testing confirmed Ctrl+K; broader interaction used the same built React interface
on local port 5173 against the actual Core on port 5000. Native screen capture
intermittently timed out, so browser results are not a claim that every native
window interaction passed. No production source changes were made in this audit.

No GPT-Astra requests, paid Steward reviews, orders, credential changes, or account
changes were performed. The two local models tested were llama3.2-1b and
qwen2.5-coder-3b. MT5 login details are intentionally excluded from this report.

| Area | Result | Observed evidence |
| --- | --- | --- |
| Core connection | Pass | Header connects; Settings → Test connection returns Connected to Niblit Core. |
| Native Ctrl+K | Pass | Palette opens, filters `status`, and Enter opens the command page. |
| Original status command | Pass | Execute returns success in approximately 3.66 seconds with real runtime status. |
| Autonomous learning status command | Partial | Command returns success in approximately 7.24 seconds, but reports Running false, Research Cycles 0 and Reasoning Cycles 0 while the memory panel is receiving new research records. The relationship between the reported engine and other research workers needs tracing. |
| Command catalogue usability | Issue | Duplicate labels for operator/governed aliases; original/surface totals differ across loading states. 452 items is not proof that 452 commands work. |
| Workspace observation | Pass | Commands → Inspect completes with purpose, action.started, action.result and finished events. |
| Existing-context assistant arithmetic | Fail | 17 × 23 returns 381 (expected 391). Repeating in assistant mode with Qwen selected still returns 381. |
| Clean local Model chat | Pass | Qwen2.5-coder-3b returns 391, with executed-model identity displayed. This isolates a useful contrast but does not prove whether earlier error was routing, history influence, or model reasoning. |
| Memory retrieval plumbing | Pass | Evidence search returns hybrid semantic/text results, source citations, unverified labels and 50% source confidence. Worker active; no pending queue at sample time. |
| Memory retrieval relevance | Fail | `machine learning` also returns unrelated Freqtrade outcomes. Retrieval needs domain/relevance filtering before use in decisions. |
| Learning-source quality | Issue | Native memory panel contains repeated definitions with different source keys and default confidence 0.5. Increasing counts alone does not show better knowledge. |
| File listing | Partial | Eventually loads. Long Loading files state initially looked stalled. Default capped listing omits README; client-only filtering then shows an empty table with no truncation warning. |
| Source file viewer | Pass | Opening __init__.py displays actual Python lines and file metadata. No code execution requested. |
| Inference page | Pass | Cloud, models, model runtime available; local model options and Astra option are listed. Paid option was not invoked. |
| Cognitive diagnostics | Partial | Essential readiness complete; 25 services, 231 modules, no failed modules reported. Startup also says 104/106 components ready: investigate the remaining two before claiming complete readiness. |
| Architecture | Pass for display | Shows Core, Cloud, trading, managed processes, wiring checks and persistent memory. This is diagnostic display, not an exercise of every component. |
| Execution page | Pass for display | Shows managed services, threads and recent events. State-changing actions not exercised. |
| Integrated Trading page | Pass for display | Embedded Market Desk loads live Binance futures candles, freshness, simulated balances/position and 31 closed outcomes. Clearly DRY-RUN. SampleStrategy is not validated by this test. No order was submitted. |
| MT5 | Installed and demo logged in | Desktop terminal confirmed installed and open on MetaQuotes-Demo. MetaTrader5 Python connector absent from Niblit's environment; no Niblit-to-MT5 bridge is implemented yet. |
| PDF attachment | Not retested | Earlier browser file-upload permission was declined. No alternate upload route was used to bypass it. Existing historical PDF error messages were not treated as a fresh test failure. |

## Priority follow-up

1. Trace assistant-mode requested versus executed model and context. Add deterministic
   arithmetic/financial calculations rather than trusting generated numbers.
2. Separate knowledge retrieval from execution-outcome retrieval and add a measured
   relevance gate; keep citations and unverified status.
3. Make file listing fast, show truncation, and offer navigation/search beyond the
   first batch. Do not interpret an empty client-filtered table as file absence.
4. Resolve duplicate command labels and test representative commands individually.
5. Identify the two non-ready startup components and reconcile generic Autonomous
   status with the actual ALE worker, which is visibly adding research records.
6. Build a demo-only MT5 adapter against the already logged-in desktop terminal;
   verify account mode and instrument identity before any future order testing.

This is a manual sample audit, not a claim of exhaustive coverage of every command,
manager, strategy, lifecycle recovery, or broker operation.
