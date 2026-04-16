// os/kernel/paging.cpp — x86 two-level 4 KiB paging implementation
//
// Page directory and the initial kernel page table are stored in BSS
// (statically allocated, 4 KiB aligned).  Additional page tables are
// allocated dynamically from Memory::alloc_frame().
#include "paging.h"
#include "memory.h"
#include "niblit_iface.h"
#include "serial.h"
#include "vga.h"

namespace Paging {

// ── Types ─────────────────────────────────────────────────────────────────────
using PDE = uint32_t;   // page-directory entry
using PTE = uint32_t;   // page-table entry

// ── Static page directory (must be 4 KiB aligned) ────────────────────────────
static PDE  s_page_dir[1024]   __attribute__((aligned(PAGE_SIZE)));

// Static page table for the first 4 MiB (kernel code + data).
static PTE  s_pt_low[1024]     __attribute__((aligned(PAGE_SIZE)));

// Static page table for 4–8 MiB (extra kernel data / stacks).
static PTE  s_pt_high[1024]    __attribute__((aligned(PAGE_SIZE)));

// ── helpers ───────────────────────────────────────────────────────────────────
static inline uint32_t pd_index(uint32_t virt) { return virt >> 22; }
static inline uint32_t pt_index(uint32_t virt) { return (virt >> 12) & 0x3FF; }
static inline uint32_t frame_addr(uint32_t entry) { return entry & ~0xFFFu; }

// ── TLB flush ─────────────────────────────────────────────────────────────────
void flush_tlb(uint32_t virt) {
    asm volatile("invlpg [%0]" : : "r"(virt) : "memory");
}

// ── Page fault handler ────────────────────────────────────────────────────────
#include "idt.h"
static void page_fault_handler(IDT::Registers* regs) {
    uint32_t fault_addr;
    asm volatile("mov %0, cr2" : "=r"(fault_addr));

    VGA::set_colour(VGA::Colour::WHITE, VGA::Colour::RED);
    VGA::write("*** PAGE FAULT at virt=");
    VGA::write_hex(fault_addr);
    VGA::write(" eip=");
    VGA::write_hex(regs->eip);
    VGA::write(" err=");
    VGA::write_hex(regs->err_code);
    VGA::newline();

    Serial::write(Serial::COM1, "PAGE FAULT virt=");
    Serial::write_hex(Serial::COM1, fault_addr);
    Serial::writeln(Serial::COM1, "");

    while (true) { asm volatile("cli; hlt"); }
}

// ── Public ────────────────────────────────────────────────────────────────────
void map_page(uint32_t virt, uint32_t phys, uint32_t flags) {
    uint32_t pdi = pd_index(virt);
    uint32_t pti = pt_index(virt);

    PTE* pt;
    if (!(s_page_dir[pdi] & PAGE_PRESENT)) {
        // Allocate a new page table frame
        uint32_t frame = Memory::alloc_frame();
        if (!frame) {
            VGA::writeln("[PAGING] ERROR: OOM allocating page table.");
            return;
        }
        pt = reinterpret_cast<PTE*>(frame);
        // Zero the new table
        for (size_t i = 0; i < 1024; ++i) pt[i] = 0;
        s_page_dir[pdi] = frame | PAGE_PRESENT | PAGE_WRITABLE | (flags & PAGE_USER);
    } else {
        pt = reinterpret_cast<PTE*>(frame_addr(s_page_dir[pdi]));
    }

    pt[pti] = (phys & ~0xFFFu) | flags | PAGE_PRESENT;
    flush_tlb(virt);
}

void unmap_page(uint32_t virt) {
    uint32_t pdi = pd_index(virt);
    uint32_t pti = pt_index(virt);

    if (!(s_page_dir[pdi] & PAGE_PRESENT)) return;
    PTE* pt = reinterpret_cast<PTE*>(frame_addr(s_page_dir[pdi]));
    pt[pti] = 0;
    flush_tlb(virt);
}

uint32_t virt_to_phys(uint32_t virt) {
    uint32_t pdi = pd_index(virt);
    uint32_t pti = pt_index(virt);
    if (!(s_page_dir[pdi] & PAGE_PRESENT)) return 0;
    PTE* pt = reinterpret_cast<PTE*>(frame_addr(s_page_dir[pdi]));
    if (!(pt[pti] & PAGE_PRESENT)) return 0;
    return frame_addr(pt[pti]) | (virt & 0xFFF);
}

void init(uint32_t kernel_end) {
    // Register page-fault handler (INT 14)
    IDT::register_handler(14, page_fault_handler);

    // ── Identity-map 0..4 MiB via s_pt_low ───────────────────────────────────
    for (size_t i = 0; i < 1024; ++i) {
        s_pt_low[i] = (i * PAGE_SIZE) | PAGE_PRESENT | PAGE_WRITABLE;
    }
    s_page_dir[0] = reinterpret_cast<uint32_t>(s_pt_low) | PAGE_PRESENT | PAGE_WRITABLE;

    // ── Identity-map 4..8 MiB via s_pt_high ──────────────────────────────────
    for (size_t i = 0; i < 1024; ++i) {
        s_pt_high[i] = (4 * 1024 * 1024 + i * PAGE_SIZE) | PAGE_PRESENT | PAGE_WRITABLE;
    }
    s_page_dir[1] = reinterpret_cast<uint32_t>(s_pt_high) | PAGE_PRESENT | PAGE_WRITABLE;

    // ── Map Niblit ring buffer virtual address ─────────────────────────────────
    // NiblitIface::init() allocates the physical frame; map it at NIBLIT_RING_VADDR.
    // (This is done after NiblitIface::init() in kernel.cpp — see the init order comment.)

    // ── Load CR3 and enable paging ────────────────────────────────────────────
    asm volatile(
        "mov cr3, %0\n\t"
        "mov eax, cr0\n\t"
        "or  eax, 0x80000000\n\t"
        "mov cr0, eax\n\t"
        : : "r"(s_page_dir) : "eax"
    );

    VGA::write("[PAGING] Enabled. Kernel identity-mapped 0-8 MiB. kernel_end=");
    VGA::write_hex(kernel_end);
    VGA::newline();
    Serial::logln("[PAGING] Identity-map active.");
}

} // namespace Paging
