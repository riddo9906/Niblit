#!/usr/bin/env python3
import sys
import os
import ast

# -----------------------------
# Ensure repo root is in sys.path
# -----------------------------
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

# -----------------------------
# Imports (do NOT import LocalDB at module level!)
# -----------------------------
from modules.self_healer import SelfHealer
from modules.self_maintenance import SelfMaintenance

# -----------------------------
# Helper functions
# -----------------------------
def find_python_scripts(root_dir):
    py_files = []
    for dirpath, _, files in os.walk(root_dir):
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.join(dirpath, f))
    return py_files

def has_main_block(filepath):
    with open(filepath, "r") as f:
        try:
            tree = ast.parse(f.read(), filename=filepath)
        except Exception:
            return False
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            try:
                if (
                    isinstance(node.test, ast.Compare) and
                    isinstance(node.test.left, ast.Name) and
                    node.test.left.id == "__name__" and
                    any(isinstance(op, ast.Eq) for op in node.test.ops) and
                    any(isinstance(c, ast.Constant) and c.value == "__main__" for c in node.test.comparators)
                ):
                    return True
            except Exception:
                continue
    return False

# -----------------------------
# FixGuideGenerator class
# -----------------------------
class FixGuideGenerator:
    def __init__(self, db):
        self.db = db
        self.self_healer = SelfHealer(db)
        self.self_maintenance = SelfMaintenance(db)

    def scan_missing_main(self):
        scripts = find_python_scripts(repo_root)
        return [s for s in scripts if not has_main_block(s)]

    def generate_cat_main_blocks(self, files_missing_main):
        commands = []
        for f in files_missing_main:
            script_name = os.path.basename(f)
            commands.append(f'echo "\n# Adding __main__ block to {script_name}"')
            commands.append(
                f'cat >> "{f}" << EOF\n'
                f'if __name__ == "__main__":\n'
                f'    print(\'Running {script_name}\')\n'
                f'EOF'
            )
        return commands

    def generate_fix_guide(self, fix_guide_path):
        files_missing_main = self.scan_missing_main()
        commands = ["#!/bin/bash\n", "echo '=== Fix Guide Started ==='\n"]
        commands += self.generate_cat_main_blocks(files_missing_main)

        commands.append("\n# Running self-maintenance")
        commands.append(
            "python3 -c 'from modules.self_maintenance import SelfMaintenance; "
            "from modules.db import LocalDB; db=LocalDB(); SelfMaintenance(db).run()'"
        )

        commands.append("\n# Running self-healer")
        commands.append(
            "python3 -c 'from modules.self_healer import SelfHealer; "
            "from modules.db import LocalDB; db=LocalDB(); SelfHealer(db).repair()'"
        )

        commands.append("\necho '=== Fix Guide Completed ==='")

        with open(fix_guide_path, "w") as f:
            f.write("\n".join(commands))
        os.chmod(fix_guide_path, 0o755)
        return f"Auto-scan Fix Guide generated at {fix_guide_path}"

# -----------------------------
# Run generator if executed directly
# -----------------------------
if __name__ == "__main__":
    # Import LocalDB here only to avoid circular imports
    from modules.db import LocalDB

    db = LocalDB()
    fg = FixGuideGenerator(db)
    fix_guide_txt = os.path.join(repo_root, "Fix_Guide.txt")
    print(fg.generate_fix_guide(fix_guide_txt))
