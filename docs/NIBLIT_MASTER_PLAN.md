# Niblit master delivery plan

Baseline: 29 October 2026. Local Core HEAD `e1485db923d9f92a12ea3398ec4a31b0722bfade`;
145 modified/untracked status entries were observed before this audit's final docs.
Local source, public GitHub and the running frozen bundle must be tracked separately.
No mass reset, deletion, formatter pass or unreviewed all-code rewrite is planned.

## Completion language

- **Verified:** a specific observed workflow/test has evidence, with its limits.
- **Partial:** code exists and some paths work; a required integration/acceptance is missing.
- **Historical:** an earlier conversation reports success; current source/build needs recheck.
- **Planned:** requested but not implemented/proven.
- **Excluded:** the requested implementation will not be supplied; an alternative is recorded.

Passing a mocked test does not prove live inference. A healthy port does not prove
an entire UI path. A demo fill does not prove profitable or funded trading.

## Milestones in dependency order

| Phase | Deliverable | Acceptance before advancing |
|---|---|---|
| 1. Establish the map | Request ledger, source atlas, component owners and data-flow guide | Every request links to evidence, a gap or an explicit scope decision; old attachments marked unavailable |
| 2. Runtime and portability | Path Manager, validated configuration precedence, single worker ownership and truthful status | Same startup/context after restart and relocation; no hidden alternate Core; existing memory preserved |
| 3. Memory and cognition | Domain filters, citations, ingestion/retrieval/review across legacy adapters | Relevant recall, no cross-domain leakage, PDF question/follow-up with pages, offline/retry/deletion tests |
| 4. Domain learning | Separate finance, software and general-learning contracts | Bounded local loop with objectives, evidence, held-out evaluations and restart recovery; no paid background work |
| 5. Trading feedback | Adapter-identified observation→decision→review→execution→outcome journal | Demo entry AND close receipts for MT5/Freqtrade, reconciled uncertain orders, no hindsight, fees and held-out performance evaluation |
| 6. Product delivery | Clean-source release manifest, bootstrap executable and documentation | Clean Windows target installs from website download, verifies signatures/hashes and starts all required services without private files |
| 7. Hosted clients | Shared/private workspaces, approved sign-up, roles, quotas, cloud hosting | HTTPS, real local inference, restart/backup/restore, adversarial tenant-isolation tests; then pricing/billing |
| 8. Vision and OS tools | Bounded object/activity events and governed OS adapters | Permission-scoped evidence, retention, false-alert tests and recovery; unknown faces remain unidentified |

The portal's isolated initial implementation can be developed alongside earlier
phases. It must not be sold as full desktop access until the underlying integration
and isolation have been demonstrated.

## Current delivery matrix

