#!/usr/bin/env python3
"""
SelfResearcher v3
- Uses DuckDuckGo Instant Answer JSON API for web queries (no scraping).
- Supports internal commands, module invocation, and terminal execution.
"""

import subprocess
import requests
from typing import Optional

DDG_API = "https://api.duckduckgo.com/"


class SelfResearcher:
    def __init__(self, db, modules_registry: Optional[dict] = None):
        self.db = db
        # registry passed in OR db.runtime_registry OR empty {}
        self.modules_registry = modules_registry or getattr(db, "runtime_registry", {}) or {}

        # shorthand → internal command mapping
        self.command_map = {
            "ideas": "ideas about",
            "reflect": "reflect",
            "analyze": "analyze",
            "memory": "!memory",
            "heal": "self-heal",
            "teach": "self-teach",
            "maintain": "self-maintenance",
            "impl": "self-idea-impl",
            "device": "device-info",
            "read": "read-file",
            "write": "write-file",
        }

    # ---------------------------------------
    # Main command interpreter
    # ---------------------------------------
    def handle_command(self, cmd: str, arg: Optional[str] = "") -> str:
        cmd = (cmd or "").strip()
        arg = (arg or "").strip()

        # 1) treat "web", "web.run", "search" as natural web query
        if cmd in ("web.run", "web", "search"):
            return self.web_search(arg)

        # 2) natural query fallback
        if cmd == "":
            return self.web_search(arg)

        # 3) internal shorthand
        if cmd in self.command_map:
            mapped = self.command_map[cmd]
            return f"[INTERNAL RESEARCH] → {mapped} {arg}".strip()

        # 4) module invocation
        if cmd == "module":
            return self.call_module(arg)

        # 5) terminal
        if cmd == "terminal":
            return self.run_terminal(arg)

        # 6) remaining → treat as natural search
        return self.web_search((cmd + " " + arg).strip())

    # ---------------------------------------
    # DuckDuckGo Instant Answer
    # ---------------------------------------
    def web_search(self, query: str) -> str:
        if not query:
            return "[WEB RESEARCH ERROR] empty query"

        try:
            params = {"q": query, "format": "json", "no_html": 1, "skip_disambig": 1}
            r = requests.get(DDG_API, params=params, timeout=8)
            r.raise_for_status()
            data = r.json()

            parts = []

            if data.get("AbstractText"):
                parts.append(data["AbstractText"])
            if data.get("Answer"):
                parts.append(str(data["Answer"]))

            if data.get("RelatedTopics"):
                for t in data["RelatedTopics"][:3]:
                    if isinstance(t, dict):
                        txt = t.get("Text") or t.get("Result") or ""
                        if txt:
                            parts.append(txt)

            if not parts and data.get("Results"):
                for res in data["Results"][:3]:
                    parts.append(res.get("Text", ""))

            if parts:
                return "[WEB RESEARCH RESULTS]\n\n" + "\n\n".join(parts)

            if data.get("AbstractURL"):
                return f"[WEB RESEARCH] URL: {data['AbstractURL']}"

            if data.get("Heading"):
                return f"[WEB RESEARCH] {data['Heading']}"

            return "[NO RESULTS FOUND]"

        except Exception as e:
            return f"[WEB RESEARCH ERROR] {e}"

    # ---------------------------------------
    # Module call helper
    # ---------------------------------------
    def call_module(self, text: str) -> str:
        if not text:
            return "[MODULE ERROR] missing module/action"

        parts = text.split()
        module_name = parts[0]
        action = " ".join(parts[1:]).strip()

        registry = self.modules_registry or getattr(self.db, "runtime_registry", {}) or {}

        if module_name not in registry:
            return f"[MODULE ERROR] Module '{module_name}' not registered."

        target = registry[module_name]

        try:
            # 1) .api(action)
            if hasattr(target, "api"):
                return target.api(action)

            # 2) .handle(action)
            if hasattr(target, "handle"):
                return target.handle(action)

            # 3) .run(action)
            if hasattr(target, "run"):
                return target.run(action)

            # 4) attribute function: first token
            if action:
                verb = action.split()[0].replace("-", "_")
                if hasattr(target, verb):
                    fn = getattr(target, verb)
                    if callable(fn):
                        remaining = " ".join(action.split()[1:]).strip()
                        return fn(remaining) if remaining else fn()

            # 5) fallback stringify
            return f"[MODULE {module_name}] {str(target)}"

        except Exception as e:
            return f"[MODULE ERROR] {e}"

    # ---------------------------------------
    # Terminal execution
    # ---------------------------------------
    def run_terminal(self, cmd: str) -> str:
        if not cmd:
            return "[TERMINAL ERROR] no command"

        try:
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            out = proc.stdout.strip()
            err = proc.stderr.strip()
            if proc.returncode != 0:
                return f"[TERMINAL ERROR] rc={proc.returncode}\n{err or out}"
            return out if out else "[TERMINAL] (no output)"
        except subprocess.TimeoutExpired:
            return "[TERMINAL ERROR] timed out"
        except Exception as e:
            return f"[TERMINAL ERROR] {e}"

