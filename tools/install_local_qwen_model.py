#!/usr/bin/env python3
"""Standalone local-model installer/validator for Niblit's local brain.

Prints ready-to-use ``wget`` / ``curl`` download commands for a
pre-quantized GGUF ``.gguf`` file and verifies an existing download when
``--gguf-path`` is provided.

This script uses the same paths as ``modules.local_brain.QwenLocalBrain``
so runtime startup does not need network access once the file is present.
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
        description="Install/verify GGUF model for Niblit local brain.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples
--------
# Show download instructions:
  python tools/install_local_qwen_model.py

# Verify an already-downloaded GGUF file:
  python tools/install_local_qwen_model.py \\
    --gguf-path ~/models/qwen2.5-0.5b-instruct-q4_k_m.gguf --verify-only
""",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("NIBLIT_LOCAL_MODEL", "Qwen/Qwen2.5-0.5B-Instruct"),
        help="HuggingFace model id or path to .gguf file (used for cache lookup).",
    )
    parser.add_argument(
        "--gguf-path",
        default=os.environ.get("NIBLIT_GGUF_MODEL_PATH", ""),
        help="Explicit path to a local .gguf file (sets NIBLIT_GGUF_MODEL_PATH).",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify existing local installation; do not show download instructions.",
    )
    return parser.parse_args()


def _print_status(status: dict, header: str) -> None:
    print(header)
    print(f"  model:             {status.get('model_name', 'unknown')}")
    print(f"  loaded:            {status.get('loaded', False)}")
    print(f"  installed_locally: {status.get('installed_locally', False)}")
    if status.get("gguf_model_path"):
        print(f"  gguf_path:         {status['gguf_model_path']}")
    files = status.get("model_files", []) or []
    if files:
        print("  model files:")
        for f in files:
            print(f"    - {f}")


def _show_gguf_instructions(gguf_path: str) -> None:
    """Print actionable download instructions for the GGUF model."""
    dest = gguf_path or _DEFAULT_GGUF_DEST
    dest_dir = str(Path(dest).expanduser().parent).replace(str(Path.home()), "~")
    print()
    print("=" * 60)
    print("  GGUF model setup for Niblit (Termux / mobile / desktop)")
    print("=" * 60)
    print()
    print("1. Create the models directory:")
    print()
    print(f"     mkdir -p {dest_dir}")
    print()
    print("2. Download the pre-quantized model (~390 MB):")
    print()
    print(f"     wget -O {dest} \\")
    print(f"       {_DEFAULT_GGUF_URL}")
    print()
    print("   Or with curl:")
    print()
    print(f"     curl -L -o {dest} \\")
    print(f"       {_DEFAULT_GGUF_URL}")
    print()
    print("3. Set environment variables (add to ~/.bashrc or .env):")
    print()
    print(f"     export NIBLIT_GGUF_MODEL_PATH={dest}")
    print()
    print("4. Inference backend — choose ONE:")
    print()
    print("   ── Option A: llama-cpp-python (desktop / server) ──")
    print()
    print("     pip install llama-cpp-python")
    print()
    print("   ── Option B: llama.cpp binary  ← RECOMMENDED for Termux ──")
    print("      (no C++ compilation inside Python, uses ~300 MB RAM to build)")
    print()
    print("     pkg install git cmake clang make")
    print("     git clone https://github.com/ggerganov/llama.cpp ~/llama.cpp")
    print("     cd ~/llama.cpp && make -j1")
    print()
    print("     export NIBLIT_GGUF_BACKEND=subprocess")
    print("     export NIBLIT_LLAMA_BINARY=~/llama.cpp/llama-cli")
    print()
    print("     # (add both exports to ~/.bashrc or .env)")
    print()
    print("5. Verify:")
    print()
    print(f"     python tools/install_local_qwen_model.py \\")
    print(f"       --gguf-path {dest} --verify-only")
    print()
    print("=" * 60)
    print()


def main() -> int:
    args = _parse_args()
    os.environ["NIBLIT_LOCAL_MODEL"] = args.model
    if args.gguf_path:
        os.environ["NIBLIT_GGUF_MODEL_PATH"] = args.gguf_path

    from modules.local_brain import QwenLocalBrain

    if not args.verify_only:
        _show_gguf_instructions(args.gguf_path)

    brain = QwenLocalBrain(
        model_name=args.model,
        gguf_model_path=args.gguf_path,
    )
    before = brain.status()
    _print_status(before, "== Pre-check ==")

    if args.verify_only:
        if before.get("installed_locally"):
            print("\n✅ GGUF model installation verified.")
            return 0
        print(
            "\n❌ GGUF model file not found. "
            "Download it and set NIBLIT_GGUF_MODEL_PATH, then re-run."
        )
        return 1

    if not before.get("installed_locally"):
        print(
            "❌ GGUF model file not found. "
            "Download it using the instructions above, then re-run with --verify-only."
        )
        return 1

    print("GGUF file found; validating load…")

    if not brain.ensure_loaded():
        print(f"❌ Failed to load model: {brain.load_error() or 'unknown error'}")
        return 1

    after = brain.status()
    _print_status(after, "== Post-check ==")

    if after.get("installed_locally") and after.get("loaded"):
        print(
            "✅ GGUF model installed and loadable. "
            "Set NIBLIT_GGUF_MODEL_PATH to make it active."
        )
        return 0

    print("❌ Local model check failed after installation attempt.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
