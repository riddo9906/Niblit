"""modules/workspace_tools.py — Phase 5D governed LLM workspace surface.

One governed read/write view over the EXISTING Niblit file authorities:

    list/read  -> core.renderers (the SAME authority the UI file tab uses:
                  get_file_metadata + RendererFactory.render_file, whose
                  CodeRenderer returns the real source as raw_content)
    write/edit -> modules.filesystem_manager.FilesystemManager
                  (write_file_safe / patch_file, both with automatic backups)
    tests      -> bounded `python -m pytest <path> -q` subprocess
    events     -> the process EventBus (no new event system)

Governance (this module is the ONLY place the LLM touches the filesystem):
    - one authorized workspace root (env NIBLIT_WORKSPACE_ROOT, default:
      the Niblit repository root);
    - path normalization + traversal/absolute-path rejection;
    - secret-file deny-list (.env, keys, tokens, credentials, .git);
    - text-extension allow-list; binary files never read;
    - hard caps: file size, returned characters, list entries, search
      results, scanned files, subprocess timeout;
    - every mutation emits code.change.* events; reads/searches emit
      workspace.* events; test runs emit tests.* events. Failures are
      structured, never raised raw into the reasoning loop.
"""

from __future__ import annotations

import logging
import ast
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path, PureWindowsPath
from typing import Any, Dict, List, Optional

from modules.event_bus import get_event_bus
from modules.event_bus import NiblitEvent

log = logging.getLogger("Niblit.WorkspaceTools")

EVENT_SOURCE = "workspace_tools"

# ---------------------------------------------------------------------------
# Governance policy
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _default_root() -> Path:
    env = os.environ.get("NIBLIT_WORKSPACE_ROOT", "").strip()
    if env:
        return Path(env).resolve()
    return _REPO_ROOT


# Text/code extensions the LLM may read or write (restricted to text).
ALLOWED_EXTENSIONS = {
    ".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".ts", ".tsx", ".js", ".jsx", ".css", ".html", ".sh", ".bash", ".sql",
    ".csv", ".rst", ".xml", ".conf", ".log",
}

# Extensionless basenames that are legitimately text and useful.
ALLOWED_BASENAMES = {
    "dockerfile", "makefile", "license", "readme", "changelog",
    ".gitignore", ".dockerignore", ".editorconfig",
}

# Filenames/directory names the LLM may never read or write.
SECRET_NAME_PATTERNS = (
    re.compile(r"^\.env"),
    re.compile(r"secret"),
    re.compile(r"password"),
    re.compile(r"credential"),
    re.compile(r"token"),
    re.compile(r"api[_-]?key"),
    re.compile(r"_keys?$"),
    re.compile(r"\.pem$"),
    re.compile(r"\.key$"),
    re.compile(r"\.p12$"),
    re.compile(r"\.pfx$"),
    re.compile(r"id_rsa"),
    re.compile(r"id_ed25519"),
    re.compile(r"\.htpasswd$"),
)
SECRET_DIR_NAMES = {".git", ".ssh", "secrets", "__pycache__", "node_modules",
                    "niblit-env", "venv", ".venv"}

MAX_LIST_ENTRIES = 200
MAX_SEARCH_RESULTS = 30
MAX_SCAN_FILES = 600
MAX_SCAN_DIRECTORIES = 2_000
MAX_FILE_BYTES = 400_000          # files larger than this are never scanned
MAX_READ_CHARS = 24_000           # per-read character budget (tool result)
MAX_PDF_BYTES = 20_000_000        # PDFs are parsed only after this size check
MAX_PDF_PAGES = 60                # never parse an unbounded document
MAX_PDF_TEXT_CHARS = 30_000       # bounded model context per PDF read
MAX_AST_NODES = 20_000            # bound structural parsing work/output
MAX_AST_DEFINITIONS = 500
MAX_AST_IMPORTS = 500
MAX_WRITE_BYTES = 200_000         # per-write content budget
TEST_TIMEOUT_SECONDS = 600
MAX_TEST_OUTPUT_CHARS = 4_000


class WorkspacePolicyError(ValueError):
    """A workspace request violated the governance policy."""


