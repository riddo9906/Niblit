"""Audio file renderer - displays audio preview and metadata."""

from __future__ import annotations

import base64
from pathlib import Path

from .base import BaseRenderer, RenderResult
from .registry import RendererRegistry
from .file_utils import get_file_metadata


class AudioRenderer(BaseRenderer):
    """Renderer for audio files (mp3, wav, ogg, etc.)."""
    
    name = "audio"
    supported_extensions = [".mp3", ".wav", ".ogg", ".oga", ".flac", ".aac", ".m4a", ".wma"]
    
    def render(self, file_path: str) -> RenderResult:
        """Render an audio file.
        
        Args:
            file_path: Path to the audio file
            
        Returns:
            RenderResult with audio data URI and metadata
        """
        metadata = get_file_metadata(file_path)
        if metadata is None:
            return RenderResult(
                success=False,
                content=None,
                mime_type="audio/mpeg",
                viewer_type="audio",
                error=f"File not found: {file_path}",
            )
        
        path = Path(file_path)
        
        try:
            # Read audio file as base64 for preview
            with open(path, "rb") as f:
                content_bytes = f.read()
            
            # Check file size - limit to 5MB for base64 encoding
            if len(content_bytes) > 5 * 1024 * 1024:
                return RenderResult(
                    success=True,
                    content={
                        "filename": metadata.name,
                        "size": metadata.size,
                        "mime_type": metadata.mime_type or "audio/mpeg",
                        "too_large": True,
                    },
                    mime_type=metadata.mime_type or "audio/mpeg",
                    viewer_type="audio",
                )
            
            # Encode as base64
            base64_data = base64.b64encode(content_bytes).decode("utf-8")
            
            return RenderResult(
                success=True,
                content={
                    "filename": metadata.name,
                    "base64": base64_data,
                    "mime_type": metadata.mime_type or "audio/mpeg",
                    "size": metadata.size,
                },
                mime_type=metadata.mime_type or "audio/mpeg",
                viewer_type="audio",
            )
        except Exception as exc:
            return RenderResult(
                success=False,
                content=None,
                mime_type=metadata.mime_type or "audio/mpeg",
                viewer_type="audio",
                error=str(exc),
            )


RendererRegistry.register(AudioRenderer)


def render_audio(file_path: str) -> RenderResult:
    """Convenience function to render an audio file."""
    return AudioRenderer().render(file_path)