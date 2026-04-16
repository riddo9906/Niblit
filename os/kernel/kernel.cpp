// os/kernel/kernel.cpp — NiblitOS C++ kernel entry point
//
// Boot sequence (v2 — extended capabilities):
//   VGA::init()            → text display available
//   Serial::init()         → COM1 debug output
//   GDT::init()            → flat segment model
//   IDT::init()            → exception + IRQ handlers (PIC remapped)
//   Memory::init()         → physical page frame allocator
//   Paging::init()         → virtual memory + identity map (CR0.PG enabled)
//   Heap::init()           → kernel slab/page heap (kmalloc/kfree)
//   PIT::init()            → 100 Hz timer (drives scheduler preemption)
//   Process::init()        → round-robin task scheduler + idle task
//   VFS::init()            → virtual filesystem (RamFS at /, DevFS at /dev)
//   Syscall::init()        → int 0x80 system call table
//   NiblitIface::init()    → Niblit AI tool IPC ring buffer
//   sti                    → enable interrupts
//   create niblit-daemon   → Niblit AI tool kernel task
//   create niblit-shell    → interactive kernel shell task
//   idle loop              → halts until next PIT tick
//
// Build: i686-elf-g++ -std=c++17 -ffreestanding -O2 -Wall -Wextra
//        -fno-exceptions -fno-rtti -c kernel.cpp -o kernel.o

#include "vga.h"
#include "serial.h"
#include "gdt.h"
#include "idt.h"
#include "memory.h"
#include "paging.h"
#include "heap.h"
#include "pit.h"
#include "process.h"
#include "vfs.h"
#include "syscall.h"
#include "niblit_iface.h"
#include <stdint.h>

// ── Multiboot2 constants ──────────────────────────────────────────────────────
static constexpr uint32_t MULTIBOOT2_MAGIC = 0x36D76289;

// ── Multiboot2 tag traversal ──────────────────────────────────────────────────
struct Mb2Tag {
    uint32_t type;
    uint32_t size;
};

struct Mb2MemMap {
    uint32_t type;
    uint32_t size;
    uint32_t entry_size;
    uint32_t entry_version;
    // followed by entries
};

// Linker-defined symbol: address immediately after the kernel binary.
extern uint8_t _kernel_end[];

// ── Panic ─────────────────────────────────────────────────────────────────────
static void panic(const char* msg) __attribute__((noreturn));
static void panic(const char* msg) {
    VGA::set_colour(VGA::Colour::WHITE, VGA::Colour::RED);
    VGA::writeln("");
    VGA::write("*** KERNEL PANIC: ");
    VGA::writeln(msg);
    Serial::log("KERNEL PANIC: ");
    Serial::writeln(Serial::COM1, msg);
    while (true) {
        asm volatile("cli; hlt");
    }
}

// ── Kernel shell task ─────────────────────────────────────────────────────────
// A minimal interactive shell that reads commands from the serial port
// (or VGA keyboard in a future version) and dispatches them.
static char s_shell_buf[256];

static void kstrncpy_s(char* dst, const char* src, size_t n) {
    size_t i = 0;
    for (; i < n - 1 && src[i]; ++i) dst[i] = src[i];
    dst[i] = '\0';
}

static bool kstrstartswith(const char* str, const char* prefix) {
    while (*prefix) { if (*str++ != *prefix++) return false; }
    return true;
}

static void shell_print_prompt() {
    VGA::set_colour(VGA::Colour::LIGHT_GREEN, VGA::Colour::BLACK);
    VGA::write("niblit-os> ");
    VGA::set_colour(VGA::Colour::LIGHT_GREY, VGA::Colour::BLACK);
    Serial::log("niblit-os> ");
}

