// os/kernel/procfs.h — ProcFS pseudo-filesystem
//
// Mounts a set of read-only virtual files under /proc that expose live kernel
// and Niblit AI tool statistics.  Files are (re)generated at init time and
// refreshed on demand so the content always reflects current state.
//
// Files exposed:
//   /proc/version    — NiblitOS version + build info
//   /proc/meminfo    — Physical memory and heap statistics
//   /proc/uptime     — Milliseconds since boot
//   /proc/cpuinfo    — CPU count + APIC IDs from ACPI
//   /proc/niblit     — Niblit AI daemon status
//   /proc/devices    — Registered character and block devices
//   /proc/syscalls   — Niblit-specific syscall reference
#pragma once

namespace ProcFS {

// Mount /proc directory and populate all virtual files with initial content.
// Must be called after VFS::init(), Memory::init(), and PIT::init().
void init();

// Regenerate all time-varying /proc files (meminfo, uptime, niblit).
// Intended to be called periodically from the niblit-daemon task loop.
void refresh();

} // namespace ProcFS
