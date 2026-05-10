# os/Makefile — NiblitOS build system
#
# Prerequisites (install with your distro's package manager):
#   - nasm          (assembler)
#   - i686-elf-gcc  (cross-compiler — see os/README.md for setup)
#   - i686-elf-g++  (C++ cross-compiler)
#   - i686-elf-ld   (cross-linker)
#   - qemu-system-i386  (emulator for testing)
#   - grub-mkrescue + xorriso  (ISO creation)
#
# Quick start:
#   cd os && make iso && make run

# ── Cross-compiler toolchain ───────────────────────────────────────────────────
CROSS   ?= i686-elf
CC      := $(CROSS)-gcc
CXX     := $(CROSS)-g++
LD      := $(CROSS)-ld
AS      := nasm

# ── Flags ─────────────────────────────────────────────────────────────────────
CFLAGS  := -std=c11   -ffreestanding -O2 -Wall -Wextra \
           -fno-stack-protector -mno-red-zone -Ikernel
CXXFLAGS:= -std=c++17 -ffreestanding -O2 -Wall -Wextra \
           -fno-exceptions -fno-rtti -fno-stack-protector \
           -mno-red-zone -Ikernel
ASFLAGS := -f elf32
LDFLAGS := -T linker.ld -nostdlib -z noexecstack

# ── Source files ──────────────────────────────────────────────────────────────
BOOT_ASM  := boot/boot.asm
KERNEL_CPP:= kernel/kernel.cpp        \
             kernel/vga.cpp           \
             kernel/serial.cpp        \
             kernel/gdt.cpp           \
             kernel/idt.cpp           \
             kernel/memory.cpp        \
             kernel/paging.cpp        \
             kernel/heap.cpp          \
             kernel/pit.cpp           \
             kernel/process.cpp       \
             kernel/vfs.cpp           \
             kernel/procfs.cpp        \
             kernel/syscall.cpp       \
             kernel/keyboard.cpp      \
             kernel/elf_loader.cpp    \
             kernel/niblit_iface.cpp  \
             kernel/acpi.cpp          \
             kernel/irq.cpp           \
             kernel/pci.cpp           \
             kernel/rtc.cpp           \
             kernel/dma.cpp           \
             kernel/ata.cpp           \
             kernel/net.cpp           \
             kernel/msg.cpp
KERNEL_ASM:= kernel/gdt.asm      \
             kernel/idt.asm      \
             kernel/process.asm

# ── Object files ──────────────────────────────────────────────────────────────
OBJS := $(BOOT_ASM:.asm=.boot.o)                       \
        $(KERNEL_CPP:kernel/%.cpp=build/%.o)            \
        $(KERNEL_ASM:kernel/%.asm=build/%.asm.o)

KERNEL_ELF := build/niblit.elf
KERNEL_ISO := niblit-os.iso

# ── Phony targets ─────────────────────────────────────────────────────────────
.PHONY: all iso run run-uefi run-elf shell shell-run runner runner-run clean help

all: $(KERNEL_ELF)

# ── Compile C++ kernel sources ────────────────────────────────────────────────
build/%.o: kernel/%.cpp | build
	$(CXX) $(CXXFLAGS) -c $< -o $@

# ── Assemble kernel ASM sources ───────────────────────────────────────────────
build/%.asm.o: kernel/%.asm | build
	$(AS) $(ASFLAGS) $< -o $@

# ── Assemble boot stub ────────────────────────────────────────────────────────
boot/boot.boot.o: boot/boot.asm
	$(AS) $(ASFLAGS) $< -o $@

# ── Link kernel ELF ───────────────────────────────────────────────────────────
$(KERNEL_ELF): $(OBJS) linker.ld | build
	$(LD) $(LDFLAGS) $(OBJS) -o $@
	@echo "Kernel ELF: $@"
	@$(CROSS)-size $@

# ── Create bootable ISO (requires grub-mkrescue + xorriso) ───────────────────
iso: $(KERNEL_ELF)
	mkdir -p iso/boot/grub
	cp $(KERNEL_ELF) iso/boot/niblit.elf
	@printf 'set timeout=0\nset default=0\n\nmenuentry "NiblitOS" {\n    multiboot2 /boot/niblit.elf\n    boot\n}\n' > iso/boot/grub/grub.cfg
	grub-mkrescue -o $(KERNEL_ISO) iso
	@echo "ISO created: $(KERNEL_ISO)"

# ── Run in QEMU ───────────────────────────────────────────────────────────────
run: iso
	qemu-system-i386 -cdrom $(KERNEL_ISO) -m 128M -serial stdio

# Run in QEMU with OVMF UEFI firmware (requires ovmf package)
run-uefi: iso
	qemu-system-x86_64 -bios /usr/share/ovmf/OVMF.fd \
	    -cdrom $(KERNEL_ISO) -m 128M -serial stdio || \
	qemu-system-x86_64 -bios /usr/share/qemu/OVMF.fd \
	    -cdrom $(KERNEL_ISO) -m 128M -serial stdio

# Run directly from ELF (no ISO needed) — serial output on stdout
run-elf: $(KERNEL_ELF)
	qemu-system-i386 -kernel $(KERNEL_ELF) -m 128M -serial stdio

# ── Userland shell (Linux test build) ────────────────────────────────────────
SHELL_BIN := build/niblit-shell
RUNNER_BIN := build/niblit-runner

shell: $(SHELL_BIN)

$(SHELL_BIN): userland/shell/shell.c | build
	gcc -std=c11 -O2 -Wall -DLINUX_TEST userland/shell/shell.c -o $@
	@echo "Shell binary: $@"

shell-run: $(SHELL_BIN)
	./$(SHELL_BIN)

# ── Niblit userspace tool runner (Linux host) ─────────────────────────────────
runner: $(RUNNER_BIN)

$(RUNNER_BIN): userland/niblit_tool/niblit_runner.c | build
	gcc -std=c11 -O2 -Wall userland/niblit_tool/niblit_runner.c -o $@
	@echo "Niblit runner binary: $@"

runner-run: $(RUNNER_BIN)
	NIBLIT_ENTRY_PATH=$(PWD)/userland/niblit_tool/niblit_entry.py \
	NIBLIT_SOCKET_PATH=/tmp/niblit.sock \
	./$(RUNNER_BIN)


build:
	mkdir -p build

# ── Clean ─────────────────────────────────────────────────────────────────────
clean:
	rm -rf build boot/*.boot.o iso $(KERNEL_ISO)

# ── Help ──────────────────────────────────────────────────────────────────────
help:
	@echo "NiblitOS Makefile targets:"
	@echo "  all       — build kernel ELF (requires i686-elf cross-compiler)"
	@echo "  iso       — wrap ELF in a GRUB2 bootable ISO"
	@echo "  run       — boot ISO in QEMU"
	@echo "  run-elf   — boot ELF directly in QEMU (no ISO)"
	@echo "  runner    — build userspace niblit runner binary"
	@echo "  runner-run— run userspace niblit runner (host Linux bridge mode)"
	@echo "  clean     — remove build artefacts"
	@echo ""
	@echo "Cross-compiler setup: see os/README.md"
