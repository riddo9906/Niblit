"""PDF file renderer with text extraction and thumbnail support."""

from __future__ import annotations

import base64
import io
from pathlib import Path

from .base import BaseRenderer, RenderResult
from .file_utils import get_file_metadata


class PDFRenderer(BaseRenderer):
    """Renderer for PDF files with text extraction and thumbnail generation."""
    
    name = "pdf"
    supported_extensions = [".pdf"]
    
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
        """Render a PDF file.
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            RenderResult with extracted text and metadata
        """
        path = Path(file_path)
        
        if not path.exists():
            return RenderResult(
                success=False,
                content=None,
                mime_type="application/pdf",
                viewer_type="pdf",
                error=f"File not found: {file_path}",
            )
        
        metadata = get_file_metadata(file_path)
        
        result = RenderResult(
            success=True,
            content={},
            mime_type="application/pdf",
            viewer_type="pdf",
            metadata=metadata,
        )
        
        # Extract text using pdfplumber or pypdf
        text_pages: list[str] = []
        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    text_pages.append(text)
            result.content["pages"] = text_pages
            result.content["total_pages"] = len(text_pages)
        except ImportError:
            try:
                import pypdf
                reader = pypdf.PdfReader(path)
                for page in reader.pages:
                    text = page.extract_text() or ""
                    text_pages.append(text)
                result.content["pages"] = text_pages
                result.content["total_pages"] = len(text_pages)
            except ImportError:
                result.content["pages"] = []
                result.content["total_pages"] = 0
        except Exception as exc:
            result.content["pages"] = []
            result.content["total_pages"] = 0
            result.content["extract_error"] = str(exc)
        
        # Generate thumbnail (first page as base64 PNG)
        try:
            import pdfplumber
            from PIL import Image
            
            with pdfplumber.open(path) as pdf:
                if pdf.pages:
                    first_page = pdf.pages[0]
                    # Render page as image
                    im = first_page.to_image()
                    if im:
                        # Convert to PNG bytes
                        img_bytes = io.BytesIO()
                        im.original.save(img_bytes, format="PNG")
                        thumbnail_b64 = base64.b64encode(img_bytes.getvalue()).decode("utf-8")
                        result.content["thumbnail"] = f"data:image/png;base64,{thumbnail_b64}"
        except Exception:
            # Thumbnail generation might fail, that's okay
            pass
        
        return result


# Register the renderer
def _register() -> None:
    """Register this renderer."""
    from .registry import RendererRegistry
    RendererRegistry.register(PDFRenderer)


_register()