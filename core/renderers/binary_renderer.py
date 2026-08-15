"""Binary file renderer with hex view support."""

from __future__ import annotations

from pathlib import Path

from .base import BaseRenderer, RenderResult
from .file_utils import get_file_metadata


class BinaryRenderer(BaseRenderer):
    """Renderer for binary files with hex dump view."""
    
    name = "binary"
    supported_extensions = []  # Catch-all for unknown files
    
    def can_render(self, file_path: str) -> bool:
        """This renderer can handle any file as fallback."""
        return True
    
    def get_supported_extensions(self) -> list[str]:
        """Return list of file extensions this renderer supports."""
        return self.supported_extensions
    
    def render(self, file_path: str) -> RenderResult:
        """Render a binary file with hex dump.
        
        Args:
            file_path: Path to the binary file
            
        Returns:
            RenderResult with hex dump and metadata
        """
        path = Path(file_path)
        
        if not path.exists():
            return RenderResult(
                success=False,
                content=None,
                mime_type="application/octet-stream",
                viewer_type="binary",
                error=f"File not found: {file_path}",
            )
        
        metadata = get_file_metadata(file_path)
        
        try:
            with open(path, "rb") as f:
                binary_data = f.read(65536)  # First 64KB for preview
        except Exception as exc:
            return RenderResult(
                success=False,
                content=None,
                mime_type="application/octet-stream",
                viewer_type="binary",
                error=f"Could not read file: {exc}",
                metadata=metadata,
            )
        
        # Generate hex dump
        hex_lines = []
        ascii_lines = []
        offset = 0
        
        for i in range(0, len(binary_data), 16):
            chunk = binary_data[i:i + 16]
            hex_parts = []
            ascii_parts = []
            
            for byte in chunk:
                hex_parts.append(f"{byte:02x}")
                ascii_parts.append(chr(byte) if 32 <= byte <= 126 else ".")
            
            hex_lines.append(f"{offset:08x}  " + " ".join(hex_parts) + "  " + "".join(ascii_parts))
            ascii_lines.append("".join(ascii_parts))
            offset += 16
        
        return RenderResult(
            success=True,
            content={
                "hex_dump": hex_lines,
                "total_size": path.stat().st_size,
            },
            mime_type="application/octet-stream",
            viewer_type="binary",
            metadata=metadata,
        )


# Register the renderer
def _register() -> None:
    """Register this renderer."""
    from .registry import RendererRegistry
    RendererRegistry.register(BinaryRenderer())


_register()