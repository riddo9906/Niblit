"""
test_aios_architecture.py — Tests for the NIBLIT AI OS 8-layer architecture.

Covers:
  * AIOSLayerRegistry — registration, retrieval, health, cross-wiring
  * SecurityHardening — key derivation, signing, nonce, proof-of-work
  * AIOSRuntime — new security / registry subsystems present after Phase 2

Run with::

    pytest test_aios_architecture.py -v
"""

from __future__ import annotations

import hashlib
import os
import secrets
import threading
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# AIOSLayerRegistry
# ─────────────────────────────────────────────────────────────────────────────

class TestAIOSLayerRegistry:
    """Tests for the formal 8-layer architecture registry."""

    def _fresh(self):
        """Return a new (non-singleton) AIOSLayerRegistry for isolation."""
        from modules.aios_layer_registry import AIOSLayerRegistry
        return AIOSLayerRegistry()

    def test_all_layers_present(self):
        from modules.aios_layer_registry import ALL_LAYERS, LAYER_APP, LAYER_INT
        from modules.aios_layer_registry import LAYER_LRN, LAYER_MEM, LAYER_NET
        from modules.aios_layer_registry import LAYER_SEC, LAYER_KRN, LAYER_HAL
        expected = {LAYER_APP, LAYER_INT, LAYER_LRN, LAYER_MEM,
                    LAYER_NET, LAYER_SEC, LAYER_KRN, LAYER_HAL}
        assert expected == set(ALL_LAYERS)

    def test_register_and_get(self):
        from modules.aios_layer_registry import LAYER_SEC
        reg = self._fresh()
        mock = MagicMock()
        reg.register(LAYER_SEC, "test_comp", mock)
        assert reg.get(LAYER_SEC, "test_comp") is mock

    def test_get_missing_returns_none(self):
        from modules.aios_layer_registry import LAYER_APP
        reg = self._fresh()
        assert reg.get(LAYER_APP, "nonexistent") is None

    def test_register_unknown_layer_raises(self):
        reg = self._fresh()
        with pytest.raises(ValueError, match="Unknown AIOS layer"):
            reg.register("UNKNOWN", "comp", MagicMock())

    def test_health_empty_layers(self):
        reg = self._fresh()
        result = reg.health()
        assert "layers" in result
        assert "total_components" in result
        assert result["total_components"] == 0
        assert result["healthy"] is True  # empty layers are not unhealthy

    def test_health_with_healthy_component(self):
        from modules.aios_layer_registry import LAYER_KRN
        reg = self._fresh()
        reg.register(LAYER_KRN, "kernel", MagicMock(), health_check=lambda: True)
        result = reg.health()
        assert result["layers"][LAYER_KRN]["healthy"] is True
        assert result["layers"][LAYER_KRN]["count"] == 1

    def test_health_with_unhealthy_component(self):
        from modules.aios_layer_registry import LAYER_SEC
        reg = self._fresh()
        reg.register(LAYER_SEC, "broken", MagicMock(), health_check=lambda: False)
        result = reg.health()
        assert result["layers"][LAYER_SEC]["healthy"] is False

    def test_health_check_exception_marks_unhealthy(self):
        from modules.aios_layer_registry import LAYER_MEM
        reg = self._fresh()

        def bad_check():
            raise RuntimeError("boom")

        reg.register(LAYER_MEM, "mem", MagicMock(), health_check=bad_check)
        result = reg.health()
        assert result["layers"][LAYER_MEM]["components"]["mem"] is False

    def test_list_components_all(self):
        from modules.aios_layer_registry import LAYER_APP, LAYER_INT
        reg = self._fresh()
        reg.register(LAYER_APP, "router", MagicMock())
        reg.register(LAYER_INT, "brain", MagicMock())
        comps = reg.list_components()
        names = {c.name for c in comps}
        assert "router" in names
        assert "brain" in names

    def test_list_components_filtered(self):
        from modules.aios_layer_registry import LAYER_APP, LAYER_INT
        reg = self._fresh()
        reg.register(LAYER_APP, "router", MagicMock())
        reg.register(LAYER_INT, "brain", MagicMock())
        app_comps = reg.list_components(layer=LAYER_APP)
        assert len(app_comps) == 1
        assert app_comps[0].name == "router"

    def test_layer_summary_contains_all_layers(self):
        from modules.aios_layer_registry import ALL_LAYERS
        reg = self._fresh()
        summary = reg.layer_summary()
        for layer_id in ALL_LAYERS:
            assert layer_id in summary

    def test_status_dict_shape(self):
        reg = self._fresh()
        s = reg.status()
        assert s["total_layers"] == 8
        assert "total_components" in s
        assert "layer_counts" in s

    def test_cross_wire_ignores_none_attrs(self):
        """cross_wire must not crash when AIOSRuntime attrs are None."""
        from modules.aios_layer_registry import LAYER_SEC
        reg = self._fresh()
        mock_runtime = MagicMock()
        # Simulate most subsystems absent
        mock_runtime.hal = None
        mock_runtime.kernel = None
        mock_runtime.niblit_runtime = None
        mock_runtime.scheduler = None
        mock_runtime.memory = None
        mock_runtime.brain = None
        mock_runtime.ale = None
        mock_runtime.router = None
        mock_runtime.security_hardening = MagicMock()
        mock_runtime.security_membrane = None
        mock_runtime.core = None
        reg.cross_wire(mock_runtime)
        # Only security_hardening should be registered
        assert reg.get(LAYER_SEC, "security_hardening") is not None

    def test_singleton_returns_same_instance(self):
        from modules.aios_layer_registry import get_aios_layer_registry
        a = get_aios_layer_registry()
        b = get_aios_layer_registry()
        assert a is b

    def test_thread_safe_concurrent_registration(self):
        from modules.aios_layer_registry import AIOSLayerRegistry, LAYER_APP
        reg = AIOSLayerRegistry()
        errors = []

        def register(i):
            try:
                reg.register(LAYER_APP, f"comp_{i}", MagicMock())
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=register, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert reg.status()["layer_counts"][LAYER_APP] == 20


