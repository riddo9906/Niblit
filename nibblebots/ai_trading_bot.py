#!/usr/bin/env python3
"""
nibblebot-ai-trading  —  AI Trading Study Bot that researches AI trading
platforms, algorithms, documentation, deployment guides, and bootcamp
materials on GitHub, then cross-references Niblit's own trading modules to
generate detailed improvement issues.

Phases:
  1. Knowledge Layer   — Load accumulated knowledge from past issues to avoid
                         re-studying the same repos and surface new findings.
  2. Live Research     — Search GitHub for top AI trading repos by topic,
                         fetch metadata, READMEs, directory trees.
  3. Niblit Scan       — Introspect the own repo's trading modules to map
                         current capabilities.
  4. Deep Analysis     — Extract trading algorithms, strategies, deployment
                         patterns, and bootcamp documentation from each repo.
  5. Gap Analysis      — Compare Niblit's current trading capabilities against
                         the best practices discovered.
  6. Autonomous Learn  — Accumulate knowledge across runs; track what has been
                         studied so each run focuses on genuinely new material.
  7. Report            — Open/update a GitHub Issue with findings, improvement
                         roadmap, and configuration suggestions.

This bot NEVER commits or pushes code.  It ONLY creates/updates GitHub Issues
labelled ``nibblebot-trading``.

Usage (local testing):
    GITHUB_TOKEN=ghp_... GITHUB_REPOSITORY=owner/repo python nibblebots/ai_trading_bot.py

Environment variables:
    GITHUB_TOKEN            — GitHub token with repo + issues scope
    GITHUB_REPOSITORY       — owner/repo  (set automatically in Actions)
    TRADING_MAX_REPOS       — max repos per topic  (default: 6)
    TRADING_DRY_RUN         — "true" to print instead of creating issue
    TRADING_DEEP_DIVE       — "true" to fetch language breakdown (uses more quota)
    TRADING_TOPICS          — comma-separated topic overrides
"""

from __future__ import annotations

import base64
import datetime
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GITHUB_API = "https://api.github.com"
UA = "Nibblebot-AITrading/1.0"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "riddo9906/Niblit")
MAX_REPOS = int(os.environ.get("TRADING_MAX_REPOS", "6"))
DRY_RUN = os.environ.get("TRADING_DRY_RUN", "").lower() == "true"
DEEP_DIVE = os.environ.get("TRADING_DEEP_DIVE", "").lower() == "true"
ISSUE_LABEL = "nibblebot-trading"
ISSUE_TITLE_PREFIX = "📈 Nibblebot AI Trading Study"

# ---------------------------------------------------------------------------
# Research topics — AI trading platforms, algorithms, deployment, bootcamps
# ---------------------------------------------------------------------------
_DEFAULT_TOPICS = (
    "algorithmic-trading,quantitative-finance,backtesting,"
    "trading-bot,cryptocurrency-trading,stock-trading,"
    "reinforcement-learning-trading,deep-learning-trading,"
    "high-frequency-trading,trading-strategy,market-making,"
    "ai-trading,trading-algorithm,trading-signals,"
    "lean-engine,freqtrade,zipline,backtrader"
)

TOPICS = [
    t.strip()
    for t in os.environ.get("TRADING_TOPICS", _DEFAULT_TOPICS).split(",")
    if t.strip()
]

# Topic → human-readable category
_TOPIC_CATEGORIES: Dict[str, str] = {}
for _cat, _keys in [
    ("Trading Platforms & Frameworks", [
        "algorithmic-trading", "lean-engine", "freqtrade", "zipline",
        "backtrader", "ai-trading",
    ]),
    ("Crypto & Market Trading Bots", [
        "trading-bot", "cryptocurrency-trading", "stock-trading",
        "market-making", "high-frequency-trading",
    ]),
    ("AI/ML Trading Algorithms", [
        "reinforcement-learning-trading", "deep-learning-trading",
        "trading-algorithm", "trading-signals", "quantitative-finance",
    ]),
    ("Backtesting & Strategy", [
        "backtesting", "trading-strategy",
    ]),
]:
    for _k in _keys:
        _TOPIC_CATEGORIES[_k] = _cat

# ---------------------------------------------------------------------------
# Pattern keywords — what to look for in trading repos
# ---------------------------------------------------------------------------
_TRADING_PATTERNS: Dict[str, List[str]] = {
    "Trading Algorithms": [
        "moving average", "rsi", "macd", "bollinger band", "ema", "sma",
        "momentum", "mean reversion", "arbitrage", "scalping", "swing trading",
        "trend following", "breakout", "grid trading", "pairs trading",
    ],
    "AI/ML Methods": [
        "reinforcement learning", "deep learning", "lstm", "transformer",
        "neural network", "q-learning", "ppo", "a3c", "dqn", "sac",
        "genetic algorithm", "evolutionary", "xgboost", "lightgbm",
        "random forest", "gradient boosting", "attention mechanism",
    ],
    "Backtesting & Simulation": [
        "backtest", "paper trading", "simulation", "historical data",
        "walk-forward", "monte carlo", "sharpe ratio", "drawdown",
        "portfolio optimization", "factor investing", "alpha generation",
    ],
    "Data & Market Feeds": [
        "binance", "alpaca", "interactive brokers", "oanda", "coinbase",
        "yahoo finance", "quandl", "polygon", "websocket", "real-time",
        "order book", "tick data", "ohlcv", "candle", "market data api",
    ],
    "Deployment & Infrastructure": [
        "docker", "kubernetes", "ci/cd", "github actions", "cloud deploy",
        "serverless", "aws", "gcp", "azure", "fly.io", "render",
        "live trading", "production", "risk management", "position sizing",
    ],
    "Risk & Portfolio Management": [
        "risk management", "stop loss", "take profit", "position sizing",
        "kelly criterion", "value at risk", "portfolio", "diversification",
        "hedging", "leverage", "margin",
    ],
    "Bootcamp & Documentation": [
        "tutorial", "bootcamp", "course", "documentation", "example",
        "notebook", "jupyter", "getting started", "quickstart", "workshop",
        "demo", "step-by-step", "guide",
    ],
}

