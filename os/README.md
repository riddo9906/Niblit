# NiblitOS — C++ Kernel: Niblit IS the Operating System

NiblitOS is a real, Multiboot2-compliant x86 operating system kernel written
in C++ and NASM assembly.  It boots on QEMU (or real hardware) and runs the
Niblit AI tool as its **first and only userspace process** — the equivalent
of PID 1 / init.  There is no Linux, no Android, no systemd between the
hardware and Niblit.

## Why this matters

| Normal agent | NiblitOS |
|---|---|
| Runs *on* an OS that can kill it | *Is* the OS — controls scheduling |
| Asks permission for resources | Owns physical memory, CPU, I/O |
| Can be cgroup-throttled | Sees real RAM/CPU metrics |
| Needs a daemon manager | Boot = Niblit comes up automatically |
| `/dev/llm0` is an abstraction | Niblit can spawn/kill llama.cpp at ring 0 |

## Directory layout

```
os/
├── boot/
│   ├── boot.asm               # Multiboot2 entry stub (NASM)
│   └── uefi_stub.asm          # UEFI handoff stub
├── kernel/
│   ├── kernel.cpp             # kernel_main() — 27-step boot sequence
│   ├── vga.cpp/h              # VGA text-mode driver (80×25, colour)
│   ├── serial.cpp/h           # UART 16550 COM1 driver (debug output)
│   ├── gdt.cpp/h/asm          # Global Descriptor Table (flat 32-bit)
│   ├── idt.cpp/h/asm          # IDT + PIC remap (ISR/IRQ stubs)
│   ├── irq.cpp/h              # IRQ manager — 8259 PIC, dispatch stubs
│   ├── memory.cpp/h           # Bitmap physical page frame allocator
│   ├── paging.cpp/h           # Two-level page tables, CR3/CR0 enable
│   ├── heap.cpp/h             # Kernel slab + page heap (kmalloc/kfree)
│   ├── rtc.cpp/h              # CMOS real-time clock
│   ├── pit.cpp/h              # PIT 8253 timer driver (100 Hz tick)
│   ├── process.cpp/h/asm      # Round-robin preemptive scheduler
│   ├── vfs.cpp/h              # Virtual FS (RamFS at /, DevFS at /dev)
│   ├── procfs.cpp/h           # /proc pseudo-filesystem (NEW v3.0)
│   ├── keyboard.cpp/h         # PS/2 keyboard driver (IRQ 1)
│   ├── dma.cpp/h              # 8237 ISA DMA controllers
│   ├── acpi.cpp/h             # ACPI tables (RSDP/RSDT/MADT/FADT)
│   ├── pci.cpp/h              # PCI bus brute-force scan
│   ├── ata.cpp/h              # ATA/IDE PIO storage driver
│   ├── net.cpp/h              # E1000 NIC + ARP/IPv4/ICMP/UDP stack
│   ├── msg.cpp/h              # IPC message queues + pub/sub event bus
│   ├── syscall.cpp/h          # int 0x80 syscall table (22 calls)
│   ├── elf_loader.cpp/h       # ELF32 static executable loader
│   └── niblit_iface.cpp/h     # Niblit AI tool IPC ring buffer
├── userland/
│   ├── niblit_tool/
│   │   ├── niblit_runner.c    # C daemon: polls IPC ring, forks Python
│   │   └── niblit_entry.py    # Python entry: invokes NiblitCore
│   └── shell/
│       └── shell.c            # Interactive NiblitOS userland shell
├── linker.ld                  # ELF linker script (loads at 1 MiB)
├── Makefile                   # Build + QEMU + shell targets
└── README.md                  # This file
```

