// os/kernel/paging.h — x86 4 KiB page-table management
//
// Sets up two-level (directory + table) 32-bit paging so the CPU
// translates virtual → physical addresses.  The kernel is identity-mapped
// (virt == phys) for the first 8 MiB.  The Niblit shared ring is mapped
// at its NIBLIT_RING_VADDR virtual address.
//
// After Paging::init() the CR0.PG bit is set and all subsequent memory
// accesses go through the page tables.
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace Paging {

static constexpr size_t   PAGE_SIZE       = 4096;
static constexpr uint32_t PAGE_PRESENT    = 0x001; // P bit
static constexpr uint32_t PAGE_WRITABLE   = 0x002; // R/W bit
static constexpr uint32_t PAGE_USER       = 0x004; // U/S bit (ring 3 access)

// Initialise paging, identity-map the kernel (0..8 MiB), and enable CR0.PG.
// *kernel_end* is the physical address of the first byte after the kernel
// binary so we know which frames are already in use.
void init(uint32_t kernel_end);

// Map virtual address *virt* to physical address *phys* with the given flags.
// Allocates a new page table if the directory entry doesn't exist yet.
void map_page(uint32_t virt, uint32_t phys, uint32_t flags = PAGE_PRESENT | PAGE_WRITABLE);

// Unmap a virtual page (sets entry to 0 and flushes TLB).
void unmap_page(uint32_t virt);

// Translate a virtual address to its physical address.
// Returns 0 if not mapped.
uint32_t virt_to_phys(uint32_t virt);

// Invalidate the TLB entry for a single page.
void flush_tlb(uint32_t virt);

} // namespace Paging
