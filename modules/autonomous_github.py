#!/usr/bin/env python3
"""
AUTONOMOUS GITHUB INTEGRATION MODULE
Enables Niblit to autonomously push self-improvements to GitHub.

Provides:
- Read access to the current repository's structure and recent commits
- Ability to create files and commit them via the GitHub API
- Pull request creation for autonomous improvements
- Safe guardrails (dry-run mode, branch isolation, size limits)

Environment variables required for write operations:
    GITHUB_TOKEN  — Personal access token or Actions token with repo scope
    GITHUB_REPO   — Repository in "owner/name" format (e.g. "riddo9906/Niblit")
    GITHUB_BRANCH — Branch to push improvements to (default: "niblit/auto-improve")

Set NIBLIT_GITHUB_DRY_RUN=1 to log all planned operations without executing them.
"""

import logging
import os
import json
import base64
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger("AutonomousGitHub")

_MAX_FILE_BYTES = 256 * 1024  # 256 KB — cap for auto-generated content


class AutonomousGitHubIntegration:
    """
    Integrates Niblit with GitHub so it can read and write to the repository
    autonomously.

    All write operations run on an isolated branch and require explicit
    ``dry_run=False`` to execute real API calls.  By default (and when the
    ``NIBLIT_GITHUB_DRY_RUN`` environment variable is set) the module only
    logs the actions it *would* take.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        repo: Optional[str] = None,
        branch: Optional[str] = None,
        dry_run: Optional[bool] = None,
        db=None,
    ):
        self.token = token or os.getenv("GITHUB_TOKEN", "")
        self.repo = repo or os.getenv("GITHUB_REPO", "")
        self.branch = branch or os.getenv("GITHUB_BRANCH", "niblit/auto-improve")
        self.db = db

        # Honour explicit arg first, then env var, then default to True (safe)
        if dry_run is not None:
            self.dry_run = dry_run
        else:
            self.dry_run = os.getenv("NIBLIT_GITHUB_DRY_RUN", "1") != "0"

        self._base_api = "https://api.github.com"
        self._session_improvements: List[Dict[str, Any]] = []

        log.info(
            "[AutonomousGitHub] Initialized — repo=%s branch=%s dry_run=%s",
            self.repo or "(unset)",
            self.branch,
            self.dry_run,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _api_get(self, path: str) -> Optional[Dict[str, Any]]:
        """GET request to the GitHub REST API. Returns parsed JSON or None."""
        try:
            import urllib.request

            url = f"{self._base_api}{path}"
            req = urllib.request.Request(url, headers=self._headers())
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except Exception as exc:
            log.warning("[AutonomousGitHub] GET %s failed: %s", path, exc)
            return None

    def _api_put(self, path: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """PUT request to the GitHub REST API. Returns parsed JSON or None."""
        if self.dry_run:
            log.info("[AutonomousGitHub] [DRY-RUN] PUT %s — payload keys: %s",
                     path, list(payload.keys()))
            return {"dry_run": True, "path": path}
        try:
            import urllib.request

            url = f"{self._base_api}{path}"
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                url, data=data, headers={**self._headers(), "Content-Type": "application/json"},
                method="PUT",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except Exception as exc:
            log.warning("[AutonomousGitHub] PUT %s failed: %s", path, exc)
            return None

    def _api_post(self, path: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """POST request to the GitHub REST API. Returns parsed JSON or None."""
        if self.dry_run:
            log.info("[AutonomousGitHub] [DRY-RUN] POST %s — payload keys: %s",
                     path, list(payload.keys()))
            return {"dry_run": True, "path": path}
        try:
            import urllib.request

            url = f"{self._base_api}{path}"
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                url, data=data, headers={**self._headers(), "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except Exception as exc:
            log.warning("[AutonomousGitHub] POST %s failed: %s", path, exc)
            return None

    # ------------------------------------------------------------------
    # Read operations (always safe, no authentication required for public repos)
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        """Return True if the minimum required configuration is present."""
        return bool(self.repo)

    def get_repo_info(self) -> Optional[Dict[str, Any]]:
        """Fetch basic repository metadata."""
        if not self.repo:
            return None
        return self._api_get(f"/repos/{self.repo}")

    def get_recent_commits(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return the *limit* most recent commits on the default branch."""
        if not self.repo:
            return []
        data = self._api_get(f"/repos/{self.repo}/commits?per_page={limit}")
        if not isinstance(data, list):
            return []
        return [
            {
                "sha": c.get("sha", "")[:12],
                "message": (c.get("commit") or {}).get("message", "")[:80],
                "author": ((c.get("commit") or {}).get("author") or {}).get("name", ""),
                "date": ((c.get("commit") or {}).get("author") or {}).get("date", ""),
            }
            for c in data
        ]

    def get_file_content(self, file_path: str, ref: Optional[str] = None) -> Optional[str]:
        """Return the decoded text content of a file in the repository."""
        if not self.repo:
            return None
        path = f"/repos/{self.repo}/contents/{file_path}"
        if ref:
            path += f"?ref={ref}"
        data = self._api_get(path)
        if not data or data.get("encoding") != "base64":
            return None
        try:
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        except Exception as exc:
            log.warning("[AutonomousGitHub] decode error for %s: %s", file_path, exc)
            return None

    # ------------------------------------------------------------------
    # Write operations (gated by dry_run and token presence)
    # ------------------------------------------------------------------

    def _get_file_sha(self, file_path: str, ref: Optional[str] = None) -> Optional[str]:
        """Return the blob SHA of an existing file (needed for updates)."""
        if not self.repo:
            return None
        path = f"/repos/{self.repo}/contents/{file_path}"
        if ref:
            path += f"?ref={ref}"
        data = self._api_get(path)
        return data.get("sha") if data else None

    def push_file(
        self,
        file_path: str,
        content: str,
        commit_message: str,
        branch: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create or update *file_path* in the repository.

        Returns a status dict with ``success``, ``dry_run``, and ``message``.
        """
        target_branch = branch or self.branch

        if not self.repo:
            return {"success": False, "message": "GITHUB_REPO not configured"}
        if not self.token and not self.dry_run:
            return {"success": False, "message": "GITHUB_TOKEN not configured"}
        if len(content.encode()) > _MAX_FILE_BYTES:
            return {"success": False,
                    "message": f"Content exceeds {_MAX_FILE_BYTES // 1024} KB limit"}

        existing_sha = self._get_file_sha(file_path, ref=target_branch)
        encoded = base64.b64encode(content.encode()).decode()
        payload: Dict[str, Any] = {
            "message": commit_message,
            "content": encoded,
            "branch": target_branch,
        }
        if existing_sha:
            payload["sha"] = existing_sha

        result = self._api_put(f"/repos/{self.repo}/contents/{file_path}", payload)

        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "file": file_path,
            "branch": target_branch,
            "message": commit_message,
            "dry_run": self.dry_run,
        }
        self._session_improvements.append(record)
        if self.db:
            try:
                self.db.add_fact(
                    f"github_push:{file_path}:{record['ts']}",
                    json.dumps(record),
                    tags=["github", "autonomous"],
                )
            except Exception:
                pass

        if result is None:
            return {"success": False, "message": "API call failed"}
        if self.dry_run:
            return {"success": True, "dry_run": True,
                    "message": f"[DRY-RUN] Would push {file_path} to {target_branch}"}
        return {"success": True, "dry_run": False,
                "message": f"Pushed {file_path} to {target_branch}"}

    def create_pull_request(
        self,
        title: str,
        body: str,
        head_branch: Optional[str] = None,
        base_branch: str = "main",
    ) -> Dict[str, Any]:
        """
        Open a pull request from *head_branch* into *base_branch*.

        Returns a status dict with ``success``, ``dry_run``, and ``url``.
        """
        head = head_branch or self.branch
        if not self.repo:
            return {"success": False, "message": "GITHUB_REPO not configured"}
        if not self.token and not self.dry_run:
            return {"success": False, "message": "GITHUB_TOKEN not configured"}

        payload = {"title": title, "body": body, "head": head, "base": base_branch}
        result = self._api_post(f"/repos/{self.repo}/pulls", payload)

        if result is None:
            return {"success": False, "message": "API call failed"}
        if self.dry_run:
            return {"success": True, "dry_run": True,
                    "url": None,
                    "message": f"[DRY-RUN] Would open PR: {title!r} ({head} → {base_branch})"}
        return {
            "success": True,
            "dry_run": False,
            "url": result.get("html_url"),
            "number": result.get("number"),
            "message": f"PR created: {result.get('html_url', '')}",
        }

    # ------------------------------------------------------------------
    # Status / reporting
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Return a summary of the integration's current state."""
        return {
            "configured": self.is_configured(),
            "repo": self.repo or "(unset)",
            "branch": self.branch,
            "dry_run": self.dry_run,
            "has_token": bool(self.token),
            "session_pushes": len(self._session_improvements),
            "last_push": self._session_improvements[-1] if self._session_improvements else None,
        }

    def session_summary(self) -> str:
        """Human-readable summary of pushes made this session."""
        if not self._session_improvements:
            return "No GitHub pushes this session."
        lines = [f"🐙 GitHub Integration — {len(self._session_improvements)} push(es) this session:"]
        for rec in self._session_improvements[-5:]:
            tag = "[DRY-RUN] " if rec.get("dry_run") else ""
            lines.append(f"  {tag}{rec['file']} → {rec['branch']} | {rec['message'][:60]}")
        return "\n".join(lines)
