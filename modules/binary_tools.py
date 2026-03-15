#!/usr/bin/env python3
"""
BINARY TOOLS MODULE
Read, write, edit, convert, and study binary/hex/dex data.

Features:
- Read/write raw binary files
- Hex-dump display (classic xxd-style)
- Convert between binary, hexadecimal, decimal, and octal representations
- Convert source-code strings / bytes to their binary/hex/dex equivalents
- Basic ELF and DEX (Dalvik) header parsing
- APK inspection helpers (requires zipfile — stdlib only)
- Autonomous study queue: seeds KnowledgeDB with binary-domain topics
"""

import os
import struct
import time
import zipfile
import logging
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("BinaryTools")

# ──────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────

HEX_DUMP_ROW_WIDTH: int = 16

# ELF magic and e_type names
_ELF_MAGIC: bytes = b"\x7fELF"
_ELF_TYPES: Dict[int, str] = {
    0: "ET_NONE",
    1: "ET_REL (relocatable)",
    2: "ET_EXEC (executable)",
    3: "ET_DYN (shared object)",
    4: "ET_CORE (core dump)",
}

# DEX magic prefix
_DEX_MAGIC_PREFIX: bytes = b"dex\n"

# Binary-domain autonomous study topics (seeded into KnowledgeDB)
BINARY_STUDY_TOPICS: List[str] = [
    "ELF binary format and section headers",
    "DEX Dalvik bytecode format",
    "PE32 Windows executable format",
    "Mach-O macOS/iOS binary format",
    "Hexadecimal and binary number systems",
    "Assembly language x86-64 instructions",
    "ARM assembly instruction set",
    "Endianness big-endian vs little-endian",
    "DWARF debug information format",
    "APK structure and smali disassembly",
    "Binary exploitation fundamentals",
    "Code signing and integrity verification",
    "Firmware binary analysis with binwalk",
    "Reverse engineering with Ghidra and radare2",
    "BIOS and UEFI firmware binary layout",
]


# ──────────────────────────────────────────────────────────────────────────────
# FILE I/O
# ──────────────────────────────────────────────────────────────────────────────

def read_binary(path: str) -> Optional[bytes]:
    """Read a file as raw bytes.  Returns None on error."""
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as exc:
        log.error("read_binary: cannot read %s: %s", path, exc)
        return None


def write_binary(path: str, data: bytes) -> bool:
    """Write *data* as raw bytes to *path*.  Returns True on success."""
    try:
        with open(path, "wb") as fh:
            fh.write(data)
        log.info("write_binary: wrote %d bytes to %s", len(data), path)
        return True
    except OSError as exc:
        log.error("write_binary: cannot write %s: %s", path, exc)
        return False


def patch_binary(path: str, offset: int, patch: bytes) -> bool:
    """Overwrite *len(patch)* bytes at *offset* in-place.  Returns True on success."""
    try:
        with open(path, "r+b") as fh:
            fh.seek(offset)
            fh.write(patch)
        log.info("patch_binary: patched %d bytes at offset 0x%x in %s", len(patch), offset, path)
        return True
    except OSError as exc:
        log.error("patch_binary: failed for %s: %s", path, exc)
        return False


# ──────────────────────────────────────────────────────────────────────────────
# DISPLAY / FORMATTING
# ──────────────────────────────────────────────────────────────────────────────

def hexdump(data: bytes, offset: int = 0, max_rows: int = 64) -> str:
    """Return a classic hexdump string for *data*.

    Format::

        00000000  48 65 6c 6c 6f 20 57 6f  72 6c 64 21 0a          |Hello World!.|
    """
    rows: List[str] = []
    for i in range(0, len(data), HEX_DUMP_ROW_WIDTH):
        if len(rows) >= max_rows:
            rows.append(f"... (truncated at {max_rows * HEX_DUMP_ROW_WIDTH} bytes)")
            break
        chunk = data[i: i + HEX_DUMP_ROW_WIDTH]
        hex_left = " ".join(f"{b:02x}" for b in chunk[:8])
        hex_right = " ".join(f"{b:02x}" for b in chunk[8:])
        hex_part = f"{hex_left:<23}  {hex_right:<23}"
        asc_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        rows.append(f"{offset + i:08x}  {hex_part}  |{asc_part}|")
    return "\n".join(rows)


# ──────────────────────────────────────────────────────────────────────────────
# CONVERSION UTILITIES
# ──────────────────────────────────────────────────────────────────────────────

