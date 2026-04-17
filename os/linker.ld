/* os/linker.ld — Linker script for NiblitOS
 *
 * Loads the kernel at 1 MiB (0x100000) — the standard address for a
 * protected-mode kernel loaded by GRUB/Multiboot2.
 *
 * Sections:
 *   .multiboot2  — Multiboot2 header (must be within first 8 KiB of file)
 *   .text        — kernel code
 *   .rodata      — read-only data
 *   .data        — initialised data
 *   .bss         — uninitialised data (zero-filled by bootloader)
 */

ENTRY(_start)

SECTIONS {
    . = 1M;                     /* load address: 1 MiB */

    /* Multiboot2 header — must come first in the binary */
    .multiboot2 ALIGN(8) : {
        KEEP(*(.multiboot2))
    }

    /* Executable code */
    .text ALIGN(4K) : {
        *(.text*)
    }

    /* Read-only data (string literals, vtables, …) */
    .rodata ALIGN(4K) : {
        *(.rodata*)
    }

    /* Initialised data */
    .data ALIGN(4K) : {
        *(.data*)
    }

    /* BSS — zero-filled, not stored in the file */
    .bss ALIGN(4K) : {
        *(COMMON)
        *(.bss*)
        . = ALIGN(16);
    }

    /* Export a symbol at the very end of the kernel image so Memory::init()
     * can skip frames occupied by the kernel itself. */
    _kernel_end = .;
}
