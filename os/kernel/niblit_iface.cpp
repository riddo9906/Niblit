// os/kernel/niblit_iface.cpp — Niblit AI Tool interface implementation
//
// Manages the shared ring buffer used to communicate between the kernel
// and the Niblit AI daemon running in userspace.
#include "niblit_iface.h"
#include "vga.h"
#include "memory.h"
#include "paging.h"
#include <stddef.h>

// Simple byte-copy (no libc available in early kernel)
static void kstrncpy(char* dst, const char* src, size_t n) {
    size_t i = 0;
    for (; i < n - 1 && src[i]; ++i) dst[i] = src[i];
    dst[i] = '\0';
}

namespace NiblitIface {

static NiblitRing* s_ring    = nullptr;
static uint32_t    s_seq     = 1;

void init() {
    // Allocate one physical page for the ring buffer
    uint32_t phys = Memory::alloc_frame();
    if (!phys) {
        VGA::writeln("[NIBLIT] ERROR: cannot allocate ring buffer page — OOM");
        return;
    }

    // Map the physical page at the canonical shared virtual address so:
    // - SYS_NIBLIT_MMAP_RING returns a real mapped location
    // - kernel + userspace agree on a single authority address
    Paging::map_page(
        NIBLIT_RING_VADDR,
        phys,
        Paging::PAGE_PRESENT | Paging::PAGE_WRITABLE | Paging::PAGE_USER
    );
    s_ring = reinterpret_cast<NiblitRing*>(NIBLIT_RING_VADDR);

    // Zero-init the ring (includes epoch_id = 0)
    volatile uint8_t* p = reinterpret_cast<volatile uint8_t*>(s_ring);
    for (size_t i = 0; i < sizeof(NiblitRing); ++i) p[i] = 0;

    VGA::write("[NIBLIT] Ring buffer vaddr=");
    VGA::write_hex(NIBLIT_RING_VADDR);
    VGA::write(" phys=");
    VGA::write_hex(phys);
    VGA::writeln(" epoch=0 (Phase 20 TCL) — Niblit AI tool interface ready.");
}

uint32_t send_request(uint32_t type, const char* tool, const char* query) {
    if (!s_ring) return 0;

    uint32_t next = (s_ring->head + 1) % NIBLIT_RING_CAPACITY;
    if (next == s_ring->tail) {
        // Ring full — drop
        VGA::writeln("[NIBLIT] WARNING: request ring full, dropping.");
        return 0;
    }

    // Phase 20: advance the temporal epoch on every request dispatch so the
    // userspace Temporal Coherence Layer can synchronise its epoch counter.
    s_ring->epoch_id++;

    NiblitRequest* req = &s_ring->requests[s_ring->head];
    req->id   = s_seq++;
    req->type = type;
    kstrncpy(req->tool,  tool  ? tool  : "", NIBLIT_MAX_TOOL);
    kstrncpy(req->query, query ? query : "", NIBLIT_MAX_QUERY);

    // Advance head (visible to daemon after this write).
    s_ring->head = next;
    return req->id;
}

NiblitResponse* poll_response(uint32_t request_id) {
    if (!s_ring) return nullptr;
    for (size_t i = 0; i < NIBLIT_RING_CAPACITY; ++i) {
        NiblitResponse* resp = &s_ring->responses[i];
        if (resp->request_id == request_id && resp->status != 2 /*pending*/) {
            return resp;
        }
    }
    return nullptr;
}

void ask(const char* question) {
    uint32_t id = send_request(0, "", question);
    VGA::write("[NIBLIT] Query #");
    VGA::write_dec(id);
    VGA::write(" posted: ");
    VGA::writeln(question);
}

void call_tool(const char* tool_name, const char* json_args) {
    uint32_t id = send_request(1, tool_name, json_args);
    VGA::write("[NIBLIT] Tool-call #");
    VGA::write_dec(id);
    VGA::write(" -> ");
    VGA::writeln(tool_name);
}

// ── Phase 20: Temporal Coherence epoch helpers ────────────────────────────────

uint32_t advance_epoch() {
    if (!s_ring) return 0;
    return ++s_ring->epoch_id;
}

uint32_t current_epoch() {
    if (!s_ring) return 0;
    return s_ring->epoch_id;
}

} // namespace NiblitIface
