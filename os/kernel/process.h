// os/kernel/process.h — Task/process management
//
// Provides a basic preemptive round-robin scheduler backed by the PIT
// timer IRQ (IRQ 0).  Each Task holds its own kernel stack and register
// context so the scheduler can context-switch between tasks.
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace Process {

static constexpr size_t STACK_SIZE   = 8192;   // 8 KiB per task kernel stack
static constexpr size_t MAX_TASKS    = 64;

// Task states
enum class State : uint8_t {
    EMPTY   = 0,
    READY   = 1,
    RUNNING = 2,
    BLOCKED = 3,
    ZOMBIE  = 4,
};

// Saved register context for context switching (cdecl / x86-32).
struct Context {
    uint32_t edi, esi, ebx, ebp;
    uint32_t eip;               // return address / next instruction
} __attribute__((packed));

using TaskFunc = void(*)();

struct Task {
    uint32_t  id;
    State     state;
    char      name[32];
    Context   ctx;
    uint8_t   stack[STACK_SIZE];
    uint32_t  ticks;            // total timer ticks consumed
};

// Initialise the scheduler and create the idle task.
void init();

// Create a new task.  Returns task ID, or 0 on failure.
uint32_t create(const char* name, TaskFunc fn);

// Yield the current task voluntarily (called from userland or kernel tasks).
void yield();

// Scheduler tick — called from the PIT IRQ handler.
void tick();

// Return a pointer to the currently running task.
Task* current();

// Print a summary of all tasks to VGA.
void dump();

} // namespace Process
