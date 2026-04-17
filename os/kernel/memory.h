// os/kernel/memory.h — Physical page frame allocator
//
// Manages available physical RAM using a simple bitmap allocator.
// Every frame is 4096 bytes (one page).  The allocator is seeded by
// the Multiboot2 memory map during kernel_main() startup.
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace Memory {

static constexpr size_t PAGE_SIZE = 4096;

// Initialise the allocator from a Multiboot2 memory-map base address
// and total bytes of available RAM.
void init(uint32_t mmap_addr, uint32_t mmap_length, uint32_t kernel_end);

// Allocate one physical page frame.  Returns 0 on OOM.
uint32_t alloc_frame();

// Free a previously allocated frame.
void free_frame(uint32_t frame_addr);

// Stats
struct Stats {
    size_t total_frames;
    size_t free_frames;
    size_t used_frames;
};
Stats stats();

} // namespace Memory
