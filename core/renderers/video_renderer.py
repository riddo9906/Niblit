"""Video file renderer - displays video preview and metadata."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

from .base import BaseRenderer, RenderResult
from .registry import RendererRegistry
from .file_utils import get_file_metadata, FileMetadata


class VideoRenderer(BaseRenderer):
    """Renderer for video files (mp4, webm, ogg, etc.)."""
    
    name = "video"
    supported_extensions = [".mp4", ".webm", ".ogg", ".ogv", ".mov", ".avi", ".mkv", ".wmv"]
    
    def render(self, file_path: str) -> RenderResult:
        """Render a video file.
        
        Args:
            file_path: Path to the video file
            
        Returns:
            RenderResult with video data URI and metadata
        """
        metadata = get_file_metadata(file_path)
        if metadata is None:
            return RenderResult(
                success=False,
                content=None,
                mime_type="video/mp4",
                viewer_type="video",
                error=f"File not found: {file_path}",
            )
        
        path = Path(file_path)
        
        try:
            # Read video file as base64 for preview
            with open(path, "rb") as f:
                content_bytes = f.read()
            
            # Check file size - limit to 10MB for base64 encoding
            if len(content_bytes) > 10 * 1024 * 1024:
                return RenderResult(
                    success=True,
                    content={
                        "filename": metadata.name,
                        "size": metadata.size,
                        "mime_type": metadata.mime_type or "video/mp4",
                        "too_large": True,
                    },
                    mime_type=metadata.mime_type or "video/mp4",
                    viewer_type="video",
                )
            
            # Encode as base64
            base64_data = base64.b64encode(content_bytes).decode("utf-8")
            
            return RenderResult(
                success=True,
                content={
                    "filename": metadata.name,
                    "base64": base64_data,
                    "mime_type": metadata.mime_type or "video/mp4",
                    "size": metadata.size,
                },
                mime_type=metadata.mime_type or "video/mp4",
                viewer_type="video",
            )
        except Exception as exc:
            return RenderResult(
                success=False,
                content=None,
                mime_type=metadata.mime_type or "video/mp4",
                viewer_type="video",
                error=str(exc),
            )


RendererRegistry.register(VideoRenderer)


def render_video(file_path: str) -> RenderResult:
    """Convenience function to render a video file."""
    return VideoRenderer().render(file_path)