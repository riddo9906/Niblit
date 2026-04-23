; os/boot/boot.asm — Multiboot2-compliant bootloader entry point
;
; This is the first code executed when the BIOS/bootloader hands off control
; to the NiblitOS kernel image.  It:
;   1. Declares the Multiboot2 header so GRUB can load us
;   2. Sets up a minimal stack in BSS
;   3. Transfers control to the C++ kernel_main() function
;
; Build with: nasm -f elf32 boot.asm -o boot.o
; Then link with: ld -m elf_i386 -T linker.ld boot.o kernel.o ... -o niblit.elf

bits 32

; ─────────────────────────────────────────────────────── Multiboot2 header ───
MULTIBOOT2_MAGIC        equ 0xE85250D6
MULTIBOOT_ARCH_I386     equ 0
HEADER_LENGTH           equ multiboot_header_end - multiboot_header
CHECKSUM                equ -(MULTIBOOT2_MAGIC + MULTIBOOT_ARCH_I386 + HEADER_LENGTH)

section .multiboot2
align 8
multiboot_header:
    dd MULTIBOOT2_MAGIC
    dd MULTIBOOT_ARCH_I386
    dd HEADER_LENGTH
    dd CHECKSUM

    ; ── End tag ─────────────────────────────────────────────────────────────
    dw 0        ; type  = end
    dw 0        ; flags = 0
    dd 8        ; size  = 8 bytes
multiboot_header_end:

; ────────────────────────────────────────────────────────── BSS / stack area ─
section .bss
align 16
stack_bottom:
    resb 65536          ; 64 KiB initial kernel stack
stack_top:

; ────────────────────────────────────────────────────────── .text entry point ─
section .text
global _start
extern kernel_main

_start:
    ; Set up the kernel stack
    mov esp, stack_top

    ; Push Multiboot2 info pointer and magic for kernel_main(uint32_t magic, uint32_t* mbi)
    ; C calling convention: first arg at [esp+4], second at [esp+8] after call.
    ; We push in reverse order: info pointer first (second arg), then magic (first arg).
    push ebx            ; Multiboot2 info structure pointer (second arg → [esp+4] → mb2_info_addr)
    push eax            ; Multiboot2 magic value           (first  arg → [esp+4] after push → mb2_magic)

    ; Call into C++ kernel
    call kernel_main

    ; kernel_main should never return; if it does, halt the CPU
.halt:
    cli
    hlt
    jmp .halt
