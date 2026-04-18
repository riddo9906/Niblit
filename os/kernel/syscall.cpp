// os/kernel/syscall.cpp — int 0x80 system call dispatcher
#include "syscall.h"
#include "idt.h"
#include "vga.h"
#include "serial.h"
#include "memory.h"
#include "heap.h"
#include "pit.h"
#include "acpi.h"
#include "process.h"
#include "vfs.h"
#include "elf_loader.h"
#include "niblit_iface.h"
#include <stddef.h>

namespace Syscall {

// ── Helpers ───────────────────────────────────────────────────────────────────
static size_t kstrlen(const char* s) {
    size_t n = 0;
    while (s && *s++) ++n;
    return n;
}

// ── Syscall implementations ───────────────────────────────────────────────────

static uint32_t sys_exit(uint32_t code) {
    Process::Task* t = Process::current();
    if (t) {
        Serial::log("[SYSCALL] exit(");
        Serial::write_dec(Serial::COM1, code);
        Serial::log(") task '");
        Serial::writeln(Serial::COM1, t->name);
        t->state = Process::State::ZOMBIE;
    }
    Process::yield();
    return 0;
}

static uint32_t sys_write(uint32_t fd, const char* buf, uint32_t len) {
    if (!buf) return static_cast<uint32_t>(-1);
    if (fd == FD_STDOUT || fd == FD_STDERR) {
        for (uint32_t i = 0; i < len; ++i) {
            VGA::put_char(buf[i]);
            Serial::put_char(Serial::COM1, buf[i]);
        }
        return len;
    }
    return static_cast<uint32_t>(-1);
}

static uint32_t sys_read(uint32_t fd, char* buf, uint32_t len) {
    if (fd != FD_STDIN || !buf || len == 0) return static_cast<uint32_t>(-1);
    uint32_t n = 0;
    while (n < len) {
        char c = Serial::read_char(Serial::COM1);
        if (!c) break;
        buf[n++] = c;
        if (c == '\n') break;
    }
    return n;
}

static uint32_t sys_getpid() {
    Process::Task* t = Process::current();
    return t ? t->id : 0;
}

static uint32_t sys_sleep_ms(uint32_t ms) {
    PIT::sleep_ms(ms);
    return 0;
}

static uint32_t sys_mem_info(char* buf, uint32_t len) {
    if (!buf || len < 64) return static_cast<uint32_t>(-1);
    Memory::Stats s = Memory::stats();
    // Simple formatted output
    const char prefix[] = "free=";
    size_t pi = 0;
    for (; prefix[pi]; ++pi) buf[pi] = prefix[pi];
    // write free MiB
    uint32_t free_mb = static_cast<uint32_t>(s.free_frames * Memory::PAGE_SIZE / (1024 * 1024));
    // number to string
    char num[12]; int ni = 0;
    if (free_mb == 0) { num[ni++] = '0'; } else { uint32_t v = free_mb; while (v) { num[ni++] = '0' + (v % 10); v /= 10; } }
    for (int i = ni - 1; i >= 0; --i) buf[pi++] = num[i];
    buf[pi++] = 'M';
    buf[pi] = '\0';
    return pi;
}

static uint32_t sys_niblit_query(const char* query) {
    if (!query) return static_cast<uint32_t>(-1);
    return NiblitIface::send_request(0, "", query);
}

static uint32_t sys_niblit_tool(const char* tool, const char* args) {
    if (!tool) return static_cast<uint32_t>(-1);
    return NiblitIface::send_request(1, tool, args ? args : "{}");
}

static uint32_t sys_proc_list(char* buf, uint32_t /*len*/) {
    (void)buf;
    Process::dump();
    return 0;
}

static uint32_t sys_open(const char* path, uint32_t flags) {
    if (!path) return static_cast<uint32_t>(-1);
    int fd = VFS::open(path, flags);
    return static_cast<uint32_t>(fd);
}

static uint32_t sys_close(uint32_t fd) {
    return static_cast<uint32_t>(VFS::close(static_cast<int>(fd)));
}

static uint32_t sys_mkdir(const char* path) {
    if (!path) return static_cast<uint32_t>(-1);
    return static_cast<uint32_t>(VFS::mkdir(path));
}

static uint32_t sys_exec(const char* path, const char* name) {
    if (!path) return static_cast<uint32_t>(-1);
    int tid = ELF::exec(path, name);
    return static_cast<uint32_t>(tid);
}

// ── Niblit AI extension syscalls ──────────────────────────────────────────────

// SYS_FORK (2) — Minimal stub.  Full copy-on-write fork requires VM page
// remapping (Phase 5).  We create a new kernel task that runs the same
// entry function and return 0 (child) to the caller; the parent is not
// duplicated.  Userland programs that need fork() for subprocess spawning
// should use SYS_NIBLIT_SPAWN_REASONER (205) instead.
static uint32_t sys_fork() {
    Process::Task* t = Process::current();
    if (t) {
        Serial::log("[SYSCALL] fork() from '");
        Serial::log(t->name);
        Serial::logln("' (stub)");
    } else {
        Serial::logln("[SYSCALL] fork() (no current task, stub)");
    }
    // Return 0 so caller treats itself as the child (stub behaviour).
    return 0;
}

// SYS_WAITPID (7) — Stub: yield until a zombie slot becomes available.
static uint32_t sys_waitpid(uint32_t /*pid*/, uint32_t* /*status*/, uint32_t /*opts*/) {
    Process::yield();
    return 0;
}

// SYS_NIBLIT_SPAWN_REASONER (205) — Request that the Niblit daemon spawn
// (or connect to) the Python reasoning process.  Posts a "spawn_reasoner"
// tool call into the IPC ring so niblit_runner.c picks it up.
static uint32_t sys_niblit_spawn_reasoner(const char* /*socket_path*/) {
    return NiblitIface::send_request(1, "spawn_reasoner", "{}");
}

// SYS_NIBLIT_KB_WRITE (206) — Persist a key/value KB fact to the kernel-side
// VFS KB store at /var/niblit/kb/<key>.  Niblit's userspace daemon can later
// sync these to the Python KnowledgeDB.
static uint32_t sys_niblit_kb_write(const char* key, const char* value) {
    if (!key || !value) return static_cast<uint32_t>(-1);
    char path[VFS::MAX_PATH];
    const char* prefix = "/var/niblit/kb/";
    size_t pi = 0;
    while (prefix[pi]) path[pi] = prefix[pi++];
    for (size_t i = 0; key[i] && pi < VFS::MAX_PATH - 1; ++i) path[pi++] = key[i];
    path[pi] = '\0';
    int r = VFS::write_file(path, value);
    return static_cast<uint32_t>(r < 0 ? (uint32_t)(-1) : 0u);
}

// SYS_NIBLIT_KB_READ (207) — Read a KB fact from /var/niblit/kb/<key>.
static uint32_t sys_niblit_kb_read(const char* key, char* buf, uint32_t len) {
    if (!key || !buf || len == 0) return static_cast<uint32_t>(-1);
    char path[VFS::MAX_PATH];
    const char* prefix = "/var/niblit/kb/";
    size_t pi = 0;
    while (prefix[pi]) path[pi] = prefix[pi++];
    for (size_t i = 0; key[i] && pi < VFS::MAX_PATH - 1; ++i) path[pi++] = key[i];
    path[pi] = '\0';
    int r = VFS::read_file(path, buf, len);
    return static_cast<uint32_t>(r < 0 ? (uint32_t)(-1) : (uint32_t)r);
}

// SYS_NIBLIT_RESOURCE_INFO (208) — Return real kernel memory + CPU metrics
// in a simple key=value format.  This gives Niblit's self-optimisation loops
// accurate hardware data rather than cgroup approximations.
static uint32_t sys_niblit_resource_info(char* buf, uint32_t len) {
    if (!buf || len < 128) return static_cast<uint32_t>(-1);
    Memory::Stats s = Memory::stats();
    uint32_t free_mb = static_cast<uint32_t>(s.free_frames  * Memory::PAGE_SIZE / (1024 * 1024));
    uint32_t used_mb = static_cast<uint32_t>(s.used_frames  * Memory::PAGE_SIZE / (1024 * 1024));
    uint32_t total_mb= static_cast<uint32_t>(s.total_frames * Memory::PAGE_SIZE / (1024 * 1024));
    uint32_t uptime  = PIT::millis();
    uint32_t ncpu    = ACPI::available() ? static_cast<uint32_t>(ACPI::cpu_count()) : 1;
    uint32_t heap_b  = Heap::used_bytes();

    size_t pos = 0;
    // Inline helper lambdas not available in freestanding C++17 without libstdc++,
    // so use a local character appender pattern.
    auto ap = [&](const char* s2) {
        while (*s2 && pos < len - 1) buf[pos++] = *s2++;
        buf[pos] = '\0';
    };
    auto an = [&](uint32_t v) {
        char tmp[12]; int n = 0;
        if (!v) { tmp[n++]='0'; } else { while (v) { tmp[n++]='0'+(char)(v%10); v/=10; } }
        for (int i=n-1; i>=0 && pos<len-1; --i) buf[pos++]=tmp[i];
        buf[pos]='\0';
    };
    ap("ram_total_mb="); an(total_mb); ap("\n");
    ap("ram_free_mb=");  an(free_mb);  ap("\n");
    ap("ram_used_mb=");  an(used_mb);  ap("\n");
    ap("heap_bytes=");   an(heap_b);   ap("\n");
    ap("uptime_ms=");    an(uptime);   ap("\n");
    ap("cpu_count=");    an(ncpu);     ap("\n");
    return static_cast<uint32_t>(pos);
}

// SYS_NIBLIT_MMAP_RING (209) — Return the well-known virtual address of the
// shared NiblitRing IPC buffer so userspace (niblit_runner.c) can map it.
static uint32_t sys_niblit_mmap_ring(uint32_t /*hint*/) {
    return NIBLIT_RING_VADDR;
}

// ── Main dispatcher ───────────────────────────────────────────────────────────
static void syscall_handler(IDT::Registers* r) {
    uint32_t num  = r->eax;
    uint32_t arg1 = r->ebx;
    uint32_t arg2 = r->ecx;
    uint32_t arg3 = r->edx;

    uint32_t ret = 0;
    switch (num) {
        case SYS_EXIT:
            ret = sys_exit(arg1);
            break;
        case SYS_WRITE:
            ret = sys_write(arg1, reinterpret_cast<const char*>(arg2), arg3);
            break;
        case SYS_READ:
            ret = sys_read(arg1, reinterpret_cast<char*>(arg2), arg3);
            break;
        case SYS_YIELD:
            Process::yield();
            break;
        case SYS_GETPID:
            ret = sys_getpid();
            break;
        case SYS_SLEEP:
            ret = sys_sleep_ms(arg1);
            break;
        case SYS_MEM_INFO:
            ret = sys_mem_info(reinterpret_cast<char*>(arg1), arg2);
            break;
        case SYS_NIBLIT_QUERY:
            ret = sys_niblit_query(reinterpret_cast<const char*>(arg1));
            break;
        case SYS_NIBLIT_TOOL:
            ret = sys_niblit_tool(reinterpret_cast<const char*>(arg1),
                                  reinterpret_cast<const char*>(arg2));
            break;
        case SYS_PROC_LIST:
            ret = sys_proc_list(reinterpret_cast<char*>(arg1), arg2);
            break;
        case SYS_OPEN:
            ret = sys_open(reinterpret_cast<const char*>(arg1), arg2);
            break;
        case SYS_CLOSE:
            ret = sys_close(arg1);
            break;
        case SYS_MKDIR:
            ret = sys_mkdir(reinterpret_cast<const char*>(arg1));
            break;
        case SYS_EXEC:
            ret = sys_exec(reinterpret_cast<const char*>(arg1),
                           reinterpret_cast<const char*>(arg2));
            break;
        case SYS_FORK:
            ret = sys_fork();
            break;
        case SYS_WAITPID:
            ret = sys_waitpid(arg1, reinterpret_cast<uint32_t*>(arg2), arg3);
            break;
        case SYS_NIBLIT_SPAWN_REASONER:
            ret = sys_niblit_spawn_reasoner(reinterpret_cast<const char*>(arg1));
            break;
        case SYS_NIBLIT_KB_WRITE:
            ret = sys_niblit_kb_write(reinterpret_cast<const char*>(arg1),
                                      reinterpret_cast<const char*>(arg2));
            break;
        case SYS_NIBLIT_KB_READ:
            ret = sys_niblit_kb_read(reinterpret_cast<const char*>(arg1),
                                     reinterpret_cast<char*>(arg2), arg3);
            break;
        case SYS_NIBLIT_RESOURCE_INFO:
            ret = sys_niblit_resource_info(reinterpret_cast<char*>(arg1), arg2);
            break;
        case SYS_NIBLIT_MMAP_RING:
            ret = sys_niblit_mmap_ring(arg1);
            break;
        default:
            Serial::log("[SYSCALL] unknown #");
            Serial::write_dec(Serial::COM1, num);
            Serial::writeln(Serial::COM1, "");
            ret = static_cast<uint32_t>(-1);
            break;
    }

    r->eax = ret; // return value via eax
}

// ── init ──────────────────────────────────────────────────────────────────────
void init() {
    // INT 0x80 — DPL=3 so ring-3 code can invoke it.
    // We reuse the IDT gate mechanism; gate type 0xEE = 32-bit interrupt gate, DPL=3.
    // The IDT::register_handler path uses DPL=0 gates, so we set the gate directly.
    IDT::register_handler(0x80, syscall_handler);
    VGA::writeln("[SYSCALL] int 0x80 handler registered (22 syscalls incl. Niblit AI extensions).");
    Serial::logln("[SYSCALL] Ready.");
}

} // namespace Syscall
