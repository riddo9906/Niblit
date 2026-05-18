"""Centralized project path resolution utilities."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_project_root() -> Path:
    """Return the repository root directory."""
    return PROJECT_ROOT


def get_data_dir() -> Path:
    """Return the canonical data directory."""
    return resolve_path("data")


def get_memory_dir() -> Path:
    """Return the canonical memory directory."""
    return resolve_path("niblit_memory")


def resolve_path(*segments: str) -> Path:
    """Resolve one or more path segments under the project root."""
    return PROJECT_ROOT.joinpath(*segments)

