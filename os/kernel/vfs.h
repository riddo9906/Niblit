// os/kernel/vfs.h — Virtual Filesystem (VFS) abstraction
//
// Provides a POSIX-like file abstraction over multiple backends:
//   - RamFS   — in-memory filesystem (default for /tmp, /proc)
//   - DevFS   — virtual device files (/dev/null, /dev/zero, /dev/niblit)
//
// All paths are absolute.  The VFS resolves paths to the correct backend
// based on the mount table.
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace VFS {

static constexpr size_t MAX_PATH     = 256;
static constexpr size_t MAX_FD       = 64;
static constexpr size_t MAX_FILES    = 128;  // RamFS file limit
static constexpr size_t MAX_FILE_SZ  = 4096; // max RamFS file content

// Open flags
static constexpr uint32_t O_RDONLY = 0x00;
static constexpr uint32_t O_WRONLY = 0x01;
static constexpr uint32_t O_RDWR   = 0x02;
static constexpr uint32_t O_CREAT  = 0x40;
static constexpr uint32_t O_TRUNC  = 0x200;

// Return codes
static constexpr int VFS_OK        =  0;
static constexpr int VFS_ENOENT    = -2;
static constexpr int VFS_EBADF     = -9;
static constexpr int VFS_EINVAL    = -22;
static constexpr int VFS_ENOMEM    = -12;

// Initialise VFS, mount RamFS at / and DevFS at /dev.
void init();

// Open a file; returns fd ≥ 0 or negative error.
int open(const char* path, uint32_t flags);

// Close a file descriptor.
int close(int fd);

// Read up to *len* bytes; returns bytes read or negative error.
int read(int fd, void* buf, size_t len);

// Write *len* bytes; returns bytes written or negative error.
int write(int fd, const void* buf, size_t len);

// Seek to position; returns new position or negative error.
int seek(int fd, int offset, int whence);

// Create a directory (RamFS only).
int mkdir(const char* path);

// List directory entries into *buf* (newline-separated names).
int listdir(const char* path, char* buf, size_t len);

// Write a string directly to a VFS path (convenience).
int write_file(const char* path, const char* content);

// Read the full content of a file into *buf*.
int read_file(const char* path, char* buf, size_t len);

} // namespace VFS
