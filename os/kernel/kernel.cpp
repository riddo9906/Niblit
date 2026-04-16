// os/kernel/kernel.cpp — NiblitOS C++ kernel entry point
//
// This is the first C++ function called by the boot stub.
// It initialises all kernel subsystems in order and then enters the
// idle loop (which the scheduler will preempt via the PIT timer IRQ).
//
// Boot sequence:
//   VGA::init()            → text display available
//   GDT::init()            → flat segment model
//   IDT::init()            → exception + IRQ handlers
//   Memory::init()         → physical page allocator
//   Process::init()        → task scheduler + idle task
//   NiblitIface::init()    → Niblit AI tool interface
//   (enable interrupts)
//   (create niblit_daemon task)
//   (idle loop)
//
// Build with: i686-elf-g++ -std=c++17 -ffreestanding -O2 -Wall -Wextra
//             -fno-exceptions -fno-rtti -c kernel.cpp -o kernel.o

#include "vga.h"
#include "gdt.h"
#include "idt.h"
#include "memory.h"
#include "process.h"
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
    while (true) {
        asm volatile("cli; hlt");
    }
}

// ── Niblit daemon task ────────────────────────────────────────────────────────
// This kernel task represents the Niblit AI tool's "presence" in the OS.
// In a full implementation it would exec() the Niblit Python process via a
// userland ELF loader; for now it sends a hello query to illustrate the
// interface and then sleeps in an event loop.
static void niblit_daemon_task() {
    VGA::set_colour(VGA::Colour::LIGHT_CYAN, VGA::Colour::BLACK);
    VGA::writeln("[niblit-daemon] Niblit AI tool daemon started.");
    VGA::set_colour(VGA::Colour::LIGHT_GREY, VGA::Colour::BLACK);

    // Demonstrate the AI tool interface: post a kernel-status query to Niblit.
    NiblitIface::ask("What is the current kernel status?");
    NiblitIface::call_tool("kernel_status", "{}");

    // Event loop: in a real OS this would block on the IPC queue waiting for
    // kernel requests and dispatching them to the Niblit Python process.
    while (true) {
        asm volatile("hlt");   // yield until the next timer tick
    }
}

// ── kernel_main ───────────────────────────────────────────────────────────────
extern "C" void kernel_main(uint32_t mb2_magic, uint32_t mb2_info_addr) {

    // ── 1. VGA ────────────────────────────────────────────────────────────────
    VGA::init();
    VGA::set_colour(VGA::Colour::LIGHT_GREEN, VGA::Colour::BLACK);
    VGA::writeln("NiblitOS v1.0 — booting...");
    VGA::set_colour(VGA::Colour::LIGHT_GREY, VGA::Colour::BLACK);

    // ── 2. Multiboot2 sanity check ────────────────────────────────────────────
    if (mb2_magic != MULTIBOOT2_MAGIC) {
        panic("Invalid Multiboot2 magic — not loaded by a Multiboot2 bootloader.");
    }

    // ── 3. GDT ────────────────────────────────────────────────────────────────
    VGA::write("[BOOT] GDT... ");
    GDT::init();
    VGA::writeln("OK");

    // ── 4. IDT + PIC ─────────────────────────────────────────────────────────
    VGA::write("[BOOT] IDT... ");
    IDT::init();
    VGA::writeln("OK");

    // ── 5. Memory (parse Multiboot2 memory map) ────────────────────────────
    VGA::write("[BOOT] Memory... ");
    {
        uint32_t mmap_addr   = 0;
        uint32_t mmap_length = 0;

        // Walk Multiboot2 tags (first 8 bytes are total_size + reserved).
        uint32_t offset = 8;
        uint32_t total_size = *reinterpret_cast<uint32_t*>(mb2_info_addr);

        while (offset < total_size) {
            const Mb2Tag* tag = reinterpret_cast<const Mb2Tag*>(mb2_info_addr + offset);
            if (tag->type == 0) break;              // end tag
            if (tag->type == 6) {                   // memory map
                const auto* mm = reinterpret_cast<const Mb2MemMap*>(tag);
                mmap_addr   = mb2_info_addr + offset + 16;  // skip tag header
                mmap_length = tag->size - 16;
            }
            offset += (tag->size + 7) & ~7u;        // 8-byte aligned
        }

        uint32_t kernel_end = reinterpret_cast<uint32_t>(_kernel_end);
        Memory::init(mmap_addr, mmap_length, kernel_end);
    }
    VGA::writeln("OK");

    // ── 6. Process scheduler ──────────────────────────────────────────────────
    VGA::write("[BOOT] Scheduler... ");
    Process::init();
    VGA::writeln("OK");

    // ── 7. Niblit AI tool interface ───────────────────────────────────────────
    VGA::write("[BOOT] Niblit AI interface... ");
    NiblitIface::init();
    VGA::writeln("OK");

    // ── 8. Enable interrupts ──────────────────────────────────────────────────
    asm volatile("sti");
    VGA::writeln("[BOOT] Interrupts enabled.");

    // ── 9. Launch Niblit daemon task ──────────────────────────────────────────
    Process::create("niblit-daemon", niblit_daemon_task);

    // ── 10. Print boot summary ────────────────────────────────────────────────
    VGA::set_colour(VGA::Colour::YELLOW, VGA::Colour::BLACK);
    VGA::writeln("");
    VGA::writeln("  NiblitOS is running.  Niblit AI tool is active.");
    VGA::set_colour(VGA::Colour::LIGHT_GREY, VGA::Colour::BLACK);

    Memory::Stats ms = Memory::stats();
    VGA::write("  RAM: ");
    VGA::write_dec(ms.free_frames * Memory::PAGE_SIZE / (1024 * 1024));
    VGA::write(" MiB free / ");
    VGA::write_dec(ms.total_frames * Memory::PAGE_SIZE / (1024 * 1024));
    VGA::writeln(" MiB total");

    Process::dump();

    // ── 11. Idle loop (scheduler will preempt via PIT IRQ) ────────────────────
    while (true) {
        asm volatile("hlt");
    }
}
