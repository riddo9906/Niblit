#!/usr/bin/env python3
"""
CODE GENERATOR MODULE
Generate source code in multiple languages, study language patterns,
learn from templates, and improve code quality over time.

Features:
- Multi-language code generation (Python, JavaScript, Bash, etc.)
- Template library for common patterns
- Study programming language idioms
- Store generated code in KnowledgeDB for future reference
"""

import os
import time
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("CodeGenerator")

# ──────────────────────────────────────────────────────────
# NIBLIT BUILD PATH
# ──────────────────────────────────────────────────────────
# The live Niblit installation directory inside Termux.  Autonomously
# generated .py files are saved here so they can be hot-reloaded and
# pushed to GitHub via GitHubSync.
try:
    from modules.evolve import TERMUX_DEPLOY_PATH as NIBLIT_BUILD_PATH
except Exception:
    NIBLIT_BUILD_PATH = Path(
        "/data/data/com.termux/files/home/NiblitAIOS/Niblit-Modules/Niblit-apk/Niblit"
    )

# ──────────────────────────────────────────────────────────
# LANGUAGE TEMPLATES
# ──────────────────────────────────────────────────────────

_TEMPLATES: Dict[str, Dict[str, str]] = {
    "python": {
        "class": '''class {name}:
    """{docstring}"""

    def __init__(self):
        pass

    def run(self):
        """Run the main logic."""
        pass
''',
        "function": '''def {name}({args}):
    """{docstring}"""
    {body}
''',
        "script": '''#!/usr/bin/env python3
"""{docstring}"""

import sys
import logging

log = logging.getLogger(__name__)


def main():
    """Entry point."""
    pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
''',
        "module": '''#!/usr/bin/env python3
"""{name} module — {docstring}"""

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("{name}")


class {classname}:
    """{classname} implementation."""

    def __init__(self, db: Any = None):
        self.db = db
        log.debug("[{name}] Initialized")

    def run(self) -> Dict[str, Any]:
        """Run the main logic."""
        return {{"status": "ok"}}


if __name__ == "__main__":
    import logging as _logging  # pylint: disable=reimported,ungrouped-imports
    _logging.basicConfig(level=_logging.INFO)
    obj = {classname}()
    print(obj.run())
''',
    },
    "bash": {
        "script": '''#!/usr/bin/env bash
# {name} — {docstring}
set -euo pipefail

# ──────────────────────────────────────
# Config
# ──────────────────────────────────────
LOG_FILE="/tmp/{name}.log"

log() {{
    echo "[$(date +'%H:%M:%S')] $*" | tee -a "$LOG_FILE"
}}

main() {{
    log "Starting {name}..."
    {body}
    log "Done."
}}

main "$@"
''',
        "function": '''# {name}: {docstring}
{name}() {{
    local arg="${{1:-}}"
    {body}
}}
''',
    },
    "javascript": {
        "module": '''/**
 * {name} — {docstring}
 */

'use strict';

class {classname} {{
    constructor() {{
        this.name = '{name}';
    }}

    run() {{
        return {{ status: 'ok' }};
    }}
}}

module.exports = {{ {classname} }};
''',
        "function": '''/**
 * {name} — {docstring}
 * @param {{*}} args
 * @returns {{*}}
 */
function {name}({args}) {{
    {body}
}}

module.exports = {{ {name} }};
''',
    },
    "html": {
        "page": '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
</head>
<body>
    <h1>{title}</h1>
    <p>{description}</p>
</body>
</html>
''',
    },
    "css": {
        "stylesheet": '''/* {name} — {docstring} */

:root {{
    --primary: #007bff;
    --bg: #ffffff;
    --text: #333333;
}}

body {{
    font-family: sans-serif;
    background: var(--bg);
    color: var(--text);
    margin: 0;
    padding: 1rem;
}}
''',
    },
    "sql": {
        "create_table": '''-- {name}: {docstring}
CREATE TABLE IF NOT EXISTS {table_name} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    {fields}
);
''',
    },
    "json": {
        "config": '''{
    "name": "{name}",
    "version": "1.0.0",
    "description": "{docstring}",
    "settings": {{}}
}}
''',
    },
}

# Supported languages
SUPPORTED_LANGUAGES: List[str] = list(_TEMPLATES.keys())

# Language file extensions
_EXTENSIONS: Dict[str, str] = {
    "python": ".py",
    "bash": ".sh",
    "javascript": ".js",
    "html": ".html",
    "css": ".css",
    "sql": ".sql",
    "json": ".json",
    "text": ".txt",
    "markdown": ".md",
    "yaml": ".yaml",
}


class CodeGenerator:
    """
    Multi-language code generator with learning capabilities.

    Usage:
        gen = CodeGenerator(db=knowledge_db)
        code = gen.generate("python", "module", name="my_module", docstring="Does X")
        stats = gen.get_stats()
    """

    def __init__(self, db: Any = None, deploy_path: Optional[str] = None):
        self.db = db
        # Where to save autonomously-generated .py files.  Defaults to the
        # Niblit build directory when running on Termux.
        if deploy_path is not None:
            self.deploy_path: Optional[Path] = Path(deploy_path)
        elif NIBLIT_BUILD_PATH.exists():
            self.deploy_path = NIBLIT_BUILD_PATH
        else:
            self.deploy_path = None
        self._stats: Dict[str, int] = {
            "generated": 0,
            "stored": 0,
        }
        log.debug("[CodeGenerator] Initialized (deploy_path=%s)", self.deploy_path)

    # ──────────────────────────────────────────────────────
    # CORE GENERATION
    # ──────────────────────────────────────────────────────

    def generate(
        self,
        language: str,
        template: str = "module",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Generate code for a given language + template combination.

        Returns: {"code": str, "language": str, "template": str, "success": bool}
        """
        lang = language.lower()
        result: Dict[str, Any] = {
            "language": lang,
            "template": template,
            "success": False,
            "code": "",
            "error": None,
        }

        if lang not in _TEMPLATES:
            result["error"] = (
                f"Language '{language}' not supported. "
                f"Supported: {', '.join(SUPPORTED_LANGUAGES)}"
            )
            return result

        lang_templates = _TEMPLATES[lang]
        if template not in lang_templates:
            available = list(lang_templates.keys())
            template = available[0]
            log.debug("[CodeGenerator] Template not found, using '%s'", template)

        tpl = lang_templates[template]

        # Fill in defaults for missing kwargs
        defaults: Dict[str, str] = {
            "name": "niblit_module",
            "classname": "NiblitModule",
            "docstring": "Auto-generated by Niblit CodeGenerator.",
            "args": "",
            "body": "pass",
            "title": "Niblit",
            "description": "Auto-generated page.",
            "table_name": "data",
            "fields": "value TEXT",
        }
        ctx = {**defaults, **kwargs}

        try:
            code = tpl.format(**ctx)
            result["code"] = code
            result["success"] = True
            self._stats["generated"] += 1
            self._store(lang, template, code, ctx.get("name", "unnamed"))
            log.info("[CodeGenerator] Generated %s/%s for '%s'", lang, template, ctx["name"])
        except KeyError as exc:
            result["error"] = f"Template key error: {exc}"
            log.error("[CodeGenerator] %s", result["error"])

        return result

    def generate_niblit_module(self, name: str, docstring: str = "") -> Dict[str, Any]:
        """Shortcut: generate a standard Niblit Python module."""
        classname = "".join(w.capitalize() for w in name.split("_"))
        return self.generate(
            "python",
            "module",
            name=name,
            classname=classname,
            docstring=docstring or f"Niblit module: {name}",
        )

    def save_to_deploy(self, name: str, code: str) -> Dict[str, Any]:
        """Save generated Python code to the Niblit build (deploy) directory.

        The file is written to *self.deploy_path/<name>.py* so it can be
        hot-reloaded by the LiveUpdater and pushed to GitHub via GitHubSync.

        Returns {"path": str, "success": bool, "error": Optional[str]}.
        """
        result: Dict[str, Any] = {"path": None, "success": False, "error": None}
        if not self.deploy_path:
            result["error"] = "deploy_path not set — not running on Termux"
            return result

        # Ensure the name is a valid filename
        safe_name = name.replace(" ", "_").replace("-", "_")
        if not safe_name.endswith(".py"):
            safe_name = safe_name + ".py"

        try:
            self.deploy_path.mkdir(parents=True, exist_ok=True)
            fpath = self.deploy_path / safe_name
            fpath.write_text(code, encoding="utf-8")
            result["path"] = str(fpath)
            result["success"] = True
            self._stats["stored"] = self._stats.get("stored", 0) + 1
            log.info("[CodeGenerator] Saved %s to deploy path", safe_name)
        except OSError as exc:
            result["error"] = str(exc)
            log.debug("[CodeGenerator] save_to_deploy failed: %s", exc)

        return result

    def get_deploy_path(self) -> Optional[str]:
        """Return the current deploy path as a string, or None."""
        return str(self.deploy_path) if self.deploy_path else None

    # ──────────────────────────────────────────────────────
    # LANGUAGE STUDY
    # ──────────────────────────────────────────────────────

    def study_language(self, language: str) -> str:
        """Return idioms and best practices for a language."""
        tips: Dict[str, List[str]] = {
            "python": [
                "Use type hints for all function signatures.",
                "Prefer f-strings for string formatting.",
                "Use dataclasses or namedtuples for data containers.",
                "Handle exceptions as specifically as possible.",
                "Use context managers (with) for resource management.",
                "Prefer list comprehensions over map/filter for clarity.",
                "Follow PEP 8 — snake_case for functions/variables, PascalCase for classes.",
                "Use logging instead of print() for production code.",
                "Write docstrings for all public functions and classes.",
                "Use pathlib.Path instead of os.path for file operations.",
            ],
            "bash": [
                "Use 'set -euo pipefail' at the top of every script.",
                "Quote all variables: \"$var\" not $var.",
                "Use [[ ]] instead of [ ] for conditionals.",
                "Prefer $() over backticks for command substitution.",
                "Use local variables in functions.",
                "Check command existence with command -v before using it.",
                "Use trap to clean up temp files on exit.",
                "Avoid parsing ls output; use globs or find instead.",
            ],
            "javascript": [
                "Use 'use strict' or ES modules.",
                "Prefer const/let over var.",
                "Use async/await over raw Promises for clarity.",
                "Use === (strict equality) not ==.",
                "Destructure objects and arrays when possible.",
                "Use arrow functions for callbacks.",
                "Handle Promise rejections with .catch() or try/catch.",
                "Use template literals instead of string concatenation.",
            ],
        }

        lang = language.lower()
        if lang not in tips:
            return f"No study material for '{language}'. Available: {', '.join(tips)}"

        lines = [f"📚 **{language.capitalize()} Best Practices:**\n"]
        for i, tip in enumerate(tips[lang], 1):
            lines.append(f"  {i:2d}. {tip}")

        result = "\n".join(lines)

        # Queue this topic for deeper research
        if self.db and hasattr(self.db, "queue_learning"):
            self.db.queue_learning(f"{language} programming patterns")

        return result

    def list_templates(self, language: Optional[str] = None) -> str:
        """List available templates."""
        if language:
            lang = language.lower()
            if lang in _TEMPLATES:
                tmpls = list(_TEMPLATES[lang].keys())
                return f"Templates for {language}: {', '.join(tmpls)}"
            return f"Language '{language}' not found. Use: {', '.join(SUPPORTED_LANGUAGES)}"

        lines = ["📋 **Available Code Templates:**\n"]
        for lang, tmpls in _TEMPLATES.items():
            lines.append(f"  {lang:<15}  {', '.join(tmpls.keys())}")
        return "\n".join(lines)

    # ──────────────────────────────────────────────────────
    # STATS
    # ──────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Return generation statistics."""
        return {
            "stats": self._stats,
            "supported_languages": SUPPORTED_LANGUAGES,
            "total_templates": sum(len(v) for v in _TEMPLATES.values()),
        }

    def _store(self, language: str, template: str, code: str, name: str) -> None:
        """Store generated code snippet in KnowledgeDB."""
        if not self.db:
            return
        key = f"generated_code:{language}:{name}:{int(time.time())}"
        snippet = {"language": language, "template": template, "name": name, "code": code[:500]}
        try:
            if hasattr(self.db, "add_fact"):
                self.db.add_fact(key, str(snippet), ["code", "generated", language])
            elif hasattr(self.db, "store_learning"):
                self.db.store_learning({"key": key, "data": snippet, "ts": time.time()})
            self._stats["stored"] += 1
        except Exception as exc:
            log.debug("[CodeGenerator] Store failed: %s", exc)

    def get_extension(self, language: str) -> str:
        """Return the file extension for a language."""
        return _EXTENSIONS.get(language.lower(), ".txt")


# ──────────────────────────────────────────────────────
# STANDALONE SELF-TEST
# ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import logging as _logging  # pylint: disable=reimported,ungrouped-imports
    _logging.basicConfig(level=_logging.INFO, format="%(message)s")
    print("=== CodeGenerator self-test ===\n")

    gen = CodeGenerator()

    result = gen.generate("python", "module", name="test_module", docstring="Test module.")
    print(f"Generated Python module:\n{result['code'][:200]}...")

    print(gen.list_templates())
    print()
    print(gen.study_language("python"))
    print()
    print("Stats:", gen.get_stats())
    print("CodeGenerator OK")
