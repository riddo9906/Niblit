"""Spaced-retrieval scheduling primitives for learned skills, not fact truth."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def schedule_review(*, quality: int, repetitions: int = 0,
                    interval_days: int = 0, ease_factor: float = 2.5,
                    reviewed_at: datetime | None = None) -> dict:
    """SM-2-style bounded review schedule; quality is 0 (failed) to 5 (easy)."""
    if isinstance(quality, bool) or not isinstance(quality, int) or not 0 <= quality <= 5:
        raise ValueError("quality must be an integer from 0 to 5")
    if repetitions < 0 or interval_days < 0 or not 1.3 <= ease_factor <= 3.0:
        raise ValueError("invalid review history")
    now = reviewed_at or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("review timestamp must be timezone-aware")
    if quality < 3:
        next_repetitions, next_interval = 0, 1
    else:
        next_repetitions = repetitions + 1
        if next_repetitions == 1:
            next_interval = 1
        elif next_repetitions == 2:
            next_interval = 6
        else:
            next_interval = max(1, round(max(1, interval_days) * ease_factor))
    delta = 5 - quality
    next_ease = max(1.3, min(3.0, ease_factor + (0.1 - delta * (0.08 + delta * 0.02))))
    due = now.astimezone(timezone.utc) + timedelta(days=next_interval)
    return {
        "repetitions": next_repetitions,
        "interval_days": next_interval,
        "ease_factor": round(next_ease, 3),
        "next_due_at": due.isoformat(),
        "quality": quality,
        "mastery_signal": "recall_performance_only",
        "does_not_verify_source_facts": True,
    }