def _is_secret_name(name: str) -> bool:
    lowered = name.lower()
    if lowered in SECRET_DIR_NAMES:
        return True
    return any(p.search(lowered) for p in SECRET_NAME_PATTERNS)


def _is_allowed_text_name(name: str) -> bool:
    p = Path(name)
    if p.suffix:
        return p.suffix.lower() in ALLOWED_EXTENSIONS
    return p.name.lower() in ALLOWED_BASENAMES


def _safe_resolve(root: Path, rel_path: str) -> Path:
    """Resolve *rel_path* inside *root*; reject anything else.

    Rejects: empty paths, absolute paths, traversal escapes, and secret
    filenames/directories anywhere along the relative path.
    """
    if not isinstance(rel_path, str) or not rel_path.strip():
        raise WorkspacePolicyError("path is required")
    if "\x00" in rel_path:
        raise WorkspacePolicyError("path contains an invalid character")
    candidate = Path(rel_path)
    windows_candidate = PureWindowsPath(rel_path)
    if (candidate.is_absolute() or candidate.drive or candidate.root
            or windows_candidate.is_absolute() or windows_candidate.drive
            or windows_candidate.root):
        raise WorkspacePolicyError(
            f"absolute paths are not permitted ({rel_path!r})")
    if any(part in ("..",) for part in candidate.parts) or any(
            part == ".." for part in windows_candidate.parts):
        raise WorkspacePolicyError(
            f"path traversal is not permitted ({rel_path!r})")
    if any(_is_secret_name(part) for part in candidate.parts):
        raise WorkspacePolicyError(
            f"path touches a protected/secret location ({rel_path!r})")
    try:
        resolved = (root / candidate).resolve()
        root_resolved = root.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise WorkspacePolicyError("path could not be safely resolved") from exc
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise WorkspacePolicyError(
            f"resolved path escapes the workspace root ({rel_path!r})")
    # Check the resolved path too: an innocent-looking symlink inside the
    # workspace must not alias a protected file or directory.
    try:
        resolved_parts = resolved.relative_to(root_resolved).parts
    except ValueError as exc:
        raise WorkspacePolicyError(
            f"resolved path escapes the workspace root ({rel_path!r})") from exc
    if any(_is_secret_name(part) for part in resolved_parts):
        raise WorkspacePolicyError(
            f"resolved path touches a protected/secret location ({rel_path!r})")
    return resolved


def _emit(event_bus, event_type: str, payload: Dict[str, Any]) -> None:
    if event_bus is None:
        return
    try:
        event_bus.publish(NiblitEvent(
            type=event_type, source=EVENT_SOURCE, payload=payload))
    except Exception as exc:  # events never abort the operation
        log.warning("[Workspace] publish failed for %s: %s", event_type, exc)


# ---------------------------------------------------------------------------
# Read surface (list / search / read) — same authorities as the UI
# ---------------------------------------------------------------------------

def list_workspace(sub_path: str = "", max_entries: Any = None,
                   event_bus=None) -> Dict[str, Any]:
    """Bounded one-level directory listing with UI-equivalent metadata."""
    root = _default_root()
    try:
        target = _safe_resolve(root, sub_path or ".")
    except WorkspacePolicyError as exc:
        return {"error": str(exc), "path": sub_path}
    if not target.exists():
        return {"error": "not_found", "path": sub_path}
    if not target.is_dir():
        return {"error": "not_a_directory", "path": sub_path}

    try:
        limit = max(1, min(int(max_entries or MAX_LIST_ENTRIES),
                           MAX_LIST_ENTRIES))
    except (TypeError, ValueError):
        limit = MAX_LIST_ENTRIES

    # Reuse the UI's metadata authority.
    from core.renderers.file_utils import get_file_metadata

    entries: List[Dict[str, Any]] = []
    truncated = False
    try:
        children = sorted(target.iterdir(), key=lambda p: p.name.lower())
    except OSError as exc:
        return {"error": f"list_failed: {exc}", "path": sub_path}
    for item in children:
        if len(entries) >= limit:
            truncated = True
            break
        if _is_secret_name(item.name):
            continue
        item_rel = str(item.relative_to(root)).replace("\\", "/")
        try:
            safe_item = _safe_resolve(root, item_rel)
        except (WorkspacePolicyError, OSError):
            continue
        entry: Dict[str, Any] = {
            "name": item.name,
            "path": item_rel,
            "type": "dir" if safe_item.is_dir() else "file",
        }
        if safe_item.is_file():
            meta = get_file_metadata(str(safe_item))
            if meta is not None:
                entry.update({
                    "size": meta.size,
                    "modified_at": meta.modified,
                    "extension": meta.extension,
                    "type_category": meta.type_category,
                })
        entries.append(entry)
    _emit(event_bus, "workspace.inspection.started",
          {"action": "list", "path": sub_path, "entries": len(entries)})
    return {"path": sub_path or ".", "entries": entries,
            "count": len(entries), "truncated": truncated}


