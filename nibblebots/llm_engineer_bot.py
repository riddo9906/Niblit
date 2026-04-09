#!/usr/bin/env python3
"""
nibblebot-llm-engineer  —  Nibblebot that studies how software engineers
build, train, fine-tune, and evaluate production LLMs and applies those
findings directly to Niblit's architecture.

Phases:
  1. Knowledge Layer  — Load accumulated knowledge from past nibblebot issues
                        to avoid re-studying the same repos.
  2. LLM-Build Research — Search GitHub for repos covering every stage of the
                          LLM development pipeline:
                          • Pre-training data pipelines and tokenizers
                          • Transformer architecture implementations
                          • SFT / RLHF / DPO / PPO fine-tuning frameworks
                          • Evaluation harnesses and benchmarks
                          • Serving, quantisation, and inference optimisation
  3. Trading-AI Research — Apply the same methodology to trading AI:
                          • RL trading environments (PPO, DQN, A3C)
                          • Transformer market models (TFT, PatchTST, lag-llama)
                          • Signal engineering, risk management, live execution
  4. Niblit Gap Analysis — Compare findings against Niblit's current codebase
                           to identify concrete upgrade opportunities.
  5. Synthesis         — Generate actionable architecture upgrade proposals
                         aligned with Niblit's existing module structure.
  6. Report            — Open/update a GitHub Issue with findings.

This bot NEVER commits or pushes code.  It ONLY creates/updates GitHub Issues
labelled ``nibblebot-llm-engineer``.

Usage (local testing):
    GITHUB_TOKEN=ghp_... GITHUB_REPOSITORY=owner/repo \\
        python nibblebots/llm_engineer_bot.py

Environment variables:
    GITHUB_TOKEN          — GitHub personal access token (repo + issues scope)
    GITHUB_REPOSITORY     — owner/repo  (set automatically in GitHub Actions)
    LLM_ENG_MAX_REPOS     — max repos per topic  (default: 5)
    LLM_ENG_DRY_RUN       — "true" to print instead of creating an issue
    LLM_ENG_DEEP_DIVE     — "true" to fetch per-repo language breakdown
    LLM_ENG_TOPICS        — comma-separated topic overrides
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
UA = "Nibblebot-LLMEngineer/1.0"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "riddo9906/Niblit")
MAX_REPOS = int(os.environ.get("LLM_ENG_MAX_REPOS", "5"))
DRY_RUN = os.environ.get("LLM_ENG_DRY_RUN", "").lower() == "true"
DEEP_DIVE = os.environ.get("LLM_ENG_DEEP_DIVE", "").lower() == "true"
ISSUE_LABEL = "nibblebot-llm-engineer"
ISSUE_TITLE_PREFIX = "🤖 Nibblebot LLM Engineer Report"

_DEFAULT_TOPICS = (
    # ── Stage 1: Data pipelines & tokenisation ───────────────────────────
    "llm-pretraining,tokenizer-training,bpe-tokenizer,sentencepiece,"
    "text-corpus-curation,data-deduplication,training-data-pipeline,"
    "the-pile,redpajama,dolma,fineweb,"
    # ── Stage 2: Transformer architecture ───────────────────────────────
    "transformer-architecture,attention-mechanism,flash-attention,"
    "rotary-positional-embedding,grouped-query-attention,mixture-of-experts,"
    "llama,mistral,phi,gemma,qwen,"
    # ── Stage 3: Training infrastructure ────────────────────────────────
    "llm-training,distributed-training,deepspeed,fsdp,megatron-lm,"
    "gradient-checkpointing,mixed-precision-training,zero-optimization,"
    # ── Stage 4: Fine-tuning & alignment ────────────────────────────────
    "supervised-fine-tuning,rlhf,dpo-training,ppo-finetuning,"
    "constitutional-ai,instruction-tuning,lora-fine-tuning,qlora,"
    "peft,trl,axolotl,unsloth,"
    # ── Stage 5: Evaluation ──────────────────────────────────────────────
    "llm-evaluation,lm-eval-harness,hellaswag,mmlu,gsm8k,"
    "perplexity-evaluation,llm-benchmark,ai-alignment-testing,"
    # ── Stage 6: Inference optimisation ─────────────────────────────────
    "vllm,text-generation-inference,llama-cpp,"
    "quantization,gptq,awq,model-compression,"
    # ── Trading AI methodology ────────────────────────────────────────────
    "reinforcement-learning-trading,ppo-trading,dqn-stock-trading,finrl,"
    "temporal-fusion-transformer,lag-llama,chronos-forecasting,patchtst,"
    "trading-feature-engineering,risk-management-trading,live-trading-execution"
)
TOPICS = [
    t.strip()
    for t in os.environ.get("LLM_ENG_TOPICS", _DEFAULT_TOPICS).split(",")
    if t.strip()
]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def _headers() -> Dict[str, str]:
    h = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    if TOKEN:
        h["Authorization"] = f"Bearer {TOKEN}"
    return h


def _get(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """Make a GET request and return parsed JSON, or {} on failure."""
    if params:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{query}"
    req = Request(url, headers=_headers())
    try:
        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except (HTTPError, URLError, Exception) as exc:
        print(f"  [WARN] GET {url[:80]} → {exc}", file=sys.stderr)
        return {}


def _b64decode(s: str) -> str:
    try:
        return base64.b64decode(s).decode("utf-8", errors="replace")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# GitHub search helpers
# ---------------------------------------------------------------------------
def search_repos(topic: str, max_repos: int = MAX_REPOS) -> List[Dict[str, Any]]:
    """Search for GitHub repositories by topic."""
    data = _get(
        f"{GITHUB_API}/search/repositories",
        params={
            "q": f"topic:{topic} stars:>100 language:Python",
            "sort": "stars",
            "order": "desc",
            "per_page": str(max_repos),
        },
    )
    return data.get("items", [])


def fetch_readme(full_name: str) -> str:
    """Fetch the README text for a repo (decoded from base64)."""
    data = _get(f"{GITHUB_API}/repos/{full_name}/readme")
    content = data.get("content", "")
    if not content:
        return ""
    return _b64decode(content)[:6000]


def fetch_repo_tree(full_name: str) -> List[str]:
    """Return a flat list of top-level file/folder names."""
    data = _get(f"{GITHUB_API}/repos/{full_name}/git/trees/HEAD", params={"recursive": "1"})
    tree = data.get("tree", [])
    return [item["path"] for item in tree if item.get("type") == "blob"][:100]


def fetch_recent_commits(full_name: str, limit: int = 3) -> List[Dict[str, str]]:
    """Return the most recent commit messages."""
    data = _get(f"{GITHUB_API}/repos/{full_name}/commits", params={"per_page": str(limit)})
    if not isinstance(data, list):
        return []
    return [
        {
            "sha": c.get("sha", "")[:7],
            "message": c.get("commit", {}).get("message", "")[:120],
            "author": c.get("commit", {}).get("author", {}).get("name", ""),
        }
        for c in data
    ]


# ---------------------------------------------------------------------------
# Knowledge layer — accumulate across runs
# ---------------------------------------------------------------------------
def load_knowledge_layer() -> Dict[str, Any]:
    """Read past nibblebot-llm-engineer issues and extract accumulated knowledge."""
    known: Dict[str, Any] = {"studied_repos": set(), "architectures": [], "methodologies": []}
    data = _get(
        f"{GITHUB_API}/repos/{REPO}/issues",
        params={
            "labels": ISSUE_LABEL,
            "state": "all",
            "per_page": "10",
            "direction": "desc",
        },
    )
    if not isinstance(data, list):
        return known
    for issue in data[:5]:
        body = issue.get("body", "") or ""
        # Extract repo names already studied
        for m in re.findall(r"`([a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+)`", body):
            known["studied_repos"].add(m)
        # Extract architecture patterns
        for m in re.findall(r"Architecture:\s*([^\n]+)", body):
            known["architectures"].append(m.strip())
        # Extract methodologies
        for m in re.findall(r"Methodology:\s*([^\n]+)", body):
            known["methodologies"].append(m.strip())
    return known


# ---------------------------------------------------------------------------
# Deep analysis
# ---------------------------------------------------------------------------
_LLM_PATTERNS = [
    # Pre-training signals
    "pretraining", "tokenizer", "sentencepiece", "tiktoken", "bpe",
    "data_pipeline", "deduplication", "corpus",
    # Architecture
    "transformer", "attention", "flash_attn", "rope", "gqa", "moe",
    "residual", "layer_norm", "rmsnorm",
    # Training
    "deepspeed", "fsdp", "megatron", "gradient_checkpoint", "bf16", "fp16",
    "zero_optimization", "gradient_accumulation",
    # Fine-tuning / alignment
    "sft", "rlhf", "dpo", "ppo", "reward_model", "lora", "qlora",
    "peft", "trl", "axolotl", "unsloth", "instruction_tuning",
    # Evaluation
    "lm_eval", "mmlu", "hellaswag", "perplexity", "benchmark",
    # Serving
    "vllm", "tgi", "llama_cpp", "quantiz", "gptq", "awq",
]

_TRADING_PATTERNS = [
    # RL
    "ppo", "dqn", "a3c", "reinforce", "policy_gradient", "reward_shaping",
    "gym", "trading_env", "finrl",
    # Architecture
    "temporal_fusion", "informer", "patchtst", "lag_llama", "chronos",
    "lstm", "gru", "tcn", "wavenet",
    # Signal engineering
    "rsi", "macd", "atr", "ema", "bollinger", "vwap", "order_flow",
    "limit_order_book", "alternative_data",
    # Risk / portfolio
    "sharpe", "drawdown", "kelly", "position_sizing", "risk_management",
    # Live execution
    "live_trading", "paper_trading", "order_management", "execution",
]


def analyse_repo(repo: Dict[str, Any], readme: str, tree: List[str]) -> Dict[str, Any]:
    """Extract LLM/trading engineering patterns from a repo."""
    combined = (readme + " " + " ".join(tree)).lower()

    llm_hits = [p for p in _LLM_PATTERNS if p in combined]
    trading_hits = [p for p in _TRADING_PATTERNS if p in combined]

    # Detect stage of the LLM pipeline covered
    stages = []
    if any(p in combined for p in ["tokenizer", "pretraining", "corpus", "deduplication"]):
        stages.append("pre-training")
    if any(p in combined for p in ["transformer", "attention", "rope", "gqa"]):
        stages.append("architecture")
    if any(p in combined for p in ["deepspeed", "fsdp", "megatron", "gradient_checkpoint"]):
        stages.append("training-infra")
    if any(p in combined for p in ["sft", "rlhf", "dpo", "lora", "peft", "trl"]):
        stages.append("fine-tuning")
    if any(p in combined for p in ["lm_eval", "mmlu", "perplexity", "benchmark"]):
        stages.append("evaluation")
    if any(p in combined for p in ["vllm", "tgi", "quantiz", "gptq", "awq"]):
        stages.append("inference")

    return {
        "name": repo.get("full_name", ""),
        "stars": repo.get("stargazers_count", 0),
        "description": repo.get("description", "") or "",
        "url": repo.get("html_url", ""),
        "llm_patterns": llm_hits[:15],
        "trading_patterns": trading_hits[:10],
        "pipeline_stages": stages,
        "language": repo.get("language", ""),
        "topics": repo.get("topics", []),
    }


# ---------------------------------------------------------------------------
# Gap analysis: compare against Niblit's current modules
# ---------------------------------------------------------------------------
_NIBLIT_CAPABILITIES = {
    "pre-training": False,          # Niblit has no pre-training loop yet
    "tokenizer": False,              # Niblit relies on HF API tokenizer
    "architecture": True,            # HFBrain uses hosted transformer
    "training-infra": False,         # No distributed training
    "fine-tuning": True,             # LLMTrainingAgent + BrainTrainer + LoRA via llm_architect_engine
    "dpo": True,                     # LLMArchitectEngine.run_dpo()
    "evaluation": True,              # LLMArchitectEngine.run_eval()
    "inference": True,               # HFBrain / local model via LOCAL_MODEL_PATH
    "rl-trading": True,              # modules/rl_trading_policy.py (PPO, DQN, Transformer)
    "transformer-market-model": False, # Not yet — TFT/PatchTST not wired
    "signal-engineering": True,      # modules/trading_brain.py (RSI, MACD, ATR, EMA, volatility)
    "risk-management": False,        # No Kelly/Sharpe/drawdown-control module yet
    "live-execution": True,          # TradingBrain._autonomous_loop
}

_UPGRADE_HINTS = {
    "pre-training": "Add a tokenizer training step in LLMArchitectEngine using SentencePiece/tiktoken on the KB corpus.",
    "tokenizer": "Train a domain-specific BPE tokenizer on Niblit's accumulated KB text. Store vocab in NIBLIT_DATA_DIR/tokenizer/.",
    "training-infra": "Add LoRA/QLoRA support (already partly done via llm_architect_engine._run_lora_sft). Set LOCAL_MODEL_PATH to a small local model to activate.",
    "transformer-market-model": "Wire a Temporal Fusion Transformer or lag-llama forecast into TradingBrain.decide_action() as an additional signal alongside the RL policy.",
    "risk-management": "Add Kelly Criterion position sizing and max-drawdown circuit breakers to TradingBrain. See QuantStats/PyPortfolioOpt on GitHub.",
}


def generate_gap_report(discovered: List[Dict[str, Any]]) -> str:
    """Generate actionable gap analysis against Niblit's known capabilities."""
    lines = ["## 🔍 Niblit Gap Analysis\n"]
    lines.append("| Capability | Niblit Status | Discovered Pattern | Upgrade Path |")
    lines.append("|------------|--------------|---------------------|--------------|")

    for cap, has_it in _NIBLIT_CAPABILITIES.items():
        status = "✅ Present" if has_it else "❌ Missing"
        # Find repos that implement this capability
        relevant = [
            d["name"] for d in discovered
            if cap.replace("-", "_") in " ".join(d.get("llm_patterns", []) + d.get("trading_patterns", []))
            or cap in d.get("pipeline_stages", [])
        ][:2]
        pattern_str = ", ".join(f"`{r}`" for r in relevant) if relevant else "—"
        hint = _UPGRADE_HINTS.get(cap, "Continue researching via ALE cycle topics.") if not has_it else "Mature."
        lines.append(f"| `{cap}` | {status} | {pattern_str} | {hint} |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------
def build_report(
    discovered: List[Dict[str, Any]],
    knowledge: Dict[str, Any],
    run_ts: str,
) -> str:
    """Build the full GitHub Issue body."""
    total_stars = sum(d.get("stars", 0) for d in discovered)
    stage_counts: Dict[str, int] = {}
    for d in discovered:
        for s in d.get("pipeline_stages", []):
            stage_counts[s] = stage_counts.get(s, 0) + 1

    lines = [
        f"# {ISSUE_TITLE_PREFIX}",
        f"",
        f"**Generated:** {run_ts}  |  **Repos analysed:** {len(discovered)}  |  **Total ★:** {total_stars:,}",
        f"",
        "---",
        "## 🏗️ LLM Pipeline Coverage Across Studied Repos",
        "",
    ]

    # Stage coverage table
    all_stages = ["pre-training", "architecture", "training-infra", "fine-tuning", "evaluation", "inference"]
    lines.append("| Pipeline Stage | Repos Covering It |")
    lines.append("|----------------|-------------------|")
    for stage in all_stages:
        count = stage_counts.get(stage, 0)
        bar = "█" * count + "░" * max(0, 5 - count)
        lines.append(f"| `{stage}` | {bar} ({count}) |")

    lines += [
        "",
        "---",
        "## 📚 Top Discovered Repos",
        "",
    ]

    for d in sorted(discovered, key=lambda x: x.get("stars", 0), reverse=True)[:15]:
        stages_str = ", ".join(f"`{s}`" for s in d.get("pipeline_stages", [])) or "—"
        llm_str = ", ".join(f"`{p}`" for p in d.get("llm_patterns", [])[:6]) or "—"
        trading_str = ", ".join(f"`{p}`" for p in d.get("trading_patterns", [])[:4]) or "—"
        lines += [
            f"### [{d['name']}]({d['url']}) ★ {d.get('stars', 0):,}",
            f"> {d.get('description', '')[:150]}",
            f"- **Pipeline stages:** {stages_str}",
            f"- **LLM patterns:** {llm_str}",
            f"- **Trading patterns:** {trading_str}",
            f"- **Language:** `{d.get('language', '?')}`",
            "",
        ]

    lines += [
        "---",
        generate_gap_report(discovered),
        "",
        "---",
        "## 🚀 Actionable Architecture Upgrades for Niblit",
        "",
        "Based on the patterns observed in the top LLM and trading AI repositories,",
        "here are the highest-priority improvements for Niblit:",
        "",
        "### 1. Activate Local Fine-Tuning (LoRA/QLoRA)",
        "Set `LOCAL_MODEL_PATH` in `.env` to a small model (e.g. `Qwen/Qwen2.5-0.5B-Instruct`).",
        "ALE Step 32 (LLMArchitectCycle) will automatically run LoRA SFT via `trl` + `peft`",
        "on every 10th cycle using Niblit's own KB as training data.",
        "",
        "**Dependencies to install:**",
        "```bash",
        "pip install trl peft bitsandbytes accelerate datasets transformers",
        "```",
        "",
        "### 2. Add Temporal Fusion Transformer to TradingBrain",
        "Wire `pytorch-forecasting` TFT as a second-opinion signal in",
        "`TradingBrain.decide_action()` alongside the existing PPO/DQN policy.",
        "The TFT predicts multi-horizon price quantiles; the RL policy learns",
        "execution timing from those predictions.",
        "",
        "**Dependencies to install:**",
        "```bash",
        "pip install pytorch-forecasting pytorch-lightning",
        "```",
        "",
        "### 3. Add Kelly Criterion Position Sizing",
        "Create `modules/position_sizer.py` implementing Kelly + fractional Kelly.",
        "Wire into `TradingBrain.cycle()` to replace the fixed position size.",
        "",
        "### 4. Train a Domain-Specific Tokenizer",
        "Run `sentencepiece.SentencePieceTrainer.train()` on Niblit's KB JSONL export",
        "to build a vocabulary tuned to AI / trading text.  Store in `niblit_tokenizer/`.",
        "",
        "### 5. Add lm-eval-harness Evaluation Pass",
        "Add an ALE step that runs `lm_eval` on Niblit's local model checkpoint after",
        "each LoRA fine-tune, storing MMLU / HellaSwag scores in the KB for tracking.",
        "",
        "---",
        f"<!-- knowledge-layer repos={len(knowledge.get('studied_repos', set()))} -->",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Issue management
# ---------------------------------------------------------------------------
def _find_existing_issue() -> Optional[int]:
    data = _get(
        f"{GITHUB_API}/repos/{REPO}/issues",
        params={"labels": ISSUE_LABEL, "state": "open", "per_page": "5"},
    )
    if not isinstance(data, list):
        return None
    for issue in data:
        if issue.get("title", "").startswith(ISSUE_TITLE_PREFIX):
            return issue["number"]
    return None


def _post_issue(title: str, body: str) -> None:
    payload = json.dumps({
        "title": title,
        "body": body,
        "labels": [ISSUE_LABEL],
    }).encode()
    req = Request(
        f"{GITHUB_API}/repos/{REPO}/issues",
        data=payload,
        headers={**_headers(), "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=30) as resp:
            info = json.loads(resp.read().decode())
            print(f"✅ Created issue #{info.get('number')}: {info.get('html_url')}")
    except Exception as exc:
        print(f"❌ Failed to create issue: {exc}", file=sys.stderr)


def _patch_issue(number: int, title: str, body: str) -> None:
    payload = json.dumps({"title": title, "body": body}).encode()
    req = Request(
        f"{GITHUB_API}/repos/{REPO}/issues/{number}",
        data=payload,
        headers={**_headers(), "Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urlopen(req, timeout=30) as resp:
            info = json.loads(resp.read().decode())
            print(f"✅ Updated issue #{info.get('number')}: {info.get('html_url')}")
    except Exception as exc:
        print(f"❌ Failed to update issue: {exc}", file=sys.stderr)


def ensure_label() -> None:
    req = Request(
        f"{GITHUB_API}/repos/{REPO}/labels",
        data=json.dumps({"name": ISSUE_LABEL, "color": "7057ff", "description": "Nibblebot LLM Engineering Research"}).encode(),
        headers={**_headers(), "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=20):
            pass
    except HTTPError as exc:
        if exc.code != 422:  # 422 = already exists
            print(f"  [WARN] Label create: {exc}", file=sys.stderr)
    except Exception as exc:
        print(f"  [WARN] Label check: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    run_ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    print(f"🤖 Nibblebot LLM Engineer Bot — {run_ts}")
    print(f"   Repo: {REPO}  |  Topics: {len(TOPICS)}  |  Max repos/topic: {MAX_REPOS}")

    if not TOKEN and not DRY_RUN:
        print("❌ GITHUB_TOKEN not set. Set it or use LLM_ENG_DRY_RUN=true.", file=sys.stderr)
        sys.exit(1)

    # Phase 1 — Knowledge layer
    print("\n📚 Phase 1: Loading knowledge layer …")
    knowledge = load_knowledge_layer()
    print(f"   Already studied: {len(knowledge['studied_repos'])} repos")

    # Phase 2 & 3 — Research
    print(f"\n🔬 Phase 2-3: Researching {len(TOPICS)} topics …")
    discovered: List[Dict[str, Any]] = []
    studied: Set[str] = set()

    for topic in TOPICS:
        print(f"  Topic: {topic}")
        repos = search_repos(topic, MAX_REPOS)
        time.sleep(1)

        for repo in repos:
            name = repo.get("full_name", "")
            if name in studied or name in knowledge["studied_repos"]:
                continue
            studied.add(name)

            readme = fetch_readme(name)
            tree = fetch_repo_tree(name) if DEEP_DIVE else []
            time.sleep(0.5)

            analysis = analyse_repo(repo, readme, tree)
            if analysis["llm_patterns"] or analysis["trading_patterns"] or analysis["pipeline_stages"]:
                discovered.append(analysis)
                print(f"    ✓ {name} ★{repo.get('stargazers_count', 0):,} — stages: {analysis['pipeline_stages']}")

    print(f"\n   Discovered {len(discovered)} relevant repos")

    # Phase 4 — Gap analysis
    print("\n📊 Phase 4: Running gap analysis …")
    gap_report = generate_gap_report(discovered)

    # Phase 5 — Synthesis and report
    print("\n📝 Phase 5: Building report …")
    body = build_report(discovered, knowledge, run_ts)

    run_date = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    title = f"{ISSUE_TITLE_PREFIX}: {run_date}"

    # Phase 6 — Publish
    print("\n📢 Phase 6: Publishing issue …")
    if DRY_RUN:
        print("\n" + "=" * 80)
        print(f"DRY RUN — Issue title: {title}")
        print("=" * 80)
        print(body[:3000])
        return

    ensure_label()
    existing = _find_existing_issue()
    if existing:
        print(f"  Updating existing issue #{existing} …")
        _patch_issue(existing, title, body)
    else:
        print("  Creating new issue …")
        _post_issue(title, body)

    print("\n✅ Nibblebot LLM Engineer Bot finished.")


if __name__ == "__main__":
    main()
