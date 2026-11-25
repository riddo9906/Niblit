# Niblit Foundational Architecture and Strict Engineering Doctrine

**Authority:** Foundational design directive for all Niblit development  
**Established:** 2026-11-25  
**Status:** Mandatory design standard; not a claim of completed implementation  
**Applies to:** Every Niblit repository, subsystem, runtime, model, integration, operating-system component, tool, deployment and future development agent.

## 1. Foundational intent

Niblit is intended to become an independently engineered, AI-native computational system. It is not defined as a chatbot assembled from APIs, a collection of loosely coupled modules, or an AI assistant attached to an otherwise conventional operating system.

Every component must be designed and implemented according to the real engineering discipline of the capability it is intended to provide. The project must use the relevant official documentation, specifications, standards, protocols, research literature, reference implementations and established engineering methods.

The objective is the actual logical integration and operation of each subsystem—not a superficial demonstration that imitates its output.

This directive defines the target architecture and mandatory engineering standard. It does not certify that any future-state capability already exists. Every status claim must be supported by current source inspection and reproducible evidence.

## 2. Mandatory engineering doctrine

Every substantial feature or subsystem must follow this lifecycle:

1. **Discipline research:** Identify the actual field of engineering, authoritative documentation, specifications, standards, protocols, research and supported platform methods.
2. **Requirements and specification:** Define purpose, boundaries, inputs, outputs, invariants, failure modes, security model, data contracts, dependencies, resource requirements and acceptance criteria.
3. **Architecture:** Design the real logical components, ownership boundaries, state transitions, interfaces, schemas and lifecycle. Record material decisions and trade-offs.
4. **Implementation:** Implement the specified behaviour using supported interfaces and methods. Do not replace missing engineering with labels, wrappers or simulated behaviour.
5. **Native integration:** Connect components through their actual contracts. Respect provider-specific semantics, versioning, lifecycle and operational requirements.
6. **Verification:** Test unit behaviour, contract compatibility, integration, failure handling, security, resource use, performance and correctness. Use real platform acceptance where required; distinguish fixtures and mocks from live evidence.
7. **Documentation and reproducibility:** Record versions, configuration assumptions, commands, evidence, limitations, rollback/recovery and exact acceptance status.
8. **Controlled evolution:** Change the architecture through reviewed, measured increments with regression coverage and preserved data/state.

A component is not complete because a file, class, endpoint, UI control or adapter exists. Completion means its intended behaviour is implemented, correctly integrated and verified against explicit acceptance criteria.

## 3. Prohibited quality shortcuts

The following are not acceptable as production engineering:

- Monkey-patching a dependency or runtime to conceal an incorrect integration or bypass its documented contract.
- Workarounds that imitate a platform feature instead of implementing the platform's actual supported method.
- Compatibility shims that silently mask version, schema, protocol or lifecycle incompatibilities.
- Fake, stubbed, hard-coded or simulated results represented as live or complete functionality.
- Duplicated authorities, parallel ledgers, shadow workers or competing sources of truth introduced to avoid integrating with the canonical subsystem.
- Skipping provider configuration, indexing, validation, authentication, lifecycle or error semantics because a basic request happens to succeed.
- Disabling safety, governance, verification or failure handling to make a demonstration pass.
- Treating a successful build, import, health endpoint or isolated unit test as proof of end-to-end capability.

### Temporary exception policy

A temporary workaround may be used only when a documented external blocker makes the correct integration temporarily impossible and continuing investigation has value. It must:
- be explicitly labelled **temporary / non-production**;
- be isolated behind a narrow interface and disabled or fail closed by default where safety requires;
- state why the correct implementation is blocked and cite the relevant platform behaviour;
- identify its owner, risks, affected environments and measurable removal condition;
- have tests that prevent it from being mistaken for the final implementation; and
- never be reported as completion of the intended integration.

Convenience, speed or avoiding proper research is not a valid exception. The preferred outcome is to stop at a clearly documented blocker rather than institutionalise a lower-quality workaround.

## 4. Niblit's central structured information architecture

Niblit's structured keyword and information architecture is a cross-system foundation, not merely a Qdrant ingestion helper or a bag of extracted strings.

It must provide a coherent internal representation for information as it is interpreted, transformed, exchanged, stored, retrieved and evaluated throughout Niblit. Depending on the domain, that representation must support typed symbols and tokens, normalized forms, concepts, entities, attributes, relationships, context, intent, quantities, units, claims, evidence, source spans, temporal information, provenance, confidence and uncertainty.

The architecture must preserve original source material and traceability while distinguishing raw observations, parsed candidates, model interpretations, hypotheses, verified facts and decisions. Heuristic keyword matches must not be promoted into semantic facts without validation.

