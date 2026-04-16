// os/kernel/gdt.h — Global Descriptor Table
//
// The GDT defines the memory segments used by the CPU.  We set up a flat
// (32/64-bit) memory model with separate kernel/user code+data segments.
#pragma once
#include <stdint.h>

namespace GDT {

// Segment selectors (byte offsets into the GDT, | 3 for ring-3 RPL).
static constexpr uint16_t SEL_NULL        = 0x00;
static constexpr uint16_t SEL_KERNEL_CODE = 0x08;
static constexpr uint16_t SEL_KERNEL_DATA = 0x10;
static constexpr uint16_t SEL_USER_CODE   = 0x18 | 3;
static constexpr uint16_t SEL_USER_DATA   = 0x20 | 3;

// Initialise the GDT and reload all segment registers.
void init();

} // namespace GDT
