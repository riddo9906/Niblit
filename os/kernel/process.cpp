// os/kernel/process.cpp — Round-robin task scheduler
#include "process.h"
#include "vga.h"
#include "idt.h"
#include <stddef.h>

namespace Process {

// ── storage ───────────────────────────────────────────────────────────────────
static Task    s_tasks[MAX_TASKS];
static uint32_t s_current_id  = 0;
static uint32_t s_next_id     = 1;   // 0 = idle
static uint32_t s_task_count  = 0;

// ── context-switch (ASM helper) ───────────────────────────────────────────────
// switch_context(Context* old_ctx, Context* new_ctx)
extern "C" void switch_context(Context* old_ctx, Context* new_ctx);

// ── helpers ───────────────────────────────────────────────────────────────────
static Task* find_task(uint32_t id) {
    for (size_t i = 0; i < MAX_TASKS; ++i) {
        if (s_tasks[i].id == id && s_tasks[i].state != State::EMPTY) {
            return &s_tasks[i];
        }
    }
    return nullptr;
}

static Task* find_slot() {
    for (size_t i = 0; i < MAX_TASKS; ++i) {
        if (s_tasks[i].state == State::EMPTY) {
            return &s_tasks[i];
        }
    }
    return nullptr;
}

// Idle task — just halts until the next interrupt.
static void idle_task() {
    while (true) {
        asm volatile("hlt");
    }
}

// ── PIT / timer IRQ handler ───────────────────────────────────────────────────
static void timer_irq_handler(IDT::Registers* /*regs*/) {
    tick();
}

// ── public ────────────────────────────────────────────────────────────────────
void init() {
    // Register timer IRQ (IRQ0 = INT 32)
    IDT::register_handler(32, timer_irq_handler);

    // Create idle task (id = 0)
    Task* idle = &s_tasks[0];
    idle->id    = 0;
    idle->state = State::READY;
    idle->ticks = 0;

    static const char idle_name[] = "idle";
    for (size_t i = 0; i < sizeof(idle_name); ++i) idle->name[i] = idle_name[i];

    // Set up idle task stack — it will be entered via switch_context
    uint32_t* stack_top = reinterpret_cast<uint32_t*>(
        idle->stack + STACK_SIZE - sizeof(uint32_t));
    *stack_top = reinterpret_cast<uint32_t>(idle_task);
    idle->ctx.eip = reinterpret_cast<uint32_t>(idle_task);
    idle->ctx.ebp = reinterpret_cast<uint32_t>(stack_top);

    s_current_id = 0;
    s_task_count = 1;
    VGA::writeln("[PROC] Scheduler initialised — idle task ready.");
}

uint32_t create(const char* name, TaskFunc fn) {
    Task* t = find_slot();
    if (!t) {
        VGA::writeln("[PROC] ERROR: no free task slots.");
        return 0;
    }

    t->id    = s_next_id++;
    t->state = State::READY;
    t->ticks = 0;

    // Copy name
    size_t ni = 0;
    while (name && name[ni] && ni < 31) { t->name[ni] = name[ni]; ++ni; }
    t->name[ni] = '\0';

    // Set up stack so that switch_context lands in fn()
    uint32_t* stack_top = reinterpret_cast<uint32_t*>(
        t->stack + STACK_SIZE - sizeof(uint32_t));
    *stack_top = reinterpret_cast<uint32_t>(fn);
    t->ctx.eip = reinterpret_cast<uint32_t>(fn);
    t->ctx.ebp = reinterpret_cast<uint32_t>(stack_top);

    ++s_task_count;
    VGA::write("[PROC] Created task '");
    VGA::write(t->name);
    VGA::write("' id=");
    VGA::write_dec(t->id);
    VGA::newline();
    return t->id;
}

void yield() {
    tick();
}

void tick() {
    Task* cur = find_task(s_current_id);
    if (cur) {
        ++cur->ticks;
        if (cur->state == State::RUNNING) cur->state = State::READY;
    }

    // Find next READY task (round-robin)
    Task* next = nullptr;
    uint32_t start = s_current_id;
    for (size_t i = 0; i < MAX_TASKS; ++i) {
        size_t idx = (s_current_id + i + 1) % MAX_TASKS;
        if (s_tasks[idx].state == State::READY) {
            next = &s_tasks[idx];
            break;
        }
    }

    if (!next || next == cur) return;   // nothing to switch to

    Task* old = cur ? cur : &s_tasks[0];
    old->state  = State::READY;
    next->state = State::RUNNING;
    s_current_id = next->id;

    switch_context(&old->ctx, &next->ctx);
}

Task* current() {
    return find_task(s_current_id);
}

void dump() {
    VGA::writeln("--- Task List ---");
    static const char* state_names[] = { "EMPTY","READY","RUNNING","BLOCKED","ZOMBIE" };
    for (size_t i = 0; i < MAX_TASKS; ++i) {
        if (s_tasks[i].state == State::EMPTY) continue;
        VGA::write("  [");
        VGA::write_dec(s_tasks[i].id);
        VGA::write("] ");
        VGA::write(s_tasks[i].name);
        VGA::write(" - ");
        VGA::write(state_names[static_cast<int>(s_tasks[i].state)]);
        VGA::write(" ticks=");
        VGA::write_dec(s_tasks[i].ticks);
        VGA::newline();
    }
}

} // namespace Process
