"""JSON file renderer with tree view support."""

from __future__ import annotations

import json
from pathlib import Path

from .base import BaseRenderer, RenderResult
from .file_utils import get_file_metadata


class JSONRenderer(BaseRenderer):
    """Renderer for JSON files with interactive tree view."""
    
    name = "json"
    supported_extensions = [".json"]
    
    @classmethod
    def can_render(cls, file_path: str) -> bool:
        """Check if this renderer can handle the given file."""
        ext = Path(file_path).suffix.lower()
        return ext in cls.supported_extensions
    
    @classmethod
    def get_supported_extensions(cls) -> list[str]:
        """Return list of file extensions this renderer supports."""
        return cls.supported_extensions
    
    def render(self, file_path: str) -> RenderResult:
        """Render a JSON file.
        
        Args:
            file_path: Path to the JSON file
            
        Returns:
            RenderResult with parsed JSON and formatted view
        """
        path = Path(file_path)
        
        if not path.exists():
            return RenderResult(
                success=False,
                content=None,
                mime_type="application/json",
                viewer_type="json",
                error=f"File not found: {file_path}",
            )
        
        metadata = get_file_metadata(file_path)
        
        try:
            raw_content = path.read_text(encoding="utf-8")
            data = json.loads(raw_content)
            formatted = json.dumps(data, indent=2, ensure_ascii=False)
        except json.JSONDecodeError as exc:
            return RenderResult(
                success=False,
                content={"raw": raw_content if "raw_content" in dir() else ""},
                mime_type="application/json",
                viewer_type="json",
                error=f"Invalid JSON: {exc}",
                metadata=metadata,
            )
        except Exception as exc:
            return RenderResult(
                success=False,
                content=None,
                mime_type="application/json",
                viewer_type="json",
                error=f"Could not read file: {exc}",
                metadata=metadata,
            )
        
        return RenderResult(
            success=True,
            content={
                "data": data,
                "formatted": formatted,
                "size": len(raw_content),
            },
            mime_type="application/json",
            viewer_type="json",
            raw_content=raw_content,
            metadata=metadata,
        )


# Register the renderer
def _register() -> None:
    """Register this renderer."""
    from .registry import RendererRegistry
    RendererRegistry.register(JSONRenderer)


_register()