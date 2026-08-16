"""Markdown file renderer with GitHub-flavored support."""

from __future__ import annotations

from pathlib import Path

from .base import BaseRenderer, RenderResult
from .file_utils import get_file_metadata


class MarkdownRenderer(BaseRenderer):
    """Renderer for Markdown files with GitHub-style rendering."""
    
    name = "markdown"
    supported_extensions = [".md", ".markdown"]
    
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
        """Render a Markdown file.
        
        Args:
            file_path: Path to the Markdown file
            
        Returns:
            RenderResult with parsed Markdown and metadata
        """
        path = Path(file_path)
        
        if not path.exists():
            return RenderResult(
                success=False,
                content=None,
                mime_type="text/plain",
                viewer_type="markdown",
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
                    mime_type="text/plain",
                    viewer_type="markdown",
                    error=f"Could not read file: {exc}",
                    metadata=metadata,
                )
        except Exception as exc:
            return RenderResult(
                success=False,
                content=None,
                mime_type="text/plain",
                viewer_type="markdown",
                error=f"Could not read file: {exc}",
                metadata=metadata,
            )
        
        # Extract frontmatter if present
        frontmatter = None
        body = content
        if content.startswith("---\n"):
            parts = content.split("---\n", 2)
            if len(parts) >= 3:
                frontmatter = parts[1]
                body = parts[2].strip()
        
        return RenderResult(
            success=True,
            content={
                "raw": content,
                "body": body,
                "frontmatter": frontmatter,
            },
            mime_type="text/markdown",
            viewer_type="markdown",
            raw_content=content,
            metadata=metadata,
        )


# Register the renderer
def _register() -> None:
    """Register this renderer."""
    from .registry import RendererRegistry
    RendererRegistry.register(MarkdownRenderer)


_register()