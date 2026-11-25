# Mandatory architecture and engineering doctrine

Before proposing or changing Niblit architecture, source code, integrations, model infrastructure, trading systems or OS components, read and obey `docs/architecture/NIBLIT_ENGINEERING_DOCTRINE.md`. This is a strict project-wide design constraint. Research and follow the real engineering discipline, official documentation, specifications, standards and supported interfaces for the capability being built. Implement the actual logical integration and verify it with evidence. Do not substitute monkey patches, superficial workarounds, compatibility shims, stubs or simulations for correct engineering or represent them as complete. Temporary exceptions must be isolated, explicitly non-production, justified by a documented blocker, assigned a removal condition and fail-closed where required. Preserve existing work and report blockers honestly. The directive defines the intended architecture; it does not certify existing code as complete.

# Niblit product direction

Riyaad reaffirmed on 2026-10-28 that Niblit's UI must be a programmer's toolbox, with Niblit itself as an integrated tool that can learn, grow and perform useful work on the PC.

Riyaad also grants creative implementation freedom within Niblit's authorized scope. Make logical, evidence-based design choices without asking about routine details. Prefer adaptable contracts, observable outcomes, recovery paths and tested increments; do not promise that untested changes will succeed in every future environment.

- Centre developer workflows: project files, code, commands, tests, debugging, runtime management and source-grounded assistance.
- The trading tab must reflect actual timestamped market state and support interaction through the authoritative trading backend. Explicitly distinguish replay, paper, dry-run and live data/execution; never relabel historical replay as live market access.
- Use a hybrid, capability-driven market manager rather than hard-coding one broker as the complete architecture. Discover and register supported environments/adapters with identity, capabilities, health, freshness and outcome evidence. Apply the same extensible manager contract to Niblit's respective subsystems. Registration is not proof of authenticated connectivity or execution permission.
- Connect the UI to the same authoritative Core instance and its Cloud inference, Lean-algos and Freqtrade bridges. A visible UI or live process is not proof that requests work.
- Keep learning and growth inspectable: memory, knowledge, feedback, demonstrated abilities and actual outcomes. Do not present saved feedback as automatic model training or simulated status as live runtime health.
- Preserve the user's manual/observe/paper versus live-execution configuration. Boot and connectivity repairs must not enable financial execution.
- Verify UI-to-Core responses and Core-to-Cloud inference, including with live telemetry connected. Boot-only or isolated Cloud health tests do not cover the full user experience.

The parent workspace AGENTS.md records the user's standing preference for autonomous routine work. Existing uncommitted work in these repositories must be preserved.

## OpenAI testing budget

On 2026-10-28 Riyaad set OPENAI_MODEL to gpt-6-astra and plans an initial $10 credit top-up. Preserve that exact configured model. Keep paid background loops off, use local models for routine checks, and prove a small useful end-to-end task before expanding paid inference. Further paid tests are pending the user's confirmation that credits are available; mocked tests and read-only account/session inspection may continue. Never buy credits on the user's behalf.
