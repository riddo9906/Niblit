// os/kernel/heap.h — Kernel dynamic memory allocator
//
// A simple two-level allocator:
//   • Small allocations (≤ SLAB_MAX bytes) → fixed-size slabs (8/16/32/64/128/256/512 B)
//   • Large allocations (> SLAB_MAX bytes) → whole page frames from Memory::alloc_frame()
//
// This gives O(1) alloc/free for the common small-object case without
// needing a full buddy system.
#pragma once
#include <stddef.h>
#include <stdint.h>

namespace Heap {

// Largest object served by the slab allocator; larger objects go to the page allocator.
static constexpr size_t SLAB_MAX = 512;

// Initialise the heap (call after Memory::init()).
void init();

// Allocate *size* bytes.  Returns nullptr on OOM.
void* kmalloc(size_t size);

// Free a previously allocated pointer.
void kfree(void* ptr);

// Return the number of bytes currently allocated from the heap.
size_t used_bytes();

} // namespace Heap
