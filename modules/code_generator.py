#!/usr/bin/env python3
"""
CODE GENERATOR MODULE
Generate source code in multiple languages, study language patterns,
learn from templates, and improve code quality over time.

Features:
- Multi-language code generation (Python, JavaScript, Bash, etc.)
- Template library for common patterns with proper indentation/structure
- Structural validation and auto-correction for all generated code
- Study programming language idioms
- Store generated code in KnowledgeDB for future reference
"""

import os
import re
import textwrap
import time
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("CodeGenerator")

# ──────────────────────────────────────────────────────────
# NIBLIT BUILD PATH
# ──────────────────────────────────────────────────────────
# The live Niblit installation directory inside Termux.  Autonomously
# generated .py files are saved here so they can be hot-reloaded and
# pushed to GitHub via GitHubSync.
try:
    from modules.evolve import TERMUX_DEPLOY_PATH as NIBLIT_BUILD_PATH
except Exception:
    NIBLIT_BUILD_PATH = Path(
        "/data/data/com.termux/files/home/NiblitAIOS/Niblit-Modules/Niblit-apk/Niblit"
    )

# Local builds directory — structured storage for all generated programs,
# available in every environment (not just Termux).
# Layout: builds/{language}/{name}.{ext}
_MODULE_DIR = Path(__file__).resolve().parent   # modules/
_REPO_DIR = _MODULE_DIR.parent                  # repository root
NIBLIT_LOCAL_BUILDS_PATH = _REPO_DIR / "builds"

# ──────────────────────────────────────────────────────────
# LANGUAGE TEMPLATES
# ──────────────────────────────────────────────────────────

_TEMPLATES: Dict[str, Dict[str, str]] = {
    "python": {
        "class": '''class {name}:
    """{docstring}"""

    def __init__(self):
        pass

    def run(self):
        """Run the main logic."""
        pass
''',
        "function": '''def {name}({args}):
    """{docstring}"""
    {body}
''',
        "script": '''#!/usr/bin/env python3
"""{docstring}"""

import sys
import logging

log = logging.getLogger(__name__)


def main():
    """Entry point."""
    pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
''',
        "module": '''#!/usr/bin/env python3
"""{name} module — {docstring}"""

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("{name}")


class {classname}:
    """{classname} implementation."""

    def __init__(self, db: Any = None):
        self.db = db
        log.debug("[{name}] Initialized")

    def run(self) -> Dict[str, Any]:
        """Run the main logic."""
        return {{"status": "ok"}}


if __name__ == "__main__":
    import logging as _logging  # pylint: disable=reimported,ungrouped-imports
    _logging.basicConfig(level=_logging.INFO)
    obj = {classname}()
    print(obj.run())
''',
    },
    "bash": {
        "script": '''#!/usr/bin/env bash
# {name} — {docstring}
set -euo pipefail

# ──────────────────────────────────────
# Config
# ──────────────────────────────────────
LOG_FILE="/tmp/{name}.log"

log() {{
    echo "[$(date +'%H:%M:%S')] $*" | tee -a "$LOG_FILE"
}}

main() {{
    log "Starting {name}..."
    {body}
    log "Done."
}}

main "$@"
''',
        "function": '''# {name}: {docstring}
{name}() {{
    local arg="${{1:-}}"
    {body}
}}
''',
    },
    "javascript": {
        "module": '''/**
 * {name} — {docstring}
 */

'use strict';

class {classname} {{
    constructor() {{
        this.name = '{name}';
    }}

    run() {{
        return {{ status: 'ok' }};
    }}
}}

module.exports = {{ {classname} }};
''',
        "function": '''/**
 * {name} — {docstring}
 * @param {{*}} args
 * @returns {{*}}
 */
function {name}({args}) {{
    {body}
}}

module.exports = {{ {name} }};
''',
    },
    "html": {
        "page": '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
</head>
<body>
    <h1>{title}</h1>
    <p>{description}</p>
</body>
</html>
''',
    },
    "css": {
        "stylesheet": '''/* {name} — {docstring} */

:root {{
    --primary: #007bff;
    --bg: #ffffff;
    --text: #333333;
}}

body {{
    font-family: sans-serif;
    background: var(--bg);
    color: var(--text);
    margin: 0;
    padding: 1rem;
}}
''',
    },
    "sql": {
        "create_table": '''-- {name}: {docstring}
CREATE TABLE IF NOT EXISTS {table_name} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    {fields}
);
''',
    },
    "json": {
        "config": '''{
    "name": "{name}",
    "version": "1.0.0",
    "description": "{docstring}",
    "settings": {{}}
}}
''',
    },
    # ── Compiled / statically-typed languages ─────────────────────────
    "java": {
        "class": '''package {name};

/**
 * {classname} — {docstring}
 */
public class {classname} {{

    public {classname}() {{
        // constructor
    }}

    public void run() {{
        System.out.println("{name} running");
    }}

    public static void main(String[] args) {{
        {classname} obj = new {classname}();
        obj.run();
    }}
}}
''',
        "interface": '''package {name};

/**
 * {classname} — {docstring}
 */
public interface {classname} {{

    void run();

    default String getName() {{
        return "{name}";
    }}
}}
''',
    },
    "c": {
        "program": '''/*
 * {name} — {docstring}
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ─── prototypes ─────────────────────────────── */
void run(void);

/* ─── entry point ────────────────────────────── */
int main(int argc, char *argv[]) {{
    (void)argc;
    (void)argv;
    run();
    return EXIT_SUCCESS;
}}

void run(void) {{
    printf("{name}: {docstring}\\n");
}}
''',
        "header": '''/*
 * {name}.h — {docstring}
 */
#ifndef {name_upper}_H
#define {name_upper}_H

#ifdef __cplusplus
extern "C" {{
#endif

/* ─── public API ─────────────────────────────── */
void {name}_init(void);
void {name}_run(void);
void {name}_free(void);

#ifdef __cplusplus
}}
#endif

#endif /* {name_upper}_H */
''',
    },
    "cpp": {
        "class": '''/*
 * {name}.cpp — {docstring}
 */
#include <iostream>
#include <string>
#include "{name}.h"

class {classname} {{
public:
    {classname}() = default;
    ~{classname}() = default;

    void run() {{
        std::cout << "{name}: {docstring}" << std::endl;
    }}
}};

int main() {{
    {classname} obj;
    obj.run();
    return 0;
}}
''',
        "header": '''/*
 * {name}.h — {docstring}
 */
#pragma once
#include <string>

class {classname} {{
public:
    {classname}();
    ~{classname}();
    void run();
}};
''',
    },
    "csharp": {
        "class": '''using System;

namespace {name}
{{
    /// <summary>{docstring}</summary>
    public class {classname}
    {{
        public {classname}() {{ }}

        public void Run()
        {{
            Console.WriteLine("{name}: {docstring}");
        }}

        static void Main(string[] args)
        {{
            var obj = new {classname}();
            obj.Run();
        }}
    }}
}}
''',
    },
    "rust": {
        "program": '''//! {name} — {docstring}

use std::error::Error;

fn main() -> Result<(), Box<dyn Error>> {{
    run()?;
    Ok(())
}}

fn run() -> Result<(), Box<dyn Error>> {{
    println!("{name}: {docstring}");
    Ok(())
}}
''',
        "lib": '''//! {name} — {docstring}

/// {classname} implementation.
pub struct {classname} {{
    pub name: String,
}}

impl {classname} {{
    pub fn new() -> Self {{
        Self {{ name: String::from("{name}") }}
    }}

    pub fn run(&self) {{
        println!("{{}}: {docstring}", self.name);
    }}
}}

impl Default for {classname} {{
    fn default() -> Self {{
        Self::new()
    }}
}}

#[cfg(test)]
mod tests {{
    use super::*;

    #[test]
    fn test_run() {{
        let obj = {classname}::new();
        obj.run();
    }}
}}
''',
    },
    "go": {
        "program": '''// {name} — {docstring}
package main

import (
    "fmt"
    "log"
    "os"
)

func main() {{
    if err := run(); err != nil {{
        log.Printf("ERROR: %v", err)
        os.Exit(1)
    }}
}}

func run() error {{
    fmt.Println("{name}: {docstring}")
    return nil
}}
''',
        "package": '''// Package {name} — {docstring}
package {name}

import "fmt"

// {classname} is the main struct.
type {classname} struct {{
    Name string
}}

// New{classname} creates a new instance.
func New{classname}() *{classname} {{
    return &{classname}{{Name: "{name}"}}
}}

// Run executes the main logic.
func (c *{classname}) Run() {{
    fmt.Printf("%s: {docstring}\\n", c.Name)
}}
''',
    },
    "kotlin": {
        "class": '''package {name}

/**
 * {classname} — {docstring}
 */
class {classname} {{
    val name: String = "{name}"

    fun run() {{
        println("$name: {docstring}")
    }}
}}

fun main() {{
    val obj = {classname}()
    obj.run()
}}
''',
        "data_class": '''package {name}

/**
 * {classname} — {docstring}
 */
data class {classname}(
    val id: Int,
    val name: String = "{name}",
    val value: String = "",
)
''',
    },
    "typescript": {
        "module": '''/**
 * {name} — {docstring}
 */

'use strict';

export interface I{classname} {{
    name: string;
    run(): void;
}}

export class {classname} implements I{classname} {{
    readonly name: string;

    constructor(name: string = '{name}') {{
        this.name = name;
    }}

    run(): void {{
        console.log(`${{this.name}}: {docstring}`);
    }}
}}
''',
    },
    "swift": {
        "class": '''// {name} — {docstring}
import Foundation

class {classname} {{
    let name: String

    init(name: String = "{name}") {{
        self.name = name
    }}

    func run() {{
        print("\\(name): {docstring}")
    }}
}}

let obj = {classname}()
obj.run()
''',
    },
    "ruby": {
        "class": '''# frozen_string_literal: true
# {name} — {docstring}

# {classname} implementation
class {classname}
  attr_reader :name

  def initialize(name = '{name}')
    @name = name
  end

  def run
    puts "#{{@name}}: {docstring}"
  end
end

{classname}.new.run if __FILE__ == $PROGRAM_NAME
''',
    },
    "php": {
        "class": '''<?php
/**
 * {name} — {docstring}
 */
declare(strict_types=1);

class {classname}
{{
    private string $name;

    public function __construct(string $name = '{name}')
    {{
        $this->name = $name;
    }}

    public function run(): void
    {{
        echo "$this->name: {docstring}\\n";
    }}
}}

$obj = new {classname}();
$obj->run();
''',
    },
    # ── Low-level / systems languages ─────────────────────────────────
    "assembly": {
        "x86_64": '''# {name} — {docstring}
# Target: x86-64 Linux (NASM syntax)
# Build:  nasm -f elf64 {name}.asm -o {name}.o && ld {name}.o -o {name}

section .data
    msg db "{name}: {docstring}", 0x0A
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
''',
        "arm": '''@ {name} — {docstring}
@ Target: ARM Linux (GNU assembler)
@ Build:  as -o {name}.o {name}.s && ld {name}.o -o {name}

    .section .data
msg:
    .asciz "{name}: {docstring}\\n"
msg_end:

    .section .text
    .global _start
_start:
    @ write(1, msg, len)
    mov r0, #1
    ldr r1, =msg
    ldr r2, =(msg_end - msg)
    mov r7, #4
    svc #0

    @ exit(0)
    mov r0, #0
    mov r7, #1
    svc #0
''',
    },
    # ── Build systems ─────────────────────────────────────────────────
    "makefile": {
        "c_project": '''# {name} — {docstring}
# Usage: make [all|clean|install]

