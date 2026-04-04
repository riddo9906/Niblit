"""
security_membrane.py — Niblit Defensive Security Membrane
==========================================================
A lightweight, purely defensive security layer that wraps Niblit's own API
surface.  It does NOT target, attack, or interact with any external system;
it only hardens Niblit itself.

Capabilities
------------
* Per-IP / global rate limiting (sliding window)
* Anomaly detection: sudden spike in request volume, oversized payloads,
  repeated failed commands
* Intrusion event log (in-memory + optional KnowledgeDB storage)
* Input sanitization helpers: strip null bytes, control chars, oversized strings
* Request fingerprinting for repeat-offender tracking
* Automatic temporary IP block after threshold breaches

Usage
-----
    from modules.security_membrane import get_security_membrane, SecurityResult

    membrane = get_security_membrane()

    # In a FastAPI route / middleware:
    result = membrane.inspect(ip="1.2.3.4", payload=request_body)
    if not result.allowed:
        return JSONResponse({"error": result.reason}, status_code=429)

    sanitized = membrane.sanitize(payload)

Singleton access via ``get_security_membrane()``.
"""

from __future__ import annotations

import hashlib
import html
import logging
import os
import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ── Tuneable constants ─────────────────────────────────────────────────────
_WINDOW_SECS = int(os.environ.get("NIBLIT_RATE_WINDOW", "60"))
_MAX_REQUESTS_PER_WINDOW = int(os.environ.get("NIBLIT_RATE_LIMIT", "60"))
_BLOCK_DURATION_SECS = int(os.environ.get("NIBLIT_BLOCK_SECS", "300"))
_MAX_PAYLOAD_BYTES = int(os.environ.get("NIBLIT_MAX_PAYLOAD", str(256 * 1024)))  # 256 KB
_ANOMALY_SPIKE_RATIO = float(os.environ.get("NIBLIT_SPIKE_RATIO", "3.0"))
_MAX_FAIL_STREAK = int(os.environ.get("NIBLIT_MAX_FAIL_STREAK", "10"))
_LOG_MAX_EVENTS = int(os.environ.get("NIBLIT_LOG_MAX_EVENTS", "1000"))


@dataclass
class SecurityResult:
    """Result of a membrane inspection."""
    allowed: bool
    reason: str = ""
    risk_score: float = 0.0  # 0.0 = clean, 1.0 = maximum risk


@dataclass
class _ClientRecord:
    """Per-IP tracking record."""
    timestamps: Deque[float] = field(default_factory=lambda: deque(maxlen=500))
    fail_streak: int = 0
    blocked_until: float = 0.0
    total_requests: int = 0
    anomaly_count: int = 0


