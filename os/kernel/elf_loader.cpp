// os/kernel/elf_loader.cpp — ELF32 executable loader
#include "elf_loader.h"
#include "vfs.h"
#include "heap.h"
#include "process.h"
#include "vga.h"
#include "serial.h"
#include <stddef.h>

namespace ELF {

// ── ELF32 type definitions ────────────────────────────────────────────────────
using Elf32_Addr  = uint32_t;
using Elf32_Off   = uint32_t;
using Elf32_Half  = uint16_t;
using Elf32_Word  = uint32_t;

struct Elf32_Ehdr {
    uint8_t   e_ident[16];
    Elf32_Half e_type;
    Elf32_Half e_machine;
    Elf32_Word e_version;
    Elf32_Addr e_entry;
    Elf32_Off  e_phoff;
    Elf32_Off  e_shoff;
    Elf32_Word e_flags;
    Elf32_Half e_ehsize;
    Elf32_Half e_phentsize;
    Elf32_Half e_phnum;
    Elf32_Half e_shentsize;
    Elf32_Half e_shnum;
    Elf32_Half e_shstrndx;
} __attribute__((packed));

struct Elf32_Phdr {
    Elf32_Word p_type;
    Elf32_Off  p_offset;
    Elf32_Addr p_vaddr;
    Elf32_Addr p_paddr;
    Elf32_Word p_filesz;
    Elf32_Word p_memsz;
    Elf32_Word p_flags;
    Elf32_Word p_align;
} __attribute__((packed));

// ELF magic / constants
static constexpr uint8_t  ELFMAG0    = 0x7F;
static constexpr uint8_t  ELFMAG1    = 'E';
static constexpr uint8_t  ELFMAG2    = 'L';
static constexpr uint8_t  ELFMAG3    = 'F';
static constexpr uint8_t  ELFCLASS32 = 1;
static constexpr uint8_t  ELFDATA2LSB = 2;  // little-endian
static constexpr uint16_t ET_EXEC    = 2;
static constexpr uint16_t EM_386     = 3;   // i386
static constexpr uint32_t PT_LOAD    = 1;   // loadable segment

// ── String / memory helpers ───────────────────────────────────────────────────
static void kmemcpy(void* dst, const void* src, size_t n) {
    auto* d = (uint8_t*)dst;
    const auto* s = (const uint8_t*)src;
    for (size_t i = 0; i < n; ++i) d[i] = s[i];
}
static void kmemset(void* dst, uint8_t val, size_t n) {
    auto* d = (uint8_t*)dst;
    for (size_t i = 0; i < n; ++i) d[i] = val;
}
static size_t kstrlen(const char* s) { size_t n = 0; while (s && *s++) ++n; return n; }
static void kstrcpy(char* d, const char* s, size_t n) {
    size_t i = 0;
    for (; i < n - 1 && s[i]; ++i) d[i] = s[i];
    d[i] = '\0';
}

// ── Load ─────────────────────────────────────────────────────────────────────
LoadResult load(const void* buf, size_t buf_len) {
    LoadResult res{ELF_ENOTELF, 0, 0xFFFFFFFF, 0};

    if (buf_len < sizeof(Elf32_Ehdr)) {
        res.error = ELF_EBADF;
        return res;
    }

    const auto* ehdr = (const Elf32_Ehdr*)buf;

    // Validate ELF magic
    if (ehdr->e_ident[0] != ELFMAG0 || ehdr->e_ident[1] != ELFMAG1 ||
        ehdr->e_ident[2] != ELFMAG2 || ehdr->e_ident[3] != ELFMAG3) {
        res.error = ELF_ENOTELF;
        return res;
    }
    if (ehdr->e_ident[4] != ELFCLASS32) { res.error = ELF_EBADCLASS; return res; }
    if (ehdr->e_type    != ET_EXEC)      { res.error = ELF_ENOTSUP;  return res; }
    if (ehdr->e_machine != EM_386)       { res.error = ELF_ENOTSUP;  return res; }

    res.error = ELF_OK;
    res.entry = ehdr->e_entry;

    // Iterate PT_LOAD program headers
    for (uint16_t i = 0; i < ehdr->e_phnum; ++i) {
        size_t ph_off = ehdr->e_phoff + i * ehdr->e_phentsize;
        if (ph_off + sizeof(Elf32_Phdr) > buf_len) { res.error = ELF_EBADF; return res; }

        const auto* phdr = (const Elf32_Phdr*)((const uint8_t*)buf + ph_off);
        if (phdr->p_type != PT_LOAD || phdr->p_memsz == 0) continue;

        // Track load extent
        if (phdr->p_vaddr < res.load_base) res.load_base = phdr->p_vaddr;
        uint32_t seg_end = phdr->p_vaddr + phdr->p_memsz;
        if (seg_end > res.load_end) res.load_end = seg_end;

        // Map: allocate a heap buffer, copy file data, zero BSS
        // In a real paging kernel we'd map pages at p_vaddr directly.
        // Here we identity-map by writing directly to p_vaddr (works because
        // we've identity-mapped the first 8 MiB).
        if (phdr->p_vaddr + phdr->p_memsz > 8u * 1024 * 1024) {
            // Beyond our identity-mapped range — skip for now
            VGA::writeln("[ELF] WARNING: segment beyond 8 MiB — skipping");
            continue;
        }

        void* dest = (void*)(uintptr_t)phdr->p_vaddr;
        size_t file_bytes = phdr->p_filesz;
        size_t zero_bytes = phdr->p_memsz - phdr->p_filesz;

        if (phdr->p_offset + file_bytes > buf_len) { res.error = ELF_EBADF; return res; }

        const void* src = (const uint8_t*)buf + phdr->p_offset;
        kmemcpy(dest, src, file_bytes);
        if (zero_bytes) kmemset((uint8_t*)dest + file_bytes, 0, zero_bytes);

        VGA::write("[ELF] Loaded segment vaddr="); VGA::write_hex(phdr->p_vaddr);
        VGA::write(" size="); VGA::write_dec(phdr->p_memsz); VGA::newline();
    }

    Serial::log("[ELF] entry="); Serial::write_hex(Serial::COM1, res.entry); Serial::writeln(Serial::COM1, "");
    return res;
}

// ── exec: VFS path → task ─────────────────────────────────────────────────────
int exec(const char* vfs_path, const char* task_name) {
    // Read file from VFS
    static char s_elf_buf[VFS::MAX_FILE_SZ];
    int n = VFS::read_file(vfs_path, s_elf_buf, sizeof(s_elf_buf));
    if (n < 0) {
        VGA::write("[ELF] exec: VFS read error for ");
        VGA::writeln(vfs_path);
        return ELF_ENOENT;
    }

    LoadResult r = load(s_elf_buf, (size_t)n);
    if (r.error != ELF_OK) {
        VGA::write("[ELF] load failed error="); VGA::write_dec(-(int)r.error); VGA::newline();
        return r.error;
    }

    // Create a kernel task at the ELF entry point.
    // We cast the entry virtual address to a TaskFunc pointer.
    auto fn = (Process::TaskFunc)(uintptr_t)r.entry;

    // Build task name (fallback to path)
    char name[32] = {};
    if (task_name && task_name[0]) {
        kstrcpy(name, task_name, 32);
    } else {
        // Use filename portion of path
        const char* p = vfs_path;
        const char* last = vfs_path;
        while (*p) { if (*p == '/') last = p + 1; ++p; }
        kstrcpy(name, last, 32);
    }

    uint32_t tid = Process::create(name, fn);
    if (!tid) {
        VGA::writeln("[ELF] Process::create failed");
        return ELF_ENOMEM;
    }

    VGA::write("[ELF] Launched '"); VGA::write(name);
    VGA::write("' tid="); VGA::write_dec(tid); VGA::newline();
    return (int)tid;
}

} // namespace ELF
