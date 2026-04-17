// os/kernel/ata.h — ATA/IDE storage driver
//
// Supports PIO-mode read/write for the primary and secondary IDE channels.
// Detects hard disks and ATAPI (CD-ROM) devices via IDENTIFY.
// For use with QEMU's IDE emulation (-hda / -hdb) or real hardware.
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace ATA {

// ATA I/O base ports
static constexpr uint16_t ATA_PRIMARY_IO    = 0x1F0;
static constexpr uint16_t ATA_SECONDARY_IO  = 0x170;

// ATA register offsets from IO base
static constexpr uint8_t REG_DATA     = 0x00;
static constexpr uint8_t REG_ERROR    = 0x01;
static constexpr uint8_t REG_FEATURES = 0x01;
static constexpr uint8_t REG_SECCOUNT = 0x02;
static constexpr uint8_t REG_LBA_LO   = 0x03;
static constexpr uint8_t REG_LBA_MID  = 0x04;
static constexpr uint8_t REG_LBA_HI   = 0x05;
static constexpr uint8_t REG_HDDEVSEL = 0x06;
static constexpr uint8_t REG_STATUS   = 0x07;
static constexpr uint8_t REG_CMD      = 0x07;

// ATA commands
static constexpr uint8_t CMD_IDENTIFY  = 0xEC;
static constexpr uint8_t CMD_READ_PIO  = 0x20;
static constexpr uint8_t CMD_WRITE_PIO = 0x30;
static constexpr uint8_t CMD_FLUSH     = 0xE7;
static constexpr uint8_t CMD_READ_DMA  = 0xC8;
static constexpr uint8_t CMD_WRITE_DMA = 0xCA;

// Status register bits
static constexpr uint8_t STATUS_BSY  = 0x80;
static constexpr uint8_t STATUS_DRDY = 0x40;
static constexpr uint8_t STATUS_ERR  = 0x01;
static constexpr uint8_t STATUS_DRQ  = 0x08;

// Maximum drives and max LBA28 sectors
static constexpr size_t MAX_DRIVES = 4;   // 2 channels × 2 drives
static constexpr uint64_t MAX_LBA28 = 0x0FFFFFFF;

// Drive types
enum class DriveType : uint8_t { NONE, ATA, ATAPI };

struct Drive {
    bool      present;
    DriveType type;
    char      model[41];   // null-terminated model string (IDENTIFY words 27–46)
    uint32_t  lba28_sectors; // total sectors (LBA28)
    uint64_t  lba48_sectors; // total sectors (LBA48) — 0 if not supported
    uint16_t  channel;       // I/O base (ATA_PRIMARY_IO or ATA_SECONDARY_IO)
    uint8_t   slave;         // 0 = master, 1 = slave
};

// Initialise both ATA channels, run IDENTIFY, populate drive list.
void init();

// Number of present drives (up to MAX_DRIVES).
size_t drive_count();

// Return drive info for index i.
const Drive* drive(size_t i);

// Read *count* 512-byte sectors starting at *lba* from drive *drv_idx*.
// *buf* must be at least count * 512 bytes.
// Returns sectors read, or -1 on error.
int read(size_t drv_idx, uint64_t lba, size_t count, void* buf);

// Write *count* 512-byte sectors starting at *lba* to drive *drv_idx*.
int write(size_t drv_idx, uint64_t lba, size_t count, const void* buf);

// Print detected drives to VGA/Serial.
void dump();

} // namespace ATA
