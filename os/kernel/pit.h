// os/kernel/pit.h — Programmable Interval Timer (8253/8254) driver
//
// Programs the PIT channel 0 to fire IRQ0 at a configurable frequency
// (default 100 Hz → 10 ms tick).  Provides a monotonic tick counter
// for scheduling, timeouts, and sleep.
#pragma once
#include <stdint.h>

namespace PIT {

static constexpr uint32_t BASE_FREQUENCY  = 1193182; // Hz (PIT input clock)
static constexpr uint32_t TICK_FREQUENCY  = 100;     // target IRQ0 rate (Hz)
static constexpr uint32_t MS_PER_TICK     = 1000 / TICK_FREQUENCY; // 10 ms

// Initialise the PIT and set the tick frequency.
void init(uint32_t hz = TICK_FREQUENCY);

// Return total ticks since init().
uint64_t ticks();

// Return milliseconds elapsed since init().
uint64_t millis();

// Busy-wait for at least *ms* milliseconds.
void sleep_ms(uint32_t ms);

// Called by IRQ0 handler — increments the tick counter and invokes
// the Process scheduler tick.
void on_tick();

} // namespace PIT
