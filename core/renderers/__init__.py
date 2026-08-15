"""File Rendering Engine - Core module for Niblit."""

from .base import BaseRenderer
from .registry import RendererRegistry
from .factory import RendererFactory
from .file_utils import detect_file_type, get_file_metadata, is_binary_file

__all__ = [
    "BaseRenderer",
    "RendererRegistry",
    "RendererFactory",
    "detect_file_type",
    "get_file_metadata",
    "is_binary_file",
]