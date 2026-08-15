"""Spreadsheet/CSV renderer with grid view support."""

from __future__ import annotations

from pathlib import Path

from .base import BaseRenderer, RenderResult
from .file_utils import get_file_metadata


class SpreadsheetRenderer(BaseRenderer):
    """Renderer for CSV, Excel, and OpenDocument spreadsheet files."""
    
    name = "spreadsheet"
    supported_extensions = [".csv", ".xlsx", ".xls", ".ods"]
    
    def can_render(self, file_path: str) -> bool:
        """Check if this renderer can handle the given file."""
        ext = Path(file_path).suffix.lower()
        return ext in self.supported_extensions
    
    def get_supported_extensions(self) -> list[str]:
        """Return list of file extensions this renderer supports."""
        return self.supported_extensions
    
    def render(self, file_path: str) -> RenderResult:
        """Render a spreadsheet file.
        
        Args:
            file_path: Path to the spreadsheet file
            
        Returns:
            RenderResult with grid data and metadata
        """
        path = Path(file_path)
        
        if not path.exists():
            return RenderResult(
                success=False,
                content=None,
                mime_type="text/csv",
                viewer_type="spreadsheet",
                error=f"File not found: {file_path}",
            )
        
        metadata = get_file_metadata(file_path)
        ext = path.suffix.lower()
        
        result = RenderResult(
            success=True,
            content={
                "sheets": {},
                "active_sheet": "Sheet1",
            },
            mime_type="application/json",
            viewer_type="spreadsheet",
            metadata=metadata,
        )
        
        # Handle CSV
        if ext == ".csv":
            try:
                import csv
                rows: list[dict[str, str]] = []
                with open(path, "r", encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        rows.append(row)
                
                result.content["sheets"]["Sheet1"] = {
                    "data": rows,
                    "headers": list(rows[0].keys()) if rows else [],
                    "total_rows": len(rows),
                }
            except Exception as exc:
                result.content["error"] = str(exc)
        
        # Handle Excel/OpenDocument
        elif ext in (".xlsx", ".xls", ".ods"):
            try:
                from openpyxl import load_workbook
                
                wb = load_workbook(path, read_only=True, data_only=True)
                sheet_names = wb.sheetnames
                
                sheets: dict[str, dict] = {}
                for sheet_name in sheet_names:
                    ws = wb[sheet_name]
                    headers = []
                    rows = []
                    
                    for i, row in enumerate(ws.iter_rows(values_only=True)):
                        if i == 0:
                            headers = list(row)
                        else:
                            row_data = {}
                            for j, cell in enumerate(row):
                                if j < len(headers):
                                    row_data[headers[j]] = str(cell) if cell is not None else ""
                            if row_data:
                                rows.append(row_data)
                    
                    sheets[sheet_name] = {
                        "data": rows,
                        "headers": headers,
                        "total_rows": len(rows),
                    }
                
                result.content["sheets"] = sheets
                result.content["active_sheet"] = sheet_names[0] if sheet_names else "Sheet1"
            except ImportError:
                result.content["error"] = "openpyxl not installed"
            except Exception as exc:
                result.content["error"] = str(exc)
        
        return result


# Register the renderer
def _register() -> None:
    """Register this renderer."""
    from .registry import RendererRegistry
    RendererRegistry.register(SpreadsheetRenderer())


_register()