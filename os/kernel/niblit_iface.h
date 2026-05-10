// os/kernel/niblit_iface.h — Niblit AI Tool Interface Contract
//
// Defines the abstract interface and data structures that the OS kernel
// uses to communicate with the Niblit AI tool running as a userspace
// process.
//
// Architecture
// ────────────
//   NiblitOS Kernel
//       │
//       │  (shared memory ring buffer + IPC syscalls)
//       │
//   niblit_daemon (userspace process, runs Python via embedded interpreter
//                  or subprocess spawned from kernel init)
//       │
//       └─→  NiblitCore (Python) — full AI reasoning stack
//
// The kernel exposes two IPC primitives to the Niblit daemon:
//   1. niblit_send_request(NiblitRequest*)  — kernel asks Niblit a question
//   2. niblit_recv_response(NiblitResponse*) — kernel reads Niblit's answer
//
// The Niblit daemon maps the same shared ring buffer and polls / blocks on
// a semaphore.  Because the kernel is minimal (no dynamic allocator yet),
// requests and responses fit in fixed-size structs.
#pragma once
#include <stdint.h>
#include <stddef.h>

// Maximum string lengths (kept small to fit in shared memory frames).
static constexpr size_t NIBLIT_MAX_QUERY    = 1024;
static constexpr size_t NIBLIT_MAX_RESPONSE = 4096;
static constexpr size_t NIBLIT_MAX_TOOL     = 64;

// ── Request / Response structs ────────────────────────────────────────────────

// A request sent from the kernel (or a kernel task) to the Niblit AI tool.
struct NiblitRequest {
    uint32_t  id;                           // sequence number
    uint32_t  type;                         // 0 = query, 1 = tool-call, 2 = shutdown
    char      tool[NIBLIT_MAX_TOOL];        // named tool (for type==1), or empty
    char      query[NIBLIT_MAX_QUERY];      // natural-language or JSON payload
    uint8_t   _pad[4];                      // align to 8-byte boundary
} __attribute__((packed));

// A response returned from the Niblit AI tool to the kernel.
struct NiblitResponse {
    uint32_t  request_id;                   // echoes NiblitRequest.id
    uint32_t  status;                       // 0 = ok, 1 = error, 2 = pending
    char      result[NIBLIT_MAX_RESPONSE];  // JSON or plain-text answer
    uint8_t   _pad[4];
} __attribute__((packed));

// ── Shared ring buffer ────────────────────────────────────────────────────────

static constexpr size_t NIBLIT_RING_CAPACITY = 8;    // max in-flight requests

struct NiblitRing {
    volatile uint32_t head;     // producer index (kernel writes requests here)
    volatile uint32_t tail;     // consumer index (daemon reads requests here)
    // Phase 20: monotonically increasing epoch counter.
    // The kernel bumps this on every AI request dispatch so the userspace
    // daemon can tag decisions and detect temporal staleness.
    volatile uint32_t epoch_id;
    uint32_t          _ring_pad; // keep 8-byte alignment
    NiblitRequest     requests[NIBLIT_RING_CAPACITY];
    NiblitResponse    responses[NIBLIT_RING_CAPACITY];
};

// Physical address of the shared ring buffer page.
// The kernel allocates one page at init and maps it to a well-known virtual
// address so the Niblit daemon can map it via a special syscall.
static constexpr uint32_t NIBLIT_RING_VADDR = 0xD0000000;

// ── Kernel-side helper functions (implemented in niblit_iface.cpp) ────────────

#ifdef __cplusplus
namespace NiblitIface {

// Initialise the shared ring buffer at NIBLIT_RING_VADDR.
void init();

// Post a request to the Niblit daemon.  Returns the request id.
// Non-blocking: if the ring is full, returns 0 (drop).
// Bumps ring->epoch_id before writing so the daemon sees the current epoch.
uint32_t send_request(uint32_t type, const char* tool, const char* query);

// Poll for a response matching *request_id*.
// Returns nullptr if not yet available.
NiblitResponse* poll_response(uint32_t request_id);

// Convenience: ask Niblit a natural-language question (fire-and-forget).
void ask(const char* question);

// Convenience: invoke a named Niblit tool with a JSON arguments string.
void call_tool(const char* tool_name, const char* json_args);

// Phase 20 — Temporal Coherence:
// Atomically advance and return the ring's epoch_id.
// Called by SYS_NIBLIT_EPOCH_SYNC so the userspace Temporal Coherence
// Layer can synchronise its epoch counter with the kernel timeline.
uint32_t advance_epoch();

// Return the current epoch_id without advancing it.
uint32_t current_epoch();

} // namespace NiblitIface
#endif // __cplusplus
