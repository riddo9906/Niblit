// os/userland/shell/shell.c
// ─────────────────────────────────────────────────────────────────────────────
// NiblitOS userspace shell
//
// This is an independent userspace program that uses int 0x80 system calls
// to interact with the kernel and with the Niblit AI tool.
//
// On real NiblitOS this compiles to a bare-metal ELF loaded by the kernel's
// ELF loader.  On Linux it compiles normally for development testing:
//   gcc -std=c11 -O2 -Wall -DLINUX_TEST shell.c -o niblit-shell
//
// System calls used:
//   SYS_WRITE  (4)  — write to stdout
//   SYS_READ   (3)  — read from stdin
//   SYS_EXIT   (1)  — exit
//   SYS_YIELD  (24) — yield to scheduler
//   SYS_NIBLIT_QUERY (201) — send AI query
//   SYS_NIBLIT_TOOL  (202) — invoke AI tool
//   SYS_MEM_INFO     (200) — memory statistics
//   SYS_PROC_LIST    (203) — process list

#include <stdint.h>
#include <stddef.h>

// ── Syscall numbers (mirror kernel/syscall.h) ─────────────────────────────────
#define SYS_EXIT         1
#define SYS_READ         3
#define SYS_WRITE        4
#define SYS_YIELD        24
#define SYS_MEM_INFO     200
#define SYS_NIBLIT_QUERY 201
#define SYS_NIBLIT_TOOL  202
#define SYS_PROC_LIST    203

#define FD_STDIN  0
#define FD_STDOUT 1
#define FD_STDERR 2

// ── Inline syscall wrappers ───────────────────────────────────────────────────

#ifdef LINUX_TEST
// On Linux, use libc for development testing
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static inline int _write(int fd, const char* buf, size_t len) {
    return (int)write(fd, buf, len);
}
static inline int _read(int fd, char* buf, size_t len) {
    return (int)read(fd, buf, len);
}
static inline void _exit_proc(int code) { _exit(code); }
static inline int _mem_info(char* buf, size_t len) {
    return snprintf(buf, len, "free=128M (Linux test mode)");
}
static inline int _niblit_query(const char* q) {
    fprintf(stderr, "[NIBLIT-QUERY] %s\n", q);
    return 1;
}
static inline int _niblit_tool(const char* tool, const char* args) {
    fprintf(stderr, "[NIBLIT-TOOL] %s(%s)\n", tool, args);
    return 2;
}
static inline int _proc_list(char* buf, size_t len) {
    return snprintf(buf, len, "1 shell (running)\n");
}

#else
// Bare-metal: invoke int 0x80 directly
static inline int _syscall3(int num, int a1, int a2, int a3) {
    int ret;
    asm volatile(
        "int 0x80"
        : "=a"(ret)
        : "0"(num), "b"(a1), "c"(a2), "d"(a3)
        : "memory"
    );
    return ret;
}
static inline int _syscall2(int num, int a1, int a2) {
    return _syscall3(num, a1, a2, 0);
}
static inline int _syscall1(int num, int a1) {
    return _syscall3(num, a1, 0, 0);
}
static inline int _syscall0(int num) {
    return _syscall3(num, 0, 0, 0);
}

static inline int _write(int fd, const char* buf, size_t len) {
    return _syscall3(SYS_WRITE, fd, (int)(uintptr_t)buf, (int)len);
}
static inline int _read(int fd, char* buf, size_t len) {
    return _syscall3(SYS_READ, fd, (int)(uintptr_t)buf, (int)len);
}
static inline void _exit_proc(int code) {
    _syscall1(SYS_EXIT, code);
    while (1) asm volatile("hlt");
}
static inline int _mem_info(char* buf, size_t len) {
    return _syscall2(SYS_MEM_INFO, (int)(uintptr_t)buf, (int)len);
}
static inline int _niblit_query(const char* q) {
    return _syscall1(SYS_NIBLIT_QUERY, (int)(uintptr_t)q);
}
static inline int _niblit_tool(const char* tool, const char* args) {
    return _syscall2(SYS_NIBLIT_TOOL, (int)(uintptr_t)tool, (int)(uintptr_t)args);
}
static inline int _proc_list(char* buf, size_t len) {
    return _syscall2(SYS_PROC_LIST, (int)(uintptr_t)buf, (int)len);
}
#endif // LINUX_TEST

// ── Minimal string library ────────────────────────────────────────────────────
static size_t slen(const char* s) { size_t n=0; while(*s++) n++; return n; }
static void   swrite(const char* s) { _write(FD_STDOUT, s, slen(s)); }
static int    scmp(const char* a, const char* b) {
    while(*a && *a==*b){a++;b++;} return (unsigned char)*a-(unsigned char)*b;
}
static int    sstartswith(const char* s, const char* p) {
    while(*p){ if(*s++!=*p++) return 0; } return 1;
}

