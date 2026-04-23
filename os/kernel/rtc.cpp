// os/kernel/rtc.cpp — CMOS Real-Time Clock driver
#include "rtc.h"
#include "vga.h"
#include "serial.h"

namespace RTC {

// CMOS I/O ports
static constexpr uint16_t CMOS_ADDR = 0x70;
static constexpr uint16_t CMOS_DATA = 0x71;

// Disable NMI while accessing CMOS
static constexpr uint8_t NMI_DISABLE = 0x80;

static inline void outb(uint16_t p, uint8_t v) { asm volatile("outb %0,%1"::"a"(v),"Nd"(p)); }
static inline uint8_t inb(uint16_t p) { uint8_t v; asm volatile("inb %1,%0":"=a"(v):"Nd"(p)); return v; }

static uint8_t read_reg(uint8_t reg) {
    outb(CMOS_ADDR, NMI_DISABLE | reg);
    return inb(CMOS_DATA);
}

static bool is_bcd() {
    return !(read_reg(0x0B) & 0x04); // bit 2 clear → BCD mode
}
static bool is_12h() {
    return !(read_reg(0x0B) & 0x02); // bit 1 clear → 12-hour mode
}
static bool is_updating() {
    return (read_reg(0x0A) & 0x80) != 0;
}

static uint8_t bcd_to_bin(uint8_t v) { return (v >> 4) * 10 + (v & 0x0F); }

static DateTime s_cached = {};
static bool s_ready = false;

void init() {
    s_ready = true;
    // Prime the cache
    s_cached = now();
    VGA::write("[RTC] ");
    char buf[32] = {};
    format_timestamp(buf, sizeof(buf));
    VGA::writeln(buf);
    Serial::log("[RTC] "); Serial::writeln(Serial::COM1, buf);
}

DateTime now() {
    // Wait until RTC is not updating
    while (is_updating());

    bool bcd = is_bcd();
    bool h12 = is_12h();

    auto rd = [&](uint8_t reg) -> uint8_t {
        uint8_t v = read_reg(reg);
        return bcd ? bcd_to_bin(v) : v;
    };

    DateTime dt;
    dt.second = rd(0x00);
    dt.minute = rd(0x02);
    uint8_t raw_hour = rd(0x04);
    dt.day    = rd(0x07);
    dt.month  = rd(0x08);
    uint8_t year_lo = rd(0x09);

    if (h12) {
        bool pm = (raw_hour & 0x80) != 0;
        raw_hour &= 0x7F;
        if (bcd) raw_hour = bcd_to_bin(raw_hour);
        if (pm && raw_hour != 12) raw_hour += 12;
        if (!pm && raw_hour == 12) raw_hour = 0;
    }
    dt.hour = raw_hour;

    // Read century register (0x32) if available; fallback to 2000+
    uint8_t century = rd(0x32);
    if (century == 0 || century < 20 || century > 25) century = 20;
    dt.year = (uint16_t)(century * 100 + year_lo);

    s_cached = dt;
    return dt;
}

uint64_t unix_time() {
    DateTime dt = now();
    // Days from 1970-01-01 to dt.year-01-01
    static const uint16_t DAYS_PER_MONTH[] = {0,31,59,90,120,151,181,212,243,273,304,334};
    auto is_leap = [](uint16_t y) { return (y%4==0 && y%100!=0) || (y%400==0); };

    uint64_t days = 0;
    for (uint16_t y = 1970; y < dt.year; ++y) days += is_leap(y) ? 366 : 365;

    days += DAYS_PER_MONTH[dt.month > 0 ? dt.month - 1 : 0];
    if (dt.month > 2 && is_leap(dt.year)) ++days;
    days += (dt.day > 0 ? dt.day - 1 : 0);

    return days * 86400ULL
         + dt.hour   * 3600ULL
         + dt.minute * 60ULL
         + dt.second;
}

static void write_dec2(char* p, uint8_t v) {
    p[0] = '0' + v / 10;
    p[1] = '0' + v % 10;
}
static void write_dec4(char* p, uint16_t v) {
    p[0] = '0' + v / 1000;
    p[1] = '0' + (v / 100) % 10;
    p[2] = '0' + (v / 10) % 10;
    p[3] = '0' + v % 10;
}

void format_timestamp(char* buf, size_t len) {
    if (!buf || len < 20) return;
    DateTime dt = now();
    // "YYYY-MM-DD HH:MM:SS"
    write_dec4(buf,      dt.year);
    buf[4] = '-';
    write_dec2(buf + 5,  dt.month);
    buf[7] = '-';
    write_dec2(buf + 8,  dt.day);
    buf[10] = ' ';
    write_dec2(buf + 11, dt.hour);
    buf[13] = ':';
    write_dec2(buf + 14, dt.minute);
    buf[16] = ':';
    write_dec2(buf + 17, dt.second);
    buf[19] = '\0';
}

} // namespace RTC
