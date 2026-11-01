# Latest: connected desktop — 2026-10-28

Launch `Start-Niblit-Connected.cmd` from the Niblit checkout. Release: `dist/latest-20261028-connected/niblit`. See [connected desktop verification and limitations](CONNECTED_DESKTOP_20261028.md).

The earlier release below is preserved for reference.

## Windows inference fix — 2026-10-27

Release: dist/latest-20261026-inference-fix/niblit
Launch niblit.exe and keep the entire folder together.

Changes:
- Cloud subprocess output goes to a persistent log instead of an unread pipe that can block the server.
- Frontend streaming handles final frames, surfaces server errors and rejects empty responses.
- Frozen module discovery uses packaged modules.
- A new memory store is no longer incorrectly labelled partial recovery. Existing unreadable stores still warn.

Verification on this corrected build:
- Native desktop autostart, 80 model catalogue requests, three real streamed local Qwen replies, both backends healthy after every reply.
- Native UI accessibility showed CORE CONNECTED, Core healthy and Cloud ready.
- 77 backend regression tests; four frontend stream tests; TypeScript compilation passed.
- Manual chat entry was not completed: Windows capture/input helper repeatedly timed out. Endpoint streaming and native connectivity were verified separately.

Tests used disposable state and no real-money execution. The older build and its state are preserved. Prior full command/Freqtrade acceptance belongs to the preceding build; it was not rerun in full for this patch.

Cloud launcher diagnostics: %LOCALAPPDATA%\Niblit\logs\cloud-server.log (or NIBLIT_SERVICE_LOG_DIR).