static void shell_handle_command(const char* cmd) {
    if (!*cmd) return;

    if (kstrstartswith(cmd, "help")) {
        const char* help =
            "NiblitOS Shell Commands:\n"
            "  help            — this help text\n"
            "  version         — kernel version\n"
            "  mem             — memory statistics\n"
            "  ps              — process list\n"
            "  ls <path>       — list VFS directory\n"
            "  cat <path>      — read a VFS file\n"
            "  ask <query>     — send query to Niblit AI\n"
            "  tool <name> <j> — call a Niblit tool with JSON args\n"
            "  uptime          — milliseconds since boot\n";
        VGA::write(help);
        Serial::write(Serial::COM1, help);

    } else if (kstrstartswith(cmd, "version")) {
        VGA::writeln("NiblitOS v2.0 — C++ kernel + Niblit AI tool layer");
        Serial::writeln(Serial::COM1, "NiblitOS v2.0");

    } else if (kstrstartswith(cmd, "mem")) {
        Memory::Stats s = Memory::stats();
        VGA::write("  Free: "); VGA::write_dec(s.free_frames * Memory::PAGE_SIZE / (1024*1024)); VGA::writeln(" MiB");
        VGA::write("  Used: "); VGA::write_dec(s.used_frames * Memory::PAGE_SIZE / (1024*1024)); VGA::writeln(" MiB");
        VGA::write("  Heap: "); VGA::write_dec(Heap::used_bytes()); VGA::writeln(" bytes");
        Serial::log("mem free="); Serial::write_dec(Serial::COM1, s.free_frames); Serial::writeln(Serial::COM1, " frames");

    } else if (kstrstartswith(cmd, "ps")) {
        Process::dump();

    } else if (kstrstartswith(cmd, "ls ")) {
        char buf[1024] = {};
        VFS::listdir(cmd + 3, buf, sizeof(buf));
        VGA::write(buf);
        Serial::write(Serial::COM1, buf);

    } else if (kstrstartswith(cmd, "cat ")) {
        char buf[VFS::MAX_FILE_SZ] = {};
        int r = VFS::read_file(cmd + 4, buf, sizeof(buf));
        if (r < 0) {
            VGA::writeln("cat: file not found");
        } else {
            VGA::write(buf);
            Serial::write(Serial::COM1, buf);
        }

    } else if (kstrstartswith(cmd, "ask ")) {
        uint32_t id = NiblitIface::send_request(0, "", cmd + 4);
        VGA::write("Niblit query #"); VGA::write_dec(id); VGA::writeln(" posted.");

    } else if (kstrstartswith(cmd, "tool ")) {
        // tool <name> <json>
        const char* rest = cmd + 5;
        char tool[64] = {};
        size_t i = 0;
        while (rest[i] && rest[i] != ' ' && i < 63) { tool[i] = rest[i]; ++i; }
        const char* args = (rest[i] == ' ') ? rest + i + 1 : "{}";
        uint32_t id = NiblitIface::send_request(1, tool, args);
        VGA::write("Niblit tool '"); VGA::write(tool); VGA::write("' #"); VGA::write_dec(id); VGA::writeln(" posted.");

    } else if (kstrstartswith(cmd, "uptime")) {
        VGA::write("Uptime: "); VGA::write_dec(PIT::millis()); VGA::writeln(" ms");

    } else {
        VGA::write("Unknown command: "); VGA::writeln(cmd);
        Serial::log("Unknown: "); Serial::writeln(Serial::COM1, cmd);
    }
}

static void niblit_shell_task() {
    VGA::set_colour(VGA::Colour::LIGHT_CYAN, VGA::Colour::BLACK);
    VGA::writeln("[shell] NiblitOS interactive shell started.");
    VGA::writeln("[shell] Type 'help' for commands. Input via serial (COM1).");
    VGA::set_colour(VGA::Colour::LIGHT_GREY, VGA::Colour::BLACK);
    Serial::writeln(Serial::COM1, "\r\nNiblitOS Shell ready. Type 'help'.");

    size_t pos = 0;
    shell_print_prompt();

    while (true) {
        char c = Serial::read_char(Serial::COM1);
        if (!c) {
            asm volatile("hlt"); // yield
            continue;
        }

        Serial::put_char(Serial::COM1, c); // echo

        if (c == '\r' || c == '\n') {
            s_shell_buf[pos] = '\0';
            VGA::newline();
            if (pos > 0) shell_handle_command(s_shell_buf);
            pos = 0;
            shell_print_prompt();
        } else if (c == 0x7F || c == '\b') { // backspace
            if (pos > 0) { --pos; Serial::log("\b \b"); }
        } else if (pos < sizeof(s_shell_buf) - 1) {
            s_shell_buf[pos++] = c;
            VGA::put_char(c);
        }
    }
}

// ── Niblit daemon task ────────────────────────────────────────────────────────
static void niblit_daemon_task() {
    VGA::set_colour(VGA::Colour::LIGHT_CYAN, VGA::Colour::BLACK);
    VGA::writeln("[niblit-daemon] Niblit AI tool daemon started.");
    VGA::set_colour(VGA::Colour::LIGHT_GREY, VGA::Colour::BLACK);
    Serial::logln("[niblit-daemon] Running.");

    // Write a boot message to the VFS log
    VFS::write_file("/var/log/niblit.log", "Niblit AI daemon started at boot.\n");

    // Post initial status requests
    NiblitIface::ask("What is the current kernel status?");
    NiblitIface::call_tool("kernel_status", "{}");

    // Poll loop: check for responses and log them
    while (true) {
        NiblitResponse* resp = NiblitIface::poll_response(1);
        if (resp && resp->status == 0) {
            VFS::write_file("/var/log/niblit.log", resp->result);
        }
        asm volatile("hlt");
    }
}

