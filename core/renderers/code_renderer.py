"""Code file renderer with syntax highlighting support."""

from __future__ import annotations

from pathlib import Path

from .base import BaseRenderer, RenderResult
from .file_utils import get_file_metadata


# Map file extensions to Pygments lexer names
LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".rs": "rust",
    ".cs": "csharp",
    ".java": "java",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "jsx",
    ".tsx": "tsx",
    ".html": "html",
    ".css": "css",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".sql": "sql",
    ".sh": "bash",
    ".bash": "bash",
    ".lua": "lua",
    ".lean": "lean",
    ".xml": "xml",
    ".go": "go",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".r": "r",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".m": "objectivec",
    ".mm": "objectivec",
    ".pl": "perl",
    ".pm": "perl",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hrl": "erlang",
    ".clj": "clojure",
    ".lisp": "lisp",
    ".scm": "scheme",
    ".hs": "haskell",
    ".ml": "ocaml",
    ".vim": "vim",
    ".dockerfile": "dockerfile",
    ".docker": "dockerfile",
    ".tf": "terraform",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "nginx",
}


class CodeRenderer(BaseRenderer):
    """Renderer for code files with syntax highlighting."""
    
    name = "code"
    supported_extensions = sorted(set(LANGUAGE_MAP.keys()))
    
    @classmethod
    def can_render(cls, file_path: str) -> bool:
        """Check if this renderer can handle the given file."""
        ext = Path(file_path).suffix.lower()
        return ext in LANGUAGE_MAP
    
    @classmethod
    def get_supported_extensions(cls) -> list[str]:
        """Return list of file extensions this renderer supports."""
        return sorted(set(LANGUAGE_MAP.keys()))
    
    def render(self, file_path: str) -> RenderResult:
        """Render a code file with syntax highlighting.
        
        Args:
            file_path: Path to the code file
            
        Returns:
            RenderResult with highlighted code and tokens
        """
        path = Path(file_path)
        
        if not path.exists():
            return RenderResult(
                success=False,
                content=None,
                mime_type="text/plain",
                viewer_type="code",
                error=f"File not found: {file_path}",
            )
        
        metadata = get_file_metadata(file_path)
        
        try:
            # Read the file content
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                content = path.read_text(encoding="latin-1")
            except Exception as exc:
                return RenderResult(
                    success=False,
                    content=None,
                    mime_type="text/plain",
                    viewer_type="code",
                    error=f"Could not read file: {exc}",
                    metadata=metadata,
                )
        except Exception as exc:
            return RenderResult(
                success=False,
                content=None,
                mime_type="text/plain",
                viewer_type="code",
                error=f"Could not read file: {exc}",
                metadata=metadata,
            )
        
        # Get language for syntax highlighting
        ext = path.suffix.lower()
        language = LANGUAGE_MAP.get(ext, "text")
        
        # Try to highlight with Pygments
        try:
            import pygments
            from pygments.lexers import get_lexer_by_name
            from pygments.formatters import JsonFormatter
            
            lexer = get_lexer_by_name(language, stripall=False)
            formatter = JsonFormatter(style="monokai")
            
            highlighted = pygments.highlight(content, lexer, formatter)
            
            import json
            tokens = json.loads(highlighted)
            
            return RenderResult(
                success=True,
                content={
                    "language": language,
                    "tokens": tokens,
                    "lines": content.splitlines(),
                },
                mime_type="application/json",
                viewer_type="code",
                raw_content=content,
                metadata=metadata,
            )
        except ImportError:
            # Pygments not available, return raw content
            return RenderResult(
                success=True,
                content={
                    "language": language,
                    "tokens": None,
                    "lines": content.splitlines(),
                },
                mime_type="text/plain",
                viewer_type="code",
                raw_content=content,
                metadata=metadata,
            )


# Register the renderer
def _register() -> None:
    """Register this renderer."""
    from .registry import RendererRegistry
    RendererRegistry.register(CodeRenderer)


_register()