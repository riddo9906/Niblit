// os/kernel/kernel.cpp — NiblitOS C++ kernel entry point
//
// Boot sequence (v3 — full driver suite):
//   VGA::init()            → text display available
//   Serial::init()         → COM1 debug output
//   GDT::init()            → flat segment model
//   IDT::init()            → exception handlers (PIC not yet remapped)
//   IRQ::init()            → remap PIC, register IRQ dispatch
//   Memory::init()         → physical page frame allocator
//   Paging::init()         → virtual memory + identity map (CR0.PG enabled)
//   Heap::init()           → kernel slab/page heap (kmalloc/kfree)
//   RTC::init()            → CMOS real-time clock
//   PIT::init()            → 100 Hz timer (drives scheduler preemption)
//   Process::init()        → round-robin task scheduler + idle task
//   VFS::init()            → virtual filesystem (RamFS at /, DevFS at /dev)
//   Keyboard::init()       → PS/2 keyboard (IRQ 1)
//   DMA::init()            → 8237 ISA DMA controllers
//   ACPI::init()           → ACPI tables (RSDP/RSDT/MADT/FADT)
//   PCI::init()            → PCI bus enumeration
//   ATA::init()            → ATA/IDE storage detection
//   Net::init()            → E1000 NIC + minimal IP stack
//   MSG::init()            → kernel IPC message queues
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
#include "irq.h"
#include "memory.h"
#include "paging.h"
#include "heap.h"
#include "rtc.h"
#include "pit.h"
#include "process.h"
#include "vfs.h"
#include "keyboard.h"
#include "dma.h"
#include "acpi.h"
#include "pci.h"
#include "ata.h"
#include "net.h"
#include "msg.h"
#include "syscall.h"
#include "elf_loader.h"
#include "procfs.h"
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
            "  help              — this help text\n"
            "  version           — kernel version\n"
            "  mem               — memory statistics\n"
            "  ps                — process list\n"
            "  ls <path>         — list VFS directory\n"
            "  cat <path>        — read a VFS file\n"
            "  write <path> <s>  — write string to VFS file\n"
            "  touch <path>      — create empty VFS file\n"
            "  mkdir <path>      — create VFS directory\n"
            "  exec  <path>      — load + run an ELF32 binary\n"
            "  ask <query>       — send query to Niblit AI\n"
            "  tool <name> <j>   — call a Niblit tool with JSON args\n"
            "  niblit-poll       — show pending Niblit AI responses\n"
            "  kbwrite <k> <v>   — write KB fact (key value) to /var/niblit/kb/\n"
            "  kbread  <k>       — read  KB fact from /var/niblit/kb/\n"
            "  procinfo          — refresh and dump all /proc files\n"
            "  uptime            — milliseconds since boot\n"
            "  date              — current date/time from RTC\n"
            "  pci               — list PCI devices\n"
            "  ata               — list detected ATA drives\n"
            "  net               — network interface status\n"
            "  ping <ip>         — ICMP ping (e.g. ping 192.168.1.1)\n"
            "  acpi              — ACPI info (CPUs, I/O APICs)\n"
            "  msg               — message queue status\n"
            "  syslog            — print syslog queue\n"
            "  reboot            — reboot via ACPI\n"
            "  poweroff          — power off via ACPI\n";
        VGA::write(help);
        Serial::write(Serial::COM1, help);

    } else if (kstrstartswith(cmd, "version")) {
        VGA::writeln("NiblitOS v3.0 — C++ kernel + Niblit AI tool layer");
        Serial::writeln(Serial::COM1, "NiblitOS v3.0");

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

    } else if (kstrstartswith(cmd, "exec ")) {
        const char* path = cmd + 5;
        int tid = ELF::exec(path, nullptr);
        if (tid > 0) {
            VGA::write("Launched tid="); VGA::write_dec((uint32_t)tid); VGA::newline();
        } else {
            VGA::write("exec failed: error="); VGA::write_dec((uint32_t)(-tid)); VGA::newline();
        }

    } else if (kstrstartswith(cmd, "write ")) {
        // write <path> <content>
        const char* rest = cmd + 6;
        char path[VFS::MAX_PATH] = {};
        size_t i = 0;
        while (rest[i] && rest[i] != ' ' && i < VFS::MAX_PATH - 1) { path[i] = rest[i]; ++i; }
        const char* content = (rest[i] == ' ') ? rest + i + 1 : "";
        int r = VFS::write_file(path, content);
        if (r >= 0) { VGA::write("Wrote "); VGA::write_dec((uint32_t)r); VGA::writeln(" bytes."); }
        else { VGA::writeln("write: error"); }

    } else if (kstrstartswith(cmd, "touch ")) {
        const char* path = cmd + 6;
        VFS::write_file(path, "");
        VGA::write("Touched "); VGA::writeln(path);

    } else if (kstrstartswith(cmd, "mkdir ")) {
        int r = VFS::mkdir(cmd + 6);
        VGA::writeln(r == 0 ? "Directory created." : "mkdir failed.");

    } else if (kstrstartswith(cmd, "niblit-poll")) {
        // Poll all response slots and print results
        bool found = false;
        for (uint32_t id = 1; id < 10; ++id) {
            NiblitResponse* resp = NiblitIface::poll_response(id);
            if (resp) {
                found = true;
                VGA::write("[NIBLIT] Response #"); VGA::write_dec(id);
                VGA::write(" status="); VGA::write_dec(resp->status);
                VGA::write(": ");
                VGA::writeln(resp->result);
            }
        }
        if (!found) VGA::writeln("[NIBLIT] No responses yet.");

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

    } else if (kstrstartswith(cmd, "date")) {
        char buf[32] = {};
        RTC::format_timestamp(buf, sizeof(buf));
        VGA::writeln(buf);
        Serial::writeln(Serial::COM1, buf);

    } else if (kstrstartswith(cmd, "pci")) {
        PCI::dump();

    } else if (kstrstartswith(cmd, "ata")) {
        ATA::dump();

    } else if (kstrstartswith(cmd, "net")) {
        Net::dump();

    } else if (kstrstartswith(cmd, "ping ")) {
        // ping <a.b.c.d>
        const char* s = cmd + 5;
        Net::IPv4Addr target = {};
        for (int i = 0; i < 4; ++i) {
            uint32_t v = 0;
            while (*s >= '0' && *s <= '9') v = v * 10 + (*s++ - '0');
            target.bytes[i] = (uint8_t)v;
            if (*s == '.') ++s;
        }
        VGA::write("PING ");
        for (int i = 0; i < 4; ++i) {
            VGA::write_dec(target.bytes[i]); if (i < 3) VGA::write(".");
        }
        VGA::writeln(" ...");
        int ms = Net::icmp_ping("eth0", target);
        if (ms >= 0) { VGA::write("Reply: "); VGA::write_dec((uint32_t)ms); VGA::writeln(" ms"); }
        else VGA::writeln("No reply (timeout or no NIC).");

    } else if (kstrstartswith(cmd, "acpi")) {
        if (ACPI::available()) {
            VGA::write("ACPI: CPUs="); VGA::write_dec((uint32_t)ACPI::cpu_count());
            VGA::write(" IOAPICs="); VGA::write_dec((uint32_t)ACPI::ioapic_count());
            VGA::write(" LAPIC=0x"); VGA::write_hex(ACPI::lapic_addr());
            VGA::newline();
            for (size_t i = 0; i < ACPI::cpu_count(); ++i) {
                ACPI::CpuInfo c = ACPI::cpu(i);
                VGA::write("  CPU"); VGA::write_dec((uint32_t)i);
                VGA::write(" APIC="); VGA::write_dec(c.apic_id);
                VGA::writeln(c.enabled ? " enabled" : " disabled");
            }
        } else {
            VGA::writeln("ACPI not available on this machine.");
        }

    } else if (kstrstartswith(cmd, "msg")) {
        MSG::dump();

    } else if (kstrstartswith(cmd, "syslog")) {
        MSG::QueueId qid = MSG::queue_open("syslog");
        MSG::Message m;
        bool any = false;
        while (MSG::msgrcv(qid, &m, MSG::MTYPE_SYSLOG) == 0) {
            m.data[m.data_len < MSG::MSG_MAX_DATA ? m.data_len : MSG::MSG_MAX_DATA - 1] = '\0';
            VGA::writeln((const char*)m.data);
            any = true;
        }
        if (!any) VGA::writeln("(syslog empty)");

    } else if (kstrstartswith(cmd, "reboot")) {
        ACPI::reboot();

    } else if (kstrstartswith(cmd, "poweroff")) {
        ACPI::power_off();

    } else if (kstrstartswith(cmd, "kbwrite ")) {
        // kbwrite <key> <value>
        const char* rest = cmd + 8;
        char key[64] = {};
        size_t ki = 0;
        while (rest[ki] && rest[ki] != ' ' && ki < 63) { key[ki] = rest[ki]; ++ki; }
        const char* value = (rest[ki] == ' ') ? rest + ki + 1 : "";
        char path[VFS::MAX_PATH] = "/var/niblit/kb/";
        size_t pi = 15;
        for (size_t i = 0; key[i] && pi < VFS::MAX_PATH - 1; ++i) path[pi++] = key[i];
        path[pi] = '\0';
        int r = VFS::write_file(path, value);
        if (r >= 0) {
            VGA::write("KB stored: "); VGA::writeln(key);
        } else {
            VGA::writeln("kbwrite: failed (VFS error)");
        }

    } else if (kstrstartswith(cmd, "kbread ")) {
        // kbread <key>
        const char* key = cmd + 7;
        char path[VFS::MAX_PATH] = "/var/niblit/kb/";
        size_t pi = 15;
        for (size_t i = 0; key[i] && pi < VFS::MAX_PATH - 1; ++i) path[pi++] = key[i];
        path[pi] = '\0';
        char buf[VFS::MAX_FILE_SZ] = {};
        int r = VFS::read_file(path, buf, sizeof(buf));
        if (r >= 0) {
            VGA::write(key); VGA::write(" = "); VGA::writeln(buf);
        } else {
            VGA::write("kbread: key not found: "); VGA::writeln(key);
        }

    } else if (kstrstartswith(cmd, "procinfo")) {
        // Refresh /proc and show a summary
        ProcFS::refresh();
        const char* files[] = {
            "/proc/version", "/proc/uptime", "/proc/meminfo",
            "/proc/niblit", nullptr
        };
        for (const char** f = files; *f; ++f) {
            VGA::write("── "); VGA::write(*f); VGA::writeln(" ──");
            char buf[VFS::MAX_FILE_SZ] = {};
            if (VFS::read_file(*f, buf, sizeof(buf)) >= 0) {
                VGA::write(buf);
                Serial::write(Serial::COM1, buf);
            }
        }

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
        // Accept input from either serial (COM1) or PS/2 keyboard
        char c = Serial::read_char(Serial::COM1);
        if (!c) c = Keyboard::read_char();
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

    // Create the KB directory tree for kernel-level fact storage
    VFS::mkdir("/var/niblit");
    VFS::mkdir("/var/niblit/kb");
    VFS::write_file("/var/niblit/kb/.version", "niblit-os-kb-v3.0\n");

    // Log boot event to MSG syslog
    MSG::syslog("[niblit-daemon] Boot complete. AI tool active.");

    // Publish a "kernel.boot" event on the MSG event bus
    const char* boot_msg = "NiblitOS v3.0 boot complete";
    MSG::publish("kernel.boot", MSG::MTYPE_KERNEL,
                 boot_msg, 28);

    // Post initial status requests to Niblit AI
    NiblitIface::ask("What is the current kernel status?");
    NiblitIface::call_tool("kernel_status", "{}");

    // Poll loop: check for responses and log them
    uint32_t tick = 0;
    while (true) {
        NiblitResponse* resp = NiblitIface::poll_response(1);
        if (resp && resp->status == 0) {
            VFS::write_file("/var/log/niblit.log", resp->result);
            MSG::syslog(resp->result);
        }
        // Every ~10 s (100 Hz PIT → 1000 ticks/s), post a heartbeat
        ++tick;
        if (tick % 1000 == 0) {
            MSG::syslog("[niblit-daemon] heartbeat");
            NiblitIface::call_tool("heartbeat", "{}");
            // Keep /proc files fresh so kernel-shell 'procinfo' shows live data
            ProcFS::refresh();
        }
        asm volatile("hlt");
    }
}

