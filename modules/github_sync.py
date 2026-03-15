#!/usr/bin/env python3
"""
GITHUB SYNC MODULE
Push and pull Niblit self-updates to/from GitHub.

Wraps git commands for the Niblit build directory at TERMUX_DEPLOY_PATH so
Niblit can persist autonomously-generated code and improvements to GitHub.
"""

import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger("GitHubSync")

# Niblit build path — imported from the canonical definition in evolve.py
try:
    from modules.evolve import TERMUX_DEPLOY_PATH as NIBLIT_BUILD_PATH
except Exception:
    NIBLIT_BUILD_PATH = Path(
        "/data/data/com.termux/files/home/NiblitAIOS/Niblit-Modules/Niblit-apk/Niblit"
    )


class GitHubSync:
    """Sync Niblit self-updates with GitHub via git push/pull.

    Operates on the Niblit build directory so Niblit can persist its
    autonomously-generated code and improvements to GitHub.

    Usage:
        sync = GitHubSync(db=knowledge_db)
        print(sync.status())
        print(sync.pull())
        print(sync.push("autonomous update: improved reasoning step"))
    """

    def __init__(self, repo_path: Optional[str] = None, db: Any = None):
        self.repo_path = Path(repo_path) if repo_path else NIBLIT_BUILD_PATH
        self.db = db
        self._stats: Dict[str, int] = {"pushes": 0, "pulls": 0, "errors": 0}
        log.debug("[GitHubSync] repo_path=%s", self.repo_path)

    # ──────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────

    def status(self) -> str:
        """Return git status of the build directory."""
        out = self._git("status", "--short")
        branch = self._git("rev-parse", "--abbrev-ref", "HEAD")
        return f"Branch: {branch}\n{out}" if out else f"Branch: {branch}\n(clean)"

    def log(self, n: int = 5) -> str:
        """Return the last *n* git commits (one-line format)."""
        return self._git("log", "--oneline", f"-{n}")

    def pull(self) -> str:
        """Pull the latest changes from the remote."""
        log.info("[GitHubSync] Pulling from remote…")
        result = self._git("pull")
        if result.startswith("error"):
            self._stats["errors"] += 1
        else:
            self._stats["pulls"] += 1
            self._store_event("pull", result)
        return result

    def push(self, message: Optional[str] = None) -> str:
        """Stage all changes, commit, and push to the remote."""
        commit_msg = message or "Niblit autonomous self-update"
        log.info("[GitHubSync] Pushing: %s", commit_msg)

        # Stage all changes
        add_result = self._git("add", "-A")
        if add_result.startswith("error"):
            self._stats["errors"] += 1
            return f"❌ git add failed: {add_result}"

        # Commit (tolerate 'nothing to commit')
        commit_result = self._git("commit", "-m", commit_msg)
        if "nothing to commit" in commit_result.lower():
            return f"ℹ️ Nothing new to commit.\n{commit_result}"
        if commit_result.startswith("error"):
            self._stats["errors"] += 1
            return f"❌ git commit failed: {commit_result}"

        # Push
        push_result = self._git("push")
        if push_result.startswith("error"):
            self._stats["errors"] += 1
            return f"❌ git push failed: {push_result}"

        self._stats["pushes"] += 1
        self._store_event("push", commit_msg)
        return f"✅ Pushed: {commit_msg}\n{push_result}"

    def get_stats(self) -> Dict[str, int]:
        """Return sync statistics."""
        return dict(self._stats)

    # ──────────────────────────────────────────────────────
    # INTERNALS
    # ──────────────────────────────────────────────────────

    def _git(self, *args: str) -> str:
        """Run a git command inside the repo directory and return output."""
        if not self.repo_path.exists():
            return f"error: repo path not found: {self.repo_path}"
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                timeout=30,
            )
            stdout = (result.stdout or "").strip()
            stderr = (result.stderr or "").strip()
            if result.returncode != 0 and stderr:
                return f"error: {stderr}"
            return stdout or stderr or "(no output)"
        except FileNotFoundError:
            return "error: git not found — install git in Termux"
        except subprocess.TimeoutExpired:
            return "error: git command timed out"
        except Exception as exc:
            log.debug("[GitHubSync] git error: %s", exc)
            return f"error: {exc}"

    def _store_event(self, action: str, detail: str) -> None:
        """Persist sync event to KnowledgeDB if available."""
        if self.db and hasattr(self.db, "add_fact"):
            try:
                self.db.add_fact(
                    f"github_sync:{action}:{int(time.time())}",
                    detail[:300],
                    tags=["github", "sync", action],
                )
            except Exception:
                pass