// ── kernel_main ───────────────────────────────────────────────────────────────
extern "C" void kernel_main(uint32_t mb2_magic, uint32_t mb2_info_addr) {

    // ── 1. VGA ────────────────────────────────────────────────────────────────
    VGA::init();
    VGA::set_colour(VGA::Colour::LIGHT_GREEN, VGA::Colour::BLACK);
    VGA::writeln("NiblitOS v2.0 — booting...");
    VGA::set_colour(VGA::Colour::LIGHT_GREY, VGA::Colour::BLACK);

    // ── 2. Serial (COM1) ──────────────────────────────────────────────────────
    if (Serial::init(Serial::COM1, 38400)) {
        Serial::writeln(Serial::COM1, "\r\n\r\n====================================");
        Serial::writeln(Serial::COM1, "NiblitOS v2.0 serial log active.");
        Serial::writeln(Serial::COM1, "====================================");
        VGA::writeln("[BOOT] Serial COM1 ready.");
    } else {
        VGA::writeln("[BOOT] Serial COM1 not present (continuing).");
    }

    // ── 3. Multiboot2 sanity check ────────────────────────────────────────────
    if (mb2_magic != MULTIBOOT2_MAGIC) {
        panic("Invalid Multiboot2 magic — not loaded by a Multiboot2 bootloader.");
    }

    // ── 4. GDT ────────────────────────────────────────────────────────────────
    VGA::write("[BOOT] GDT... ");
    GDT::init();
    VGA::writeln("OK");

    // ── 5. IDT + PIC ─────────────────────────────────────────────────────────
    VGA::write("[BOOT] IDT... ");
    IDT::init();
    VGA::writeln("OK");

    // ── 6. Memory (parse Multiboot2 memory map) ───────────────────────────────
    VGA::write("[BOOT] Memory... ");
    uint32_t kernel_end_addr = 0;
    {
        uint32_t mmap_addr   = 0;
        uint32_t mmap_length = 0;

        uint32_t offset     = 8;
        uint32_t total_size = *reinterpret_cast<uint32_t*>(mb2_info_addr);

        while (offset < total_size) {
            const Mb2Tag* tag = reinterpret_cast<const Mb2Tag*>(mb2_info_addr + offset);
            if (tag->type == 0) break;
            if (tag->type == 6) {
                mmap_addr   = mb2_info_addr + offset + 16;
                mmap_length = tag->size - 16;
            }
            offset += (tag->size + 7) & ~7u;
        }

        kernel_end_addr = reinterpret_cast<uint32_t>(_kernel_end);
        Memory::init(mmap_addr, mmap_length, kernel_end_addr);
    }
    VGA::writeln("OK");

    // ── 7. Paging ────────────────────────────────────────────────────────────
    VGA::write("[BOOT] Paging... ");
    Paging::init(kernel_end_addr);
    VGA::writeln("OK");

    // ── 8. Kernel heap ────────────────────────────────────────────────────────
    VGA::write("[BOOT] Heap... ");
    Heap::init();
    VGA::writeln("OK");

    // ── 9. PIT timer ─────────────────────────────────────────────────────────
    VGA::write("[BOOT] PIT timer... ");
    PIT::init(100);
    VGA::writeln("OK");

    // ── 10. Process scheduler ─────────────────────────────────────────────────
    VGA::write("[BOOT] Scheduler... ");
    Process::init();
    VGA::writeln("OK");

    // ── 11. Virtual Filesystem ────────────────────────────────────────────────
    VGA::write("[BOOT] VFS... ");
    VFS::init();
    VGA::writeln("OK");

    // ── 12. Syscall interface ─────────────────────────────────────────────────
    VGA::write("[BOOT] Syscalls... ");
    Syscall::init();
    VGA::writeln("OK");

    // ── 13. Niblit AI tool interface ──────────────────────────────────────────
    VGA::write("[BOOT] Niblit AI interface... ");
    NiblitIface::init();
    VGA::writeln("OK");

    // ── 14. Enable interrupts ─────────────────────────────────────────────────
    asm volatile("sti");
    VGA::writeln("[BOOT] Interrupts enabled.");
    Serial::logln("[BOOT] All subsystems initialised. Interrupts ON.");

    // ── 15. Launch kernel tasks ────────────────────────────────────────────────
    Process::create("niblit-daemon", niblit_daemon_task);
    Process::create("niblit-shell",  niblit_shell_task);

    // ── 16. Boot summary ──────────────────────────────────────────────────────
    VGA::set_colour(VGA::Colour::YELLOW, VGA::Colour::BLACK);
    VGA::writeln("");
    VGA::writeln("  ╔═══════════════════════════════════════╗");
    VGA::writeln("  ║  NiblitOS v2.0 — Fully Operational   ║");
    VGA::writeln("  ║  Niblit AI tool: ACTIVE               ║");
    VGA::writeln("  ║  Shell: serial COM1 (-serial stdio)   ║");
    VGA::writeln("  ╚═══════════════════════════════════════╝");
    VGA::set_colour(VGA::Colour::LIGHT_GREY, VGA::Colour::BLACK);

    Memory::Stats ms = Memory::stats();
    VGA::write("  RAM: "); VGA::write_dec(ms.free_frames * Memory::PAGE_SIZE / (1024*1024));
    VGA::write(" MiB free / ");
    VGA::write_dec(ms.total_frames * Memory::PAGE_SIZE / (1024*1024));
    VGA::writeln(" MiB total");
    VGA::write("  Heap used: "); VGA::write_dec(Heap::used_bytes()); VGA::writeln(" bytes");
    VGA::write("  Uptime: "); VGA::write_dec(PIT::millis()); VGA::writeln(" ms");
    VGA::newline();
    Process::dump();

    // ── 17. Idle loop ─────────────────────────────────────────────────────────
    while (true) {
        asm volatile("hlt");
    }
}