def to_hex(data: bytes) -> str:
    """Convert bytes to a contiguous hex string (e.g. b'AB' → '4142')."""
    return data.hex()


def from_hex(hex_str: str) -> bytes:
    """Convert a hex string (with optional spaces/newlines) back to bytes."""
    cleaned = hex_str.replace(" ", "").replace("\n", "").replace("\r", "")
    return bytes.fromhex(cleaned)


def to_binary_string(data: bytes) -> str:
    """Convert bytes to a space-separated binary string.

    Example: b'A' → '01000001'
    """
    return " ".join(f"{b:08b}" for b in data)


def from_binary_string(bin_str: str) -> bytes:
    """Convert a space-separated binary string back to bytes.

    Example: '01000001' → b'A'
    """
    groups = bin_str.strip().split()
    return bytes(int(g, 2) for g in groups if g)


def int_to_representations(value: int) -> Dict[str, str]:
    """Return decimal *value* in binary, hex, octal, and decimal.

    Example::

        >>> int_to_representations(255)
        {'decimal': '255', 'hex': '0xFF', 'binary': '0b11111111', 'octal': '0o377'}
    """
    return {
        "decimal": str(value),
        "hex": hex(value),
        "binary": bin(value),
        "octal": oct(value),
    }


def string_to_hex(text: str, encoding: str = "utf-8") -> str:
    """Encode *text* and return as a hex string."""
    return text.encode(encoding).hex()


def string_to_binary(text: str, encoding: str = "utf-8") -> str:
    """Encode *text* and return as a binary string."""
    return to_binary_string(text.encode(encoding))


def code_to_hex(source_code: str, encoding: str = "utf-8") -> Dict[str, str]:
    """Convert source *code* (any language) to its hex and binary representation.

    Returns a dict with 'hex', 'binary', 'length_bytes', and 'encoding'.
    """
    raw = source_code.encode(encoding)
    return {
        "hex": raw.hex(),
        "binary": to_binary_string(raw),
        "length_bytes": str(len(raw)),
        "encoding": encoding,
    }


# ──────────────────────────────────────────────────────────────────────────────
# ELF BINARY ANALYSIS
# ──────────────────────────────────────────────────────────────────────────────

def parse_elf_header(data: bytes) -> Dict[str, Any]:
    """Parse a minimal ELF header from raw *data*.

    Returns a dict with key ELF fields or an 'error' key on failure.
    """
    if len(data) < 64:
        return {"error": "File too small to be a valid ELF"}
    if data[:4] != _ELF_MAGIC:
        return {"error": "Not an ELF file (magic mismatch)"}

    ei_class = data[4]  # 1=32-bit, 2=64-bit
    ei_data = data[5]   # 1=LE, 2=BE
    endian = "<" if ei_data == 1 else ">"
    bits = 32 if ei_class == 1 else 64

    if bits == 64:
        fmt = f"{endian}HHIQQQIHHHHHH"
        size = struct.calcsize(fmt)
        if len(data) < size + 16:
            return {"error": "ELF64 header truncated"}
        fields = struct.unpack(fmt, data[16: 16 + size])
        e_type, e_machine = fields[0], fields[1]
    else:
        fmt = f"{endian}HHIIIIIHHHHHH"
        size = struct.calcsize(fmt)
        if len(data) < size + 16:
            return {"error": "ELF32 header truncated"}
        fields = struct.unpack(fmt, data[16: 16 + size])
        e_type, e_machine = fields[0], fields[1]

    return {
        "magic": data[:4].hex(),
        "class": f"ELF{bits}",
        "endianness": "little-endian" if ei_data == 1 else "big-endian",
        "type": _ELF_TYPES.get(e_type, f"unknown ({e_type})"),
        "machine": f"0x{e_machine:04x}",
        "valid": True,
    }


def analyze_elf(path: str) -> Dict[str, Any]:
    """Read *path* and return ELF header analysis."""
    data = read_binary(path)
    if data is None:
        return {"error": f"Cannot read file: {path}"}
    return parse_elf_header(data)


# ──────────────────────────────────────────────────────────────────────────────
# DEX (DALVIK) ANALYSIS
# ──────────────────────────────────────────────────────────────────────────────

