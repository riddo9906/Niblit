; os/kernel/gdt.asm — GDT flush (must be in ASM to reload CS via far jump)
;
; void gdt_flush(uint32_t gdtr_ptr)
bits 32
section .text
global gdt_flush

gdt_flush:
    mov eax, [esp+4]    ; gdtr pointer passed by C++
    lgdt [eax]

    ; Reload data segment registers with kernel data selector (0x10)
    mov ax, 0x10
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax
    mov ss, ax

    ; Far jump to reload CS with kernel code selector (0x08)
    jmp 0x08:.flush
.flush:
    ret
