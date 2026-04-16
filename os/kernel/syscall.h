// os/kernel/syscall.h — int 0x80 system call interface
//
// User programs invoke system calls by executing `int 0x80` with:
//   eax = syscall number
//   ebx = arg1
//   ecx = arg2
//   edx = arg3
//
// The return value is placed in eax.
//
// Syscall numbers mirror a Linux-compatible subset so that a future
// musl libc port requires minimal changes.
#pragma once
#include <stdint.h>
#include <stddef.h>

// ── Syscall numbers ───────────────────────────────────────────────────────────
static constexpr uint32_t SYS_EXIT          =  1;
static constexpr uint32_t SYS_WRITE         =  4;  // write(fd, buf, len)
static constexpr uint32_t SYS_READ          =  3;  // read(fd, buf, len)
static constexpr uint32_t SYS_OPEN          =  5;  // open(path, flags)
static constexpr uint32_t SYS_CLOSE         =  6;  // close(fd)
static constexpr uint32_t SYS_MKDIR         = 39;  // mkdir(path, mode)
static constexpr uint32_t SYS_YIELD         = 24;  // sched_yield()
static constexpr uint32_t SYS_GETPID        = 20;  // getpid()
static constexpr uint32_t SYS_SLEEP         = 162; // nanosleep-like (arg1 = ms)
static constexpr uint32_t SYS_MEM_INFO      = 200; // NiblitOS extension: memory stats
static constexpr uint32_t SYS_NIBLIT_QUERY  = 201; // NiblitOS extension: AI query
static constexpr uint32_t SYS_NIBLIT_TOOL   = 202; // NiblitOS extension: AI tool call
static constexpr uint32_t SYS_PROC_LIST     = 203; // NiblitOS extension: process list
static constexpr uint32_t SYS_EXEC          = 204; // NiblitOS extension: exec ELF

// File descriptors
static constexpr uint32_t FD_STDIN  = 0;
static constexpr uint32_t FD_STDOUT = 1;
static constexpr uint32_t FD_STDERR = 2;

namespace Syscall {

// Saved userspace register state (layout matches the IDT push order).
struct Regs {
    uint32_t ds;
    uint32_t edi, esi, ebp, esp_ignored;
    uint32_t ebx, edx, ecx, eax;       // eax = syscall number on entry
    uint32_t int_no, err_code;
    uint32_t eip, cs, eflags, useresp, ss;
};

// Initialise the syscall handler (registers INT 0x80 in the IDT).
void init();

} // namespace Syscall
