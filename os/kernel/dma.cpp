// os/kernel/dma.cpp — ISA DMA controller (8237 compatible)
#include "dma.h"
#include "vga.h"
#include "serial.h"

namespace DMA {

static inline void outb(uint16_t p, uint8_t v) { asm volatile("outb %0,%1"::"a"(v),"Nd"(p)); }
static inline uint8_t inb(uint16_t p) { uint8_t v; asm volatile("inb %1,%0":"=a"(v):"Nd"(p)); return v; }

// ── Port map for DMA controllers ──────────────────────────────────────────────
// DMA1 (channels 0–3, 8-bit transfers)
static constexpr uint16_t DMA1_RESET   = 0x0D;  // master reset
static constexpr uint16_t DMA1_MASK    = 0x0A;  // single channel mask
static constexpr uint16_t DMA1_MODE    = 0x0B;  // mode register
static constexpr uint16_t DMA1_FF      = 0x0C;  // flip-flop reset

// DMA2 (channels 4–7, 16-bit transfers; channel 4 = cascade)
static constexpr uint16_t DMA2_RESET   = 0xDA;
static constexpr uint16_t DMA2_MASK    = 0xD4;
static constexpr uint16_t DMA2_MODE    = 0xD6;
static constexpr uint16_t DMA2_FF      = 0xD8;

// Per-channel port layout (DMA1)
static const uint16_t DMA1_ADDR[4] = { 0x00, 0x02, 0x04, 0x06 };
static const uint16_t DMA1_CNT[4]  = { 0x01, 0x03, 0x05, 0x07 };
static const uint16_t DMA1_PAGE[4] = { 0x87, 0x83, 0x81, 0x82 };

void init() {
    // Reset both controllers
    outb(DMA1_RESET, 0xFF);
    outb(DMA2_RESET, 0xFF);

    // Mask all channels
    outb(DMA1_MASK, 0x04); // mask ch0
    outb(DMA1_MASK, 0x05); // mask ch1
    outb(DMA1_MASK, 0x06); // mask ch2
    outb(DMA1_MASK, 0x07); // mask ch3

    VGA::writeln("[DMA] 8237 controllers reset.");
    Serial::logln("[DMA] Ready.");
}

void setup(uint8_t ch, uint32_t buffer, size_t count, uint8_t mode) {
    if (ch > 3) return;  // only support DMA1 (8-bit channels)

    // Mask the channel
    outb(DMA1_MASK, (uint8_t)(0x04 | (ch & 0x03)));

    // Reset flip-flop
    outb(DMA1_FF, 0xFF);

    // Write address (low then high byte)
    outb(DMA1_ADDR[ch], (uint8_t)(buffer & 0xFF));
    outb(DMA1_ADDR[ch], (uint8_t)((buffer >> 8) & 0xFF));

    // Write page register (bits 16–23)
    outb(DMA1_PAGE[ch], (uint8_t)((buffer >> 16) & 0xFF));

    // Reset flip-flop again for count
    outb(DMA1_FF, 0xFF);

    // Write count − 1
    size_t cnt = (count > 0) ? count - 1 : 0;
    outb(DMA1_CNT[ch], (uint8_t)(cnt & 0xFF));
    outb(DMA1_CNT[ch], (uint8_t)((cnt >> 8) & 0xFF));

    // Write mode (mode | channel)
    outb(DMA1_MODE, (uint8_t)(mode | (ch & 0x03)));

    // Unmask channel
    outb(DMA1_MASK, (uint8_t)(ch & 0x03));
}

void mask(uint8_t ch) {
    if (ch < 4) outb(DMA1_MASK, (uint8_t)(0x04 | (ch & 0x03)));
    else        outb(DMA2_MASK, (uint8_t)(0x04 | ((ch - 4) & 0x03)));
}

void unmask(uint8_t ch) {
    if (ch < 4) outb(DMA1_MASK, (uint8_t)(ch & 0x03));
    else        outb(DMA2_MASK, (uint8_t)((ch - 4) & 0x03));
}

void reset() {
    outb(DMA1_RESET, 0xFF);
    outb(DMA2_RESET, 0xFF);
}

} // namespace DMA
