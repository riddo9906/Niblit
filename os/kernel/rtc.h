// os/kernel/rtc.h — CMOS Real-Time Clock driver
//
// Reads the system date/time from the x86 CMOS RTC registers (I/O ports
// 0x70/0x71).  Converts BCD to binary.  Provides a simple Unix-style
// timestamp (seconds since 1970-01-01 UTC) for kernel logging.
#pragma once
#include <stdint.h>

namespace RTC {

struct DateTime {
    uint8_t  second;  // 0–59
    uint8_t  minute;  // 0–59
    uint8_t  hour;    // 0–23
    uint8_t  day;     // 1–31
    uint8_t  month;   // 1–12
    uint16_t year;    // full year, e.g. 2024
};

// Initialise the RTC driver (disables NMI, reads from CMOS).
void init();

// Return the current date/time.
DateTime now();

// Return a Unix timestamp (seconds since 1970-01-01 00:00 UTC).
// Good enough for kernel logging (ignores leap seconds).
uint64_t unix_time();

// Write a human-readable timestamp to buf (at least 32 bytes).
void format_timestamp(char* buf, size_t len);

} // namespace RTC
