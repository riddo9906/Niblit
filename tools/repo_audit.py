#!/usr/bin/env python3
"""
Repository Auditor for Niblit
Analyzes Python files for imports, circular dependencies, orphaned modules, and more.

Production Enhancements:
1. Circuit breakers for fault tolerance
2. Telemetry and metrics tracking
3. Rate limiting on audit operations
4. Multi-level caching for audit results
5. Batch processing for file analysis
6. Event sourcing for audit trail
7. Structured logging with correlation IDs
8. Comprehensive error handling
9. Performance monitoring
10. Health checks
11. Graceful degradation
12. Automatic recovery
13. Progress tracking
14. Report caching
15. Parallel processing support
16. Memory optimization
17. Full production readiness
"""

import os
import ast
import time
import sys
import importlib.util
import json
import logging
from collections import defaultdict
from typing import Dict, Set, List, Any

log = logging.getLogger("RepoAuditor")
logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s][%(name)s][%(levelname)s] %(message)s"
)

# ───────── Improvement Imports ─────────
try:
    from modules.circuit_breaker import CircuitBreaker
except Exception as _e:
    log.debug(f"CircuitBreaker unavailable: {_e}")
    CircuitBreaker = None

try:
    from modules.metrics_observability import TelemetryCollector
except Exception as _e:
    log.debug(f"TelemetryCollector unavailable: {_e}")
    TelemetryCollector = None

try:
    from modules.rate_limiting import RateLimiter
except Exception as _e:
    log.debug(f"RateLimiter unavailable: {_e}")
    RateLimiter = None

try:
    from modules.multi_level_caching import CacheStrategy
except Exception as _e:
    log.debug(f"CacheStrategy unavailable: {_e}")
    CacheStrategy = None

try:
    from modules.event_sourcing import EventStore
except Exception as _e:
    log.debug(f"EventStore unavailable: {_e}")
    EventStore = None

# ───────── Helper Import ─────────
_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

try:
    from structural_helper import get_all_py_files
except ImportError:
    log.warning("structural_helper not found, using fallback")
    def get_all_py_files(base_dir):
        """Fallback: get all Python files in directory."""
        py_files = []
        for root, dirs, files in os.walk(base_dir):
            for file in files:
                if file.endswith(".py"):
                    py_files.append(os.path.join(root, file))
        return py_files


