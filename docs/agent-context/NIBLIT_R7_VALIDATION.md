# Niblit r7 validation — 6 November 2026

| Area | Evidence |
|---|---|
| Implemented | MT5 reconciliation tracks the stable position identifier and the current order ticket separately. It quarantines mixed opening attribution and reconciles a protective exit even when its magic number differs from the entry. |
| MT5 | Fresh 200-candle EURUSD M5 read-only probe passed. The approved demo scope activated at 19:51:27 SAST. MT5 confirmed one SELL entry, 0.01 lot at 1.11453, deal 58824170802, position 59227514240. No broker-confirmed closure by final readback. Any remaining position stays protected by its broker-side stop and target. |
| Strategies | All six rules were evaluated. Only breakout_v1 qualified for the entry. Session signal counts were {'sell': 5, 'buy': 1, 'wait': 8}. WAIT and stale observations produced no orders. |
| Risk | One entry and one concurrent position, 0.01 lot maximum, lower of USD 3 or 0.25% of equity stop-risk cap, 60-minute scope and existing exposure and drawdown gates. Entry estimated stop risk USD 2. Broker stop 1.11653 and target 1.11053 were confirmed independently. |
| Positions | Core recorded 14 owned-position marks and 1 reconciliation events. Final session state expired. The approved deadline was 20:51:27 SAST. Core authority ended at expiry. Read-only marks after expiry recorded = 1. |
| Memory | 35 session events have canonical memory receipts. Outbox states {'complete': 35}. Three local Qdrant points for the entry, reconciliation and expiry matched their SQLite payloads. Outcome learning from a realized exit remains unverified. Remote projection remains scoped to synthetic acceptance. |
| Inference | Two isolated local GGUF completions passed while the observation Core remained healthy. The r6.1 cancellation regression tests passed. Shutdown during active Core-owned inference was not exercised. |
| Freqtrade | Live read-only API and 200 fresh BTC futures candles verified. Engine stopped, three occupied slots, NiblitLabManager selected and fee unreported. No Freqtrade order authorization or delivery. |
| Packaging | 93 scoped tests, frozen preflight, both broker doubles and a 15.1-second isolated graceful service exit passed. All four sidecars match r6.1. Market Desk page and session asset returned HTTP 200. |
| Remaining | Windows popup delivery, live Core shutdown under active native inference, remote projection and Freqtrade execution remain unverified. Actual MT5 exit and realized P&L remain pending. |

Session d4f541b3804c417092c31b40be7c1a2a. Real-money execution remains disabled. The r7 package is `C:\Users\Operator\Documents\GitHub\Niblit\dist\releases\v202-20261106-r7\niblit`. Keep the full folder together. Background operation uses the existing `Start-Niblit-Autotrading.cmd -BackgroundCore` launcher.
