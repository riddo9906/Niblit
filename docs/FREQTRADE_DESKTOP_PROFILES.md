# Packaged Freqtrade profiles

The bundled `freqtrade/niblit-freqtrade-worker.exe` supports historical replay
(default) and the real Freqtrade CLI (`--engine`). These are distinct modes.
The ordinary Testing launcher continues to use replay. To use real exchange
market data, prepare a separate profile and use the Freqtrade launcher below.

For a double-click workflow use `Start-Niblit-Freqtrade.cmd` (live market data,
simulated funds). It creates a stopped private dry-run profile if absent.
`Start-Niblit-Live.cmd` creates a stopped private live profile on its first run
and exits so you can configure it; subsequent runs validate it and open Niblit.
Both wrappers authorize the separate human engine start/stop controls. Neither
wrapper starts native trading automatically. The profile files are under
`%LOCALAPPDATA%\Niblit\trading`, outside the distributable application folder.

In PowerShell, from the new bundle folder, prepare a private profile outside
the bundle. This command creates configuration only and starts no services:

```powershell
& .\freqtrade\niblit-freqtrade-worker.exe --prepare-profile --mode dry-run --output "$env:LOCALAPPDATA\Niblit\trading\dry-run.json"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-Niblit-Freqtrade.ps1 -ConfigPath "$env:LOCALAPPDATA\Niblit\trading\dry-run.json"
```

For a real-money-capable configuration, prepare `--mode live` with a DIFFERENT
filename such as `live.json`. It has `dry_run=false`, empty exchange keys and
`initial_state=stopped`. Fill in exchange credentials privately and review
pairs, stake amount, balance allocation, maximum positions and strategy
settings before using it. Neither build verification nor profile preparation
starts real-money trading. Existing profiles are never overwritten.

Launch it with `Start-Niblit-Freqtrade.ps1 -ConfigPath <private-live-profile>`.
Add `-EnableTradingControls` to authorize the human start/stop commands for
this profile. This creates a separate profile-local permission file and does
not grant other Niblit mutation permissions. Omitting it keeps controls blocked.
The native Freqtrade engine starts STOPPED. Niblit attaches in observe mode;
its force-entry/exit permissions stay disabled. Actual native strategy trading
can be started deliberately by the human through Freqtrade's authenticated
API/client or the separate desktop operator command `freqtrade start dry-run`.
For a live engine the explicit command is
`freqtrade start live I_UNDERSTAND_LIVE_TRADING_RISK`, subject to the existing
operator trading permission. Use `freqtrade stop` to stop new native entries.
Read-only commands: `freqtrade status`, `freqtrade health`, `freqtrade balance`,
and `freqtrade trades`. These are separate from legacy `trading` brain commands
and are not exposed as assistant tools. No live start command is run in testing.
A live connection may query exchange balances and open orders;
testing must use dry-run, without real keys. Do not share the profile or log
its passwords/keys. Profile API credentials are generated locally.

Freqtrade API uses 127.0.0.1:18080; Niblit trading API uses 127.0.0.1:8100.
The launcher's readiness checks require the exact stopped profile and an
authenticated healthy adapter; it refuses occupied ports rather than
replacing another app. Closing the Core stops the two child services owned
by this launcher. Persistent state remains alongside the private profile.

After moving the bundle, update `strategy_path` in the private profile to
the moved bundle's `freqtrade/strategies` directory. The full path manager is
not implemented by these launchers. Missing cognitive envelopes retain the
existing strategy behavior: technical entries can be allowed. This is not
a certification of strategy profitability or a complete live-trading audit.
