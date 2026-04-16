// os/kernel/idt.cpp — Interrupt Descriptor Table implementation
#include "idt.h"
#include "vga.h"
#include <stddef.h>

namespace IDT {

// ── gate descriptor (8 bytes) ─────────────────────────────────────────────────
struct Entry {
    uint16_t offset_low;
    uint16_t selector;
    uint8_t  zero;
    uint8_t  type_attr;     // P | DPL(2) | gate type(5)
    uint16_t offset_high;
} __attribute__((packed));

struct Pointer {
    uint16_t limit;
    uint32_t base;
} __attribute__((packed));

// ── storage ───────────────────────────────────────────────────────────────────
static Entry   idt[256];
static Pointer idtr;
static Handler handlers[256] = {};

// ── external stubs declared in idt.asm ───────────────────────────────────────
extern "C" {
    void isr0();  void isr1();  void isr2();  void isr3();
    void isr4();  void isr5();  void isr6();  void isr7();
    void isr8();  void isr9();  void isr10(); void isr11();
    void isr12(); void isr13(); void isr14(); void isr15();
    void isr16(); void isr17(); void isr18(); void isr19();
    void isr20(); void isr21(); void isr22(); void isr23();
    void isr24(); void isr25(); void isr26(); void isr27();
    void isr28(); void isr29(); void isr30(); void isr31();
    void irq0();  void irq1();  void irq2();  void irq3();
    void irq4();  void irq5();  void irq6();  void irq7();
    void irq8();  void irq9();  void irq10(); void irq11();
    void irq12(); void irq13(); void irq14(); void irq15();
    void idt_flush(uint32_t);
}

static inline void outb(uint16_t port, uint8_t val) {
    asm volatile("outb %0, %1" : : "a"(val), "Nd"(port));
}
static inline uint8_t inb(uint16_t port) {
    uint8_t ret;
    asm volatile("inb %1, %0" : "=a"(ret) : "Nd"(port));
    return ret;
}

// ── helpers ───────────────────────────────────────────────────────────────────
static void set_gate(size_t num, uint32_t base, uint16_t sel, uint8_t flags) {
    idt[num].offset_low  = base & 0xFFFF;
    idt[num].offset_high = (base >> 16) & 0xFFFF;
    idt[num].selector    = sel;
    idt[num].zero        = 0;
    idt[num].type_attr   = flags;
}

static void remap_pic() {
    // Save masks
    uint8_t a1 = inb(0x21), a2 = inb(0xA1);
    // Start init sequence (cascade mode)
    outb(0x20, 0x11); outb(0xA0, 0x11);
    // Remap: IRQ 0–7 → INT 32–39, IRQ 8–15 → INT 40–47
    outb(0x21, 0x20); outb(0xA1, 0x28);
    // Tell master/slave their relationship
    outb(0x21, 0x04); outb(0xA1, 0x02);
    // 8086 mode
    outb(0x21, 0x01); outb(0xA1, 0x01);
    // Restore masks
    outb(0x21, a1);   outb(0xA1, a2);
}

// ── public ────────────────────────────────────────────────────────────────────
void init() {
    remap_pic();

    // Exceptions 0–31
    set_gate( 0, (uint32_t)isr0,  0x08, 0x8E);
    set_gate( 1, (uint32_t)isr1,  0x08, 0x8E);
    set_gate( 2, (uint32_t)isr2,  0x08, 0x8E);
    set_gate( 3, (uint32_t)isr3,  0x08, 0x8E);
    set_gate( 4, (uint32_t)isr4,  0x08, 0x8E);
    set_gate( 5, (uint32_t)isr5,  0x08, 0x8E);
    set_gate( 6, (uint32_t)isr6,  0x08, 0x8E);
    set_gate( 7, (uint32_t)isr7,  0x08, 0x8E);
    set_gate( 8, (uint32_t)isr8,  0x08, 0x8E);
    set_gate( 9, (uint32_t)isr9,  0x08, 0x8E);
    set_gate(10, (uint32_t)isr10, 0x08, 0x8E);
    set_gate(11, (uint32_t)isr11, 0x08, 0x8E);
    set_gate(12, (uint32_t)isr12, 0x08, 0x8E);
    set_gate(13, (uint32_t)isr13, 0x08, 0x8E);
    set_gate(14, (uint32_t)isr14, 0x08, 0x8E);
    set_gate(15, (uint32_t)isr15, 0x08, 0x8E);
    set_gate(16, (uint32_t)isr16, 0x08, 0x8E);
    set_gate(17, (uint32_t)isr17, 0x08, 0x8E);
    set_gate(18, (uint32_t)isr18, 0x08, 0x8E);
    set_gate(19, (uint32_t)isr19, 0x08, 0x8E);
    set_gate(20, (uint32_t)isr20, 0x08, 0x8E);
    set_gate(21, (uint32_t)isr21, 0x08, 0x8E);
    set_gate(22, (uint32_t)isr22, 0x08, 0x8E);
    set_gate(23, (uint32_t)isr23, 0x08, 0x8E);
    set_gate(24, (uint32_t)isr24, 0x08, 0x8E);
    set_gate(25, (uint32_t)isr25, 0x08, 0x8E);
    set_gate(26, (uint32_t)isr26, 0x08, 0x8E);
    set_gate(27, (uint32_t)isr27, 0x08, 0x8E);
    set_gate(28, (uint32_t)isr28, 0x08, 0x8E);
    set_gate(29, (uint32_t)isr29, 0x08, 0x8E);
    set_gate(30, (uint32_t)isr30, 0x08, 0x8E);
    set_gate(31, (uint32_t)isr31, 0x08, 0x8E);

    // Hardware IRQs 0–15 (mapped to INT 32–47)
    set_gate(32, (uint32_t)irq0,  0x08, 0x8E);
    set_gate(33, (uint32_t)irq1,  0x08, 0x8E);
    set_gate(34, (uint32_t)irq2,  0x08, 0x8E);
    set_gate(35, (uint32_t)irq3,  0x08, 0x8E);
    set_gate(36, (uint32_t)irq4,  0x08, 0x8E);
    set_gate(37, (uint32_t)irq5,  0x08, 0x8E);
    set_gate(38, (uint32_t)irq6,  0x08, 0x8E);
    set_gate(39, (uint32_t)irq7,  0x08, 0x8E);
    set_gate(40, (uint32_t)irq8,  0x08, 0x8E);
    set_gate(41, (uint32_t)irq9,  0x08, 0x8E);
    set_gate(42, (uint32_t)irq10, 0x08, 0x8E);
    set_gate(43, (uint32_t)irq11, 0x08, 0x8E);
    set_gate(44, (uint32_t)irq12, 0x08, 0x8E);
    set_gate(45, (uint32_t)irq13, 0x08, 0x8E);
    set_gate(46, (uint32_t)irq14, 0x08, 0x8E);
    set_gate(47, (uint32_t)irq15, 0x08, 0x8E);

    idtr.limit = sizeof(idt) - 1;
    idtr.base  = reinterpret_cast<uint32_t>(&idt);
    idt_flush(reinterpret_cast<uint32_t>(&idtr));
}

void register_handler(uint8_t num, Handler fn) {
    handlers[num] = fn;
}

} // namespace IDT

// ── C interrupt dispatch ──────────────────────────────────────────────────────
// Called from the common ASM stub.
extern "C" void isr_handler(IDT::Registers* regs) {
    if (IDT::handlers[regs->int_no]) {
        IDT::handlers[regs->int_no](regs);
    } else {
        VGA::set_colour(VGA::Colour::LIGHT_RED, VGA::Colour::BLACK);
        VGA::write("EXCEPTION #");
        VGA::write_dec(regs->int_no);
        VGA::write(" err=");
        VGA::write_hex(regs->err_code);
        VGA::write(" eip=");
        VGA::write_hex(regs->eip);
        VGA::newline();
    }
}

extern "C" void irq_handler(IDT::Registers* regs) {
    // Send End-Of-Interrupt to PIC
    if (regs->int_no >= 40) {
        // Slave PIC
        asm volatile("outb %0, %1" : : "a"((uint8_t)0x20), "Nd"((uint16_t)0xA0));
    }
    // Master PIC
    asm volatile("outb %0, %1" : : "a"((uint8_t)0x20), "Nd"((uint16_t)0x20));

    if (IDT::handlers[regs->int_no]) {
        IDT::handlers[regs->int_no](regs);
    }
}
