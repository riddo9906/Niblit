#!/usr/bin/env python3
"""
modules/game_engine.py — Niblit Game Engine

A lightweight, headless-first 2D game/simulation engine that lets Niblit's
agent layer create, run, step, and introspect game worlds.

Features
--------
* **Headless mode** (default): runs entirely in Python with no display — ideal
  for agentic simulations, tests, and serverless deployments.
* **pygame mode** (optional): if ``pygame`` is installed and
  ``NIBLIT_GAME_DISPLAY=1`` is set, the engine can open a real window.
* **Entity / Scene management**: add / remove / list entities, each with a
  position, velocity, and arbitrary ``tags`` dict.
* **Tick loop**: ``step(dt)`` advances physics, processes events, calls
  per-entity ``update`` hooks.
* **Save / load state**: snapshot current world to JSON, restore from it.
* **Score & event log**: kept in memory and persisted to ``niblit_game_log.jsonl``.
* **Agent API**: ``get_state()``, ``apply_action()``, ``reset()`` make it
  easy for Niblit's planning/research agents to treat a game as an RL
  environment.

CLI commands (via NiblitCore._cmd_game)
----------------------------------------
game status            — Engine status
game list              — List active entities
game add <name> [x=N] [y=N] [tag=v] — Add an entity
game remove <name>     — Remove an entity
game step [N]          — Advance N ticks (default 1)
game reset             — Reset the world
game save [path]       — Save world state to JSON
game load <path>       — Load world state from JSON
game log [N]           — Show last N event log entries
game score             — Show current score
game play <game_name>  — Load a bundled game template
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("GameEngine")

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_LOG_PATH = _REPO_ROOT / "niblit_game_log.jsonl"
_DEFAULT_STATE_PATH = _REPO_ROOT / "niblit_game_state.json"

# ── optional pygame ───────────────────────────────────────────────────────────
try:
    import pygame as _pygame
    _PYGAME_AVAILABLE = True
except ImportError:
    _pygame = None  # type: ignore[assignment]
    _PYGAME_AVAILABLE = False

_DISPLAY_ENABLED = os.environ.get("NIBLIT_GAME_DISPLAY", "0") == "1"


# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Entity:
    """A game object in the world."""
    name: str
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    tags: Dict[str, Any] = field(default_factory=dict)

    def update(self, dt: float) -> None:
        """Advance position by velocity × dt."""
        self.x += self.vx * dt
        self.y += self.vy * dt

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Entity":
        return cls(**d)


# ─────────────────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────────────────

class GameEngine:
    """
    Niblit's modular game / simulation engine.

    The engine is always safe to import and construct — pygame is only
    needed when display mode is explicitly enabled.
    """

    # Built-in template games ─────────────────────────────────────────────────
    _TEMPLATES: Dict[str, List[Dict[str, Any]]] = {
        "pong": [
            {"name": "ball",   "x": 400.0, "y": 300.0, "vx": 200.0, "vy": 150.0},
            {"name": "paddle_left",  "x": 30.0,  "y": 300.0, "tags": {"type": "paddle"}},
            {"name": "paddle_right", "x": 770.0, "y": 300.0, "tags": {"type": "paddle"}},
        ],
        "gravity": [
            {"name": "particle_A", "x": 100.0, "y": 0.0, "vy": 0.0, "tags": {"mass": 1.0}},
            {"name": "particle_B", "x": 300.0, "y": 0.0, "vy": 0.0, "tags": {"mass": 2.0}},
        ],
        "adventure": [
            {"name": "hero",    "x": 50.0,  "y": 50.0,  "tags": {"hp": 100, "role": "hero"}},
            {"name": "monster", "x": 400.0, "y": 400.0, "tags": {"hp": 50,  "role": "enemy"}},
            {"name": "treasure","x": 700.0, "y": 100.0, "tags": {"value": 100, "role": "item"}},
        ],
    }

    def __init__(
        self,
        width: int = 800,
        height: int = 600,
        fps: int = 60,
        log_path: Path = _DEFAULT_LOG_PATH,
    ) -> None:
        self.width = width
        self.height = height
        self.fps = fps
        self.log_path = Path(log_path)

        self.entities: Dict[str, Entity] = {}
        self.score: float = 0.0
        self.tick: int = 0
        self.running: bool = False
        self._events: List[Dict[str, Any]] = []
        self._screen = None  # pygame surface (only in display mode)

        log.info(
            "GameEngine ready (display=%s, pygame=%s)",
            _DISPLAY_ENABLED,
            _PYGAME_AVAILABLE,
        )

    # ── Entity API ────────────────────────────────────────────────────────────

    def add_entity(self, name: str, **kwargs: Any) -> str:
        """Add (or replace) an entity and return a status string."""
        self.entities[name] = Entity(name=name, **kwargs)
        self._log_event("entity_add", {"name": name, **kwargs})
        return f"✅ Entity '{name}' added at ({kwargs.get('x', 0)}, {kwargs.get('y', 0)})"

    def remove_entity(self, name: str) -> str:
        """Remove entity by name."""
        if name not in self.entities:
            return f"❌ Entity '{name}' not found"
        del self.entities[name]
        self._log_event("entity_remove", {"name": name})
        return f"🗑 Entity '{name}' removed"

    def list_entities(self) -> str:
        """Return a formatted list of entities."""
        if not self.entities:
            return "No entities in the world."
        lines = [f"  • {e.name}  pos=({e.x:.1f},{e.y:.1f})  vel=({e.vx:.1f},{e.vy:.1f})  tags={e.tags}"
                 for e in self.entities.values()]
        return "Entities:\n" + "\n".join(lines)

    # ── Simulation ────────────────────────────────────────────────────────────

    def step(self, n: int = 1, dt: float = 1.0 / 60.0) -> str:
        """Advance the simulation by *n* ticks."""
        for _ in range(n):
            for entity in self.entities.values():
                entity.update(dt)
            self.tick += 1
        self._log_event("step", {"n": n, "tick": self.tick})
        return f"⏩ Stepped {n} tick(s) — total ticks: {self.tick}"

    def reset(self) -> str:
        """Clear all entities and reset score / tick counter."""
        self.entities.clear()
        self.score = 0.0
        self.tick = 0
        self._events.clear()
        self._log_event("reset", {})
        return "🔄 World reset"

    # ── Template games ────────────────────────────────────────────────────────

    def play(self, game_name: str) -> str:
        """Load a named built-in game template."""
        name = game_name.lower()
        if name not in self._TEMPLATES:
            return (
                f"Unknown template '{game_name}'. "
                f"Available: {', '.join(self._TEMPLATES)}"
            )
        self.reset()
        for edict in self._TEMPLATES[name]:
            edict_copy = dict(edict)
            ename = edict_copy.pop("name")
            self.entities[ename] = Entity(name=ename, **edict_copy)
        self._log_event("play", {"game": name})
        return (
            f"🎮 Loaded template '{name}' with "
            f"{len(self.entities)} entities — use 'game step N' to advance"
        )

    # ── Agent API ─────────────────────────────────────────────────────────────

    def get_state(self) -> Dict[str, Any]:
        """Return the full world state as a serialisable dict."""
        return {
            "tick": self.tick,
            "score": self.score,
            "entities": {n: e.to_dict() for n, e in self.entities.items()},
        }

    def apply_action(self, entity_name: str, action: Dict[str, Any]) -> str:
        """Apply an action dict (e.g. ``{'vx': 10, 'vy': -5}``) to an entity."""
        ent = self.entities.get(entity_name)
        if ent is None:
            return f"❌ Entity '{entity_name}' not found"
        for key, val in action.items():
            if hasattr(ent, key):
                setattr(ent, key, val)
            else:
                ent.tags[key] = val
        self._log_event("action", {"entity": entity_name, "action": action})
        return f"⚡ Action applied to '{entity_name}': {action}"

    def add_score(self, points: float) -> str:
        self.score += points
        return f"🏆 Score: {self.score:+.0f} → {self.score}"

    # ── Persistence ───────────────────────────────────────────────────────────

    def save_state(self, path: Optional[str] = None) -> str:
        """Serialise world state to JSON."""
        dest = Path(path) if path else _DEFAULT_STATE_PATH
        try:
            dest.write_text(json.dumps(self.get_state(), indent=2), encoding="utf-8")
            return f"💾 State saved to {dest}"
        except Exception as exc:
            return f"❌ Save failed: {exc}"

    def load_state(self, path: str) -> str:
        """Restore world state from JSON."""
        src = Path(path)
        if not src.exists():
            return f"❌ File not found: {src}"
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
            self.tick = data.get("tick", 0)
            self.score = data.get("score", 0.0)
            self.entities = {
                n: Entity.from_dict(e)
                for n, e in data.get("entities", {}).items()
            }
            self._log_event("load", {"path": str(src)})
            return f"📂 State loaded from {src} ({len(self.entities)} entities)"
        except Exception as exc:
            return f"❌ Load failed: {exc}"

    # ── Event log ─────────────────────────────────────────────────────────────

    def _log_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        entry = {"ts": time.time(), "event": event_type, **payload}
        self._events.append(entry)
        try:
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    def event_log(self, n: int = 20) -> str:
        """Return last *n* event log entries."""
        recent = self._events[-n:]
        if not recent:
            return "Event log is empty."
        lines = [
            f"  [{e['event']}] tick={e.get('tick', '?')} {json.dumps({k: v for k, v in e.items() if k not in ('ts', 'event')})}"
            for e in recent
        ]
        return "Event log (last {}):\n".format(len(recent)) + "\n".join(lines)

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> str:
        """Human-readable engine status."""
        return (
            f"🎮 GameEngine | tick={self.tick} | score={self.score} "
            f"| entities={len(self.entities)} "
            f"| display={'on (pygame)' if _DISPLAY_ENABLED and _PYGAME_AVAILABLE else 'headless'} "
            f"| templates={', '.join(self._TEMPLATES)}"
        )


# ── Singleton helper ──────────────────────────────────────────────────────────
_engine_instance: Optional[GameEngine] = None


def get_game_engine() -> GameEngine:
    """Return the process-level GameEngine singleton, creating it if needed."""
    global _engine_instance  # pylint: disable=global-statement
    if _engine_instance is None:
        _engine_instance = GameEngine()
    return _engine_instance
