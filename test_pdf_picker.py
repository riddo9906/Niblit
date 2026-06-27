import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

module_path = Path(__file__).resolve().parent / "niblit_core.py"
module_spec = importlib.util.spec_from_file_location("niblit_core_under_test", module_path)
assert module_spec is not None and module_spec.loader is not None
niblit_core = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(niblit_core)


class _CompletedProcess:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_windows_pdf_picker_parses_powershell_output(monkeypatch):
    def fake_run(*args, **kwargs):
        return _CompletedProcess(stdout=r"C:\Users\me\Documents\sample.pdf\n")

    monkeypatch.setattr(niblit_core.subprocess, "run", fake_run)
    monkeypatch.setattr(niblit_core.shutil, "which", lambda name: "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe")

    ok, selected = niblit_core.NiblitCore._select_pdf_via_native_windows_dialog()

    assert ok is True
    assert selected == r"C:\Users\me\Documents\sample.pdf"


def test_windows_pdf_picker_reports_powershell_errors(monkeypatch):
    def fake_run(*args, **kwargs):
        return _CompletedProcess(stderr="dialog blocked", returncode=1)

    monkeypatch.setattr(niblit_core.subprocess, "run", fake_run)
    monkeypatch.setattr(niblit_core.shutil, "which", lambda name: "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe")

    ok, selected = niblit_core.NiblitCore._select_pdf_via_native_windows_dialog()

    assert ok is False
    assert "dialog blocked" in selected
