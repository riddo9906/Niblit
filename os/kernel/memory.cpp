// os/kernel/memory.cpp — Physical page frame allocator implementation
//
// Uses a bitmap where each bit represents one 4096-byte physical page frame.
// Bit 0 = frame available, Bit 1 = frame allocated.
//
// The bitmap itself is placed in the BSS section (static array sized for up
// to 4 GiB of RAM = 1 048 576 frames = 131 072 bytes of bitmap).
#include "memory.h"
#include "vga.h"
#include <stddef.h>

namespace Memory {

// ── Multiboot2 memory-map entry ───────────────────────────────────────────────
struct MmapEntry {
    uint32_t entry_size;
    uint64_t base_addr;
    uint64_t length;
    uint32_t type;          // 1 = available RAM
} __attribute__((packed));

// ── bitmap storage (covers up to 4 GiB) ──────────────────────────────────────
static constexpr size_t MAX_FRAMES  = 1024 * 1024;          // 4 GiB / 4096
static constexpr size_t BITMAP_SIZE = MAX_FRAMES / 32;      // 32 bits per word

static uint32_t s_bitmap[BITMAP_SIZE];
static size_t   s_total  = 0;
static size_t   s_free   = 0;
static uint32_t s_kend   = 0;   // first frame after the kernel image

// ── bit manipulation ──────────────────────────────────────────────────────────
static inline void set_bit(size_t frame) {
    s_bitmap[frame / 32] |= (1u << (frame % 32));
}
static inline void clear_bit(size_t frame) {
    s_bitmap[frame / 32] &= ~(1u << (frame % 32));
}
static inline bool test_bit(size_t frame) {
    return (s_bitmap[frame / 32] >> (frame % 32)) & 1u;
}

// ── public ────────────────────────────────────────────────────────────────────
void init(uint32_t mmap_addr, uint32_t mmap_length, uint32_t kernel_end) {
    s_kend = kernel_end;

    // Mark everything allocated (unavailable) by default.
    for (size_t i = 0; i < BITMAP_SIZE; ++i) {
        s_bitmap[i] = 0xFFFFFFFF;
    }

    // Walk the Multiboot2 memory map and mark available regions as free.
    uint32_t offset = 0;
    while (offset < mmap_length) {
        const auto* entry = reinterpret_cast<const MmapEntry*>(mmap_addr + offset);
        if (entry->type == 1) {   // available RAM
            uint64_t start = entry->base_addr;
            uint64_t end   = start + entry->length;

            // Skip the first 1 MiB (BIOS/VGA area) and the kernel image.
            if (start < 0x100000) start = 0x100000;
            if (start < kernel_end) start = kernel_end;
            start = (start + PAGE_SIZE - 1) & ~(uint64_t)(PAGE_SIZE - 1);

            for (uint64_t addr = start; addr + PAGE_SIZE <= end && addr < (uint64_t)MAX_FRAMES * PAGE_SIZE; addr += PAGE_SIZE) {
                size_t frame = addr / PAGE_SIZE;
                if (frame < MAX_FRAMES) {
                    clear_bit(frame);
                    ++s_free;
                    ++s_total;
                }
            }
        }
        # The Multiboot2 mmap entry_size field records the size of the entry
        # body only (not the entry_size field itself, which is 4 bytes).
        offset += entry->entry_size + 4;
    }

    VGA::write("[MEM] Frames free: ");
    VGA::write_dec(s_free);
    VGA::write(" / total: ");
    VGA::write_dec(s_total);
    VGA::write(" (");
    VGA::write_dec(s_free * PAGE_SIZE / (1024 * 1024));
    VGA::writeln(" MiB free)");
}

uint32_t alloc_frame() {
    for (size_t word = 0; word < BITMAP_SIZE; ++word) {
        if (s_bitmap[word] == 0xFFFFFFFF) continue;
        for (uint32_t bit = 0; bit < 32; ++bit) {
            size_t frame = word * 32 + bit;
            if (frame >= MAX_FRAMES) break;
            if (!test_bit(frame)) {
                set_bit(frame);
                --s_free;
                return static_cast<uint32_t>(frame * PAGE_SIZE);
            }
        }
    }
    return 0; // OOM
}

void free_frame(uint32_t addr) {
    size_t frame = addr / PAGE_SIZE;
    if (frame < MAX_FRAMES && test_bit(frame)) {
        clear_bit(frame);
        ++s_free;
    }
}

Stats stats() {
    return { s_total, s_free, s_total - s_free };
}

} // namespace Memory
