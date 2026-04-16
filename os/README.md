# NiblitOS — Building the C++ Kernel

NiblitOS is a real, Multiboot2-compliant x86 operating system kernel written
in C++ and NASM assembly.  It boots on QEMU (or real hardware) and starts
Niblit's AI tool layer as its first userspace process.

## Directory layout

```
os/
├── boot/
│   └── boot.asm          # Multiboot2 entry stub (NASM)
├── kernel/
│   ├── kernel.cpp         # kernel_main() — boot sequence + init
│   ├── vga.cpp/h          # VGA text-mode driver (80×25)
│   ├── gdt.cpp/h/asm      # Global Descriptor Table
│   ├── idt.cpp/h/asm      # Interrupt Descriptor Table + PIC remapping
│   ├── memory.cpp/h       # Physical page frame allocator
│   ├── process.cpp/h/asm  # Round-robin task scheduler
│   └── niblit_iface.cpp/h # Niblit AI tool IPC interface
├── userland/
│   └── niblit_tool/
│       ├── niblit_runner.c    # C daemon: polls ring buffer, forks Python
│       └── niblit_entry.py    # Python entry: invokes NiblitCore
├── linker.ld              # ELF linker script (loads at 1 MiB)
├── Makefile               # Build + QEMU run targets
└── README.md              # This file
```

## Boot sequence

```
BIOS/UEFI
  └─→ GRUB2 (Multiboot2 loader)
        └─→ boot/boot.asm  (_start)
              └─→ kernel/kernel.cpp  (kernel_main)
                    ├── VGA::init()           (text display)
                    ├── GDT::init()           (flat memory model)
                    ├── IDT::init()           (exceptions + IRQs)
                    ├── Memory::init()        (physical allocator)
                    ├── Process::init()       (scheduler + idle task)
                    ├── NiblitIface::init()   (AI tool IPC ring)
                    ├── sti                   (enable interrupts)
                    ├── Process::create("niblit-daemon", ...)
                    └── idle loop             (scheduler takes over)
```

The `niblit-daemon` kernel task interfaces with the Python NiblitCore process
via a shared ring buffer, making Niblit's AI capabilities available to every
OS component.

## Prerequisites

### Cross-compiler (required)

You need an `i686-elf` cross-compiler.  The easiest way on Ubuntu/Debian:

```bash
# Install build dependencies
sudo apt install build-essential bison flex libgmp3-dev libmpc-dev \
    libmpfr-dev texinfo libisl-dev nasm qemu-system-x86 \
    grub-pc-bin grub-common xorriso mtools

# Build binutils + GCC cross-toolchain (takes ~20 min)
export PREFIX="$HOME/opt/cross"
export TARGET=i686-elf
export PATH="$PREFIX/bin:$PATH"

mkdir -p "$HOME/src"
cd "$HOME/src"

# Binutils
curl -O https://ftp.gnu.org/gnu/binutils/binutils-2.42.tar.gz
tar xf binutils-2.42.tar.gz
mkdir build-binutils && cd build-binutils
../binutils-2.42/configure --target=$TARGET --prefix="$PREFIX" \
    --with-sysroot --disable-nls --disable-werror
make -j$(nproc) && make install
cd ..

# GCC
curl -O https://ftp.gnu.org/gnu/gcc/gcc-13.2.0/gcc-13.2.0.tar.gz
tar xf gcc-13.2.0.tar.gz
mkdir build-gcc && cd build-gcc
../gcc-13.2.0/configure --target=$TARGET --prefix="$PREFIX" \
    --disable-nls --enable-languages=c,c++ --without-headers
make -j$(nproc) all-gcc all-target-libgcc
make install-gcc install-target-libgcc
```

### Using a Docker cross-compiler image (easier)

```bash
docker run --rm -v $(pwd)/os:/work osdev/cross-compiler:i686 \
    sh -c "cd /work && make"
```

## Build

```bash
cd os

# Build kernel ELF
make

# Build bootable ISO
make iso

# Run in QEMU (requires make iso first)
make run

# Run ELF directly in QEMU (no ISO, faster iteration)
make run-elf
```

## From the repo root (via top-level Makefile)

```bash
make boot-kernel     # build kernel ELF
make run-os          # boot NiblitOS in QEMU
```

## How Niblit runs inside NiblitOS

```
NiblitOS Kernel (C++)
  │
  │  NiblitIface::send_request("query", "", "What is the status?")
  │              ↓  (shared ring buffer at physical page)
  │
  niblit-daemon task (kernel task → execs niblit_runner)
              ↓  (fork + exec)
  niblit_runner (C userland)
              ↓  (fork + pipe)
  python3 niblit_entry.py
              ↓  (imports NiblitCore)
  NiblitCore   — full AI reasoning stack
              ↓  (stdout → pipe → ring buffer response)
  niblit-daemon writes response into NiblitRing.responses[]
              ↓
  Kernel polls NiblitIface::poll_response(id) to read answer
```

## Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| 1     | ✅ Done | Python `kernel/` OS abstraction layer wired into NiblitCore |
| 2     | ✅ Done | C++ OS kernel: VGA, GDT, IDT, memory, scheduler, Niblit IPC |
| 3     | 🔲 Next | Paging (4 KiB pages), virtual memory, `mmap` syscall |
| 4     | 🔲 Next | ELF loader, proper userspace, system call table (int 0x80) |
| 5     | 🔲 Next | VFS layer: ext2 read-only, initrd (cpio), `/proc` stubs |
| 6     | 🔲 Next | POSIX shell (`/bin/sh`) as init process |
| 7     | 🔲 Next | Port musl libc; run Python 3 as a native process |
| 8     | 🔲 Next | Network stack (lwIP), SSH daemon |
| 9     | 🔲 Next | Full NiblitCore as persistent daemon |
