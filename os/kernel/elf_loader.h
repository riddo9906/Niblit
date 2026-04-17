// os/kernel/elf_loader.h — ELF32 static executable loader
//
// Loads a statically-linked ELF32 executable from a VFS path into
// memory and returns the entry-point address.  The kernel creates
// a new task for the loaded program via Process::create_elf().
//
// Supported:
//   ELF32, little-endian, ET_EXEC (static)
//   PT_LOAD segments mapped at their p_vaddr
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace ELF {

// Return codes
static constexpr int ELF_OK         =  0;
static constexpr int ELF_ENOENT     = -1;   // file not found
static constexpr int ELF_ENOTELF    = -2;   // bad magic
static constexpr int ELF_EBADCLASS  = -3;   // not ELF32
static constexpr int ELF_ENOTSUP    = -4;   // unsupported type/arch
static constexpr int ELF_ENOMEM     = -5;   // out of memory
static constexpr int ELF_EBADF      = -6;   // bad segment / truncated

struct LoadResult {
    int       error;           // ELF_OK or negative error code
    uint32_t  entry;           // entry-point virtual address
    uint32_t  load_base;       // lowest loaded segment address
    uint32_t  load_end;        // highest loaded segment end address
};

// Load an ELF32 executable from a VFS path.
// *buf* must point to the file's content in memory with *buf_len* bytes.
LoadResult load(const void* buf, size_t buf_len);

// High-level: read from VFS and create a kernel task.
// Returns the task ID (> 0) or negative error.
int exec(const char* vfs_path, const char* task_name);

} // namespace ELF