# ---------------------------------------------------------------------------
# Niblit trading module scan — what capabilities Niblit already has
# ---------------------------------------------------------------------------
_NIBLIT_TRADING_FILES = [
    "modules/trading_brain.py",
    "modules/trading_study.py",
    "modules/trading_swing_v3.py",
    "modules/lean_deploy_engine.py",
    "modules/deployment_bridge.py",
    "niblit_deployment_bridge.json",
    "fly.toml",
    "render.yaml",
    "run_trading_brain.py",
    "run_lean_engine.py",
]

_NIBLIT_TRADING_KEYWORDS: Dict[str, List[str]] = {
    "algorithms": ["rsi", "macd", "ema", "sma", "bollinger", "momentum", "swing", "breakout"],
    "ai_methods": ["reinforcement", "neural", "lstm", "deep learning", "xgboost"],
    "brokers": ["binance", "alpaca", "oanda", "coinbase", "interactive brokers"],
    "deployment": ["docker", "fly.io", "render", "lean", "uvicorn", "fastapi"],
    "risk": ["stop loss", "position size", "risk", "drawdown", "kelly"],
    "backtesting": ["backtest", "paper trading", "simulation", "historical"],
    "data_feeds": ["websocket", "tick", "ohlcv", "candle", "market data", "live"],
}


# ---------------------------------------------------------------------------
# GitHub REST API helpers
# ---------------------------------------------------------------------------

def _gh_request(
    path: str,
    body: Optional[Dict[str, Any]] = None,
    method: str = "GET",
) -> Any:
    """Core GitHub REST API v3 request helper."""
    url = path if path.startswith("http") else f"{GITHUB_API}{path}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": UA}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    data: Optional[bytes] = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=25) as resp:  # noqa: S310
            return json.loads(resp.read().decode())
    except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
        print(f"  ⚠ API {method} error: {path} → {exc}", file=sys.stderr)
        return None


def gh_get(path: str) -> Any:
    return _gh_request(path)


def gh_post(path: str, body: Dict[str, Any]) -> Any:
    return _gh_request(path, body, "POST")


def gh_patch(path: str, body: Dict[str, Any]) -> Any:
    return _gh_request(path, body, "PATCH")


def gh_search_repos(query: str, per_page: int = MAX_REPOS) -> List[Dict[str, Any]]:
    encoded = query.replace(" ", "+")
    data = gh_get(f"/search/repositories?q={encoded}&sort=stars&per_page={per_page}")
    if data and "items" in data:
        return data["items"]
    return []


def _decode_b64(content: str) -> str:
    try:
        return base64.b64decode(content).decode("utf-8", errors="replace")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Phase 1 — Knowledge Layer
# ---------------------------------------------------------------------------

_KL_MAX_ISSUES = 10


def load_knowledge_layer() -> Dict[str, Any]:
    """
    Read past nibblebot-trading issues to extract accumulated knowledge.
    Returns: known_repos, known_algos, past_insights, known_platforms.
    """
    print("  📚 Loading knowledge layer from past issues…")
    known_repos: Set[str] = set()
    known_algos: Set[str] = set()
    known_platforms: Set[str] = set()
    past_insights: List[str] = []

    for label in (ISSUE_LABEL, "nibblebot"):
        issues = gh_get(
            f"/repos/{REPO}/issues"
            f"?labels={label}&state=closed&per_page={_KL_MAX_ISSUES}&sort=updated"
        )
        if not issues:
            continue
        for issue in issues:
            body = issue.get("body") or ""
            # Repo names
            for m in re.finditer(r"\b[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+\b", body):
                cand = m.group(0)
                if "/" in cand:
                    known_repos.add(cand)
            # Algorithms (lines with specific keywords)
            for line in body.splitlines():
                l = line.strip().lower()
                for algo in ["rsi", "macd", "lstm", "dqn", "ppo", "bollinger", "ema", "sma",
                             "reinforcement learning", "transformer", "xgboost"]:
                    if algo in l:
                        known_algos.add(algo)
                for plat in ["freqtrade", "zipline", "backtrader", "lean", "alpaca",
                             "binance", "oanda", "quantconnect"]:
                    if plat in l:
                        known_platforms.add(plat)
            # Insights
            for line in body.splitlines():
                line = line.strip()
                if line.startswith(("- [x]", "💡", "📌", "✅", "🔑")):
                    text = re.sub(r"^[-\*•✅💡🔑📌\[\]x ]+", "", line).strip()
                    if len(text) > 20:
                        past_insights.append(text)

    past_insights = list(dict.fromkeys(past_insights))[:30]
    print(
        f"  ✓ Knowledge layer: {len(known_repos)} repos, "
        f"{len(known_algos)} algos, {len(known_platforms)} platforms known"
    )
    return {
        "known_repos": known_repos,
        "known_algos": known_algos,
        "known_platforms": known_platforms,
        "past_insights": past_insights,
    }