Niblit's internal representation is not an excuse to ignore external contracts. Each integration must have an explicit adapter that translates between Niblit's typed internal contracts and the provider's documented schemas and semantics. The adapter must validate both directions and preserve information that the provider cannot represent.

This principle applies to native cognition, language processing, memory, model inputs and outputs, tools, market data, trading, operating-system services, APIs and future integrations.

## 5. Provider-specific integration engineering

A service connection is not a completed integration. Each provider must be implemented according to its current official documentation, supported API, version and operational model.

For each provider, document:
- official API / protocol and supported versions;
- authentication and secret-handling boundaries;
- request and response schemas;
- data preparation, normalization and validation;
- resource creation and lifecycle;
- indexing, caching and consistency behaviour;
- error, retry, timeout, rate-limit and partial-failure semantics;
- security and access-control model;
- observability, acceptance tests and recovery procedure.

### Qdrant example

Qdrant Cloud is a vector-search and storage/retrieval component, not Niblit's complete memory or truth authority. A real integration must implement the appropriate documented collection and vector configuration, embedding model and dimensions, dense/sparse representation where selected, payload schema, payload indexes, point identity and update semantics, filtering, query construction, retrieval and operational handling.

Embedding models must be selected and configured intentionally. Vector dimensions, distance metric, model revision and preprocessing must agree. Payload metadata must preserve the fields needed for filtering, provenance, access control and interpretation. Retrieval quality must be evaluated with representative queries and known expected results.

Niblit's canonical memory authority remains responsible for deciding what is admitted, trusted, retained and acted upon. Qdrant's role and any projection/rebuild relationship must be explicit. A reachable cluster or successful upsert alone is not retrieval acceptance.

The same standard applies to every provider, database, broker, framework, model runtime and infrastructure service.

## 6. Native LLM and cognition engineering

The native Niblit language/intelligence objective must be distinguished from calling an external model. The engineering roadmap must explicitly identify which elements are Niblit-native, which are delegated, which are research prototypes and which have passed acceptance.

Relevant disciplines include tokenizer and vocabulary design, corpus acquisition and governance, data cleaning and deduplication, architecture and parameterization, objective functions, training and optimization, pretraining, fine-tuning, inference, decoding, context management, evaluation, safety, deployment and reproducibility.

Niblit's cognition architecture must define the real processing and control flow for perception/intake, structured parsing, evidence assessment, context formation, memory retrieval, reasoning, planning, evaluation, action proposal, observation and consolidation. Deterministic procedures, learned model behaviour and external model contributions must remain distinguishable.

Memory retrieval does not itself establish truth. Repetition does not establish factual confidence. Saving a memory does not train model weights. Model-generated hypotheses must retain their provenance and uncertainty until independently evaluated.

## 7. Local llama.cpp and GGUF engineering

The local inference platform must be built and configured for the actual host operating system and hardware. Follow llama.cpp's documented build system, backend support, GGUF format, quantization, inference and serving interfaces rather than assuming that a binary or model file proves compatibility.

Engineering includes platform/toolchain selection, CPU instruction support, GPU/Vulkan backend correctness, driver compatibility, memory and VRAM planning, model/context sizing, KV-cache policy, batching and concurrency, model lifecycle, API contracts, streaming, structured output, cancellation, observability and performance benchmarking.

The local GGUF team may provide specialist reasoning and delegated work. Niblit's native runtime must own orchestration, context contracts, result validation, provenance and governance. Model outputs remain proposals until accepted by the responsible Niblit subsystem.

The design target is broad local capability: models can request authorized access to the PC's filesystem, applications, processes, services, network and hardware through proper local interfaces. The owner retains ultimate control over permissions, credentials, approvals and consequential actions. Local execution is not equivalent to unrestricted authority.

## 8. Memory, learning and knowledge

Memory must be engineered as a governed information lifecycle, not equated with a vector database. Define canonical records, namespaces, identity, provenance, access control, admission, retention, deduplication, updates, deletion, projection, retrieval, consolidation, backup and recovery.

Any vector store or search index must have an explicit relationship to the canonical records and a tested rebuild/reconciliation path. Do not introduce competing memory authorities to bypass the existing canonical contract.

Learning must distinguish skill acquisition, feedback, retrieval, parameter updates and model training. Any training pipeline requires dataset lineage, consent/rights and data governance, train/validation/test separation, reproducibility, evaluation, rollback and explicit authorization. Ordinary memory updates must never be described as weight training.

## 9. Quantitative and AI trading engineering

Trading systems must be based on documented quantitative finance, algorithmic trading, market microstructure, statistical modelling and machine-learning disciplines—not arbitrary indicators or unsupported pattern claims.

Research and implementation must cover, where relevant, market structure, price action, trend and momentum, volatility, mean reversion, liquidity, order flow, microstructure, regime detection, feature engineering, statistical inference, strategy construction, portfolio/risk management, execution algorithms, broker constraints, fees, spread, slippage and market impact.