def _collect_text_files(root: Path, sub_path: str):
    """Return (files, hit_cap): bounded text-file candidates for scanning."""
    base = _safe_resolve(root, sub_path) if sub_path else root
    if base.is_file():
        return [base], False
    files: List[Path] = []
    hit_cap = False
    stack = [base]
    visited: set[Path] = set()
    while stack and len(files) < MAX_SCAN_FILES:
        current = stack.pop()
        try:
            current = current.resolve()
            if current in visited:
                continue
            visited.add(current)
        except (OSError, RuntimeError):
            continue
        if len(visited) > MAX_SCAN_DIRECTORIES:
            hit_cap = True
            break
        try:
            children = sorted(current.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue
        for child in children:
            if len(files) >= MAX_SCAN_FILES:
                hit_cap = True
                break
            if _is_secret_name(child.name):
                continue
            relative = str(child.relative_to(root)).replace("\\", "/")
            try:
                safe_child = _safe_resolve(root, relative)
            except (WorkspacePolicyError, OSError):
                continue
            if child.is_dir():
                stack.append(safe_child)
                continue
            if not safe_child.is_file():
                continue
            if (safe_child.suffix.lower() != ".pdf"
                    and not _is_allowed_text_name(safe_child.name)):
                continue
            try:
                max_bytes = (MAX_PDF_BYTES if safe_child.suffix.lower() == ".pdf"
                             else MAX_FILE_BYTES)
                if safe_child.stat().st_size > max_bytes:
                    continue
            except OSError:
                continue
            files.append(safe_child)
    return files, hit_cap


def search_workspace(query: str, sub_path: str = "", max_results: Any = None,
                     event_bus=None) -> Dict[str, Any]:
    """Bounded filename + content search (real grep over real files)."""
    root = _default_root()
    query = str(query or "").strip()
    if not query:
        return {"error": "empty_query"}
    if len(query) > 200:
        query = query[:200]
    try:
        limit = max(1, min(int(max_results or MAX_SEARCH_RESULTS),
                           MAX_SEARCH_RESULTS))
    except (TypeError, ValueError):
        limit = MAX_SEARCH_RESULTS

    lowered = query.lower()
    matches: List[Dict[str, Any]] = []
    name_matches: List[str] = []
    truncated = False
    try:
        files, scan_cap_hit = _collect_text_files(root, sub_path)
        for file_path in files:
            rel = str(file_path.relative_to(root)).replace("\\", "/")
            if lowered in file_path.name.lower() and len(name_matches) < limit:
                name_matches.append(rel)
            # PDFs are discoverable by name, but binary bytes are never fed to
            # the text search loop. Their contents use workspace_read_pdf.
            if file_path.suffix.lower() == ".pdf":
                continue
            try:
                with open(file_path, "r", encoding="utf-8",
                          errors="ignore") as fh:
                    for line_no, line in enumerate(fh, start=1):
                        if lowered in line.lower():
                            if len(matches) >= limit:
                                truncated = True
                                break
                            matches.append({
                                "path": rel,
                                "line_number": line_no,
                                "line_text": line.strip()[:240],
                            })
            except OSError:
                continue
            if truncated:
                break
    except WorkspacePolicyError as exc:
        return {"error": str(exc), "path": sub_path}
    _emit(event_bus, "workspace.search.completed", {
        "query": query, "path": sub_path,
        "content_matches": len(matches), "name_matches": len(name_matches),
        "truncated": truncated or scan_cap_hit})
    return {"query": query, "path": sub_path or ".",
            "content_matches": matches, "name_matches": name_matches,
            "count": len(matches) + len(name_matches),
            "truncated": truncated or scan_cap_hit}


def read_workspace(rel_path: str, max_chars: Any = None,
                   event_bus=None) -> Dict[str, Any]:
    """Read REAL file content through the UI's render authority.

    Returns the actual source (CodeRenderer.raw_content) — never a summary.
    """
    root = _default_root()
    try:
        target = _safe_resolve(root, rel_path)
    except WorkspacePolicyError as exc:
        return {"error": str(exc), "path": rel_path}
    if not target.exists() or not target.is_file():
        return {"error": "not_found", "path": rel_path}
    if not _is_allowed_text_name(target.name):
        return {"error": f"file type not permitted: {target.name!r}",
                "path": rel_path}
    try:
        size = target.stat().st_size
    except OSError as exc:
        return {"error": f"stat_failed: {exc}", "path": rel_path}
    if size > MAX_FILE_BYTES:
        return {"error": f"file too large ({size} > {MAX_FILE_BYTES} bytes)",
                "path": rel_path}

    try:
        limit = max(200, min(int(max_chars or MAX_READ_CHARS), MAX_READ_CHARS))
    except (TypeError, ValueError):
        limit = MAX_READ_CHARS

    # Same authority the UI uses: RendererFactory.render_file.
    content: Optional[str] = None
    language = ""
    try:
        from core.renderers import RendererFactory
        result = RendererFactory.render_file(str(target))
        if result.success and result.raw_content:
            content = result.raw_content
            if isinstance(result.content, dict):
                language = str(result.content.get("language", ""))
    except Exception as exc:  # renderer optional-dep failures etc.
        log.debug("[Workspace] renderer fallback for %s: %s", rel_path, exc)

    if content is None:
        # Bounded direct read for text files without a renderer.
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {"error": f"read_failed: {exc}", "path": rel_path}

    truncated = len(content) > limit
    if truncated:
        content = content[:limit]
    _emit(event_bus, "workspace.file.read", {
        "path": rel_path, "size": size, "truncated": truncated})
    return {
        "path": rel_path,
        "content": content,
        "language": language,
        "size": size,
        "truncated": truncated,
        "returned_chars": len(content),
        "line_start": 1,
        "line_end": content.count("\n") + (1 if content else 0),
    }


def read_workspace_pdf(rel_path: str, event_bus=None) -> Dict[str, Any]:
    """Extract bounded, page-aware text from a PDF inside the authorized root.

    This is a read-only extraction tool. It does not perform OCR, execute PDF
    actions, or persist extracted content. Image-only documents are reported
    as requiring OCR instead of being described as understood.
    """
    root = _default_root()
    try:
        target = _safe_resolve(root, rel_path)
    except WorkspacePolicyError as exc:
        return {"error": str(exc), "path": rel_path}
    if not target.exists() or not target.is_file():
        return {"error": "not_found", "path": rel_path}
    if target.suffix.lower() != ".pdf":
        return {"error": "pdf_file_required", "path": rel_path}
    try:
        size = target.stat().st_size
    except OSError:
        return {"error": "stat_failed", "path": rel_path}
    if size > MAX_PDF_BYTES:
        return {"error": "pdf_too_large", "path": rel_path,
                "size": size, "max_bytes": MAX_PDF_BYTES}

    try:
        from pypdf import PdfReader
    except ImportError:
        PdfReader = None
    try:
        pages = []
        text_parts = []
        chars_remaining = MAX_PDF_TEXT_CHARS
        if PdfReader is not None:
            reader = PdfReader(str(target), strict=False)
            if reader.is_encrypted:
                try:
                    decrypted = reader.decrypt("")
                except Exception:
                    decrypted = 0
                if not decrypted:
                    return {"error": "encrypted_pdf", "path": rel_path}
            page_count = len(reader.pages)
            page_iter = enumerate(reader.pages[:MAX_PDF_PAGES], start=1)
            for index, page in page_iter:
                if chars_remaining <= 0:
                    break
                page_text = str(page.extract_text() or "").strip()
                if not page_text:
                    continue
                page_text = page_text[:chars_remaining]
                chars_remaining -= len(page_text)
                pages.append({"page": index, "text": page_text})
                text_parts.append(f"[Page {index}]\n{page_text}")
        else:
            # Some supported deployments install pdfplumber as their parser
            # rather than pypdf. Keep the same bounds and page-aware output.
            import pdfplumber
            with pdfplumber.open(str(target)) as pdf:
                page_count = len(pdf.pages)
                for index, page in enumerate(pdf.pages[:MAX_PDF_PAGES], start=1):
                    if chars_remaining <= 0:
                        break
                    page_text = str(page.extract_text() or "").strip()
                    if not page_text:
                        continue
                    page_text = page_text[:chars_remaining]
                    chars_remaining -= len(page_text)
                    pages.append({"page": index, "text": page_text})
                    text_parts.append(f"[Page {index}]\n{page_text}")
    except Exception as exc:
        if isinstance(exc, ImportError):
            return {"error": "pdf_parser_unavailable",
                    "detail": "Install pypdf or pdfplumber."}
        log.info("PDF extraction failed for authorized workspace file: %s",
                 type(exc).__name__)
        return {"error": "invalid_or_unsupported_pdf", "path": rel_path}

    text = "\n\n".join(text_parts)
    truncated = page_count > MAX_PDF_PAGES or chars_remaining <= 0
    if not text:
        return {"error": "no_extractable_text", "path": rel_path,
                "page_count": page_count, "needs_ocr": True}
    _emit(event_bus, "workspace.pdf.read", {
        "path": rel_path, "page_count": page_count,
        "pages_extracted": len(pages), "truncated": truncated})
    return {"path": rel_path, "page_count": page_count,
            "pages_extracted": len(pages), "pages": pages,
            "text": text, "size": size, "truncated": truncated,
            "needs_ocr": False}


def inspect_python_workspace(rel_path: str, event_bus=None) -> Dict[str, Any]:
    """Parse an authorized Python source file without importing or executing it."""
    root = _default_root()
    try:
        target = _safe_resolve(root, rel_path)
    except WorkspacePolicyError as exc:
        return {"error": str(exc), "path": rel_path}
    if not target.exists() or not target.is_file():
        return {"error": "not_found", "path": rel_path}
    if target.suffix.lower() != ".py":
        return {"error": "python_source_required", "path": rel_path}
    try:
        size = target.stat().st_size
    except OSError as exc:
        return {"error": f"stat_failed: {exc}", "path": rel_path}
    if size > MAX_FILE_BYTES:
        return {"error": f"file too large ({size} > {MAX_FILE_BYTES} bytes)",
                "path": rel_path}
    try:
        source = target.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError as exc:
        return {
            "error": "syntax_error",
            "path": rel_path,
            "line": exc.lineno,
            "column": exc.offset,
            "message": (exc.msg or "invalid Python syntax")[:300],
        }
    except (OSError, UnicodeError) as exc:
        return {"error": f"read_failed: {exc}", "path": rel_path}
    except (RecursionError, MemoryError) as exc:
        return {"error": "parse_resource_limit", "path": rel_path,
                "detail": type(exc).__name__}

    node_count = 0
    node_limit_hit = False
    imports: List[Dict[str, Any]] = []
    definitions: List[Dict[str, Any]] = []
    class_stack: List[str] = []
    imports_truncated = False

    class Collector(ast.NodeVisitor):
        def visit_ClassDef(self, node):
            definitions.append({
                "kind": "class", "name": node.name,
                "line_start": node.lineno,
                "line_end": getattr(node, "end_lineno", node.lineno),
                "docstring": (ast.get_docstring(node) or "")[:500],
            })
            class_stack.append(node.name)
            self.generic_visit(node)
            class_stack.pop()

        def _visit_function(self, node):
            definitions.append({
                "kind": "method" if class_stack else "function",
                "name": node.name,
                **({"class": class_stack[-1]} if class_stack else {}),
                "line_start": node.lineno,
                "line_end": getattr(node, "end_lineno", node.lineno),
                "docstring": (ast.get_docstring(node) or "")[:500],
            })
            self.generic_visit(node)

        visit_FunctionDef = _visit_function
        visit_AsyncFunctionDef = _visit_function

        def visit_Import(self, node):
            nonlocal imports_truncated
            for alias in node.names:
                if len(imports) >= MAX_AST_IMPORTS:
                    imports_truncated = True
                    continue
                imports.append({"module": alias.name, "line": node.lineno,
                                "alias": alias.asname})

        def visit_ImportFrom(self, node):
            nonlocal imports_truncated
            if len(imports) >= MAX_AST_IMPORTS:
                imports_truncated = True
                return
            imports.append({
                "module": node.module or "",
                "level": node.level,
                "names": [alias.name for alias in node.names[:50]],
                "line": node.lineno,
            })

    for node in ast.walk(tree):
        node_count += 1
        if node_count > MAX_AST_NODES:
            node_limit_hit = True
            break
    if node_limit_hit:
        return {"error": "parse_node_limit", "path": rel_path,
                "max_nodes": MAX_AST_NODES}

    collector = Collector()
    collector.visit(tree)
    definitions_truncated = len(definitions) > MAX_AST_DEFINITIONS
    definitions = definitions[:MAX_AST_DEFINITIONS]
    imports = imports[:MAX_AST_IMPORTS]
    result = {
        "path": rel_path,
        "size": size,
        "line_count": len(source.splitlines()),
        "module_docstring": (ast.get_docstring(tree) or "")[:1000],
        "imports": imports,
        "definitions": definitions,
        "counts": {"imports": len(imports), "definitions": len(definitions),
                   "ast_nodes": node_count},
        "truncated": {"imports": imports_truncated,
                      "definitions": definitions_truncated},
    }
    _emit(event_bus, "workspace.python.inspected", {
        "path": rel_path, "imports": len(imports),
        "definitions": len(definitions),
    })
    return result


# ---------------------------------------------------------------------------
# Write surface — delegates to the existing FilesystemManager authority
# ---------------------------------------------------------------------------

def _filesystem_manager():
    from modules.filesystem_manager import FilesystemManager
    return FilesystemManager(base_dir=str(_default_root()))


def _precheck_write(rel_path: str, content: str) -> Dict[str, Any]:
    root = _default_root()
    try:
        target = _safe_resolve(root, rel_path)
    except WorkspacePolicyError as exc:
        return {"error": str(exc), "path": rel_path}
    if not _is_allowed_text_name(target.name):
        return {"error": f"file type not permitted: {target.name!r}",
                "path": rel_path}
    payload = content.encode("utf-8", errors="replace")
    if len(payload) > MAX_WRITE_BYTES:
        return {"error": (f"content too large ({len(payload)} > "
                          f"{MAX_WRITE_BYTES} bytes)"), "path": rel_path}
    return {"ok": True, "target": target, "root": root}


def write_workspace(rel_path: str, content: str,
                    event_bus=None) -> Dict[str, Any]:
    """Create/overwrite a workspace text file (auto-backup on replace)."""
    if not isinstance(content, str) or not content.strip():
        return {"error": "content is required", "path": rel_path}
    check = _precheck_write(rel_path, content)
    if "error" in check:
        return check
    target, root = check["target"], check["root"]
    _emit(event_bus, "code.change.started",
          {"action": "write", "path": rel_path, "bytes": len(content)})
    fm = _filesystem_manager()
    result = fm.write_file_safe(str(target), content, backup=True)
    ok = bool(result.get("success"))
    payload = {
        "action": "write", "path": rel_path,
        "success": ok, "error": result.get("error"),
        "backup_path": result.get("backup_path", ""),
    }
    _emit(event_bus, "code.change.completed", payload)
    if not ok:
        return {"error": result.get("error") or "write_failed",
                "path": rel_path}
    return {"path": rel_path, "written": True,
            "backup_path": result.get("backup_path", ""),
            "workspace_root": str(root)}


def edit_workspace(rel_path: str, old_text: str, new_text: str,
                   event_bus=None) -> Dict[str, Any]:
    """Exact-match patch (must match exactly once) with automatic backup.

    Byte-faithful: content is decoded WITHOUT newline translation and the
    patched content is written through FilesystemManager.write_file_safe
    (atomic + backup, itself newline-faithful). The exactly-once guard is
    enforced HERE so the LLM can never perform an ambiguous multi-site
    replacement, and a no-match edit is always an explicit error.
    """
    if not isinstance(old_text, str) or not old_text:
        return {"error": "old_text is required", "path": rel_path}
    if not isinstance(new_text, str):
        return {"error": "new_text must be a string", "path": rel_path}
    check = _precheck_write(rel_path, old_text + new_text)
    if "error" in check:
        return check
    target, root = check["target"], check["root"]
    try:
        raw = target.read_bytes()
        current = raw.decode("utf-8", errors="replace")  # no \n translation
    except OSError as exc:
        return {"error": f"read_failed: {exc}", "path": rel_path}
    occurrences = current.count(old_text)
    if occurrences == 0:
        return {"error": "old_text not found in file", "path": rel_path}
    if occurrences > 1:
        return {"error": (f"old_text matches {occurrences} times; "
                          "it must match exactly once"), "path": rel_path}
    _emit(event_bus, "code.change.started",
          {"action": "edit", "path": rel_path})
    patched = current.replace(old_text, new_text, 1)
    fm = _filesystem_manager()
    result = fm.write_file_safe(str(target), patched, backup=True)
    ok = bool(result.get("success"))
    payload = {
        "action": "edit", "path": rel_path,
        "success": ok, "error": result.get("error"),
        "backup_path": result.get("backup_path", ""),
    }
    _emit(event_bus, "code.change.completed", payload)
    if not ok:
        return {"error": result.get("error") or "edit_failed",
                "path": rel_path}
    return {"path": rel_path, "edited": True,
            "backup_path": result.get("backup_path", ""),
            "workspace_root": str(root)}


# ---------------------------------------------------------------------------
# Bounded test runner
# ---------------------------------------------------------------------------

_TESTS_LOCK = threading.Lock()


def _is_test_file(rel_path: str) -> bool:
    p = Path(rel_path)
    parts = {part.lower() for part in p.parts}
    return (p.name.startswith("test_") and p.suffix == ".py") or (
        "tests" in parts and p.suffix == ".py")


def run_tests(test_path: str, timeout: Any = None,
              event_bus=None) -> Dict[str, Any]:
    """Run ONE bounded pytest invocation on a workspace test path.

    Fixed command template (no shell, no arbitrary commands): the only
    parameter is a validated in-workspace test path.
    """
    root = _default_root()
    try:
        target = _safe_resolve(root, test_path)
    except WorkspacePolicyError as exc:
        return {"error": str(exc), "path": test_path}
    if not target.exists() or not target.is_file():
        return {"error": "not_found", "path": test_path}
    if not _is_test_file(test_path):
        return {"error": ("only test paths (tests/… or test_*.py) may be "
                          "executed"), "path": test_path}
    try:
        timeout_s = max(30, min(int(timeout or TEST_TIMEOUT_SECONDS), 900))
    except (TypeError, ValueError):
        timeout_s = TEST_TIMEOUT_SECONDS

    if not _TESTS_LOCK.acquire(blocking=False):
        return {"error": "test_run_in_progress",
                "detail": "one bounded test run at a time"}
    _emit(event_bus, "tests.started", {"path": test_path})
    t0 = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(target), "-q",
             "-o", "addopts=", "--no-header", "-p", "no:cacheprovider"],
            cwd=str(root), capture_output=True, text=True,
            timeout=timeout_s, encoding="utf-8", errors="replace",
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        summary = {
            "path": test_path,
            "returncode": proc.returncode,
            "passed": proc.returncode == 0,
            "duration_s": round(time.time() - t0, 1),
            "output_tail": output[-MAX_TEST_OUTPUT_CHARS:],
        }
    except subprocess.TimeoutExpired:
        summary = {"path": test_path, "returncode": None, "passed": False,
                   "error": f"timeout after {timeout_s}s",
                   "duration_s": round(time.time() - t0, 1),
                   "output_tail": ""}
    except OSError as exc:
        summary = {"path": test_path, "returncode": None, "passed": False,
                   "error": str(exc)[:200], "output_tail": ""}
    finally:
        _TESTS_LOCK.release()
    _emit(event_bus, "tests.completed", {
        "path": test_path, "passed": summary.get("passed"),
        "returncode": summary.get("returncode")})
    return summary
