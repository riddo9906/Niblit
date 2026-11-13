# Niblit r8 verification — 6 November 2026

| Area | Result |
|---|---|
| Implemented | Core can propose a fresh MT5 demo close-only scope for one canonical owned entry whose original session ended. The scope binds the broker position identifier and rejects entries. It allows at most one close attempt under the existing strategy and risk exit rules, with a fresh ownership check immediately before delivery. Exit reason, fill prices, costs and one deduplicated outcome are retained for governed learning. Market Desk exposes the close-only review. |
| Activated | The verified r8 background Core is running both MT5 EURUSD M5 and Freqtrade BTC futures observation. Each assessed all six strategies. Startup granted zero execution sessions. The task-owned r7 observer exited normally before the switch, and r8 found the same protected position. |
| Broker-confirmed | The original r7 demo sell remains open at the verified readback. Position 59227514240, 0.01 lot at 1.11453, stop 1.11653 and target 1.11053. No closing deal or realized P&L. The non-submitting check to close exactly that ticket passed. No r8 broker orders. |
| Simulated | Trading, learning and shutdown suite passed 92 tests. A final overlapping trading and consensus run passed 71 tests, including close-only exit, approval gating, no duplicate exit, exact ownership, realized net and a single canonical outcome. Both frozen broker-double pipelines and the packaged desk notification doubles passed. |
| Consensus | An eligible strategy can qualify when other rules return WAIT. Conflicting eligible directions, all abstentions, or an incomplete assessment prevent an entry. The policy has no numerical confidence threshold. This is why r7's one breakout_v1 SELL with five WAIT votes qualified. |
| Runtime and memory | Frozen preflight and a 14.2-second isolated clean shutdown passed. No forced termination or owned descendants. The attached Cloud stayed reachable. Three live position-watch points matched local Qdrant and SQLite exactly. Remote projection remains scoped to synthetic acceptance. Two isolated local GGUF completions passed with the observer healthy. |
| Blocked | Actual close requires fresh approval. Freqtrade has a stopped engine, three occupied slots, the older strategy and no reported fee. Its read-only API returned fresh data. Windows popup delivery and Core shutdown with active Core-owned inference remain unverified. |
| Real money | Default deny remains in force. No live-account submission path was enabled or validated. |

Release folder `C:\Users\Riyaad\Documents\GitHub\Niblit\dist\releases\v202-20261106-r8-verified\niblit`. The four r7 sidecars are byte-identical.

Pending Core proposal `deb6d6753df14b9d98d7b5272da473cd` binds MT5 demo account `b95a8bc3fd731d67`, EURUSD M5, position `59227514240`, up to 0.01 lot, zero entries and one conditional close attempt in a 60-minute window. It is unactivated. The normal proposal review window is five minutes and execution duration starts only after activation. If the pending record expires, recheck ownership and regenerate the identical scope before activation.
