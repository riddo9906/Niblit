"""Archive file renderer with tree view support."""

from __future__ import annotations

from pathlib import Path

from .base import BaseRenderer, RenderResult
from .file_utils import get_file_metadata


class ArchiveRenderer(BaseRenderer):
    """Renderer for archive files (ZIP, RAR, 7Z, TAR, GZ) with tree view."""
    
    name = "archive"
    supported_extensions = [".zip", ".rar", ".7z", ".tar", ".gz"]
    
    def can_render(self, file_path: str) -> bool:
        """Check if this renderer can handle the given file."""
        ext = Path(file_path).suffix.lower()
        return ext in self.supported_extensions
    
    def get_supported_extensions(self) -> list[str]:
        """Return list of file extensions this renderer supports."""
        return self.supported_extensions
    
    def render(self, file_path: str) -> RenderResult:
        """Render an archive file.
        
        Args:
            file_path: Path to the archive file
            
        Returns:
            RenderResult with file tree and metadata
        """
        path = Path(file_path)
        
        if not path.exists():
            return RenderResult(
                success=False,
                content=None,
                mime_type="application/zip",
                viewer_type="archive",
                error=f"File not found: {file_path}",
            )
        
        metadata = get_file_metadata(file_path)
        ext = path.suffix.lower()
        
        files: list[dict] = []
        
        # Handle ZIP files
        if ext == ".zip":
            try:
                import zipfile
                with zipfile.ZipFile(path, "r") as zf:
                    for info in zf.infolist():
                        files.append({
                            "name": info.filename,
                            "size": info.file_size,
                            "compressed_size": info.compress_size,
                            "is_dir": info.is_dir(),
                            "modified": info.date_time,
                        })
            except Exception as exc:
                return RenderResult(
                    success=False,
                    content={"error": str(exc)},
                    mime_type="application/zip",
                    viewer_type="archive",
                    metadata=metadata,
                )
        
        # Handle TAR files
        elif ext in (".tar", ".gz"):
            try:
                import tarfile
                mode = "r:gz" if ext == ".gz" else "r"
                with tarfile.open(path, mode) as tf:
                    for member in tf.getmembers():
                        files.append({
                            "name": member.name,
                            "size": member.size,
                            "is_dir": member.isdir(),
                            "modified": member.mtime,
                        })
            except Exception as exc:
                return RenderResult(
                    success=False,
                    content={"error": str(exc)},
                    mime_type="application/x-tar",
                    viewer_type="archive",
                    metadata=metadata,
                )
        
        # Other formats may need external tools
        else:
            files = [{"error": f"Unsupported archive format: {ext}"}]
        
        return RenderResult(
            success=True,
            content={
                "files": files,
                "total_files": len([f for f in files if not f.get("is_dir", False)]),
            },
            mime_type=self._get_mime_type(ext),
            viewer_type="archive",
            metadata=metadata,
        )
    
    def _get_mime_type(self, ext: str) -> str:
        """Get MIME type for archive format."""
        mime_types = {
            ".zip": "application/zip",
            ".rar": "application/x-rar-compressed",
            ".7z": "application/x-7z-compressed",
            ".tar": "application/x-tar",
            ".gz": "application/gzip",
        }
        return mime_types.get(ext, "application/octet-stream")


# Register the renderer
def _register() -> None:
    """Register this renderer."""
    from .registry import RendererRegistry
    RendererRegistry.register(ArchiveRenderer())


_register()