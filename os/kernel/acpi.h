// os/kernel/acpi.h — ACPI subsystem
//
// Locates and parses the ACPI Root System Description Pointer (RSDP),
// RSDT/XSDT, MADT (Multiple APIC Description Table), and FADT.
// Provides helper APIs for SMP CPU discovery, interrupt routing, and
// power management.
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace ACPI {

// ── Public types ──────────────────────────────────────────────────────────────

struct RSDP {
    char     signature[8];   // "RSD PTR "
    uint8_t  checksum;
    char     oem_id[6];
    uint8_t  revision;       // 0 = ACPI 1.0, 2 = ACPI 2.0+
    uint32_t rsdt_addr;
    // ACPI 2.0+ extension (if revision >= 2):
    uint32_t length;
    uint64_t xsdt_addr;
    uint8_t  ext_checksum;
    uint8_t  _reserved[3];
} __attribute__((packed));

struct SDTHeader {
    char     signature[4];
    uint32_t length;
    uint8_t  revision;
    uint8_t  checksum;
    char     oem_id[6];
    char     oem_table_id[8];
    uint32_t oem_revision;
    uint32_t creator_id;
    uint32_t creator_revision;
} __attribute__((packed));

struct RSDT {
    SDTHeader hdr;
    // followed by uint32_t pointers to other tables
} __attribute__((packed));

// MADT — I/O APIC / Local APIC info
struct MADT {
    SDTHeader hdr;
    uint32_t  lapic_addr;   // local APIC physical address
    uint32_t  flags;        // bit 0: 8259 PICs present
} __attribute__((packed));

struct MADTEntry {
    uint8_t  type;
    uint8_t  length;
} __attribute__((packed));

// MADT entry types
static constexpr uint8_t MADT_LAPIC      = 0;
static constexpr uint8_t MADT_IOAPIC     = 1;
static constexpr uint8_t MADT_ISO        = 2;  // interrupt source override
static constexpr uint8_t MADT_LAPIC_NMI  = 4;
static constexpr uint8_t MADT_LAPIC_ADDR = 5;  // 64-bit LAPIC addr override

struct MADTLocalAPIC {
    MADTEntry hdr;
    uint8_t   acpi_cpu_id;
    uint8_t   apic_id;
    uint32_t  flags;          // bit 0 = processor enabled
} __attribute__((packed));

struct MADTIOApic {
    MADTEntry hdr;
    uint8_t   ioapic_id;
    uint8_t   _reserved;
    uint32_t  ioapic_addr;
    uint32_t  global_system_interrupt_base;
} __attribute__((packed));

// FADT — Fixed ACPI Description Table
struct FADT {
    SDTHeader hdr;
    uint32_t  firmware_ctrl;
    uint32_t  dsdt_addr;
    uint8_t   _res1;
    uint8_t   preferred_pm_profile;
    uint16_t  sci_interrupt;
    uint32_t  smi_cmd;
    uint8_t   acpi_enable;
    uint8_t   acpi_disable;
    // ... abbreviated — we only need the first fields
} __attribute__((packed));

// ── CPU info extracted from MADT ──────────────────────────────────────────────
static constexpr size_t MAX_CPUS    = 32;
static constexpr size_t MAX_IOAPICS = 8;

struct CpuInfo {
    uint8_t acpi_id;
    uint8_t apic_id;
    bool    enabled;
};

struct IOApicInfo {
    uint8_t  id;
    uint32_t addr;
    uint32_t gsi_base;
};

// ── Public API ────────────────────────────────────────────────────────────────

// Locate the RSDP in low memory and EBDA, parse all tables.
bool init();

// True if ACPI was successfully initialised.
bool available();

// Number of CPUs found in MADT.
size_t cpu_count();

// Return CPU info for index i (0-based).
CpuInfo cpu(size_t i);

// Number of I/O APICs.
size_t ioapic_count();

// Return I/O APIC info for index i.
IOApicInfo ioapic(size_t i);

// Local APIC physical address (from MADT).
uint32_t lapic_addr();

// Pointer to a raw ACPI table by signature (e.g. "DSDT"), or nullptr.
const SDTHeader* find_table(const char* sig);

// Power off via ACPI S5 state (if FADT available).
void power_off();

// Reboot via ACPI reset register (if available).
void reboot();

} // namespace ACPI
