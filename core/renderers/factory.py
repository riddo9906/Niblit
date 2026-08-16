"""Renderer factory for creating renderer instances."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Optional

from .base import BaseRenderer, RenderResult
from .registry import RendererRegistry

log = logging.getLogger("RendererFactory")

#: Ordered list of renderer modules to import/register during initialization.
#: Imported one at a time so an optional renderer failure never blocks the rest.
_RENDERER_MODULES = (
    "code_renderer",
    "markdown_renderer",
    "json_renderer",
    "yaml_renderer",
    "html_renderer",
    "pdf_renderer",
    "image_renderer",
    "video_renderer",
    "audio_renderer",
    "binary_renderer",
    "archive_renderer",
    "spreadsheet_renderer",
    "database_renderer",
    "notebook_renderer",
)


class RendererFactory:
    """Factory for creating and using renderers to process files."""

    _initialized: bool = False

    @classmethod
    def initialize(cls) -> None:
        """Initialize the renderer registry.

        Idempotent. Each renderer module is imported individually; an *optional*
        renderer that cannot be imported is logged and skipped so that content
        renderers (text / code / json / markdown / image …) remain available.
        Allocation errors that are NOT pure ``ImportError`` (e.g. a broken
        ``BaseRenderer`` contract) propagate so they are surfaced in tests.
        """
        if cls._initialized:
            return

        for mod_name in _RENDERER_MODULES:
            try:
                importlib.import_module(f".{mod_name}", __package__)
            except ImportError as exc:
                # Optional dependency missing for this renderer only.
                log.warning("Renderer '%s' unavailable: %s", mod_name, exc)

        cls._initialized = True

    @classmethod
    def render_file(cls, file_path: str) -> RenderResult:
        """Render a file using the appropriate renderer.

        Args:
            file_path: Path to the file to render

        Returns:
            RenderResult with rendered content
        """
        cls.initialize()

        renderer_cls = RendererRegistry.get_renderer_for_file(file_path)

        if renderer_cls is None:
            return RenderResult(
                success=False,
                content=None,
                mime_type="application/octet-stream",
                viewer_type="binary",
                error=f"No renderer found for file: {file_path}",
            )

        try:
            # The registry stores classes; instantiate only when rendering.
            return renderer_cls().render(file_path)
        except Exception as exc:
            return RenderResult(
                success=False,
                content=None,
                mime_type="application/octet-stream",
                viewer_type="error",
                error=str(exc),
            )

    @classmethod
    def get_supported_types(cls) -> dict[str, list[str]]:
        """Get all supported file types mapped to their renderer.

        Returns:
            Dict mapping renderer names to their supported extensions
        """
        cls.initialize()

        result: dict[str, list[str]] = {}
        for renderer in RendererRegistry.get_all_renderers():
            result[renderer.name] = renderer.get_supported_extensions()
        return result