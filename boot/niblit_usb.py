#!/usr/bin/env python3
"""
boot/niblit_usb.py — Niblit Bootable USB Creator
=================================================
Creates a bootable USB drive (or directory image) that contains a minimal
Linux environment + Niblit, capable of booting on any PC/laptop and launching
Niblit as the primary interactive layer on top of the host hardware.

Strategy
--------
This script takes a pragmatic approach that works on any host OS:

1. **Linux host with `dd` / `debootstrap`** — builds a minimal Debian chroot,
   installs Python + Niblit, then writes a GRUB/syslinux bootloader and packs
   everything into an ISO image, which can then be `dd`d to a USB stick.

2. **Any host without root** — generates a ready-to-use shell script + config
   bundle that the user can run on a Linux machine to finish the USB creation.

The resulting system boots to a minimal Linux shell that immediately starts
Niblit in service mode via the systemd unit (boot/niblit@.service).

Usage
-----
    python boot/niblit_usb.py --help
    python boot/niblit_usb.py --out /tmp/niblit.iso    # build ISO (needs root on Linux)
    python boot/niblit_usb.py --out /dev/sdb --write   # write directly to USB (DESTRUCTIVE)
    python boot/niblit_usb.py --bundle /tmp/niblit_usb_bundle  # generate config bundle only
"""

from __future__ import annotations

import argparse
import logging
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import textwrap
from pathlib import Path

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

NIBLIT_ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list, check: bool = True, **kw) -> subprocess.CompletedProcess:
    log.info("$ %s", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, check=check, **kw)


# ─────────────────────────────────────────────────────────────────────────────
# Bundle generator (works on any host, no root needed)
# ─────────────────────────────────────────────────────────────────────────────

