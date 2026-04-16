// os/kernel/syscall.cpp — int 0x80 system call dispatcher
#include "syscall.h"
#include "idt.h"
#include "vga.h"
#include "serial.h"
#include "memory.h"
#include "process.h"
#include "pit.h"
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
    VGA::writeln("[SYSCALL] int 0x80 handler registered (15 syscalls).");
    Serial::logln("[SYSCALL] Ready.");
}

} // namespace Syscall