| User goal | Status | Evidence / remaining work |
|---|---|---|
| Manual signals app | Partial | Signal Desk exists; multi-market feed coverage and strategy validity need acceptance |
| Live market API | Partial | Crypto/Freqtrade and MT5 observations exist; unified freshness/venue contracts remain |
| Programmer toolbox UI | Partial | Working desktop chat, commands and files; diagnostic UX and full tab acceptance remain |
| Boot Core/Cloud/Lean together | Verified in tested release | Desktop boot and responses reported/observed; portable new-machine build not proven |
| Original Ctrl+K commands | Partial | Palette works; registry count/duplicate labels and every intended handler not fully reconciled |
| PDF attachments reach AI | Partial | Parser and older governed file flow tested; current native attachment-to-model acceptance incomplete; OCR absent |
| Local file understanding and follow-ups | Historical | Earlier actual Qwen route answered source question and follow-up; current release needs recheck |
| Qdrant persistent framework | Partial | Durable ledger, projection, embeddings, memory desk; remaining legacy adapters/relevance/consolidation gaps |
| Clear readable memory UI | Verified in observed views | Actual stored records visible; confidence and repeated facts still need quality controls |
| MT5 live demo connection | Verified in tested profile | Terminal observed, quote-advancement checks, actual 0.01 demo fill receipt |
| MT5 close control | Partial | Backend/UI implemented; final actual close acceptance outstanding |
| Freqtrade container and manual controls | Partial | Dry-run API connected, min-stake rejection reconciled; final entry/close UI acceptance outstanding |
| Trading brain learns from outcomes | Partial | Scoped MarketJournal adapter and imported outcomes exist; full causal loop and MT5 identity absent |
| Finance expertise | Planned / unproven | No claim of expertise or profitable strategy based on memory count |
| Autonomy | Partial; lifecycle source repaired | Worker ownership, truthful stop/status and timeout overlap guards pass 16 focused tests; frozen release rollout and full evaluated learning loop remain |
| Domain-specific growth | Planned | Finance/software/general learning need distinct objective/evaluation contracts |
| Manager and Path Manager upgrade | Planned | Existing managers are not yet one portable capability/health/evidence contract |
| Pip/Pulse companion | Partial | Local implementation exists; actual autonomous growth and seamless mutual agent interaction unproven |
| Steward agent and observation tool | Partial | Runner/tests/tool surface exist; executor/environment and full inside-Niblit workflow need recheck |
| Always-on desktop eyes for Codex | Not delivered | On-demand supported UI observation exists; no continuous access or persistent Codex presence |
| Ruflo layer in real work | Unverified | Existing integration needs discovery and one bounded actual task; do not infer availability from a stub |
| OpenAI adapter / exact model | Tested earlier, budget constrained | Keep configured gpt-6-astra; no paid inference performed in this audit |
| VS Code local model bridge | Historical | Earlier native response/stream evidence and 306-test report; current acceptance not repeated |
| Executable fresh-PC installer | Planned | No real clean-install-tested download exists; source provenance and dependencies must be fixed first |
| Enginehead company website | Verified publication | Version 2 published; Niblit presented as a product, not the company name |
| Website custom domain | Pending confirmation | Sites records created; user can open domain, but authoritative domain/certificate status needs a follow-up check |
| Shared hosted Niblit service | Partial | Local durable shared session tested; cloud host and actual model round trip not deployed |
| Sign-up and roles | Verified backend / UI form | Pending sign-up, admin approval, viewer default, revocation; no verified email/password recovery yet |
| Private Personal/Pro/Team | Verified backend | Isolated history/context and tier checks tested; manually assigned pilot limits, billing absent |
| Cloud container package | Prepared / unverified | Narrow source-only Docker profile exists; image build, inference networking and host deployment not done |
| CCTV object/pattern event memory | Planned | Depends on later camera setup and validation; no camera service implemented here |
| Match unknown faces to social profiles | Excluded | Use intrusion/activity evidence and explicitly enrolled consenting identities instead |
| Sustainable business / revenue | Goal, not demonstrated | Validate one paid-value workflow and measured costs; automation alone does not guarantee income |
| Explain all code / reconcile all requests | In progress | Atlas + guide + 143-request inventory; individual evidence review and all-module explanation unfinished |

## Next implementation batch

1. Package and verify the worker ownership/status source repair; coordinate the remaining independent producers without enabling paid loops.
2. Add a domain contract and truthful progress/evaluation reporting to that actual worker.
3. Complete trading adapter identity and outcome linkage; exercise demo closes manually.
4. Add Path Manager around real launcher/memory/model paths; preserve current defaults.
5. Rebuild one dated release with a source/dependency manifest, then test clean install.

Each batch must leave a working increment, explain what/how/why in its changed
modules, record exact tests and update the matrix. Do not stop at generating more
architecture documents or create replacement services for already-working paths.

## Findings that require care

- Legacy LocalBrain `BrainTrainer.record_exchange` and `ingest_research` are
  intentionally deprecated no-ops. Trace actual callers before deleting/replacing.
- `TradingBrain` now uses a journal cutoff and scope, but hardcodes Binance venue.
- The older root `render.yaml` enables autonomous loops and broad providers; the
  restricted client container must not inherit it.
- Source AST flags include valid interfaces/property setters. Review them before
  counting stubs or claiming a defective runtime.
- The atlas measures source/docstring coverage, not intelligence or production readiness.
