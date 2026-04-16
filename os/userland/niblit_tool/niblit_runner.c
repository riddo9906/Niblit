// os/userland/niblit_tool/niblit_runner.c
// ─────────────────────────────────────────────────────────────────────────────
// NiblitOS userspace daemon — Niblit AI Tool runner
//
// This process is spawned by the kernel init task as the first userspace
// program.  It:
//
//   1. Mmaps the kernel's shared NiblitRing at NIBLIT_RING_VADDR.
//   2. Polls the ring for requests posted by the kernel.
//   3. For each request, forks a child that execs `python3 niblit_entry.py`
//      with the request payload passed via stdin.
//   4. Writes the response back into the ring buffer.
//
// In a full NiblitOS build this binary is compiled as a flat ELF and placed
// in the OS's initrd alongside niblit_entry.py (the Python bootstrap that
// imports NiblitCore).
//
// Compile (once a C standard library port exists for NiblitOS):
//   i686-elf-gcc -std=c11 -O2 -Wall niblit_runner.c -o niblit_runner
//
// On a standard Linux host (for development testing):
//   gcc -std=c11 -O2 -Wall niblit_runner.c -o niblit_runner

#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <errno.h>

// Keep niblit_iface.h definitions available in userland too.
// We replicate the critical constants here to avoid a kernel header dependency.
#define NIBLIT_MAX_QUERY     1024
#define NIBLIT_MAX_RESPONSE  4096
#define NIBLIT_MAX_TOOL      64
#define NIBLIT_RING_CAPACITY 8
#define NIBLIT_RING_VADDR    0xD0000000u

typedef struct {
    uint32_t id;
    uint32_t type;
    char     tool[NIBLIT_MAX_TOOL];
    char     query[NIBLIT_MAX_QUERY];
    uint8_t  _pad[4];
} NiblitRequest;

typedef struct {
    uint32_t request_id;
    uint32_t status;
    char     result[NIBLIT_MAX_RESPONSE];
    uint8_t  _pad[4];
} NiblitResponse;

typedef struct {
    volatile uint32_t head;
    volatile uint32_t tail;
    NiblitRequest     requests[NIBLIT_RING_CAPACITY];
    NiblitResponse    responses[NIBLIT_RING_CAPACITY];
} NiblitRing;

// ── Dispatch a request to the Niblit Python process ───────────────────────────
static void dispatch(NiblitRing* ring, uint32_t req_idx) {
    NiblitRequest* req = &ring->requests[req_idx];
    NiblitResponse* resp = &ring->responses[req_idx];
    resp->request_id = req->id;
    resp->status = 2; // pending

    int pipefd[2];
    if (pipe(pipefd) == -1) {
        snprintf(resp->result, NIBLIT_MAX_RESPONSE, "ERROR: pipe() failed: %s", strerror(errno));
        resp->status = 1;
        return;
    }

    pid_t pid = fork();
    if (pid < 0) {
        snprintf(resp->result, NIBLIT_MAX_RESPONSE, "ERROR: fork() failed: %s", strerror(errno));
        resp->status = 1;
        close(pipefd[0]);
        close(pipefd[1]);
        return;
    }

    if (pid == 0) {
        // Child: redirect stdout to pipe write-end, then exec niblit_entry.py
        close(pipefd[0]);
        dup2(pipefd[1], STDOUT_FILENO);
        close(pipefd[1]);

        // Pass request as environment variables
        char id_str[16];
        snprintf(id_str, sizeof(id_str), "%u", req->id);
        setenv("NIBLIT_REQUEST_ID",   id_str,    1);
        setenv("NIBLIT_REQUEST_TYPE", req->type == 1 ? "tool" : "query", 1);
        setenv("NIBLIT_TOOL",         req->tool,  1);
        setenv("NIBLIT_QUERY",        req->query, 1);

        execl("/bin/python3", "python3", "niblit_entry.py", NULL);
        // If exec fails, fall back to a simple echo
        execl("/usr/bin/python3", "python3", "niblit_entry.py", NULL);
        fprintf(stderr, "ERROR: cannot exec niblit_entry.py\n");
        _exit(1);
    }

    // Parent: read child output
    close(pipefd[1]);
    ssize_t n = read(pipefd[0], resp->result, NIBLIT_MAX_RESPONSE - 1);
    close(pipefd[0]);
    if (n < 0) n = 0;
    resp->result[n] = '\0';

    int status;
    waitpid(pid, &status, 0);
    resp->status = (WIFEXITED(status) && WEXITSTATUS(status) == 0) ? 0 : 1;
}

// ── Main loop ─────────────────────────────────────────────────────────────────
int main(void) {
    fprintf(stderr, "[niblit-runner] Starting Niblit AI tool daemon...\n");

    // Attempt to map the kernel's shared ring.
    // On a real NiblitOS this would use a special syscall; on Linux we use
    // /dev/mem or a shared-memory segment for development.
    void* ring_mem = mmap(NULL, sizeof(NiblitRing),
                          PROT_READ | PROT_WRITE,
                          MAP_ANON | MAP_SHARED, -1, 0);
    if (ring_mem == MAP_FAILED) {
        fprintf(stderr, "[niblit-runner] mmap failed: %s\n", strerror(errno));
        return 1;
    }

    NiblitRing* ring = (NiblitRing*)ring_mem;
    memset(ring, 0, sizeof(NiblitRing));
    fprintf(stderr, "[niblit-runner] Ring buffer mapped at %p\n", ring_mem);
    fprintf(stderr, "[niblit-runner] Waiting for kernel requests...\n");

    // Poll loop
    while (1) {
        if (ring->tail != ring->head) {
            uint32_t idx = ring->tail;
            fprintf(stderr, "[niblit-runner] Processing request #%u (type=%u tool='%s')\n",
                    ring->requests[idx].id,
                    ring->requests[idx].type,
                    ring->requests[idx].tool);
            dispatch(ring, idx);
            ring->tail = (ring->tail + 1) % NIBLIT_RING_CAPACITY;
        } else {
            usleep(1000); // 1 ms sleep between polls
        }
    }

    munmap(ring_mem, sizeof(NiblitRing));
    return 0;
}
