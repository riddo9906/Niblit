// os/kernel/dma.h — ISA DMA controller (Intel 8237 / compatible)
//
// Provides a simple API to set up ISA DMA transfers for legacy devices
// (e.g. floppy, Sound Blaster 16).  Modern devices use bus-master DMA via
// PCI BAR registers and do not use this controller.
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace DMA {

// DMA channel numbers (0–3: 8-bit; 4–7: 16-bit cascaded)
static constexpr uint8_t CH_FLOPPY = 2;
static constexpr uint8_t CH_SB16   = 1;

// Transfer modes
static constexpr uint8_t MODE_SINGLE  = 0x40;
static constexpr uint8_t MODE_BLOCK   = 0x80;
static constexpr uint8_t MODE_DEMAND  = 0x00;

// Transfer directions
static constexpr uint8_t DIR_READ     = 0x44; // device → memory
static constexpr uint8_t DIR_WRITE    = 0x48; // memory → device

// Initialise both 8237 controllers (reset + clear flip-flops).
void init();

// Set up a single-cycle DMA transfer.
//   channel — DMA channel (0–7)
//   buffer  — physical address of the DMA buffer (must be in first 16 MiB for 8-bit,
//              24-bit address space for ISA DMA)
//   count   — number of bytes to transfer (actual transfer is count−1 bytes per HW spec)
//   mode    — MODE_SINGLE | DIR_READ or MODE_SINGLE | DIR_WRITE
void setup(uint8_t channel, uint32_t buffer, size_t count, uint8_t mode);

// Mask (disable) a DMA channel.
void mask(uint8_t channel);

// Unmask (enable) a DMA channel.
void unmask(uint8_t channel);

// Reset both DMA controllers.
void reset();

} // namespace DMA
