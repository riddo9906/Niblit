// os/kernel/pci.cpp — PCI bus enumeration
#include "pci.h"
#include "vga.h"
#include "serial.h"
#include <stddef.h>

namespace PCI {

// ── I/O helpers ───────────────────────────────────────────────────────────────
static inline void outl(uint16_t port, uint32_t val) {
    asm volatile("outl %0, %1" : : "a"(val), "Nd"(port));
}
static inline uint32_t inl(uint16_t port) {
    uint32_t v;
    asm volatile("inl %1, %0" : "=a"(v) : "Nd"(port));
    return v;
}

// ── Module state ──────────────────────────────────────────────────────────────
static Device s_devices[MAX_DEVICES];
static size_t s_count = 0;

// ── Config space access ───────────────────────────────────────────────────────
uint32_t config_read32(uint8_t bus, uint8_t slot, uint8_t func, uint8_t offset) {
    uint32_t addr = (1u << 31)
                  | ((uint32_t)bus  << 16)
                  | ((uint32_t)slot << 11)
                  | ((uint32_t)func <<  8)
                  | (offset & 0xFC);
    outl(PCI_CONFIG_ADDR, addr);
    return inl(PCI_CONFIG_DATA);
}

void config_write32(uint8_t bus, uint8_t slot, uint8_t func, uint8_t offset, uint32_t val) {
    uint32_t addr = (1u << 31)
                  | ((uint32_t)bus  << 16)
                  | ((uint32_t)slot << 11)
                  | ((uint32_t)func <<  8)
                  | (offset & 0xFC);
    outl(PCI_CONFIG_ADDR, addr);
    outl(PCI_CONFIG_DATA, val);
}

uint16_t config_read16(uint8_t bus, uint8_t slot, uint8_t func, uint8_t offset) {
    uint32_t dword = config_read32(bus, slot, func, offset & ~3u);
    return (uint16_t)(dword >> ((offset & 2) * 8));
}

uint8_t config_read8(uint8_t bus, uint8_t slot, uint8_t func, uint8_t offset) {
    uint32_t dword = config_read32(bus, slot, func, offset & ~3u);
    return (uint8_t)(dword >> ((offset & 3) * 8));
}

// ── Bus scan ─────────────────────────────────────────────────────────────────
static void check_device(uint8_t bus, uint8_t slot, uint8_t func) {
    uint32_t id = config_read32(bus, slot, func, 0x00);
    if ((id & 0xFFFF) == 0xFFFF) return;  // nothing here

    if (s_count >= MAX_DEVICES) return;

    Device& d = s_devices[s_count++];
    d.valid      = true;
    d.bus        = bus;
    d.slot       = slot;
    d.func       = func;
    d.vendor_id  = (uint16_t)(id & 0xFFFF);
    d.device_id  = (uint16_t)(id >> 16);

    uint32_t class_rev = config_read32(bus, slot, func, 0x08);
    d.revision   = (uint8_t)(class_rev);
    d.prog_if    = (uint8_t)(class_rev >>  8);
    d.subclass   = (uint8_t)(class_rev >> 16);
    d.class_code = (uint8_t)(class_rev >> 24);

    uint32_t hdr_latency = config_read32(bus, slot, func, 0x0C);
    d.header_type = (uint8_t)(hdr_latency >> 16) & 0x7F;

    uint32_t irq_info = config_read32(bus, slot, func, 0x3C);
    d.irq_line = (uint8_t)(irq_info & 0xFF);
    d.irq_pin  = (uint8_t)((irq_info >> 8) & 0xFF);

    // Read BARs (header type 0)
    if (d.header_type == 0) {
        for (int i = 0; i < 6; ++i) {
            d.bar[i] = config_read32(bus, slot, func, 0x10 + i * 4);
        }
    } else {
        for (int i = 0; i < 6; ++i) d.bar[i] = 0;
    }
}

void init() {
    s_count = 0;
    for (uint32_t bus = 0; bus < 256; ++bus) {
        for (uint32_t slot = 0; slot < 32; ++slot) {
            uint32_t hdr_byte = config_read8((uint8_t)bus, (uint8_t)slot, 0, 0x0E);
            uint8_t max_func = (hdr_byte & 0x80) ? 8 : 1;
            for (uint8_t func = 0; func < max_func; ++func) {
                check_device((uint8_t)bus, (uint8_t)slot, func);
            }
        }
    }
    VGA::write("[PCI] "); VGA::write_dec((uint32_t)s_count); VGA::writeln(" devices found.");
    Serial::log("[PCI] devices="); Serial::write_dec(Serial::COM1, (uint64_t)s_count);
    Serial::writeln(Serial::COM1, "");
}

const Device* find_device(uint16_t vendor, uint16_t dev) {
    for (size_t i = 0; i < s_count; ++i) {
        if (s_devices[i].vendor_id == vendor && s_devices[i].device_id == dev)
            return &s_devices[i];
    }
    return nullptr;
}

const Device* find_class(uint8_t cls, uint8_t sub) {
    for (size_t i = 0; i < s_count; ++i) {
        if (s_devices[i].class_code == cls && s_devices[i].subclass == sub)
            return &s_devices[i];
    }
    return nullptr;
}

size_t        device_count() { return s_count; }
const Device* device(size_t i) { return (i < s_count) ? &s_devices[i] : nullptr; }

void enable_bus_master(const Device* dev) {
    if (!dev) return;
    uint32_t cmd = config_read32(dev->bus, dev->slot, dev->func, 0x04);
    cmd |= (1u << 2); // Bus Master Enable
    config_write32(dev->bus, dev->slot, dev->func, 0x04, cmd);
}

void dump() {
    VGA::writeln("PCI Devices:");
    for (size_t i = 0; i < s_count; ++i) {
        const Device& d = s_devices[i];
        VGA::write("  ");
        VGA::write_hex(d.bus); VGA::write(":"); VGA::write_hex(d.slot);
        VGA::write(".");      VGA::write_dec(d.func);
        VGA::write("  vid="); VGA::write_hex(d.vendor_id);
        VGA::write(" did="); VGA::write_hex(d.device_id);
        VGA::write(" cls="); VGA::write_hex(d.class_code);
        VGA::write("."); VGA::write_hex(d.subclass);
        VGA::write(" irq="); VGA::write_dec(d.irq_line);
        VGA::newline();
    }
}

} // namespace PCI