// ── kernel_main ───────────────────────────────────────────────────────────────
extern "C" void kernel_main(uint32_t mb2_magic, uint32_t mb2_info_addr) {

    // ── 1. VGA ────────────────────────────────────────────────────────────────
    VGA::init();
    VGA::set_colour(VGA::Colour::LIGHT_GREEN, VGA::Colour::BLACK);
    VGA::writeln("NiblitOS v3.0 — booting...");
    VGA::set_colour(VGA::Colour::LIGHT_GREY, VGA::Colour::BLACK);

    // ── 2. Serial (COM1) ──────────────────────────────────────────────────────
    if (Serial::init(Serial::COM1, 38400)) {
        Serial::writeln(Serial::COM1, "\r\n\r\n====================================");
        Serial::writeln(Serial::COM1, "NiblitOS v3.0 serial log active.");
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

    // ── 5. IDT (exception handlers) ───────────────────────────────────────────
    VGA::write("[BOOT] IDT... ");
    IDT::init();
    VGA::writeln("OK");

    // ── 6. IRQ manager (remap 8259 PIC, install dispatch stubs) ──────────────
    VGA::write("[BOOT] IRQ manager... ");
    IRQ::init();
    VGA::writeln("OK");

    // ── 7. Memory (parse Multiboot2 memory map) ───────────────────────────────
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

    // ── 8. Paging ────────────────────────────────────────────────────────────
    VGA::write("[BOOT] Paging... ");
    Paging::init(kernel_end_addr);
    VGA::writeln("OK");

    // ── 9. Kernel heap ────────────────────────────────────────────────────────
    VGA::write("[BOOT] Heap... ");
    Heap::init();
    VGA::writeln("OK");

    // ── 10. RTC ──────────────────────────────────────────────────────────────
    VGA::write("[BOOT] RTC... ");
    RTC::init();
    // (RTC::init prints its own timestamp)

    // ── 11. PIT timer ─────────────────────────────────────────────────────────
    VGA::write("[BOOT] PIT timer... ");
    PIT::init(100);
    VGA::writeln("OK");

    // ── 12. Process scheduler ─────────────────────────────────────────────────
    VGA::write("[BOOT] Scheduler... ");
    Process::init();
    VGA::writeln("OK");

    // ── 13. Virtual Filesystem ────────────────────────────────────────────────
    VGA::write("[BOOT] VFS... ");
    VFS::init();
    VGA::writeln("OK");

    // ── 13a. ProcFS (/proc pseudo-filesystem) ─────────────────────────────────
    VGA::write("[BOOT] ProcFS... ");
    ProcFS::init(); // prints "OK" itself

    // ── 14. Keyboard (PS/2) ───────────────────────────────────────────────────
    VGA::write("[BOOT] Keyboard... ");
    Keyboard::init();
    VGA::writeln("OK");

    // ── 15. DMA controllers ───────────────────────────────────────────────────
    VGA::write("[BOOT] DMA... ");
    DMA::init();

    // ── 16. ACPI ─────────────────────────────────────────────────────────────
    VGA::write("[BOOT] ACPI... ");
    if (ACPI::init()) {
        VGA::writeln("OK");
    } else {
        VGA::writeln("(not available)");
    }

    // ── 17. PCI bus ───────────────────────────────────────────────────────────
    VGA::write("[BOOT] PCI... ");
    PCI::init();

    // ── 18. ATA storage ──────────────────────────────────────────────────────
    VGA::write("[BOOT] ATA... ");
    ATA::init();

    // ── 19. Network ───────────────────────────────────────────────────────────
    VGA::write("[BOOT] Network... ");
    Net::init();

    // ── 20. MSG IPC subsystem ─────────────────────────────────────────────────
    VGA::write("[BOOT] MSG IPC... ");
    MSG::init();

    // ── 21. Syscall interface ─────────────────────────────────────────────────
    VGA::write("[BOOT] Syscalls... ");
    Syscall::init();
    VGA::writeln("OK");

    // ── 22. Niblit AI tool interface ──────────────────────────────────────────
    VGA::write("[BOOT] Niblit AI interface... ");
    NiblitIface::init();
    VGA::writeln("OK");

    // ── 23. Enable interrupts ─────────────────────────────────────────────────
    asm volatile("sti");
    VGA::writeln("[BOOT] Interrupts enabled.");
    Serial::logln("[BOOT] All subsystems initialised. Interrupts ON.");

    // Log boot event to syslog
    {
        char ts[32] = {};
        RTC::format_timestamp(ts, sizeof(ts));
        MSG::syslog("NiblitOS booted at ");
        MSG::syslog(ts);
    }

    // ── 24. Launch kernel tasks ────────────────────────────────────────────────
    Process::create("niblit-daemon", niblit_daemon_task);
    Process::create("niblit-shell",  niblit_shell_task);

    // ── 25. Boot summary ──────────────────────────────────────────────────────
    VGA::set_colour(VGA::Colour::YELLOW, VGA::Colour::BLACK);
    VGA::writeln("");
    VGA::writeln("  ╔═══════════════════════════════════════════╗");
    VGA::writeln("  ║  NiblitOS v3.0 — Full Driver Suite        ║");
    VGA::writeln("  ║  Niblit AI tool: ACTIVE  (PID 1 = AI)     ║");
    VGA::writeln("  ║  ACPI | PCI | ATA | NET | MSG: ACTIVE     ║");
    VGA::writeln("  ║  /proc: READY  |  /var/niblit/kb: READY   ║");
    VGA::writeln("  ║  Shell: serial COM1 + PS/2 keyboard       ║");
    VGA::writeln("  ╚═══════════════════════════════════════════╝");
    VGA::set_colour(VGA::Colour::LIGHT_GREY, VGA::Colour::BLACK);

    Memory::Stats ms = Memory::stats();
    VGA::write("  RAM: "); VGA::write_dec(ms.free_frames * Memory::PAGE_SIZE / (1024*1024));
    VGA::write(" MiB free / ");
    VGA::write_dec(ms.total_frames * Memory::PAGE_SIZE / (1024*1024));
    VGA::writeln(" MiB total");
    VGA::write("  Heap used: "); VGA::write_dec(Heap::used_bytes()); VGA::writeln(" bytes");
    VGA::write("  Uptime: "); VGA::write_dec(PIT::millis()); VGA::writeln(" ms");
    VGA::write("  PCI devices: "); VGA::write_dec((uint32_t)PCI::device_count()); VGA::newline();
    VGA::write("  ATA drives:  "); VGA::write_dec((uint32_t)ATA::drive_count()); VGA::newline();
    VGA::write("  Net ifaces:  "); VGA::write_dec((uint32_t)Net::iface_count()); VGA::newline();
    VGA::newline();
    Process::dump();

    // ── 26. Idle loop ─────────────────────────────────────────────────────────
    while (true) {
        asm volatile("hlt");
    }
}
