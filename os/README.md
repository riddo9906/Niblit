# NiblitOS — Building the C++ Kernel

NiblitOS is a real, Multiboot2-compliant x86 operating system kernel written
in C++ and NASM assembly.  It boots on QEMU (or real hardware) and starts
Niblit's AI tool layer as its first userspace process.

## Directory layout

```
os/
├── boot/
│   └── boot.asm               # Multiboot2 entry stub (NASM)
├── kernel/
│   ├── kernel.cpp             # kernel_main() — 17-step boot sequence
│   ├── vga.cpp/h              # VGA text-mode driver (80×25, colour)
│   ├── serial.cpp/h           # UART 16550 COM1 driver (debug output)
│   ├── gdt.cpp/h/asm          # Global Descriptor Table (flat 32-bit)
│   ├── idt.cpp/h/asm          # IDT + PIC remap (ISR/IRQ stubs)
│   ├── memory.cpp/h           # Bitmap physical page frame allocator
│   ├── paging.cpp/h           # Two-level page tables, CR3/CR0 enable
│   ├── heap.cpp/h             # Kernel slab + page heap (kmalloc/kfree)
│   ├── pit.cpp/h              # PIT 8253 timer driver (100 Hz tick)
│   ├── process.cpp/h/asm      # Round-robin preemptive scheduler
│   ├── vfs.cpp/h              # Virtual FS (RamFS at /, DevFS at /dev)
│   ├── syscall.cpp/h          # int 0x80 syscall table (10 calls)
│   └── niblit_iface.cpp/h     # Niblit AI tool IPC ring buffer
├── userland/
│   ├── niblit_tool/
│   │   ├── niblit_runner.c    # C daemon: polls ring, forks Python
│   │   └── niblit_entry.py    # Python entry: invokes NiblitCore
│   └── shell/
│       └── shell.c            # Interactive NiblitOS userland shell
├── linker.ld                  # ELF linker script (loads at 1 MiB)
├── Makefile                   # Build + QEMU + shell targets
└── README.md                  # This file
```

## Boot sequence (v2)

```
BIOS/UEFI
  └─→ GRUB2 (Multiboot2)
        └─→ boot/boot.asm  (_start)
              └─→ kernel_main()
                    ├──  1. VGA::init()           text display
                    ├──  2. Serial::init()         COM1 debug output
                    ├──  3. Multiboot2 magic check
                    ├──  4. GDT::init()            flat memory model
                    ├──  5. IDT::init()            exceptions + IRQs
                    ├──  6. Memory::init()         page frame allocator
                    ├──  7. Paging::init()         virtual memory ON
                    ├──  8. Heap::init()           kmalloc/kfree
                    ├──  9. PIT::init(100)         preemptive timer
                    ├── 10. Process::init()        scheduler + idle
                    ├── 11. VFS::init()            RamFS + DevFS
                    ├── 12. Syscall::init()        int 0x80 table
                    ├── 13. NiblitIface::init()    AI tool IPC ring
                    ├── 14. sti                    enable interrupts
                    ├── 15. create niblit-daemon   AI daemon task
                    ├── 16. create niblit-shell    interactive shell
                    └── 17. idle loop
```

The `niblit-shell` kernel task provides a command prompt over COM1 serial
(use QEMU's `-serial stdio`).  The `niblit-daemon` forwards OS queries to
the Niblit Python AI tool via the IPC ring buffer.

## Syscall table (int 0x80)

| Number | Name            | Args (ebx, ecx, edx)           |
|--------|-----------------|--------------------------------|
| 1      | exit            | code                           |
| 3      | read            | fd, buf_ptr, len               |
| 4      | write           | fd, buf_ptr, len               |
| 20     | getpid          | —                              |
| 24     | yield           | —                              |
| 162    | sleep           | ms                             |
| 200    | mem_info        | buf_ptr, len                   |
| 201    | niblit_query    | query_ptr                      |
| 202    | niblit_tool     | tool_ptr, args_ptr             |
| 203    | proc_list       | buf_ptr, len                   |

## Prerequisites

### Cross-compiler (required for kernel)

```bash
sudo apt install build-essential bison flex libgmp3-dev libmpc-dev \
    libmpfr-dev texinfo libisl-dev nasm qemu-system-x86 \
    grub-pc-bin grub-common xorriso mtools gcc

# Build i686-elf cross-toolchain (~20 min) — see OSDev Wiki for details
export PREFIX="$HOME/opt/cross"
export TARGET=i686-elf
```

### Userland shell (no cross-compiler needed)

The shell compiles with any standard `gcc`:
```bash
cd os
make shell          # produces os/build/niblit-shell
make shell-run      # launches it interactively
```

### Docker (easiest)
```bash
docker run --rm -v $(pwd)/os:/work osdev/cross-compiler:i686 \
    sh -c "cd /work && make"
```

## Build

```bash
cd os
make            # kernel ELF
make iso        # bootable ISO
make run        # QEMU from ISO  (-serial stdio for shell)
make run-elf    # QEMU from ELF  (faster iteration)
make shell      # build userland shell
make shell-run  # run shell on host
```

## From the repo root

```bash
make boot-kernel        # build kernel ELF
make boot-kernel-iso    # build ISO
make run-os             # boot in QEMU
make run-os-elf         # boot ELF in QEMU
make niblit-shell       # build userland shell binary
make niblit-shell-run   # launch interactive shell
make kernel-shell       # launch Python kernel/ shell
```

## How Niblit runs inside NiblitOS

```
NiblitOS Kernel (C++)
  │
  │  int 0x80 SYS_NIBLIT_QUERY / NiblitIface::ask()
  │              ↓  (shared ring buffer)
  │
  niblit-daemon (kernel task)
              ↓  (fork + exec)
  niblit_runner.c  (userland C)
              ↓  (subprocess)
  python3 niblit_entry.py
              ↓  (NiblitCore)
  NiblitCore AI reasoning stack
              ↓  (response → ring buffer)
  Kernel reads NiblitIface::poll_response(id)
```

## Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| 1     | ✅ Done | Python `kernel/` OS abstraction layer |
| 2a    | ✅ Done | C++ kernel: VGA, GDT, IDT, memory, scheduler, Niblit IPC |
| 2b    | ✅ Done | Paging, heap, PIT, VFS, syscall table, serial driver, shell |
| 3     | 🔲 Next | ELF loader — load userspace programs from VFS |
| 4     | 🔲 Next | Keyboard (PS/2) driver → full interactive shell on VGA |
| 5     | 🔲 Next | initrd (cpio), `/proc` stubs, proper `/etc/init` |
| 6     | 🔲 Next | Port musl libc; run Python 3 as a native NiblitOS process |
| 7     | 🔲 Next | Network stack (lwIP) + SSH for remote Niblit access |
| 8     | 🔲 Next | SMP (multi-core) scheduler |
