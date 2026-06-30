import importlib
import sys
from pathlib import Path


def test_lifecycle_engine_imports_with_external_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sys.modules.pop("lifecycle_engine", None)

    module = importlib.import_module("lifecycle_engine")

    assert module.LifecycleEngine is not None
    assert module.NiblitTasks is not None
