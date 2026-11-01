# Command repairs — 2026-10-26

The earlier Windows Freqtrade launcher work did not repair the whole Niblit
command system. This pass fixes shared desktop command infrastructure.

## Changes

- Recognize legacy `[safe_call error: ...]` and `[ERROR::...]` failures instead
  of reporting success.
- Preserve structured unavailable, rejected and authorization-required states.
- Treat a successful stopped-state report as a result, not a failed command.
- Recognize missing dependencies using both initialized/initialised spellings.
- Resolve typed command aliases with correct argument boundaries and preserve
  argument case. Prefer the longest matching command or alias.
- Preserve the backend error message in the UI command runner.
- Format unified status without importing the main boot entrypoint. Keep an
  already registered canonical unified-status handler authoritative.

## Verification

The backend command/runtime/catalogue suite passed (98 passed, one skipped).
Desktop command tests passed (26 tests), and TypeScript checking, Vite and Tauri
production builds passed. The trading suite passed (177 passed, one skipped),
as did three SLSA lifecycle tests.

Tests exercise dispatch, aliases, arguments, result/error handling, original
handlers, availability, authorization, API envelopes and catalogue consistency.
They do not execute every mutating command or establish that every optional
service, account, plugin, model and provider is available.

## Delivery limits and remaining work

The updated EXE is now rebuilt in `dist/latest-20261026/niblit/`. Its 39 packaged
acceptance checks passed, including operator commands, local inference, file
handling and memory recovery after restart. Ten native Freqtrade checks passed
using live Binance prices and simulated funds. The broader suites passed:
98 command tests (one skipped), 177 trading tests (one skipped), 26 command UI
tests, and three SLSA lifecycle tests. SLSA's constructor and missing start/stop
lifecycle mismatches discovered in packaged boot were repaired and repackaged.

The native Freqtrade engine and separate `freqtrade` operator commands are
included. Legacy `trading start/stop/status` still controls TradingBrain, not
the Freqtrade engine. Use `Start-Niblit-Freqtrade.cmd` for live-data simulation,
or `Start-Niblit-Live.cmd` to prepare/configure a stopped real-money profile.
No real-money trading was started during this work.

The runtime catalogue exposes 414 operator entries; only selected entries were
executed in packaged acceptance, alongside the wider automated suites. This
does not certify every optional integration or every command's domain behavior.
The Qdrant service was intentionally unavailable during isolated acceptance;
local memory persistence was verified. See the release verification summary
and `docs/FREQTRADE_DESKTOP_PROFILES.md` for scope and launch instructions.
