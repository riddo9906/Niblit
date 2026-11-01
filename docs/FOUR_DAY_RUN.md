# Four-day operating handoff — 31 October 2026

Launcher reliability update: `Start-Client-Portal.cmd` now checks Docker first
and can start either the existing per-user or all-users Docker Desktop install.
It waits at most 45 seconds plus a bounded readiness probe, makes no installation
or volume changes, and refuses to continue if Docker stays unavailable. Starting
Docker can resume existing restart-enabled containers under their existing profiles.
Use `Check-Niblit-Local.cmd` for the read-only native dependency check. This tests
the bounded source profile's dependencies, not every frozen Core subsystem.
Eight focused launcher/readiness tests pass.

This is the verified local configuration, not a new packaged desktop release.
No strategy code, funded-trading permission or risk budget was changed today.

## What is running

- Market Desk: http://127.0.0.1:8767/ — EURUSD `auto` observation only.
  The current-moment comparer can collect and later score observations. This
  MT5 session does not place orders. Start an explicitly bounded demo session
  in the desk if wanted; no four-day unlimited MT5 executor was enabled.
- Freqtrade: existing `NiblitLabManager`, confirmed `dry_run=true`, resumed
  `running`, maximum three open trades. Three existing simulated positions were
  present. It can collect simulated outcomes under its existing strategy/risk
  rules. No new micro-trading strategy was activated.
- Local Qwen model: existing authenticated service on 8766, one idle slot at
  readiness check. Memory gateway on 8772 and task authority idle.
- Docker portal on 8769 returns HTTP 200 health; existing Qdrant container is up.
  Portal SQLite backup created in its existing backup volume:
  `portal-20261031T135113264158Z.sqlite3`.

Keep Windows awake, Docker Desktop running and internet available. This is not a
cloud uptime guarantee: a restart can stop observation and a market closure can
produce no new ticks. No trade or profit is guaranteed. Learning observations
remain unverified; saved data does not train model weights automatically.
Paid background inference stays off. No recurring local-model study was started.

## Stop or recover

Use the Market Desk stop control to stop its observation/demo session. In FreqUI,
stop entries if no new simulated entries are wanted; closing positions alone
does not disable the strategy's next entry. Review remaining positions separately.
Do not delete Docker volumes or old release data during this run.

After a PC restart, start Docker Desktop, use `Start-Trading-Desk.cmd` and
`Start-Client-Portal.cmd`, then verify the displayed backend and dry-run state.
`scripts/resume-market-observation.py` only resumes observation if no market
session is active. `scripts/check-native-runtime.py` checks dependencies without
generating, trading or changing `.env`. Neither proves full Core boot.

## Vercel remains a separate incomplete deployment

The company website is ready at https://enginehead-company.vercel.app/.
`enginehsd.site` and `www.enginehsd.site` are now attached to enginehead-company;
www redirects to the apex. Namecheap DNS remains parked/misconfigured, and the
owner has deferred further domain work. See DOMAIN_CONNECTION_STATUS.md.

The client portal's latest production deployment is ERROR:
`FASTAPI_ENTRYPOINT_NOT_FOUND` at commit 58c009a. Its source also requires a
persistent backend and SQLite volume; adding an entry point alone would not
make account/session storage or local inference work on Vercel. No working
public client login, cloud database migration or public desktop tunnel is claimed.
Finish durable backend/database and inference connectivity before enabling a
public signup flow. The user's local working portal has not been replaced.

Fifteen focused native-readiness/evidence/admission/comparer checks passed.
No rebuilt executable or APK was produced.
