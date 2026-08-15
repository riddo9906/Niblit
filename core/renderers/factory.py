"""Renderer factory for creating renderer instances."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .base import BaseRenderer, RenderResult
from .registry import RendererRegistry


class RendererFactory:
    """Factory for creating and using renderers to process files."""
    
    _initialized: bool = False
    
    @classmethod
    def initialize(cls) -> None:
        """Initialize the renderer registry by importing and registering all renderers."""
        if cls._initialized:
            return
        
        # Import all renderers to register them
        try:
            from . import code_renderer  # noqa: F401
            from . import markdown_renderer  # noqa: F401
            from . import pdf_renderer  # noqa: F401
            from . import spreadsheet_renderer  # noqa: F401
            from . import json_renderer  # noqa: F401
            from . import html_renderer  # noqa: F401
            from . import image_renderer  # noqa: F401
            from . import video_renderer  # noqa: F401
            from . import audio_renderer  # noqa: F401
            from . import binary_renderer  # noqa: F401
            from . import archive_renderer  # noqa: F401
            from . import database_renderer  # noqa: F401
            from . import notebook_renderer  # noqa: F401
        except ImportError:
            # Renderers may not be available yet
            pass
        
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
        
        renderer = RendererRegistry.get_renderer_for_file(file_path)
        
        if renderer is None:
            return RenderResult(
                success=False,
                content=None,
                mime_type="application/octet-stream",
                viewer_type="binary",
                error=f"No renderer found for file: {file_path}",
            )
        
        try:
            return renderer.render(file_path)
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