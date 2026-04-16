// os/kernel/irq.h — IRQ management layer
//
// Abstracts the 8259A PIC (legacy) and optionally APIC interrupt routing.
// Allows kernel subsystems to register handlers for specific IRQ lines.
// Provides a unified IRQ dispatch path called from the IDT stub.
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace IRQ {

// Maximum IRQ lines (16 for dual 8259 PIC)
static constexpr size_t MAX_IRQ = 16;

// IRQ handler callback type.
using Handler = void (*)(uint8_t irq, void* context);

// Initialise the IRQ manager (should be called after IDT::init()).
void init();

// Register a handler for a given IRQ line (0–15).
// Returns true on success, false if the slot is already taken.
bool register_handler(uint8_t irq, Handler handler, void* context = nullptr);

// Unregister a handler.
void unregister_handler(uint8_t irq);

// Enable (unmask) a specific IRQ line.
void enable(uint8_t irq);

// Disable (mask) a specific IRQ line.
void disable(uint8_t irq);

// Called from IDT handler stubs for IRQs 0–15 (INT 32–47).
// Dispatches to registered handler, then sends EOI.
void dispatch(uint8_t irq);

// Send End-Of-Interrupt to the appropriate PIC.
void send_eoi(uint8_t irq);

// Return IRQ stats (dispatch count per line).
uint32_t dispatch_count(uint8_t irq);

} // namespace IRQ
