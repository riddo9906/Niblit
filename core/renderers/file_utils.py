"""File type detection and metadata utilities for the File Rendering Engine."""

from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class FileMetadata:
    """Metadata for a file to be rendered."""
    path: str
    name: str
    extension: str
    size: int
    created: str
    modified: str
    mime_type: str
    encoding: Optional[str]
    hash_md5: str
    hash_sha256: str
    is_binary: bool
    type_category: str  # 'document', 'code', 'image', 'video', 'audio', 'data', 'archive', 'unknown'


# File extension to category mapping
EXTENSION_CATEGORIES: dict[str, str] = {
    # Documents
    ".pdf": "document",
    ".docx": "document",
    ".odt": "document",
    ".txt": "document",
    ".md": "document",
    ".markdown": "document",
    ".rtf": "document",
    
    # Code
    ".py": "code",
    ".rs": "code",
    ".cs": "code",
    ".java": "code",
    ".js": "code",
    ".ts": "code",
    ".jsx": "code",
    ".tsx": "code",
    ".html": "code",
    ".css": "code",
    ".json": "data",
    ".yaml": "data",
    ".yml": "data",
    ".toml": "data",
    ".sql": "code",
    ".sh": "code",
    ".bash": "code",
    ".lua": "code",
    ".lean": "code",
    
    # Data
    ".csv": "data",
    ".xlsx": "data",
    ".xls": "data",
    ".ods": "data",
    ".sqlite": "data",
    ".db": "data",
    ".duckdb": "data",
    
    # Images
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".svg": "image",
    ".webp": "image",
    ".gif": "image",
    ".bmp": "image",
    ".tiff": "image",
    ".tif": "image",
    
    # Video
    ".mp4": "video",
    ".avi": "video",
    ".mkv": "video",
    ".mov": "video",
    ".webm": "video",
    
    # Audio
    ".mp3": "audio",
    ".wav": "audio",
    ".flac": "audio",
    ".ogg": "audio",
    ".aac": "audio",
    
    # Archives
    ".zip": "archive",
    ".rar": "archive",
    ".7z": "archive",
    ".tar": "archive",
    ".gz": "archive",
}

# Binary file extensions (for quick detection)
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".bmp", ".tiff", ".tif",
    ".mp4", ".avi", ".mkv", ".mov", ".webm",
    ".mp3", ".wav", ".flac", ".ogg", ".aac",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".pdf", ".docx", ".odt", ".xlsx", ".xls", ".ods",
}


def detect_file_type(file_path: str | Path) -> str:
    """Detect the file type category based on extension.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Type category string: 'document', 'code', 'image', 'video', 'audio', 'data', 'archive', 'unknown'
    """
    path = Path(file_path)
    ext = path.suffix.lower()
    return EXTENSION_CATEGORIES.get(ext, "unknown")


def is_binary_file(file_path: str | Path) -> bool:
    """Check if a file is binary based on extension.
    
    Args:
        file_path: Path to the file
        
    Returns:
        True if the file is likely binary
    """
    path = Path(file_path)
    ext = path.suffix.lower()
    return ext in BINARY_EXTENSIONS


def get_file_metadata(file_path: str | Path) -> FileMetadata | None:
    """Extract comprehensive metadata from a file.
    
    Args:
        file_path: Path to the file
        
    Returns:
        FileMetadata dataclass with all extracted metadata, or None if file doesn't exist
    """
    path = Path(file_path)
    
    if not path.exists():
        return None
    
    stat = path.stat()
    
    # Calculate hashes
    md5_hash = hashlib.md5()
    sha256_hash = hashlib.sha256()
    
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                md5_hash.update(chunk)
                sha256_hash.update(chunk)
    except (OSError, IOError):
        pass
    
    # Detect MIME type
    mime_type, _ = mimetypes.guess_type(str(path))
    
    # Detect encoding for text files
    encoding = None
    if not is_binary_file(path):
        encoding = _detect_encoding(path)
    
    return FileMetadata(
        path=str(path),
        name=path.name,
        extension=path.suffix.lower(),
        size=stat.st_size,
        created=datetime.fromtimestamp(stat.st_ctime).isoformat(),
        modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
        mime_type=mime_type or "application/octet-stream",
        encoding=encoding,
        hash_md5=md5_hash.hexdigest(),
        hash_sha256=sha256_hash.hexdigest(),
        is_binary=is_binary_file(path),
        type_category=detect_file_type(path),
    )


def _detect_encoding(file_path: Path) -> str:
    """Detect text file encoding by checking BOM and common patterns."""
    try:
        with open(file_path, "rb") as f:
            raw = f.read(4)
        
        # Check BOM markers
        if raw.startswith(b'\xef\xbb\xbf'):
            return "utf-8-sig"
        if raw.startswith(b'\xff\xfe'):
            return "utf-16-le"
        if raw.startswith(b'\xfe\xff'):
            return "utf-16-be"
        
        # Default to utf-8
        return "utf-8"
    except (OSError, IOError):
        return "utf-8"