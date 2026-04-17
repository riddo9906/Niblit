// os/kernel/pci.h — PCI bus enumeration and configuration
//
// Provides brute-force PCI configuration space scan (method 1: port I/O).
// Detects all PCI devices and builds a static device list.
// Drivers call pci_find_device() to locate their hardware.
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace PCI {

// Config space I/O ports
static constexpr uint16_t PCI_CONFIG_ADDR = 0xCF8;
static constexpr uint16_t PCI_CONFIG_DATA = 0xCFC;

// Max devices to track
static constexpr size_t MAX_DEVICES = 64;

// Common PCI class codes
static constexpr uint8_t CLASS_STORAGE   = 0x01;
static constexpr uint8_t CLASS_NETWORK   = 0x02;
static constexpr uint8_t CLASS_DISPLAY   = 0x03;
static constexpr uint8_t CLASS_BRIDGE    = 0x06;
static constexpr uint8_t CLASS_SERIAL    = 0x07; // serial bus (USB)
static constexpr uint8_t CLASS_SOUND     = 0x04;

// Subclass codes for CLASS_STORAGE
static constexpr uint8_t SUB_IDE         = 0x01;
static constexpr uint8_t SUB_SATA        = 0x06; // AHCI
static constexpr uint8_t SUB_NVME        = 0x08;

// Subclass codes for CLASS_SERIAL
static constexpr uint8_t SUB_USB_UHCI    = 0x00;
static constexpr uint8_t SUB_USB_OHCI    = 0x10;
static constexpr uint8_t SUB_USB_EHCI    = 0x20;
static constexpr uint8_t SUB_USB_XHCI    = 0x30;

// Well-known vendor/device IDs
static constexpr uint16_t VENDOR_INTEL   = 0x8086;
static constexpr uint16_t VENDOR_VIRTIO  = 0x1AF4;
static constexpr uint16_t DEV_E1000      = 0x100E; // Intel 82540EM (QEMU default)
static constexpr uint16_t DEV_E1000_E    = 0x100F; // Intel 82545EM
static constexpr uint16_t DEV_VIRTIO_NET = 0x1000; // virtio-net (transitional)
static constexpr uint16_t DEV_PIIX3_IDE  = 0x7010; // Intel PIIX3 IDE
static constexpr uint16_t DEV_ICH9_AHCI  = 0x2922; // ICH9 AHCI (QEMU -M q35)

struct Device {
    uint8_t  bus;
    uint8_t  slot;
    uint8_t  func;
    uint16_t vendor_id;
    uint16_t device_id;
    uint8_t  class_code;
    uint8_t  subclass;
    uint8_t  prog_if;
    uint8_t  revision;
    uint8_t  header_type;
    uint8_t  irq_line;
    uint8_t  irq_pin;
    uint32_t bar[6];    // Base Address Registers
    bool     valid;
};

// Initialise: scan all buses, slots, and functions.
void init();

// Read a 32-bit DWORD from PCI config space.
uint32_t config_read32(uint8_t bus, uint8_t slot, uint8_t func, uint8_t offset);

// Write a 32-bit DWORD to PCI config space.
void config_write32(uint8_t bus, uint8_t slot, uint8_t func, uint8_t offset, uint32_t val);

// Read a 16-bit word from PCI config space.
uint16_t config_read16(uint8_t bus, uint8_t slot, uint8_t func, uint8_t offset);

// Read an 8-bit byte from PCI config space.
uint8_t config_read8(uint8_t bus, uint8_t slot, uint8_t func, uint8_t offset);

// Find a device by vendor + device ID. Returns nullptr if not found.
const Device* find_device(uint16_t vendor, uint16_t device_id);

// Find a device by class + subclass. Returns nullptr if not found.
const Device* find_class(uint8_t class_code, uint8_t subclass);

// Return total number of detected PCI devices.
size_t device_count();

// Return device at index i.
const Device* device(size_t i);

// Enable bus-mastering DMA for a device.
void enable_bus_master(const Device* dev);

// Print all discovered devices to VGA and Serial.
void dump();

} // namespace PCI
