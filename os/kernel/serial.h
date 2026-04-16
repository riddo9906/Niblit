// os/kernel/serial.h — UART 16550 serial port driver (COM1)
//
// Provides unbuffered character output to the first serial port.
// In QEMU, launch with `-serial stdio` (or `-serial mon:stdio`) to see
// all kernel log output on your host terminal — much easier to debug than
// reading VGA screenshots.
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace Serial {

static constexpr uint16_t COM1 = 0x3F8;
static constexpr uint16_t COM2 = 0x2F8;

// Initialise the UART at the given baud rate (default 38400).
// Returns true on success (loopback self-test passed).
bool init(uint16_t port = COM1, uint32_t baud = 38400);

// Write a single character (blocks until transmit buffer is empty).
void put_char(uint16_t port, char c);

// Write a null-terminated string.
void write(uint16_t port, const char* str);

// Write a null-terminated string followed by '\n'.
void writeln(uint16_t port, const char* str);

// Write a 32-bit hex value.
void write_hex(uint16_t port, uint32_t val);

// Write a decimal integer.
void write_dec(uint16_t port, uint64_t val);

// Read a character (non-blocking — returns 0 if no data available).
char read_char(uint16_t port);

// Check whether a character is waiting.
bool data_ready(uint16_t port);

// Convenience: write to COM1.
inline void log(const char* str) { write(COM1, str); }
inline void logln(const char* str) { writeln(COM1, str); }

} // namespace Serial
