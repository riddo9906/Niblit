// os/kernel/vfs.cpp — Virtual Filesystem implementation
//
// RamFS: a flat array of (path, content) pairs — simple and sufficient
// for an early-boot environment.  DevFS supplies /dev/null and /dev/zero.
#include "vfs.h"
#include "vga.h"
#include "serial.h"
#include <stddef.h>

namespace VFS {

// ── String helpers ────────────────────────────────────────────────────────────
static size_t kstrlen(const char* s) { size_t n=0; while(s && *s++) ++n; return n; }
static int    kstrcmp(const char* a, const char* b) {
    while (*a && *a == *b) { ++a; ++b; }
    return (unsigned char)*a - (unsigned char)*b;
}
static void kstrcpy(char* d, const char* s, size_t n) {
    size_t i=0;
    for(; i<n-1 && s[i]; ++i) d[i]=s[i];
    d[i]='\0';
}
static void kmemcpy(void* d, const void* s, size_t n) {
    auto* dp=(uint8_t*)d; const auto* sp=(const uint8_t*)s;
    for(size_t i=0;i<n;++i) dp[i]=sp[i];
}

// ── RamFS inode ───────────────────────────────────────────────────────────────
struct Inode {
    bool   used;
    bool   is_dir;
    char   path[MAX_PATH];
    uint8_t data[MAX_FILE_SZ];
    size_t  size;
};

static Inode s_inodes[MAX_FILES];

// ── File descriptor table ─────────────────────────────────────────────────────
struct FD {
    bool    open;
    int     inode_idx;   // -1 for /dev/null, -2 for /dev/zero
    uint32_t flags;
    size_t   pos;
};
static FD s_fds[MAX_FD];

// ── Inode helpers ─────────────────────────────────────────────────────────────
static int find_inode(const char* path) {
    for (int i = 0; i < (int)MAX_FILES; ++i) {
        if (s_inodes[i].used && kstrcmp(s_inodes[i].path, path) == 0) return i;
    }
    return -1;
}

static int alloc_inode() {
    for (int i = 0; i < (int)MAX_FILES; ++i) {
        if (!s_inodes[i].used) return i;
    }
    return -1;
}

static int alloc_fd() {
    for (int i = 3; i < (int)MAX_FD; ++i) { // 0/1/2 = stdin/stdout/stderr
        if (!s_fds[i].open) return i;
    }
    return -1;
}

// ── init ──────────────────────────────────────────────────────────────────────
void init() {
    for (size_t i = 0; i < MAX_FILES; ++i) s_inodes[i] = {};
    for (size_t i = 0; i < MAX_FD; ++i)   s_fds[i]    = {};

    // Create root and standard directories
    auto mk = [](const char* p) {
        int idx = alloc_inode();
        if (idx < 0) return;
        s_inodes[idx].used   = true;
        s_inodes[idx].is_dir = true;
        kstrcpy(s_inodes[idx].path, p, MAX_PATH);
    };
    mk("/");
    mk("/dev");
    mk("/tmp");
    mk("/proc");
    mk("/var");
    mk("/var/log");

    // Create /proc/version
    write_file("/proc/version", "NiblitOS v1.0 (niblit-kernel)\n");
    // Create /dev/null sentinel (inode_idx = -1 is the dev/null convention)
    write_file("/dev/null", "");

    VGA::writeln("[VFS] Mounted RamFS at / and DevFS at /dev.");
    Serial::logln("[VFS] Ready. Directories: / /dev /tmp /proc /var");
}

// ── open ─────────────────────────────────────────────────────────────────────
int open(const char* path, uint32_t flags) {
    int iidx = find_inode(path);

    if (iidx < 0 && !(flags & O_CREAT)) return VFS_ENOENT;

    if (iidx < 0 && (flags & O_CREAT)) {
        iidx = alloc_inode();
        if (iidx < 0) return VFS_ENOMEM;
        s_inodes[iidx].used   = true;
        s_inodes[iidx].is_dir = false;
        s_inodes[iidx].size   = 0;
        kstrcpy(s_inodes[iidx].path, path, MAX_PATH);
    }

    if (flags & O_TRUNC) {
        s_inodes[iidx].size = 0;
    }

    int fd = alloc_fd();
    if (fd < 0) return VFS_ENOMEM;

    s_fds[fd].open      = true;
    s_fds[fd].inode_idx = iidx;
    s_fds[fd].flags     = flags;
    s_fds[fd].pos       = (flags & O_TRUNC) ? 0 : s_inodes[iidx].size;
    return fd;
}

// ── close ─────────────────────────────────────────────────────────────────────
int close(int fd) {
    if (fd < 0 || fd >= (int)MAX_FD || !s_fds[fd].open) return VFS_EBADF;
    s_fds[fd] = {};
    return VFS_OK;
}

// ── read ──────────────────────────────────────────────────────────────────────
int read(int fd, void* buf, size_t len) {
    if (fd < 0 || fd >= (int)MAX_FD || !s_fds[fd].open) return VFS_EBADF;

    int iidx = s_fds[fd].inode_idx;

    // /dev/zero
    if (iidx == -2) {
        auto* b = (uint8_t*)buf;
        for (size_t i = 0; i < len; ++i) b[i] = 0;
        return (int)len;
    }
    // /dev/null
    if (iidx == -1) return 0;

    Inode* in = &s_inodes[iidx];
    size_t avail = in->size > s_fds[fd].pos ? in->size - s_fds[fd].pos : 0;
    size_t n     = avail < len ? avail : len;
    if (n == 0) return 0;
    kmemcpy(buf, in->data + s_fds[fd].pos, n);
    s_fds[fd].pos += n;
    return (int)n;
}

// ── write ─────────────────────────────────────────────────────────────────────
int write(int fd, const void* buf, size_t len) {
    if (fd < 0 || fd >= (int)MAX_FD || !s_fds[fd].open) return VFS_EBADF;

    int iidx = s_fds[fd].inode_idx;
    if (iidx == -1) return (int)len; // /dev/null eats everything

    Inode* in = &s_inodes[iidx];
    size_t end = s_fds[fd].pos + len;
    if (end > MAX_FILE_SZ) return VFS_ENOMEM;

    kmemcpy(in->data + s_fds[fd].pos, buf, len);
    s_fds[fd].pos += len;
    if (s_fds[fd].pos > in->size) in->size = s_fds[fd].pos;
    return (int)len;
}

// ── seek ──────────────────────────────────────────────────────────────────────
int seek(int fd, int offset, int whence) {
    if (fd < 0 || fd >= (int)MAX_FD || !s_fds[fd].open) return VFS_EBADF;
    int iidx = s_fds[fd].inode_idx;
    if (iidx < 0) return VFS_EINVAL;
    Inode* in = &s_inodes[iidx];

    int newpos;
    if (whence == 0)      newpos = offset;                           // SEEK_SET
    else if (whence == 1) newpos = (int)s_fds[fd].pos + offset;     // SEEK_CUR
    else                  newpos = (int)in->size + offset;           // SEEK_END

    if (newpos < 0) return VFS_EINVAL;
    s_fds[fd].pos = (size_t)newpos;
    return newpos;
}

// ── mkdir ─────────────────────────────────────────────────────────────────────
int mkdir(const char* path) {
    if (find_inode(path) >= 0) return VFS_OK; // already exists
    int idx = alloc_inode();
    if (idx < 0) return VFS_ENOMEM;
    s_inodes[idx].used   = true;
    s_inodes[idx].is_dir = true;
    kstrcpy(s_inodes[idx].path, path, MAX_PATH);
    return VFS_OK;
}

// ── listdir ───────────────────────────────────────────────────────────────────
int listdir(const char* path, char* buf, size_t len) {
    size_t plen = kstrlen(path);
    size_t pos  = 0;

    for (size_t i = 0; i < MAX_FILES; ++i) {
        if (!s_inodes[i].used) continue;
        const char* p = s_inodes[i].path;
        size_t pl = kstrlen(p);
        if (pl <= plen) continue;
        // Check that p starts with path + '/'
        bool match = true;
        for (size_t j = 0; j < plen; ++j) {
            if (p[j] != path[j]) { match = false; break; }
        }
        if (!match) continue;
        if (p[plen] != '/') continue;
        // Only direct children (no further '/' after the prefix)
        bool direct = true;
        for (size_t j = plen + 1; j < pl; ++j) {
            if (p[j] == '/') { direct = false; break; }
        }
        if (!direct) continue;

        const char* name = p + plen + 1;
        size_t nl = kstrlen(name);
        if (pos + nl + 1 >= len) break;
        for (size_t j = 0; j < nl; ++j) buf[pos++] = name[j];
        buf[pos++] = '\n';
    }
    buf[pos] = '\0';
    return (int)pos;
}

// ── write_file / read_file (convenience) ─────────────────────────────────────
int write_file(const char* path, const char* content) {
    int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC);
    if (fd < 0) return fd;
    size_t len = kstrlen(content);
    int r = write(fd, content, len);
    close(fd);
    return r;
}

int read_file(const char* path, char* buf, size_t len) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) return fd;
    int r = read(fd, buf, len - 1);
    close(fd);
    if (r >= 0) buf[r] = '\0';
    return r;
}

} // namespace VFS
