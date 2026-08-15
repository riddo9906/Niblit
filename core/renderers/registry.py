"""Renderer registry for managing and routing to appropriate renderers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .base import BaseRenderer


class RendererRegistry:
    """Registry for all file type renderers."""
    
    _renderers: dict[str, BaseRenderer] = {}
    _extension_map: dict[str, str] = {}  # extension -> renderer name
    
    @classmethod
    def register(cls, renderer: BaseRenderer) -> None:
        """Register a renderer."""
        cls._renderers[renderer.name] = renderer
        for ext in renderer.get_supported_extensions():
            cls._extension_map[ext.lower()] = renderer.name
    
    @classmethod
    def get_renderer(cls, name: str) -> Optional[BaseRenderer]:
        """Get a renderer by name."""
        return cls._renderers.get(name)
    
    @classmethod
    def get_renderer_for_file(cls, file_path: str) -> Optional[BaseRenderer]:
        """Get the appropriate renderer for a file based on extension.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Renderer that can handle this file, or None
        """
        from pathlib import Path
        
        ext = Path(file_path).suffix.lower()
        renderer_name = cls._extension_map.get(ext)
        if renderer_name:
            return cls._renderers.get(renderer_name)
        return None
    
    @classmethod
    def get_all_renderers(cls) -> list[BaseRenderer]:
        """Get all registered renderers."""
        return list(cls._renderers.values())
    
    @classmethod
    def get_registered_names(cls) -> list[str]:
        """Get names of all registered renderers."""
        return sorted(cls._renderers.keys())