// os/kernel/irq.cpp — IRQ management layer
#include "irq.h"
#include "idt.h"
#include "vga.h"
#include "serial.h"

namespace IRQ {

// ── I/O helpers ───────────────────────────────────────────────────────────────
static inline uint8_t inb(uint16_t port) {
    uint8_t v;
    asm volatile("inb %1, %0" : "=a"(v) : "Nd"(port));
    return v;
}
static inline void outb(uint16_t port, uint8_t v) {
    asm volatile("outb %0, %1" : : "a"(v), "Nd"(port));
}

// 8259A PIC ports
static constexpr uint16_t PIC1_CMD  = 0x20;
static constexpr uint16_t PIC1_DATA = 0x21;
static constexpr uint16_t PIC2_CMD  = 0xA0;
static constexpr uint16_t PIC2_DATA = 0xA1;
static constexpr uint8_t  PIC_EOI   = 0x20;

// ── Module state ──────────────────────────────────────────────────────────────
struct IRQSlot {
    Handler  handler;
    void*    context;
    uint32_t count;
};

static IRQSlot s_slots[MAX_IRQ] = {};

// ── PIC helpers ───────────────────────────────────────────────────────────────
static void pic_remap(uint8_t offset1, uint8_t offset2) {
    uint8_t m1 = inb(PIC1_DATA);  // save masks
    uint8_t m2 = inb(PIC2_DATA);

    outb(PIC1_CMD,  0x11); // init cascade
    outb(PIC2_CMD,  0x11);
    outb(PIC1_DATA, offset1);     // PIC1 vector offset
    outb(PIC2_DATA, offset2);     // PIC2 vector offset
    outb(PIC1_DATA, 0x04);        // tell PIC1 cascade at IRQ2
    outb(PIC2_DATA, 0x02);        // tell PIC2 its cascade identity
    outb(PIC1_DATA, 0x01);        // 8086 mode
    outb(PIC2_DATA, 0x01);

    outb(PIC1_DATA, m1);   // restore masks
    outb(PIC2_DATA, m2);
}

// ── IRQ dispatcher ────────────────────────────────────────────────────────────
// Called from the IDT stubs for INT 32–47 (IRQ 0–15).
static void irq_idt_handler(IDT::Registers* regs) {
    uint8_t irq = (uint8_t)(regs->int_no - 32);
    if (irq < MAX_IRQ) {
        s_slots[irq].count++;
        if (s_slots[irq].handler) {
            s_slots[irq].handler(irq, s_slots[irq].context);
        }
    }
    send_eoi(irq);
}

// ── Public API ────────────────────────────────────────────────────────────────
void init() {
    // Remap PIC: IRQ 0–7 → INT 32–39, IRQ 8–15 → INT 40–47
    pic_remap(0x20, 0x28);

    // Mask all IRQs initially
    outb(PIC1_DATA, 0xFF);
    outb(PIC2_DATA, 0xFF);

    // Register IDT handlers for INT 32–47
    for (uint8_t i = 0; i < MAX_IRQ; ++i) {
        IDT::register_handler(32 + i, irq_idt_handler);
    }

    // Unmask IRQ 2 (PIC cascade) so PIC2 lines work
    uint8_t mask1 = inb(PIC1_DATA);
    outb(PIC1_DATA, mask1 & ~(1u << 2));

    VGA::writeln("[IRQ] PIC remapped; all IRQs initially masked.");
    Serial::logln("[IRQ] Ready.");
}

bool register_handler(uint8_t irq, Handler handler, void* context) {
    if (irq >= MAX_IRQ) return false;
    s_slots[irq].handler = handler;
    s_slots[irq].context = context;
    enable(irq);
    return true;
}

void unregister_handler(uint8_t irq) {
    if (irq >= MAX_IRQ) return;
    disable(irq);
    s_slots[irq].handler = nullptr;
    s_slots[irq].context = nullptr;
}

void enable(uint8_t irq) {
    if (irq >= MAX_IRQ) return;
    if (irq < 8) {
        uint8_t mask = inb(PIC1_DATA);
        outb(PIC1_DATA, mask & ~(1u << irq));
    } else {
        uint8_t mask = inb(PIC2_DATA);
        outb(PIC2_DATA, mask & ~(1u << (irq - 8)));
        // Ensure cascade is unmasked
        uint8_t m1 = inb(PIC1_DATA);
        outb(PIC1_DATA, m1 & ~(1u << 2));
    }
}

void disable(uint8_t irq) {
    if (irq >= MAX_IRQ) return;
    if (irq < 8) {
        uint8_t mask = inb(PIC1_DATA);
        outb(PIC1_DATA, mask | (1u << irq));
    } else {
        uint8_t mask = inb(PIC2_DATA);
        outb(PIC2_DATA, mask | (1u << (irq - 8)));
    }
}

void dispatch(uint8_t irq) {
    if (irq < MAX_IRQ && s_slots[irq].handler) {
        s_slots[irq].handler(irq, s_slots[irq].context);
    }
    send_eoi(irq);
}

void send_eoi(uint8_t irq) {
    if (irq >= 8) outb(PIC2_CMD, PIC_EOI);
    outb(PIC1_CMD, PIC_EOI);
}

uint32_t dispatch_count(uint8_t irq) {
    return (irq < MAX_IRQ) ? s_slots[irq].count : 0;
}

} // namespace IRQ
