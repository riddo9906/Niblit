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
    def out(message):
        if not NiblitIO._quiet:
            print(f"{NiblitIO.timestamp()} {message}")

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
            print(token, end="", flush=flush)
            parts.append(token)
            if delay > 0:
                time.sleep(delay)
        print(end, end="", flush=flush)
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
                print(f"{NiblitIO.timestamp()} {line}", flush=True)
            if delay > 0:
                time.sleep(delay)
            yield line

# Test
if __name__ == "__main__":
    NiblitIO.out("Niblit IO initialized.")
    NiblitIO.stream_out(["Hello", ", ", "world", "!"], delay=0.05)
