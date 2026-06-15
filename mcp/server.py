from mcp.server.fastmcp import FastMCP
import os
import json
import ast
from typing import Dict, Any, Optional

# Optional external LLM client (safe fallback)
try:
    from llm_client import ExternalLLMClient
except Exception:
    ExternalLLMClient = None


mcp = FastMCP("niblit-core-mcp")


# =========================================================
# GLOBAL CONFIG
# =========================================================

REPO_ROOT = r"C:\Users\Riyaad\Documents\GitHub\Niblit"

MEMORY_FILE = os.path.join(
    os.path.dirname(__file__),
    "memory.json"
)

llm = None
if ExternalLLMClient:
    try:
        llm = ExternalLLMClient(
            endpoint="http://localhost:8000/v1/chat/completions",
            api_key=None
        )
    except Exception:
        llm = None


# =========================================================
# UTILITIES
# =========================================================

def resolve_path(path: str) -> str:
    """Resolve relative paths into repo root context"""
    if os.path.isabs(path):
        return path
    return os.path.join(REPO_ROOT, path)


def load_memory_store():
    if not os.path.exists(MEMORY_FILE):
        return {}
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_memory_store(data):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# =========================================================
# TOOL: READ FILE
# =========================================================

@mcp.tool()
def read_file(path: str) -> str:
    """Read file safely from repo"""
    try:
        full_path = resolve_path(path)
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"ERROR: {str(e)}"


# =========================================================
# TOOL: SCAN REPOSITORY (TOKEN SAFE VERSION)
# =========================================================

@mcp.tool()
def scan_repo(root: Optional[str] = None, max_depth: int = 3) -> Dict[str, Any]:
    """
    Lightweight repo scan (SAFE FOR LLM CONTEXT)

    FIXES:
    - prevents token explosion
    - limits depth
    - limits file counts
    """

    root = root or REPO_ROOT
    tree = {}

    for folder, dirs, files in os.walk(root):

        # depth limiter (IMPORTANT FIX)
        depth = folder.replace(root, "").count(os.sep)
        if depth > max_depth:
            continue

        # noise filter
        if ".git" in folder or "__pycache__" in folder:
            continue

        tree[folder] = {
            "dirs": dirs[:10],     # LIMIT
            "files": files[:30]    # LIMIT
        }

    return {
        "root": root,
        "folder_count": len(tree),
        "total_files_sampled": sum(len(v["files"]) for v in tree.values()),
        "note": "THIS IS A CONTROLLED SAMPLE VIEW (NOT FULL DUMP)",
        "tree": tree
    }


# =========================================================
# TOOL: ANALYZE SINGLE FILE (DEEP VIEW)
# =========================================================

@mcp.tool()
def analyze_file(path: str) -> Dict[str, Any]:
    """Extract structure from a Python file"""

    try:
        full_path = resolve_path(path)

        with open(full_path, "r", encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source)

        imports = []
        classes = []
        functions = []

        for node in ast.walk(tree):

            if isinstance(node, ast.Import):
                for name in node.names:
                    imports.append(name.name)

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)

            elif isinstance(node, ast.ClassDef):
                classes.append(node.name)

            elif isinstance(node, ast.FunctionDef):
                functions.append(node.name)

        return {
            "file": path,
            "imports": sorted(set(imports)),
            "classes": classes,
            "functions": functions,
            "line_count": len(source.splitlines())
        }

    except Exception as e:
        return {"error": str(e)}


# =========================================================
# TOOL: ARCHITECTURE ANALYSIS
# =========================================================

@mcp.tool()
def analyze_architecture(root: Optional[str] = None) -> Dict[str, Any]:

    root = root or REPO_ROOT

    structure = {}
    python_modules = {}

    for folder, _, files in os.walk(root):

        if ".git" in folder or "__pycache__" in folder:
            continue

        structure[folder] = files

        for f in files:
            if f.endswith(".py"):
                python_modules[f] = folder

    return {
        "root": root,
        "folder_count": len(structure),
        "file_count": sum(len(v) for v in structure.values()),
        "structure": structure,
        "python_module_index": python_modules,
        "system_insights": {
            "has_local_brain": "local_brain.py" in python_modules,
            "has_runtime_router": any("runtime" in k.lower() for k in structure.keys()),
            "has_memory_system": any("memory" in k.lower() for k in structure.keys()),
            "has_tool_system": any("tool" in k.lower() for k in structure.keys())
        }
    }


# =========================================================
# TOOL: SYSTEM OVERVIEW (FAST CONTEXT)
# =========================================================

@mcp.tool()
def get_system_overview(root: Optional[str] = None) -> Dict[str, Any]:

    root = root or REPO_ROOT

    arch = analyze_architecture(root)

    return {
        "summary": {
            "folders": arch["folder_count"],
            "files": arch["file_count"]
        },
        "key_modules": list(arch["python_module_index"].keys())[:25],
        "purpose": "fast_external_llm_context"
    }


# =========================================================
# TOOL: MEMORY SYSTEM
# =========================================================

@mcp.tool()
def save_memory(key: str, value: Any) -> Dict[str, Any]:

    memory = load_memory_store()
    memory[key] = value
    save_memory_store(memory)

    return {
        "status": "saved",
        "key": key
    }


@mcp.tool()
def load_memory(key: str):
    memory = load_memory_store()
    return memory.get(key)


@mcp.tool()
def list_memories():
    memory = load_memory_store()
    return list(memory.keys())


# =========================================================
# TOOL: LOOP STATE REGISTRY
# =========================================================

@mcp.tool()
def register_loop_state(loop_name: str, state: Dict[str, Any]) -> Dict[str, Any]:

    return {
        "loop": loop_name,
        "state": state,
        "status": "registered",
        "note": "future ALE traffic controller integration"
    }


# =========================================================
# START SERVER
# =========================================================

if __name__ == "__main__":
    mcp.run()