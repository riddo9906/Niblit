// os/kernel/pit.cpp — PIT 8253/8254 driver implementation
#include "pit.h"
#include "idt.h"
#include "process.h"
#include "vga.h"

namespace PIT {

// ── I/O helpers ───────────────────────────────────────────────────────────────
static inline void outb(uint16_t port, uint8_t val) {
    asm volatile("outb %0, %1" : : "a"(val), "Nd"(port));
}

// ── State ─────────────────────────────────────────────────────────────────────
static volatile uint64_t s_ticks  = 0;
static          uint32_t s_hz     = TICK_FREQUENCY;

// ── IRQ0 handler ──────────────────────────────────────────────────────────────
static void pit_irq_handler(IDT::Registers* /*regs*/) {
    on_tick();
}

// ── Public ────────────────────────────────────────────────────────────────────
void init(uint32_t hz) {
    s_hz = hz ? hz : TICK_FREQUENCY;

    // Divisor for the desired frequency.
    uint32_t divisor = BASE_FREQUENCY / s_hz;
    if (divisor > 0xFFFF) divisor = 0xFFFF;

    // Channel 0, lobyte/hibyte mode, rate generator (mode 2).
    outb(0x43, 0x36);
    outb(0x40, static_cast<uint8_t>(divisor & 0xFF));
    outb(0x40, static_cast<uint8_t>((divisor >> 8) & 0xFF));

    // Register IRQ0 (INT 32) handler.
    IDT::register_handler(32, pit_irq_handler);

    VGA::write("[PIT] Initialised at ");
    VGA::write_dec(s_hz);
    VGA::writeln(" Hz.");
}

void on_tick() {
    ++s_ticks;
    Process::tick();  // hand off to scheduler
}

uint64_t ticks() {
    return s_ticks;
}

uint64_t millis() {
    return s_ticks * (1000 / s_hz);
}

void sleep_ms(uint32_t ms) {
    uint64_t target = millis() + ms;
    while (millis() < target) {
        asm volatile("hlt");
    }
}

} // namespace PIT