Backtesting must guard against look-ahead bias, survivorship bias, leakage, overfitting and unrealistic fills. Use chronological splits, walk-forward evaluation, out-of-sample testing, realistic costs, baselines, ablations and uncertainty analysis. Evaluate calibration and robustness across regimes and instruments.

Separate observation, research, simulation, paper/dry-run, demo and live execution. Risk controls and execution authority remain explicit and independently enforced. An analytical prediction is not an order authorization, and a profitable historical simulation is not proof of a live edge.

## 10. Niblit as an actual AI-native operating system

The ultimate objective is a real Niblit operating system, not only an AI desktop shell or a conventional OS with an assistant attached. The target includes bootloader integration, kernel, hardware abstraction, memory and process management, scheduling, interrupts, device drivers, storage, networking, security, system services, application/runtime interfaces and recovery.

The native intelligence is intended to become the primary intelligent system orchestrator and task manager: observing system state, understanding goals, planning workloads, coordinating services and authorized hardware operations, diagnosing failures and managing applications.

The AI does not literally replace motherboard firmware or the deterministic kernel scheduler. UEFI/firmware must initialize sufficient hardware for boot; a trusted boot chain loads the kernel and the minimum runtime needed to start intelligence. The kernel and drivers perform deterministic low-level operations and enforce memory, process, interrupt, device and safety boundaries. The AI orchestrates through documented firmware, kernel, driver and system-service interfaces.

Hardware communication must use actual platform mechanisms and specifications as applicable: UEFI, ACPI, CPU architecture interfaces, PCIe, supported controller buses, device protocols and driver frameworks. Never claim direct motherboard control where only an OS-level API or telemetry interface exists.

A minimal trusted boot, diagnostic and recovery environment must remain usable if the AI model, inference service, memory or network is unavailable. The owner must retain ultimate control.

A Linux-based bring-up environment may be used as a deliberate intermediate stage if it accelerates hardware and driver research. It must be labelled as an intermediate platform and must not silently replace the ultimate custom Niblit kernel/OS objective.

## 11. Cross-system contracts and ownership

Every subsystem must declare its authority and boundaries. Examples:
- Native Niblit owns internal knowledge interpretation, cognition coordination and memory admission policy.
- Provider adapters own translation to external service contracts, not the meaning or authority of Niblit's internal records.
- Qdrant provides configured vector storage and retrieval, not factual authority.
- llama.cpp provides local inference execution, not Niblit's overall identity, permissions or memory authority.
- GGUF specialists provide bounded model contributions, not unrestricted host authority.
- The OS kernel and drivers own deterministic resource and hardware control; AI orchestration proposes and coordinates within those interfaces.
- Trading analytics produce evidence and recommendations; separate risk and execution authorities control order lifecycle.

Contracts must specify schemas, versions, invariants, identity, error semantics, cancellation, timeouts, concurrency, resource budgets, audit events and compatibility. Cross-repository changes must be versioned and accepted end-to-end.

## 12. Evidence and status vocabulary

Every report must distinguish:
- **Implemented and verified:** actual intended path passed its acceptance criteria.
- **Implemented, verification incomplete:** code exists but required evidence is missing.
- **Partial:** only a bounded subset is working.
- **Prototype / experimental:** useful exploration, not production acceptance.
- **Planned:** not implemented.
- **Blocked:** a specific external or technical prerequisite prevents progress.
- **Requires reconstruction:** existing design violates the required discipline or contract.

Tests must label mocks, fixtures, simulations and real platform interactions. Build success is not runtime acceptance. API health is not end-to-end acceptance. A model response is not proof of correct reasoning. A database write is not proof of retrieval quality. A trading backtest is not proof of live profitability.

## 13. Development-agent obligations

Every human or AI development agent working on Niblit must:
1. Read and apply this directive before proposing or changing architecture.
2. Inspect the current source, contracts, documentation and worktree before editing.
3. Research the real discipline and authoritative platform documentation before implementing an integration.
4. Prefer correct logical integration over expedient compatibility patches.
5. Preserve existing work, data, security boundaries and subsystem ownership.
6. Stop and report a real blocker rather than silently weakening the design.
7. Provide exact changed paths, commands, test results, live evidence, limitations and remaining work.
8. Never promote an aspiration, prototype, mock or workaround into a verified capability claim.

This directive is a design constraint for future work, not permission to rewrite or discard existing code wholesale. Existing implementation must be audited incrementally, with evidence and preservation of unrelated work.

## 14. Foundational rule

**Build the real system according to the real engineering discipline of what it is intended to become. Follow the documented methods and interfaces precisely. Implement the actual logical integration. Do not trade correctness for convenience, and do not mistake a workaround for engineering completion.**
