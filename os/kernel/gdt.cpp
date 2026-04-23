// os/kernel/gdt.cpp — Global Descriptor Table implementation
#include "gdt.h"
#include <stddef.h>

namespace GDT {

// ── descriptor format (8 bytes each) ─────────────────────────────────────────
struct Entry {
    uint16_t limit_low;
    uint16_t base_low;
    uint8_t  base_mid;
    uint8_t  access;        // P | DPL(2) | S | Type(4)
    uint8_t  granularity;   // G | DB | L | AVL | limit_high(4)
    uint8_t  base_high;
} __attribute__((packed));

struct Pointer {
    uint16_t limit;
    uint32_t base;
} __attribute__((packed));

// ── table storage ─────────────────────────────────────────────────────────────
static Entry   gdt[5];
static Pointer gdtr;

// ── helper ────────────────────────────────────────────────────────────────────
static void set_entry(size_t idx,
                      uint32_t base,
                      uint32_t limit,
                      uint8_t  access,
                      uint8_t  gran) {
    gdt[idx].limit_low   = limit & 0xFFFF;
    gdt[idx].base_low    = base  & 0xFFFF;
    gdt[idx].base_mid    = (base  >> 16) & 0xFF;
    gdt[idx].access      = access;
    gdt[idx].granularity = ((limit >> 16) & 0x0F) | (gran & 0xF0);
    gdt[idx].base_high   = (base  >> 24) & 0xFF;
}

// ── external ASM flush routine ────────────────────────────────────────────────
extern "C" void gdt_flush(uint32_t gdtr_ptr);

// ── public ────────────────────────────────────────────────────────────────────
void init() {
    //                  base  limit       access  granularity
    set_entry(0,    0,       0,          0x00,   0x00); // null
    set_entry(1,    0,       0xFFFFFFFF, 0x9A,   0xCF); // kernel code  (ring 0)
    set_entry(2,    0,       0xFFFFFFFF, 0x92,   0xCF); // kernel data  (ring 0)
    set_entry(3,    0,       0xFFFFFFFF, 0xFA,   0xCF); // user   code  (ring 3)
    set_entry(4,    0,       0xFFFFFFFF, 0xF2,   0xCF); // user   data  (ring 3)

    gdtr.limit = sizeof(gdt) - 1;
    gdtr.base  = reinterpret_cast<uint32_t>(&gdt);

    gdt_flush(reinterpret_cast<uint32_t>(&gdtr));
}

} // namespace GDT