# ---------------------------------------------------------------------------
# Phase 2 — Live Research via GitHub REST API
# ---------------------------------------------------------------------------

def fetch_repo_details(full_name: str) -> Dict[str, Any]:
    """Fetch README, top-level files, recent commits for a repo."""
    details: Dict[str, Any] = {}

    # README
    readme_data = gh_get(f"/repos/{full_name}/readme")
    if readme_data and "content" in readme_data:
        details["readme"] = _decode_b64(readme_data["content"])[:6000]
    else:
        details["readme"] = ""

    # Top-level file tree
    tree = gh_get(f"/repos/{full_name}/contents")
    details["top_files"] = (
        [f.get("name", "") for f in (tree or [])[:60]]
        if isinstance(tree, list) else []
    )

    # Recent commits
    commits = gh_get(f"/repos/{full_name}/commits?per_page=5")
    if isinstance(commits, list):
        details["recent_commits"] = [
            {
                "sha": c.get("sha", "")[:7],
                "message": (c.get("commit", {}).get("message") or "")[:100],
                "date": (c.get("commit", {}).get("author") or {}).get("date", "")[:10],
            }
            for c in commits
        ]
    else:
        details["recent_commits"] = []

    # Language breakdown (only in deep-dive mode)
    if DEEP_DIVE:
        lang_data = gh_get(f"/repos/{full_name}/languages")
        if isinstance(lang_data, dict):
            total = sum(lang_data.values()) or 1
            details["languages"] = {
                k: f"{v / total * 100:.1f}%"
                for k, v in sorted(lang_data.items(), key=lambda x: x[1], reverse=True)[:5]
            }
        else:
            details["languages"] = {}
    else:
        details["languages"] = {}

    return details


def research_topic(topic: str, known_repos: Set[str]) -> List[Dict[str, Any]]:
    """Search GitHub for repos matching *topic* and fetch enriched details."""
    print(f"  📡 Researching: {topic}")
    query = f"topic:{topic}" if " " not in topic else topic
    items = gh_search_repos(query, per_page=MAX_REPOS + 3)

    repos: List[Dict[str, Any]] = []
    new_count = 0
    for item in items:
        full_name = item.get("full_name", "")
        if not full_name or full_name in known_repos:
            continue
        if new_count >= MAX_REPOS:
            break

        print(f"    🔎 {full_name} ({item.get('stargazers_count', 0)}⭐)")
        details = fetch_repo_details(full_name)
        time.sleep(0.8)

        repos.append({
            "full_name": full_name,
            "stars": item.get("stargazers_count", 0),
            "forks": item.get("forks_count", 0),
            "open_issues": item.get("open_issues_count", 0),
            "description": (item.get("description") or "")[:200],
            "language": item.get("language") or "Unknown",
            "topics": (item.get("topics") or [])[:15],
            "url": item.get("html_url", ""),
            "homepage": item.get("homepage") or "",
            "created_at": (item.get("created_at") or "")[:10],
            "updated_at": (item.get("updated_at") or "")[:10],
            "archived": item.get("archived", False),
            "source_topic": topic,
            "category": _TOPIC_CATEGORIES.get(topic, "AI Trading"),
            **details,
        })
        new_count += 1

    print(f"  ✓ {len(repos)} new repos for '{topic}'")
    return repos


def collect_research(known_repos: Set[str]) -> List[Dict[str, Any]]:
    """Research all configured topics and return a deduplicated repo list."""
    all_repos: List[Dict[str, Any]] = []
    seen: Set[str] = set(known_repos)

    for topic in TOPICS:
        found = research_topic(topic, seen)
        for r in found:
            seen.add(r["full_name"])
        all_repos.extend(found)
        time.sleep(1.2)

    return all_repos


# ---------------------------------------------------------------------------
# Phase 3 — Niblit Trading Module Scan
# ---------------------------------------------------------------------------

