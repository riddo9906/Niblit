# Original command restoration — 25 October 2026

The desktop now discovers original handlers from the live canonical registry and
positive command guards in `niblit_core.py`, `niblit_router.py`, and
`niblit_brain.py`, plus the CLI vocabulary in `main.py`. Brain's deprecated
adapter remains a fallback for verified legacy handlers. The CLI and desktop
share the same `main.py` unified-status implementation.

The defect was that only assistant-safe tools could execute from the tab. Other
original commands were classified in a catalogue but could only be copied;
router prefixes had no callable handler in the registry. A separate operator
endpoint now invokes the actual original handler with its original text
arguments. Exact selections are not stolen by broader command prefixes, unknown
commands are rejected without chat fallback, and original spelling variants
resolve to the canonical command. Permission checks apply to the complete
invocation, including mutating subcommands of read-only families.

The UI combines operator and assistant commands, shows the correct exposure,
provides argument forms, confirmation and real results, and lets catalogue
entries prepare their actual action. Unbound entries have no dead action button.
Aliases come from backend metadata rather than individual words in a name.

`remember` also no longer swallows storage errors and then reports success.
Both Core and Router require a working canonical store and successful write.

Validation in the isolated packaged build:

- 413 original operator entries discovered; 260 executable, 137 permission-gated,
  16 unavailable in that runtime. Counts can vary with installed components.
- 13 packaged checks passed: original discovery, actual `threads` and
  `unified status`, a unique `remember` fact written to disk and returned in
  actual recall entries, `knowledge-stats` alias execution, unknown-command
  rejection, and a protected subcommand blocked before execution.
- 73 backend command/audit tests passed; one optional integration test skipped.
- 55 UI tests passed; TypeScript, Vite and the native Tauri build succeeded.
- Browser acceptance against packaged Core executed `remember` after confirmation
  and recalled the same key/value through the governed canonical memory path.

The assistant tool allowlist was not expanded. Interactive CLI lifecycle
commands and permission-gated operations remain visibly restricted.

Start the new build with `dist/testing-20261025-commands/niblit/Start-Niblit-Testing.cmd`
after closing the older desktop. `COMMAND_ACCEPTANCE_REPORT.json` is inside the
bundle. The previous `testing-20261025-final` bundle was preserved.
