#!/usr/bin/env python3
"""
Niblit Canonical Ingestion Layer
LOCKS ALL INTERACTIONS INTO ONE STRUCTURE
No module should store raw strings anymore.
"""

import time
import re
import logging

log = logging.getLogger("NiblitIngest")

# -------------------------------------------------
# CANONICAL EVENT FORMAT
# -------------------------------------------------

def event(
    speaker: str,
    msg: str,
    intent=None,
    meta=None,
):
    return {
        "ts": int(time.time()),
        "speaker": speaker,
        "msg": msg,
        "intent": intent,
        "meta": meta or {}
    }


# -------------------------------------------------
# RAW TEXT → CANONICAL EVENT
# -------------------------------------------------

USER_PATTERN = re.compile(r'^(user|agent|system)\s*:\s*(.+)$', re.I)

def canonicalize(raw: str, default="user") -> dict:
    """
    Converts ANY raw chat line into canonical structure.
    NEVER store raw strings again.
    """

    raw = raw.strip()

    m = USER_PATTERN.match(raw)

    if m:
        return event(
            speaker=m.group(1).lower(),
            msg=m.group(2).strip()
        )

    return event(
        speaker=default,
        msg=raw
    )


# -------------------------------------------------
# SAFE STORE (UNIVERSAL ENTRYPOINT)
# -------------------------------------------------

def ingest(memory, raw_line, speaker="user"):
    """
    ONLY function the system should call to store interaction.
    """

    e = canonicalize(raw_line, speaker)

    try:
        # supports BOTH memory systems automatically

        if hasattr(memory, "add_event"):
            memory.add_event(e)

        elif hasattr(memory, "log_event"):
            memory.log_event(e)

        elif hasattr(memory, "store"):
            memory.store(e)

        else:
            log.warning("Memory has no supported storage method")

    except Exception as ex:
        log.error(f"INGEST FAILED: {ex}")

    return e


if __name__ == "__main__":
    print('Running ingestion.py')
