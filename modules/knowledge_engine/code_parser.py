#!/usr/bin/env python3
"""
modules/knowledge_engine/code_parser.py

Extract meaningful structural components from Python source files using the
built-in ``ast`` module (no external parser required).

Extracted components:
    - function definitions (with docstrings)
    - class definitions (with docstrings, method names)
    - import statements
    - decorators
    - module-level docstrings

Usage::

    from modules.knowledge_engine.code_parser import CodeParser
    parser = CodeParser()
    result = parser.parse_file("my_module.py")
    snippets = parser.extract_snippets("my_module.py", max_lines=30)
    summary = parser.parse_directory("/path/to/repo")
"""

import ast
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

log = logging.getLogger("CodeParser")

_SUPPORTED_EXTENSIONS = {".py"}
_MAX_FILE_SIZE = 512 * 1024  # 512 KB — skip huge generated files

class CodeParser:
    """
    Parse Python source files and extract structural information.

    The parser never executes code — it only reads source text and builds
    an AST, making it safe to run on untrusted repository files.
    """

    # ── public API ────────────────────────────────────────────────────────────

    def parse_file(self, filepath: str) -> Dict[str, Any]:
        """
        Parse a single Python file.

        Returns dict with keys:
            path, functions, classes, imports, decorators, docstring, error
        """
        result: Dict[str, Any] = {
            "path": filepath,
            "functions": [],
            "classes": [],
            "imports": [],
            "decorators": [],
            "docstring": "",
            "error": None,
        }
        try:
            size = os.path.getsize(filepath)
            if size > _MAX_FILE_SIZE:
                result["error"] = f"file too large ({size} bytes)"
                return result

            source = Path(filepath).read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=filepath)

            result["docstring"] = ast.get_docstring(tree) or ""
            result["functions"] = self._extract_functions(tree)
            result["classes"] = self._extract_classes(tree)
            result["imports"] = self._extract_imports(tree)
            result["decorators"] = self._extract_decorators(tree)
        except SyntaxError as exc:
            result["error"] = f"SyntaxError: {exc}"
        except Exception as exc:  # noqa: BLE001
            result["error"] = str(exc)
        return result

    def parse_directory(
        self,
        directory: str,
        max_files: int = 200,
    ) -> List[Dict[str, Any]]:
        """
        Recursively parse all Python files under *directory*.

        Returns a list of parse_file() results (up to *max_files*).
        """
        results: List[Dict[str, Any]] = []
        for root, _dirs, files in os.walk(directory):
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                results.append(self.parse_file(os.path.join(root, fname)))
                if len(results) >= max_files:
                    return results
        return results

    def extract_snippets(
        self,
        filepath: str,
        max_lines: int = 30,
    ) -> List[Dict[str, str]]:
        """
        Extract short, self-contained code snippets from a file.

        Returns list of dicts with keys: name, kind (function|class), snippet.
        """
        snippets: List[Dict[str, str]] = []
        try:
            source = Path(filepath).read_text(encoding="utf-8", errors="replace")
            lines = source.splitlines()
            tree = ast.parse(source, filename=filepath)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                start = node.lineno - 1
                end = getattr(node, "end_lineno", start + max_lines)
                chunk = "\n".join(lines[start:min(end, start + max_lines)])
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                snippets.append({"name": node.name, "kind": kind, "snippet": chunk})
        except Exception as exc:  # noqa: BLE001
            log.debug("extract_snippets failed for %s: %s", filepath, exc)
        return snippets

    def summarise_repo(self, directory: str) -> Dict[str, Any]:
        """Return a high-level summary of a repository's code structure."""
        files = self.parse_directory(directory)
        total_functions = sum(len(f["functions"]) for f in files)
        total_classes = sum(len(f["classes"]) for f in files)
        all_imports: set = set()
        for f in files:
            all_imports.update(f["imports"])
        return {
            "file_count": len(files),
            "total_functions": total_functions,
            "total_classes": total_classes,
            "unique_imports": sorted(all_imports),
        }

    # ── internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_functions(tree: ast.AST) -> List[Dict[str, Any]]:
        funcs = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.append({
                    "name": node.name,
                    "lineno": node.lineno,
                    "docstring": ast.get_docstring(node) or "",
                    "async": isinstance(node, ast.AsyncFunctionDef),
                })
        return funcs

    @staticmethod
    def _extract_classes(tree: ast.AST) -> List[Dict[str, Any]]:
        classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                methods = [
                    n.name for n in ast.walk(node)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                classes.append({
                    "name": node.name,
                    "lineno": node.lineno,
                    "docstring": ast.get_docstring(node) or "",
                    "methods": methods,
                })
        return classes

    @staticmethod
    def _extract_imports(tree: ast.AST) -> List[str]:
        imports: List[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module.split(".")[0])
        return sorted(set(imports))

    @staticmethod
    def _extract_decorators(tree: ast.AST) -> List[str]:
        decorators: List[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for dec in node.decorator_list:
                if isinstance(dec, ast.Name):
                    decorators.append(dec.id)
                elif isinstance(dec, ast.Attribute):
                    decorators.append(dec.attr)
        return sorted(set(decorators))


if __name__ == "__main__":
    print('Running code_parser.py')
