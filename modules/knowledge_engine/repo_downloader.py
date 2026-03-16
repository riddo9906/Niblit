#!/usr/bin/env python3
"""
modules/knowledge_engine/repo_downloader.py

Clone repositories locally for code analysis.

Large repositories are shallow-cloned (``--depth 1``) to save disk and time.
A configurable working directory keeps clones isolated.

Usage::

    from modules.knowledge_engine.repo_downloader import RepoDownloader
    dl = RepoDownloader(work_dir="/tmp/seke_repos")
    path = dl.clone("https://github.com/tiangolo/fastapi")
    dl.cleanup(path)
"""

import logging
import os
import shutil
import subprocess
import tempfile
from typing import Optional

log = logging.getLogger("RepoDownloader")

_DEFAULT_WORK_DIR = os.path.join(tempfile.gettempdir(), "seke_repos")


class RepoDownloader:
    """
    Clone public GitHub repositories for local analysis.

    Args:
        work_dir: Base directory for clones.  Defaults to a sub-directory of
                  the system temp folder.
        timeout:  Maximum seconds to wait for ``git clone`` to finish.
        shallow:  When True (default) clones with ``--depth 1``.
    """

    def __init__(
        self,
        work_dir: str = _DEFAULT_WORK_DIR,
        timeout: int = 60,
        shallow: bool = True,
    ) -> None:
        self.work_dir = work_dir
        self.timeout = timeout
        self.shallow = shallow
        os.makedirs(self.work_dir, exist_ok=True)

    # ── public API ────────────────────────────────────────────────────────────

    def clone(self, repo_url: str, name: Optional[str] = None) -> Optional[str]:
        """
        Clone *repo_url* into ``work_dir/<name>``.

        Returns the local path on success, None on failure.
        """
        if not name:
            name = repo_url.rstrip("/").split("/")[-1].removesuffix(".git")
        dest = os.path.join(self.work_dir, name)

        if os.path.isdir(dest):
            log.debug("RepoDownloader: %s already cloned at %s", name, dest)
            return dest

        cmd = ["git", "clone"]
        if self.shallow:
            cmd += ["--depth", "1"]
        cmd += ["--", repo_url, dest]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            if result.returncode == 0:
                log.info("RepoDownloader: cloned %s → %s", repo_url, dest)
                return dest
            log.warning(
                "RepoDownloader: git clone failed (rc=%d): %s",
                result.returncode,
                result.stderr[:200],
            )
            return None
        except subprocess.TimeoutExpired:
            log.warning("RepoDownloader: clone timed out for %s", repo_url)
            return None
        except Exception as exc:  # noqa: BLE001
            log.warning("RepoDownloader: clone error: %s", exc)
            return None

    def cleanup(self, path: str) -> None:
        """Remove a cloned repository directory."""
        if path and os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
            log.debug("RepoDownloader: removed %s", path)

    def cleanup_all(self) -> None:
        """Remove all cloned repositories in work_dir."""
        if os.path.isdir(self.work_dir):
            shutil.rmtree(self.work_dir, ignore_errors=True)
            os.makedirs(self.work_dir, exist_ok=True)
            log.info("RepoDownloader: cleaned work_dir %s", self.work_dir)

    def list_cloned(self):
        """Return names of directories currently in work_dir."""
        if not os.path.isdir(self.work_dir):
            return []
        return [
            d for d in os.listdir(self.work_dir)
            if os.path.isdir(os.path.join(self.work_dir, d))
        ]