// ── Shell banner ──────────────────────────────────────────────────────────────
static const char BANNER[] =
    "\r\n"
    "  ███╗   ██╗██╗██████╗ ██╗     ██╗████████╗      ██████╗ ███████╗\r\n"
    "  ████╗  ██║██║██╔══██╗██║     ██║╚══██╔══╝     ██╔═══██╗██╔════╝\r\n"
    "  ██╔██╗ ██║██║██████╔╝██║     ██║   ██║        ██║   ██║███████╗\r\n"
    "  ██║╚██╗██║██║██╔══██╗██║     ██║   ██║        ██║   ██║╚════██║\r\n"
    "  ██║ ╚████║██║██████╔╝███████╗██║   ██║        ╚██████╔╝███████║\r\n"
    "  ╚═╝  ╚═══╝╚═╝╚═════╝ ╚══════╝╚═╝   ╚═╝         ╚═════╝ ╚══════╝\r\n"
    "\r\n"
    "  NiblitOS v2.0  —  AI-Integrated Operating System\r\n"
    "  Type 'help' for available commands.\r\n\r\n";

// ── Command handlers ──────────────────────────────────────────────────────────
static void cmd_help(void) {
    swrite(
        "Commands:\r\n"
        "  help              — this help\r\n"
        "  version           — OS version\r\n"
        "  mem               — memory stats\r\n"
        "  ps                — process list\r\n"
        "  ask <query>       — query the Niblit AI\r\n"
        "  tool <name> <j>   — call a Niblit AI tool (JSON args)\r\n"
        "  echo <text>       — print text\r\n"
        "  clear             — clear screen (sends VT100 escape)\r\n"
        "  exit              — exit shell\r\n"
    );
}

static void cmd_version(void) {
    swrite("NiblitOS v2.0\r\n"
           "  Kernel:  C++ (i686 Multiboot2)\r\n"
           "  AI tool: Niblit (Python NiblitCore)\r\n"
           "  Shell:   niblit-shell v1.0\r\n");
}

static void cmd_mem(void) {
    char buf[128];
    _mem_info(buf, sizeof(buf));
    swrite("Memory: "); swrite(buf); swrite("\r\n");
}

static void cmd_ps(void) {
    char buf[1024] = {0};
    _proc_list(buf, sizeof(buf));
    swrite(buf); swrite("\r\n");
}

static void cmd_ask(const char* query) {
    if (!*query) { swrite("Usage: ask <query>\r\n"); return; }
    int id = _niblit_query(query);
    swrite("Niblit query #");
    char num[16]; int n=0; int v=id;
    if(v<=0){num[n++]='0';}else{while(v){num[n++]='0'+(v%10);v/=10;}}
    char rev[16]; for(int i=0;i<n;i++) rev[i]=num[n-1-i]; rev[n]=0;
    swrite(rev); swrite(" posted — response will appear on VGA/log.\r\n");
}

static void cmd_tool(const char* rest) {
    // tool <name> <json>
    if (!*rest) { swrite("Usage: tool <name> <json-args>\r\n"); return; }
    char name[64] = {0};
    size_t i = 0;
    while (rest[i] && rest[i] != ' ' && i < 63) { name[i] = rest[i]; i++; }
    const char* args = (rest[i] == ' ') ? rest + i + 1 : "{}";
    int id = _niblit_tool(name, args);
    swrite("Tool '"); swrite(name); swrite("' call #");
    char num[16]; int n=0; int v=id;
    if(v<=0){num[n++]='0';}else{while(v){num[n++]='0'+(v%10);v/=10;}}
    char rev[16]; for(int i2=0;i2<n;i2++) rev[i2]=num[n-1-i2]; rev[n]=0;
    swrite(rev); swrite(" posted.\r\n");
}

// ── Main REPL ─────────────────────────────────────────────────────────────────
#define LINE_MAX 512

int main(void) {
    swrite(BANNER);

    char line[LINE_MAX];
    size_t pos = 0;

    while (1) {
        swrite("\033[32mniblit-os\033[0m> ");  // green prompt

        pos = 0;
        while (1) {
            char c = 0;
            int r = _read(FD_STDIN, &c, 1);
            if (r <= 0) break;

            if (c == '\r' || c == '\n') {
                swrite("\r\n");
                break;
            } else if ((c == 127 || c == '\b') && pos > 0) {
                --pos;
                swrite("\b \b");
            } else if (c >= 32 && pos < LINE_MAX - 1) {
                line[pos++] = c;
                _write(FD_STDOUT, &c, 1);  // echo
            }
        }
        line[pos] = '\0';
        if (pos == 0) continue;

        // Dispatch
        if (scmp(line, "help") == 0)          cmd_help();
        else if (scmp(line, "version") == 0)  cmd_version();
        else if (scmp(line, "mem") == 0)      cmd_mem();
        else if (scmp(line, "ps") == 0)       cmd_ps();
        else if (scmp(line, "exit") == 0)     { swrite("Goodbye.\r\n"); _exit_proc(0); }
        else if (scmp(line, "clear") == 0)    swrite("\033[2J\033[H");
        else if (sstartswith(line, "echo "))  { swrite(line + 5); swrite("\r\n"); }
        else if (sstartswith(line, "ask "))   cmd_ask(line + 4);
        else if (sstartswith(line, "tool "))  cmd_tool(line + 5);
        else {
            swrite("Unknown command: '"); swrite(line); swrite("'\r\n");
            swrite("Type 'help' for a list of commands.\r\n");
        }
    }
    return 0;
}
