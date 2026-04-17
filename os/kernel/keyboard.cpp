// os/kernel/keyboard.cpp — PS/2 keyboard driver implementation
//
// Decodes PS/2 scan-code set 1 key-press events received on IRQ 1
// (INT 33) and queues ASCII characters into a ring buffer.
#include "keyboard.h"
#include "idt.h"
#include "process.h"
#include <stddef.h>

namespace Keyboard {

// ── I/O helpers ───────────────────────────────────────────────────────────────
static inline uint8_t inb(uint16_t port) {
    uint8_t v;
    asm volatile("inb %1, %0" : "=a"(v) : "Nd"(port));
    return v;
}
static inline void outb(uint16_t port, uint8_t v) {
    asm volatile("outb %0, %1" : : "a"(v), "Nd"(port));
}

// PS/2 controller ports
static constexpr uint16_t KBD_DATA    = 0x60;
static constexpr uint16_t KBD_STATUS  = 0x64;
static constexpr uint16_t KBD_CMD     = 0x64;

// ── Scan-code set 1 → ASCII table (unshifted) ─────────────────────────────────
static const char s_scancode[128] = {
    0,  27, '1','2','3','4','5','6','7','8','9','0','-','=', '\b',
    '\t','q','w','e','r','t','y','u','i','o','p','[',']','\n',
    0,  // 29 = Ctrl
    'a','s','d','f','g','h','j','k','l',';','\'','`',
    0,  // 42 = Left Shift
    '\\','z','x','c','v','b','n','m',',','.','/',
    0,  // 54 = Right Shift
    '*',
    0,  // 56 = Alt
    ' ',
    0,  // 58 = Caps Lock
    0,0,0,0,0,0,0,0,0,0, // F1–F10
    0,  // 69 = Num Lock
    0,  // 70 = Scroll Lock
    0,0,0,0,0,0,0,0,0,0,0,0,0, // keypad
    0,0,                        // spare
    0,0,0,                      // F11, F12
    // rest = 0
};

// Shifted version of the printable row
static const char s_scancode_shifted[128] = {
    0,  27, '!','@','#','$','%','^','&','*','(',')','_','+', '\b',
    '\t','Q','W','E','R','T','Y','U','I','O','P','{','}','\n',
    0,'A','S','D','F','G','H','J','K','L',':','"','~',
    0,'|','Z','X','C','V','B','N','M','<','>','?',
    0,'*',0,' ',
    // rest = 0
};

// ── Ring buffer ────────────────────────────────────────────────────────────────
static constexpr size_t BUF_SIZE = 64;
static char    s_buf[BUF_SIZE];
static volatile size_t s_head = 0;  // write head
static volatile size_t s_tail = 0;  // read tail

static void buf_push(char c) {
    size_t next = (s_head + 1) % BUF_SIZE;
    if (next != s_tail) {   // drop if full
        s_buf[s_head] = c;
        s_head = next;
    }
}

static char buf_pop() {
    if (s_head == s_tail) return 0;
    char c = s_buf[s_tail];
    s_tail = (s_tail + 1) % BUF_SIZE;
    return c;
}

// ── Modifier state ────────────────────────────────────────────────────────────
static bool s_shift    = false;
static bool s_ctrl     = false;
static bool s_alt      = false;
static bool s_caps     = false;

// ── IRQ 1 handler ─────────────────────────────────────────────────────────────
static void keyboard_irq(IDT::Registers* /*regs*/) {
    uint8_t sc = inb(KBD_DATA);

    // Key release events have bit 7 set
    bool released = (sc & 0x80) != 0;
    uint8_t code  = sc & 0x7F;

    switch (code) {
        case 0x2A: case 0x36: s_shift = !released; return;  // Shift L/R
        case 0x1D:             s_ctrl  = !released; return;  // Ctrl
        case 0x38:             s_alt   = !released; return;  // Alt
        case 0x3A: if (!released) s_caps = !s_caps;  return; // Caps Lock
        default: break;
    }

    if (released) return; // only process key-press

    // Translate to ASCII
    char c = 0;
    if (code < 128) {
        bool upper = s_caps ^ s_shift;
        c = upper ? s_scancode_shifted[code] : s_scancode[code];
    }

    if (c) {
        if (s_ctrl && c >= 'a' && c <= 'z') c -= 96; // Ctrl+letter → control char
        buf_push(c);
    }
}

// ── Public API ────────────────────────────────────────────────────────────────
void init() {
    // Flush the PS/2 output buffer
    while (inb(KBD_STATUS) & 0x01) inb(KBD_DATA);

    // Enable keyboard scanning
    outb(KBD_DATA, 0xF4);

    // IRQ 1 = INT 33 (0x20 PIC remapping + 1)
    IDT::register_handler(33, keyboard_irq);
}

char read_char() {
    return buf_pop();
}

bool data_ready() {
    return s_head != s_tail;
}

char read_char_blocking() {
    while (!data_ready()) {
        asm volatile("hlt");   // yield until next interrupt
    }
    return buf_pop();
}

Modifiers modifiers() {
    Modifiers m{};
    m.shift = s_shift;
    m.ctrl  = s_ctrl;
    m.alt   = s_alt;
    m.caps  = s_caps;
    return m;
}

} // namespace Keyboard