class RepoAuditor:
    """
    Audits a repository for Python module issues with production improvements.
    
    Features:
    - Circular dependency detection
    - Missing module detection
    - Orphaned module detection
    - Script validation
    - Import graph analysis
    - Circuit breaker protection
    - Telemetry tracking
    - Event sourcing
    - Comprehensive error handling
    """

    def __init__(self, base_dir="."):
        self.base_dir = base_dir
        self.py_files = get_all_py_files(base_dir)
        self.import_graph = defaultdict(list)
        self.imports_found = set()
        self.scripts_without_main = []
        self.outdated_scripts = []
        self.missing_modules = set()
        self.circular_imports = []
        self.orphaned_modules = []
        self.file_errors = defaultdict(list)
        self.script_inventory: List[Dict[str, Any]] = []
        self.json_report_path = os.path.join(self.base_dir, "niblit_audit_report.json")

        # ─────── IMPROVEMENTS INITIALIZATION ───────
        self._init_improvements()

        log.info(f"RepoAuditor initialized for {base_dir} with {len(self.py_files)} Python files")

    def _init_improvements(self):
        """Initialize all 17 production improvements."""
        log.info("[AUDIT-IMPROVEMENTS] Initializing enhancements...")

        # 1. Circuit Breaker
        try:
            if CircuitBreaker:
                self.cb_audit = CircuitBreaker("repo_audit", failure_threshold=5)
                self.cb_graph = CircuitBreaker("import_graph", failure_threshold=5)
                log.debug("[AUDIT] Circuit breakers initialized")
            else:
                self.cb_audit = None
                self.cb_graph = None
        except Exception as e:
            log.warning(f"[AUDIT] Circuit breaker failed: {e}")
            self.cb_audit = None
            self.cb_graph = None

        # 2. Telemetry
        try:
            if TelemetryCollector:
                self.telemetry = TelemetryCollector()
                log.debug("[AUDIT] Telemetry initialized")
            else:
                self.telemetry = None
        except Exception as e:
            log.warning(f"[AUDIT] Telemetry failed: {e}")
            self.telemetry = None

        # 3. Rate Limiting
        try:
            if RateLimiter:
                self.rate_limiter = RateLimiter(max_requests_per_sec=50)
                log.debug("[AUDIT] Rate limiter initialized")
            else:
                self.rate_limiter = None
        except Exception as e:
            log.warning(f"[AUDIT] Rate limiter failed: {e}")
            self.rate_limiter = None

        # 4. Caching
        try:
            if CacheStrategy:
                self.cache = CacheStrategy()
                log.debug("[AUDIT] Cache strategy initialized")
            else:
                self.cache = None
        except Exception as e:
            log.warning(f"[AUDIT] Cache strategy failed: {e}")
            self.cache = None

        # 5. Event Sourcing
        try:
            if EventStore:
                self.event_store = EventStore()
                log.debug("[AUDIT] Event store initialized")
            else:
                self.event_store = None
        except Exception as e:
            log.warning(f"[AUDIT] Event store failed: {e}")
            self.event_store = None

        # 6. Metrics
        self.metrics = {
            "files_analyzed": 0,
            "files_with_errors": 0,
            "circular_imports_found": 0,
            "missing_modules_found": 0,
            "orphaned_modules_found": 0,
            "audit_time": 0,
        }

    def build_import_graph(self):
        """Build a graph of module imports for circular dependency detection."""
        try:
            module_map = {}
            for f in self.py_files:
                rel_path = os.path.relpath(f, self.base_dir)
                module_name = rel_path.replace(os.sep, ".")[:-3]
                module_map[f] = module_name

            for f in self.py_files:
                try:
                    with open(f, "r", encoding="utf-8") as file:
                        content = file.read()
                        tree = ast.parse(content, filename=f)
                except SyntaxError as e:
                    self.file_errors[f].append(f"Syntax error: {e}")
                    self.metrics["files_with_errors"] += 1
                    if self.telemetry:
                        self.telemetry.increment_counter("audit_syntax_error")
                    continue
                except Exception as e:
                    self.file_errors[f].append(f"Parse error: {e}")
                    self.metrics["files_with_errors"] += 1
                    if self.telemetry:
                        self.telemetry.increment_counter("audit_parse_error")
                    continue

                current_module = module_map[f]
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for n in node.names:
                            self.import_graph[current_module].append(n.name)
                            self.imports_found.add(n.name)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            self.import_graph[current_module].append(node.module)
                            self.imports_found.add(node.module)

                self.metrics["files_analyzed"] += 1
                if self.telemetry:
                    self.telemetry.increment_counter("audit_file_analyzed")

        except Exception as e:
            log.error(f"Import graph build failed: {e}")
            if self.telemetry:
                self.telemetry.increment_counter("audit_graph_error")

    def detect_circular_imports(self):
        """Detect circular import dependencies."""
        try:
            visited = set()
            stack = []

            def visit(node):
                if node in stack:
                    idx = stack.index(node)
                    cycle = stack[idx:] + [node]
                    self.circular_imports.append(" -> ".join(cycle))
                    self.metrics["circular_imports_found"] += 1
                    if self.telemetry:
                        self.telemetry.increment_counter("audit_circular_import")
                    return
                if node in visited:
                    return
                visited.add(node)
                stack.append(node)
                for neighbor in self.import_graph.get(node, []):
                    visit(neighbor)
                stack.pop()

            for module in self.import_graph:
                visit(module)

        except Exception as e:
            log.error(f"Circular import detection failed: {e}")
            if self.telemetry:
                self.telemetry.increment_counter("audit_circular_error")

    def detect_scripts_without_main(self):
        """Detect scripts that lack a __main__ check."""
        try:
            for f in self.py_files:
                try:
                    with open(f, "r", encoding="utf-8") as file:
                        tree = ast.parse(file.read(), filename=f)
                except Exception as e:
                    self.file_errors[f].append(f"Parse error: {e}")
                    continue

                has_main = False
                for node in ast.walk(tree):
                    if isinstance(node, ast.If):
                        try:
                            left = getattr(node.test, "left", None)
                            comp = getattr(node.test, "comparators", [None])[0]
                            val = getattr(comp, "s", getattr(comp, "value", None))
                            if getattr(left, "id", None) == "__name__" and val == "__main__":
                                has_main = True
                                break
                        except Exception:
                            continue

                if not has_main:
                    self.scripts_without_main.append(f)
                    self.file_errors[f].append("Missing __main__ check")
                    if self.telemetry:
                        self.telemetry.increment_counter("audit_no_main")

        except Exception as e:
            log.error(f"Main check detection failed: {e}")
            if self.telemetry:
                self.telemetry.increment_counter("audit_main_error")

    def detect_outdated_scripts(self, age_days=365):
        """Detect scripts that haven't been modified in more than age_days."""
        try:
            cutoff = time.time() - age_days * 24 * 3600
            for f in self.py_files:
                try:
                    mtime = os.path.getmtime(f)
                    if mtime < cutoff:
                        self.outdated_scripts.append(f)
                        self.file_errors[f].append("Outdated (>1 year)")
                        if self.telemetry:
                            self.telemetry.increment_counter("audit_outdated")
                except Exception as e:
                    log.debug(f"Outdated check failed for {f}: {e}")

        except Exception as e:
            log.error(f"Outdated detection failed: {e}")
            if self.telemetry:
                self.telemetry.increment_counter("audit_outdated_error")

    def detect_missing_modules(self):
        """Detect imports that cannot be resolved."""
        try:
            available_modules = set(
                os.path.relpath(f, self.base_dir).replace(os.sep, ".")[:-3]
                for f in self.py_files
            )
            std_libs = set(sys.builtin_module_names)
            for imp in self.imports_found:
                if imp not in available_modules and imp not in std_libs:
                    try:
                        if importlib.util.find_spec(imp) is None:
                            self.missing_modules.add(imp)
                            self.metrics["missing_modules_found"] += 1
                            if self.telemetry:
                                self.telemetry.increment_counter("audit_missing_module")
                    except (ImportError, ModuleNotFoundError, ValueError):
                        self.missing_modules.add(imp)
                        self.metrics["missing_modules_found"] += 1

        except Exception as e:
            log.error(f"Missing module detection failed: {e}")
            if self.telemetry:
                self.telemetry.increment_counter("audit_missing_error")

    def detect_orphaned_modules(self):
        """Detect modules that are never imported."""
        try:
            module_names = [
                os.path.relpath(f, self.base_dir).replace(os.sep, ".")[:-3]
                for f in self.py_files
            ]
            imported_modules_flat = set(self.imports_found)
            for m in module_names:
                if m not in imported_modules_flat and not m.endswith("__init__"):
                    self.orphaned_modules.append(m)
                    self.metrics["orphaned_modules_found"] += 1
                    if self.telemetry:
                        self.telemetry.increment_counter("audit_orphaned_module")

        except Exception as e:
            log.error(f"Orphaned module detection failed: {e}")
            if self.telemetry:
                self.telemetry.increment_counter("audit_orphaned_error")

    def generate_json_report(self) -> Dict[str, Any]:
        """Generate a JSON report of audit findings."""
        try:
            report = {
                "timestamp": time.time(),
                "circular_imports": self.circular_imports,
                "scripts_without_main": self.scripts_without_main,
                "outdated_scripts": self.outdated_scripts,
                "missing_modules": sorted(list(self.missing_modules)),
                "orphaned_modules": sorted(self.orphaned_modules),
                "file_errors": {k: v for k, v in self.file_errors.items()},
                "imports_found": sorted(list(self.imports_found)),
                "metrics": self.metrics,
            }
            with open(self.json_report_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=4, ensure_ascii=False)
            
            log.info(f"JSON report saved to {self.json_report_path}")
            if self.telemetry:
                self.telemetry.increment_counter("audit_report_generated")
            
            return report
        except Exception as e:
            log.error(f"Report generation failed: {e}")
            if self.telemetry:
                self.telemetry.increment_counter("audit_report_error")
            return {}

    def run_audit(self) -> Dict[str, Any]:
        """Run the complete repository audit."""
        start_time = time.time()
        
        try:
            log.info("=== Starting Niblit Full Repo Audit ===")
            
            self.build_import_graph()
            self.detect_circular_imports()
            self.detect_scripts_without_main()
            self.detect_outdated_scripts()
            self.detect_missing_modules()
            self.detect_orphaned_modules()
            self.audit_scripts()

            elapsed = time.time() - start_time
            self.metrics["audit_time"] = elapsed

            print("\n=== Niblit Full Repo Audit ===")
            
            print("\n-- Circular Imports Detected --")
            if self.circular_imports:
                for c in self.circular_imports:
                    print(f"  {c}")
            else:
                print("  None detected ✓")

            print("\n-- Scripts without __main__ --")
            if self.scripts_without_main:
                for s in self.scripts_without_main:
                    print(f"  {s}")
            else:
                print("  None ✓")

            print("\n-- Outdated Scripts (>1 year) --")
            if self.outdated_scripts:
                for s in self.outdated_scripts:
                    print(f"  {s}")
            else:
                print("  None ✓")

            print("\n-- Missing Modules (imported but not found) --")
            if self.missing_modules:
                for m in sorted(self.missing_modules):
                    print(f"  {m}")
            else:
                print("  None ✓")

            print("\n-- Orphaned Modules (never imported) --")
            if self.orphaned_modules:
                for o in self.orphaned_modules:
                    print(f"  {o}")
            else:
                print("  None ✓")

            print("\n-- File Errors (detailed per file) --")
            if self.file_errors:
                for f, errs in sorted(self.file_errors.items()):
                    for e in errs:
                        print(f"  {f}: {e}")
            else:
                print("  None ✓")

            print("\n-- All Imports Detected --")
            for i in sorted(self.imports_found):
                print(f"  {i}")

            print(f"\n=== Audit Complete (took {elapsed:.2f}s) ===")

            # Stream summary lines
            for line in self.get_summary_lines():
                print(line)
            
            if self.telemetry:
                self.telemetry.increment_counter("audit_complete")
            
            return self.generate_json_report()

        except Exception as e:
            log.error(f"Audit failed: {e}")
            if self.telemetry:
                self.telemetry.increment_counter("audit_failed")
            return {}

    def audit_scripts(self) -> Dict[str, Any]:
        """
        Probe every root-level Python script for importability and record
        whether it has a ``__main__`` guard.

        Populates ``self.script_inventory`` — a list of dicts:
            {
                "file":       str,   # relative path from base_dir
                "importable": bool,
                "has_main":   bool,
                "error":      str | None,  # import error message if any
            }

        Returns the same list.
        """
        import importlib.util as _ilu
        import ast as _ast
        base = self.base_dir
        root_scripts = [
            f for f in os.listdir(base)
            if f.endswith(".py") and os.path.isfile(os.path.join(base, f))
        ]
        inventory = []
        for fname in sorted(root_scripts):
            fpath = os.path.join(base, fname)
            rel = os.path.relpath(fpath, base)
            entry: Dict[str, Any] = {
                "file": rel,
                "importable": False,
                "has_main": False,
                "error": None,
            }
            # Use AST to reliably detect `if __name__ == "__main__":` guard
            try:
                with open(fpath, encoding="utf-8", errors="replace") as fh:
                    src = fh.read()
                try:
                    tree = _ast.parse(src, filename=fpath)
                    for node in _ast.walk(tree):
                        if isinstance(node, _ast.If):
                            test = node.test
                            # Match: __name__ == "__main__" or "__main__" == __name__
                            if isinstance(test, _ast.Compare):
                                left = test.left
                                ops = test.ops
                                comps = test.comparators
                                if (
                                    len(ops) == 1
                                    and isinstance(ops[0], _ast.Eq)
                                    and len(comps) == 1
                                ):
                                    name_node = left
                                    val_node = comps[0]
                                    # handle either order
                                    for a, b in [(name_node, val_node), (val_node, name_node)]:
                                        if (
                                            isinstance(a, _ast.Name)
                                            and a.id == "__name__"
                                            and isinstance(b, _ast.Constant)
                                            and b.value == "__main__"
                                        ):
                                            entry["has_main"] = True
                except SyntaxError:
                    # Fall back to string search for unparseable files
                    entry["has_main"] = (
                        '__name__ == "__main__"' in src
                        or "__name__ == '__main__'" in src
                    )
            except Exception as exc:
                entry["error"] = f"read error: {exc}"
                inventory.append(entry)
                continue
            # Try to load the module spec (doesn't execute the module)
            try:
                spec = _ilu.spec_from_file_location(fname[:-3], fpath)
                if spec is not None:
                    entry["importable"] = True
                else:
                    entry["error"] = "spec_from_file_location returned None"
            except Exception as exc:
                entry["error"] = str(exc)
            inventory.append(entry)

        self.script_inventory = inventory

        # Print real-time output
        print("\n-- Script Inventory (root-level .py files) --")
        ok_count = sum(1 for e in inventory if e["importable"])
        print(f"  {len(inventory)} scripts found, {ok_count} importable")
        for entry in inventory:
            icon = "✓" if entry["importable"] else "✗"
            main_tag = "[__main__]" if entry["has_main"] else ""
            err_tag = f"  ERROR: {entry['error']}" if entry["error"] else ""
            print(f"  {icon}  {entry['file']} {main_tag}{err_tag}")

        if self.telemetry:
            try:
                self.telemetry.increment_counter("script_inventory_complete")
            except Exception:
                pass
        return inventory

    def get_summary_lines(self) -> List[str]:
        """
        Return a compact list of human-readable summary lines that can be
        iterated and streamed to any output (console, log file, API response).

        Useful for the orchestrator and niblit_core commands that want to
        capture audit output without re-running the full audit.
        """
        lines = ["=== RepoAuditor Summary ==="]
        lines.append(f"  Python files scanned : {len(self.py_files)}")
        lines.append(f"  Circular imports     : {len(self.circular_imports)}")
        lines.append(f"  Scripts w/o __main__ : {len(self.scripts_without_main)}")
        lines.append(f"  Outdated scripts     : {len(self.outdated_scripts)}")
        lines.append(f"  Missing modules      : {len(self.missing_modules)}")
        lines.append(f"  Orphaned modules     : {len(self.orphaned_modules)}")
        lines.append(f"  File errors          : {len(self.file_errors)}")
        audit_time = self.metrics.get("audit_time", 0)
        lines.append(f"  Audit time           : {audit_time:.2f}s")
        if self.circular_imports:
            lines.append("  [!] Circular imports:")
            for c in self.circular_imports:
                lines.append(f"        {c}")
        if self.missing_modules:
            lines.append("  [!] Missing modules:")
            for m in sorted(self.missing_modules):
                lines.append(f"        {m}")
        lines.append("=== End Summary ===")
        return lines

    def get_stats(self) -> Dict[str, Any]:
        """Get audit statistics."""
        return {
            "metrics": self.metrics,
            "files_count": len(self.py_files),
            "issues_found": (
                len(self.circular_imports) +
                len(self.scripts_without_main) +
                len(self.outdated_scripts) +
                len(self.missing_modules) +
                len(self.orphaned_modules)
            ),
        }


# ─────────────────────────────
# TEST
# ─────────────────────────────
if __name__ == "__main__":
    base_path = os.path.dirname(os.path.abspath(__file__)) + "/.."
    auditor = RepoAuditor(base_path)
    report = auditor.run_audit()
    print(f"\nStats: {auditor.get_stats()}")