CC      := gcc
CFLAGS  := -Wall -Wextra -pedantic -O2 -std=c11
TARGET  := {name}
SRCS    := $(wildcard src/*.c)
OBJS    := $(SRCS:.c=.o)
PREFIX  := /usr/local

.PHONY: all clean install

all: $(TARGET)

$(TARGET): $(OBJS)
\t$(CC) $(CFLAGS) -o $@ $^

%.o: %.c
\t$(CC) $(CFLAGS) -c -o $@ $<

clean:
\trm -f $(OBJS) $(TARGET)

install: $(TARGET)
\tinstall -m 755 $(TARGET) $(PREFIX)/bin/
''',
    },
    "cmake": {
        "project": '''# {name} — {docstring}
cmake_minimum_required(VERSION 3.16)
project({name} VERSION 1.0.0 LANGUAGES C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Sources
file(GLOB_RECURSE SOURCES "src/*.c" "src/*.cpp")
add_executable({name} ${{SOURCES}})

# Include dirs
target_include_directories({name} PRIVATE include)

# Install
install(TARGETS {name} DESTINATION bin)
''',
    },
    # ── Networking ────────────────────────────────────────────────────
    "networking": {
        "tcp_server_python": '''#!/usr/bin/env python3
"""{name} — {docstring} (TCP Server)"""
import socket
import threading
import logging

log = logging.getLogger("{name}")
HOST = "0.0.0.0"
PORT = 9000


def handle_client(conn: socket.socket, addr: tuple) -> None:
    """Handle a single client connection."""
    with conn:
        log.info("Connected: %s", addr)
        while True:
            data = conn.recv(4096)
            if not data:
                break
            conn.sendall(data)  # echo
        log.info("Disconnected: %s", addr)


def main() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((HOST, PORT))
        srv.listen(10)
        log.info("Listening on %s:%d", HOST, PORT)
        while True:
            conn, addr = srv.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
''',
        "tcp_client_python": '''#!/usr/bin/env python3
"""{name} — {docstring} (TCP Client)"""
import socket
import logging

log = logging.getLogger("{name}")
HOST = "127.0.0.1"
PORT = 9000


def main() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((HOST, PORT))
        log.info("Connected to %s:%d", HOST, PORT)
        s.sendall(b"Hello, {name}")
        data = s.recv(4096)
        log.info("Received: %s", data.decode())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
''',
        "bash_network": '''#!/usr/bin/env bash
# {name} — {docstring}
set -euo pipefail

HOST="${{1:-127.0.0.1}}"
PORT="${{2:-9000}}"

check_port() {{
    nc -zv "$HOST" "$PORT" 2>&1 && echo "Port $PORT is open" || echo "Port $PORT is closed"
}}

scan_host() {{
    ping -c 3 "$HOST"
}}

show_interfaces() {{
    ip addr show 2>/dev/null || ifconfig 2>/dev/null || echo "No network tools found"
}}

main() {{
    echo "=== Network Utility: {name} ==="
    show_interfaces
    scan_host
    check_port
}}

main
''',
    },
    # ── Operating System / Linux kernel module ─────────────────────────
    "linux_kernel": {
        "module": '''/*
 * {name}.c — {docstring}
 * Linux kernel module (loadable)
 * Build: make -C /lib/modules/$(uname -r)/build M=$(pwd) modules
 */
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>

MODULE_LICENSE("GPL");
MODULE_AUTHOR("Niblit");
MODULE_DESCRIPTION("{docstring}");
MODULE_VERSION("0.1");

static int __init {name}_init(void)
{{
    printk(KERN_INFO "{name}: module loaded\\n");
    return 0;
}}

static void __exit {name}_exit(void)
{{
    printk(KERN_INFO "{name}: module unloaded\\n");
}}

module_init({name}_init);
module_exit({name}_exit);
''',
        "char_device": '''/*
 * {name}_dev.c — {docstring}
 * Linux character device driver skeleton
 */
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/fs.h>
#include <linux/uaccess.h>

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("{docstring}");

#define DEVICE_NAME "{name}"
#define BUF_SIZE    256

static int    major_num;
static char   device_buf[BUF_SIZE];

static int     dev_open(struct inode *, struct file *);
static int     dev_release(struct inode *, struct file *);
static ssize_t dev_read(struct file *, char __user *, size_t, loff_t *);
static ssize_t dev_write(struct file *, const char __user *, size_t, loff_t *);

static const struct file_operations fops = {{
    .open    = dev_open,
    .read    = dev_read,
    .write   = dev_write,
    .release = dev_release,
}};

static int __init {name}_init(void)
{{
    major_num = register_chrdev(0, DEVICE_NAME, &fops);
    if (major_num < 0)
        return major_num;
    printk(KERN_INFO "{name}: registered with major %d\\n", major_num);
    return 0;
}}

static void __exit {name}_exit(void)
{{
    unregister_chrdev(major_num, DEVICE_NAME);
}}

module_init({name}_init);
module_exit({name}_exit);
''',
    },
    # ── Firmware / Embedded / BIOS ─────────────────────────────────────
    "firmware": {
        "embedded_c": '''/*
 * {name}.c — {docstring}
 * Bare-metal / embedded firmware skeleton (C99)
 * Toolchain: arm-none-eabi-gcc (or equivalent)
 */
#include <stdint.h>
#include <stdbool.h>

/* ─── hardware register map ──────────────────── */
#define GPIO_BASE   0x40020000UL
#define GPIO_ODR    (*(volatile uint32_t *)(GPIO_BASE + 0x14))
#define GPIO_IDR    (*(volatile uint32_t *)(GPIO_BASE + 0x10))

/* ─── forward declarations ───────────────────── */
static void {name}_init(void);
static void {name}_loop(void);
static void delay_ms(uint32_t ms);

/* ─── entry point ────────────────────────────── */
int main(void) {{
    {name}_init();
    for (;;) {{
        {name}_loop();
    }}
    return 0;
}}

static void {name}_init(void) {{
    /* TODO: configure clocks, GPIO, peripherals */
}}

static void {name}_loop(void) {{
    /* TODO: main application logic */
    GPIO_ODR ^= 0x01U;   /* toggle bit 0 (LED blink example) */
    delay_ms(500);
}}

static void delay_ms(uint32_t ms) {{
    volatile uint32_t count = ms * 4000U;
    while (count--) {{}}
}}
''',
        "bios_stub": '''/*
 * {name}_bios.c — {docstring}
 * Minimal BIOS / bootloader stub (x86 protected mode)
 * Build: nasm + gcc cross-compiler targeting i386-elf
 */
#include <stdint.h>

/* VGA text-mode buffer */
#define VGA_ADDR   ((volatile uint16_t *)0xB8000)
#define VGA_COLS   80
#define VGA_ATTR   0x0F00  /* white on black */

static void vga_puts(const char *s, int row, int col);
static void bios_halt(void);

void bios_main(void) {{
    vga_puts("{name}: {docstring}", 0, 0);
    bios_halt();
}}

static void vga_puts(const char *s, int row, int col) {{
    volatile uint16_t *buf = VGA_ADDR + row * VGA_COLS + col;
    while (*s) {{
        *buf++ = VGA_ATTR | (uint16_t)(uint8_t)*s++;
    }}
}}

static void bios_halt(void) {{
    for (;;) {{
        __asm__ volatile("hlt");
    }}
}}
''',
    },
    # ── Android ───────────────────────────────────────────────────────
    "android": {
        "activity_java": '''package com.{name}.app;

import android.app.Activity;
import android.os.Bundle;
import android.util.Log;
import android.widget.TextView;

/**
 * {classname} — {docstring}
 */
public class {classname} extends Activity {{

    private static final String TAG = "{classname}";

    @Override
    protected void onCreate(Bundle savedInstanceState) {{
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        Log.i(TAG, "{name} started");
        TextView tv = findViewById(R.id.textView);
        if (tv != null) tv.setText("{docstring}");
    }}

    @Override
    protected void onDestroy() {{
        super.onDestroy();
        Log.i(TAG, "{name} stopped");
    }}
}}
''',
        "activity_kotlin": '''package com.{name}.app

import android.app.Activity
import android.os.Bundle
import android.util.Log
import android.widget.TextView

/**
 * {classname} — {docstring}
 */
class {classname} : Activity() {{

    companion object {{
        private const val TAG = "{classname}"
    }}

    override fun onCreate(savedInstanceState: Bundle?) {{
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        Log.i(TAG, "{name} started")
        findViewById<TextView>(R.id.textView)?.text = "{docstring}"
    }}

    override fun onDestroy() {{
        super.onDestroy()
        Log.i(TAG, "{name} stopped")
    }}
}}
''',
        "manifest": '''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.{name}.app">

    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />

    <application
        android:label="{name}"
        android:allowBackup="true"
        android:theme="@style/Theme.AppCompat.Light">

        <activity
            android:name=".{classname}"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
''',
    },
    # ── Binary / hex utilities ─────────────────────────────────────────
    "binary": {
        "reader": '''#!/usr/bin/env python3
"""{name} — {docstring} (binary file reader/editor)"""
import sys
import struct
import logging
from typing import Optional

log = logging.getLogger("{name}")
ROW_WIDTH = 16


def hexdump(data: bytes, offset: int = 0) -> str:
    """Return a classic hexdump string for *data*."""
    rows = []
    for i in range(0, len(data), ROW_WIDTH):
        chunk = data[i : i + ROW_WIDTH]
        hex_part = " ".join(f"{{b:02x}}" for b in chunk)
        asc_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        rows.append(f"{{offset + i:08x}}  {{hex_part:<48}}  |{{asc_part}}|")
    return "\n".join(rows)


def read_binary(path: str) -> Optional[bytes]:
    """Read a file as raw bytes."""
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as exc:
        log.error("Cannot read %s: %s", path, exc)
        return None


def write_binary(path: str, data: bytes) -> bool:
    """Write raw bytes to a file."""
    try:
        with open(path, "wb") as fh:
            fh.write(data)
        return True
    except OSError as exc:
        log.error("Cannot write %s: %s", path, exc)
        return False


def to_hex_string(data: bytes) -> str:
    """Convert bytes to hex string."""
    return data.hex()


def from_hex_string(hex_str: str) -> bytes:
    """Convert hex string to bytes."""
    return bytes.fromhex(hex_str.replace(" ", "").replace("\\n", ""))


def bytes_to_binary_string(data: bytes) -> str:
    """Convert bytes to binary (0/1) string."""
    return " ".join(f"{{b:08b}}" for b in data)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    path = sys.argv[1] if len(sys.argv) > 1 else __file__
    raw = read_binary(path)
    if raw:
        print(hexdump(raw[:256]))
''',
    },
}

# Supported languages
SUPPORTED_LANGUAGES: List[str] = list(_TEMPLATES.keys())

# Language file extensions
_EXTENSIONS: Dict[str, str] = {
    "python": ".py",
    "bash": ".sh",
    "javascript": ".js",
    "html": ".html",
    "css": ".css",
    "sql": ".sql",
    "json": ".json",
    "text": ".txt",
    "markdown": ".md",
    "yaml": ".yaml",
    "java": ".java",
    "c": ".c",
    "cpp": ".cpp",
    "csharp": ".cs",
    "rust": ".rs",
    "go": ".go",
    "kotlin": ".kt",
    "typescript": ".ts",
    "swift": ".swift",
    "ruby": ".rb",
    "php": ".php",
    "assembly": ".asm",
    "makefile": "Makefile",
    "cmake": "CMakeLists.txt",
    "networking": ".py",
    "linux_kernel": ".c",
    "firmware": ".c",
    "android": ".java",
    "binary": ".py",
}

# Structure-check constants
# Pure Python scripts shorter than this line count don't require a def/class.
_PY_MAX_LINES_WITHOUT_DEF: int = 10
# Number of characters at the start of a JS file to scan for 'use strict'.
_JS_HEADER_CHECK_SIZE: int = 300
# Maximum length of the safe-name portion used in generated module names.
_MAX_MODULE_NAME_LEN: int = 40
# Maximum characters of research text embedded in Python module docstrings.
_MAX_RESEARCH_SUMMARY_LEN: int = 300
# Maximum width (chars) for research comment lines in Rust/Go/JS builders.
_RESEARCH_SUMMARY_WIDTH: int = 120
# Maximum length for Go package names (Go identifiers must be short).
_MAX_GO_PACKAGE_NAME_LEN: int = 20


class CodeGenerator:
    """
    Multi-language code generator with learning capabilities.

    Usage:
        gen = CodeGenerator(db=knowledge_db)
        code = gen.generate("python", "module", name="my_module", docstring="Does X")
        stats = gen.get_stats()
    """

    def __init__(self, db: Any = None, deploy_path: Optional[str] = None):
        self.db = db
        # Where to save autonomously-generated .py files.  Defaults to the
        # Niblit build directory when running on Termux.
        if deploy_path is not None:
            self.deploy_path: Optional[Path] = Path(deploy_path)
        elif NIBLIT_BUILD_PATH.exists():
            self.deploy_path = NIBLIT_BUILD_PATH
        else:
            self.deploy_path = None
        self._stats: Dict[str, int] = {
            "generated": 0,
            "stored": 0,
        }
        log.debug("[CodeGenerator] Initialized (deploy_path=%s)", self.deploy_path)

    # ──────────────────────────────────────────────────────
    # CORE GENERATION
    # ──────────────────────────────────────────────────────

    def generate(
        self,
        language: str,
        template: str = "module",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Generate code for a given language + template combination.

        Returns: {"code": str, "language": str, "template": str, "success": bool}
        """
        lang = language.lower()
        result: Dict[str, Any] = {
            "language": lang,
            "template": template,
            "success": False,
            "code": "",
            "error": None,
        }

        if lang not in _TEMPLATES:
            result["error"] = (
                f"Language '{language}' not supported. "
                f"Supported: {', '.join(SUPPORTED_LANGUAGES)}"
            )
            return result

        lang_templates = _TEMPLATES[lang]
        if template not in lang_templates:
            available = list(lang_templates.keys())
            template = available[0]
            log.debug("[CodeGenerator] Template not found, using '%s'", template)

        tpl = lang_templates[template]

        # Fill in defaults for missing kwargs
        # Use language-appropriate body placeholders so templates are valid in
        # their target language (Python "pass" is not valid Bash/JS syntax).
        _lang_body_defaults: Dict[str, str] = {
            "bash": ":  # implementation pending",
            "sh":   ":  # implementation pending",
            "javascript": "// implementation pending",
            "js":         "// implementation pending",
            "typescript": "// implementation pending",
        }
        defaults: Dict[str, str] = {
            "name": "niblit_module",
            "classname": "NiblitModule",
            "docstring": "Auto-generated by Niblit CodeGenerator.",
            "args": "",
            "body": _lang_body_defaults.get(lang, "pass"),
            "title": "Niblit",
            "description": "Auto-generated page.",
            "table_name": "data",
            "fields": "value TEXT",
            # C/C++ header guard
            "name_upper": "NIBLIT_MODULE",
        }
        # Auto-derive name_upper from name if not explicitly provided
        if "name" in kwargs and "name_upper" not in kwargs:
            defaults["name_upper"] = kwargs["name"].upper().replace("-", "_")
        ctx = {**defaults, **kwargs}

        try:
            code = tpl.format(**ctx)
            result["code"] = code
            result["success"] = True
            self._stats["generated"] += 1
            self._store(lang, template, code, ctx.get("name", "unnamed"))
            log.info("[CodeGenerator] Generated %s/%s for '%s'", lang, template, ctx["name"])
        except KeyError as exc:
            result["error"] = f"Template key error: {exc}"
            log.error("[CodeGenerator] %s", result["error"])

        return result

    def generate_niblit_module(self, name: str, docstring: str = "") -> Dict[str, Any]:
        """Shortcut: generate a standard Niblit Python module."""
        classname = "".join(w.capitalize() for w in name.split("_"))
        return self.generate(
            "python",
            "module",
            name=name,
            classname=classname,
            docstring=docstring or f"Niblit module: {name}",
        )

    def save_to_deploy(self, name: str, code: str) -> Dict[str, Any]:
        """Save generated Python code to the Niblit build (deploy) directory.

        The file is written to *self.deploy_path/<name>.py* so it can be
        hot-reloaded by the LiveUpdater and pushed to GitHub via GitHubSync.

        Returns {"path": str, "success": bool, "error": Optional[str]}.
        """
        result: Dict[str, Any] = {"path": None, "success": False, "error": None}
        if not self.deploy_path:
            result["error"] = "deploy_path not set — not running on Termux"
            return result

        # Ensure the name is a valid filename
        safe_name = name.replace(" ", "_").replace("-", "_")
        if not safe_name.endswith(".py"):
            safe_name = safe_name + ".py"

        try:
            self.deploy_path.mkdir(parents=True, exist_ok=True)
            fpath = self.deploy_path / safe_name
            fpath.write_text(code, encoding="utf-8")
            result["path"] = str(fpath)
            result["success"] = True
            self._stats["stored"] = self._stats.get("stored", 0) + 1
            log.info("[CodeGenerator] Saved %s to deploy path", safe_name)
        except OSError as exc:
            result["error"] = str(exc)
            log.debug("[CodeGenerator] save_to_deploy failed: %s", exc)

        return result

    def get_deploy_path(self) -> Optional[str]:
        """Return the current deploy path as a string, or None."""
        return str(self.deploy_path) if self.deploy_path else None

    def save_to_builds(self, language: str, name: str, code: str) -> Dict[str, Any]:
        """Save generated code to the local ``builds/{language}/`` directory.

        Provides a structured build store that works in any environment
        (Termux or standard Linux) and persists generated programs across
        sessions.  The directory is created automatically if it does not exist.

        Args:
            language: Target language (e.g. ``"rust"``, ``"python"``).
            name:     Base filename without extension (e.g. ``"ale_rust_module"``).
            code:     Source code string to write.

        Returns:
            ``{"path": str, "success": bool, "error": Optional[str]}``
        """
        result: Dict[str, Any] = {"path": None, "success": False, "error": None}
        lang = language.lower()
        ext = _EXTENSIONS.get(lang, ".txt")

        safe_name = name.replace(" ", "_").replace("-", "_")
        # For languages like "makefile"/"cmake", _EXTENSIONS stores a full filename
        # ("Makefile" / "CMakeLists.txt") rather than a dot-extension, so we use
        # that filename directly instead of appending a suffix.
        if ext in ("Makefile", "CMakeLists.txt"):
            safe_name = ext
        elif not safe_name.endswith(ext):
            safe_name = safe_name + ext

        try:
            build_dir = NIBLIT_LOCAL_BUILDS_PATH / lang
            build_dir.mkdir(parents=True, exist_ok=True)
            fpath = build_dir / safe_name
            fpath.write_text(code, encoding="utf-8")
            result["path"] = str(fpath)
            result["success"] = True
            self._stats["stored"] = self._stats.get("stored", 0) + 1
            log.info("[CodeGenerator] Saved %s to builds/%s/", safe_name, lang)
        except OSError as exc:
            result["error"] = str(exc)
            log.debug("[CodeGenerator] save_to_builds failed: %s", exc)

        return result

    # ──────────────────────────────────────────────────────
    # CODE STRUCTURE VALIDATION & CORRECTION
    # ──────────────────────────────────────────────────────

    def validate_structure(self, language: str, code: str) -> Dict[str, Any]:
        """Check whether *code* has proper structure for *language*.

        Checks performed:
          - python  : proper indentation (4 spaces), no mixed tabs/spaces,
                      has at least one top-level definition
          - bash    : starts with shebang, has ``set -euo pipefail``
          - javascript: has ``'use strict'`` or ``"use strict"``, no var declarations

        Returns:
            {
                "valid": bool,
                "language": str,
                "issues": List[str],   # empty when valid
            }
        """
        lang = language.lower()
        issues: List[str] = []

        if lang in ("python", "python3"):
            issues.extend(self._check_python_structure(code))
        elif lang in ("bash", "sh"):
            issues.extend(self._check_bash_structure(code))
        elif lang in ("javascript", "js"):
            issues.extend(self._check_javascript_structure(code))

        return {"valid": len(issues) == 0, "language": lang, "issues": issues}

    def ensure_structure(self, language: str, code: str) -> str:
        """Return *code* with common structural issues automatically fixed.

        Fixes applied per language:
          - python  : convert tabs to 4-space indent, normalise CRLF → LF
          - bash    : prepend ``#!/usr/bin/env bash`` if missing,
                      prepend ``set -euo pipefail`` if missing
          - javascript: prepend ``'use strict';`` if missing
        """
        lang = language.lower()
        # Universal: normalise CRLF line endings
        code = code.replace("\r\n", "\n")

        if lang in ("python", "python3"):
            code = self._fix_python_structure(code)
        elif lang in ("bash", "sh"):
            code = self._fix_bash_structure(code)
        elif lang in ("javascript", "js"):
            code = self._fix_javascript_structure(code)

        return code

    def generate_with_validation(
        self,
        language: str,
        template: str = "module",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Generate code and apply structural validation + auto-correction.

        Runs ``generate()`` then ``ensure_structure()`` then
        ``validate_structure()``.  Returns the same dict as ``generate()``
        with two extra keys: ``structure_issues`` (list) and
        ``structure_valid`` (bool).
        """
        result = self.generate(language, template, **kwargs)
        if not result.get("success"):
            result["structure_issues"] = []
            result["structure_valid"] = False
            return result

        # Auto-fix structural issues before returning
        fixed_code = self.ensure_structure(language, result["code"])
        result["code"] = fixed_code

        check = self.validate_structure(language, fixed_code)
        result["structure_issues"] = check["issues"]
        result["structure_valid"] = check["valid"]

        if not check["valid"]:
            log.warning(
                "[CodeGenerator] %s/%s structural issues: %s",
                language,
                template,
                check["issues"],
            )
        return result

    def generate_with_llm(
        self,
        language: str,
        purpose: str,
        research_context: str = "",
        llm: Any = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Generate code using an LLM when available, falling back to templates.

        When an LLM is provided and returns substantive content, it produces a
        richer implementation informed by *research_context*.  Falls back to
        :meth:`generate_with_validation` when the LLM is unavailable or returns
        nothing useful.

        Args:
            language:         Target language (e.g. ``"python"``).
            purpose:          Short description of what the code should do.
            research_context: Text snippets from autonomous research to guide
                              the LLM (truncated to 600 chars internally).
            llm:              An object with a ``generate_code(language, purpose,
                              context)`` method (e.g. ``HFLLMAdapter``).
            **kwargs:         Extra keyword args forwarded to the template
                              fallback (e.g. ``name``, ``classname``,
                              ``docstring``).

        Returns:
            Same dict structure as :meth:`generate_with_validation` with an
            extra ``"source"`` key: ``"llm"`` or ``"template"``.
        """
        lang = language.lower()
        result: Dict[str, Any] = {
            "language": lang,
            "success": False,
            "code": "",
            "error": None,
            "source": "template",
            "structure_issues": [],
            "structure_valid": True,
        }

        # ── LLM-powered generation ──────────────────────────────────────────
        if llm and hasattr(llm, "generate_code"):
            try:
                llm_code = llm.generate_code(lang, purpose, research_context)
                if llm_code and len(llm_code) > _MIN_LLM_CODE_LENGTH:
                    fixed = self.ensure_structure(lang, llm_code)
                    check = self.validate_structure(lang, fixed)
                    result["code"] = fixed
                    result["success"] = True
                    result["source"] = "llm"
                    result["structure_issues"] = check["issues"]
                    result["structure_valid"] = check["valid"]
                    self._stats["generated"] += 1
                    name = kwargs.get("name", "llm_generated")
                    self._store(lang, "llm", fixed, name)
                    log.info(
                        "[CodeGenerator] LLM-generated %s code (%d chars) for '%s'",
                        lang, len(fixed), purpose[:60],
                    )
                    return result
            except Exception as exc:
                log.debug("[CodeGenerator] LLM generation failed: %s", exc)

        # ── Template fallback ───────────────────────────────────────────────
        template = kwargs.pop("template", "module")
        fallback = self.generate_with_validation(lang, template, **kwargs)
        fallback["source"] = "template"
        return fallback

    # ── private structure helpers ──────────────────────────

    def _check_python_structure(self, code: str) -> List[str]:
        issues: List[str] = []
        lines = code.splitlines()
        has_tabs = any("\t" in ln for ln in lines)
        if has_tabs:
            issues.append("Mixed tabs detected — use 4-space indentation")
        # Check for at least one def/class at module level
        has_def = any(re.match(r"^(def |class )", ln) for ln in lines)
        if lines and not has_def:
            # Allow pure scripts (no def/class) only if short
            if len(lines) > _PY_MAX_LINES_WITHOUT_DEF:
                issues.append(
                    f"Scripts longer than {_PY_MAX_LINES_WITHOUT_DEF} lines "
                    "should contain at least one top-level def or class"
                )
        # Check indented blocks use multiples of 4 spaces
        for ln in lines:
            stripped = ln.lstrip(" ")
            indent = len(ln) - len(stripped)
            if indent > 0 and indent % 4 != 0 and not ln.strip().startswith("#"):
                issues.append(f"Non-4-space indent ({indent} spaces) on: {ln[:40]!r}")
                break  # report once
        return issues

    def _check_bash_structure(self, code: str) -> List[str]:
        issues: List[str] = []
        lines = [ln for ln in code.splitlines() if ln.strip()]
        if not lines:
            return issues
        if not lines[0].startswith("#!"):
            issues.append("Missing shebang line (e.g. #!/usr/bin/env bash)")
        if not any("set -" in ln for ln in lines[:10]):
            issues.append("Missing 'set -euo pipefail' safety flags")
        return issues

    def _check_javascript_structure(self, code: str) -> List[str]:
        issues: List[str] = []
        header = code[:_JS_HEADER_CHECK_SIZE]
        if "'use strict'" not in header and '"use strict"' not in header:
            issues.append("Missing 'use strict' directive")
        if re.search(r"\bvar\s+\w", code):
            issues.append("Found 'var' declaration — prefer const/let")
        return issues

    def _fix_python_structure(self, code: str) -> str:
        # Replace tab indentation with 4 spaces
        lines = []
        for ln in code.splitlines():
            leading = len(ln) - len(ln.lstrip("\t"))
            if leading:
                ln = "    " * leading + ln.lstrip("\t")
            lines.append(ln)
        return "\n".join(lines) + ("\n" if code.endswith("\n") else "")

    def _fix_bash_structure(self, code: str) -> str:
        lines = code.splitlines()
        non_empty = [ln for ln in lines if ln.strip()]
        if not non_empty:
            return code
        # Ensure shebang
        if not lines[0].startswith("#!"):
            lines.insert(0, "#!/usr/bin/env bash")
        # Ensure set -euo pipefail after shebang
        has_set = any("set -" in ln for ln in lines[:10])
        if not has_set:
            insert_at = 1
            # Insert after any comment block at top
            while insert_at < len(lines) and lines[insert_at].startswith("#"):
                insert_at += 1
            lines.insert(insert_at, "set -euo pipefail")
        return "\n".join(lines) + ("\n" if code.endswith("\n") else "")

    def _fix_javascript_structure(self, code: str) -> str:
        header = code[:_JS_HEADER_CHECK_SIZE]
        if "'use strict'" not in header and '"use strict"' not in header:
            code = "'use strict';\n\n" + code
        return code



    def study_language(self, language: str) -> str:
        """Return idioms and best practices for a language."""
        tips: Dict[str, List[str]] = {
            "python": [
                "Use type hints for all function signatures.",
                "Prefer f-strings for string formatting.",
                "Use dataclasses or namedtuples for data containers.",
                "Handle exceptions as specifically as possible.",
                "Use context managers (with) for resource management.",
                "Prefer list comprehensions over map/filter for clarity.",
                "Follow PEP 8 — snake_case for functions/variables, PascalCase for classes.",
                "Use logging instead of print() for production code.",
                "Write docstrings for all public functions and classes.",
                "Use pathlib.Path instead of os.path for file operations.",
            ],
            "bash": [
                "Use 'set -euo pipefail' at the top of every script.",
                "Quote all variables: \"$var\" not $var.",
                "Use [[ ]] instead of [ ] for conditionals.",
                "Prefer $() over backticks for command substitution.",
                "Use local variables in functions.",
                "Check command existence with command -v before using it.",
                "Use trap to clean up temp files on exit.",
                "Avoid parsing ls output; use globs or find instead.",
            ],
            "javascript": [
                "Use 'use strict' or ES modules.",
                "Prefer const/let over var.",
                "Use async/await over raw Promises for clarity.",
                "Use === (strict equality) not ==.",
                "Destructure objects and arrays when possible.",
                "Use arrow functions for callbacks.",
                "Handle Promise rejections with .catch() or try/catch.",
                "Use template literals instead of string concatenation.",
            ],
            "java": [
                "Follow SOLID principles — especially single responsibility.",
                "Use Optional<T> instead of returning null.",
                "Prefer interface types over concrete class types in declarations.",
                "Use try-with-resources for AutoCloseable objects.",
                "Use StringBuilder for string concatenation in loops.",
                "Mark fields final whenever possible.",
                "Annotate overrides with @Override.",
                "Use enhanced for-loop (for-each) over index-based loops.",
                "Prefer enums over integer constants for named values.",
                "Use logging frameworks (SLF4J/Logback) over System.out.",
            ],
            "c": [
                "Always initialise variables — undefined behaviour is silent.",
                "Check every return value, especially from malloc/calloc.",
                "Use const for pointers to read-only data.",
                "Free every heap allocation; prefer RAII wrappers in C++.",
                "Use static analysis (clang-tidy, cppcheck) regularly.",
                "Prefer snprintf over sprintf to prevent buffer overflows.",
                "Include guards in every header file (#ifndef HEADER_H).",
                "Use size_t for sizes and indices, not int.",
                "Separate interface (.h) from implementation (.c).",
                "Enable all compiler warnings: -Wall -Wextra -pedantic.",
            ],
            "cpp": [
                "Prefer smart pointers (unique_ptr/shared_ptr) over raw pointers.",
                "Use RAII — resource acquisition is initialisation.",
                "Prefer std::string over C-style char arrays.",
                "Use range-based for loops.",
                "Mark member functions const when they don't mutate state.",
                "Avoid raw new/delete; use make_unique/make_shared.",
                "Use std::array instead of C arrays for fixed-size collections.",
                "Apply Rule of Zero, Three, or Five consistently.",
                "Use noexcept where applicable.",
                "Compile with -std=c++17 or later.",
            ],
            "rust": [
                "Embrace ownership and the borrow checker — don't fight it.",
                "Use Result<T,E> and ? operator for error propagation.",
                "Prefer iterators and adapters over manual loops.",
                "Use #[derive(Debug, Clone)] liberally.",
                "Use cargo clippy and cargo fmt regularly.",
                "Avoid .unwrap() in production; use proper error handling.",
                "Use lifetimes explicitly only when the compiler asks for them.",
                "Prefer &str over String for function parameters when possible.",
                "Use structured logging with the tracing crate.",
                "Write unit tests in the same file using #[cfg(test)].",
            ],
            "go": [
                "Handle every error explicitly — don't ignore returns.",
                "Use defer for cleanup instead of finally blocks.",
                "Keep goroutines small and well-scoped; always pass context.",
                "Use interfaces for dependency injection and testability.",
                "Prefer value receivers unless you need mutation.",
                "Use sync.WaitGroup and channels for goroutine coordination.",
                "Run go vet and golint on every commit.",
                "Organise code into small, focused packages.",
                "Prefer table-driven tests.",
                "Use context.Context for cancellation and deadlines.",
            ],
            "kotlin": [
                "Prefer val (immutable) over var wherever possible.",
                "Use data classes for plain data holders.",
                "Leverage extension functions to add behaviour to existing types.",
                "Use coroutines (suspend fun) over callbacks.",
                "Use when instead of chained if-else.",
                "Leverage null-safety: use ?: and ?. operators.",
                "Use sealed classes for exhaustive when expressions.",
                "Prefer Sequence over List for lazy chain operations.",
                "Annotate Android entry points with @Inject / Hilt.",
                "Write unit tests with JUnit5 + MockK.",
            ],
            "typescript": [
                "Enable strict mode in tsconfig.json.",
                "Prefer interfaces for object shapes and type aliases for unions.",
                "Avoid any; use unknown and narrow it.",
                "Use readonly for immutable properties.",
                "Type async functions with Promise<T> return types.",
                "Use enum or const enum for named constants.",
                "Use utility types (Partial, Required, Pick, Omit).",
                "Enable noImplicitAny and strictNullChecks.",
                "Use ESLint + @typescript-eslint for linting.",
                "Prefer optional chaining (?.) over explicit null checks.",
            ],
            "assembly": [
                "Comment every non-obvious instruction.",
                "Preserve caller-saved registers (push/pop or push/pop xmm).",
                "Follow the System V AMD64 or ARM AAPCS calling convention.",
                "Use symbolic constants (equ) for magic numbers.",
                "Align data sections to natural word boundaries.",
                "Separate .data, .bss, and .text sections clearly.",
                "Use debug symbols (DWARF) to aid GDB debugging.",
                "Test on a VM before running on real hardware.",
                "Minimise the critical path — pipeline stalls are costly.",
                "Document register usage at function entry.",
            ],
            "swift": [
                "Prefer struct over class for value semantics.",
                "Use guard for early exits to reduce nesting.",
                "Use optional binding (if let / guard let) over force unwrapping.",
                "Leverage protocol-oriented design.",
                "Use lazy for expensive computed properties.",
                "Prefer Codable for JSON serialisation.",
                "Use async/await (Swift 5.5+) for concurrency.",
                "Apply access control (private, internal, public).",
                "Use SwiftLint to enforce style.",
                "Write tests with XCTest.",
            ],
            "ruby": [
                "Follow the Ruby Style Guide (2-space indentation).",
                "Use frozen_string_literal: true at the top of every file.",
                "Prefer symbols over strings for hash keys.",
                "Use blocks, procs, and lambdas idiomatically.",
                "Use Enumerable methods (map, select, reduce) over loops.",
                "Use keyword arguments for clarity.",
                "Prefer attr_reader/writer/accessor over manual getter/setter.",
                "Use RuboCop for style enforcement.",
                "Write tests with RSpec or Minitest.",
                "Use Bundler and a Gemfile for dependency management.",
            ],
            "php": [
                "Declare strict_types=1 at the top of every file.",
                "Use typed properties (PHP 7.4+).",
                "Prefer named arguments for clarity (PHP 8.0+).",
                "Use Composer for dependency management.",
                "Avoid global variables; use dependency injection.",
                "Use PSR-12 coding standard.",
                "Handle errors with exceptions, not error codes.",
                "Use prepared statements to prevent SQL injection.",
                "Use PHPStan or Psalm for static analysis.",
                "Test with PHPUnit.",
            ],
        }

        lang = language.lower()
        if lang not in tips:
            return f"No study material for '{language}'. Available: {', '.join(tips)}"

        lines = [f"📚 **{language.capitalize()} Best Practices:**\n"]
        for i, tip in enumerate(tips[lang], 1):
            lines.append(f"  {i:2d}. {tip}")

        result = "\n".join(lines)

        # Queue this topic for deeper research
        if self.db and hasattr(self.db, "queue_learning"):
            self.db.queue_learning(f"{language} programming patterns")

        return result

    def study_domain(self, domain: str) -> str:
        """Return study notes and best practices for a broad technical domain.

        Domains: networking, operating_systems, binary, kernel, firmware, bios,
                 android, linux, security, embedded.
        """
        notes: Dict[str, List[str]] = {
            "networking": [
                "Understand the OSI model — each layer has distinct responsibilities.",
                "Learn TCP vs UDP trade-offs: reliability vs latency.",
                "Use non-blocking / async I/O (select, poll, epoll, io_uring) for scale.",
                "Always validate and sanitise data received from the network.",
                "Use TLS/SSL for all production network communication.",
                "Implement connection timeouts and retry with exponential backoff.",
                "Study socket options: SO_REUSEADDR, SO_KEEPALIVE, TCP_NODELAY.",
                "Use Wireshark / tcpdump to analyse live traffic.",
                "Learn DNS: A, AAAA, CNAME, MX, TXT record types.",
                "Study HTTP/1.1, HTTP/2, and HTTP/3 (QUIC) differences.",
            ],
            "operating_systems": [
                "Understand process vs thread vs coroutine distinctions.",
                "Learn virtual memory: page tables, TLBs, demand paging.",
                "Study scheduling algorithms: CFS (Linux), round-robin, priority queues.",
                "Understand IPC: pipes, sockets, shared memory, message queues.",
                "Learn file-system internals: inodes, journaling, VFS layer.",
                "Study system calls: the kernel/user-space boundary.",
                "Understand interrupt handling and context switching.",
                "Learn about capability-based security and SELinux/AppArmor.",
                "Study container primitives: namespaces and cgroups.",
                "Use strace and perf to debug system-level issues.",
            ],
            "binary": [
                "Understand endianness — little-endian vs big-endian.",
                "Learn ELF format: .text, .data, .bss, .rodata sections.",
                "Study the PE format for Windows executables.",
                "Use hexdump, xxd, binwalk for binary analysis.",
                "Understand DEX (Dalvik bytecode) format for Android.",
                "Learn to read disassembly output (objdump, IDA, Ghidra).",
                "Study DWARF debug info embedded in binaries.",
                "Understand code signing and integrity verification.",
                "Learn about PIE (position-independent executables) and ASLR.",
                "Practise writing Python scripts using struct module for binary I/O.",
            ],
            "kernel": [
                "Understand the monolithic vs microkernel architecture trade-offs.",
                "Learn Linux module programming: init/exit, module_param.",
                "Study device driver model: platform devices, character devices, block devices.",
                "Understand memory management: kmalloc, vmalloc, slab allocator.",
                "Learn DMA and interrupt handling in kernel context.",
                "Study the Virtual Filesystem (VFS) abstraction.",
                "Use KGDB or QEMU for kernel debugging.",
                "Write and run unit tests with KUnit.",
                "Study kernel locking primitives: spinlock, mutex, RCU.",
                "Follow Documentation/process/coding-style.rst for kernel code style.",
            ],
            "firmware": [
                "Understand the boot sequence: ROM → bootloader → RTOS/OS.",
                "Learn CMSIS for ARM Cortex-M peripheral access.",
                "Use volatile for memory-mapped I/O registers.",
                "Prefer fixed-width integer types (uint32_t, int8_t).",
                "Avoid dynamic memory allocation on bare-metal systems.",
                "Use watchdog timers to recover from firmware hangs.",
                "Understand flash memory wear levelling.",
                "Use SWD/JTAG + GDB for firmware debugging.",
                "Implement over-the-air (OTA) update with A/B partition scheme.",
                "Validate checksums (CRC32) before booting firmware images.",
            ],
            "bios": [
                "Understand BIOS vs UEFI — UEFI is PE32+ EFI application based.",
                "Learn UEFI boot services vs runtime services.",
                "Study ACPI tables: RSDP, RSDT, XSDT, DSDT, SSDT.",
                "Use EDK2 / TianoCore as the open-source UEFI reference implementation.",
                "Learn how the bootloader hands off to the OS (ExitBootServices).",
                "Understand SMM (System Management Mode) and its security implications.",
                "Study Secure Boot chain of trust: keys, signatures, MOK.",
                "Use OVMF + QEMU to test UEFI firmware without real hardware.",
                "Learn legacy BIOS INT calls (INT 10h video, INT 13h disk).",
                "Analyse firmware with Binwalk and UEFITool.",
            ],
            "android": [
                "Understand the Android stack: Linux kernel → HAL → ART/Dalvik → Framework → Apps.",
                "Learn the Activity lifecycle: onCreate → onStart → onResume → onPause → onStop → onDestroy.",
                "Use ViewModel + LiveData / StateFlow for MVVM architecture.",
                "Prefer Jetpack Compose for new UI work.",
                "Always request permissions at runtime (Android 6+).",
                "Use Room for local database access.",
                "Learn about Android's Binder IPC mechanism.",
                "Use ADB for debugging: adb logcat, adb shell, adb install.",
                "Study DEX bytecode and smali for reverse-engineering.",
                "Sign APKs with aligned zipalign and apksigner.",
            ],
            "linux": [
                "Learn the FHS (Filesystem Hierarchy Standard).",
                "Use systemd unit files for service management.",
                "Master cgroups v2 for resource control.",
                "Use LVM for flexible storage management.",
                "Learn iptables / nftables for firewall rules.",
                "Use auditd for security event logging.",
                "Automate with Ansible, SaltStack, or Chef.",
                "Use namespaces for lightweight containerisation.",
                "Master sed, awk, and grep for text processing.",
                "Keep the kernel up-to-date; use live-patching (kpatch) for CVEs.",
            ],
            "security": [
                "Apply the principle of least privilege everywhere.",
                "Sanitise and validate all external inputs.",
                "Use parameterised queries to prevent SQL injection.",
                "Keep dependencies updated; use SBOM and Dependabot.",
                "Enforce TLS 1.2+ and strong cipher suites.",
                "Use Content-Security-Policy and other security headers.",
                "Implement proper password hashing (Argon2id, bcrypt).",
                "Conduct threat-modelling using STRIDE.",
                "Use static analysis (CodeQL, Semgrep) in CI.",
                "Practise responsible disclosure and CVE reporting.",
            ],
            "embedded": [
                "Profile memory usage: RAM is scarce on microcontrollers.",
                "Use interrupt-driven I/O instead of polling where latency matters.",
                "Understand clock domains and metastability in FPGAs.",
                "Prefer MISRA-C or CERT-C for safety-critical code.",
                "Use an RTOS (FreeRTOS, Zephyr) for multi-tasking needs.",
                "Implement hardware abstraction layers for portability.",
                "Test on a development board before final hardware.",
                "Use scope / logic-analyser to debug hardware timing issues.",
                "Read datasheets cover-to-cover for peripherals you use.",
                "Enable watchdog timer and fault handlers.",
            ],
        }

        domain_key = domain.lower().replace(" ", "_")
        if domain_key not in notes:
            return (
                f"No domain notes for '{domain}'. "
                f"Available: {', '.join(notes)}"
            )

        lines = [f"🌐 **{domain.replace('_', ' ').title()} Study Notes:**\n"]
        for i, note in enumerate(notes[domain_key], 1):
            lines.append(f"  {i:2d}. {note}")

        result = "\n".join(lines)

        # Queue for deeper research
        if self.db and hasattr(self.db, "queue_learning"):
            self.db.queue_learning(f"{domain} system architecture patterns")

        return result

    def list_templates(self, language: Optional[str] = None) -> str:
        """List available templates."""
        if language:
            lang = language.lower()
            if lang in _TEMPLATES:
                tmpls = list(_TEMPLATES[lang].keys())
                return f"Templates for {language}: {', '.join(tmpls)}"
            return f"Language '{language}' not found. Use: {', '.join(SUPPORTED_LANGUAGES)}"

        lines = ["📋 **Available Code Templates:**\n"]
        for lang, tmpls in _TEMPLATES.items():
            lines.append(f"  {lang:<15}  {', '.join(tmpls.keys())}")
        return "\n".join(lines)

    # ──────────────────────────────────────────────────────
    # RESEARCH-DRIVEN CODE GENERATION
    # ──────────────────────────────────────────────────────

    # Map of topic keywords → real Python code snippet that implements the concept.
    # Each entry is a (imports, constants, functions, class_body) tuple of code strings.
    _PYTHON_TOPIC_SNIPPETS: Dict[str, Dict[str, str]] = {
        "nlp": {
            "imports": "import re\nimport string\nfrom collections import Counter",
            "constants": (
                "STOPWORDS = {\n"
                "    'the', 'a', 'an', 'is', 'it', 'in', 'of', 'to', 'and', 'or',\n"
                "    'for', 'on', 'at', 'by', 'with', 'that', 'this', 'was', 'are',\n"
                "}\n"
                "MAX_TOKENS = 512"
            ),
            "functions": (
                "def tokenize(text: str) -> List[str]:\n"
                "    \"\"\"Split text into tokens, removing punctuation and stopwords.\"\"\"\n"
                "    text = text.lower()\n"
                "    text = re.sub(r'[^\\w\\s]', '', text)\n"
                "    return [w for w in text.split() if w and w not in STOPWORDS]\n"
                "\n"
                "def clean_text(text: str) -> str:\n"
                "    \"\"\"Normalise whitespace and lowercase text.\"\"\"\n"
                "    return re.sub(r'\\s+', ' ', text).strip().lower()\n"
                "\n"
                "def extract_keywords(text: str, top_n: int = 10) -> List[str]:\n"
                "    \"\"\"Return the top-N most frequent tokens.\"\"\"\n"
                "    tokens = tokenize(clean_text(text))\n"
                "    freq = Counter(tokens)\n"
                "    return [w for w, _ in freq.most_common(top_n)]\n"
                "\n"
                "def ngrams(tokens: List[str], n: int = 2) -> List[tuple]:\n"
                "    \"\"\"Yield consecutive n-grams from a token list.\"\"\"\n"
                "    return [tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]"
            ),
            "class_body": (
                "    def __init__(self, language: str = 'en') -> None:\n"
                "        self.language = language\n"
                "        self._docs: List[str] = []\n"
                "        log.debug('[%s] Initialized (lang=%s)', __name__, language)\n"
                "\n"
                "    def process(self, text: str) -> Dict[str, Any]:\n"
                "        \"\"\"Tokenise, clean, and extract features from *text*.\"\"\"\n"
                "        cleaned = clean_text(text)\n"
                "        tokens = tokenize(cleaned)\n"
                "        keywords = extract_keywords(cleaned)\n"
                "        bigrams = ngrams(tokens, 2)\n"
                "        self._docs.append(cleaned)\n"
                "        return {\n"
                "            'original_length': len(text),\n"
                "            'cleaned': cleaned,\n"
                "            'tokens': tokens[:20],\n"
                "            'keywords': keywords,\n"
                "            'bigrams': [' '.join(b) for b in bigrams[:10]],\n"
                "            'token_count': len(tokens),\n"
                "        }\n"
                "\n"
                "    def batch_process(self, texts: List[str]) -> List[Dict[str, Any]]:\n"
                "        \"\"\"Process a list of texts and return per-document results.\"\"\"\n"
                "        return [self.process(t) for t in texts]\n"
                "\n"
                "    def run(self) -> Dict[str, Any]:\n"
                "        \"\"\"Return current statistics.\"\"\"\n"
                "        return {'documents_processed': len(self._docs), 'language': self.language}"
            ),
        },
        "chat": {
            "imports": "import json\nimport time",
            "constants": (
                "VALID_ROLES = ('system', 'user', 'assistant')\n"
                "DEFAULT_MAX_TOKENS = 2048\n"
                "DEFAULT_TEMPERATURE = 0.7"
            ),
            "functions": (
                "def build_message(role: str, content: str) -> Dict[str, str]:\n"
                "    \"\"\"Validate and build a chat message dict.\"\"\"\n"
                "    if role not in VALID_ROLES:\n"
                "        raise ValueError(f'role must be one of {VALID_ROLES}')\n"
                "    return {'role': role, 'content': content.strip()}\n"
                "\n"
                "def truncate_history(\n"
                "    history: List[Dict[str, str]],\n"
                "    max_messages: int = 20,\n"
                ") -> List[Dict[str, str]]:\n"
                "    \"\"\"Keep the system message plus the most-recent *max_messages* turns.\"\"\"\n"
                "    system = [m for m in history if m.get('role') == 'system']\n"
                "    turns = [m for m in history if m.get('role') != 'system']\n"
                "    return system + turns[-max_messages:]"
            ),
            "class_body": (
                "    def __init__(self, system_prompt: str = 'You are a helpful assistant.') -> None:\n"
                "        self.history: List[Dict[str, str]] = [\n"
                "            build_message('system', system_prompt)\n"
                "        ]\n"
                "        self._created_at: float = time.time()\n"
                "        log.debug('[%s] Initialized', __name__)\n"
                "\n"
                "    def send(self, user_input: str) -> Dict[str, Any]:\n"
                "        \"\"\"Append a user turn and return the payload for an LLM API call.\"\"\"\n"
                "        self.history.append(build_message('user', user_input))\n"
                "        payload = {\n"
                "            'messages': self.history,\n"
                "            'max_tokens': DEFAULT_MAX_TOKENS,\n"
                "            'temperature': DEFAULT_TEMPERATURE,\n"
                "        }\n"
                "        return payload\n"
                "\n"
                "    def receive(self, assistant_reply: str) -> None:\n"
                "        \"\"\"Record an assistant reply in the conversation history.\"\"\"\n"
                "        self.history.append(build_message('assistant', assistant_reply))\n"
                "        self.history = truncate_history(self.history)\n"
                "\n"
                "    def clear(self) -> None:\n"
                "        \"\"\"Reset conversation history (keeps the system prompt).\"\"\"\n"
                "        self.history = [m for m in self.history if m.get('role') == 'system']\n"
                "\n"
                "    def run(self) -> Dict[str, Any]:\n"
                "        \"\"\"Return conversation statistics.\"\"\"\n"
                "        turns = [m for m in self.history if m.get('role') != 'system']\n"
                "        return {\n"
                "            'turns': len(turns),\n"
                "            'history_bytes': len(json.dumps(self.history)),\n"
                "            'uptime_s': round(time.time() - self._created_at, 1),\n"
                "        }"
            ),
        },
        "api": {
            "imports": "import urllib.request\nimport urllib.error\nimport json\nimport time",
            "constants": (
                "DEFAULT_TIMEOUT = 30\n"
                "MAX_RETRIES = 3\n"
                "RETRY_DELAY = 2.0"
            ),
            "functions": (
                "def http_get(url: str, headers: Optional[Dict[str, str]] = None,\n"
                "             timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:\n"
                "    \"\"\"Simple HTTP GET with retry logic; returns parsed JSON or raw text.\"\"\"\n"
                "    req = urllib.request.Request(url, headers=headers or {})\n"
                "    for attempt in range(1, MAX_RETRIES + 1):\n"
                "        try:\n"
                "            with urllib.request.urlopen(req, timeout=timeout) as resp:\n"
                "                raw = resp.read().decode('utf-8', errors='replace')\n"
                "                try:\n"
                "                    return {'ok': True, 'data': json.loads(raw), 'status': resp.status}\n"
                "                except json.JSONDecodeError:\n"
                "                    return {'ok': True, 'data': raw, 'status': resp.status}\n"
                "        except urllib.error.URLError as exc:\n"
                "            if attempt == MAX_RETRIES:\n"
                "                return {'ok': False, 'error': str(exc), 'status': None}\n"
                "            time.sleep(RETRY_DELAY * attempt)\n"
                "    return {'ok': False, 'error': 'max retries exceeded', 'status': None}"
            ),
            "class_body": (
                "    def __init__(self, base_url: str = '', api_key: str = '') -> None:\n"
                "        self.base_url = base_url.rstrip('/')\n"
                "        self._headers: Dict[str, str] = {}\n"
                "        if api_key:\n"
                "            self._headers['Authorization'] = f'Bearer {api_key}'\n"
                "        log.debug('[%s] Initialized (base=%s)', __name__, self.base_url)\n"
                "\n"
                "    def get(self, path: str, extra_headers: Optional[Dict[str, str]] = None\n"
                "            ) -> Dict[str, Any]:\n"
                "        \"\"\"Perform GET *base_url/path* and return parsed response.\"\"\"\n"
                "        url = f'{self.base_url}/{path.lstrip(\"/\")}'\n"
                "        headers = {**self._headers, **(extra_headers or {})}\n"
                "        return http_get(url, headers=headers)\n"
                "\n"
                "    def health_check(self) -> bool:\n"
                "        \"\"\"Return True if the API base URL is reachable.\"\"\"\n"
                "        if not self.base_url:\n"
                "            return False\n"
                "        result = http_get(self.base_url, headers=self._headers, timeout=5)\n"
                "        return result.get('ok', False)\n"
                "\n"
                "    def run(self) -> Dict[str, Any]:\n"
                "        \"\"\"Return client configuration summary.\"\"\"\n"
                "        return {\n"
                "            'base_url': self.base_url,\n"
                "            'has_auth': bool(self._headers.get('Authorization')),\n"
                "            'timeout': DEFAULT_TIMEOUT,\n"
                "        }"
            ),
        },
        "memory": {
            "imports": "import json\nimport time\nimport threading",
            "constants": (
                "MAX_MEMORY_ENTRIES = 1000\n"
                "MEMORY_TTL_SECONDS = 3600"
            ),
            "functions": (
                "def _now() -> float:\n"
                "    return time.time()\n"
                "\n"
                "def _expired(entry: Dict[str, Any], ttl: float = MEMORY_TTL_SECONDS) -> bool:\n"
                "    \"\"\"Return True if the *entry* has exceeded its TTL.\"\"\"\n"
                "    return (_now() - entry.get('ts', 0)) > ttl"
            ),
            "class_body": (
                "    def __init__(self, max_entries: int = MAX_MEMORY_ENTRIES) -> None:\n"
                "        self._store: Dict[str, Any] = {}\n"
                "        self._max = max_entries\n"
                "        self._lock = threading.Lock()\n"
                "        log.debug('[%s] Initialized (max=%d)', __name__, max_entries)\n"
                "\n"
                "    def set(self, key: str, value: Any, ttl: float = MEMORY_TTL_SECONDS\n"
                "            ) -> None:\n"
                "        \"\"\"Store *value* under *key* with an optional TTL.\"\"\"\n"
                "        with self._lock:\n"
                "            self._evict()\n"
                "            self._store[key] = {'value': value, 'ts': _now(), 'ttl': ttl}\n"
                "\n"
                "    def get(self, key: str, default: Any = None) -> Any:\n"
                "        \"\"\"Retrieve a value; returns *default* if missing or expired.\"\"\"\n"
                "        with self._lock:\n"
                "            entry = self._store.get(key)\n"
                "            if entry is None or _expired(entry, entry.get('ttl', MEMORY_TTL_SECONDS)):\n"
                "                return default\n"
                "            return entry['value']\n"
                "\n"
                "    def delete(self, key: str) -> bool:\n"
                "        \"\"\"Remove *key*; returns True if the key existed.\"\"\"\n"
                "        with self._lock:\n"
                "            return self._store.pop(key, None) is not None\n"
                "\n"
                "    def _evict(self) -> None:\n"
                "        \"\"\"Remove expired entries; trim to *_max* if still over capacity.\"\"\"\n"
                "        self._store = {\n"
                "            k: v for k, v in self._store.items()\n"
                "            if not _expired(v, v.get('ttl', MEMORY_TTL_SECONDS))\n"
                "        }\n"
                "        if len(self._store) >= self._max:\n"
                "            oldest = sorted(self._store.items(), key=lambda kv: kv[1]['ts'])\n"
                "            for k, _ in oldest[:len(self._store) - self._max + 1]:\n"
                "                del self._store[k]\n"
                "\n"
                "    def run(self) -> Dict[str, Any]:\n"
                "        \"\"\"Return current memory statistics.\"\"\"\n"
                "        with self._lock:\n"
                "            return {\n"
                "                'entries': len(self._store),\n"
                "                'max_entries': self._max,\n"
                "                'oldest_ts': min(\n"
                "                    (v['ts'] for v in self._store.values()), default=None\n"
                "                ),\n"
                "            }"
            ),
        },
        "reasoning": {
            "imports": "import re\nimport math\nfrom collections import defaultdict",
            "constants": (
                "LOGIC_OPS = {\n"
                "    'and': lambda a, b: a and b,\n"
                "    'or':  lambda a, b: a or b,\n"
                "    'not': lambda a, _: not a,\n"
                "    'xor': lambda a, b: bool(a) != bool(b),\n"
                "}\n"
                "CONFIDENCE_THRESHOLD = 0.6"
            ),
            "functions": (
                "def chain_of_thought(premises: List[str]) -> List[str]:\n"
                "    \"\"\"Apply simple forward chaining over a list of premise strings.\"\"\"\n"
                "    derived: List[str] = list(premises)\n"
                "    for i, p in enumerate(premises):\n"
                "        for j, q in enumerate(premises):\n"
                "            if i != j and q.startswith(p.split()[-1]):\n"
                "                conclusion = f'{p.split()[0]} → {q.split()[-1]}'\n"
                "                if conclusion not in derived:\n"
                "                    derived.append(conclusion)\n"
                "    return derived\n"
                "\n"
                "def score_confidence(evidence: List[float]) -> float:\n"
                "    \"\"\"Aggregate evidence weights into a single confidence score 0–1.\"\"\"\n"
                "    if not evidence:\n"
                "        return 0.0\n"
                "    return min(1.0, sum(evidence) / (len(evidence) * 1.0))\n"
                "\n"
                "def extract_facts(text: str) -> List[str]:\n"
                "    \"\"\"Extract simple subject-verb-object facts from plain text.\"\"\"\n"
                "    sentences = re.split(r'[.!?]', text)\n"
                "    return [s.strip() for s in sentences if len(s.strip().split()) >= 3]"
            ),
            "class_body": (
                "    def __init__(self) -> None:\n"
                "        self._knowledge: Dict[str, List[str]] = defaultdict(list)\n"
                "        self._inferences: List[str] = []\n"
                "        log.debug('[%s] Initialized', __name__)\n"
                "\n"
                "    def add_fact(self, subject: str, predicate: str, obj: str) -> None:\n"
                "        \"\"\"Store a (subject, predicate, object) triple.\"\"\"\n"
                "        triple = f'{subject} {predicate} {obj}'\n"
                "        self._knowledge[subject].append(triple)\n"
                "\n"
                "    def infer(self, query: str) -> List[str]:\n"
                "        \"\"\"Return known facts whose subject matches *query*.\"\"\"\n"
                "        results = self._knowledge.get(query, [])\n"
                "        chains = chain_of_thought(results)\n"
                "        self._inferences.extend(chains)\n"
                "        return chains\n"
                "\n"
                "    def learn_from_text(self, text: str) -> int:\n"
                "        \"\"\"Extract and store facts from free text; return count added.\"\"\"\n"
                "        facts = extract_facts(text)\n"
                "        for fact in facts:\n"
                "            parts = fact.split(maxsplit=2)\n"
                "            if len(parts) == 3:\n"
                "                self.add_fact(*parts)\n"
                "        return len(facts)\n"
                "\n"
                "    def run(self) -> Dict[str, Any]:\n"
                "        \"\"\"Return knowledge-base statistics.\"\"\"\n"
                "        return {\n"
                "            'subjects': len(self._knowledge),\n"
                "            'total_facts': sum(len(v) for v in self._knowledge.values()),\n"
                "            'inferences': len(self._inferences),\n"
                "            'confidence_threshold': CONFIDENCE_THRESHOLD,\n"
                "        }"
            ),
        },
        "networking": {
            "imports": "import socket\nimport struct\nimport select\nimport threading",
            "constants": (
                "DEFAULT_HOST = '127.0.0.1'\n"
                "DEFAULT_PORT = 8080\n"
                "BUFFER_SIZE = 4096\n"
                "BACKLOG = 5"
            ),
            "functions": (
                "def pack_message(data: bytes) -> bytes:\n"
                "    \"\"\"Prefix *data* with a 4-byte big-endian length header.\"\"\"\n"
                "    return struct.pack('>I', len(data)) + data\n"
                "\n"
                "def unpack_message(sock: 'socket.socket') -> Optional[bytes]:\n"
                "    \"\"\"Read a length-prefixed message from *sock*; returns None on EOF.\"\"\"\n"
                "    raw_len = _recv_all(sock, 4)\n"
                "    if not raw_len:\n"
                "        return None\n"
                "    (msg_len,) = struct.unpack('>I', raw_len)\n"
                "    return _recv_all(sock, msg_len)\n"
                "\n"
                "def _recv_all(sock: 'socket.socket', n: int) -> Optional[bytes]:\n"
                "    \"\"\"Read exactly *n* bytes from *sock* or return None on connection loss.\"\"\"\n"
                "    buf = bytearray()\n"
                "    while len(buf) < n:\n"
                "        chunk = sock.recv(n - len(buf))\n"
                "        if not chunk:\n"
                "            return None\n"
                "        buf.extend(chunk)\n"
                "    return bytes(buf)"
            ),
            "class_body": (
                "    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT\n"
                "                 ) -> None:\n"
                "        self.host = host\n"
                "        self.port = port\n"
                "        self._sock: Optional[socket.socket] = None\n"
                "        log.debug('[%s] Initialized (%s:%d)', __name__, host, port)\n"
                "\n"
                "    def connect(self) -> bool:\n"
                "        \"\"\"Open a TCP connection; return True on success.\"\"\"\n"
                "        try:\n"
                "            self._sock = socket.create_connection((self.host, self.port),\n"
                "                                                  timeout=10)\n"
                "            log.info('[%s] Connected to %s:%d', __name__,\n"
                "                     self.host, self.port)\n"
                "            return True\n"
                "        except OSError as exc:\n"
                "            log.error('[%s] connect failed: %s', __name__, exc)\n"
                "            return False\n"
                "\n"
                "    def send(self, data: bytes) -> bool:\n"
                "        \"\"\"Send a length-prefixed message; return True on success.\"\"\"\n"
                "        if not self._sock:\n"
                "            return False\n"
                "        try:\n"
                "            self._sock.sendall(pack_message(data))\n"
                "            return True\n"
                "        except OSError as exc:\n"
                "            log.error('[%s] send failed: %s', __name__, exc)\n"
                "            return False\n"
                "\n"
                "    def close(self) -> None:\n"
                "        \"\"\"Close the connection.\"\"\"\n"
                "        if self._sock:\n"
                "            self._sock.close()\n"
                "            self._sock = None\n"
                "\n"
                "    def run(self) -> Dict[str, Any]:\n"
                "        \"\"\"Return connection status.\"\"\"\n"
                "        return {\n"
                "            'host': self.host,\n"
                "            'port': self.port,\n"
                "            'connected': self._sock is not None,\n"
                "        }"
            ),
        },
        "data": {
            "imports": "import csv\nimport json\nimport os\nfrom pathlib import Path",
            "constants": (
                "DEFAULT_ENCODING = 'utf-8'\n"
                "MAX_ROWS = 10_000"
            ),
            "functions": (
                "def read_jsonl(path: str) -> List[Dict[str, Any]]:\n"
                "    \"\"\"Read a newline-delimited JSON file and return a list of records.\"\"\"\n"
                "    records: List[Dict[str, Any]] = []\n"
                "    with open(path, encoding=DEFAULT_ENCODING) as fh:\n"
                "        for line in fh:\n"
                "            line = line.strip()\n"
                "            if line:\n"
                "                records.append(json.loads(line))\n"
                "    return records[:MAX_ROWS]\n"
                "\n"
                "def write_jsonl(records: List[Dict[str, Any]], path: str) -> int:\n"
                "    \"\"\"Write *records* to a JSONL file; returns number of records written.\"\"\"\n"
                "    Path(path).parent.mkdir(parents=True, exist_ok=True)\n"
                "    with open(path, 'w', encoding=DEFAULT_ENCODING) as fh:\n"
                "        for rec in records:\n"
                "            fh.write(json.dumps(rec, ensure_ascii=False) + '\\n')\n"
                "    return len(records)\n"
                "\n"
                "def flatten(d: Dict[str, Any], prefix: str = '') -> Dict[str, Any]:\n"
                "    \"\"\"Recursively flatten a nested dict with dot-separated keys.\"\"\"\n"
                "    items: Dict[str, Any] = {}\n"
                "    for k, v in d.items():\n"
                "        key = f'{prefix}.{k}' if prefix else k\n"
                "        if isinstance(v, dict):\n"
                "            items.update(flatten(v, key))\n"
                "        else:\n"
                "            items[key] = v\n"
                "    return items"
            ),
            "class_body": (
                "    def __init__(self, data_dir: str = '.') -> None:\n"
                "        self.data_dir = Path(data_dir)\n"
                "        self._records: List[Dict[str, Any]] = []\n"
                "        log.debug('[%s] Initialized (dir=%s)', __name__, data_dir)\n"
                "\n"
                "    def load(self, filename: str) -> int:\n"
                "        \"\"\"Load records from a JSONL file under *data_dir*.\"\"\"\n"
                "        path = str(self.data_dir / filename)\n"
                "        self._records = read_jsonl(path)\n"
                "        log.info('[%s] Loaded %d records from %s',\n"
                "                 __name__, len(self._records), filename)\n"
                "        return len(self._records)\n"
                "\n"
                "    def save(self, filename: str) -> int:\n"
                "        \"\"\"Persist current records to *filename* under *data_dir*.\"\"\"\n"
                "        path = str(self.data_dir / filename)\n"
                "        n = write_jsonl(self._records, path)\n"
                "        log.info('[%s] Saved %d records to %s', __name__, n, filename)\n"
                "        return n\n"
                "\n"
                "    def filter(self, **kwargs: Any) -> List[Dict[str, Any]]:\n"
                "        \"\"\"Return records where every key=value pair matches.\"\"\"\n"
                "        result = self._records\n"
                "        for key, val in kwargs.items():\n"
                "            result = [r for r in result if r.get(key) == val]\n"
                "        return result\n"
                "\n"
                "    def run(self) -> Dict[str, Any]:\n"
                "        \"\"\"Return dataset statistics.\"\"\"\n"
                "        keys: set = set()\n"
                "        for r in self._records:\n"
                "            keys.update(r.keys())\n"
                "        return {\n"
                "            'records': len(self._records),\n"
                "            'fields': sorted(keys),\n"
                "            'data_dir': str(self.data_dir),\n"
                "        }"
            ),
        },
        "learning": {
            "imports": "import math\nimport random\nfrom collections import deque",
            "constants": (
                "LEARNING_RATE = 0.01\n"
                "DISCOUNT_FACTOR = 0.95\n"
                "EPSILON = 0.1\n"
                "MAX_MEMORY = 500"
            ),
            "functions": (
                "def softmax(logits: List[float]) -> List[float]:\n"
                "    \"\"\"Compute softmax probabilities from raw logits.\"\"\"\n"
                "    max_l = max(logits)\n"
                "    exps = [math.exp(x - max_l) for x in logits]\n"
                "    s = sum(exps)\n"
                "    return [e / s for e in exps]\n"
                "\n"
                "def epsilon_greedy(q_values: List[float], epsilon: float = EPSILON\n"
                "                   ) -> int:\n"
                "    \"\"\"Select an action using ε-greedy policy; returns action index.\"\"\"\n"
                "    if random.random() < epsilon:\n"
                "        return random.randrange(len(q_values))\n"
                "    return q_values.index(max(q_values))\n"
                "\n"
                "def td_update(q: float, reward: float, next_q: float,\n"
                "              lr: float = LEARNING_RATE,\n"
                "              gamma: float = DISCOUNT_FACTOR) -> float:\n"
                "    \"\"\"Apply a single temporal-difference Q-value update.\"\"\"\n"
                "    return q + lr * (reward + gamma * next_q - q)"
            ),
            "class_body": (
                "    def __init__(self, n_actions: int = 4) -> None:\n"
                "        self.n_actions = n_actions\n"
                "        self.q_table: Dict[str, List[float]] = {}\n"
                "        self.memory: deque = deque(maxlen=MAX_MEMORY)\n"
                "        self._steps = 0\n"
                "        log.debug('[%s] Initialized (actions=%d)', __name__, n_actions)\n"
                "\n"
                "    def observe(self, state: str, action: int, reward: float,\n"
                "                next_state: str) -> None:\n"
                "        \"\"\"Store a (state, action, reward, next_state) experience.\"\"\"\n"
                "        self.memory.append((state, action, reward, next_state))\n"
                "        self._steps += 1\n"
                "\n"
                "    def act(self, state: str) -> int:\n"
                "        \"\"\"Choose an action for *state* using ε-greedy policy.\"\"\"\n"
                "        q_vals = self.q_table.setdefault(\n"
                "            state, [0.0] * self.n_actions\n"
                "        )\n"
                "        return epsilon_greedy(q_vals)\n"
                "\n"
                "    def train_step(self) -> Optional[float]:\n"
                "        \"\"\"Sample one experience and apply a TD update; return the loss.\"\"\"\n"
                "        if not self.memory:\n"
                "            return None\n"
                "        s, a, r, ns = random.choice(self.memory)\n"
                "        q = self.q_table.setdefault(s,  [0.0] * self.n_actions)[a]\n"
                "        next_q = max(self.q_table.get(ns, [0.0] * self.n_actions))\n"
                "        updated = td_update(q, r, next_q)\n"
                "        self.q_table[s][a] = updated\n"
                "        return abs(updated - q)\n"
                "\n"
                "    def run(self) -> Dict[str, Any]:\n"
                "        \"\"\"Return learning statistics.\"\"\"\n"
                "        return {\n"
                "            'states': len(self.q_table),\n"
                "            'memory': len(self.memory),\n"
                "            'steps': self._steps,\n"
                "            'learning_rate': LEARNING_RATE,\n"
                "        }"
            ),
        },
        "binary": {
            "imports": "import struct\nimport os\nfrom pathlib import Path",
            "constants": (
                "ELF_MAGIC = b'\\x7fELF'\n"
                "PE_MAGIC  = b'MZ'\n"
                "DEX_MAGIC = b'dex\\n'\n"
                "WORD_SIZE = 4"
            ),
            "functions": (
                "def hexdump(data: bytes, width: int = 16) -> str:\n"
                "    \"\"\"Return a formatted hex dump of *data* (like xxd).\"\"\"\n"
                "    lines: List[str] = []\n"
                "    for i in range(0, len(data), width):\n"
                "        chunk = data[i:i + width]\n"
                "        hex_part = ' '.join(f'{b:02x}' for b in chunk).ljust(width * 3)\n"
                "        asc_part = ''.join(chr(b) if 0x20 <= b < 0x7f else '.' for b in chunk)\n"
                "        lines.append(f'{i:08x}  {hex_part}  |{asc_part}|')\n"
                "    return '\\n'.join(lines)\n"
                "\n"
                "def detect_format(data: bytes) -> str:\n"
                "    \"\"\"Heuristically identify a binary format from its magic bytes.\"\"\"\n"
                "    if data[:4] == ELF_MAGIC:\n"
                "        return 'ELF'\n"
                "    if data[:2] == PE_MAGIC:\n"
                "        return 'PE/MZ'\n"
                "    if data[:4] == DEX_MAGIC:\n"
                "        return 'DEX'\n"
                "    if data[:4] in (b'\\xcf\\xfa\\xed\\xfe', b'\\xce\\xfa\\xed\\xfe'):\n"
                "        return 'Mach-O'\n"
                "    return 'unknown'"
            ),
            "class_body": (
                "    def __init__(self) -> None:\n"
                "        self._files_inspected: int = 0\n"
                "        log.debug('[%s] Initialized', __name__)\n"
                "\n"
                "    def inspect(self, path: str) -> Dict[str, Any]:\n"
                "        \"\"\"Read *path* and return format, size, and first-256-byte hexdump.\"\"\"\n"
                "        data = Path(path).read_bytes()\n"
                "        fmt = detect_format(data)\n"
                "        self._files_inspected += 1\n"
                "        return {\n"
                "            'path': path,\n"
                "            'format': fmt,\n"
                "            'size': len(data),\n"
                "            'hexdump': hexdump(data[:256]),\n"
                "        }\n"
                "\n"
                "    def bytes_to_int(self, data: bytes, signed: bool = False) -> int:\n"
                "        \"\"\"Interpret *data* as a little-endian integer.\"\"\"\n"
                "        return int.from_bytes(data, byteorder='little', signed=signed)\n"
                "\n"
                "    def run(self) -> Dict[str, Any]:\n"
                "        \"\"\"Return inspection statistics.\"\"\"\n"
                "        return {\n"
                "            'files_inspected': self._files_inspected,\n"
                "            'formats_known': ['ELF', 'PE/MZ', 'DEX', 'Mach-O'],\n"
                "        }"
            ),
        },
    }

    # Map of topic keywords to a snippet key in _PYTHON_TOPIC_SNIPPETS
    _TOPIC_KEYWORD_MAP: List[tuple] = [
        # keyword substring → snippet key
        ("nlp",         "nlp"),
        ("natural lang", "nlp"),
        ("tokeniz",     "nlp"),
        ("spacy",       "nlp"),
        ("nltk",        "nlp"),
        ("text gen",    "nlp"),
        ("language mod","nlp"),
        ("chat",        "chat"),
        ("completion",  "chat"),
        ("conversation","chat"),
        ("dialogue",    "chat"),
        ("llm",         "chat"),
        ("prompt",      "chat"),
        ("api",         "api"),
        ("http",        "api"),
        ("request",     "api"),
        ("rest",        "api"),
        ("client",      "api"),
        ("memory",      "memory"),
        ("cache",       "memory"),
        ("storage",     "memory"),
        ("store",       "memory"),
        ("reasoning",   "reasoning"),
        ("logic",       "reasoning"),
        ("inference",   "reasoning"),
        ("chain of",    "reasoning"),
        ("knowledge gr","reasoning"),
        ("network",     "networking"),
        ("socket",      "networking"),
        ("tcp",         "networking"),
        ("ip ",         "networking"),
        ("protocol",    "networking"),
        ("data",        "data"),
        ("dataset",     "data"),
        ("json",        "data"),
        ("csv",         "data"),
        ("learning",    "learning"),
        ("reinforcement","learning"),
        ("train",       "learning"),
        ("binary",      "binary"),
        ("hex",         "binary"),
        ("elf",         "binary"),
        ("dex",         "binary"),
        ("firmware",    "binary"),
        ("kernel",      "binary"),
    ]

    def _select_snippet_key(self, topic: str, research_text: str) -> str:
        """Pick the best snippet key for *topic* + *research_text*."""
        combined = (topic + " " + research_text).lower()
        for keyword, key in self._TOPIC_KEYWORD_MAP:
            if keyword in combined:
                return key
        return "data"  # fallback: generic data-processing module

    def generate_from_research(
        self,
        language: str,
        topic: str,
        research_text: str,
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate **real, functional** code informed by *research_text*.

        Unlike :meth:`generate` which fills a static template with ``pass``
        bodies, this method:

        1. Analyses *topic* and *research_text* to pick the best code pattern.
        2. Builds a complete, working module with real constants, utility
           functions, and a class whose methods perform genuine computation.
        3. Saves the result to the builds directory.

        Args:
            language:      Target language (e.g. ``"python"``, ``"rust"``).
            topic:         Human-readable topic from autonomous research.
            research_text: Raw research snippet(s) collected by the ALE.
            name:          Optional module/file base-name.  Auto-derived when
                           omitted.

        Returns:
            Same ``{"code", "language", "template", "success", "error"}``
            dict as :meth:`generate`, plus ``"snippet_key"`` indicating which
            code pattern was applied.
        """
        lang = language.lower()
        result: Dict[str, Any] = {
            "language": lang,
            "template": "research",
            "success": False,
            "code": "",
            "error": None,
            "snippet_key": "generic",
        }

        # Derive a safe module name from topic if not provided
        if not name:
            safe_name = re.sub(r"[^a-z0-9]+", "_", topic.lower())[:_MAX_MODULE_NAME_LEN].strip("_")
            name = f"ale_{lang}_{safe_name}" if safe_name else f"ale_{lang}_module"

        classname = "".join(
            w.capitalize() for w in re.split(r"[_\s]+", name) if w
        )

        # Track the derived name so callers can use it (e.g. for save_to_builds)
        result["name"] = name

        try:
            if lang in ("python", "python3"):
                code = self._generate_python_from_research(
                    name, classname, topic, research_text
                )
            elif lang in ("rust",):
                code = self._generate_rust_from_research(
                    name, classname, topic, research_text
                )
            elif lang in ("go",):
                code = self._generate_go_from_research(
                    name, classname, topic, research_text
                )
            elif lang in ("javascript", "js", "typescript", "ts"):
                code = self._generate_js_from_research(
                    name, classname, topic, research_text, lang
                )
            elif lang in ("bash", "sh"):
                code = self._generate_bash_from_research(
                    name, topic, research_text
                )
            else:
                # Fall back to template-based generation for other languages
                fallback = self.generate_with_validation(
                    lang, "module",
                    name=name,
                    classname=classname,
                    docstring=f"{topic}: {research_text[:120]}",
                )
                return {**fallback, "snippet_key": "template_fallback"}

            code = self.ensure_structure(lang, code)
            snippet_key = self._select_snippet_key(topic, research_text)
            result.update({
                "success": bool(code.strip()),
                "code": code,
                "snippet_key": snippet_key,
            })
            if result["success"]:
                self._stats["generated"] += 1
                self._store(lang, "research", code, name)
                log.info(
                    "[CodeGenerator] Research-driven %s module '%s' (%d chars) — pattern: %s",
                    lang, name, len(code), snippet_key,
                )
        except Exception as exc:
            result["error"] = str(exc)
            log.error("[CodeGenerator] generate_from_research failed: %s", exc)

        return result

    # ── language-specific research-driven builders ─────────────────────────

    def _generate_python_from_research(
        self,
        name: str,
        classname: str,
        topic: str,
        research_text: str,
    ) -> str:
        """Build a complete Python module from research context."""
        key = self._select_snippet_key(topic, research_text)
        snippet = self._PYTHON_TOPIC_SNIPPETS.get(key, self._PYTHON_TOPIC_SNIPPETS["data"])

        # Trim research text for embedding in the docstring
        summary = research_text[:_MAX_RESEARCH_SUMMARY_LEN].replace('"""', "'''").strip()

        lines: List[str] = [
            "#!/usr/bin/env python3",
            f'"""{name} — {topic}',
            "",
            "Auto-generated by Niblit ALE from autonomous research.",
            f"Research summary:",
            *[f"  {ln}" for ln in textwrap.wrap(summary, width=76)],
            '"""',
            "",
            snippet["imports"],
            "import logging",
            "from typing import Any, Dict, List, Optional",
            "",
            f'log = logging.getLogger("{name}")',
            "",
            "# ── constants ────────────────────────────────────────────────────────",
            snippet["constants"],
            "",
            "",
            "# ── utility functions ────────────────────────────────────────────────",
            snippet["functions"],
            "",
            "",
            f"class {classname}:",
            f'    """{classname} — {topic}"""',
            "",
            snippet["class_body"],
            "",
            "",
            'if __name__ == "__main__":',
            "    import logging as _logging",
            "    _logging.basicConfig(level=_logging.INFO)",
            f"    obj = {classname}()",
            "    print(obj.run())",
        ]
        return "\n".join(lines)

    def _generate_rust_from_research(
        self,
        name: str,
        classname: str,
        topic: str,
        research_text: str,
    ) -> str:
        """Build a Rust module from research context."""
        summary = textwrap.shorten(
            research_text.replace('"', "'"), width=_RESEARCH_SUMMARY_WIDTH, placeholder="..."
        )
        snake = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        struct_name = classname if classname else "AleModule"

        code_lines: List[str] = [
            f"//! {snake} — {topic}",
            "//!",
            f"//! Auto-generated by Niblit ALE.",
            f"//! Research: {summary}",
            "",
            "use std::collections::HashMap;",
            "use std::error::Error;",
            "use std::time::{SystemTime, UNIX_EPOCH};",
            "",
            f"/// {struct_name} implements: {topic}",
            f"pub struct {struct_name} {{",
            "    name: String,",
            "    data: HashMap<String, String>,",
            "    created_at: u64,",
            "}",
            "",
            f"impl {struct_name} {{",
            "    /// Create a new instance.",
            "    pub fn new(name: impl Into<String>) -> Self {",
            "        let ts = SystemTime::now()",
            "            .duration_since(UNIX_EPOCH)",
            "            .map(|d| d.as_secs())",
            "            .unwrap_or(0);",
            "        Self {",
            "            name: name.into(),",
            "            data: HashMap::new(),",
            "            created_at: ts,",
            "        }",
            "    }",
            "",
            "    /// Store a key-value pair.",
            "    pub fn set(&mut self, key: impl Into<String>, value: impl Into<String>) {",
            "        self.data.insert(key.into(), value.into());",
            "    }",
            "",
            "    /// Retrieve a value by key.",
            "    pub fn get(&self, key: &str) -> Option<&str> {",
            "        self.data.get(key).map(String::as_str)",
            "    }",
            "",
            "    /// Return basic statistics as a formatted string.",
            "    pub fn stats(&self) -> String {",
            "        format!(\"{}: {} entries, created={}\",",
            "                self.name, self.data.len(), self.created_at)",
            "    }",
            "}",
            "",
            "fn main() -> Result<(), Box<dyn Error>> {",
            f'    let mut m = {struct_name}::new("{snake}");',
            '    m.set("topic", "' + topic[:60].replace('"', "'") + '");',
            "    println!(\"{}\", m.stats());",
            "    Ok(())",
            "}",
            "",
            "#[cfg(test)]",
            "mod tests {",
            "    use super::*;",
            "",
            "    #[test]",
            "    fn test_set_get() {",
            f'        let mut m = {struct_name}::new("test");',
            '        m.set("key", "value");',
            '        assert_eq!(m.get("key"), Some("value"));',
            "    }",
            "}",
        ]
        return "\n".join(code_lines)

    def _generate_go_from_research(
        self,
        name: str,
        classname: str,
        topic: str,
        research_text: str,
    ) -> str:
        """Build a Go package from research context."""
        summary = textwrap.shorten(
            research_text.replace('"', "'"), width=_RESEARCH_SUMMARY_WIDTH, placeholder="..."
        )
        pkg = re.sub(r"[^a-z0-9]+", "", name.lower())[:_MAX_GO_PACKAGE_NAME_LEN] or "alemodule"
        struct_name = classname if classname else "AleModule"

        code_lines: List[str] = [
            f"// Package {pkg} — {topic}",
            "//",
            "// Auto-generated by Niblit ALE.",
            f"// Research: {summary}",
            f"package {pkg}",
            "",
            "import (",
            '    "fmt"',
            '    "time"',
            ")",
            "",
            f"// {struct_name} implements {topic}.",
            f"type {struct_name} struct {{",
            "    Name      string",
            "    Data      map[string]string",
            "    CreatedAt time.Time",
            "}",
            "",
            f"// New{struct_name} creates a new instance.",
            f"func New{struct_name}(name string) *{struct_name} {{",
            f"    return &{struct_name}{{",
            "        Name:      name,",
            "        Data:      make(map[string]string),",
            "        CreatedAt: time.Now(),",
            "    }",
            "}",
            "",
            "// Set stores a key-value pair.",
            f"func (m *{struct_name}) Set(key, value string) {{",
            "    m.Data[key] = value",
            "}",
            "",
            "// Get retrieves a value; returns empty string if not found.",
            f"func (m *{struct_name}) Get(key string) string {{",
            "    return m.Data[key]",
            "}",
            "",
            "// Stats returns a summary string.",
            f"func (m *{struct_name}) Stats() string {{",
            '    return fmt.Sprintf("%s: %d entries, age=%s",',
            "        m.Name, len(m.Data), time.Since(m.CreatedAt).Round(time.Second))",
            "}",
            "",
            "func main() {",
            f'    m := New{struct_name}("{pkg}")',
            '    m.Set("topic", "' + topic[:60].replace('"', "'") + '")',
            "    fmt.Println(m.Stats())",
            "}",
        ]
        return "\n".join(code_lines)

    def _generate_js_from_research(
        self,
        name: str,
        classname: str,
        topic: str,
        research_text: str,
        lang: str = "javascript",
    ) -> str:
        """Build a JavaScript/TypeScript module from research context."""
        summary = textwrap.shorten(
            research_text.replace("`", "'"), width=_RESEARCH_SUMMARY_WIDTH, placeholder="..."
        )
        is_ts = lang in ("typescript", "ts")

        if is_ts:
            type_annotation = ": Record<string, unknown>"
            constructor_type = ""
            method_ret = ": Record<string, unknown>"
        else:
            type_annotation = ""
            constructor_type = ""
            method_ret = ""

        code_lines: List[str] = [
            "'use strict';",
            "",
            f"/**",
            f" * {name} — {topic}",
            f" *",
            f" * Auto-generated by Niblit ALE.",
            f" * Research: {summary}",
            f" */",
            "",
            f"class {classname} {{",
            f"  constructor(name{constructor_type}) {{",
            "    this.name = name || '" + name + "';",
            "    this.data = {};",
            "    this.createdAt = Date.now();",
            "  }",
            "",
            f"  set(key, value){method_ret} {{",
            "    this.data[key] = value;",
            "    return this;",
            "  }",
            "",
            f"  get(key){method_ret} {{",
            "    return this.data[key] ?? null;",
            "  }",
            "",
            f"  run(){method_ret} {{",
            "    return {",
            "      name: this.name,",
            "      entries: Object.keys(this.data).length,",
            "      uptime: Date.now() - this.createdAt,",
            "    };",
            "  }",
            "}",
            "",
            f"// Example usage",
            f"const instance = new {classname}('{name}');",
            "instance.set('topic', '" + topic[:60].replace("'", "\\'") + "');",
            "console.log(instance.run());",
            "",
            f"module.exports = {{ {classname} }};",
        ]
        return "\n".join(code_lines)

    def _generate_bash_from_research(
        self,
        name: str,
        topic: str,
        research_text: str,
    ) -> str:
        """Build a Bash script from research context."""
        summary = textwrap.shorten(
            research_text.replace('"', "'"), width=100, placeholder="..."
        )
        snake = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")

        code_lines: List[str] = [
            "#!/usr/bin/env bash",
            "# " + snake + " — " + topic,
            "#",
            "# Auto-generated by Niblit ALE.",
            "# Research: " + summary[:100],
            "set -euo pipefail",
            "",
            '# ── config ───────────────────────────────────────────────────────────',
            f'readonly SCRIPT_NAME="{snake}"',
            f'readonly LOG_FILE="/tmp/${{SCRIPT_NAME}}.log"',
            'readonly TIMESTAMP=$(date +%Y%m%d_%H%M%S)',
            "",
            "# ── logging ──────────────────────────────────────────────────────────",
            'log() { echo "[$(date +%T)] $*" | tee -a "$LOG_FILE"; }',
            'die() { log "ERROR: $*" >&2; exit 1; }',
            "",
            "# ── main ─────────────────────────────────────────────────────────────",
            "main() {",
            '    log "Starting $SCRIPT_NAME at $TIMESTAMP"',
            "",
            "    # Check required commands",
            "    for cmd in grep awk sed; do",
            '        command -v "$cmd" > /dev/null 2>&1 \\',
            '            || die "Required command not found: $cmd"',
            "    done",
            "",
            '    log "All checks passed."',
            '    log "Done."',
            "}",
            "",
            "main \"$@\"",
        ]
        return "\n".join(code_lines)

    # ──────────────────────────────────────────────────────
    # STATS
    # ──────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Return generation statistics."""
        return {
            "stats": self._stats,
            "supported_languages": SUPPORTED_LANGUAGES,
            "total_templates": sum(len(v) for v in _TEMPLATES.values()),
        }

    def _store(self, language: str, template: str, code: str, name: str) -> None:
        """Store generated code snippet in KnowledgeDB."""
        if not self.db:
            return
        key = f"generated_code:{language}:{name}:{int(time.time())}"
        snippet = {"language": language, "template": template, "name": name, "code": code[:500]}
        try:
            if hasattr(self.db, "add_fact"):
                self.db.add_fact(key, str(snippet), ["code", "generated", language])
            elif hasattr(self.db, "store_learning"):
                self.db.store_learning({"key": key, "data": snippet, "ts": time.time()})
            self._stats["stored"] += 1
        except Exception as exc:
            log.debug("[CodeGenerator] Store failed: %s", exc)

    def get_extension(self, language: str) -> str:
        """Return the file extension for a language."""
        return _EXTENSIONS.get(language.lower(), ".txt")


# ──────────────────────────────────────────────────────
# STANDALONE SELF-TEST
# ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import logging as _logging  # pylint: disable=reimported,ungrouped-imports
    _logging.basicConfig(level=_logging.INFO, format="%(message)s")
    print("=== CodeGenerator self-test ===\n")

    gen = CodeGenerator()

    result = gen.generate("python", "module", name="test_module", docstring="Test module.")
    print(f"Generated Python module:\n{result['code'][:200]}...")

    print(gen.list_templates())
    print()
    print(gen.study_language("python"))
    print()
    print("Stats:", gen.get_stats())
    print("CodeGenerator OK")
