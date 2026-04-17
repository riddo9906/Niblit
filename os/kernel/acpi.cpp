// os/kernel/acpi.cpp — ACPI subsystem implementation
#include "acpi.h"
#include "vga.h"
#include "serial.h"
#include <stddef.h>

namespace ACPI {

// ── Helpers ───────────────────────────────────────────────────────────────────
static uint8_t s_buf_checksum(const void* ptr, size_t len) {
    const auto* p = (const uint8_t*)ptr;
    uint8_t sum = 0;
    for (size_t i = 0; i < len; ++i) sum += p[i];
    return sum;
}

static bool s_sig4(const char* a, const char* b) {
    return a[0]==b[0] && a[1]==b[1] && a[2]==b[2] && a[3]==b[3];
}
static bool s_sig8(const char* a, const char* b) {
    for (int i = 0; i < 8; ++i) if (a[i] != b[i]) return false;
    return true;
}

// ── Module state ──────────────────────────────────────────────────────────────
static bool        s_ready         = false;
static const RSDP* s_rsdp          = nullptr;
static const RSDT* s_rsdt          = nullptr;
static uint32_t    s_lapic_addr    = 0;
static uint32_t    s_fadt_addr     = 0;

static CpuInfo     s_cpus[MAX_CPUS]       = {};
static IOApicInfo  s_ioapics[MAX_IOAPICS] = {};
static size_t      s_cpu_count    = 0;
static size_t      s_ioapic_count = 0;

// ── RSDP search ───────────────────────────────────────────────────────────────
static const RSDP* find_rsdp_in(uint32_t start, uint32_t end) {
    for (uint32_t addr = start; addr < end; addr += 16) {
        const auto* rsdp = reinterpret_cast<const RSDP*>(addr);
        if (!s_sig8(rsdp->signature, "RSD PTR ")) continue;
        if (s_buf_checksum(rsdp, 20) != 0) continue;
        return rsdp;
    }
    return nullptr;
}

static const RSDP* find_rsdp() {
    // 1. Search Extended BIOS Data Area (EBDA) — first 1 KiB
    uint32_t ebda = (uint32_t)(*(uint16_t*)0x40E) << 4;
    if (ebda) {
        const RSDP* r = find_rsdp_in(ebda, ebda + 1024);
        if (r) return r;
    }
    // 2. Search the BIOS ROM area 0xE0000–0xFFFFF
    return find_rsdp_in(0xE0000, 0x100000);
}

// ── MADT parser ───────────────────────────────────────────────────────────────
static void parse_madt(const MADT* madt) {
    s_lapic_addr = madt->lapic_addr;
    const uint8_t* p   = reinterpret_cast<const uint8_t*>(madt) + sizeof(MADT);
    const uint8_t* end = reinterpret_cast<const uint8_t*>(madt) + madt->hdr.length;

    while (p < end) {
        const auto* entry = reinterpret_cast<const MADTEntry*>(p);
        if (entry->length == 0) break;

        if (entry->type == MADT_LAPIC) {
            const auto* la = reinterpret_cast<const MADTLocalAPIC*>(p);
            if (s_cpu_count < MAX_CPUS) {
                s_cpus[s_cpu_count++] = { la->acpi_cpu_id, la->apic_id,
                                          (la->flags & 1) != 0 };
            }
        } else if (entry->type == MADT_IOAPIC) {
            const auto* io = reinterpret_cast<const MADTIOApic*>(p);
            if (s_ioapic_count < MAX_IOAPICS) {
                s_ioapics[s_ioapic_count++] = { io->ioapic_id,
                    io->ioapic_addr, io->global_system_interrupt_base };
            }
        } else if (entry->type == MADT_LAPIC_ADDR) {
            // 64-bit override (ACPI 2.0+)
            // For 32-bit mode we keep the 32-bit portion only
            const uint32_t* addr64 = reinterpret_cast<const uint32_t*>(p + 4);
            s_lapic_addr = addr64[0]; // lower 32 bits
        }
        p += entry->length;
    }
}

// ── RSDT parser ───────────────────────────────────────────────────────────────
static void parse_rsdt(const RSDT* rsdt) {
    size_t entry_count = (rsdt->hdr.length - sizeof(SDTHeader)) / sizeof(uint32_t);
    const uint32_t* entries = reinterpret_cast<const uint32_t*>(
        reinterpret_cast<const uint8_t*>(rsdt) + sizeof(SDTHeader));

    for (size_t i = 0; i < entry_count; ++i) {
        if (!entries[i]) continue;
        const auto* hdr = reinterpret_cast<const SDTHeader*>(entries[i]);
        if (s_buf_checksum(hdr, hdr->length) != 0) continue;

        if (s_sig4(hdr->signature, "APIC")) {
            parse_madt(reinterpret_cast<const MADT*>(hdr));
        } else if (s_sig4(hdr->signature, "FACP")) {
            s_fadt_addr = entries[i];
        }
    }
}

// ── Public API ────────────────────────────────────────────────────────────────
bool init() {
    s_rsdp = find_rsdp();
    if (!s_rsdp) {
        VGA::writeln("[ACPI] RSDP not found — ACPI unavailable.");
        Serial::logln("[ACPI] RSDP not found.");
        return false;
    }

    VGA::write("[ACPI] RSDP found at "); VGA::write_hex((uint32_t)(uintptr_t)s_rsdp);
    VGA::write(" rev="); VGA::write_dec(s_rsdp->revision); VGA::newline();

    s_rsdt = reinterpret_cast<const RSDT*>(s_rsdp->rsdt_addr);
    if (s_buf_checksum(s_rsdt, s_rsdt->hdr.length) != 0) {
        VGA::writeln("[ACPI] RSDT checksum invalid.");
        return false;
    }

    parse_rsdt(s_rsdt);

    VGA::write("[ACPI] CPUs="); VGA::write_dec(s_cpu_count);
    VGA::write(" IOAPICs="); VGA::write_dec(s_ioapic_count);
    VGA::write(" LAPIC=0x"); VGA::write_hex(s_lapic_addr);
    VGA::newline();
    Serial::logln("[ACPI] Tables parsed OK.");

    s_ready = true;
    return true;
}

bool     available()     { return s_ready; }
size_t   cpu_count()     { return s_cpu_count; }
CpuInfo  cpu(size_t i)   { return (i < s_cpu_count) ? s_cpus[i] : CpuInfo{}; }
size_t   ioapic_count()  { return s_ioapic_count; }
IOApicInfo ioapic(size_t i) { return (i < s_ioapic_count) ? s_ioapics[i] : IOApicInfo{}; }
uint32_t lapic_addr()    { return s_lapic_addr; }

const SDTHeader* find_table(const char* sig) {
    if (!s_rsdt) return nullptr;
    size_t count = (s_rsdt->hdr.length - sizeof(SDTHeader)) / sizeof(uint32_t);
    const uint32_t* entries = reinterpret_cast<const uint32_t*>(
        reinterpret_cast<const uint8_t*>(s_rsdt) + sizeof(SDTHeader));
    for (size_t i = 0; i < count; ++i) {
        if (!entries[i]) continue;
        const auto* hdr = reinterpret_cast<const SDTHeader*>(entries[i]);
        if (s_sig4(hdr->signature, sig)) return hdr;
    }
    return nullptr;
}

void power_off() {
    if (!s_fadt_addr) {
        VGA::writeln("[ACPI] power_off: FADT not found.");
        return;
    }
    const auto* fadt = reinterpret_cast<const FADT*>(s_fadt_addr);
    // Write ACPI enable bit to SMI_CMD, then set SLP_TYP for S5
    // This is a simplified stub; real code parses the _S5 AML object.
    // For QEMU: outw(0x604, 0x2000) performs shutdown with PIIX ACPI emulation.
    auto outw = [](uint16_t port, uint16_t val) {
        asm volatile("outw %0, %1" : : "a"(val), "Nd"(port));
    };
    VGA::writeln("[ACPI] Attempting ACPI power off...");
    Serial::logln("[ACPI] power_off triggered.");
    // QEMU ACPI PM1a_CNT shutdown (PIIX3/PIIX4)
    outw(0xB004, 0x2000);  // Bochs/QEMU old
    outw(0x0604, 0x2000);  // QEMU newer ACPI
    (void)fadt;
    // If still running, triple-fault
    asm volatile("cli; hlt");
}

void reboot() {
    VGA::writeln("[ACPI] Rebooting...");
    // Keyboard controller reset (port 0x64) — works on most x86 hardware
    auto outb = [](uint16_t port, uint8_t val) {
        asm volatile("outb %0, %1" : : "a"(val), "Nd"(port));
    };
    outb(0x64, 0xFE); // pulse CPU reset line
    asm volatile("cli; hlt");
}

} // namespace ACPI
