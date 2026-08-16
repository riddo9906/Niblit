"""HTML file renderer with preview support."""

from __future__ import annotations

from pathlib import Path

from .base import BaseRenderer, RenderResult
from .file_utils import get_file_metadata


class HTMLRenderer(BaseRenderer):
    """Renderer for HTML files with preview support."""
    
    name = "html"
    supported_extensions = [".html", ".htm", ".xhtml"]
    
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
        """Render an HTML file.
        
        Args:
            file_path: Path to the HTML file
            
        Returns:
            RenderResult with HTML content and metadata
        """
        path = Path(file_path)
        
        if not path.exists():
            return RenderResult(
                success=False,
                content=None,
                mime_type="text/html",
                viewer_type="html",
                error=f"File not found: {file_path}",
            )
        
        metadata = get_file_metadata(file_path)
        
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                content = path.read_text(encoding="latin-1")
            except Exception as exc:
                return RenderResult(
                    success=False,
                    content=None,
                    mime_type="text/html",
                    viewer_type="html",
                    error=f"Could not read file: {exc}",
                    metadata=metadata,
                )
        except Exception as exc:
            return RenderResult(
                success=False,
                content=None,
                mime_type="text/html",
                viewer_type="html",
                error=f"Could not read file: {exc}",
                metadata=metadata,
            )
        
        return RenderResult(
            success=True,
            content={
                "html": content,
            },
            mime_type="text/html",
            viewer_type="html",
            raw_content=content,
            metadata=metadata,
        )


# Register the renderer
def _register() -> None:
    """Register this renderer."""
    from .registry import RendererRegistry
    RendererRegistry.register(HTMLRenderer)


_register()