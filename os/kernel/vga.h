// os/kernel/vga.h — VGA text-mode driver
//
// Provides coloured text output to the 80×25 VGA text buffer at 0xB8000.
// All functions are callable before any heap/allocator is available.
#pragma once

#include <stdint.h>
#include <stddef.h>

namespace VGA {

// Colour attribute nibbles (foreground | background << 4)
enum class Colour : uint8_t {
    BLACK         = 0,
    BLUE          = 1,
    GREEN         = 2,
    CYAN          = 3,
    RED           = 4,
    MAGENTA       = 5,
    BROWN         = 6,
    LIGHT_GREY    = 7,
    DARK_GREY     = 8,
    LIGHT_BLUE    = 9,
    LIGHT_GREEN   = 10,
    LIGHT_CYAN    = 11,
    LIGHT_RED     = 12,
    LIGHT_MAGENTA = 13,
    YELLOW        = 14,
    WHITE         = 15,
};

static constexpr size_t WIDTH  = 80;
static constexpr size_t HEIGHT = 25;

// Initialise the driver and clear the screen.
void init();

// Set the default text colour used by write() / writeln().
void set_colour(Colour fg, Colour bg);

// Write a single character at the current cursor position.
void put_char(char c);

// Write a null-terminated string.
void write(const char* str);

// Write a null-terminated string followed by a newline.
void writeln(const char* str);

// Write a 32-bit hex value prefixed with "0x".
void write_hex(uint32_t value);

// Write a 64-bit hex value prefixed with "0x".
void write_hex64(uint64_t value);

// Write a decimal integer.
void write_dec(uint64_t value);

// Move cursor to column 0 of the next line.
void newline();

// Clear the entire screen.
void clear();

} // namespace VGA