def scan_niblit_trading_modules() -> Dict[str, Any]:
    """
    Introspect Niblit's own trading modules to inventory current capabilities.
    Reads local files from the repo root (available in the Actions runner).
    """
    print("  🔍 Scanning Niblit trading modules…")
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    found_files: List[str] = []
    capabilities: Dict[str, List[str]] = {k: [] for k in _NIBLIT_TRADING_KEYWORDS}
    file_sizes: Dict[str, int] = {}

    for rel_path in _NIBLIT_TRADING_FILES:
        abs_path = os.path.join(repo_root, rel_path)
        if not os.path.isfile(abs_path):
            continue
        found_files.append(rel_path)
        try:
            with open(abs_path, encoding="utf-8", errors="replace") as fh:
                content = fh.read()
            file_sizes[rel_path] = len(content)
            lower = content.lower()
            for capability, keywords in _NIBLIT_TRADING_KEYWORDS.items():
                for kw in keywords:
                    if kw in lower and kw not in capabilities[capability]:
                        capabilities[capability].append(kw)
        except OSError:
            pass

    # Also scan for notebooks, scripts, configs in root
    for name in os.listdir(repo_root):
        if name.endswith((".py", ".ipynb")) and any(
            kw in name.lower() for kw in ["trade", "algo", "strat", "market", "quant"]
        ):
            if name not in [os.path.basename(p) for p in found_files]:
                found_files.append(name)

    print(f"  ✓ Found {len(found_files)} trading-related files in Niblit")
    return {
        "found_files": found_files,
        "capabilities": capabilities,
        "file_sizes": file_sizes,
    }


# ---------------------------------------------------------------------------
# Phase 4 — Deep Analysis
# ---------------------------------------------------------------------------

def _match(text: str, keywords: List[str]) -> List[str]:
    lower = text.lower()
    return [kw for kw in keywords if kw in lower]


def analyse_repo(repo: Dict[str, Any]) -> Dict[str, Any]:
    """Extract trading patterns and insights from a single repo."""
    readme = repo.get("readme", "")
    files_str = " ".join(repo.get("top_files", []))
    desc = repo.get("description", "")
    topics_str = " ".join(repo.get("topics", []))
    combined = f"{readme} {files_str} {desc} {topics_str}"

    patterns: Dict[str, List[str]] = {
        cat: _match(combined, kws)
        for cat, kws in _TRADING_PATTERNS.items()
    }
    total_patterns = sum(len(v) for v in patterns.values())

    top_files = repo.get("top_files", [])
    has_tests = any(f.startswith("test") or f == "tests" for f in top_files)
    has_docker = "Dockerfile" in top_files or "docker-compose.yml" in top_files
    has_ci = ".github" in top_files
    has_docs = any(f.endswith(".md") or f in ("docs", "documentation") for f in top_files)
    has_notebooks = any(f.endswith(".ipynb") for f in top_files)
    has_backtest = any("backtest" in f.lower() or "strategy" in f.lower() for f in top_files)
    has_config = any(f.endswith((".yaml", ".yml", ".toml", ".cfg", ".ini")) for f in top_files)

    recent_commits = repo.get("recent_commits", [])
    last_commit_date = recent_commits[0]["date"] if recent_commits else "unknown"

    # Extract named algorithms mentioned in README
    named_algos: List[str] = []
    for algo_name in [
        "RSI", "MACD", "EMA", "SMA", "Bollinger Bands", "ATR",
        "LSTM", "DQN", "PPO", "SAC", "A3C", "Transformer",
        "XGBoost", "LightGBM", "Random Forest",
        "Freqtrade", "Zipline", "Backtrader", "QuantConnect", "LEAN",
        "Alpaca", "Binance", "OANDA",
    ]:
        if algo_name.lower() in combined.lower():
            named_algos.append(algo_name)

    # Check for deployment docs
    deploy_docs: List[str] = []
    for deploy_kw in ["fly.io", "render.com", "heroku", "aws", "gcp", "docker deploy", "kubernetes"]:
        if deploy_kw.lower() in combined.lower():
            deploy_docs.append(deploy_kw)

    return {
        "full_name": repo["full_name"],
        "stars": repo["stars"],
        "forks": repo["forks"],
        "open_issues": repo["open_issues"],
        "url": repo["url"],
        "description": desc,
        "language": repo["language"],
        "category": repo["category"],
        "source_topic": repo["source_topic"],
        "patterns": patterns,
        "total_patterns": total_patterns,
        "named_algos": named_algos,
        "deploy_docs": deploy_docs,
        "has_tests": has_tests,
        "has_docker": has_docker,
        "has_ci": has_ci,
        "has_docs": has_docs,
        "has_notebooks": has_notebooks,
        "has_backtest": has_backtest,
        "has_config": has_config,
        "last_commit_date": last_commit_date,
        "top_files": top_files[:20],
        "languages": repo.get("languages", {}),
        "archived": repo.get("archived", False),
    }


