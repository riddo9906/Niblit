// os/kernel/net.h — Network subsystem
//
// Provides:
//   - Loopback interface (lo)
//   - E1000 (Intel 82540EM) NIC driver (QEMU default)
//   - Minimal Ethernet + ARP + IPv4 + ICMP + UDP stack
//   - BSD-like socket API (SOCK_RAW, SOCK_DGRAM)
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace Net {

// ── Ethernet frame limits ─────────────────────────────────────────────────────
static constexpr size_t ETH_MIN_FRAME  = 64;
static constexpr size_t ETH_MAX_FRAME  = 1522;
static constexpr size_t ETH_HDR_SIZE   = 14;
static constexpr size_t IPV4_HDR_SIZE  = 20;
static constexpr size_t UDP_HDR_SIZE   = 8;
static constexpr size_t ICMP_HDR_SIZE  = 8;

// Ethernet type codes
static constexpr uint16_t ETHERTYPE_ARP  = 0x0806;
static constexpr uint16_t ETHERTYPE_IP4  = 0x0800;
static constexpr uint16_t ETHERTYPE_IP6  = 0x86DD;

// IP protocols
static constexpr uint8_t IP_PROTO_ICMP = 1;
static constexpr uint8_t IP_PROTO_TCP  = 6;
static constexpr uint8_t IP_PROTO_UDP  = 17;

// ── Address types ─────────────────────────────────────────────────────────────
struct MACAddr {
    uint8_t bytes[6];
    bool operator==(const MACAddr& o) const {
        for (int i = 0; i < 6; ++i) if (bytes[i] != o.bytes[i]) return false;
        return true;
    }
};
static const MACAddr MAC_BROADCAST = {0xFF,0xFF,0xFF,0xFF,0xFF,0xFF};

struct IPv4Addr {
    uint8_t bytes[4];
    bool operator==(const IPv4Addr& o) const {
        for (int i = 0; i < 4; ++i) if (bytes[i] != o.bytes[i]) return false;
        return true;
    }
};

// ── Network interface ─────────────────────────────────────────────────────────
struct NetIface {
    char      name[8];       // "lo", "eth0", etc.
    MACAddr   mac;
    IPv4Addr  ip;
    IPv4Addr  netmask;
    IPv4Addr  gateway;
    bool      up;
    uint64_t  rx_packets;
    uint64_t  tx_packets;
    uint64_t  rx_bytes;
    uint64_t  tx_bytes;
};

// ── Socket handle ─────────────────────────────────────────────────────────────
static constexpr size_t SOCK_MAX = 16;

struct SockAddr {
    uint16_t family;    // AF_INET = 2
    uint16_t port;      // host byte order
    IPv4Addr addr;
};

// ── Receive callback ──────────────────────────────────────────────────────────
// Called in interrupt context when a packet arrives.
using RxCallback = void (*)(const uint8_t* frame, size_t len, void* ctx);

// ── Initialise ────────────────────────────────────────────────────────────────
// Detects E1000 via PCI, sets up TX/RX rings, registers IRQ handler.
// Also creates the loopback interface.
void init();

// ── Interface management ──────────────────────────────────────────────────────
const NetIface* iface(const char* name);  // find by name
size_t          iface_count();
const NetIface* iface(size_t i);

// Configure an interface.
void iface_set_ip(const char* name, IPv4Addr ip, IPv4Addr mask, IPv4Addr gw);
void iface_up(const char* name);
void iface_down(const char* name);

// ── Transmit ──────────────────────────────────────────────────────────────────
// Send a raw Ethernet frame on the named interface.
bool send_frame(const char* iface_name, const uint8_t* frame, size_t len);

// ── ARP ───────────────────────────────────────────────────────────────────────
// Resolve an IPv4 address to a MAC address (may block up to 1 s).
bool arp_resolve(const char* iface_name, IPv4Addr ip, MACAddr* out_mac);

// ── UDP ───────────────────────────────────────────────────────────────────────
int  udp_open();                                          // return fd ≥ 0
int  udp_bind(int fd, uint16_t port);
int  udp_send(int fd, SockAddr dst, const void* data, size_t len);
int  udp_recv(int fd, SockAddr* src, void* buf, size_t len); // non-blocking
void udp_close(int fd);

// ── ICMP ping ─────────────────────────────────────────────────────────────────
// Send one ICMP Echo Request; returns round-trip ms or -1 on timeout (1 s).
int icmp_ping(const char* iface_name, IPv4Addr target);

// ── Raw receive hook ──────────────────────────────────────────────────────────
void register_rx_hook(RxCallback cb, void* ctx);

// ── Status dump ───────────────────────────────────────────────────────────────
void dump();

} // namespace Net