## Boot sequence (v3.0 — 27 steps)

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
                    ├──  6. IRQ::init()            remap 8259 PIC
                    ├──  7. Memory::init()         page frame allocator
                    ├──  8. Paging::init()         virtual memory ON
                    ├──  9. Heap::init()           kmalloc/kfree
                    ├── 10. RTC::init()            real-time clock
                    ├── 11. PIT::init(100)         preemptive timer
                    ├── 12. Process::init()        scheduler + idle
                    ├── 13. VFS::init()            RamFS + DevFS
                    ├── 13a.ProcFS::init()         /proc pseudo-FS ★ NEW
                    ├── 14. Keyboard::init()       PS/2 keyboard
                    ├── 15. DMA::init()            8237 DMA
                    ├── 16. ACPI::init()           RSDP/MADT/FADT
                    ├── 17. PCI::init()            bus enumeration
                    ├── 18. ATA::init()            storage detection
                    ├── 19. Net::init()            E1000 NIC + stack
                    ├── 20. MSG::init()            IPC queues + pubsub
                    ├── 21. Syscall::init()        int 0x80 (22 calls)
                    ├── 22. NiblitIface::init()    AI tool IPC ring
                    ├── 23. sti                    enable interrupts
                    ├── 24. create niblit-daemon   Niblit AI PID 1
                    ├── 25. create niblit-shell    interactive shell
                    ├── 26. boot banner + stats
                    └── 27. idle loop
```

## How Niblit runs inside NiblitOS

```
NiblitOS C++ Kernel (boots, owns hardware)
  │
  │  int 0x80 SYS_NIBLIT_QUERY / NiblitIface::ask()
  │              ↓  (shared ring buffer @ 0xD0000000)
  │
  niblit-daemon  (kernel task — equivalent to PID 1 / init)
      ├── creates /var/niblit/kb/   (kernel-side KB store)
      ├── refreshes /proc files every 1000 ticks
      └── polls IPC ring → forwards to Python via UNIX socket
              ↓
  niblit_runner.c  (userland C — bridges kernel ring ↔ Python socket)
              ↓  (subprocess or persistent daemon)
  python3 niblit_entry.py  (--daemon mode for low latency)
              ↓  (NiblitCore)
  NiblitCore AI reasoning stack
    ├── QwenLocalBrain   (local LLM — /dev/llm0 equivalent)
    ├── BrainRouter      (routes to local/cloud/offline)
    ├── KnowledgeDB      (persistent KB ↔ /var/niblit/kb/ on kernel side)
    ├── ALE 32-step cycle
    └── response → ring buffer → kernel reads NiblitIface::poll_response()