def analyse_all(repos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [analyse_repo(r) for r in repos]


# ---------------------------------------------------------------------------
# Phase 5 — Gap Analysis: Niblit vs. best-practice repos
# ---------------------------------------------------------------------------

_IMPROVEMENT_TEMPLATES: Dict[str, str] = {
    "algorithms": (
        "Implement additional trading algorithms: {items}. "
        "These are widely used in top-starred trading repos."
    ),
    "ai_methods": (
        "Add AI/ML methods to the TradingBrain: {items}. "
        "RL-based approaches like PPO/DQN are dominant in elite repos."
    ),
    "brokers": (
        "Expand broker integrations to include: {items}. "
        "Multi-broker support improves flexibility and redundancy."
    ),
    "deployment": (
        "Strengthen deployment infrastructure: {items}. "
        "Top repos include full CI/CD, Docker, and cloud-provider docs."
    ),
    "risk": (
        "Add risk management features: {items}. "
        "Kelly Criterion, VAR, and dynamic position sizing are standard in professional platforms."
    ),
    "backtesting": (
        "Extend backtesting capabilities: {items}. "
        "Walk-forward analysis and Monte Carlo simulation are present in leading repos."
    ),
    "data_feeds": (
        "Integrate additional market data feeds: {items}. "
        "Real-time tick data and alternative data sources are key differentiators."
    ),
}


def gap_analysis(
    niblit_scan: Dict[str, Any],
    analyses: List[Dict[str, Any]],
    knowledge: Dict[str, Any],
) -> Dict[str, Any]:
    """Compare Niblit's current capabilities against the studied repos."""
    niblit_caps = niblit_scan["capabilities"]

    # Aggregate what the top repos implement
    repo_algo_freq: Dict[str, int] = {}
    repo_deploy_freq: Dict[str, int] = {}
    for a in analyses:
        for algo in a["named_algos"]:
            repo_algo_freq[algo] = repo_algo_freq.get(algo, 0) + 1
        for dep in a["deploy_docs"]:
            repo_deploy_freq[dep] = repo_deploy_freq.get(dep, 0) + 1

    # Top algos not yet found in Niblit
    missing_algos: List[str] = []
    for algo, count in sorted(repo_algo_freq.items(), key=lambda x: x[1], reverse=True):
        if algo.lower() not in [c.lower() for c in niblit_caps.get("algorithms", [])]:
            missing_algos.append(f"{algo} ({count} repos)")

    # Top deployment approaches not yet in Niblit
    missing_deploy: List[str] = []
    for dep, count in sorted(repo_deploy_freq.items(), key=lambda x: x[1], reverse=True):
        if dep.lower() not in [c.lower() for c in niblit_caps.get("deployment", [])]:
            missing_deploy.append(f"{dep} ({count} repos)")

    # Pattern gaps per category
    category_gaps: Dict[str, List[str]] = {}
    niblit_all_text = " ".join(
        " ".join(v) for v in niblit_caps.values()
    ).lower()
    for cat, kws in _TRADING_PATTERNS.items():
        gaps = []
        for kw in kws:
            # Count how many studied repos have this keyword
            count = sum(1 for a in analyses if kw in [k for kws2 in a["patterns"].values() for k in kws2])
            if count >= 2 and kw.lower() not in niblit_all_text:
                gaps.append(f"`{kw}` ({count} repos)")
        if gaps:
            category_gaps[cat] = gaps[:6]

    # Generate improvement suggestions
    improvements: List[Dict[str, str]] = []

    if missing_algos:
        improvements.append({
            "title": "🧮 Missing Trading Algorithms",
            "priority": "HIGH",
            "detail": (
                "The following algorithms appear frequently in top repos but were NOT found "
                f"in Niblit's trading modules:\n\n"
                + "\n".join(f"- {a}" for a in missing_algos[:10])
            ),
        })

    if missing_deploy:
        improvements.append({
            "title": "🚀 Deployment Infrastructure Gaps",
            "priority": "MEDIUM",
            "detail": (
                "Deployment targets commonly documented in top trading repos but missing from Niblit:\n\n"
                + "\n".join(f"- {d}" for d in missing_deploy[:8])
            ),
        })

    for cat, gaps in category_gaps.items():
        improvements.append({
            "title": f"📊 {cat} — Missing Patterns",
            "priority": "MEDIUM",
            "detail": (
                f"Patterns in the **{cat}** category that top repos implement, "
                f"not yet present in Niblit:\n\n"
                + "\n".join(f"- {g}" for g in gaps)
            ),
        })

    # Notebooks / bootcamp gap
    notebook_repos = [a for a in analyses if a["has_notebooks"]]
    if notebook_repos and not any("notebook" in f.lower() or ".ipynb" in f for f in niblit_scan["found_files"]):
        improvements.append({
            "title": "📓 AI Trading Bootcamp / Notebook Gap",
            "priority": "LOW",
            "detail": (
                f"{len(notebook_repos)} studied repos include Jupyter notebooks for "
                "tutorials and bootcamp documentation. Niblit currently has none. "
                "Adding starter notebooks would lower the onboarding barrier.\n\n"
                "Repos with notebooks:\n"
                + "\n".join(f"- [{a['full_name']}]({a['url']})" for a in notebook_repos[:5])
            ),
        })

    # Risk management gap
    if not niblit_caps.get("risk"):
        improvements.append({
            "title": "🛡️ Risk Management — Not Implemented",
            "priority": "HIGH",
            "detail": (
                "Niblit's trading modules do not appear to implement formal risk management "
                "(stop-loss, position sizing, Kelly Criterion, VAR). This is a critical gap "
                "for production trading. Top repos reference:\n\n"
                "- Dynamic stop-loss tied to ATR\n"
                "- Kelly Criterion for position sizing\n"
                "- Maximum drawdown circuit-breaker\n"
                "- Value-at-Risk (VAR) daily limits"
            ),
        })

    return {
        "missing_algos": missing_algos[:10],
        "missing_deploy": missing_deploy[:8],
        "category_gaps": category_gaps,
        "improvements": improvements,
        "niblit_caps": niblit_caps,
        "niblit_files": niblit_scan["found_files"],
    }


# ---------------------------------------------------------------------------
# Phase 6 — Autonomous Learning: synthesis
# ---------------------------------------------------------------------------

def synthesise(
    analyses: List[Dict[str, Any]],
    knowledge: Dict[str, Any],
) -> Dict[str, Any]:
    """Aggregate repo analyses into cross-cutting trading insights."""
    pattern_freq: Dict[str, Dict[str, int]] = {cat: {} for cat in _TRADING_PATTERNS}
    lang_counts: Dict[str, int] = {}
    algo_freq: Dict[str, int] = {}

    for a in analyses:
        for cat, matched in a["patterns"].items():
            for kw in matched:
                pattern_freq[cat][kw] = pattern_freq[cat].get(kw, 0) + 1
        lang = a.get("language") or "Unknown"
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
        for algo in a.get("named_algos", []):
            algo_freq[algo] = algo_freq.get(algo, 0) + 1

    def _top(d: Dict[str, int], n: int = 8) -> List[Tuple[str, int]]:
        return sorted(d.items(), key=lambda x: x[1], reverse=True)[:n]

    # High-value repos for deep study
    sorted_stars = sorted(a["stars"] for a in analyses)
    p75_idx = min(int(len(sorted_stars) * 0.75), len(sorted_stars) - 1)
    star_p75 = sorted_stars[p75_idx] if sorted_stars else 0
    high_value = sorted(
        [a for a in analyses if a["total_patterns"] >= 2 and a["stars"] >= star_p75],
        key=lambda x: x["total_patterns"] * x["stars"],
        reverse=True,
    )[:6]

    # New insights (not in past knowledge)
    past_algos_lower = {a.lower() for a in knowledge.get("known_algos", set())}
    new_insights: List[str] = []
    for a in analyses:
        for algo in a.get("named_algos", []):
            if algo.lower() not in past_algos_lower:
                new_insights.append(f"Algorithm **{algo}** — new in this run (from {a['full_name']})")
    for cat, matched_kws in pattern_freq.items():
        for kw, count in matched_kws.items():
            if count >= 3 and kw not in knowledge.get("known_algos", set()):
                new_insights.append(f"Pattern `{kw}` ({cat}) appears in {count} repos — newly discovered")
    new_insights = list(dict.fromkeys(new_insights))[:20]

    return {
        "total_repos_studied": len(analyses),
        "pattern_freq": {cat: _top(freq) for cat, freq in pattern_freq.items()},
        "top_languages": _top(lang_counts, 6),
        "top_algos": _top(algo_freq, 12),
        "high_value_repos": high_value,
        "new_insights": new_insights,
        "past_insights": knowledge.get("past_insights", [])[:8],
    }


# ---------------------------------------------------------------------------
# Phase 7 — Build the GitHub Issue body
# ---------------------------------------------------------------------------

_PRIO_EMOJI = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}


