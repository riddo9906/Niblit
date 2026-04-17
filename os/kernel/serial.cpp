// os/kernel/serial.cpp — UART 16550 driver implementation
#include "serial.h"

namespace Serial {

// ── I/O helpers ───────────────────────────────────────────────────────────────
static inline void outb(uint16_t port, uint8_t val) {
    asm volatile("outb %0, %1" : : "a"(val), "Nd"(port));
}
static inline uint8_t inb(uint16_t port) {
    uint8_t ret;
    asm volatile("inb %1, %0" : "=a"(ret) : "Nd"(port));
    return ret;
}

// ── UART register offsets ─────────────────────────────────────────────────────
static constexpr uint16_t REG_DATA        = 0; // RBR / THR
static constexpr uint16_t REG_IER         = 1; // Interrupt Enable
static constexpr uint16_t REG_FIFO        = 2; // FIFO Control (write) / IIR (read)
static constexpr uint16_t REG_LCR         = 3; // Line Control
static constexpr uint16_t REG_MCR         = 4; // Modem Control
static constexpr uint16_t REG_LSR         = 5; // Line Status
static constexpr uint16_t REG_DLAB_LO     = 0; // Divisor Latch Low  (DLAB=1)
static constexpr uint16_t REG_DLAB_HI     = 1; // Divisor Latch High (DLAB=1)

static constexpr uint8_t  LSR_DATA_READY  = 0x01;
static constexpr uint8_t  LSR_THRE        = 0x20; // Transmit Holding Register Empty

// ── init ─────────────────────────────────────────────────────────────────────
bool init(uint16_t port, uint32_t baud) {
    // Disable all interrupts
    outb(port + REG_IER, 0x00);

    // Enable DLAB (set baud rate divisor)
    outb(port + REG_LCR, 0x80);

    uint16_t divisor = static_cast<uint16_t>(115200 / baud);
    outb(port + REG_DLAB_LO, static_cast<uint8_t>(divisor & 0xFF));
    outb(port + REG_DLAB_HI, static_cast<uint8_t>((divisor >> 8) & 0xFF));

    // 8 bits, no parity, 1 stop bit (8N1), DLAB off
    outb(port + REG_LCR, 0x03);

    // Enable FIFO, clear, 14-byte threshold
    outb(port + REG_FIFO, 0xC7);

    // IRQs enabled, RTS/DSR set
    outb(port + REG_MCR, 0x0B);

    // Loopback self-test: send 0xAE and check echo
    outb(port + REG_MCR, 0x1E); // loopback mode
    outb(port + REG_DATA, 0xAE);
    if (inb(port + REG_DATA) != 0xAE) {
        return false; // no serial port present
    }

    // Normal operation
    outb(port + REG_MCR, 0x0F);
    return true;
}

// ── output ────────────────────────────────────────────────────────────────────
static inline void wait_tx(uint16_t port) {
    while (!(inb(port + REG_LSR) & LSR_THRE)) {
        asm volatile("pause");
    }
}

void put_char(uint16_t port, char c) {
    wait_tx(port);
    outb(port + REG_DATA, static_cast<uint8_t>(c));
}

void write(uint16_t port, const char* str) {
    for (; *str; ++str) {
        if (*str == '\n') put_char(port, '\r'); // CRLF for terminals
        put_char(port, *str);
    }
}

void writeln(uint16_t port, const char* str) {
    write(port, str);
    put_char(port, '\r');
    put_char(port, '\n');
}

void write_hex(uint16_t port, uint32_t val) {
    static const char digits[] = "0123456789ABCDEF";
    write(port, "0x");
    for (int shift = 28; shift >= 0; shift -= 4) {
        put_char(port, digits[(val >> shift) & 0xF]);
    }
}

void write_dec(uint16_t port, uint64_t val) {
    if (val == 0) { put_char(port, '0'); return; }
    char buf[21]; int len = 0;
    while (val) { buf[len++] = '0' + (val % 10); val /= 10; }
    for (int i = len - 1; i >= 0; --i) put_char(port, buf[i]);
}

// ── input ─────────────────────────────────────────────────────────────────────
bool data_ready(uint16_t port) {
    return (inb(port + REG_LSR) & LSR_DATA_READY) != 0;
}

char read_char(uint16_t port) {
    if (!data_ready(port)) return 0;
    return static_cast<char>(inb(port + REG_DATA));
}

} // namespace Serial
