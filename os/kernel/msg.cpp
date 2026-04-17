// os/kernel/msg.cpp — Kernel IPC messaging subsystem
#include "msg.h"
#include "vga.h"
#include "serial.h"
#include "heap.h"
#include "process.h"
#include <stddef.h>
#include <stdarg.h>

namespace MSG {

// ── Queue store ───────────────────────────────────────────────────────────────
struct Queue {
    bool   used;
    char   name[32];
    size_t head;    // read index
    size_t tail;    // write index
    size_t count;
    Message msgs[MSG_QUEUE_DEPTH];
};

static Queue s_queues[MAX_QUEUES];

// ── Topic store ───────────────────────────────────────────────────────────────
struct Subscriber {
    EventHandler handler;
    void*        ctx;
};
struct Topic {
    bool       used;
    char       name[32];
    Subscriber subs[8];
    size_t     sub_count;
};
static Topic s_topics[MAX_TOPICS];

// ── Notification store ────────────────────────────────────────────────────────
struct Notif {
    bool used;
    volatile bool signalled;
};
static Notif s_notifs[MAX_NOTIFS];

// ── String helpers ────────────────────────────────────────────────────────────
static bool str_eq(const char* a, const char* b) {
    while (*a && *b && *a == *b) { ++a; ++b; }
    return *a == *b;
}
static void str_copy(char* dst, const char* src, size_t n) {
    size_t i = 0;
    for (; i < n - 1 && src[i]; ++i) dst[i] = src[i];
    dst[i] = '\0';
}
static void mem_copy(void* dst, const void* src, size_t n) {
    auto* d = (uint8_t*)dst; const auto* s = (const uint8_t*)src;
    for (size_t i = 0; i < n; ++i) d[i] = s[i];
}

// ── Syslog queue id ───────────────────────────────────────────────────────────
static QueueId s_syslog_qid = -1;
static uint32_t s_seq = 0;

// ── Queue API ─────────────────────────────────────────────────────────────────
void init() {
    for (auto& q : s_queues) q = {};
    for (auto& t : s_topics) t = {};
    for (auto& n : s_notifs) n = {};

    // Create well-known syslog queue
    s_syslog_qid = queue_open("syslog");
    VGA::writeln("[MSG] IPC messaging subsystem ready.");
    Serial::logln("[MSG] Ready.");
}

QueueId queue_open(const char* name) {
    // Find existing
    for (int i = 0; i < (int)MAX_QUEUES; ++i) {
        if (s_queues[i].used && str_eq(s_queues[i].name, name)) return i;
    }
    // Allocate new
    for (int i = 0; i < (int)MAX_QUEUES; ++i) {
        if (!s_queues[i].used) {
            s_queues[i] = {};
            s_queues[i].used = true;
            str_copy(s_queues[i].name, name, 32);
            return i;
        }
    }
    return -1;
}

void queue_close(QueueId) { /* no-op: ref counted in full impl */ }

void queue_destroy(const char* name) {
    for (auto& q : s_queues) {
        if (q.used && str_eq(q.name, name)) { q = {}; return; }
    }
}

int msgsnd(QueueId qid, const Message* msg) {
    if (qid < 0 || qid >= (int)MAX_QUEUES || !s_queues[qid].used) return -1;
    Queue& q = s_queues[qid];
    if (q.count >= MSG_QUEUE_DEPTH) return -1;

    Message& m = q.msgs[q.tail];
    mem_copy(&m, msg, sizeof(Message));
    m.seq = ++s_seq;
    m.sender = Process::current() ? Process::current()->id : 0;

    q.tail = (q.tail + 1) % MSG_QUEUE_DEPTH;
    ++q.count;
    return 0;
}

int msgrcv(QueueId qid, Message* out, int32_t mtype) {
    if (qid < 0 || qid >= (int)MAX_QUEUES || !s_queues[qid].used) return -1;
    Queue& q = s_queues[qid];
    if (q.count == 0) return -1;

    // Linear scan for matching mtype
    size_t idx = q.head;
    for (size_t i = 0; i < q.count; ++i) {
        Message& m = q.msgs[idx % MSG_QUEUE_DEPTH];
        if (mtype == MTYPE_ANY || m.mtype == mtype) {
            mem_copy(out, &m, sizeof(Message));
            // Compact ring (simplified: just advance head)
            q.head = (q.head + 1) % MSG_QUEUE_DEPTH;
            --q.count;
            return 0;
        }
        ++idx;
    }
    return -1;
}

size_t msgcount(QueueId qid) {
    if (qid < 0 || qid >= (int)MAX_QUEUES || !s_queues[qid].used) return 0;
    return s_queues[qid].count;
}

// ── Event bus ─────────────────────────────────────────────────────────────────
bool subscribe(const char* topic_name, EventHandler handler, void* ctx) {
    // Find or create topic
    for (auto& t : s_topics) {
        if (t.used && str_eq(t.name, topic_name)) {
            if (t.sub_count >= 8) return false;
            t.subs[t.sub_count++] = { handler, ctx };
            return true;
        }
    }
    for (auto& t : s_topics) {
        if (!t.used) {
            t = {};
            t.used = true;
            str_copy(t.name, topic_name, 32);
            t.subs[t.sub_count++] = { handler, ctx };
            return true;
        }
    }
    return false;
}

void unsubscribe(const char* topic_name, EventHandler handler) {
    for (auto& t : s_topics) {
        if (!t.used || !str_eq(t.name, topic_name)) continue;
        for (size_t i = 0; i < t.sub_count; ++i) {
            if (t.subs[i].handler == handler) {
                t.subs[i] = t.subs[--t.sub_count];
            }
        }
        return;
    }
}

void publish(const char* topic_name, int32_t mtype, const void* data, size_t dlen) {
    Message msg = {};
    msg.mtype    = mtype;
    msg.data_len = dlen < MSG_MAX_DATA ? dlen : MSG_MAX_DATA;
    mem_copy(msg.data, data, msg.data_len);

    for (auto& t : s_topics) {
        if (!t.used || !str_eq(t.name, topic_name)) continue;
        for (size_t i = 0; i < t.sub_count; ++i) {
            if (t.subs[i].handler) {
                t.subs[i].handler(topic_name, &msg, t.subs[i].ctx);
            }
        }
        return;
    }
}

// ── Notification ──────────────────────────────────────────────────────────────
NotifId notif_create() {
    for (int i = 0; i < (int)MAX_NOTIFS; ++i) {
        if (!s_notifs[i].used) {
            s_notifs[i] = { true, false };
            return i;
        }
    }
    return -1;
}
void notif_signal(NotifId id) {
    if (id >= 0 && id < (int)MAX_NOTIFS && s_notifs[id].used)
        s_notifs[id].signalled = true;
}
void notif_wait(NotifId id) {
    if (id < 0 || id >= (int)MAX_NOTIFS) return;
    while (!s_notifs[id].signalled) asm volatile("hlt");
    s_notifs[id].signalled = false;
}
bool notif_poll(NotifId id) {
    if (id < 0 || id >= (int)MAX_NOTIFS) return false;
    if (s_notifs[id].signalled) { s_notifs[id].signalled = false; return true; }
    return false;
}
void notif_destroy(NotifId id) {
    if (id >= 0 && id < (int)MAX_NOTIFS) s_notifs[id] = {};
}

// ── Syslog ────────────────────────────────────────────────────────────────────
void syslog(const char* message) {
    if (s_syslog_qid < 0) return;
    Message msg = {};
    msg.mtype = MTYPE_SYSLOG;
    size_t n = 0;
    while (message[n] && n < MSG_MAX_DATA - 1) { msg.data[n] = (uint8_t)message[n]; ++n; }
    msg.data_len = n;
    msgsnd(s_syslog_qid, &msg);
}

void syslogf(const char* /*fmt*/, ...) {
    // Minimal impl: just pass the format string directly
    syslog("(syslogf: formatted logging not yet impl)");
}

void dump() {
    VGA::writeln("MSG Queues:");
    for (int i = 0; i < (int)MAX_QUEUES; ++i) {
        if (!s_queues[i].used) continue;
        VGA::write("  ["); VGA::write_dec((uint32_t)i); VGA::write("] ");
        VGA::write(s_queues[i].name);
        VGA::write("  pending="); VGA::write_dec((uint32_t)s_queues[i].count);
        VGA::newline();
    }
}

} // namespace MSG
