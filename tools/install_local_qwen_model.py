#!/usr/bin/env python3
"""Standalone local-model installer/validator for Qwen2.5-0.5B-Instruct.

This script pre-downloads model files into the same HuggingFace cache path used
by modules.local_brain.QwenLocalBrain so runtime startup does not need to
download the model.
"""

from __future__ import annotations

import argparse
import os
import sys


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install/verify local Qwen model cache for Niblit.")
    parser.add_argument(
        "--model",
        default=os.environ.get("NIBLIT_LOCAL_MODEL", "Qwen/Qwen2.5-0.5B-Instruct"),
        help="HuggingFace model id to install (default: Qwen/Qwen2.5-0.5B-Instruct).",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify existing local installation (do not trigger download/load).",
    )
    return parser.parse_args()


def _print_status(status: dict, header: str) -> None:
    print(header)
    print(f"- model: {status.get('model_name', 'unknown')}")
    print(f"- hub cache: {status.get('hub_cache_dir', 'unknown')}")
    print(f"- repo cache: {status.get('repo_cache_dir', 'unknown')}")
    print(f"- installed_locally: {status.get('installed_locally', False)}")
    files = status.get("model_files", []) or []
    if files:
        print("- model files:")
        for f in files:
            print(f"  - {f}")


def main() -> int:
    args = _parse_args()
    os.environ["NIBLIT_LOCAL_MODEL"] = args.model

    from modules.local_brain import QwenLocalBrain

    brain = QwenLocalBrain(model_name=args.model)
    before = brain.status()
    _print_status(before, "== Pre-check ==")

    if args.verify_only:
        if before.get("installed_locally"):
            print("✅ Local model installation verified.")
            return 0
        print("❌ Local model not installed.")
        return 1

    if not before.get("installed_locally"):
        print("Downloading/loading local model via current Niblit LocalBrain logic...")
    else:
        print("Local model files already found; validating load path...")

    if not brain.ensure_loaded():
        print(f"❌ Failed to load model: {brain.load_error() or 'unknown error'}")
        return 1

    after = brain.status()
    _print_status(after, "== Post-check ==")

    if after.get("installed_locally") and after.get("loaded"):
        print(
            "✅ Qwen local model installed and loadable. "
            "Use NIBLIT_LLM_PROVIDER=qwen (or `llm-provider qwen`) to make it active."
        )
        return 0

    print("❌ Local model check failed after installation attempt.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
