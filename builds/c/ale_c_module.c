/*
 * ale_c_memory_safety_and_ownership — memory safety and ownership: 
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ─── prototypes ─────────────────────────────── */
void run(void);

/* ─── entry point ────────────────────────────── */
int main(int argc, char *argv[]) {
    (void)argc;
    (void)argv;
    run();
    return EXIT_SUCCESS;
}

void run(void) {
    printf("ale_c_memory_safety_and_ownership: memory safety and ownership: \n");
}
