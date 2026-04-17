// os/kernel/vga.cpp — VGA text-mode driver implementation
#include "vga.h"

namespace VGA {

// The VGA text buffer lives at physical address 0xB8000.
// Each cell is 2 bytes: [char][attribute].
static volatile uint16_t* const BUFFER =
    reinterpret_cast<volatile uint16_t*>(0xB8000);

static size_t   g_row    = 0;
static size_t   g_col    = 0;
static uint8_t  g_colour = 0;   // computed in set_colour()

// ── helpers ──────────────────────────────────────────────────────────────────

static inline uint16_t make_entry(char c, uint8_t colour) {
    return static_cast<uint16_t>(static_cast<uint8_t>(c))
         | static_cast<uint16_t>(colour) << 8;
}

static void scroll_up() {
    // Copy each row one row above.
    for (size_t row = 1; row < HEIGHT; ++row) {
        for (size_t col = 0; col < WIDTH; ++col) {
            BUFFER[(row - 1) * WIDTH + col] = BUFFER[row * WIDTH + col];
        }
    }
    // Blank the last row.
    for (size_t col = 0; col < WIDTH; ++col) {
        BUFFER[(HEIGHT - 1) * WIDTH + col] = make_entry(' ', g_colour);
    }
    g_row = HEIGHT - 1;
}

// ── public API ────────────────────────────────────────────────────────────────

void init() {
    set_colour(Colour::LIGHT_GREY, Colour::BLACK);
    clear();
}

void set_colour(Colour fg, Colour bg) {
    g_colour = static_cast<uint8_t>(fg)
             | (static_cast<uint8_t>(bg) << 4);
}

void clear() {
    for (size_t i = 0; i < WIDTH * HEIGHT; ++i) {
        BUFFER[i] = make_entry(' ', g_colour);
    }
    g_row = 0;
    g_col = 0;
}

void newline() {
    g_col = 0;
    if (++g_row >= HEIGHT) {
        scroll_up();
    }
}

void put_char(char c) {
    if (c == '\n') {
        newline();
        return;
    }
    if (c == '\r') {
        g_col = 0;
        return;
    }
    BUFFER[g_row * WIDTH + g_col] = make_entry(c, g_colour);
    if (++g_col >= WIDTH) {
        newline();
    }
}

void write(const char* str) {
    for (; *str; ++str) {
        put_char(*str);
    }
}

void writeln(const char* str) {
    write(str);
    newline();
}

void write_hex(uint32_t value) {
    static const char digits[] = "0123456789ABCDEF";
    write("0x");
    for (int shift = 28; shift >= 0; shift -= 4) {
        put_char(digits[(value >> shift) & 0xF]);
    }
}

void write_hex64(uint64_t value) {
    static const char digits[] = "0123456789ABCDEF";
    write("0x");
    for (int shift = 60; shift >= 0; shift -= 4) {
        put_char(digits[(value >> shift) & 0xF]);
    }
}

void write_dec(uint64_t value) {
    if (value == 0) {
        put_char('0');
        return;
    }
    char buf[21];
    int  len = 0;
    while (value) {
        buf[len++] = '0' + (value % 10);
        value /= 10;
    }
    for (int i = len - 1; i >= 0; --i) {
        put_char(buf[i]);
    }
}

} // namespace VGA
