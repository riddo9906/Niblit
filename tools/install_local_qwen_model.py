#!/usr/bin/env python3
"""Standalone local-model installer/validator for Niblit's local brain.

Supports both backends:

* **safetensors** (default, desktop): Downloads and verifies the
  HuggingFace safetensors model into the HuggingFace cache.

* **gguf** (recommended for Termux / Android): Prints a ready-to-use
  ``wget`` / ``curl`` download command for a pre-quantized ``.gguf`` file
  and verifies an existing download when ``--gguf-path`` is provided.

This script pre-downloads model files into the same paths used by
``modules.local_brain.QwenLocalBrain`` so runtime startup does not need
to download the model.
"""

from __future__ import annotations

import argparse
import os
import sys

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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install/verify local Qwen model cache for Niblit.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples
--------
# Verify safetensors cache (desktop / server):
  python tools/install_local_qwen_model.py --verify-only

# Show GGUF download instructions (Termux / mobile):
  python tools/install_local_qwen_model.py --format gguf

# Verify an already-downloaded GGUF file:
  python tools/install_local_qwen_model.py --format gguf \\
    --gguf-path ~/models/qwen2.5-0.5b-instruct-q4_k_m.gguf --verify-only
""",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("NIBLIT_LOCAL_MODEL", "Qwen/Qwen2.5-0.5B-Instruct"),
        help="HuggingFace model id (safetensors) or path to .gguf file.",
    )
    parser.add_argument(
        "--format",
        choices=["auto", "gguf", "safetensors"],
        default=os.environ.get("NIBLIT_LOCAL_MODEL_FORMAT", "auto"),
        help=(
            "Backend format. 'gguf' is recommended for Termux/mobile (lighter, ~390 MB). "
            "'safetensors' is the default desktop format (~2 GB RAM). "
            "Default: auto (detected from model path / env vars)."
        ),
    )
    parser.add_argument(
        "--gguf-path",
        default=os.environ.get("NIBLIT_GGUF_MODEL_PATH", ""),
        help="Explicit path to a local .gguf file (sets NIBLIT_GGUF_MODEL_PATH).",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify existing local installation; do not download or load.",
    )
    return parser.parse_args()


def _print_status(status: dict, header: str) -> None:
    print(header)
    print(f"  model:            {status.get('model_name', 'unknown')}")
    print(f"  format:           {status.get('model_format', 'unknown')}")
    print(f"  loaded:           {status.get('loaded', False)}")
    print(f"  installed_locally: {status.get('installed_locally', False)}")
    print(f"  hub cache:        {status.get('hub_cache_dir', 'unknown')}")
    if status.get('gguf_model_path'):
        print(f"  gguf_path:        {status['gguf_model_path']}")
    files = status.get("model_files", []) or []
    if files:
        print("  model files:")
        for f in files:
            print(f"    - {f}")


def _show_gguf_instructions(gguf_path: str) -> None:
    """Print actionable download instructions for the GGUF model."""
    dest = gguf_path or f"~/{_DEFAULT_GGUF_FILENAME}"
    print()
    print("=" * 60)
    print("  GGUF model setup (recommended for Termux / mobile)")
    print("=" * 60)
    print()
    print("1. Download the pre-quantized model (~390 MB):")
    print()
    print(f"     wget -O {dest} \\")
    print(f"       {_DEFAULT_GGUF_URL}")
    print()
    print("   Or with curl:")
    print()
    print(f"     curl -L -o {dest} \\")
    print(f"       {_DEFAULT_GGUF_URL}")
    print()
    print("2. Set environment variables (add to ~/.bashrc or .env):")
    print()
    print(f"     export NIBLIT_GGUF_MODEL_PATH={dest}")
    print("     export NIBLIT_LOCAL_MODEL_FORMAT=gguf")
    print()
    print("3. Install llama-cpp-python (if not already installed):")
    print()
    print("     pip install llama-cpp-python")
    print()
    print("   On Termux:")
    print()
    print("     pip install llama-cpp-python --extra-index-url \\")
    print("       https://abetlen.github.io/llama-cpp-python/whl/cpu")
    print()
    print("4. Verify:")
    print()
    print(f"     python tools/install_local_qwen_model.py --format gguf \\")
    print(f"       --gguf-path {dest} --verify-only")
    print()
    print("Why GGUF instead of safetensors?")
    print("  safetensors: ~2 GB RAM spike → crashes on Termux")
    print("  GGUF q4_K_M: ~390 MB, no PyTorch, stable on mobile CPU")
    print("=" * 60)
    print()


def main() -> int:
    args = _parse_args()
    os.environ["NIBLIT_LOCAL_MODEL"] = args.model
    if args.gguf_path:
        os.environ["NIBLIT_GGUF_MODEL_PATH"] = args.gguf_path
    if args.format != "auto":
        os.environ["NIBLIT_LOCAL_MODEL_FORMAT"] = args.format

    from modules.local_brain import QwenLocalBrain, _resolve_model_format

    effective_format = _resolve_model_format(args.model, args.gguf_path, args.format)

    # For GGUF without a path, always show download instructions first.
    if effective_format == "gguf" and not args.verify_only:
        _show_gguf_instructions(args.gguf_path)

    brain = QwenLocalBrain(
        model_name=args.model,
        gguf_model_path=args.gguf_path,
        model_format=args.format,
    )
    before = brain.status()
    _print_status(before, "== Pre-check ==")

    if args.verify_only:
        if before.get("installed_locally"):
            print("\n✅ Local model installation verified.")
            return 0
        fmt_hint = (
            f"Set NIBLIT_GGUF_MODEL_PATH and download the file shown above."
            if effective_format == "gguf"
            else "Run without --verify-only to trigger download."
        )
        print(f"\n❌ Local model not installed. {fmt_hint}")
        return 1

    if effective_format == "gguf":
        if not before.get("installed_locally"):
            print(
                "❌ GGUF model file not found. "
                "Download it using the instructions above, then re-run with --verify-only."
            )
            return 1
        print("GGUF file found; validating load…")
    else:
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
        if effective_format == "gguf":
            print(
                "✅ GGUF model installed and loadable. "
                "Set NIBLIT_LOCAL_MODEL_FORMAT=gguf and NIBLIT_GGUF_MODEL_PATH "
                "to make it active."
            )
        else:
            print(
                "✅ Qwen local model installed and loadable. "
                "Use NIBLIT_LLM_PROVIDER=qwen (or `llm-provider qwen`) to make it active."
            )
        return 0

    print("❌ Local model check failed after installation attempt.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
