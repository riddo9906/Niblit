// os/kernel/msg.h — Kernel IPC messaging subsystem
//
// Provides System-V-style message queues and a simple pub/sub event bus.
//
// Kernel tasks (and eventually userspace processes) use this to exchange
// structured messages without sharing memory directly.
//
// Three primitives:
//   1. Message queues  — FIFO, typed, bounded (like msgsnd/msgrcv)
//   2. Event bus       — publish/subscribe by topic string
//   3. Notification    — one-shot signal delivery (like eventfd)
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace MSG {

// ── Message types ─────────────────────────────────────────────────────────────
static constexpr size_t MSG_MAX_DATA = 512;  // max payload bytes per message
static constexpr size_t MSG_QUEUE_DEPTH = 32; // messages per queue
static constexpr size_t MAX_QUEUES = 32;
static constexpr size_t MAX_TOPICS = 64;
static constexpr size_t MAX_NOTIFS = 64;

// Well-known message type IDs (positive = user; negative = kernel)
static constexpr int32_t MTYPE_ANY      =  0; // match any type in msgrcv
static constexpr int32_t MTYPE_KERNEL   = -1; // kernel notification
static constexpr int32_t MTYPE_SYSLOG   = -2; // kernel syslog entry
static constexpr int32_t MTYPE_NIBLIT   = -3; // Niblit AI tool event
static constexpr int32_t MTYPE_NET      = -4; // network event
static constexpr int32_t MTYPE_ATA      = -5; // ATA I/O completion
static constexpr int32_t MTYPE_USB      = -6; // USB plug/unplug event
static constexpr int32_t MTYPE_ACPI     = -7; // ACPI power event
static constexpr int32_t MTYPE_USER     =  1; // first user-defined type

struct Message {
    int32_t  mtype;               // message type (see MTYPE_* above)
    uint32_t sender;              // task ID of sender
    uint32_t seq;                 // monotonic sequence number
    size_t   data_len;            // bytes used in data[]
    uint8_t  data[MSG_MAX_DATA];  // payload
} __attribute__((packed));

// ── Queue API ─────────────────────────────────────────────────────────────────
using QueueId = int;  // ≥ 0 on success, < 0 on error

// Create or open a named queue.
QueueId queue_open(const char* name);

// Close (but don't destroy) a queue handle.
void queue_close(QueueId qid);

// Destroy a named queue and release all its messages.
void queue_destroy(const char* name);

// Send a message to a queue.
// Returns 0 on success, -1 if queue is full.
int msgsnd(QueueId qid, const Message* msg);

// Receive the oldest message matching *mtype* (0 = any).
// Non-blocking: returns -1 if no matching message is available.
int msgrcv(QueueId qid, Message* out, int32_t mtype);

// Return the number of messages currently in the queue.
size_t msgcount(QueueId qid);

// ── Event bus (pub/sub) ───────────────────────────────────────────────────────
using EventHandler = void (*)(const char* topic, const Message* msg, void* ctx);

// Subscribe to events published on *topic*.
bool subscribe(const char* topic, EventHandler handler, void* ctx = nullptr);

// Unsubscribe from a topic.
void unsubscribe(const char* topic, EventHandler handler);

// Publish an event to all subscribers of *topic*.
void publish(const char* topic, int32_t mtype, const void* data, size_t len);

// ── Notification (one-shot) ───────────────────────────────────────────────────
using NotifId = int;

// Create a notification slot; returns id ≥ 0 or -1 on error.
NotifId notif_create();

// Signal a notification (can be called from interrupt context).
void notif_signal(NotifId id);

// Wait for a notification (blocks; spins on hlt if no scheduler).
void notif_wait(NotifId id);

// Poll a notification without blocking; returns true if signalled.
bool notif_poll(NotifId id);

// Destroy a notification slot.
void notif_destroy(NotifId id);

// ── Initialise ────────────────────────────────────────────────────────────────
void init();

// ── Syslog helpers ────────────────────────────────────────────────────────────
// Post a log line to the MTYPE_SYSLOG queue (name = "syslog").
void syslog(const char* message);
void syslogf(const char* fmt, ...);

// Dump all queues and their pending message counts.
void dump();

} // namespace MSG
