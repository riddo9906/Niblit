import os
from pathlib import Path

# =========================
# TOOL 1: Read a file
# =========================
def read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"ERROR reading file: {str(e)}"


# =========================
# TOOL 2: List repo structure
# =========================
def list_repo(root: str):
    structure = {}

    for folder, dirs, files in os.walk(root):
        # skip heavy/system folders
        if ".git" in folder or "__pycache__" in folder:
            continue

        structure[folder] = files

    return structure


# =========================
# TOOL 3: Summarize file (lightweight)
# =========================
def summarize_file(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        lines = content.splitlines()

        return {
            "path": path,
            "line_count": len(lines),
            "preview": "\n".join(lines[:50])  # first 50 lines only
        }

    except Exception as e:
        return {"error": str(e)}


# =========================
# TOOL 4: Full repo snapshot
# =========================
def analyze_repo(root: str):
    return {
        "structure": list_repo(root),
        "entry_points": [
            "server.py",
            "mcp/server.py",
            "modules/local_brain.py",
            "modules/runtime_router_v2.py",
            "modules/chat_completions.py"
        ],
        "intent": "Niblit architecture mapping for external LLM reasoning"
    }