class SecurityMembrane:
    """
    Defensive security membrane for Niblit's own API surface.

    All logic is purely protective — it monitors, rate-limits, and sanitizes
    inbound requests to Niblit.  It never initiates outbound connections or
    interacts with any external system.
    """

    def __init__(self, knowledge_db: Optional[Any] = None) -> None:
        self.knowledge_db = knowledge_db
        self._clients: Dict[str, _ClientRecord] = defaultdict(_ClientRecord)
        self._global_timestamps: Deque[float] = deque(maxlen=10_000)
        self._events: Deque[Dict[str, Any]] = deque(maxlen=_LOG_MAX_EVENTS)
        self._lock = threading.Lock()
        self._baseline_rps: float = 1.0  # requests/second rolling baseline
        self._last_baseline_update: float = time.time()
        log.info("SecurityMembrane initialised (rate_limit=%d/%ds, block=%ds)",
                 _MAX_REQUESTS_PER_WINDOW, _WINDOW_SECS, _BLOCK_DURATION_SECS)

    # ── Public API ─────────────────────────────────────────────────────────

    def inspect(
        self,
        ip: str = "unknown",
        payload: Any = None,
        command: str = "",
    ) -> SecurityResult:
        """
        Inspect an incoming request.

        Parameters
        ----------
        ip:      Caller IP address (or any string identifier).
        payload: Raw request body / dict.  Checked for size and content.
        command: The Niblit command string, if any.

        Returns
        -------
        SecurityResult — ``allowed=True`` if the request should proceed.
        """
        now = time.time()
        risk = 0.0

        with self._lock:
            client = self._clients[ip]

            # 1. Block check
            if client.blocked_until > now:
                self._log_event("blocked", ip, "IP is temporarily blocked")
                remaining = int(client.blocked_until - now)
                return SecurityResult(False, f"Blocked for {remaining}s", 1.0)

            # 2. Payload size check
            if payload is not None:
                size = self._payload_size(payload)
                if size > _MAX_PAYLOAD_BYTES:
                    risk += 0.4
                    self._log_event("oversized", ip, f"Payload {size} bytes > limit {_MAX_PAYLOAD_BYTES}")
                    self._maybe_block(client, ip, "oversized payload")
                    return SecurityResult(False, "Payload too large", risk)

            # 3. Rate limit check
            client.timestamps.append(now)
            client.total_requests += 1
            self._global_timestamps.append(now)

            window_start = now - _WINDOW_SECS
            recent = sum(1 for t in client.timestamps if t >= window_start)
            if recent > _MAX_REQUESTS_PER_WINDOW:
                risk = min(1.0, risk + 0.5 + (recent - _MAX_REQUESTS_PER_WINDOW) / _MAX_REQUESTS_PER_WINDOW)
                self._log_event("rate_limit", ip, f"{recent} requests in {_WINDOW_SECS}s")
                self._maybe_block(client, ip, "rate limit exceeded")
                return SecurityResult(False, f"Rate limit exceeded ({recent}/{_MAX_REQUESTS_PER_WINDOW} per {_WINDOW_SECS}s)", risk)

            # 4. Anomaly: spike detection vs. baseline
            global_recent = sum(1 for t in self._global_timestamps if t >= window_start)
            baseline_requests = self._baseline_rps * _WINDOW_SECS
            if baseline_requests > 5 and global_recent > baseline_requests * _ANOMALY_SPIKE_RATIO:
                risk = min(1.0, risk + 0.3)
                client.anomaly_count += 1
                self._log_event("spike", ip, f"Global {global_recent} requests vs baseline {baseline_requests:.0f}")

            # 5. Command injection probe detection
            if command:
                probe_risk = self._check_command_probes(command)
                if probe_risk > 0:
                    risk = min(1.0, risk + probe_risk)
                    client.fail_streak += 1
                    self._log_event("probe", ip, f"Suspicious command pattern in: {command[:80]}")
                    if client.fail_streak >= _MAX_FAIL_STREAK:
                        self._maybe_block(client, ip, "repeated suspicious commands")
                        return SecurityResult(False, "Blocked: too many suspicious requests", 1.0)

            # 6. Update baseline periodically
            self._update_baseline(now)

        return SecurityResult(True, "", risk)

    def sanitize(self, value: Any, max_len: int = 32_768) -> Any:
        """
        Sanitize a value for safe use inside Niblit.

        * Strings: strip null bytes, non-printable control chars, HTML-encode
          angle brackets, truncate to max_len.
        * Dicts/lists: recursively sanitize values.
        * Other types: returned as-is.
        """
        if isinstance(value, str):
            # Remove null bytes and non-printable controls (except tab/newline/CR)
            cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
            cleaned = html.escape(cleaned, quote=False)
            return cleaned[:max_len]
        if isinstance(value, dict):
            return {k: self.sanitize(v, max_len) for k, v in value.items()}
        if isinstance(value, list):
            return [self.sanitize(item, max_len) for item in value]
        return value

    def record_failure(self, ip: str, reason: str = "") -> None:
        """Record a failed/rejected command for a given IP."""
        with self._lock:
            client = self._clients[ip]
            client.fail_streak += 1
            self._log_event("failure", ip, reason)
            if client.fail_streak >= _MAX_FAIL_STREAK:
                self._maybe_block(client, ip, f"fail streak {client.fail_streak}")

    def reset_client(self, ip: str) -> None:
        """Reset tracking state for a specific IP (e.g., after successful auth)."""
        with self._lock:
            self._clients.pop(ip, None)

    def status(self) -> Dict[str, Any]:
        """Return a summary of membrane health and statistics."""
        now = time.time()
        with self._lock:
            active_clients = len(self._clients)
            blocked = sum(
                1 for c in self._clients.values() if c.blocked_until > now
            )
            recent_events = list(self._events)[-20:]
            window_start = now - _WINDOW_SECS
            global_recent = sum(1 for t in self._global_timestamps if t >= window_start)
        return {
            "active_clients": active_clients,
            "blocked_ips": blocked,
            "global_requests_last_window": global_recent,
            "rate_limit": f"{_MAX_REQUESTS_PER_WINDOW}/{_WINDOW_SECS}s",
            "max_payload_kb": _MAX_PAYLOAD_BYTES // 1024,
            "baseline_rps": round(self._baseline_rps, 2),
            "recent_events": recent_events,
        }

    def get_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return the most recent security events."""
        with self._lock:
            return list(self._events)[-limit:]

    # ── Internal helpers ───────────────────────────────────────────────────

    @staticmethod
    def _payload_size(payload: Any) -> int:
        if isinstance(payload, (bytes, bytearray)):
            return len(payload)
        if isinstance(payload, str):
            return len(payload.encode("utf-8", errors="replace"))
        try:
            import json as _json
            return len(_json.dumps(payload, default=str).encode())
        except Exception:
            return 0

    @staticmethod
    def _check_command_probes(cmd: str) -> float:
        """
        Check for common command injection / probe patterns.
        Returns a risk float 0.0–0.8.
        """
        risk = 0.0
        dangerous_patterns = [
            (r";\s*(rm|dd|mkfs|fdisk|wget|curl)\b", 0.6),
            (r"\|\s*(bash|sh|zsh|python|perl|ruby)\b", 0.5),
            (r"`[^`]{1,200}`", 0.4),
            (r"\$\([^)]{1,200}\)", 0.4),
            (r"\.\./\.\./", 0.3),
            (r"/etc/(passwd|shadow|sudoers)", 0.7),
            (r"(nc|netcat|ncat)\s+-[el]", 0.8),
            (r"(base64\s+-d|base64\s+--decode)", 0.3),
            (r">>\s*/etc/", 0.7),
            (r"chmod\s+[0-7]*[67][0-7][0-7]\s+", 0.4),
        ]
        for pattern, weight in dangerous_patterns:
            if re.search(pattern, cmd, re.IGNORECASE):
                risk = max(risk, weight)
        return risk

    def _maybe_block(self, client: _ClientRecord, ip: str, reason: str) -> None:
        """Temporarily block an IP."""
        if client.blocked_until <= time.time():
            client.blocked_until = time.time() + _BLOCK_DURATION_SECS
            log.warning("SecurityMembrane: blocking %s for %ds — %s", ip, _BLOCK_DURATION_SECS, reason)
            self._log_event("block", ip, reason)
            if self.knowledge_db:
                try:
                    self.knowledge_db.add_fact(
                        f"security:block:{_fingerprint(ip)}",
                        f"IP blocked at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} — {reason}",
                    )
                except Exception:
                    pass

    def _log_event(self, event_type: str, ip: str, detail: str) -> None:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "type": event_type,
            "ip_hash": _fingerprint(ip),
            "detail": detail[:200],
        }
        self._events.append(entry)
        log.debug("SecurityMembrane [%s] %s: %s", event_type, entry["ip_hash"], detail[:80])

    def _update_baseline(self, now: float) -> None:
        """Update the rolling request-per-second baseline every 60 s."""
        if now - self._last_baseline_update < 60:
            return
        window_start = now - _WINDOW_SECS
        count = sum(1 for t in self._global_timestamps if t >= window_start)
        new_rps = count / _WINDOW_SECS
        self._baseline_rps = 0.8 * self._baseline_rps + 0.2 * new_rps
        self._last_baseline_update = now


def _fingerprint(ip: str) -> str:
    """One-way hash of an IP so we never log raw addresses."""
    return hashlib.sha256(ip.encode()).hexdigest()[:12]


# ── Singleton ──────────────────────────────────────────────────────────────
_instance: Optional[SecurityMembrane] = None
_instance_lock = threading.Lock()


def get_security_membrane(knowledge_db: Optional[Any] = None) -> SecurityMembrane:
    """Return the process-level SecurityMembrane singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = SecurityMembrane(knowledge_db=knowledge_db)
    return _instance
