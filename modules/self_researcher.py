#!/usr/bin/env python3
# modules/self_researcher.py
"""
SelfResearcher: provides both command-style handling (handle_command)
and a convenient .search(query) method that returns a list[str].

It will prefer to use an InternetManager if available via:
 - modules_registry (passed in constructor) OR
 - db.runtime_registry (if db supplied has that attribute)
Otherwise falls back to DuckDuckGo instant answer.
"""
import subprocess
import requests
from typing import Optional, List

DDG_API = "https://api.duckduckgo.com/"

class SelfResearcher:
    def __init__(self, db, modules_registry: Optional[dict] = None):
        self.db = db
        # registry passed in OR db.runtime_registry OR empty {}
        self.modules_registry = modules_registry or getattr(db, "runtime_registry", {}) or {}
        # shorthand internal command mapping
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

    # -----------------------
    # primary public search
    # -----------------------
    def search(self, query: str, max_results: int = 5) -> List[str]:
        """Return a list of short textual results/snippets for 'query'."""
        q = (query or "").strip()
        if not q:
            return []

        # try InternetManager from registry if available
        im = None
        try:
            im = self.modules_registry.get("internet_manager") or (getattr(self.db, "runtime_registry", {}) or {}).get("internet_manager")
        except Exception:
            im = None

        if im and hasattr(im, "search_web"):
            try:
                return im.search_web(q, max_results=max_results)
            except Exception:
                pass

        # fallback: use DuckDuckGo Instant Answer JSON
        try:
            params = {"q": q, "format": "json", "no_html": 1, "skip_disambig": 1}
            r = requests.get(DDG_API, params=params, timeout=6)
            r.raise_for_status()
            data = r.json()
            parts = []
            if data.get("AbstractText"):
                parts.append(data.get("AbstractText"))
            if data.get("Answer"):
                parts.append(str(data.get("Answer")))
            if data.get("RelatedTopics"):
                for t in data["RelatedTopics"][:max_results]:
                    if isinstance(t, dict):
                        txt = t.get("Text") or t.get("Result") or ""
                        if txt:
                            parts.append(txt)
            # results
            if parts:
                # normalize and limit
                cleaned = []
                for p in parts:
                    s = str(p).strip()
                    if s and s not in cleaned:
                        cleaned.append(s)
                    if len(cleaned) >= max_results:
                        break
                return cleaned
        except Exception:
            pass

        # final fallback
        return [f"No instant answers for '{q}'. Try a web search."]

    # -----------------------
    # command dispatcher
    # -----------------------
    def handle_command(self, cmd: str, arg: Optional[str] = "") -> str:
        cmd = (cmd or "").strip()
        arg = (arg or "").strip()

        if cmd in ("web.run", "web", "search"):
            # natural web query
            results = self.search(arg, max_results=5)
            return "[WEB RESEARCH RESULTS]\n\n" + "\n\n".join(results)

        if cmd == "":
            return self.search(arg, max_results=3).__repr__()

        if cmd in self.command_map:
            mapped = self.command_map[cmd]
            return f"[INTERNAL RESEARCH] → {mapped} {arg}".strip()

        if cmd == "module":
            return self.call_module(arg)

        if cmd == "terminal":
            return self.run_terminal(arg)

        # default
        return self.search((cmd + " " + arg).strip(), max_results=5).__repr__()

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
            if hasattr(target, "api"):
                return target.api(action)
            if hasattr(target, "handle"):
                return target.handle(action)
            if hasattr(target, "run"):
                return target.run(action)
            if action:
                verb = action.split()[0].replace("-", "_")
                if hasattr(target, verb):
                    fn = getattr(target, verb)
                    if callable(fn):
                        remaining = " ".join(action.split()[1:]).strip()
                        return fn(remaining) if remaining else fn()
            return f"[MODULE {module_name}] {str(target)}"
        except Exception as e:
            return f"[MODULE ERROR] {e}"

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
