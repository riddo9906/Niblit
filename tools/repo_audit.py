import os
import ast
import time
import sys
import importlib.util
import json
from collections import defaultdict

# Ensure the tools directory is in sys.path so structural_helper can be found
_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from structural_helper import get_all_py_files

class RepoAuditor:
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
        self.json_report_path = os.path.join(self.base_dir, "niblit_audit_report.json")

    # -----------------------------
    # Build import graph for circular detection
    # -----------------------------
    def build_import_graph(self):
        module_map = {}  # filepath -> module name
        for f in self.py_files:
            rel_path = os.path.relpath(f, self.base_dir)
            module_name = rel_path.replace(os.sep, ".")[:-3]  # remove .py
            module_map[f] = module_name

        for f in self.py_files:
            with open(f, "r", encoding="utf-8") as file:
                try:
                    tree = ast.parse(file.read(), filename=f)
                except Exception as e:
                    self.file_errors[f].append(f"Syntax error: {e}")
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

    # -----------------------------
    # Detect circular imports
    # -----------------------------
    def detect_circular_imports(self):
        visited = set()
        stack = []

        def visit(node):
            if node in stack:
                idx = stack.index(node)
                cycle = stack[idx:] + [node]
                self.circular_imports.append(" -> ".join(cycle))
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

    # -----------------------------
    # Detect scripts without __main__
    # -----------------------------
    def detect_scripts_without_main(self):
        for f in self.py_files:
            with open(f, "r", encoding="utf-8") as file:
                try:
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
                    except:
                        continue

            if not has_main:
                self.scripts_without_main.append(f)
                self.file_errors[f].append("Missing __main__ check")

    # -----------------------------
    # Detect outdated scripts
    # -----------------------------
    def detect_outdated_scripts(self, age_days=365):
        cutoff = time.time() - age_days * 24 * 3600
        for f in self.py_files:
            mtime = os.path.getmtime(f)
            if mtime < cutoff:
                self.outdated_scripts.append(f)
                self.file_errors[f].append("Outdated (>1 year)")

    # -----------------------------
    # Detect missing modules
    # -----------------------------
    def detect_missing_modules(self):
        available_modules = set(os.path.relpath(f, self.base_dir).replace(os.sep, ".")[:-3] for f in self.py_files)
        std_libs = set(sys.builtin_module_names)
        for imp in self.imports_found:
            if imp not in available_modules and imp not in std_libs:
                if importlib.util.find_spec(imp) is None:
                    self.missing_modules.add(imp)

    # -----------------------------
    # Detect orphaned modules (never imported)
    # -----------------------------
    def detect_orphaned_modules(self):
        module_names = [os.path.relpath(f, self.base_dir).replace(os.sep, ".")[:-3] for f in self.py_files]
        imported_modules_flat = set(self.imports_found)
        for m in module_names:
            if m not in imported_modules_flat and not m.endswith("__init__"):
                self.orphaned_modules.append(m)

    # -----------------------------
    # Generate JSON report
    # -----------------------------
    def generate_json_report(self):
        report = {
            "circular_imports": self.circular_imports,
            "scripts_without_main": self.scripts_without_main,
            "outdated_scripts": self.outdated_scripts,
            "missing_modules": list(self.missing_modules),
            "orphaned_modules": self.orphaned_modules,
            "file_errors": {k: v for k, v in self.file_errors.items()},
            "imports_found": list(self.imports_found)
        }
        with open(self.json_report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=4)
        print(f"\n[JSON report saved to {self.json_report_path}]")
        return report

    # -----------------------------
    # Run full audit
    # -----------------------------
    def run_audit(self):
        print("=== Niblit Full Repo Audit ===")
        self.build_import_graph()
        self.detect_circular_imports()
        self.detect_scripts_without_main()
        self.detect_outdated_scripts()
        self.detect_missing_modules()
        self.detect_orphaned_modules()

        print("\n-- Circular Imports Detected --")
        if self.circular_imports:
            for c in self.circular_imports:
                print(c)
        else:
            print("None detected")

        print("\n-- Scripts without __main__ --")
        for s in self.scripts_without_main:
            print(s)
        if not self.scripts_without_main:
            print("None")

        print("\n-- Outdated Scripts (>1 year) --")
        for s in self.outdated_scripts:
            print(s)
        if not self.outdated_scripts:
            print("None")

        print("\n-- Missing Modules (imported but not found) --")
        for m in self.missing_modules:
            print(m)
        if not self.missing_modules:
            print("None")

        print("\n-- Orphaned Modules (never imported) --")
        for o in self.orphaned_modules:
            print(o)
        if not self.orphaned_modules:
            print("None")

        print("\n-- File Errors (detailed per file) --")
        for f, errs in self.file_errors.items():
            for e in errs:
                print(f"{f}: {e}")
        if not self.file_errors:
            print("None")

        print("\n-- All Imports Detected --")
        for i in sorted(self.imports_found):
            print(i)

        print("\n=== Audit Complete ===")
        return self.generate_json_report()

# -----------------------------
# Handler if run as a script
# -----------------------------
if __name__ == "__main__":
    base_path = os.path.dirname(os.path.abspath(__file__)) + "/.."
    auditor = RepoAuditor(base_path)
    auditor.run_audit()
