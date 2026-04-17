#!/usr/bin/env python3
"""Runtime verifier for Niblit's local GGUF model (QwenLocalBrain).

By default, checks whether the GGUF model file and inference binary are in
place and prints a pass/fail status.  Use ``--setup`` to print one-time
download/build instructions.

This script is safe to call at Niblit startup or from CI — it never
downloads anything automatically.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Default GGUF download URL — pre-quantized Q4_K_M from official Qwen repo.
# ~390 MB, stable on Termux/mobile.
_DEFAULT_GGUF_URL = (
    "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/"
    "qwen2.5-0.5b-instruct-q4_k_m.gguf"
)
_DEFAULT_GGUF_FILENAME = "qwen2.5-0.5b-instruct-q4_k_m.gguf"
_DEFAULT_GGUF_DIR = "~/models"
_DEFAULT_GGUF_DEST = f"{_DEFAULT_GGUF_DIR}/{_DEFAULT_GGUF_FILENAME}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify GGUF model installation for Niblit local brain.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples
--------
# Verify model is in place (default — no network access):
  python tools/install_local_qwen_model.py

# Show one-time download/build instructions:
  python tools/install_local_qwen_model.py --setup

# Verify a specific GGUF file path:
  python tools/install_local_qwen_model.py \\
    --gguf-path ~/models/qwen2.5-0.5b-instruct-q4_k_m.gguf
""",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get(
            "NIBLIT_LOCAL_MODEL", "~/models/qwen2.5-0.5b-instruct-q4_k_m.gguf"
        ),
        help="HuggingFace model id or path to .gguf file (used for cache lookup).",
    )
    parser.add_argument(
        "--gguf-path",
        default=os.environ.get("NIBLIT_GGUF_MODEL_PATH", ""),
        help="Explicit path to a local .gguf file (sets NIBLIT_GGUF_MODEL_PATH).",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Print one-time download and build instructions, then exit.",
    )
    return parser.parse_args()


def _print_status(status: dict, header: str) -> None:
    print(header)
    print(f"  model:             {status.get('model_name', 'unknown')}")
    print(f"  backend_in_use:    {status.get('backend_in_use', 'none')}")
    print(f"  loaded:            {status.get('loaded', False)}")
    print(f"  installed_locally: {status.get('installed_locally', False)}")
    if status.get("gguf_model_path"):
        print(f"  gguf_path:         {status['gguf_model_path']}")
    if status.get("llama_binary"):
        print(f"  llama_binary:      {status['llama_binary']}")
    files = status.get("model_files", []) or []
    if files:
        print("  model files:")
        for f in files:
            print(f"    - {f}")


def _show_setup_instructions(gguf_path: str) -> None:
    """Print one-time setup instructions for the GGUF model and llama.cpp."""
    dest = gguf_path or _DEFAULT_GGUF_DEST
    dest_dir = str(Path(dest).expanduser().parent).replace(str(Path.home()), "~")
    print()
    print("=" * 60)
    print("  One-time setup: GGUF model + llama.cpp binary")
    print("=" * 60)
    print()
    print("── Step 1: Download the model (~390 MB) ────────────────────")
    print()
    print(f"  mkdir -p {dest_dir}")
    print(f"  wget -O {dest} \\")
    print(f"    {_DEFAULT_GGUF_URL}")
    print()
    print("  Or with curl:")
    print()
    print(f"  curl -L -o {dest} \\")
    print(f"    {_DEFAULT_GGUF_URL}")
    print()
    print("── Step 2: Build llama.cpp (Termux / Linux) ─────────────────")
    print()
    print("  pkg install git cmake clang make   # Termux")
    print("  # or: apt install git cmake clang make  # Debian/Ubuntu")
    print("  git clone https://github.com/ggerganov/llama.cpp ~/llama.cpp")
    print("  cd ~/llama.cpp && make -j1")
    print()
    print("── Step 3: Add to ~/.bashrc or .env ─────────────────────────")
    print()
    print(f"  export NIBLIT_GGUF_MODEL_PATH={dest}")
    print("  export NIBLIT_GGUF_BACKEND=subprocess")
    print("  export NIBLIT_LLAMA_BINARY=~/llama.cpp/llama-cli")
    print()
    print("── Step 4: Verify ───────────────────────────────────────────")
    print()
    print("  python tools/install_local_qwen_model.py")
    print()
    print("=" * 60)
    print()


def main() -> int:
    args = _parse_args()

    if args.setup:
        _show_setup_instructions(args.gguf_path)
        return 0

    # Set env vars so QwenLocalBrain picks up the explicit path.
    os.environ["NIBLIT_LOCAL_MODEL"] = args.model
    if args.gguf_path:
        os.environ["NIBLIT_GGUF_MODEL_PATH"] = args.gguf_path

    from modules.local_brain import QwenLocalBrain

    brain = QwenLocalBrain(
        model_name=args.model,
        gguf_model_path=args.gguf_path,
    )
    status = brain.status()
    _print_status(status, "== Local brain status ==")

    if status.get("installed_locally"):
        print("\n✅ GGUF model file found.")
    else:
        print(
            "\n❌ GGUF model file not found. "
            "Run with --setup for download/build instructions."
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
