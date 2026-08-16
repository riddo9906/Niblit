"""Jupyter/IPYNB notebook renderer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import BaseRenderer, RenderResult
from .registry import RendererRegistry
from .file_utils import get_file_metadata


class NotebookRenderer(BaseRenderer):
    """Renderer for Jupyter notebooks (.ipynb files)."""

    name = "notebook"
    supported_extensions = [".ipynb"]

    @classmethod
    def can_render(cls, file_path: str) -> bool:
        """Check if this renderer can handle the given file."""
        ext = Path(file_path).suffix.lower()
        return ext in cls.supported_extensions

    @classmethod
    def get_supported_extensions(cls) -> list[str]:
        """Return list of file extensions this renderer supports."""
        return list(cls.supported_extensions)

    def render(self, file_path: str) -> RenderResult:
        """Render a Jupyter notebook.

        Args:
            file_path: Path to the notebook file

        Returns:
            RenderResult with notebook cells
        """
        metadata = get_file_metadata(file_path)
        if metadata is None:
            return RenderResult(
                success=False,
                content=None,
                mime_type="application/x-ipynb+json",
                viewer_type="notebook",
                error=f"File not found: {file_path}",
            )

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                nb_data = json.load(f)

            cells = []
            for cell in nb_data.get("cells", []):
                cell_info = {
                    "cell_type": cell.get("cell_type", "code"),
                    "source": "".join(cell.get("source", [])),
                    "outputs": cell.get("outputs", []),
                    "execution_count": cell.get("execution_count"),
                }
                cells.append(cell_info)

            return RenderResult(
                success=True,
                content={
                    "filename": metadata.name,
                    "cells": cells,
                    "cell_count": len(cells),
                    "metadata": nb_data.get("metadata", {}),
                },
                mime_type=metadata.mime_type or "application/x-ipynb+json",
                viewer_type="notebook",
            )
        except Exception as exc:
            return RenderResult(
                success=False,
                content=None,
                mime_type=metadata.mime_type or "application/x-ipynb+json",
                viewer_type="notebook",
                error=str(exc),
            )


RendererRegistry.register(NotebookRenderer)


def render_notebook(file_path: str) -> RenderResult:
    """Convenience function to render a notebook."""
    return NotebookRenderer().render(file_path)
