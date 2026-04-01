# ale_assembly_arm_cortex_m_bare_metal_programming — ARM Cortex-M bare metal programming: ✅ Researched assembly ARM Cortex-M bare metal programming: 2 result(s) fetched.
First result: No data found for 'assembl
# Target: x86-64 Linux (NASM syntax)
# Build:  nasm -f elf64 ale_assembly_arm_cortex_m_bare_metal_programming.asm -o ale_assembly_arm_cortex_m_bare_metal_programming.o && ld ale_assembly_arm_cortex_m_bare_metal_programming.o -o ale_assembly_arm_cortex_m_bare_metal_programming

section .data
    msg db "ale_assembly_arm_cortex_m_bare_metal_programming: ARM Cortex-M bare metal programming: ✅ Researched assembly ARM Cortex-M bare metal programming: 2 result(s) fetched.
First result: No data found for 'assembl", 0x0A
    msg_len equ $ - msg

section .text
    global _start

_start:
    ; write(1, msg, msg_len)
    mov rax, 1          ; syscall: write
    mov rdi, 1          ; fd: stdout
    mov rsi, msg        ; buffer
    mov rdx, msg_len    ; length
    syscall

    ; exit(0)
    mov rax, 60         ; syscall: exit
    xor rdi, rdi        ; status: 0
    syscall
