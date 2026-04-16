// os/kernel/heap.cpp — Kernel slab + page-frame heap implementation
//
// Small allocations (≤ SLAB_MAX bytes) use fixed-size slab caches.
// Each slab object is prefixed by a 4-byte "size tag" so kfree can
// identify the correct slab without a separate metadata table.
// Large allocations use whole page frames with a LargeHeader prefix.
#include "heap.h"
#include "memory.h"
#include "vga.h"
#include "serial.h"
#include <stddef.h>

namespace Heap {

// ── Slab sizes ────────────────────────────────────────────────────────────────
static constexpr size_t SLAB_SIZES[]  = { 8, 16, 32, 64, 128, 256, 512 };
static constexpr size_t NUM_SLABS     = sizeof(SLAB_SIZES) / sizeof(SLAB_SIZES[0]);

// The actual object stored in a slab is:
//   [ uint32_t tag | ... payload ... ]
// where tag == obj_size (used by kfree to locate the correct slab).
static constexpr size_t TAG_SIZE = sizeof(uint32_t);

// Each free object in a slab stores a pointer to the next free object.
struct FreeNode {
    FreeNode* next;
};

struct SlabCache {
    size_t    obj_size;   // size of the user-visible payload
    size_t    full_size;  // obj_size + TAG_SIZE
    FreeNode* free_list;
    size_t    allocated;
};

// ── Large allocation header ───────────────────────────────────────────────────
struct LargeHeader {
    uint32_t magic;
    size_t   size;
    size_t   num_pages;
};
static constexpr uint32_t HEAP_MAGIC = 0xDEADBEEF;

// ── State ─────────────────────────────────────────────────────────────────────
static SlabCache s_slabs[NUM_SLABS];
static size_t    s_used = 0;

// ── Slab helpers ──────────────────────────────────────────────────────────────
static void replenish(SlabCache* sc) {
    uint32_t frame = Memory::alloc_frame();
    if (!frame) return;

    uint8_t* p   = reinterpret_cast<uint8_t*>(frame);
    size_t   cnt = Memory::PAGE_SIZE / sc->full_size;

    for (size_t i = 0; i < cnt; ++i) {
        uint8_t* raw = p + i * sc->full_size;
        // Write the tag at the start of the raw block.
        *reinterpret_cast<uint32_t*>(raw) = static_cast<uint32_t>(sc->obj_size);
        // The FreeNode overlaps the payload bytes (only used while free).
        auto* node    = reinterpret_cast<FreeNode*>(raw + TAG_SIZE);
        node->next    = sc->free_list;
        sc->free_list = node;
    }
}

static SlabCache* find_slab_for_size(size_t size) {
    for (size_t i = 0; i < NUM_SLABS; ++i) {
        if (s_slabs[i].obj_size >= size) return &s_slabs[i];
    }
    return nullptr;
}

static SlabCache* find_slab_by_tag(uint32_t tag) {
    for (size_t i = 0; i < NUM_SLABS; ++i) {
        if (s_slabs[i].obj_size == static_cast<size_t>(tag)) return &s_slabs[i];
    }
    return nullptr;
}

// ── Public ────────────────────────────────────────────────────────────────────
void init() {
    for (size_t i = 0; i < NUM_SLABS; ++i) {
        s_slabs[i].obj_size  = SLAB_SIZES[i];
        s_slabs[i].full_size = SLAB_SIZES[i] + TAG_SIZE;
        s_slabs[i].free_list = nullptr;
        s_slabs[i].allocated = 0;
        replenish(&s_slabs[i]);
    }
    VGA::writeln("[HEAP] Kernel slab allocator ready.");
    Serial::logln("[HEAP] Ready.");
}

void* kmalloc(size_t size) {
    if (size == 0) return nullptr;

    SlabCache* sc = find_slab_for_size(size);
    if (sc) {
        if (!sc->free_list) replenish(sc);
        if (!sc->free_list) return nullptr;

        FreeNode* node  = sc->free_list;
        sc->free_list   = node->next;
        ++sc->allocated;
        s_used += sc->obj_size;

        // The tag is stored at (node - TAG_SIZE); it was written in replenish().
        return node; // payload starts right after the tag
    }

    // Large allocation
    size_t total     = sizeof(LargeHeader) + size;
    size_t num_pages = (total + Memory::PAGE_SIZE - 1) / Memory::PAGE_SIZE;

    uint8_t* first = nullptr;
    for (size_t i = 0; i < num_pages; ++i) {
        uint32_t frame = Memory::alloc_frame();
        if (!frame) return nullptr;
        if (i == 0) first = reinterpret_cast<uint8_t*>(frame);
    }

    auto* hdr      = reinterpret_cast<LargeHeader*>(first);
    hdr->magic     = HEAP_MAGIC;
    hdr->size      = size;
    hdr->num_pages = num_pages;

    s_used += num_pages * Memory::PAGE_SIZE;
    return first + sizeof(LargeHeader);
}

void kfree(void* ptr) {
    if (!ptr) return;

    // ── Large allocation? ────────────────────────────────────────────────────
    auto* hdr = reinterpret_cast<LargeHeader*>(
        reinterpret_cast<uint8_t*>(ptr) - sizeof(LargeHeader));
    if (hdr->magic == HEAP_MAGIC) {
        uint8_t* p = reinterpret_cast<uint8_t*>(hdr);
        for (size_t i = 0; i < hdr->num_pages; ++i) {
            Memory::free_frame(reinterpret_cast<uint32_t>(p + i * Memory::PAGE_SIZE));
        }
        s_used -= hdr->num_pages * Memory::PAGE_SIZE;
        hdr->magic = 0;
        return;
    }

    // ── Slab allocation — read tag to find correct slab ──────────────────────
    // The tag word is stored immediately before the payload (ptr).
    uint32_t tag = *reinterpret_cast<uint32_t*>(
        reinterpret_cast<uint8_t*>(ptr) - TAG_SIZE);
    SlabCache* sc = find_slab_by_tag(tag);
    if (!sc) {
        // Unknown pointer — log and ignore to avoid corruption.
        Serial::log("[HEAP] kfree: unknown ptr tag=");
        Serial::write_hex(Serial::COM1, tag);
        Serial::writeln(Serial::COM1, "");
        return;
    }

    auto* node    = reinterpret_cast<FreeNode*>(ptr);
    node->next    = sc->free_list;
    sc->free_list = node;
    --sc->allocated;
    s_used -= sc->obj_size;
}

size_t used_bytes() { return s_used; }

} // namespace Heap

