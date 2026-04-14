# Niblit LEAN Algorithms

A comprehensive collection of AI-powered trading algorithms for
[QuantConnect LEAN](https://www.lean.io/), built to integrate cleanly
with [Niblit](https://github.com/riddo9906/Niblit) — the autonomous
AI agent — without any naming collisions or circular dependencies.

## Repository Structure

```
niblit-lean-algos/
├── niblit_bridge/
│   ├── __init__.py
│   └── connector.py        ← Niblit ↔ LEAN signal bridge (file-based)
├── algorithms/
│   ├── 01_ema_triple_cross/main.py
│   ├── 02_macd_momentum/main.py
│   ├── 03_rsi_mean_reversion/main.py
│   ├── 04_bollinger_squeeze/main.py
│   ├── 05_supertrend_atr/main.py
│   ├── 06_pairs_cointegration/main.py
│   ├── 07_ml_random_forest/main.py
│   ├── 08_lstm_predictor/main.py
│   ├── 09_rl_dqn/main.py
│   ├── 10_rl_ppo/main.py
│   ├── 11_regime_hmm/main.py
│   ├── 12_multi_factor/main.py
│   ├── 13_kalman_pairs/main.py
│   ├── 14_crypto_funding_arb/main.py
│   ├── 15_volatility_targeting/main.py
│   ├── 16_dual_momentum/main.py
│   ├── 17_gradient_boosting/main.py
│   ├── 18_transformer_attention/main.py
│   ├── 19_sentiment_alpha/main.py
│   └── 20_niblit_ai_master/main.py
├── scripts/
│   └── deploy_all_to_qc.py ← batch deployment via Niblit's LeanDeployEngine
├── lean.json               ← LEAN workspace config
├── requirements.txt
└── README.md
```

## How Niblit Integration Works

**No Niblit Python modules are imported inside LEAN algorithms.** Instead,
a lightweight file-based signal bridge is used:

```
Niblit TradingBrain
   │  writes /tmp/niblit_lean_signal.json
   ▼
NiblitBridge.get_signal()   ← called from on_data() in each LEAN algo
   │  reads JSON → "BUY" | "SELL" | "HOLD"
   ▼
LEAN QCAlgorithm (position management)
```

The `modules/lean_algo_manager.py` module in Niblit orchestrates:
1. Pushing algorithm files to QC cloud via the REST API
2. Writing Niblit's trading brain signal to the signal file
3. Reading back live P&L and feeding it to Niblit's knowledge base

## Quick Start

### 1. Set credentials

```bash
export QC_USER_ID=<your_quantconnect_user_id>
export QC_API_CRED=<your_quantconnect_api_token>
```

### 2. Deploy all algorithms to QuantConnect Cloud

Inside the Niblit shell:
```
lean algo deploy-all
lean algo list
lean algo backtest <project_id>
lean algo live <project_id>
```

Or directly via Python:
```bash
cd niblit-lean-algos
python scripts/deploy_all_to_qc.py
```

### 3. Enable Niblit AI Master algorithm (live practice)

The `20_niblit_ai_master` algorithm reads Niblit's trading brain signals
in real-time. Start Niblit first, then start live practice:

```
trading start          ← start Niblit's trading brain
lean algo live <id>    ← start the master algorithm on paper brokerage
```

## Algorithms

| # | Algorithm | Style | Key Indicators | Live Ready |
|---|-----------|-------|----------------|------------|
| 01 | EMA Triple Crossover | Trend | EMA 9/21/50 | ✅ |
| 02 | MACD Momentum | Trend/Momentum | MACD, ATR | ✅ |
| 03 | RSI Mean Reversion | Mean Reversion | RSI, EMA | ✅ |
| 04 | Bollinger Squeeze | Breakout | BB, KeltnerCh | ✅ |
| 05 | Supertrend ATR | Trend | ATR Supertrend | ✅ |
| 06 | Pairs Cointegration | Stat Arb | Spread z-score | ✅ |
| 07 | ML Random Forest | AI/ML | Pure-Python RF | ✅ |
| 08 | LSTM Predictor | AI/ML | Rolling LSTM | ✅ |
| 09 | RL DQN Trader | AI/RL | Q-learning | ✅ |
| 10 | RL PPO Trader | AI/RL | Actor-Critic | ✅ |
| 11 | Regime HMM | AI/ML | HMM regimes | ✅ |
| 12 | Multi-Factor | Factor | MOM/QUA/VOL | ✅ |
| 13 | Kalman Pairs | Stat Arb | Kalman spread | ✅ |
| 14 | Crypto Funding Arb | Arb | Funding rate | ✅ |
| 15 | Volatility Targeting | Risk | ATR vol target | ✅ |
| 16 | Dual Momentum | Momentum | ABS+REL mom | ✅ |
| 17 | Gradient Boosting | AI/ML | Pure-Python GBM | ✅ |
| 18 | Transformer Attention | AI/ML | Attention weights | ✅ |
| 19 | Sentiment Alpha | NLP/AI | News sentiment | ✅ |
| 20 | **Niblit AI Master** | **AI Agent** | **All signals** | ✅ |

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `QC_USER_ID` | QuantConnect user ID | For deployment |
| `QC_API_CRED` | QuantConnect API token | For deployment |
| `NIBLIT_SIGNAL_FILE` | Path to Niblit signal JSON | For AI Master |
| `NIBLIT_ALGO_MODE` | `paper` or `live` | Optional |

## Notes

- All algorithms are **paper-trading safe by default** (brokerage set to
  `PaperBrokerage` when `self.live_mode` is False).
- ML/AI algorithms use **pure Python** implementations (no PyTorch/sklearn)
  so they deploy on QuantConnect Cloud without custom package requirements.
- The Niblit AI Master algorithm is the **only** algorithm that reads
  external Niblit signals; all others are self-contained.
