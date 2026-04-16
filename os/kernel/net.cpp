// os/kernel/net.cpp — Network subsystem (E1000 NIC + minimal IP stack)
#include "net.h"
#include "pci.h"
#include "irq.h"
#include "heap.h"
#include "vga.h"
#include "serial.h"
#include "pit.h"
#include <stddef.h>
#include <stdint.h>

namespace Net {

// ── Endian helpers ────────────────────────────────────────────────────────────
static inline uint16_t htons(uint16_t v) { return (uint16_t)((v>>8)|(v<<8)); }
static inline uint16_t ntohs(uint16_t v) { return htons(v); }
static inline uint32_t htonl(uint32_t v) {
    return ((v>>24)&0xFF)|((v>>8)&0xFF00)|((v<<8)&0xFF0000)|((v<<24)&0xFF000000U);
}
static inline uint32_t ntohl(uint32_t v) { return htonl(v); }

static inline void outl(uint16_t p, uint32_t v) { asm volatile("outl %0,%1"::"a"(v),"Nd"(p)); }
static inline uint32_t inl(uint16_t p) { uint32_t v; asm volatile("inl %1,%0":"=a"(v):"Nd"(p)); return v; }
static inline void outb(uint16_t p, uint8_t v) { asm volatile("outb %0,%1"::"a"(v),"Nd"(p)); }
static inline uint8_t inb(uint16_t p) { uint8_t v; asm volatile("inb %1,%0":"=a"(v):"Nd"(p)); return v; }

// ── E1000 MMIO register offsets ───────────────────────────────────────────────
static constexpr uint32_t E1000_CTRL    = 0x0000;
static constexpr uint32_t E1000_STATUS  = 0x0008;
static constexpr uint32_t E1000_EECD    = 0x0010;
static constexpr uint32_t E1000_EERD    = 0x0014;
static constexpr uint32_t E1000_ICR     = 0x00C0;
static constexpr uint32_t E1000_IMS     = 0x00D0;
static constexpr uint32_t E1000_IMC     = 0x00D8;
static constexpr uint32_t E1000_RCTL    = 0x0100;
static constexpr uint32_t E1000_TCTL    = 0x0400;
static constexpr uint32_t E1000_RDBAL   = 0x2800;
static constexpr uint32_t E1000_RDBAH   = 0x2804;
static constexpr uint32_t E1000_RDLEN   = 0x2808;
static constexpr uint32_t E1000_RDH     = 0x2810;
static constexpr uint32_t E1000_RDT     = 0x2818;
static constexpr uint32_t E1000_TDBAL   = 0x3800;
static constexpr uint32_t E1000_TDBAH   = 0x3804;
static constexpr uint32_t E1000_TDLEN   = 0x3808;
static constexpr uint32_t E1000_TDH     = 0x3810;
static constexpr uint32_t E1000_TDT     = 0x3818;
static constexpr uint32_t E1000_RAL     = 0x5400;
static constexpr uint32_t E1000_RAH     = 0x5404;
static constexpr uint32_t E1000_MTA     = 0x5200;

static constexpr uint32_t E1000_CTRL_RST    = (1u << 26);
static constexpr uint32_t E1000_CTRL_ASDE   = (1u << 5);
static constexpr uint32_t E1000_CTRL_SLU    = (1u << 6);
static constexpr uint32_t E1000_RCTL_EN     = (1u << 1);
static constexpr uint32_t E1000_RCTL_SBP    = (1u << 2);
static constexpr uint32_t E1000_RCTL_UPE    = (1u << 3);
static constexpr uint32_t E1000_RCTL_MPE    = (1u << 4);
static constexpr uint32_t E1000_RCTL_LPE    = (1u << 5);
static constexpr uint32_t E1000_RCTL_BAM    = (1u << 15);
static constexpr uint32_t E1000_RCTL_BSIZE  = (3u << 16);
static constexpr uint32_t E1000_RCTL_SECRC  = (1u << 26);
static constexpr uint32_t E1000_TCTL_EN     = (1u << 1);
static constexpr uint32_t E1000_TCTL_PSP    = (1u << 3);
static constexpr uint32_t E1000_IMS_RXT0    = (1u << 7);

static constexpr size_t RX_DESC_COUNT = 32;
static constexpr size_t TX_DESC_COUNT = 8;
static constexpr size_t RX_BUF_SIZE   = 2048;

struct E1000RxDesc {
    uint64_t addr;
    uint16_t length;
    uint16_t checksum;
    uint8_t  status;
    uint8_t  errors;
    uint16_t special;
} __attribute__((packed));

struct E1000TxDesc {
    uint64_t addr;
    uint16_t length;
    uint8_t  cso;
    uint8_t  cmd;
    uint8_t  status;
    uint8_t  css;
    uint16_t special;
} __attribute__((packed));

// ── Module state ──────────────────────────────────────────────────────────────
static volatile uint32_t* s_mmio = nullptr;
static uint8_t  s_rx_buf[RX_DESC_COUNT][RX_BUF_SIZE] __attribute__((aligned(16)));
static E1000RxDesc s_rx_descs[RX_DESC_COUNT] __attribute__((aligned(16)));
static E1000TxDesc s_tx_descs[TX_DESC_COUNT] __attribute__((aligned(16)));
static uint32_t s_rx_tail = 0;
static uint32_t s_tx_tail = 0;

static NetIface s_ifaces[4];
static size_t   s_iface_count = 0;

static RxCallback s_rx_hook = nullptr;
static void*      s_rx_hook_ctx = nullptr;

// ARP cache
struct ArpEntry { IPv4Addr ip; MACAddr mac; bool valid; };
static ArpEntry s_arp_cache[16];

// UDP sockets
struct UdpSocket {
    bool       used;
    uint16_t   local_port;
    uint8_t    rx_buf[1500];
    size_t     rx_len;
    SockAddr   rx_src;
    bool       rx_ready;
};
static UdpSocket s_udp[SOCK_MAX];

// Sequence counter
static uint16_t s_ip_id   = 0;
static uint16_t s_icmp_id = 0x1234;

// ── MMIO helpers ──────────────────────────────────────────────────────────────
static inline uint32_t e1000_read(uint32_t reg) {
    return s_mmio[reg / 4];
}
static inline void e1000_write(uint32_t reg, uint32_t val) {
    s_mmio[reg / 4] = val;
}

// ── EEPROM read ───────────────────────────────────────────────────────────────
static uint16_t eeprom_read(uint8_t addr) {
    e1000_write(E1000_EERD, (1u) | ((uint32_t)addr << 8));
    uint32_t val;
    for (int i = 0; i < 10000; ++i) {
        val = e1000_read(E1000_EERD);
        if (val & (1u << 4)) break;
    }
    return (uint16_t)(val >> 16);
}

static void read_mac(MACAddr& mac) {
    uint16_t w0 = eeprom_read(0);
    uint16_t w1 = eeprom_read(1);
    uint16_t w2 = eeprom_read(2);
    mac.bytes[0] = (uint8_t)(w0 & 0xFF); mac.bytes[1] = (uint8_t)(w0 >> 8);
    mac.bytes[2] = (uint8_t)(w1 & 0xFF); mac.bytes[3] = (uint8_t)(w1 >> 8);
    mac.bytes[4] = (uint8_t)(w2 & 0xFF); mac.bytes[5] = (uint8_t)(w2 >> 8);
}

// ── E1000 IRQ handler ─────────────────────────────────────────────────────────
static void e1000_irq(uint8_t /*irq*/, void* /*ctx*/) {
    uint32_t icr = e1000_read(E1000_ICR);
    if (icr & E1000_IMS_RXT0) {
        // Receive one or more packets
        while (true) {
            uint32_t head = e1000_read(E1000_RDH);
            if (s_rx_tail == head) break;

            E1000RxDesc& desc = s_rx_descs[s_rx_tail];
            if (!(desc.status & 0x01)) break; // DD bit not set

            if (s_rx_hook && desc.length > 0) {
                s_rx_hook(s_rx_buf[s_rx_tail], desc.length, s_rx_hook_ctx);
            }

            // Return descriptor to ring
            desc.status = 0;
            e1000_write(E1000_RDT, s_rx_tail);
            s_rx_tail = (s_rx_tail + 1) % RX_DESC_COUNT;
        }
    }
}

// ── Checksum ─────────────────────────────────────────────────────────────────
static uint16_t ip_checksum(const void* data, size_t len) {
    const uint16_t* p = (const uint16_t*)data;
    uint32_t sum = 0;
    while (len > 1) { sum += *p++; len -= 2; }
    if (len) sum += *(const uint8_t*)p;
    while (sum >> 16) sum = (sum & 0xFFFF) + (sum >> 16);
    return (uint16_t)(~sum);
}

// ── Public API ────────────────────────────────────────────────────────────────
void init() {
    // Create loopback
    NetIface& lo = s_ifaces[s_iface_count++];
    for (int i=0;i<8;i++) lo.name[i]=0;
    lo.name[0]='l'; lo.name[1]='o';
    lo.mac = {};
    lo.ip      = {127,0,0,1};
    lo.netmask = {255,0,0,0};
    lo.gateway = {};
    lo.up      = true;

    // Look for E1000 on PCI
    const PCI::Device* nic = PCI::find_device(PCI::VENDOR_INTEL, PCI::DEV_E1000);
    if (!nic) nic = PCI::find_device(PCI::VENDOR_INTEL, PCI::DEV_E1000_E);
    if (!nic) {
        VGA::writeln("[NET] No E1000 NIC found — network limited to loopback.");
        return;
    }

    // Map MMIO BAR0
    uint32_t bar0 = nic->bar[0] & ~0xF; // clear flags
    s_mmio = reinterpret_cast<volatile uint32_t*>(bar0);

    PCI::enable_bus_master(nic);

    // Reset NIC
    e1000_write(E1000_CTRL, e1000_read(E1000_CTRL) | E1000_CTRL_RST);
    for (volatile int i = 0; i < 10000; ++i);
    e1000_write(E1000_CTRL, (e1000_read(E1000_CTRL) | E1000_CTRL_ASDE | E1000_CTRL_SLU)
                           & ~E1000_CTRL_RST);

    // Clear interrupts
    e1000_write(E1000_IMC, 0xFFFFFFFF);
    e1000_read(E1000_ICR);

    // Read MAC from EEPROM
    NetIface& eth = s_ifaces[s_iface_count++];
    for (int i=0;i<8;i++) eth.name[i]=0;
    eth.name[0]='e'; eth.name[1]='t'; eth.name[2]='h'; eth.name[3]='0';
    read_mac(eth.mac);
    eth.ip      = {192,168,1,100};
    eth.netmask = {255,255,255,0};
    eth.gateway = {192,168,1,1};
    eth.up      = true;

    // Program MAC into RAL/RAH
    uint32_t ral = (uint32_t)eth.mac.bytes[0]
                 | ((uint32_t)eth.mac.bytes[1] <<  8)
                 | ((uint32_t)eth.mac.bytes[2] << 16)
                 | ((uint32_t)eth.mac.bytes[3] << 24);
    uint32_t rah = (uint32_t)eth.mac.bytes[4]
                 | ((uint32_t)eth.mac.bytes[5] << 8)
                 | (1u << 31); // AV bit
    e1000_write(E1000_RAL, ral);
    e1000_write(E1000_RAH, rah);

    // Clear MTA
    for (int i = 0; i < 128; ++i) e1000_write(E1000_MTA + i*4, 0);

    // Setup RX descriptors
    for (size_t i = 0; i < RX_DESC_COUNT; ++i) {
        s_rx_descs[i].addr   = (uint64_t)(uintptr_t)s_rx_buf[i];
        s_rx_descs[i].status = 0;
    }
    e1000_write(E1000_RDBAL, (uint32_t)(uintptr_t)s_rx_descs);
    e1000_write(E1000_RDBAH, 0);
    e1000_write(E1000_RDLEN, RX_DESC_COUNT * sizeof(E1000RxDesc));
    e1000_write(E1000_RDH,   0);
    e1000_write(E1000_RDT,   RX_DESC_COUNT - 1);
    e1000_write(E1000_RCTL,  E1000_RCTL_EN | E1000_RCTL_BAM |
                             E1000_RCTL_SBP | E1000_RCTL_UPE |
                             E1000_RCTL_MPE | E1000_RCTL_SECRC);

    // Setup TX descriptors
    for (size_t i = 0; i < TX_DESC_COUNT; ++i) s_tx_descs[i] = {};
    e1000_write(E1000_TDBAL, (uint32_t)(uintptr_t)s_tx_descs);
    e1000_write(E1000_TDBAH, 0);
    e1000_write(E1000_TDLEN, TX_DESC_COUNT * sizeof(E1000TxDesc));
    e1000_write(E1000_TDH,   0);
    e1000_write(E1000_TDT,   0);
    e1000_write(E1000_TCTL,  E1000_TCTL_EN | E1000_TCTL_PSP | (0x10 << 4) | (0x40 << 12));

    // Enable RX interrupt
    e1000_write(E1000_IMS, E1000_IMS_RXT0);
    IRQ::register_handler(nic->irq_line, e1000_irq, nullptr);

    VGA::write("[NET] E1000 MAC=");
    for (int i = 0; i < 6; ++i) {
        VGA::write_hex(eth.mac.bytes[i]);
        if (i < 5) VGA::write(":");
    }
    VGA::writeln(" UP");
    Serial::logln("[NET] E1000 ready.");
}

const NetIface* iface(const char* name) {
    for (size_t i = 0; i < s_iface_count; ++i) {
        const char* n = s_ifaces[i].name;
        size_t j = 0;
        while (n[j] && n[j] == name[j]) ++j;
        if (n[j] == name[j]) return &s_ifaces[i];
    }
    return nullptr;
}
size_t iface_count() { return s_iface_count; }
const NetIface* iface(size_t i) { return (i < s_iface_count) ? &s_ifaces[i] : nullptr; }

void iface_set_ip(const char* name, IPv4Addr ip, IPv4Addr mask, IPv4Addr gw) {
    for (size_t i = 0; i < s_iface_count; ++i) {
        const char* n = s_ifaces[i].name;
        size_t j = 0;
        while (n[j] && n[j] == name[j]) ++j;
        if (n[j] != name[j]) continue;
        s_ifaces[i].ip      = ip;
        s_ifaces[i].netmask = mask;
        s_ifaces[i].gateway = gw;
        return;
    }
}
void iface_up(const char* name) {
    for (size_t i = 0; i < s_iface_count; ++i)
        if (s_ifaces[i].name[0] == name[0]) { s_ifaces[i].up = true; return; }
}
void iface_down(const char* name) {
    for (size_t i = 0; i < s_iface_count; ++i)
        if (s_ifaces[i].name[0] == name[0]) { s_ifaces[i].up = false; return; }
}

bool send_frame(const char* iface_name, const uint8_t* frame, size_t len) {
    if (!s_mmio) return false;

    E1000TxDesc& desc = s_tx_descs[s_tx_tail];
    desc.addr   = (uint64_t)(uintptr_t)frame;
    desc.length = (uint16_t)len;
    desc.cmd    = 0x0B; // EOP + IFCS + RS
    desc.status = 0;

    s_tx_tail = (s_tx_tail + 1) % TX_DESC_COUNT;
    e1000_write(E1000_TDT, s_tx_tail);

    // Wait for TX completion (RS bit sets status bit 0)
    uint32_t timeout = 100000;
    while (!(desc.status & 0xFF) && timeout--);

    const NetIface* ni = iface(iface_name);
    if (ni) const_cast<NetIface*>(ni)->tx_packets++;
    return true;
}

bool arp_resolve(const char* iface_name, IPv4Addr ip, MACAddr* out_mac) {
    // Check cache
    for (auto& e : s_arp_cache) {
        if (e.valid && e.ip == ip) { *out_mac = e.mac; return true; }
    }
    // Broadcast ARP request (simplified)
    // Real impl would send ARP, wait for reply interrupt
    // For now, broadcast MAC
    *out_mac = MAC_BROADCAST;
    return false;
}

void register_rx_hook(RxCallback cb, void* ctx) {
    s_rx_hook     = cb;
    s_rx_hook_ctx = ctx;
}

int icmp_ping(const char* iface_name, IPv4Addr target) {
    const NetIface* ni = iface(iface_name);
    if (!ni || !ni->up || !s_mmio) return -1;

    struct PingPacket {
        // Ethernet header
        uint8_t  dst_mac[6];
        uint8_t  src_mac[6];
        uint16_t ethertype;
        // IPv4 header
        uint8_t  ihl_ver;
        uint8_t  tos;
        uint16_t tot_len;
        uint16_t id;
        uint16_t frag_off;
        uint8_t  ttl;
        uint8_t  protocol;
        uint16_t checksum;
        uint8_t  src_ip[4];
        uint8_t  dst_ip[4];
        // ICMP header + data
        uint8_t  type;
        uint8_t  code;
        uint16_t icmp_cksum;
        uint16_t icmp_id;
        uint16_t icmp_seq;
        uint8_t  payload[56]; // 64-byte ICMP data
    } __attribute__((packed));

    PingPacket pkt = {};

    // Eth header
    for (int i=0;i<6;i++) pkt.dst_mac[i] = 0xFF;
    for (int i=0;i<6;i++) pkt.src_mac[i] = ni->mac.bytes[i];
    pkt.ethertype = htons(0x0800);

    // IPv4
    pkt.ihl_ver   = 0x45;
    pkt.tos       = 0;
    pkt.tot_len   = htons(20 + 8 + 56);
    pkt.id        = htons(++s_ip_id);
    pkt.frag_off  = 0;
    pkt.ttl       = 64;
    pkt.protocol  = 1; // ICMP
    for (int i=0;i<4;i++) pkt.src_ip[i] = ni->ip.bytes[i];
    for (int i=0;i<4;i++) pkt.dst_ip[i] = target.bytes[i];
    pkt.checksum  = ip_checksum(&pkt.ihl_ver, 20);

    // ICMP
    pkt.type      = 8; // Echo Request
    pkt.code      = 0;
    pkt.icmp_id   = htons(++s_icmp_id);
    pkt.icmp_seq  = htons(1);
    for (int i=0;i<56;i++) pkt.payload[i] = (uint8_t)i;
    pkt.icmp_cksum = ip_checksum(&pkt.type, 8 + 56);

    uint32_t t0 = PIT::millis();
    send_frame(iface_name, (const uint8_t*)&pkt, sizeof(pkt));

    // Poll for ICMP reply (simplified — just wait 1 s)
    while ((PIT::millis() - t0) < 1000) {
        asm volatile("hlt");
    }
    return -1; // reply detection not yet wired into RX path
}

int udp_open() {
    for (int i = 0; i < SOCK_MAX; ++i) {
        if (!s_udp[i].used) { s_udp[i].used = true; return i; }
    }
    return -1;
}
int  udp_bind(int fd, uint16_t port) {
    if (fd < 0 || fd >= SOCK_MAX || !s_udp[fd].used) return -1;
    s_udp[fd].local_port = port;
    return 0;
}
int udp_send(int fd, SockAddr dst, const void* data, size_t len) {
    // Simplified: wrap in IP+UDP and send raw
    // Full implementation would ARP-resolve + set correct headers
    (void)fd; (void)dst; (void)data; (void)len;
    return 0;
}
int udp_recv(int fd, SockAddr* src, void* buf, size_t len) {
    if (fd < 0 || fd >= SOCK_MAX || !s_udp[fd].used) return -1;
    if (!s_udp[fd].rx_ready) return -1;
    size_t n = s_udp[fd].rx_len < len ? s_udp[fd].rx_len : len;
    const uint8_t* src_buf = s_udp[fd].rx_buf;
    uint8_t* dst_buf = (uint8_t*)buf;
    for (size_t i = 0; i < n; ++i) dst_buf[i] = src_buf[i];
    if (src) *src = s_udp[fd].rx_src;
    s_udp[fd].rx_ready = false;
    return (int)n;
}
void udp_close(int fd) {
    if (fd >= 0 && fd < SOCK_MAX) s_udp[fd] = {};
}

void dump() {
    VGA::writeln("Network Interfaces:");
    for (size_t i = 0; i < s_iface_count; ++i) {
        const NetIface& n = s_ifaces[i];
        VGA::write("  "); VGA::write(n.name);
        VGA::write("  IP=");
        for (int j = 0; j < 4; ++j) {
            VGA::write_dec(n.ip.bytes[j]);
            if (j < 3) VGA::write(".");
        }
        VGA::write(n.up ? "  UP" : "  DOWN");
        VGA::write("  TX="); VGA::write_dec((uint32_t)n.tx_packets);
        VGA::write("  RX="); VGA::write_dec((uint32_t)n.rx_packets);
        VGA::newline();
    }
}

} // namespace Net
