"""YAML file renderer with syntax highlighting."""

from __future__ import annotations

from pathlib import Path

from .base import BaseRenderer, RenderResult
from .file_utils import get_file_metadata


class YAMLRenderer(BaseRenderer):
    """Renderer for YAML files with tree navigation."""
    
    name = "yaml"
    supported_extensions = [".yaml", ".yml"]
    
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
        """Render a YAML file.
        
        Args:
            file_path: Path to the YAML file
            
        Returns:
            RenderResult with parsed YAML data
        """
        path = Path(file_path)
        
        if not path.exists():
            return RenderResult(
                success=False,
                content=None,
                mime_type="application/x-yaml",
                viewer_type="yaml",
                error=f"File not found: {file_path}",
            )
        
        metadata = get_file_metadata(file_path)
        
        try:
            import yaml
            raw_content = path.read_text(encoding="utf-8")
            data = yaml.safe_load(raw_content)
        except ImportError:
            return RenderResult(
                success=False,
                content=None,
                mime_type="application/x-yaml",
                viewer_type="yaml",
                error="PyYAML not installed",
                metadata=metadata,
            )
        except yaml.YAMLError as exc:
            return RenderResult(
                success=False,
                content=None,
                mime_type="application/x-yaml",
                viewer_type="yaml",
                error=f"Invalid YAML: {exc}",
                metadata=metadata,
            )
        except Exception as exc:
            return RenderResult(
                success=False,
                content=None,
                mime_type="application/x-yaml",
                viewer_type="yaml",
                error=f"Could not read file: {exc}",
                metadata=metadata,
            )
        
        return RenderResult(
            success=True,
            content={
                "data": data,
                "raw": raw_content,
            },
            mime_type="application/json",
            viewer_type="yaml",
            raw_content=raw_content,
            metadata=metadata,
        )


# Register the renderer
def _register() -> None:
    from .registry import RendererRegistry
    RendererRegistry.register(YAMLRenderer)


_register()