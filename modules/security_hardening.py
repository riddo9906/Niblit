#!/usr/bin/env python3
"""
modules/security_hardening.py — NIBLIT-AIOS Computational Security Hardening
=============================================================================
Provides cryptographically strong, **computationally expensive** primitives
that make it hard for attackers to brute-force credentials, forge requests,
or replay captured tokens.

Design principles
-----------------
* **No new external dependencies** — uses only the Python standard library
  (``hashlib``, ``hmac``, ``secrets``, ``os``).
* **Defence-in-depth** — every public method is a distinct protection layer
  that can be applied independently.
* **Timing-safe** — all comparison operations use ``hmac.compare_digest`` to
  prevent timing side-channel attacks.
* **Computationally expensive by design** — key derivation (PBKDF2) uses
  ``NIBLIT_KDF_ITERATIONS`` (default 260,000) rounds of HMAC-SHA256 so that
  brute-forcing a leaked hash requires significant compute.

Public API
----------
``SecurityHardening.derive_key(password, salt)``
    Derive a 32-byte key from a password using PBKDF2-HMAC-SHA256.
    Expensive by design (configurable iteration count).

``SecurityHardening.sign_request(payload, key)``
    Produce an HMAC-SHA256 signature for a request payload.

``SecurityHardening.verify_request(payload, signature, key)``
    Constant-time HMAC verification.

``SecurityHardening.issue_challenge(difficulty)``
    Issue a proof-of-work challenge nonce.

``SecurityHardening.verify_challenge(nonce, solution, difficulty)``
    Verify a proof-of-work solution (SHA-256 hash must start with
    ``difficulty`` zero bits).

``SecurityHardening.generate_token()``
    Generate a 32-byte cryptographically random token.

``SecurityHardening.consume_nonce(nonce)``
    Register a nonce as used; return ``False`` if it was already seen
    (replay-attack prevention).

Singleton access via ``get_security_hardening()``.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import threading
import time
from collections import deque
from typing import Deque, Optional, Set, Tuple

log = logging.getLogger("aios.security_hardening")

# ── Tuneable constants (override via environment) ──────────────────────────────

# PBKDF2 iteration count. NIST SP 800-132 recommends ≥ 210,000 for SHA-256.
# Higher = more expensive for attackers, slightly slower for Niblit itself.
_KDF_ITERATIONS: int = int(os.environ.get("NIBLIT_KDF_ITERATIONS", "260000"))
_KDF_HASH: str = "sha256"
_KEY_LENGTH_BYTES: int = 32

# Proof-of-work default difficulty (leading zero bits in SHA-256 result).
# 16 bits ≈ 65,536 expected hashes per challenge — fast enough for legitimate
# callers, expensive enough to deter automated flooding.
_DEFAULT_POW_DIFFICULTY: int = int(os.environ.get("NIBLIT_POW_DIFFICULTY", "16"))

# Nonce expiry: replay-protection window in seconds.
_NONCE_TTL_SECS: int = int(os.environ.get("NIBLIT_NONCE_TTL", "300"))  # 5 min

# Maximum size of the used-nonce set (prevents unbounded memory growth).
_NONCE_CACHE_MAX: int = 100_000


# ── SecurityHardening ──────────────────────────────────────────────────────────

class SecurityHardening:
    """
    Computational security hardening for NIBLIT-AIOS.

    All operations are thread-safe.  The class is stateful only for nonce
    tracking (replay-attack prevention); all other methods are stateless
    and can be called concurrently.
    """

    def __init__(self, kdf_iterations: int = _KDF_ITERATIONS) -> None:
        self._kdf_iterations = kdf_iterations
        self._lock = threading.Lock()
        # Nonce store: set of used nonces + a deque for TTL-based eviction.
        self._used_nonces: Set[str] = set()
        self._nonce_timestamps: Deque[Tuple[float, str]] = deque(
            maxlen=_NONCE_CACHE_MAX
        )
        log.debug(
            "SecurityHardening initialised (kdf_iterations=%d, pow_difficulty=%d)",
            self._kdf_iterations,
            _DEFAULT_POW_DIFFICULTY,
        )

    # ── Key Derivation ────────────────────────────────────────────────────────

    def derive_key(
        self,
        password: str | bytes,
        salt: bytes,
        *,
        iterations: Optional[int] = None,
        length: int = _KEY_LENGTH_BYTES,
    ) -> bytes:
        """
        Derive a cryptographic key from a password using PBKDF2-HMAC-SHA256.

        This is **intentionally slow** — the high iteration count makes
        brute-force and dictionary attacks computationally impractical.

        Parameters
        ----------
        password:   The secret (string or bytes).
        salt:       Random per-credential salt (at least 16 bytes recommended).
        iterations: Override the default iteration count (expert use only).
        length:     Desired key length in bytes (default 32 = 256 bits).

        Returns
        -------
        Derived key as raw bytes.
        """
        if isinstance(password, str):
            password = password.encode("utf-8")
        n_iter = iterations if iterations is not None else self._kdf_iterations
        key = hashlib.pbkdf2_hmac(_KDF_HASH, password, salt, n_iter, dklen=length)
        return key

    def generate_salt(self, length: int = 16) -> bytes:
        """Return a cryptographically random salt of the given length."""
        return secrets.token_bytes(length)

    # ── Request Signing ───────────────────────────────────────────────────────

    def sign_request(self, payload: str | bytes, key: bytes) -> str:
        """
        Produce an HMAC-SHA256 signature for *payload* using *key*.

        Parameters
        ----------
        payload: Request body / canonical string to sign.
        key:     Signing key (bytes).

        Returns
        -------
        Hex-encoded HMAC-SHA256 signature.
        """
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        sig = hmac.new(key, payload, digestmod=hashlib.sha256).hexdigest()
        return sig

    def verify_request(
        self,
        payload: str | bytes,
        signature: str,
        key: bytes,
    ) -> bool:
        """
        Verify an HMAC-SHA256 signature in **constant time**.

        Returns ``True`` if the signature matches, ``False`` otherwise.
        Timing is independent of where any mismatch occurs, preventing
        timing side-channel attacks.
        """
        expected = self.sign_request(payload, key)
        return hmac.compare_digest(expected, signature)

    # ── Replay-Attack Protection ──────────────────────────────────────────────

    def generate_token(self, length: int = 32) -> str:
        """
        Generate a URL-safe, cryptographically random token.

        Returns a hex string of ``length * 2`` characters.
        """
        return secrets.token_hex(length)

    def consume_nonce(self, nonce: str) -> bool:
        """
        Attempt to consume a nonce for replay-attack prevention.

        Returns
        -------
        ``True``  — nonce has NOT been seen before (request is fresh).
        ``False`` — nonce was already consumed (reject as a replay).
        """
        now = time.monotonic()
        with self._lock:
            self._evict_expired_nonces(now)
            if nonce in self._used_nonces:
                log.debug("SecurityHardening: replay detected — nonce already consumed")
                return False
            self._used_nonces.add(nonce)
            self._nonce_timestamps.append((now, nonce))
        return True

    def _evict_expired_nonces(self, now: float) -> None:
        """Remove nonces older than ``_NONCE_TTL_SECS`` (lock must be held)."""
        cutoff = now - _NONCE_TTL_SECS
        while self._nonce_timestamps and self._nonce_timestamps[0][0] < cutoff:
            _, old_nonce = self._nonce_timestamps.popleft()
            self._used_nonces.discard(old_nonce)

    # ── Proof-of-Work ────────────────────────────────────────────────────────

    def issue_challenge(self, difficulty: int = _DEFAULT_POW_DIFFICULTY) -> str:
        """
        Issue a proof-of-work challenge nonce.

        The solver must find a *solution* string such that::

            SHA-256(nonce + ":" + solution)

        has at least *difficulty* leading zero bits.

        Returns a random hex challenge nonce.
        """
        return secrets.token_hex(16)

    def verify_challenge(
        self,
        nonce: str,
        solution: str,
        difficulty: int = _DEFAULT_POW_DIFFICULTY,
    ) -> bool:
        """
        Verify a proof-of-work solution.

        Checks that SHA-256(nonce + ":" + solution) has at least *difficulty*
        leading zero bits.

        Parameters
        ----------
        nonce:      The challenge nonce issued by ``issue_challenge()``.
        solution:   The solver's answer string.
        difficulty: Number of leading zero bits required (default 16).

        Returns
        -------
        ``True`` if the solution is valid, ``False`` otherwise.
        """
        candidate = (nonce + ":" + solution).encode("utf-8")
        digest = hashlib.sha256(candidate).digest()

        # Count leading zero bits in the digest.
        zeros = 0
        for byte in digest:
            if byte == 0:
                zeros += 8
            else:
                # Count leading zero bits in this byte.
                zeros += 8 - byte.bit_length()
                break
        return zeros >= difficulty

    def solve_challenge(
        self,
        nonce: str,
        difficulty: int = _DEFAULT_POW_DIFFICULTY,
        max_attempts: int = 10_000_000,
    ) -> Optional[str]:
        """
        Solve a proof-of-work challenge locally (used in tests / self-validation).

        Returns the solution string, or ``None`` if unsolvable within
        *max_attempts*.
        """
        for attempt in range(max_attempts):
            candidate = str(attempt)
            if self.verify_challenge(nonce, candidate, difficulty):
                return candidate
        return None

    # ── Constant-time token check ─────────────────────────────────────────────

    def check_token(self, token: str, expected: str) -> bool:
        """
        Compare two tokens in **constant time** to prevent timing attacks.

        Returns ``True`` if they match.
        """
        return hmac.compare_digest(
            token.encode("utf-8"),
            expected.encode("utf-8"),
        )

    # ── Status / Diagnostics ──────────────────────────────────────────────────

    def status(self) -> dict:
        """Return a summary dict for telemetry."""
        with self._lock:
            nonce_cache_size = len(self._used_nonces)
        return {
            "kdf_algorithm": f"PBKDF2-HMAC-{_KDF_HASH.upper()}",
            "kdf_iterations": self._kdf_iterations,
            "key_length_bytes": _KEY_LENGTH_BYTES,
            "default_pow_difficulty": _DEFAULT_POW_DIFFICULTY,
            "nonce_ttl_secs": _NONCE_TTL_SECS,
            "nonce_cache_size": nonce_cache_size,
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_hardening: Optional[SecurityHardening] = None
_hardening_lock = threading.Lock()


def get_security_hardening(
    kdf_iterations: int = _KDF_ITERATIONS,
) -> SecurityHardening:
    """Return the process-level SecurityHardening singleton."""
    global _hardening
    if _hardening is None:
        with _hardening_lock:
            if _hardening is None:
                _hardening = SecurityHardening(kdf_iterations=kdf_iterations)
    return _hardening
