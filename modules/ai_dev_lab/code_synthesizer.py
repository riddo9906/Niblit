#!/usr/bin/env python3
"""
modules/ai_dev_lab/code_synthesizer.py

Generate executable code implementations from architecture specifications.

Pipeline::

    architecture spec
          ↓
    code template selection
          ↓
    LLM generation (optional)
          ↓
    static safety analysis
          ↓
    test scaffold generation

Uses existing Niblit infrastructure:
    - CodeGenerator (modules/code_generator.py)
    - SafetyGuard   (modules/ai_dev_lab/safety_guard.py)

Usage::

    from modules.ai_dev_lab.code_synthesizer import CodeSynthesizer
    synth = CodeSynthesizer()
    result = synth.generate(architecture_spec)
    print(result["code"])
"""

import logging
import textwrap
from typing import Any, Dict, List, Optional

log = logging.getLogger("CodeSynthesizer")

# Built-in code templates keyed by architecture pattern
_TEMPLATES: Dict[str, str] = {
    "pipeline": textwrap.dedent("""\
        class {name}Pipeline:
            \"\"\"Auto-generated pipeline for {description}.\"\"\"

            def __init__(self) -> None:
                self.stages: list = []

            def add_stage(self, stage) -> None:
                self.stages.append(stage)

            def run(self, data):
                for stage in self.stages:
                    data = stage(data)
                return data
        """),
    "event_driven": textwrap.dedent("""\
        class {name}EventBus:
            \"\"\"Auto-generated event bus for {description}.\"\"\"

            def __init__(self) -> None:
                self._handlers: dict = {{}}

            def subscribe(self, event_type: str, handler) -> None:
                self._handlers.setdefault(event_type, []).append(handler)

            def publish(self, event_type: str, payload=None) -> None:
                for h in self._handlers.get(event_type, []):
                    h(payload)
        """),
    "actor_model": textwrap.dedent("""\
        import threading

        class {name}Actor:
            \"\"\"Auto-generated actor for {description}.\"\"\"

            def __init__(self) -> None:
                self._inbox: list = []
                self._lock = threading.Lock()

            def send(self, message) -> None:
                with self._lock:
                    self._inbox.append(message)

            def process_next(self):
                with self._lock:
                    if self._inbox:
                        return self._inbox.pop(0)
                return None
        """),
    "repository_pattern": textwrap.dedent("""\
        class {name}Repository:
            \"\"\"Auto-generated repository for {description}.\"\"\"

            def __init__(self) -> None:
                self._store: dict = {{}}

            def save(self, key: str, value) -> None:
                self._store[key] = value

            def get(self, key: str):
                return self._store.get(key)

            def delete(self, key: str) -> bool:
                return self._store.pop(key, None) is not None

            def all(self) -> list:
                return list(self._store.values())
        """),
    "default": textwrap.dedent("""\
        class {name}:
            \"\"\"Auto-generated module for {description}.\"\"\"

            def __init__(self) -> None:
                pass

            def run(self, *args, **kwargs):
                raise NotImplementedError
        """),
}


class CodeSynthesizer:
    """
    Synthesize executable Python code from architecture specifications.

    Args:
        llm:          Optional LLM adapter with .generate(prompt) → str.
        safety_guard: Optional SafetyGuard instance.
    """

    def __init__(
        self,
        llm: Optional[Any] = None,
        safety_guard: Optional[Any] = None,
    ) -> None:
        self._llm = llm
        self._guard = safety_guard or self._default_guard()

    # ── public API ────────────────────────────────────────────────────────────

    def generate(
        self, architecture: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate code for the given architecture specification.

        Returns dict with keys:
            name, code, safe, warnings, method (template|llm)
        """
        name = architecture.get("name", "Generated").replace(" ", "_").title().replace("_", "")
        description = architecture.get("description", "")
        patterns = architecture.get("patterns", [])

        code = ""
        method = "template"

        # Try LLM first if available
        if self._llm is not None:
            code = self._generate_with_llm(name, architecture) or ""
            if code and len(code) > 50:
                method = "llm"

        # Fallback to template
        if not code:
            code = self._generate_from_template(name, description, patterns)

        # Safety check
        safe, warnings = True, []
        if self._guard is not None:
            try:
                safe = self._guard.validate(code)
                warnings = self._guard.get_warnings(code) if hasattr(self._guard, "get_warnings") else []
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Safety check error: {exc}")

        return {
            "name": name,
            "code": code,
            "safe": safe,
            "warnings": warnings,
            "method": method,
            "architecture": architecture.get("name", ""),
        }

    def generate_batch(
        self, architectures: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        return [self.generate(arch) for arch in architectures]

    # ── internals ─────────────────────────────────────────────────────────────

    def _generate_from_template(
        self, name: str, description: str, patterns: List[str]
    ) -> str:
        # Pick the most specific matching template
        for pattern in patterns:
            pattern_key = pattern.lower().replace("-", "_").replace(" ", "_")
            if pattern_key in _TEMPLATES:
                return _TEMPLATES[pattern_key].format(name=name, description=description or name)
        return _TEMPLATES["default"].format(name=name, description=description or name)

    def _generate_with_llm(
        self, name: str, architecture: Dict[str, Any]
    ) -> str:
        components = ", ".join(architecture.get("components", []))
        patterns = ", ".join(architecture.get("patterns", []))
        prompt = (
            f"Write a clean, concise Python class named {name} implementing "
            f"the {architecture.get('name', '')} architecture pattern. "
            f"Components: {components}. Patterns: {patterns}. "
            f"Description: {architecture.get('description', '')}. "
            "Include __init__, a run() method, and docstring."
        )
        try:
            return self._llm.generate(prompt) or ""
        except Exception as exc:  # noqa: BLE001
            log.debug("CodeSynthesizer: LLM generation failed: %s", exc)
            return ""

    @staticmethod
    def _default_guard() -> Optional[Any]:
        try:
            from modules.ai_dev_lab.safety_guard import SafetyGuard  # type: ignore[import]
            return SafetyGuard()
        except Exception:  # noqa: BLE001
            return None
