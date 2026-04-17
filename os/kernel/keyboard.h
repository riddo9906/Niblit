// os/kernel/keyboard.h — PS/2 keyboard driver (IRQ 1)
//
// Translates PS/2 scan codes (set 1) to ASCII characters.
// Supports Shift, Caps Lock, and basic control characters.
// Input is delivered via a small ring buffer; callers use
// Keyboard::read_char() to dequeue characters.
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace Keyboard {

// Initialise the PS/2 driver and register IRQ 1.
void init();

// Return the next character from the keyboard buffer.
// Returns 0 if the buffer is empty (non-blocking).
char read_char();

// Return true if at least one character is waiting.
bool data_ready();

// Wait (blocking, yielding to scheduler) until a char is available.
char read_char_blocking();

// Return the current state of modifier keys.
struct Modifiers {
    bool shift    : 1;
    bool ctrl     : 1;
    bool alt      : 1;
    bool caps     : 1;
    uint8_t _pad  : 4;
};
Modifiers modifiers();

} // namespace Keyboard
