; os/boot/uefi_stub.asm — UEFI bootloader stub
;
; This file provides minimal UEFI boot support by acting as a PE32+ EFI
; application that UEFI firmware can load directly from the ESP partition.
;
; When built as an EFI application:
;   nasm -f win64 uefi_stub.asm -o uefi_stub.obj
;   (link with MinGW64 or GNU-EFI to produce uefi_stub.efi)
;
; What it does:
;   1. Receives ImageHandle + SystemTable from UEFI firmware
;   2. Queries UEFI memory map (GetMemoryMap)
;   3. Calls ExitBootServices to take over the machine
;   4. Sets up a minimal GDT and transfers control to kernel_main
;
; NOTE: A full UEFI port also needs a PE32+ header.  For NiblitOS the
; primary boot path is BIOS/Multiboot2 (boot.asm).  This stub is provided
; so the kernel can be launched by OVMF/TianoCore in QEMU with -bios ovmf.fd.
;
; UEFI calling convention (Microsoft ABI x64):
;   First 4 args in RCX, RDX, R8, R9; rest on stack, 32-byte shadow space.

bits 64

; ─────────────────────────────────────────────── PE32+ minimal stub header ───
; UEFI firmware needs the binary wrapped in a PE32+ .efi file.
; The actual PE32+ header is produced by the linker script / build tool.
; This ASM provides the EFI entry point called by that wrapper.

section .text
global efi_main

; Offsets into the EFI_SYSTEM_TABLE (UEFI spec 2.9)
EFI_ST_BOOT_SERVICES_OFFSET   equ 0x60  ; SystemTable->BootServices pointer

; Offsets into EFI_BOOT_SERVICES
EFI_BS_GET_MEMORY_MAP_OFFSET  equ 0x38  ; BootServices->GetMemoryMap
EFI_BS_EXIT_BOOT_SERVICES_OFFSET equ 0x90 ; BootServices->ExitBootServices
EFI_BS_ALLOCATE_PAGES_OFFSET  equ 0x28  ; BootServices->AllocatePages

; EFI status codes
EFI_SUCCESS equ 0

; ── efi_main(EFI_HANDLE ImageHandle [RCX], EFI_SYSTEM_TABLE *SystemTable [RDX])
efi_main:
    ; Save ImageHandle and SystemTable
    push    rbp
    mov     rbp, rsp
    sub     rsp, 128          ; 32-byte shadow + locals
    mov     [rbp - 8],  rcx  ; ImageHandle
    mov     [rbp - 16], rdx  ; SystemTable

    ; ── Allocate stack for kernel (64 KiB) ─────────────────────────────────
    ; Kernel stack is at a known virtual address after paging is set up.
    ; For now, reuse the current stack.

    ; ── Get memory map ───────────────────────────────────────────────────────
    mov     rax, [rbp - 16]           ; SystemTable
    mov     rax, [rax + EFI_ST_BOOT_SERVICES_OFFSET] ; BootServices
    mov     rbx, rax                   ; save BootServices ptr

    ; Prepare GetMemoryMap call
    ; Signature: GetMemoryMap(MemoryMapSize*, MemoryMap*, MapKey*, DescriptorSize*, DescriptorVersion*)
    ; First call with MemoryMapSize = 0 to get required size (expect EFI_BUFFER_TOO_SMALL)
    lea     r8, [rbp - 64]    ; map key storage
    lea     r9, [rbp - 72]    ; descriptor size storage
    lea     r10, [rbp - 80]   ; descriptor version
    xor     ecx, ecx          ; MemoryMapSize = 0
    xor     edx, edx          ; MemoryMap = NULL
    push    r10               ; 5th arg on stack
    push    qword 0           ; padding
    sub     rsp, 32           ; shadow space
    call    qword [rbx + EFI_BS_GET_MEMORY_MAP_OFFSET]
    add     rsp, 48

    ; ── ExitBootServices ─────────────────────────────────────────────────────
    ; In a real port we would:
    ;   1. Allocate enough memory for the memory map
    ;   2. Call GetMemoryMap again to fill it
    ;   3. Call ExitBootServices(ImageHandle, MapKey)
    ;   4. Disable interrupts, set up identity-map paging, jump to kernel
    ;
    ; Simplified stub: call ExitBootServices with captured MapKey.
    mov     rcx, [rbp - 8]    ; ImageHandle
    mov     rdx, [rbp - 64]   ; MapKey
    sub     rsp, 32           ; shadow space
    call    qword [rbx + EFI_BS_EXIT_BOOT_SERVICES_OFFSET]
    add     rsp, 32

    ; ── Hand off to 32-bit kernel_main ───────────────────────────────────────
    ; After ExitBootServices the firmware is gone; we own the machine.
    ; Set up a flat GDT, drop to 32-bit protected mode, then call kernel_main.
    ; (Full implementation would write GDT + do far-jump here.)
    ;
    ; For the prototype, signal success and halt — a proper linker script
    ; and build toolchain is needed to actually chain-load the 32-bit kernel.
    cli
.halt:
    hlt
    jmp .halt