# ─────────────────────────────────────────────────────────────────────────────
# SecurityHardening
# ─────────────────────────────────────────────────────────────────────────────

class TestSecurityHardening:
    """Tests for the computational security hardening module."""

    def _fresh(self, iterations: int = 1000):
        """Return a low-iteration SecurityHardening for fast tests."""
        from modules.security_hardening import SecurityHardening
        return SecurityHardening(kdf_iterations=iterations)

    # ── Key derivation ─────────────────────────────────────────────────────

    def test_derive_key_returns_bytes(self):
        sh = self._fresh()
        salt = sh.generate_salt()
        key = sh.derive_key("password", salt)
        assert isinstance(key, bytes)
        assert len(key) == 32

    def test_derive_key_deterministic(self):
        sh = self._fresh()
        salt = sh.generate_salt()
        k1 = sh.derive_key("secret", salt)
        k2 = sh.derive_key("secret", salt)
        assert k1 == k2

    def test_derive_key_different_passwords(self):
        sh = self._fresh()
        salt = sh.generate_salt()
        k1 = sh.derive_key("password1", salt)
        k2 = sh.derive_key("password2", salt)
        assert k1 != k2

    def test_derive_key_different_salts(self):
        sh = self._fresh()
        s1 = sh.generate_salt()
        s2 = sh.generate_salt()
        k1 = sh.derive_key("same", s1)
        k2 = sh.derive_key("same", s2)
        assert k1 != k2

    def test_derive_key_accepts_bytes_password(self):
        sh = self._fresh()
        salt = sh.generate_salt()
        key = sh.derive_key(b"bytes_password", salt)
        assert isinstance(key, bytes) and len(key) == 32

    def test_derive_key_custom_length(self):
        sh = self._fresh()
        salt = sh.generate_salt()
        key = sh.derive_key("pw", salt, length=64)
        assert len(key) == 64

    def test_generate_salt_length(self):
        sh = self._fresh()
        for n in [8, 16, 32]:
            assert len(sh.generate_salt(n)) == n

    # ── Request signing ────────────────────────────────────────────────────

    def test_sign_and_verify_roundtrip(self):
        sh = self._fresh()
        key = secrets.token_bytes(32)
        payload = "GET /api/status timestamp=1234567890"
        sig = sh.sign_request(payload, key)
        assert sh.verify_request(payload, sig, key)

    def test_verify_wrong_key_fails(self):
        sh = self._fresh()
        key1 = secrets.token_bytes(32)
        key2 = secrets.token_bytes(32)
        sig = sh.sign_request("payload", key1)
        assert not sh.verify_request("payload", sig, key2)

    def test_verify_tampered_payload_fails(self):
        sh = self._fresh()
        key = secrets.token_bytes(32)
        sig = sh.sign_request("original", key)
        assert not sh.verify_request("tampered", sig, key)

    def test_sign_bytes_payload(self):
        sh = self._fresh()
        key = secrets.token_bytes(32)
        payload = b"\x00\x01\x02binary\xff"
        sig = sh.sign_request(payload, key)
        assert sh.verify_request(payload, sig, key)

    # ── Nonce / replay protection ─────────────────────────────────────────

    def test_consume_nonce_first_use(self):
        sh = self._fresh()
        nonce = sh.generate_token()
        assert sh.consume_nonce(nonce) is True

    def test_consume_nonce_replay_rejected(self):
        sh = self._fresh()
        nonce = sh.generate_token()
        sh.consume_nonce(nonce)
        assert sh.consume_nonce(nonce) is False

    def test_different_nonces_both_accepted(self):
        sh = self._fresh()
        n1, n2 = sh.generate_token(), sh.generate_token()
        assert sh.consume_nonce(n1) is True
        assert sh.consume_nonce(n2) is True

    def test_generate_token_unique(self):
        sh = self._fresh()
        tokens = {sh.generate_token() for _ in range(100)}
        assert len(tokens) == 100

    # ── Proof-of-work ─────────────────────────────────────────────────────

    def test_issue_challenge_is_hex(self):
        sh = self._fresh()
        nonce = sh.issue_challenge(difficulty=8)
        int(nonce, 16)  # must be valid hex

    def test_solve_and_verify_challenge(self):
        sh = self._fresh()
        nonce = sh.issue_challenge(difficulty=8)
        solution = sh.solve_challenge(nonce, difficulty=8)
        assert solution is not None
        assert sh.verify_challenge(nonce, solution, difficulty=8)

    def test_wrong_solution_rejected(self):
        sh = self._fresh()
        nonce = sh.issue_challenge(difficulty=8)
        # A solution of "WRONG" is almost certainly invalid
        assert not sh.verify_challenge(nonce, "WRONG", difficulty=8)

    def test_verify_challenge_manual(self):
        """Manually construct a valid solution and verify."""
        sh = self._fresh()
        nonce = "testnonce"
        # Brute-force a valid solution for difficulty=4 (fast)
        for i in range(100_000):
            candidate = str(i)
            data = (nonce + ":" + candidate).encode()
            digest = hashlib.sha256(data).digest()
            zeros = 0
            for byte in digest:
                if byte == 0:
                    zeros += 8
                else:
                    zeros += 8 - byte.bit_length()
                    break
            if zeros >= 4:
                assert sh.verify_challenge(nonce, candidate, difficulty=4)
                return
        pytest.skip("Could not find a PoW solution in 100k attempts (unlikely)")

    # ── Constant-time token check ─────────────────────────────────────────

    def test_check_token_match(self):
        sh = self._fresh()
        tok = sh.generate_token()
        assert sh.check_token(tok, tok)

    def test_check_token_mismatch(self):
        sh = self._fresh()
        assert not sh.check_token("aaa", "bbb")

    # ── Status ────────────────────────────────────────────────────────────

    def test_status_shape(self):
        sh = self._fresh()
        s = sh.status()
        assert "kdf_algorithm" in s
        assert "kdf_iterations" in s
        assert "default_pow_difficulty" in s
        assert "nonce_cache_size" in s

    def test_singleton_returns_same_instance(self):
        from modules.security_hardening import get_security_hardening
        a = get_security_hardening()
        b = get_security_hardening()
        assert a is b

    def test_thread_safe_nonce_consumption(self):
        """Concurrent nonce consumption should produce exactly one success."""
        from modules.security_hardening import SecurityHardening
        sh = SecurityHardening(kdf_iterations=1)
        nonce = sh.generate_token()
        results = []
        lock = threading.Lock()

        def consume():
            ok = sh.consume_nonce(nonce)
            with lock:
                results.append(ok)

        threads = [threading.Thread(target=consume) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sum(results) == 1  # exactly one thread got True


# ─────────────────────────────────────────────────────────────────────────────
# AIOSRuntime — new fields
# ─────────────────────────────────────────────────────────────────────────────

class TestAIOSRuntimeNewFields:
    """Smoke-tests that AIOSRuntime exposes the new SEC-layer subsystems."""

    def test_runtime_has_security_hardening_attr(self):
        from aios_runtime import AIOSRuntime
        rt = AIOSRuntime()
        assert hasattr(rt, "security_hardening")
        assert rt.security_hardening is None  # before boot

    def test_runtime_has_security_membrane_attr(self):
        from aios_runtime import AIOSRuntime
        rt = AIOSRuntime()
        assert hasattr(rt, "security_membrane")
        assert rt.security_membrane is None

    def test_runtime_has_layer_registry_attr(self):
        from aios_runtime import AIOSRuntime
        rt = AIOSRuntime()
        assert hasattr(rt, "layer_registry")
        assert rt.layer_registry is None

    def test_status_includes_new_keys(self):
        from aios_runtime import AIOSRuntime
        rt = AIOSRuntime()
        s = rt.status()
        assert "security_hardening_available" in s
        assert "security_membrane_available" in s
        assert "layer_registry_available" in s
        assert s["security_hardening_available"] is False

    def test_phase_2_wires_security_hardening(self):
        """After _phase_2_bootloader(), security_hardening should be set."""
        from aios_runtime import AIOSRuntime
        rt = AIOSRuntime()
        rt._phase_2_bootloader()
        assert rt.security_hardening is not None

    def test_phase_2_wires_security_membrane(self):
        from aios_runtime import AIOSRuntime
        rt = AIOSRuntime()
        rt._phase_2_bootloader()
        assert rt.security_membrane is not None

    def test_phase_2_wires_layer_registry(self):
        from aios_runtime import AIOSRuntime
        rt = AIOSRuntime()
        rt._phase_2_bootloader()
        assert rt.layer_registry is not None

    def test_phase_7_cross_wires_registry(self):
        """After Phase 2 + 7, the layer registry should have SEC components."""
        from aios_runtime import AIOSRuntime
        from modules.aios_layer_registry import LAYER_SEC
        rt = AIOSRuntime()
        rt._phase_2_bootloader()
        rt._phase_7_interface()
        assert rt.layer_registry is not None
        # security_hardening was registered under SEC
        sh = rt.layer_registry.get(LAYER_SEC, "security_hardening")
        assert sh is not None


if __name__ == "__main__":
    print('Running test_aios_architecture.py')
