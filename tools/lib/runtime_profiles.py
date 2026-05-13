#!/usr/bin/env python3
"""Runtime profile loading utilities for Niblit tooling."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimeProfile:
    name: str
    path: Path
    values: dict[str, str]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def profile_dir() -> Path:
    return _repo_root() / "tools" / "runtime_profiles"


def available_profiles() -> list[str]:
    base = profile_dir()
    if not base.exists():
        return []
    return sorted(p.stem for p in base.glob("*.env"))


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def load_profile(name: str = "niblit") -> RuntimeProfile:
    env_path = profile_dir() / f"{name}.env"
    if not env_path.exists():
        raise FileNotFoundError(f"Runtime profile not found: {env_path}")
    return RuntimeProfile(name=name, path=env_path, values=_parse_env_file(env_path))


def apply_profile(name: str = "niblit", *, override_existing: bool = False) -> RuntimeProfile:
    profile = load_profile(name)
    for key, value in profile.values.items():
        if override_existing or key not in os.environ:
            os.environ[key] = value
    os.environ["NIBLIT_RUNTIME_PROFILE"] = profile.name
    return profile


if __name__ == "__main__":
    print('Running runtime_profiles.py')