def parse_dex_header(data: bytes) -> Dict[str, Any]:
    """Parse a minimal DEX header from raw *data*.

    DEX header layout (first 112 bytes):
      0x00  8 bytes  magic ("dex\\n035\\0")
      0x08  4 bytes  checksum (Adler-32)
      0x0c  20 bytes SHA-1 signature
      0x20  4 bytes  file_size
      0x24  4 bytes  header_size (should be 0x70)
      ...
    """
    if len(data) < 112:
        return {"error": "File too small to be a valid DEX"}
    if data[:4] != _DEX_MAGIC_PREFIX:
        return {"error": "Not a DEX file (magic mismatch)"}

    version = data[4:8].rstrip(b"\x00").decode("ascii", errors="replace")
    file_size = struct.unpack_from("<I", data, 0x20)[0]
    header_size = struct.unpack_from("<I", data, 0x24)[0]
    string_ids_size = struct.unpack_from("<I", data, 0x38)[0]
    type_ids_size = struct.unpack_from("<I", data, 0x40)[0]
    method_ids_size = struct.unpack_from("<I", data, 0x50)[0]
    class_defs_size = struct.unpack_from("<I", data, 0x60)[0]

    return {
        "magic": data[:8].rstrip(b"\x00").decode("ascii", errors="replace"),
        "version": version,
        "file_size": file_size,
        "header_size": header_size,
        "string_ids_size": string_ids_size,
        "type_ids_size": type_ids_size,
        "method_ids_size": method_ids_size,
        "class_defs_size": class_defs_size,
        "valid": True,
    }


def analyze_dex(path: str) -> Dict[str, Any]:
    """Read *path* and return DEX header analysis."""
    data = read_binary(path)
    if data is None:
        return {"error": f"Cannot read file: {path}"}
    return parse_dex_header(data)


# ──────────────────────────────────────────────────────────────────────────────
# APK INSPECTION
# ──────────────────────────────────────────────────────────────────────────────

def inspect_apk(path: str) -> Dict[str, Any]:
    """Return a summary of an APK (Android Package) file.

    APKs are ZIP archives containing:
      - classes.dex  (Dalvik bytecode)
      - AndroidManifest.xml  (binary XML)
      - res/  (resources)
      - META-INF/  (signature)
    """
    result: Dict[str, Any] = {
        "path": path,
        "valid": False,
        "entries": [],
        "has_dex": False,
        "has_manifest": False,
        "dex_files": [],
        "error": None,
    }
    try:
        with zipfile.ZipFile(path, "r") as zf:
            result["valid"] = True
            entries = zf.namelist()
            result["entries"] = entries[:50]  # cap at 50
            result["total_entries"] = len(entries)
            dex_files = [e for e in entries if e.endswith(".dex")]
            result["dex_files"] = dex_files
            result["has_dex"] = bool(dex_files)
            result["has_manifest"] = "AndroidManifest.xml" in entries
    except zipfile.BadZipFile as exc:
        result["error"] = f"Not a valid ZIP/APK: {exc}"
    except OSError as exc:
        result["error"] = f"Cannot open file: {exc}"
    return result


# ──────────────────────────────────────────────────────────────────────────────
# BINARY STUDIER — autonomous knowledge seeding
# ──────────────────────────────────────────────────────────────────────────────

