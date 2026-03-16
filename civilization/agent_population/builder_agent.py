"""BuilderAgent — civilisation agent specialised for code generation.

Usage example::

    agent = BuilderAgent("b1", "builder")
    result = agent.execute({"architecture": {"type": "microservice"}})
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict

from .base_agent import BaseAgent

log = logging.getLogger("BuilderAgent")

_CODE_TEMPLATE = '''"""Auto-generated module for {purpose}."""

class {class_name}:
    """Generated class for {purpose}."""

    def run(self) -> None:
        """Entry point."""
        pass
'''


class BuilderAgent(BaseAgent):
    """Generates code from architecture specifications."""

    # ── public API ──

    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute build task; return code/language/architecture dict."""
        arch = task.get("architecture", {"type": "service", "language": "python"})
        language = arch.get("language", "python")
        code = self.generate_code(arch)
        result = {
            "code": code,
            "language": language,
            "architecture": arch,
            "generated_at": time.time(),
        }
        self._record_task()
        log.info("BuilderAgent %s: generated %s code", self._agent_id, language)
        return result

    def generate_code(self, architecture: Dict[str, Any]) -> str:
        """Generate code stub from *architecture* dict."""
        arch_type = architecture.get("type", "service")
        class_name = arch_type.replace("-", "_").replace(" ", "_").title()
        return _CODE_TEMPLATE.format(purpose=arch_type, class_name=class_name)

    def validate_output(self, code: str) -> bool:
        """Return True if *code* looks like valid Python."""
        try:
            import ast
            ast.parse(code)
            return True
        except SyntaxError:
            return False
