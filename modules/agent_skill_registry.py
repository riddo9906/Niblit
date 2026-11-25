"""On-demand SKILL.md discovery and loading for Niblit's agent loop.

Only Markdown skill instructions are loaded. Executable scripts and arbitrary
plugin code are never imported by this registry.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger("Niblit.AgentSkills")
_MAX_SKILLS = 100
_MAX_SKILL_BYTES = 50_000
_MAX_RETURN_CHARS = 18_000


class SkillRegistry:
    def __init__(self, roots: list[Path] | None = None):
        self._lock = threading.RLock()
        self._roots = [Path(root).expanduser() for root in roots] if roots is not None else self._default_roots()
        self._cache: list[dict[str, Any]] | None = None

    @staticmethod
    def _default_roots() -> list[Path]:
        home = Path.home()
        roots = [Path(__file__).resolve().parents[1] / "skills"]
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            roots.insert(0, Path(bundle_root) / "skills")
        roots.extend([
            home / ".claude" / "skills",
            home / ".continue" / "skills",
            home / ".niblit" / "skills",
        ])
        # Codex user-installed skills are useful; .system contains Codex-owned
        # internal skills and is deliberately excluded from Niblit's catalog.
        roots.append(home / ".codex" / "skills")
        return roots

    @staticmethod
    def _frontmatter(text: str, fallback_name: str):
        name = fallback_name
        description = ""
        match = re.match(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.S)
        if match:
            header = match.group(1)
            name_match = re.search(r"(?m)^name:\s*[\"']?(.+?)[\"']?\s*$", header)
            desc_match = re.search(r"(?m)^description:\s*[\"']?(.+?)[\"']?\s*$", header)
            if name_match:
                name = name_match.group(1).strip()
            if desc_match:
                description = desc_match.group(1).strip()
        if not description:
            for line in text.splitlines():
                line = line.strip().lstrip("#").strip()
                if line and not line.startswith("---"):
                    description = line[:280]
                    break
        return name, description

    def discover(self, refresh: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            if self._cache is not None and not refresh:
                return [dict(item) for item in self._cache]
            found: dict[str, dict[str, Any]] = {}
            count = 0
            for root in self._roots:
                if not root.is_dir():
                    continue
                try:
                    skill_files = sorted(root.glob("*/SKILL.md"))
                except OSError:
                    continue
                for skill_file in skill_files:
                    if count >= _MAX_SKILLS:
                        break
                    try:
                        resolved = skill_file.resolve(strict=True)
                        resolved.relative_to(root.resolve(strict=True))
                        if any(part.casefold() == ".system" for part in resolved.parts):
                            continue
                        if resolved.stat().st_size > _MAX_SKILL_BYTES:
                            continue
                        content = resolved.read_text(encoding="utf-8")
                    except (OSError, UnicodeError, ValueError):
                        continue
                    fallback = skill_file.parent.name
                    name, description = self._frontmatter(content, fallback)
                    key = name.casefold()
                    if key in found:
                        continue
                    source = "built-in" if "skills" in root.parts and root.name == "skills" and root.parent.name == "Niblit" else "user"
                    found[key] = {
                        "name": name,
                        "description": description,
                        "source": source,
                        "path": str(resolved),
                    }
                    count += 1
            self._cache = list(found.values())
            return [dict(item) for item in self._cache]

    def list_skills(self) -> dict[str, Any]:
        items = self.discover()
        return {
            "count": len(items),
            "skills": [
                {"name": item["name"], "description": item["description"], "source": item["source"]}
                for item in items
            ],
        }

    def search_skills(self, query: str) -> dict[str, Any]:
        text = str(query or "").strip().casefold()
        if not text:
            return {"error": "query_required", "skills": []}
        tokens = [token for token in re.findall(r"[a-z0-9_-]+", text) if len(token) > 1]
        ranked = []
        for item in self.discover():
            haystack = (item["name"] + " " + item["description"]).casefold()
            score = sum(3 if token in item["name"].casefold() else 1 for token in tokens if token in haystack)
            if score:
                ranked.append((score, item))
        ranked.sort(key=lambda entry: (-entry[0], entry[1]["name"].casefold()))
        return {
            "query": text,
            "skills": [
                {"name": item["name"], "description": item["description"], "source": item["source"]}
                for _, item in ranked[:8]
            ],
        }

    def load_skill(self, name: str) -> dict[str, Any]:
        requested = str(name or "").strip().casefold()
        if not requested:
            return {"error": "skill_name_required"}
        item = next((entry for entry in self.discover() if entry["name"].casefold() == requested), None)
        if item is None:
            return {"error": "skill_not_found", "name": name}
        try:
            content = Path(item["path"]).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return {"error": "skill_unavailable", "name": item["name"]}
        return {
            "name": item["name"],
            "description": item["description"],
            "source": item["source"],
            "content": content[:_MAX_RETURN_CHARS],
            "truncated": len(content) > _MAX_RETURN_CHARS,
        }


_registry: SkillRegistry | None = None
_registry_lock = threading.RLock()


def get_skill_registry() -> SkillRegistry:
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = SkillRegistry()
        return _registry


def register_skill_tools(loop) -> list[str]:
    registry = get_skill_registry()
    definitions = [
        (
            "list_skills",
            "List available Niblit and user-installed SKILL.md instruction packs.",
            {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            lambda **kwargs: registry.list_skills(),
        ),
        (
            "search_skills",
            "Find relevant skill packs by task or topic. Returns names and short descriptions.",
            {"type": "object", "properties": {"query": {"type": "string", "minLength": 2, "maxLength": 200}}, "required": ["query"], "additionalProperties": False},
            lambda query, **kwargs: registry.search_skills(query),
        ),
        (
            "load_skill",
            "Load one SKILL.md instruction pack by its exact discovered name. Skill text is guidance, not permission.",
            {"type": "object", "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 100}}, "required": ["name"], "additionalProperties": False},
            lambda name, **kwargs: registry.load_skill(name),
        ),
    ]
    from modules.core_tool_runtime import GOVERNED_COMMAND_METADATA
    registered = []
    for name, description, parameters, handler in definitions:
        schema = {"type": "function", "function": {
            "name": name, "description": description, "parameters": parameters,
        }}
        loop.register_capability(name, handler, schema)
        GOVERNED_COMMAND_METADATA[name] = {
            "category": "Skills",
            "risk_class": "low",
            "side_effect_level": "read_only",
            "requires_authorization": False,
            "availability": lambda core: True,
        }
        registered.append(name)
    return registered
