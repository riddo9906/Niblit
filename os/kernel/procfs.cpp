// os/kernel/procfs.cpp — ProcFS pseudo-filesystem implementation
//
// Populates /proc with virtual files whose content is generated dynamically
// from live kernel subsystem data.  Content is written to the RamFS so
// normal VFS open()/read() calls work on them from userspace.
#include "procfs.h"
#include "vfs.h"
#include "memory.h"
#include "heap.h"
#include "pit.h"
#include "acpi.h"
#include "process.h"
#include "vga.h"
#include "serial.h"
#include <stdint.h>
#include <stddef.h>

namespace ProcFS {

// ── String helpers ────────────────────────────────────────────────────────────

static void kappend(char* buf, size_t& pos, size_t max, const char* s) {
    while (*s && pos < max - 1) buf[pos++] = *s++;
    buf[pos] = '\0';
}

static void kappend_u32(char* buf, size_t& pos, size_t max, uint32_t v) {
    char tmp[12];
    int n = 0;
    if (v == 0) {
        tmp[n++] = '0';
    } else {
        while (v) { tmp[n++] = '0' + (char)(v % 10); v /= 10; }
    }
    for (int i = n - 1; i >= 0 && pos < max - 1; --i) buf[pos++] = tmp[i];
    buf[pos] = '\0';
}

static void write_proc(const char* path, const char* content) {
    VFS::write_file(path, content);
}

// ── /proc/version ─────────────────────────────────────────────────────────────

static void build_version() {
    write_proc("/proc/version",
        "NiblitOS v3.0 (C++ kernel + Niblit AI tool layer)\n"
        "Kernel: i686-elf-g++ -std=c++17 -ffreestanding -O2 -fno-exceptions\n"
        "Boot:   Multiboot2 via GRUB2 (or QEMU -kernel)\n"
        "Init:   niblit-daemon (PID 1 equivalent — Niblit IS the OS)\n"
        "Stack:  C++ kernel → niblit-daemon → niblit_runner.c → niblit_entry.py → NiblitCore\n");
}

// ── /proc/meminfo ─────────────────────────────────────────────────────────────

static void build_meminfo() {
    Memory::Stats s = Memory::stats();
    uint32_t total_kb = static_cast<uint32_t>(s.total_frames * Memory::PAGE_SIZE / 1024);
    uint32_t free_kb  = static_cast<uint32_t>(s.free_frames  * Memory::PAGE_SIZE / 1024);
    uint32_t used_kb  = static_cast<uint32_t>(s.used_frames  * Memory::PAGE_SIZE / 1024);
    uint32_t heap_b   = Heap::used_bytes();

    char buf[VFS::MAX_FILE_SZ];
    size_t pos = 0;

    kappend(buf, pos, sizeof(buf), "MemTotal:     "); kappend_u32(buf, pos, sizeof(buf), total_kb); kappend(buf, pos, sizeof(buf), " kB\n");
    kappend(buf, pos, sizeof(buf), "MemFree:      "); kappend_u32(buf, pos, sizeof(buf), free_kb);  kappend(buf, pos, sizeof(buf), " kB\n");
    kappend(buf, pos, sizeof(buf), "MemUsed:      "); kappend_u32(buf, pos, sizeof(buf), used_kb);  kappend(buf, pos, sizeof(buf), " kB\n");
    kappend(buf, pos, sizeof(buf), "HeapUsed:     "); kappend_u32(buf, pos, sizeof(buf), heap_b);   kappend(buf, pos, sizeof(buf), " bytes\n");
    kappend(buf, pos, sizeof(buf), "PageSize:     "); kappend_u32(buf, pos, sizeof(buf), static_cast<uint32_t>(Memory::PAGE_SIZE)); kappend(buf, pos, sizeof(buf), " bytes\n");
    kappend(buf, pos, sizeof(buf), "TotalFrames:  "); kappend_u32(buf, pos, sizeof(buf), static_cast<uint32_t>(s.total_frames)); kappend(buf, pos, sizeof(buf), " frames\n");
    kappend(buf, pos, sizeof(buf), "FreeFrames:   "); kappend_u32(buf, pos, sizeof(buf), static_cast<uint32_t>(s.free_frames));  kappend(buf, pos, sizeof(buf), " frames\n");

    write_proc("/proc/meminfo", buf);
}

// ── /proc/uptime ──────────────────────────────────────────────────────────────

static void build_uptime() {
    uint32_t ms = PIT::millis();
    char buf[64];
    size_t pos = 0;
    kappend_u32(buf, pos, sizeof(buf), ms);
    kappend(buf, pos, sizeof(buf), " ms since boot (PIT 100 Hz)\n");
    write_proc("/proc/uptime", buf);
}

// ── /proc/cpuinfo ─────────────────────────────────────────────────────────────

static void build_cpuinfo() {
    char buf[VFS::MAX_FILE_SZ];
    size_t pos = 0;
    uint32_t ncpu = (ACPI::available() && ACPI::cpu_count() > 0)
                        ? static_cast<uint32_t>(ACPI::cpu_count())
                        : 1;

    for (uint32_t i = 0; i < ncpu; ++i) {
        kappend(buf, pos, sizeof(buf), "processor\t: ");
        kappend_u32(buf, pos, sizeof(buf), i);
        kappend(buf, pos, sizeof(buf), "\n");
        kappend(buf, pos, sizeof(buf), "model name\t: NiblitOS i686 vCPU (Multiboot2 x86)\n");
        kappend(buf, pos, sizeof(buf), "vendor\t\t: NiblitOS\n");

        if (ACPI::available()) {
            ACPI::CpuInfo ci = ACPI::cpu(i);
            kappend(buf, pos, sizeof(buf), "apicid\t\t: ");
            kappend_u32(buf, pos, sizeof(buf), static_cast<uint32_t>(ci.apic_id));
            kappend(buf, pos, sizeof(buf), "\n");
            kappend(buf, pos, sizeof(buf), "status\t\t: ");
            kappend(buf, pos, sizeof(buf), ci.enabled ? "enabled" : "disabled");
            kappend(buf, pos, sizeof(buf), "\n");
        }
        kappend(buf, pos, sizeof(buf), "\n");
        if (pos > sizeof(buf) - 128) break; // guard against overflow
    }

    write_proc("/proc/cpuinfo", buf);
}

// ── /proc/niblit ──────────────────────────────────────────────────────────────
// Live status of the Niblit AI daemon.

static void build_niblit() {
    char buf[VFS::MAX_FILE_SZ];
    size_t pos = 0;
    uint32_t ms = PIT::millis();

    kappend(buf, pos, sizeof(buf), "niblit_version: 3.0\n");
    kappend(buf, pos, sizeof(buf), "daemon_status:  active\n");
    kappend(buf, pos, sizeof(buf), "uptime_ms:      "); kappend_u32(buf, pos, sizeof(buf), ms); kappend(buf, pos, sizeof(buf), "\n");
    kappend(buf, pos, sizeof(buf), "ipc_ring_vaddr: 0xD0000000\n");
    kappend(buf, pos, sizeof(buf), "ring_capacity:  8 slots\n");
    kappend(buf, pos, sizeof(buf), "unix_socket:    /tmp/niblit.sock\n");
    kappend(buf, pos, sizeof(buf), "entry_point:    os/userland/niblit_tool/niblit_entry.py\n");
    kappend(buf, pos, sizeof(buf), "roles:          copilot manager coach trainer\n");
    kappend(buf, pos, sizeof(buf), "kb_path:        /var/niblit/kb/\n");
    kappend(buf, pos, sizeof(buf), "log_path:       /var/log/niblit.log\n");
    kappend(buf, pos, sizeof(buf), "qwen_syscall:   SYS_NIBLIT_SPAWN_REASONER=205\n");

    write_proc("/proc/niblit", buf);
}

// ── /proc/devices ─────────────────────────────────────────────────────────────

static void build_devices() {
    write_proc("/proc/devices",
        "Character devices:\n"
        "  1 /dev/null     (discard sink)\n"
        "  2 /dev/zero     (zero source)\n"
        "  3 /dev/niblit   (Niblit AI IPC — maps NiblitRing @ 0xD0000000)\n"
        "Block devices:\n"
        "  (ATA/IDE drives detected at boot — run 'ata' for list)\n");
}

// ── /proc/syscalls ────────────────────────────────────────────────────────────

static void build_syscalls() {
    write_proc("/proc/syscalls",
        "NiblitOS int 0x80 syscall table\n"
        "eax  name                   args (ebx, ecx, edx)\n"
        "---  --------------------   ---------------------\n"
        "  1  exit                   code\n"
        "  2  fork                   — (returns 0 stub)\n"
        "  3  read                   fd, buf, len\n"
        "  4  write                  fd, buf, len\n"
        "  5  open                   path, flags\n"
        "  6  close                  fd\n"
        "  7  waitpid                pid, status_ptr, opts\n"
        " 20  getpid                 —\n"
        " 24  yield                  —\n"
        " 39  mkdir                  path\n"
        "162  sleep                  ms\n"
        "200  mem_info               buf, len\n"
        "201  niblit_query           query_ptr\n"
        "202  niblit_tool            tool_ptr, args_ptr\n"
        "203  proc_list              buf, len\n"
        "204  exec                   path, name\n"
        "205  niblit_spawn_reasoner  socket_path (or NULL for default)\n"
        "206  niblit_kb_write        key_ptr, value_ptr\n"
        "207  niblit_kb_read         key_ptr, buf_ptr, len\n"
        "208  niblit_resource_info   buf_ptr, len\n"
        "209  niblit_mmap_ring       — (returns NIBLIT_RING_VADDR)\n");
}

// ── Public API ────────────────────────────────────────────────────────────────

void init() {
    VFS::mkdir("/proc");

    build_version();
    build_meminfo();
    build_uptime();
    build_cpuinfo();
    build_niblit();
    build_devices();
    build_syscalls();

    VGA::writeln("OK (/proc ready — 7 virtual files)");
    Serial::logln("[ProcFS] /proc mounted: version meminfo uptime cpuinfo niblit devices syscalls");
}

void refresh() {
    // Regenerate the time-varying entries so readers always get fresh data.
    build_meminfo();
    build_uptime();
    build_niblit();
}

} // namespace ProcFS