def generate_bundle(out_dir: Path) -> None:
    """
    Generate a self-contained bundle that a Linux machine can use to build a
    Niblit USB stick.  No root required on the current host.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Copy the Niblit project (excluding .git and __pycache__)
    niblit_copy = out_dir / "niblit"
    if niblit_copy.exists():
        shutil.rmtree(niblit_copy)
    log.info("Copying Niblit project → %s", niblit_copy)
    shutil.copytree(
        NIBLIT_ROOT,
        niblit_copy,
        ignore=shutil.ignore_patterns(
            ".git", "__pycache__", "*.pyc", "*.pyo",
            "niblit_memory.db", "niblit.db",
            "ale_python_*",
        ),
    )

    # 2. Write the USB builder script
    builder = out_dir / "build_usb.sh"
    builder.write_text(textwrap.dedent(r"""
        #!/usr/bin/env bash
        # Niblit USB Builder — run as root on a Linux machine
        # Usage:  sudo bash build_usb.sh [/dev/sdX]
        set -euo pipefail
        BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        TARGET="${1:-}"

        err() { echo "ERROR: $*" >&2; exit 1; }
        need() { command -v "$1" &>/dev/null || err "Please install: $1"; }

        [[ "$(id -u)" -eq 0 ]] || err "Run as root: sudo bash build_usb.sh"
        need debootstrap
        need grub-mkrescue
        need xorriso

        WORKDIR="$(mktemp -d /tmp/niblit_usb_XXXXXX)"
        trap 'rm -rf "$WORKDIR"' EXIT

        # ── Minimal Debian chroot ──────────────────────────────────────────
        echo "[niblit] Bootstrapping minimal Debian..."
        debootstrap --variant=minbase --arch=amd64 \
            bookworm "$WORKDIR/chroot" http://deb.debian.org/debian

        # ── Install Python inside chroot ───────────────────────────────────
        echo "[niblit] Installing Python 3..."
        chroot "$WORKDIR/chroot" apt-get install -y --no-install-recommends \
            python3 python3-pip python3-venv git ca-certificates openssh-client \
            2>/dev/null

        # ── Copy Niblit into chroot ────────────────────────────────────────
        echo "[niblit] Copying Niblit..."
        cp -r "$BUNDLE_DIR/niblit" "$WORKDIR/chroot/opt/niblit"

        # ── Install Niblit Python deps ─────────────────────────────────────
        echo "[niblit] Installing Python requirements (may take a while)..."
        chroot "$WORKDIR/chroot" bash -c \
            "cd /opt/niblit && python3 -m pip install --quiet -r requirements.txt" \
            || echo "WARN: some pip packages failed — running in degraded mode"

        # ── Install systemd service ────────────────────────────────────────
        cp "$BUNDLE_DIR/niblit/boot/niblit@.service" \
           "$WORKDIR/chroot/etc/systemd/system/niblit@niblit.service"
        sed -i 's|/opt/niblit|/opt/niblit|' \
            "$WORKDIR/chroot/etc/systemd/system/niblit@niblit.service"
        ln -sf /etc/systemd/system/niblit@niblit.service \
            "$WORKDIR/chroot/etc/systemd/system/multi-user.target.wants/niblit@niblit.service"

        # ── GRUB bootloader config ─────────────────────────────────────────
        mkdir -p "$WORKDIR/iso/boot/grub"
        cat > "$WORKDIR/iso/boot/grub/grub.cfg" <<'GRUBEOF'
        set default=0
        set timeout=3
        menuentry "Niblit AI OS" {
            linux  /boot/vmlinuz quiet splash NIBLIT_BOOT_MODE=service
            initrd /boot/initrd.img
        }
        GRUBEOF

        # Copy kernel + initrd from chroot
        cp "$WORKDIR/chroot/boot/vmlinuz-"* "$WORKDIR/iso/boot/vmlinuz"   2>/dev/null || true
        cp "$WORKDIR/chroot/boot/initrd.img-"* "$WORKDIR/iso/boot/initrd.img" 2>/dev/null || true

        # Pack chroot as squashfs
        need mksquashfs
        mkdir -p "$WORKDIR/iso/live"
        mksquashfs "$WORKDIR/chroot" "$WORKDIR/iso/live/filesystem.squashfs" \
            -comp xz -noappend -quiet

        # Build ISO
        ISO_OUT="/tmp/niblit_$(date +%Y%m%d).iso"
        grub-mkrescue -o "$ISO_OUT" "$WORKDIR/iso" -- -as mkisofs \
            -iso-level 3 -rock -joliet -volid "NIBLIT" 2>/dev/null
        echo "[niblit] ISO built: $ISO_OUT"

        if [[ -n "$TARGET" && -b "$TARGET" ]]; then
            echo "[niblit] Writing to $TARGET (this will erase the drive!)"
            read -rp "Type YES to confirm: " confirm
            [[ "$confirm" == "YES" ]] || { echo "Aborted."; exit 0; }
            dd if="$ISO_OUT" of="$TARGET" bs=4M status=progress conv=fsync
            sync
            echo "[niblit] USB written successfully → $TARGET"
        else
            echo "[niblit] To write to USB: sudo dd if=$ISO_OUT of=/dev/sdX bs=4M status=progress"
        fi
    """).lstrip())
    builder.chmod(0o755)

    # 3. README
    (out_dir / "README.txt").write_text(textwrap.dedent(f"""
        Niblit Bootable USB Bundle
        ==========================
        This bundle was generated by niblit_usb.py on {platform.system()}.

        To build the bootable USB:
        1. Copy this entire folder to a Linux machine (any distro).
        2. Install tools:  sudo apt install debootstrap grub-mkrescue xorriso squashfs-tools
        3. Run:  sudo bash build_usb.sh [optional: /dev/sdX]

        The script will:
        • Bootstrap a minimal Debian system in a temporary chroot
        • Install Python 3 and Niblit inside the chroot
        • Build a bootable ISO (saved to /tmp/niblit_YYYYMMDD.iso)
        • Optionally write the ISO directly to a USB drive

        Booting the USB
        ---------------
        • Plug the USB into any PC/laptop and reboot
        • Select the USB in the boot menu (usually F12, F11, ESC, or Del)
        • Choose "Niblit AI OS" from the GRUB menu
        • Niblit starts automatically on every boot as a background daemon

        Platform targets
        ----------------
        Android/Termux : bash niblit/boot/install.sh
        Linux PC       : bash niblit/boot/install.sh  (or sudo for system-wide)
        Windows        : niblit\\boot\\install_windows.bat (run as Administrator)
        macOS          : bash niblit/boot/install.sh
        Raspberry Pi   : bash niblit/boot/install.sh
    """).lstrip())

    log.info("Bundle generated: %s", out_dir)
    print(f"\n✅ Niblit USB bundle written to: {out_dir}")
    print("   Follow the instructions in README.txt to build the bootable USB.")


# ─────────────────────────────────────────────────────────────────────────────
# Direct ISO builder (Linux root only)
# ─────────────────────────────────────────────────────────────────────────────

def build_iso(out_path: Path, write_to: str | None = None) -> None:
    """Build a Niblit bootable ISO.  Requires root on Linux."""
    if platform.system() != "Linux":
        print("Direct ISO building only works on Linux. Use --bundle instead.")
        sys.exit(1)
    if os.geteuid() != 0:
        print("ISO building requires root (sudo python boot/niblit_usb.py --out ...)")
        sys.exit(1)

    with tempfile.TemporaryDirectory(prefix="niblit_usb_") as tmp:
        bundle_dir = Path(tmp) / "bundle"
        generate_bundle(bundle_dir)
        # Invoke the generated builder script
        _run(["bash", str(bundle_dir / "build_usb.sh")] +
             ([write_to] if write_to else []),
             check=False)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Niblit Bootable USB Creator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              python boot/niblit_usb.py --bundle /tmp/niblit_usb_bundle
              sudo python boot/niblit_usb.py --out /tmp/niblit.iso
              sudo python boot/niblit_usb.py --out /dev/sdb --write
        """),
    )
    parser.add_argument("--bundle", metavar="DIR",
                        help="Generate a config/script bundle (no root needed)")
    parser.add_argument("--out", metavar="PATH",
                        help="Build ISO to this path (requires root on Linux)")
    parser.add_argument("--write", metavar="DEVICE", nargs="?", const=True,
                        help="Write ISO directly to a USB device (DESTRUCTIVE)")
    args = parser.parse_args()

    if args.bundle:
        generate_bundle(Path(args.bundle))
    elif args.out:
        write_to = args.write if isinstance(args.write, str) else None
        build_iso(Path(args.out), write_to=write_to)
    else:
        # Default: generate bundle in current directory
        default_out = Path.cwd() / "niblit_usb_bundle"
        generate_bundle(default_out)


if __name__ == "__main__":
    main()