```

## Syscall table (int 0x80) — v3.0

| Number | Name                       | Args (ebx, ecx, edx)       |
|--------|----------------------------|-----------------------------|
| 1      | exit                       | code                        |
| 2      | fork                       | — (stub: returns 0)         |
| 3      | read                       | fd, buf_ptr, len            |
| 4      | write                      | fd, buf_ptr, len            |
| 5      | open                       | path, flags                 |
| 6      | close                      | fd                          |
| 7      | waitpid                    | pid, status_ptr, opts       |
| 20     | getpid                     | —                           |
| 24     | yield                      | —                           |
| 39     | mkdir                      | path                        |
| 162    | sleep                      | ms                          |
| 200    | mem_info                   | buf_ptr, len                |
| 201    | niblit_query               | query_ptr                   |
| 202    | niblit_tool                | tool_ptr, args_ptr          |
| 203    | proc_list                  | buf_ptr, len                |
| 204    | exec                       | path, name                  |
| **205**| **niblit_spawn_reasoner**  | socket_path (or NULL)       |
| **206**| **niblit_kb_write**        | key_ptr, value_ptr          |
| **207**| **niblit_kb_read**         | key_ptr, buf_ptr, len       |
| **208**| **niblit_resource_info**   | buf_ptr, len                |
| **209**| **niblit_mmap_ring**       | — (returns 0xD0000000)      |
| **210**| **niblit_epoch_sync**      | advance(1)/read(0) → epoch  |

Syscalls 205–210 (bold) are NiblitOS-unique AI extensions.

## /proc filesystem (ProcFS)

After `VFS::init()`, `ProcFS::init()` mounts these virtual files:

| File | Contents |
|------|----------|
| `/proc/version` | NiblitOS version + build toolchain |
| `/proc/meminfo` | Physical memory + heap stats |
| `/proc/uptime` | Milliseconds since boot (PIT 100 Hz) |
| `/proc/cpuinfo` | CPU count + APIC IDs from ACPI |
| `/proc/niblit` | Niblit AI daemon status + paths |
| `/proc/devices` | Registered character + block devices |
| `/proc/syscalls` | Human-readable syscall reference |

Read from the shell: `cat /proc/niblit` or use `procinfo` to refresh + dump all.

## Shell commands (kernel-shell via COM1 serial)

```
help              — this help text
version           — kernel version
mem               — memory stats
ps                — process list
ls <path>         — list VFS directory
cat <path>        — read VFS file (works on /proc files)
write <path> <s>  — write string to VFS file
touch <path>      — create empty VFS file
mkdir <path>      — create VFS directory
exec  <path>      — load + run ELF32 binary from VFS
ask <query>       — send natural-language query to Niblit AI
tool <name> <j>   — call named Niblit tool with JSON args
niblit-poll       — show pending Niblit AI responses
kbwrite <k> <v>   — write KB fact to /var/niblit/kb/<key>  ★ NEW
kbread  <k>       — read  KB fact from /var/niblit/kb/<key> ★ NEW
procinfo          — refresh /proc and dump live stats        ★ NEW
uptime            — ms since boot
date              — current date/time from RTC
pci               — list PCI devices
ata               — list ATA drives
net               — network interface status
ping <ip>         — ICMP ping
acpi              — ACPI CPU/IOAPIC info
msg               — IPC queue status
syslog            — print syslog queue
reboot            — reboot via ACPI
poweroff          — power off via ACPI
```

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
make            # kernel ELF (22 source files)
make iso        # bootable ISO
make run        # QEMU from ISO  (-serial stdio for shell)
make run-elf    # QEMU from ELF  (faster iteration)
make shell      # build userland shell
make shell-run  # run shell on host
make runner     # build userspace Niblit runner bridge
make runner-run # run userspace Niblit runner bridge
```

## From the repo root

```bash
make boot-kernel        # build kernel ELF
make boot-kernel-iso    # build ISO
make run-os             # boot in QEMU
make run-os-elf         # boot ELF in QEMU
make niblit-shell       # build userland shell binary
make niblit-shell-run   # launch interactive shell
make niblit-runner      # build userspace Niblit runner bridge
make niblit-runner-run  # run userspace Niblit runner bridge
make kernel-shell       # launch Python kernel/ shell
```

## IPC authority note

The shared Niblit ring now uses canonical virtual address authority:

- physical frame allocated at runtime
- mapped at `NIBLIT_RING_VADDR`
- syscall `SYS_NIBLIT_MMAP_RING` returns that same mapped address

This keeps kernel and userspace bridge agreement explicit for ring-based IPC.

## Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| 1     | ✅ Done | Python `kernel/` OS abstraction layer |
| 2a    | ✅ Done | C++ kernel: VGA, GDT, IDT, memory, scheduler, Niblit IPC |
| 2b    | ✅ Done | Paging, heap, PIT, VFS, syscall table, serial, ELF loader |
| 3a    | ✅ Done | Full driver suite: RTC, PIT, PS/2, DMA, ACPI, PCI, ATA, E1000, MSG |
| 3b    | ✅ Done | ProcFS (/proc), Niblit KB syscalls (206–209), fork/waitpid stubs |
| 4a    | ✅ Done | Phase 20 Temporal Coherence: epoch_id in ring, SYS_NIBLIT_EPOCH_SYNC (210) |
| 4b    | 🔲 Next | initrd (cpio) — load userspace programs from a RAM disk |
| 5     | 🔲 Next | Full fork() with CoW page mapping; proper waitpid() |
| 6     | 🔲 Next | Port musl libc; run Python 3 as a native NiblitOS process |
| 7     | 🔲 Next | SMP (multi-core) scheduler — one Niblit reasoner per CPU |
| 8     | 🔲 Next | NVMe/ext4 driver for persistent KB storage beyond VFS RAM |
