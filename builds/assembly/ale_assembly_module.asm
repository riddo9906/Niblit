# ale_assembly_x86_64_system_call_interface_1773726105 — x86-64 system call interface 1773726105: Julia is a dynamic general-purpose programming language. As a high-level language, distinctive aspects of Julia's design
# Target: x86-64 Linux (NASM syntax)
# Build:  nasm -f elf64 ale_assembly_x86_64_system_call_interface_1773726105.asm -o ale_assembly_x86_64_system_call_interface_1773726105.o && ld ale_assembly_x86_64_system_call_interface_1773726105.o -o ale_assembly_x86_64_system_call_interface_1773726105

section .data
    msg db "ale_assembly_x86_64_system_call_interface_1773726105: x86-64 system call interface 1773726105: Julia is a dynamic general-purpose programming language. As a high-level language, distinctive aspects of Julia's design", 0x0A
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
