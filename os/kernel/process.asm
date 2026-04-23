; os/kernel/process.asm — Context-switch helper
;
; void switch_context(Context* old_ctx, Context* new_ctx)
;
; Saves callee-saved registers into *old_ctx* then restores them from
; *new_ctx* and returns (which jumps to the saved EIP of the new task).

bits 32
section .text
global switch_context

switch_context:
    ; [esp+4] = old_ctx pointer
    ; [esp+8] = new_ctx pointer

    mov eax, [esp+4]    ; eax → old_ctx

    ; Save callee-saved registers + EIP (return address already on stack)
    mov [eax+0],  edi
    mov [eax+4],  esi
    mov [eax+8],  ebx
    mov [eax+12], ebp
    ; Save return address as the resumption point
    mov ecx, [esp]      ; return address is at [esp] right now
    mov [eax+16], ecx

    mov eax, [esp+8]    ; eax → new_ctx

    ; Restore callee-saved registers
    mov edi, [eax+0]
    mov esi, [eax+4]
    mov ebx, [eax+8]
    mov ebp, [eax+12]
    ; Replace return address on stack so ret jumps into the new task
    mov ecx, [eax+16]
    mov [esp], ecx

    ret
