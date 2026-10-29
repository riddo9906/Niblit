# Niblit

**An evolving AI runtime and programmer workspace, maintained by Enginehead Software Development.**

Niblit connects local or optional hosted models, governed tools, persistent memory
and domain integrations. It is under active development. The broader AI operating
system vision is a roadmap; the project does not currently replace a desktop OS
or demonstrate reliable autonomous expertise on every device.

[Enginehead Software Development](https://enginehsd.site/) ·
[Current status](docs/CURRENT_STATUS.md) · [License](LICENSE) ·
[Licensing scope](docs/LICENSING.md) · [Contributing](CONTRIBUTING.md)

## What is available

- A Windows desktop toolbox connecting UI, Core and separate inference/runtime services.
- Governed command and workspace-file tools, conversation persistence and source-grounded workflows.
- A durable memory framework with a source ledger and optional Qdrant retrieval projection.
- MT5 demo and Freqtrade dry-run integrations for observed market data and reviewed simulated orders.
- Research, learning and code-generation components with ongoing integration and evaluation work.

These are development capabilities with different levels of verification. Current
local prototypes, public source and packaged releases may differ. Read the
[status matrix](docs/CURRENT_STATUS.md) before relying on a feature. Saving facts
or feedback does not by itself train a model or establish expertise.

## Architecture

The UI presents state; Core governs requests and tools; Cloud owns inference;
Lean and other trading adapters own their execution environments. The memory
ledger retains source evidence, while Qdrant supplies a searchable projection.
A restricted hosted client service is a separate development track from access
to the owner's private desktop.

Read [desktop runtime connections](docs/DESKTOP_RUNTIME_ARCHITECTURE.md) and
[memory responsibilities](docs/MEMORY_STRUCTURE.md). Historical design notes are
retained in [the previous README](docs/history/README_PRE_20261029.md); its older
feature and deployment claims are not current acceptance guarantees.

## Source setup

This repository is a development checkout, not a one-command verified installer.
Use a dedicated Python environment and inspect the selected dependency/profile
configuration before starting it. The declared project minimum is Python 3.10;
that declaration is not evidence of full-platform testing on every supported version.

```text
git clone https://github.com/riddo9906/Niblit.git
cd Niblit
python -m venv .venv
```

Activate that environment using your operating system's normal procedure. Review
`pyproject.toml`, `requirements.txt` and optional profiles for the work you intend
to run. Desktop packaging also requires the sibling UI, Cloud and Lean products,
model/runtime assets and build tools. Do not assume a standalone UI executable
contains the entire environment.

Keep environment secrets private. Hosted providers have separate costs. Use local
or scripted test responders for routine tests; enable paid/background work only
through an explicit reviewed configuration. No funded trading setup is enabled
by these instructions.

## Development and verification

Use focused tests for the changed subsystem and retain actual output, configuration
and source revision. Mocked tests, live inference, startup health and full UI
acceptance are different kinds of evidence. A complete release also needs clean
installation, restart persistence, recovery and dependency/license checks.

Do not describe the full project as production-ready based only on module counts
or a passing focused test batch. Strategy profitability, automatic self-improvement
and a working fresh-PC bootstrap download remain separate acceptance tasks.

## License and attribution

The source remains MIT-licensed under the existing [LICENSE](LICENSE), including
its original contributor notice. [NOTICE](NOTICE) and [licensing guidance](docs/LICENSING.md)
explain attribution and third-party boundaries. Models, dependencies and sibling
products retain their own terms. Company branding does not transfer contributor
copyright or change those terms.

For a focused development or integration enquiry, use the
[Enginehead website](https://enginehsd.site/) or the repository's issue tracker.
Never post API keys, private documents, account information or personal memory in
public issues.

