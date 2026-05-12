#!/usr/bin/env python3
"""Portable local GGUF runtime validator (Qwen/Llama/Gemma/generic).

Backwards-compatible entrypoint name retained: tools/install_local_qwen_model.py
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import request

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.lib.runtime_profiles import apply_profile

DEFAULT_MODELS = {
    "qwen": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
    "llama": "Llama-3.2-1B-Instruct-Q4_K_M.gguf",
    "gemma": "gemma-2b-it-q4_k_m.gguf",
}

TERMUX_HOME = "/data/data/com.termux/files/home"
DEFAULT_GGUF_DIRS = [
    Path(os.environ.get("NIBLIT_MODEL_DIR", "")).expanduser() if os.environ.get("NIBLIT_MODEL_DIR") else None,
    Path.home() / "models",
    Path(f"{TERMUX_HOME}/models"),
    Path("/data"),
]


@dataclass
class VerificationResult:
    name: str
    ok: bool
    details: dict[str, Any]


def detect_platform() -> dict[str, Any]:
    system = platform.system().lower()
    release = platform.release().lower()
    in_container = Path("/.dockerenv").exists() or "container" in Path("/proc/1/cgroup").read_text(errors="ignore") if Path("/proc/1/cgroup").exists() else False
    is_termux = "com.termux" in os.environ.get("PREFIX", "") or Path(f"{TERMUX_HOME}/usr/bin").exists()
    return {
        "system": system,
        "release": release,
        "termux": bool(is_termux),
        "container": bool(in_container),
        "machine": platform.machine().lower(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate local GGUF runtime setup for Niblit")
    parser.add_argument("--profile", default="niblit", help="Runtime profile name")
    parser.add_argument("--model-family", default="qwen", choices=["qwen", "llama", "gemma", "generic"], help="Model family")
    parser.add_argument("--model", default=os.environ.get("NIBLIT_LOCAL_MODEL", ""), help="Model id or model filename hint")
    parser.add_argument("--gguf-path", default=os.environ.get("NIBLIT_GGUF_MODEL_PATH", ""), help="Explicit GGUF file path")
    parser.add_argument("--llama-binary", default=os.environ.get("NIBLIT_LLAMA_BINARY", ""), help="Path to llama binary (llama-server/llama-cli)")
    parser.add_argument("--server-url", default=os.environ.get("NIBLIT_LLAMA_SERVER_URL", "http://127.0.0.1:8080"), help="HTTP inference URL")

    parser.add_argument("--verify", nargs="+", default=["filesystem"], choices=["filesystem", "llama-binary", "http", "local-brain"], help="Verification modes")
    parser.add_argument("--setup", action="store_true", help="Print setup instructions")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    return parser.parse_args()


def find_gguf_path(explicit: str, model_family: str, model_hint: str) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        if path.is_file():
            return path

    candidates: list[str] = []
    if model_hint and model_hint.endswith(".gguf"):
        candidates.append(Path(model_hint).name)
    if model_family in DEFAULT_MODELS:
        candidates.append(DEFAULT_MODELS[model_family])

    for directory in [d for d in DEFAULT_GGUF_DIRS if d is not None]:
        if not directory.exists():
            continue
        for name in candidates:
            p = directory / name
            if p.is_file():
                return p
        for p in directory.glob("*.gguf"):
            if p.is_file():
                return p
    return None


def verify_filesystem(args: argparse.Namespace, gguf_path: Path | None) -> VerificationResult:
    ok = gguf_path is not None and gguf_path.exists()
    details = {
        "gguf_path": str(gguf_path) if gguf_path else "",
        "exists": bool(ok),
    }
    if ok:
        details["size_mb"] = round(gguf_path.stat().st_size / (1024 * 1024), 2)
    return VerificationResult("filesystem", ok, details)


def verify_llama_binary(path_str: str) -> VerificationResult:
    path = Path(path_str).expanduser() if path_str else None
    if path and path.exists() and os.access(path, os.X_OK):
        try:
            proc = subprocess.run([str(path), "--version"], capture_output=True, text=True, timeout=8)
            out = (proc.stdout or proc.stderr or "").strip().splitlines()[:2]
            return VerificationResult("llama-binary", True, {"binary": str(path), "version": out})
        except Exception as exc:  # noqa: BLE001
            return VerificationResult("llama-binary", False, {"binary": str(path), "error": str(exc)})

    resolved = shutil.which("llama-server") or shutil.which("llama-cli")
    if resolved:
        return verify_llama_binary(resolved)
    return VerificationResult("llama-binary", False, {"binary": path_str or "", "error": "No llama binary found"})


def verify_http(url: str) -> VerificationResult:
    base = url.rstrip("/")
    probes = ["/health", "/v1/models", "/props", "/"]
    for endpoint in probes:
        target = f"{base}{endpoint}"
        try:
            with request.urlopen(target, timeout=4) as resp:  # noqa: S310
                return VerificationResult("http", True, {"url": target, "status": getattr(resp, "status", 200)})
        except Exception:
            continue
    return VerificationResult("http", False, {"url": base, "error": "No probe endpoint responded"})


def verify_local_brain(args: argparse.Namespace, gguf_path: Path | None) -> VerificationResult:
    try:
        from modules.local_brain import QwenLocalBrain  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return VerificationResult("local-brain", False, {"error": f"local_brain import unavailable: {exc}"})

    try:
        brain = QwenLocalBrain(model_name=args.model or args.model_family, gguf_model_path=str(gguf_path or ""))
        status = brain.status()
        return VerificationResult("local-brain", bool(status.get("installed_locally")), status)
    except Exception as exc:  # noqa: BLE001
        return VerificationResult("local-brain", False, {"error": str(exc)})


def runtime_recommendations(plat: dict[str, Any]) -> list[str]:
    recs: list[str] = []
    cpu_count = os.cpu_count() or 1

    mem_gb = None
    if hasattr(os, "sysconf") and "SC_PAGE_SIZE" in os.sysconf_names and "SC_PHYS_PAGES" in os.sysconf_names:
        try:
            mem_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
            mem_gb = mem_bytes / (1024**3)
        except Exception:  # noqa: BLE001
            mem_gb = None

    if mem_gb is not None:
        if mem_gb < 4:
            recs.append("Use <=2k context (NIBLIT_GGUF_N_CTX=2048) and small Q4 model.")
        elif mem_gb < 8:
            recs.append("Use 2k-4k context and keep threads moderate for thermal stability.")
        else:
            recs.append("4k-8k context feasible; tune threads to avoid sustained thermal throttling.")

    if cpu_count <= 4:
        recs.append("Set NIBLIT_GGUF_N_THREADS to 2-4.")
    else:
        recs.append(f"Start with NIBLIT_GGUF_N_THREADS={min(8, cpu_count)} and adjust for battery/latency.")

    if plat.get("termux"):
        recs.append("Termux: use termux-wake-lock and prefer two-session mode for long runs.")
    if plat.get("container"):
        recs.append("Container/Fly: prefer HTTP backend + external/local sidecar bridge.")
    if plat.get("system") == "darwin":
        recs.append("macOS: use arm64-native llama builds on Apple Silicon when available.")

    battery_status = Path("/sys/class/power_supply/BAT0/status")
    if battery_status.exists():
        status = battery_status.read_text(errors="ignore").strip().lower()
        if status and status != "charging":
            recs.append("Battery not charging: reduce context/threads to limit thermal/battery pressure.")

    return recs


def setup_instructions(args: argparse.Namespace, plat: dict[str, Any]) -> str:
    fam = args.model_family
    default_name = DEFAULT_MODELS.get(fam, "model.gguf")
    destination = Path(args.gguf_path).expanduser() if args.gguf_path else Path.home() / "models" / default_name

    lines = [
        "== One-time setup ==",
        f"Model family: {fam}",
        f"Suggested destination: {destination}",
        "",
        "1) Create model directory:",
        f"   mkdir -p {destination.parent}",
        "2) Download a GGUF model (Qwen/Llama/Gemma/generic):",
        f"   wget -O {destination} <GGUF_URL>",
        "3) Build/install llama.cpp and ensure llama-server or llama-cli is available.",
        "4) Verify filesystem + binary + HTTP setup:",
        f"   python {Path(__file__).name} --verify filesystem llama-binary http --gguf-path {destination}",
    ]

    if plat.get("termux"):
        lines.extend(
            [
                "",
                "Termux workflow:",
                "- Run llama-server in normal Termux session.",
                "- Run Niblit in proot session with NIBLIT_GGUF_BACKEND=http and NIBLIT_LLAMA_SERVER_URL set.",
            ]
        )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    apply_profile(args.profile)

    plat = detect_platform()
    gguf = find_gguf_path(args.gguf_path, args.model_family, args.model)

    if args.setup:
        text = setup_instructions(args, plat)
        if args.json:
            print(json.dumps({"setup": text, "platform": plat}, indent=2))
        else:
            print(text)
        return 0

    checks: list[VerificationResult] = []
    for mode in args.verify:
        if mode == "filesystem":
            checks.append(verify_filesystem(args, gguf))
        elif mode == "llama-binary":
            checks.append(verify_llama_binary(args.llama_binary))
        elif mode == "http":
            checks.append(verify_http(args.server_url))
        elif mode == "local-brain":
            checks.append(verify_local_brain(args, gguf))

    recommendations = runtime_recommendations(plat)
    payload = {
        "profile": args.profile,
        "model_family": args.model_family,
        "model": args.model,
        "platform": plat,
        "checks": [
            {"name": c.name, "ok": c.ok, "details": c.details} for c in checks
        ],
        "recommendations": recommendations,
    }

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("== Local runtime verification ==")
        print(f"profile:      {payload['profile']}")
        print(f"model_family: {payload['model_family']}")
        print(f"platform:     {plat['system']} ({plat['machine']}) termux={plat['termux']} container={plat['container']}")
        for c in checks:
            state = "✅" if c.ok else "❌"
            print(f"{state} {c.name}")
            for k, v in c.details.items():
                print(f"    {k}: {v}")
        if recommendations:
            print("\nRecommendations:")
            for rec in recommendations:
                print(f" - {rec}")

    ok = all(c.ok for c in checks) if checks else False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
