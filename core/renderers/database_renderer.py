"""Database file renderer for SQLite and DuckDB."""

from __future__ import annotations

from pathlib import Path

from .base import BaseRenderer, RenderResult
from .file_utils import get_file_metadata


class DatabaseRenderer(BaseRenderer):
    """Renderer for SQLite and DuckDB database files."""
    
    name = "database"
    supported_extensions = [".sqlite", ".db", ".duckdb"]
    
    def can_render(self, file_path: str) -> bool:
        """Check if this renderer can handle the given file."""
        ext = Path(file_path).suffix.lower()
        return ext in self.supported_extensions
    
    def get_supported_extensions(self) -> list[str]:
        """Return list of file extensions this renderer supports."""
        return self.supported_extensions
    
    def render(self, file_path: str) -> RenderResult:
        """Render a database file.
        
        Args:
            file_path: Path to the database file
            
        Returns:
            RenderResult with schema and table information
        """
        path = Path(file_path)
        
        if not path.exists():
            return RenderResult(
                success=False,
                content=None,
                mime_type="application/x-sqlite3",
                viewer_type="database",
                error=f"File not found: {file_path}",
            )
        
        metadata = get_file_metadata(file_path)
        ext = path.suffix.lower()
        
        result = RenderResult(
            success=True,
            content={
                "database_type": "sqlite" if ext in (".sqlite", ".db") else "duckdb",
                "tables": [],
                "views": [],
                "indexes": [],
                "schema_sql": "",
            },
            mime_type="application/json",
            viewer_type="database",
            metadata=metadata,
        )
        
        # Handle SQLite
        if ext in (".sqlite", ".db"):
            try:
                import sqlite3
                con = sqlite3.connect(str(path))
                cur = con.cursor()
                
                # Get tables
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                result.content["tables"] = [row[0] for row in cur.fetchall()]
                
                # Get views
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name"
                )
                result.content["views"] = [row[0] for row in cur.fetchall()]
                
                # Get indexes
                cur.execute(
                    "SELECT name, tbl_name FROM sqlite_master WHERE type='index' ORDER BY name"
                )
                result.content["indexes"] = [
                    {"name": row[0], "table": row[1]} for row in cur.fetchall()
                ]
                
                # Get schema SQL
                cur.execute("SELECT sql FROM sqlite_master WHERE type='table'")
                schemas = cur.fetchall()
                result.content["schema_sql"] = "\n\n".join(
                    s[0] for s in schemas if s[0]
                )
                
                con.close()
            except Exception as exc:
                result.content["error"] = str(exc)
        
        # Handle DuckDB
        elif ext == ".duckdb":
            try:
                import duckdb
                con = duckdb.connect(str(path))
                
                # Get tables
                tables_df = con.execute(
                    "SHOW TABLES"
                ).fetchdf()
                result.content["tables"] = tables_df["name"].tolist() if not tables_df.empty else []
                
                con.close()
            except ImportError:
                result.content["error"] = "duckdb not installed"
            except Exception as exc:
                result.content["error"] = str(exc)
        
        return result
    
    def query(self, file_path: str, sql: str) -> RenderResult:
        """Execute a SQL query on the database.
        
        Args:
            file_path: Path to the database file
            sql: SQL query to execute
            
        Returns:
            RenderResult with query results
        """
        path = Path(file_path)
        
        if not path.exists():
            return RenderResult(
                success=False,
                content=None,
                mime_type="application/json",
                viewer_type="database",
                error=f"File not found: {file_path}",
            )
        
        ext = path.suffix.lower()
        
        try:
            if ext in (".sqlite", ".db"):
                import sqlite3
                import json
                con = sqlite3.connect(str(path))
                cur = con.cursor()
                cur.execute(sql)
                
                columns = [desc[0] for desc in cur.description] if cur.description else []
                rows = [dict(zip(columns, row)) for row in cur.fetchall()]
                
                con.close()
                
                return RenderResult(
                    success=True,
                    content={"columns": columns, "rows": rows},
                    mime_type="application/json",
                    viewer_type="database",
                )
            elif ext == ".duckdb":
                import duckdb
                con = duckdb.connect(str(path))
                df = con.execute(sql).fetchdf()
                con.close()
                
                return RenderResult(
                    success=True,
                    content={"columns": df.columns.tolist(), "rows": df.to_dict("records")},
                    mime_type="application/json",
                    viewer_type="database",
                )
        except Exception as exc:
            return RenderResult(
                success=False,
                content={"error": str(exc)},
                mime_type="application/json",
                viewer_type="database",
                error=f"Query failed: {exc}",
            )


# Register the renderer
def _register() -> None:
    """Register this renderer."""
    from .registry import RendererRegistry
    RendererRegistry.register(DatabaseRenderer())


_register()