def build_issue_body(
    analyses: List[Dict[str, Any]],
    synthesis: Dict[str, Any],
    gaps: Dict[str, Any],
    knowledge: Dict[str, Any],
) -> str:
    """Render the full GitHub Issue markdown."""
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    past_count = len(knowledge.get("known_repos", set()))

    lines: List[str] = [
        "# 📈 Nibblebot AI Trading Study Report",
        "",
        f"**Generated:** {now}  ",
        f"**Repos studied this run:** {synthesis['total_repos_studied']}  ",
        f"**Known repos (knowledge layer):** {past_count}  ",
        f"**Topics covered:** {', '.join(TOPICS[:8])}{'…' if len(TOPICS) > 8 else ''}",
        "",
        (
            "> This report is generated by the Nibblebot AI Trading Study Bot.\n"
            "> It researches AI trading platforms, algorithms, bootcamp documentation,\n"
            "> and deployment patterns on GitHub, then cross-references Niblit's own\n"
            "> trading modules to produce actionable improvement suggestions.\n"
            "> The bot autonomously accumulates knowledge across runs."
        ),
        "",
    ]

    # ── Niblit Current Trading Capabilities ──────────────────────────────
    lines += [
        "## 🔍 Niblit Current Trading Capabilities (Module Scan)",
        "",
        f"**Trading files found:** {', '.join(f'`{f}`' for f in gaps['niblit_files'][:8]) or '_none_'}",
        "",
        "| Capability Area | Detected Keywords |",
        "|----------------|-------------------|",
    ]
    for cap, kws in gaps["niblit_caps"].items():
        kw_str = ", ".join(f"`{k}`" for k in kws[:6]) if kws else "—"
        lines.append(f"| {cap.replace('_', ' ').title()} | {kw_str} |")
    lines.append("")

    # ── Knowledge Layer Carry-forward ────────────────────────────────────
    if knowledge.get("past_insights"):
        lines += [
            "## 📚 Knowledge Layer — Carried-Forward Insights",
            "",
            "_From previous study runs:_",
            "",
        ]
        for insight in knowledge["past_insights"][:6]:
            lines.append(f"- 📌 {insight}")
        lines.append("")

    # ── New Discoveries ──────────────────────────────────────────────────
    if synthesis["new_insights"]:
        lines += [
            "## 💡 New Discoveries (First Time Seen)",
            "",
        ]
        for insight in synthesis["new_insights"][:15]:
            lines.append(f"- ✨ {insight}")
        lines.append("")

    # ── Improvement Recommendations ──────────────────────────────────────
    if gaps["improvements"]:
        lines += [
            "## 🛠️ Improvement Recommendations for Niblit",
            "",
            "_Prioritised findings from gap analysis:_",
            "",
        ]
        for imp in gaps["improvements"]:
            emoji = _PRIO_EMOJI.get(imp["priority"], "⚪")
            lines += [
                f"### {emoji} [{imp['priority']}] {imp['title']}",
                "",
                imp["detail"],
                "",
            ]

    # ── Top Trading Algorithms Seen ──────────────────────────────────────
    if synthesis["top_algos"]:
        lines += [
            "## 🧮 Most Referenced Trading Algorithms",
            "",
            "| Algorithm | Repos Using It |",
            "|-----------|---------------|",
        ]
        for algo, count in synthesis["top_algos"]:
            lines.append(f"| `{algo}` | {count} |")
        lines.append("")

    # ── Pattern Frequency ────────────────────────────────────────────────
    lines += ["## 📊 Pattern Frequency by Category", ""]
    for cat, top_patterns in synthesis["pattern_freq"].items():
        if not top_patterns:
            continue
        lines += [
            f"### {cat}",
            "",
            "| Pattern / Keyword | Repos |",
            "|-------------------|-------|",
        ]
        for kw, count in top_patterns:
            lines.append(f"| `{kw}` | {count} |")
        lines.append("")

    # ── Top Languages ────────────────────────────────────────────────────
    lines += [
        "## 🌐 Language Landscape",
        "",
        "| Language | Repos |",
        "|----------|-------|",
    ]
    for lang, count in synthesis["top_languages"]:
        lines.append(f"| {lang} | {count} |")
    lines.append("")

    # ── High-Value Repos for Deep Study ──────────────────────────────────
    if synthesis["high_value_repos"]:
        lines += [
            "## ⭐ High-Value Repos — Recommended for Deep Study",
            "",
            "| Repo | Stars | Category | Key Patterns | Notebooks | Last Commit |",
            "|------|-------|----------|-------------|-----------|------------|",
        ]
        for a in synthesis["high_value_repos"]:
            all_kws = [kw for kws in a["patterns"].values() for kw in kws][:3]
            kw_str = ", ".join(f"`{k}`" for k in all_kws) if all_kws else "—"
            nb = "✅" if a["has_notebooks"] else "—"
            lines.append(
                f"| [{a['full_name']}]({a['url']}) "
                f"| {a['stars']:,} "
                f"| {a['category']} "
                f"| {kw_str} "
                f"| {nb} "
                f"| {a['last_commit_date']} |"
            )
        lines.append("")

    # ── Per-Repo Breakdown ────────────────────────────────────────────────
    lines += ["## 🗂️ Repos Studied This Run", ""]
    seen_cats: Set[str] = set()
    for a in sorted(analyses, key=lambda x: x["category"]):
        cat = a["category"]
        if cat not in seen_cats:
            seen_cats.add(cat)
            lines += [f"### {cat}", ""]

        badges: List[str] = []
        if a["has_tests"]:
            badges.append("✅ tests")
        if a["has_docker"]:
            badges.append("🐳 docker")
        if a["has_ci"]:
            badges.append("⚙️ CI")
        if a["has_docs"]:
            badges.append("📄 docs")
        if a["has_notebooks"]:
            badges.append("📓 notebooks")
        if a["has_backtest"]:
            badges.append("📉 backtest")
        badge_str = " · ".join(badges) or "_no markers_"

        algos_str = ", ".join(f"`{al}`" for al in a["named_algos"][:5]) if a["named_algos"] else "—"
        deploy_str = ", ".join(a["deploy_docs"][:3]) if a["deploy_docs"] else "—"

        lines += [
            f"**[{a['full_name']}]({a['url']})** — {a['stars']:,}⭐  ",
            f"_{a['description'] or 'No description'}_  ",
            f"Lang: `{a['language']}` | {badge_str}  ",
            f"Algorithms: {algos_str} | Deploy docs: {deploy_str}",
            "",
        ]

    # ── Deployment & Infrastructure Study ────────────────────────────────
    lines += [
        "## 🚀 Deployment Patterns Found in Studied Repos",
        "",
    ]
    all_deploy: Dict[str, int] = {}
    for a in analyses:
        for dep in a.get("deploy_docs", []):
            all_deploy[dep] = all_deploy.get(dep, 0) + 1
    if all_deploy:
        lines += [
            "| Deployment Target | Repos |",
            "|-------------------|-------|",
        ]
        for dep, count in sorted(all_deploy.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"| `{dep}` | {count} |")
    else:
        lines.append("_No specific deployment documentation found in this batch._")
    lines.append("")

    # ── Autonomous Learning Growth ────────────────────────────────────────
    lines += [
        "## 📈 Autonomous Learning Progress",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Repos in knowledge layer (before this run) | {past_count} |",
        f"| New repos studied | {synthesis['total_repos_studied']} |",
        f"| New insights discovered | {len(synthesis['new_insights'])} |",
        f"| Topics covered | {len(TOPICS)} |",
        "",
    ]

    # ── Action Items Checklist ────────────────────────────────────────────
    lines += [
        "## ✅ Niblit AI Trading Improvement Checklist",
        "",
        "- [ ] Review and implement missing algorithms from gap analysis",
        "- [ ] Add formal risk management module (stop-loss, Kelly Criterion, VAR)",
        "- [ ] Study high-value repos listed above for integration ideas",
        "- [ ] Add Jupyter notebook trading bootcamp / quickstart guide",
        "- [ ] Extend broker integrations (Alpaca, Binance, Interactive Brokers)",
        "- [ ] Add walk-forward backtesting and Monte Carlo simulation",
        "- [ ] Document trading deployment guide (fly.io, Render, Docker)",
        "- [ ] Integrate real-time tick data websocket feed",
        "- [ ] Add reinforcement learning trading agent (PPO/DQN)",
        "- [ ] Create automated trading performance dashboard",
        "",
    ]

    # Footer
    lines += [
        "---",
        "",
        "_Nibblebot AI Trading Study Bot — GitHub REST API + Autonomous Knowledge Layer_  ",
        "_Part of the [Niblit](https://github.com/riddo9906/Niblit) project_",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Issue management
# ---------------------------------------------------------------------------

def find_open_issue() -> Optional[int]:
    """Return the number of an existing open nibblebot-trading issue, or None."""
    data = gh_get(
        f"/repos/{REPO}/issues?labels={ISSUE_LABEL}&state=open&per_page=10"
    )
    if not data:
        return None
    for issue in data:
        if ISSUE_TITLE_PREFIX in issue.get("title", ""):
            return issue["number"]
    return None


def create_or_update_issue(title: str, body: str) -> None:
    """Create a new issue or update the body of the existing one."""
    existing = find_open_issue()
    if existing:
        print(f"  ✏️  Updating existing issue #{existing}…")
        gh_patch(f"/repos/{REPO}/issues/{existing}", {"body": body})
        print(f"  ✓ Issue #{existing} updated.")
    else:
        print("  🆕 Creating new issue…")
        result = gh_post(
            f"/repos/{REPO}/issues",
            {"title": title, "body": body, "labels": [ISSUE_LABEL]},
        )
        if result:
            print(f"  ✓ Issue #{result.get('number')} created: {result.get('html_url')}")
        else:
            print("  ⚠ Failed to create issue.", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("📈 Nibblebot AI Trading Study Bot starting…")
    print(f"   Repo       : {REPO}")
    print(f"   Topics     : {', '.join(TOPICS[:5])}{'…' if len(TOPICS) > 5 else ''}")
    print(f"   Max repos  : {MAX_REPOS} per topic")
    print(f"   Deep dive  : {DEEP_DIVE}")
    print(f"   Dry run    : {DRY_RUN}")
    print()

    if not TOKEN:
        print(
            "⚠ GITHUB_TOKEN not set — API calls will be unauthenticated and heavily rate-limited.",
            file=sys.stderr,
        )

    # Phase 1 — Knowledge Layer
    print("📚 Phase 1: Loading knowledge layer…")
    knowledge = load_knowledge_layer()
    print()

    # Phase 2 — Live Research
    print("📡 Phase 2: Live research on GitHub AI trading repos…")
    repos = collect_research(knowledge["known_repos"])
    if not repos:
        print("⚠ No new repos found. Expand TRADING_TOPICS or increase TRADING_MAX_REPOS.")
        return
    print(f"\n  ✓ Total new repos collected: {len(repos)}")
    print()

    # Phase 3 — Niblit Scan
    print("🔍 Phase 3: Scanning Niblit trading modules…")
    niblit_scan = scan_niblit_trading_modules()
    print()

    # Phase 4 — Analysis
    print("🧠 Phase 4: Analysing repos…")
    analyses = analyse_all(repos)
    print(f"  ✓ Analysed {len(analyses)} repos")
    print()

    # Phase 5 — Gap Analysis
    print("📊 Phase 5: Running gap analysis…")
    gaps = gap_analysis(niblit_scan, analyses, knowledge)
    print(f"  ✓ {len(gaps['improvements'])} improvement areas identified")
    print()

    # Phase 6 — Synthesis
    print("⚗️  Phase 6: Synthesising with knowledge layer…")
    synthesis = synthesise(analyses, knowledge)
    print(f"  ✓ {len(synthesis['new_insights'])} new insights discovered")
    print()

    # Phase 7 — Report
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    title = (
        f"{ISSUE_TITLE_PREFIX} — {now_str} "
        f"({synthesis['total_repos_studied']} repos, "
        f"{len(gaps['improvements'])} gaps)"
    )
    body = build_issue_body(analyses, synthesis, gaps, knowledge)

    if DRY_RUN:
        print("\n" + "=" * 70)
        print(f"DRY RUN — Issue title: {title}")
        print("=" * 70)
        print(body[:4000] + ("\n…[truncated]" if len(body) > 4000 else ""))
        print("=" * 70)
    else:
        print(f"📝 Phase 7: Publishing issue: {title}")
        create_or_update_issue(title, body)

    print("\n✅ Nibblebot AI Trading Study Bot finished.")


if __name__ == "__main__":
    main()