class BinaryStudier:
    """Autonomous binary-domain study helper.

    Seeds KnowledgeDB with binary/hex/dex topics so that the Autonomous
    Learning Engine can research and reflect on them.
    """

    def __init__(self, db: Any = None):
        self.db = db
        self._topics_seeded: int = 0

    def seed_topics(self) -> int:
        """Queue all binary study topics into KnowledgeDB.

        Returns the number of topics queued.
        """
        if not self.db:
            log.debug("[BinaryStudier] No DB — topics not queued")
            return 0

        queued = 0
        for topic in BINARY_STUDY_TOPICS:
            try:
                if hasattr(self.db, "queue_learning"):
                    self.db.queue_learning(topic)
                    queued += 1
                elif hasattr(self.db, "add_fact"):
                    self.db.add_fact(
                        f"binary_study_topic:{int(time.time())}",
                        topic,
                        tags=["binary", "study", "autonomous"],
                    )
                    queued += 1
            except Exception as exc:
                log.debug("[BinaryStudier] Failed to queue '%s': %s", topic, exc)

        self._topics_seeded += queued
        log.info("[BinaryStudier] Seeded %d binary study topics", queued)
        return queued

    def get_topic_list(self) -> List[str]:
        """Return the list of binary study topics."""
        return list(BINARY_STUDY_TOPICS)

    def study_topic(self, topic: str) -> str:
        """Return a brief study note for *topic* (offline, no internet needed)."""
        quick_notes: Dict[str, str] = {
            "elf": (
                "ELF (Executable and Linkable Format) is the standard binary format "
                "for Linux/Unix. Key sections: .text (code), .data (init data), "
                ".bss (zero-init data), .rodata (read-only), .symtab (symbols)."
            ),
            "dex": (
                "DEX (Dalvik EXecutable) is Android's bytecode format. "
                "ART (Android Runtime) compiles DEX to native code via AOT or JIT. "
                "Use baksmali to disassemble DEX to smali."
            ),
            "pe": (
                "PE (Portable Executable) is the binary format for Windows (.exe/.dll). "
                "Consists of DOS header, NT header, section headers, and sections."
            ),
            "hex": (
                "Hexadecimal (base-16) is the standard notation for binary data. "
                "Each hex digit represents 4 bits (a nibble). "
                "Use xxd, hexdump, or Python bytes.hex() to inspect files."
            ),
            "binary": (
                "Binary (base-2) is the lowest-level representation of data. "
                "Every byte is 8 bits. Use struct module in Python for structured I/O."
            ),
            "endianness": (
                "Little-endian stores the least-significant byte first (x86). "
                "Big-endian stores the most-significant byte first (network order). "
                "Use socket.htons/ntohl or struct endian flags to convert."
            ),
        }
        key = topic.lower().split()[0]
        note = quick_notes.get(key)
        if note:
            return f"📖 **Binary Study — {topic}:**\n\n  {note}"
        return f"[No offline note for '{topic}'. Queue it for internet research.]"

    def analyze_file(self, path: str) -> Dict[str, Any]:
        """Auto-detect and analyse a binary file (ELF, DEX, APK, or raw hex dump)."""
        data = read_binary(path)
        if data is None:
            return {"error": f"Cannot read: {path}"}

        result: Dict[str, Any] = {"path": path, "size_bytes": len(data)}

        if data[:4] == _ELF_MAGIC:
            result["format"] = "ELF"
            result["header"] = parse_elf_header(data)
        elif data[:4] == _DEX_MAGIC_PREFIX:
            result["format"] = "DEX"
            result["header"] = parse_dex_header(data)
        elif data[:2] in (b"PK", b"MZ"):
            # ZIP (APK) or PE
            if data[:2] == b"PK":
                result["format"] = "ZIP/APK"
                result["apk_info"] = inspect_apk(path)
            else:
                result["format"] = "PE"
                result["note"] = "PE parsing not yet implemented"
        else:
            result["format"] = "unknown"
            result["hex_preview"] = hexdump(data[:64])

        return result

    def get_stats(self) -> Dict[str, Any]:
        """Return stats for this studier instance."""
        return {
            "topics_available": len(BINARY_STUDY_TOPICS),
            "topics_seeded": self._topics_seeded,
        }


# ──────────────────────────────────────────────────────────────────────────────
# STANDALONE SELF-TEST
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(message)s")
    print("=== BinaryTools self-test ===\n")

    # Round-trip bytes → hex → bytes
    original = b"Hello, Niblit binary world!\n"
    h = to_hex(original)
    assert from_hex(h) == original
    print(f"✅ hex round-trip: {h[:20]}...")

    # Round-trip bytes → binary string → bytes
    b_str = to_binary_string(b"\x41\x42")
    assert from_binary_string(b_str) == b"\x41\x42"
    print(f"✅ binary string round-trip: {b_str}")

    # int representations
    reps = int_to_representations(255)
    assert reps["hex"] == "0xff"
    assert reps["binary"] == "0b11111111"
    print(f"✅ int representations: {reps}")

    # hexdump
    dump = hexdump(original)
    assert "Hello" in dump
    print(f"✅ hexdump OK (first row):\n  {dump.splitlines()[0]}")

    # code_to_hex
    conv = code_to_hex("print('hi')")
    assert len(conv["hex"]) > 0
    print(f"✅ code_to_hex: {conv['length_bytes']} bytes")

    # BinaryStudier
    studier = BinaryStudier()
    note = studier.study_topic("elf")
    assert "ELF" in note
    print(f"✅ BinaryStudier.study_topic: {note[:60]}...")
    print(f"✅ BinaryStudier.get_stats: {studier.get_stats()}")

    print("\nBinaryTools OK")
