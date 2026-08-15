"""Image file renderer with zoom/pan support."""

from __future__ import annotations

import base64
import io
from pathlib import Path

from .base import BaseRenderer, RenderResult
from .file_utils import get_file_metadata


class ImageRenderer(BaseRenderer):
    """Renderer for image files with metadata extraction."""
    
    name = "image"
    supported_extensions = [".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".bmp", ".tiff", ".tif"]
    
    def can_render(self, file_path: str) -> bool:
        """Check if this renderer can handle the given file."""
        ext = Path(file_path).suffix.lower()
        return ext in self.supported_extensions
    
    def get_supported_extensions(self) -> list[str]:
        """Return list of file extensions this renderer supports."""
        return self.supported_extensions
    
    def render(self, file_path: str) -> RenderResult:
        """Render an image file.
        
        Args:
            file_path: Path to the image file
            
        Returns:
            RenderResult with image data URI and metadata
        """
        path = Path(file_path)
        
        if not path.exists():
            return RenderResult(
                success=False,
                content=None,
                mime_type="image/png",
                viewer_type="image",
                error=f"File not found: {file_path}",
            )
        
        metadata = get_file_metadata(file_path)
        
        # Read image as base64 data URI
        try:
            with open(path, "rb") as f:
                image_data = f.read()
            
            # Detect mime type
            mime_type = self._get_mime_type(path)
            data_uri = f"data:{mime_type};base64,{base64.b64encode(image_data).decode('utf-8')}"
            
            result = RenderResult(
                success=True,
                content={
                    "data_uri": data_uri,
                    "mime_type": mime_type,
                    "size": len(image_data),
                },
                mime_type=mime_type,
                viewer_type="image",
                metadata=metadata,
            )
            
            # Extract image dimensions using Pillow
            try:
                from PIL import Image
                with Image.open(path) as img:
                    result.content["width"] = img.width
                    result.content["height"] = img.height
                    result.content["mode"] = img.mode
            except Exception:
                pass
            
            return result
        except Exception as exc:
            return RenderResult(
                success=False,
                content=None,
                mime_type="image/png",
                viewer_type="image",
                error=f"Could not read image: {exc}",
                metadata=metadata,
            )
    
    def _get_mime_type(self, path: Path) -> str:
        """Get MIME type for an image file."""
        ext = path.suffix.lower()
        mime_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".svg": "image/svg+xml",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".tiff": "image/tiff",
            ".tif": "image/tiff",
        }
        return mime_types.get(ext, "image/png")


# Register the renderer
def _register() -> None:
    """Register this renderer."""
    from .registry import RendererRegistry
    RendererRegistry.register(ImageRenderer())


_register()