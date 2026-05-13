from __future__ import annotations

import os

from tools.lib.runtime_profiles import apply_profile, available_profiles, load_profile
from tools.lib.sidecar_client import format_response, normalize_response


def test_runtime_profiles_exist() -> None:
    profiles = set(available_profiles())
    assert {"niblit", "cloud-server", "termux-local"}.issubset(profiles)


def test_apply_profile_sets_runtime_profile_env() -> None:
    os.environ.pop("NIBLIT_RUNTIME_PROFILE", None)
    profile = apply_profile("niblit", override_existing=False)
    assert profile.name == "niblit"
    assert os.environ.get("NIBLIT_RUNTIME_PROFILE") == "niblit"


def test_load_profile_has_required_keys() -> None:
    profile = load_profile("cloud-server")
    required = {
        "NIBLIT_APP_NAME",
        "NIBLIT_CTL_HOST",
        "NIBLIT_CTL_PORT",
        "NIBLIT_GGUF_BACKEND",
        "NIBLIT_LLAMA_SERVER_URL",
        "NIBLIT_RUNTIME_MODE",
    }
    assert required.issubset(set(profile.values.keys()))


def test_response_normalization_handles_missing_fields() -> None:
    resp = normalize_response({"status": "ok", "message": "hello"})
    assert resp.status == "ok"
    assert resp.result == "hello"


def test_format_response_modes() -> None:
    resp = normalize_response({"status": "ok", "result": "pong"})
    assert "status=ok" in format_response(resp, mode="pretty")
    assert "pong" in format_response(resp, mode="json")
    assert "status" in format_response(resp, mode="raw")


if __name__ == "__main__":
    print('Running test_runtime_tooling_layer.py')
