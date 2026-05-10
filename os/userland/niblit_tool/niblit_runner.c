// os/userland/niblit_tool/niblit_runner.c
// ─────────────────────────────────────────────────────────────────────────────
// NiblitOS userspace daemon — Niblit AI Tool runner
//
// This process is spawned by the kernel init task as the first userspace
// program.  It:
//
//   1. Optionally starts niblit_entry.py in daemon mode (UNIX socket).
//   2. Polls the kernel's shared NiblitRing for requests.
//   3. For each request, sends it to the daemon via UNIX socket if available,
//      or forks a child that execs `python3 niblit_entry.py` (single-shot).
//   4. Writes the response back into the ring buffer.
//
// Compile on Linux host (development):
//   gcc -std=c11 -O2 -Wall niblit_runner.c -o niblit_runner
//
// Environment variables:
//   NIBLIT_SOCKET_PATH   — path for UNIX socket (default: /tmp/niblit.sock)
//   NIBLIT_NO_DAEMON     — set to 1 to disable daemon mode (always fork)
//   NIBLIT_ENTRY_PATH    — path to niblit_entry.py (default: niblit_entry.py)
//   NIBLIT_PYTHON        — python3 interpreter to use (default: python3)

#define _DEFAULT_SOURCE

#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <errno.h>
#include <signal.h>
#include <fcntl.h>

// Keep niblit_iface.h definitions available in userland too.
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
    volatile uint32_t epoch_id; // Phase 20: Temporal Coherence epoch counter
    uint32_t          _ring_pad;
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

    // Determine python interpreter and entry script
    const char* python = getenv("NIBLIT_PYTHON");
    if (!python || !python[0]) python = "python3";
    const char* entry = getenv("NIBLIT_ENTRY_PATH");
    if (!entry || !entry[0]) entry = "niblit_entry.py";

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

        execlp(python, python, entry, NULL);
        // Fallback paths
        execl("/usr/bin/python3", "python3", entry, NULL);
        execl("/bin/python3",     "python3", entry, NULL);
        fprintf(stderr, "ERROR: cannot exec %s %s\n", python, entry);
        _exit(1);
    }

    // Parent: read child output
    close(pipefd[1]);
    ssize_t n = 0, total = 0;
    while (total < NIBLIT_MAX_RESPONSE - 1) {
        n = read(pipefd[0], resp->result + total, (size_t)(NIBLIT_MAX_RESPONSE - 1 - total));
        if (n <= 0) break;
        total += n;
    }
    close(pipefd[0]);
    resp->result[total] = '\0';

    int status;
    waitpid(pid, &status, 0);
    resp->status = (WIFEXITED(status) && WEXITSTATUS(status) == 0) ? 0 : 1;
}

// ── Socket-based dispatch (daemon mode) ───────────────────────────────────────
static int g_daemon_fd = -1;   // connected socket to niblit daemon

static int connect_daemon(const char* socket_path) {
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return -1;
    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, socket_path, sizeof(addr.sun_path) - 1);
    if (connect(fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        close(fd);
        return -1;
    }
    return fd;
}

