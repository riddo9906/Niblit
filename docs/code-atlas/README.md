# Source atlas

Run `niblit-env/Scripts/python.exe tools/build_code_atlas.py` from Niblit to rebuild.
The scanner reads source without importing or executing project modules. It records
file hashes, line counts, Python definitions/docstring summaries and review signals.
JavaScript/TypeScript/Rust files are listed but do not receive Python AST analysis.

- [Core](Niblit.md)
- [Cloud](Niblit-cloud-server.md)
- [UI](niblit-ui.md)
- [Lean](niblit-lean-algos.md)
- [Steward](niblit-steward.md)
- [Pip and Signal Desk](trade-signal-desk.md)
- [VS Code gateway](github-copilot-llm-gateway.md)
- [Company website](niblit-website.md)
- [Machine-readable index](index.json) and [counts](summary.json)

Generated/runtime/model/vendor directories are excluded. The `dist` directories
of the two buildless web projects are included because they contain their source.
Tests and legacy source are included. Freqtrade upstream is excluded from this
first-party atlas; its integration/configuration must be audited separately without
exporting account credentials. Symlink files are skipped.

Review signals are leads, not confirmed bugs. Abstract methods, exception classes,
intentional compatibility no-ops and property getter/setter pairs can be valid.
One historical Cloud verification script has a syntax signal; that does not prove
the running service has a syntax failure. A missing docstring means explanation
work remains, not that the function is broken.
