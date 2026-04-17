// os/kernel/ata.cpp — ATA/IDE storage driver (PIO mode)
#include "ata.h"
#include "vga.h"
#include "serial.h"
#include "pit.h"
#include <stddef.h>

namespace ATA {

static inline void outb(uint16_t p, uint8_t v) { asm volatile("outb %0,%1"::"a"(v),"Nd"(p)); }
static inline void outw(uint16_t p, uint16_t v){ asm volatile("outw %0,%1"::"a"(v),"Nd"(p)); }
static inline uint8_t  inb(uint16_t p) { uint8_t  v; asm volatile("inb %1,%0":"=a"(v):"Nd"(p)); return v; }
static inline uint16_t inw(uint16_t p) { uint16_t v; asm volatile("inw %1,%0":"=a"(v):"Nd"(p)); return v; }

// ── Module state ──────────────────────────────────────────────────────────────
static Drive s_drives[MAX_DRIVES];
static size_t s_drive_count = 0;

// ── Helpers ───────────────────────────────────────────────────────────────────
static void swap_string(char* buf, int start, int end) {
    for (int i = start; i < end; i += 2) {
        char tmp = buf[i];
        buf[i]   = buf[i + 1];
        buf[i+1] = tmp;
    }
}

static void wait_bsy(uint16_t io) {
    uint32_t timeout = 100000;
    while ((inb(io + REG_STATUS) & STATUS_BSY) && timeout--);
}

static bool wait_drq(uint16_t io) {
    uint32_t timeout = 100000;
    while (timeout--) {
        uint8_t st = inb(io + REG_STATUS);
        if (st & STATUS_ERR) return false;
        if (st & STATUS_DRQ) return true;
    }
    return false;
}

static void identify_drive(uint16_t io, uint8_t slave, size_t drv_idx) {
    if (drv_idx >= MAX_DRIVES) return;

    // Select drive
    outb(io + REG_HDDEVSEL, (uint8_t)(0xA0 | (slave << 4)));
    // 400ns delay (read status 4 times)
    for (int i = 0; i < 4; ++i) inb(io + REG_STATUS);

    // Zero LBA registers
    outb(io + REG_SECCOUNT, 0);
    outb(io + REG_LBA_LO,   0);
    outb(io + REG_LBA_MID,  0);
    outb(io + REG_LBA_HI,   0);

    // Issue IDENTIFY
    outb(io + REG_CMD, CMD_IDENTIFY);
    for (int i = 0; i < 4; ++i) inb(io + REG_STATUS);

    uint8_t status = inb(io + REG_STATUS);
    if (status == 0) return; // drive doesn't exist

    // Check if ATAPI
    uint8_t mid = inb(io + REG_LBA_MID);
    uint8_t hi  = inb(io + REG_LBA_HI);
    bool atapi  = (mid == 0x14 && hi == 0xEB);

    if (!wait_drq(io)) return;

    uint16_t buf[256];
    for (int i = 0; i < 256; ++i) buf[i] = inw(io + REG_DATA);

    Drive& d = s_drives[s_drive_count++];
    d.present  = true;
    d.type     = atapi ? DriveType::ATAPI : DriveType::ATA;
    d.channel  = io;
    d.slave    = slave;

    // Model string: words 27–46 (big-endian bytes)
    char model[41] = {};
    for (int i = 0; i < 20; ++i) {
        model[i * 2]     = (char)(buf[27 + i] >> 8);
        model[i * 2 + 1] = (char)(buf[27 + i] & 0xFF);
    }
    model[40] = '\0';
    // Trim trailing spaces
    for (int i = 39; i >= 0 && model[i] == ' '; --i) model[i] = '\0';
    for (int i = 0; model[i] && i < 41; ++i) d.model[i] = model[i];

    // LBA28 sector count (words 60–61)
    d.lba28_sectors = ((uint32_t)buf[61] << 16) | buf[60];

    // LBA48 sector count (words 100–103) — check bit 26 of word 83
    if (buf[83] & (1u << 10)) {
        d.lba48_sectors = ((uint64_t)buf[103] << 48)
                        | ((uint64_t)buf[102] << 32)
                        | ((uint64_t)buf[101] << 16)
                        |            buf[100];
    } else {
        d.lba48_sectors = d.lba28_sectors;
    }
}

// ── Public API ────────────────────────────────────────────────────────────────
void init() {
    s_drive_count = 0;
    for (int i = 0; i < MAX_DRIVES; ++i) s_drives[i] = {};

    identify_drive(ATA_PRIMARY_IO,   0, s_drive_count);
    identify_drive(ATA_PRIMARY_IO,   1, s_drive_count);
    identify_drive(ATA_SECONDARY_IO, 0, s_drive_count);
    identify_drive(ATA_SECONDARY_IO, 1, s_drive_count);

    VGA::write("[ATA] "); VGA::write_dec((uint32_t)s_drive_count); VGA::writeln(" drive(s) detected.");
    for (size_t i = 0; i < s_drive_count; ++i) {
        VGA::write("  disk"); VGA::write_dec((uint32_t)i);
        VGA::write(": "); VGA::writeln(s_drives[i].model);
    }
    Serial::logln("[ATA] Ready.");
}

size_t       drive_count()    { return s_drive_count; }
const Drive* drive(size_t i)  { return (i < s_drive_count) ? &s_drives[i] : nullptr; }

int read(size_t idx, uint64_t lba, size_t count, void* buf) {
    if (idx >= s_drive_count || !s_drives[idx].present) return -1;
    const Drive& d = s_drives[idx];
    if (d.type == DriveType::ATAPI) return -1; // TODO: ATAPI read

    auto* p = (uint8_t*)buf;
    for (size_t s = 0; s < count; ++s) {
        uint64_t slba = lba + s;
        wait_bsy(d.channel);

        // LBA28 mode
        outb(d.channel + REG_HDDEVSEL,
             (uint8_t)(0xE0 | (d.slave << 4) | ((slba >> 24) & 0x0F)));
        outb(d.channel + REG_SECCOUNT, 1);
        outb(d.channel + REG_LBA_LO,  (uint8_t)(slba));
        outb(d.channel + REG_LBA_MID, (uint8_t)(slba >> 8));
        outb(d.channel + REG_LBA_HI,  (uint8_t)(slba >> 16));
        outb(d.channel + REG_CMD,     CMD_READ_PIO);

        if (!wait_drq(d.channel)) return (int)s;

        for (int w = 0; w < 256; ++w) {
            uint16_t word = inw(d.channel + REG_DATA);
            *p++ = (uint8_t)(word & 0xFF);
            *p++ = (uint8_t)(word >> 8);
        }
    }
    return (int)count;
}

int write(size_t idx, uint64_t lba, size_t count, const void* buf) {
    if (idx >= s_drive_count || !s_drives[idx].present) return -1;
    const Drive& d = s_drives[idx];
    if (d.type == DriveType::ATAPI) return -1;

    const auto* p = (const uint8_t*)buf;
    for (size_t s = 0; s < count; ++s) {
        uint64_t slba = lba + s;
        wait_bsy(d.channel);

        outb(d.channel + REG_HDDEVSEL,
             (uint8_t)(0xE0 | (d.slave << 4) | ((slba >> 24) & 0x0F)));
        outb(d.channel + REG_SECCOUNT, 1);
        outb(d.channel + REG_LBA_LO,  (uint8_t)(slba));
        outb(d.channel + REG_LBA_MID, (uint8_t)(slba >> 8));
        outb(d.channel + REG_LBA_HI,  (uint8_t)(slba >> 16));
        outb(d.channel + REG_CMD,     CMD_WRITE_PIO);

        if (!wait_drq(d.channel)) return (int)s;

        for (int w = 0; w < 256; ++w) {
            uint16_t word = (uint16_t)(p[0]) | ((uint16_t)(p[1]) << 8);
            p += 2;
            outw(d.channel + REG_DATA, word);
        }
        // Flush cache
        outb(d.channel + REG_CMD, CMD_FLUSH);
        wait_bsy(d.channel);
    }
    return (int)count;
}

void dump() {
    for (size_t i = 0; i < s_drive_count; ++i) {
        const Drive& d = s_drives[i];
        VGA::write("  disk"); VGA::write_dec((uint32_t)i);
        VGA::write(d.type == DriveType::ATAPI ? " [ATAPI] " : " [ATA]   ");
        VGA::writeln(d.model);
    }
}

} // namespace ATA
