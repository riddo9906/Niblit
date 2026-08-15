#!/usr/bin/env python3
# Niblit I/O Interface

import sys
import time
from datetime import datetime
from typing import Generator, Iterable, Optional

class NiblitIO:
    # When True, out() is silenced (set via 'loop hide' / 'loops hide' command)
    _quiet: bool = False

    @staticmethod
    def timestamp():
        return datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")

    @staticmethod
    def out(
        message,
        *,
        flush: bool = False,
        end: str = "\n",
        sep: str = " ",
        file=None,
        **kwargs,
    ):
        """Print a timestamped message to stdout.

        Compatible with Python's built-in print() interface:
        - flush: Whether to flush stdout after writing (default: False)
        - end: String appended after the message (default: "\\\\n")
        - sep: Separator between arguments (default: " ")
        - file: Destination stream (default: None = stdout)
        - **kwargs: Ignored to support future extensions

        All keyword arguments are optional to maintain backward compatibility.
        Unicode characters that cannot be encoded are replaced with '?' or removed
        to prevent UnicodeEncodeError on Windows consoles.
        """
        if NiblitIO._quiet:
            return
        # Build the full message with timestamp
        full_message = f"{NiblitIO.timestamp()} {message}"
        # Handle encoding issues on Windows console (cp1252) gracefully
        try:
            print(full_message, end=end, file=file, flush=flush)
        except UnicodeEncodeError:
            # Replace unencodable characters with '?' or remove them
            safe_message = full_message.encode("utf-8", errors="replace").decode("latin-1", errors="replace")
            print(safe_message, end=end, file=file, flush=flush, **kwargs)
        # Allow for potential future keyword arguments without raising

    @staticmethod
    def error(message):
        print(f"{NiblitIO.timestamp()} ERROR: {message}", file=sys.stderr)

    @staticmethod
    def prompt(msg="> "):
        try:
            return input(msg)
        except Exception:
            return None

    # ── Streaming output (vLLM-inspired) ─────────────────────────────────────

    @staticmethod
    def stream_out(
        tokens: Iterable[str],
        *,
        delay: float = 0.0,
        end: str = "\n",
        flush: bool = True,
    ) -> str:
        """Print *tokens* one-by-one to stdout, simulating streaming output.

        Inspired by vLLM's streaming inference API — each token (or chunk) is
        written immediately so the user sees the response grow in real time
        rather than waiting for the full text to be assembled.

        Args:
            tokens: Iterable of string chunks to print sequentially.
            delay:  Optional pause (seconds) between tokens (default: 0 — no
                    artificial throttle; set e.g. ``0.02`` for a typewriter
                    effect in demos).
            end:    String written after the last token (default: ``"\\n"``).
            flush:  Whether to ``flush`` stdout after each token.

        Returns:
            The full concatenated text that was streamed.
        """
        if NiblitIO._quiet:
            return "".join(tokens)

        parts = []
        for token in tokens:
            try:
                print(token, end="", flush=flush)
            except UnicodeEncodeError:
                safe_token = token.encode("utf-8", errors="replace").decode("latin-1", errors="replace")
                print(safe_token, end="", flush=flush)
            parts.append(token)
            if delay > 0:
                time.sleep(delay)
        try:
            print(end, end="", flush=flush)
        except UnicodeEncodeError:
            safe_end = end.encode("utf-8", errors="replace").decode("latin-1", errors="replace")
            print(safe_end, end="", flush=flush)
        return "".join(parts)

    @staticmethod
    def stream_lines(
        text: str,
        *,
        delay: float = 0.0,
    ) -> Generator[str, None, None]:
        """Yield and print each line of *text* progressively.

        Useful for streaming multi-line LLM responses line-by-line.

        Args:
            text:  The full text to stream.
            delay: Optional pause (seconds) between lines.

        Yields:
            Each line of *text* (without the trailing newline).
        """
        for line in text.splitlines():
            if not NiblitIO._quiet:
                try:
                    print(f"{NiblitIO.timestamp()} {line}", flush=True)
                except UnicodeEncodeError:
                    safe_line = line.encode("utf-8", errors="replace").decode("latin-1", errors="replace")
                    print(f"{NiblitIO.timestamp()} {safe_line}", flush=True)
            if delay > 0:
                time.sleep(delay)
            yield line

# Test
if __name__ == "__main__":
    NiblitIO.out("Niblit IO initialized.")
    NiblitIO.stream_out(["Hello", ", ", "world", "!"], delay=0.05)
