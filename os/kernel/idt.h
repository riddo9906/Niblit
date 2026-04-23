// os/kernel/idt.h — Interrupt Descriptor Table
//
// Sets up the IDT with handlers for CPU exceptions (0–31) and hardware
// IRQs (32–47 after PIC remapping).
#pragma once
#include <stdint.h>

namespace IDT {

// CPU register state saved on interrupt entry (pushed by isr_common_stub).
struct Registers {
    uint32_t ds;                            // data segment pushed by us
    uint32_t edi, esi, ebp, esp_ignored;    // pushed by pusha
    uint32_t ebx, edx, ecx, eax;           // pushed by pusha
    uint32_t int_no, err_code;              // pushed by our stubs
    uint32_t eip, cs, eflags, useresp, ss; // pushed by the CPU
};

// Initialise IDT and remap the 8259 PIC.
void init();

// Register a C++ handler for interrupt *num*.
using Handler = void(*)(Registers*);
void register_handler(uint8_t num, Handler fn);

} // namespace IDT
