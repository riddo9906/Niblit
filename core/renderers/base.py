"""Base renderer interface for all file type renderers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

from .file_utils import FileMetadata


@dataclass
class RenderResult:
    """Result from a renderer containing rendered content and metadata."""
    success: bool
    content: Any  # The rendered content (varies by type)
    mime_type: str
    viewer_type: str  # 'code', 'pdf', 'markdown', 'image', 'spreadsheet', etc.
    raw_content: Optional[str] = None  # Original text content if applicable
    error: Optional[str] = None
    metadata: Optional[FileMetadata] = None


class BaseRenderer(ABC):
    """Abstract base class for all file type renderers."""

    name: str = "base"
    supported_extensions: list[str] = []

    @classmethod
    @abstractmethod
    def can_render(cls, file_path: str) -> bool:
        """Check if this renderer can handle the given file.

        Class method because it is used for capability discovery against the
        renderer *class* (registered, not yet instantiated).
        """
        raise NotImplementedError

    @abstractmethod
    def render(self, file_path: str) -> RenderResult:
        """Render the file and return structured result."""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def get_supported_extensions(cls) -> list[str]:
        """Return list of file extensions this renderer supports.

        Class method so the registry can discover capabilities from the renderer
        *class* without instantiating it.
        """
        raise NotImplementedError