// Try to dispatch via the daemon socket; returns 1 on success, 0 on failure.
static int dispatch_via_socket(NiblitRing* ring, uint32_t req_idx,
                                const char* socket_path) {
    if (g_daemon_fd < 0) {
        g_daemon_fd = connect_daemon(socket_path);
        if (g_daemon_fd < 0) return 0;
    }

    NiblitRequest* req  = &ring->requests[req_idx];
    NiblitResponse* resp = &ring->responses[req_idx];
    resp->request_id = req->id;
    resp->status = 2; // pending

    // Build JSON request
    char request_json[NIBLIT_MAX_QUERY + 256];

    // Simple JSON string escape for query (replace " with \")
    char escaped_query[NIBLIT_MAX_QUERY * 2 + 4];
    size_t qi = 0, oi = 1;
    escaped_query[0] = '"';
    for (; req->query[qi] && oi < sizeof(escaped_query) - 3; qi++) {
        char c = req->query[qi];
        if (c == '"' || c == '\\') escaped_query[oi++] = '\\';
        if (c == '\n') { escaped_query[oi++] = '\\'; escaped_query[oi++] = 'n'; continue; }
        escaped_query[oi++] = c;
    }
    escaped_query[oi++] = '"';
    escaped_query[oi] = '\0';

    int w = snprintf(
        request_json,
        sizeof(request_json),
        "{\"request_id\":%u,\"type\":\"%s\",\"tool\":\"%s\",\"query\":%s}\n",
        req->id,
        req->type == 1 ? "tool" : "query",
        req->tool,
        escaped_query
    );
    if (w < 0 || (size_t)w >= sizeof(request_json)) {
        resp->status = 1;
        snprintf(resp->result, NIBLIT_MAX_RESPONSE,
                 "ERROR: request JSON too large");
        return 0;
    }

    // Send
    if (send(g_daemon_fd, request_json, strlen(request_json), MSG_NOSIGNAL) < 0) {
        close(g_daemon_fd);
        g_daemon_fd = -1;
        return 0;
    }

    // Receive response (wait for newline)
    char buf[NIBLIT_MAX_RESPONSE + 256];
    ssize_t total = 0;
    while (total < (ssize_t)sizeof(buf) - 1) {
        ssize_t n = recv(g_daemon_fd, buf + total, (size_t)(sizeof(buf) - 1 - total), 0);
        if (n <= 0) { close(g_daemon_fd); g_daemon_fd = -1; return 0; }
        total += n;
        if (memchr(buf, '\n', (size_t)total)) break;
    }
    buf[total] = '\0';

    // Extract "result" field (simple substring search — no full JSON parser)
    const char* result_key = "\"result\":\"";
    const char* rp = strstr(buf, result_key);
    if (rp) {
        rp += strlen(result_key);
        size_t ri = 0;
        while (*rp && *rp != '"' && ri < NIBLIT_MAX_RESPONSE - 1) {
            if (*rp == '\\' && *(rp+1)) {
                ++rp;
                if (*rp == 'n') resp->result[ri++] = '\n';
                else             resp->result[ri++] = *rp;
            } else {
                resp->result[ri++] = *rp;
            }
            ++rp;
        }
        resp->result[ri] = '\0';
    } else {
        size_t copy_n = (size_t)total;
        if (copy_n > NIBLIT_MAX_RESPONSE - 1) copy_n = NIBLIT_MAX_RESPONSE - 1;
        memcpy(resp->result, buf, copy_n);
        resp->result[copy_n] = '\0';
    }

    const char* status_ok = "\"status\":\"ok\"";
    resp->status = strstr(buf, status_ok) ? 0 : 1;
    return 1;
}

// ── Main loop ─────────────────────────────────────────────────────────────────
int main(void) {
    fprintf(stderr, "[niblit-runner] Starting Niblit AI tool daemon...\n");

    // Configuration from environment
    const char* socket_path = getenv("NIBLIT_SOCKET_PATH");
    if (!socket_path || !socket_path[0]) socket_path = "/tmp/niblit.sock";
    int no_daemon = (getenv("NIBLIT_NO_DAEMON") != NULL);

    // Attempt to map the kernel's shared ring.
    // On a real NiblitOS this would use a special syscall; on Linux we use
    // an anonymous shared-memory mapping for development.
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

    if (!no_daemon) {
        fprintf(stderr, "[niblit-runner] Starting niblit_entry.py daemon on %s\n", socket_path);
        // Launch niblit_entry.py --daemon in background
        const char* python = getenv("NIBLIT_PYTHON");
        if (!python || !python[0]) python = "python3";
        const char* entry = getenv("NIBLIT_ENTRY_PATH");
        if (!entry || !entry[0]) entry = "niblit_entry.py";

        pid_t dpid = fork();
        if (dpid == 0) {
            // Child: start the daemon (detach from terminal)
            setsid();
            execlp(python, python, entry, "--daemon", "--socket", socket_path, NULL);
            _exit(1);
        }
        if (dpid > 0) {
            fprintf(stderr, "[niblit-runner] Daemon pid=%d; waiting for socket...\n", dpid);
            // Give the daemon 3 seconds to start
            for (int i = 0; i < 30; i++) {
                usleep(100000); // 100 ms
                if (access(socket_path, F_OK) == 0) break;
            }
        }
    }

    fprintf(stderr, "[niblit-runner] Waiting for kernel requests...\n");

    // Ignore SIGPIPE (in case socket connection drops)
    signal(SIGPIPE, SIG_IGN);

    // Poll loop
    while (1) {
        if (ring->tail != ring->head) {
            uint32_t idx = ring->tail;
            fprintf(stderr, "[niblit-runner] Processing request #%u (type=%u tool='%s')\n",
                    ring->requests[idx].id,
                    ring->requests[idx].type,
                    ring->requests[idx].tool);
            // Try socket dispatch first; fall back to fork-exec
            if (no_daemon || !dispatch_via_socket(ring, idx, socket_path)) {
                dispatch(ring, idx);
            }
            ring->tail = (ring->tail + 1) % NIBLIT_RING_CAPACITY;
        } else {
            usleep(1000); // 1 ms sleep between polls
        }
    }

    munmap(ring_mem, sizeof(NiblitRing));
    return 0;
}
