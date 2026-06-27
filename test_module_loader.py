import importlib
import sys
from pathlib import Path

import module_loader


def test_load_modules_uses_loader_location_and_repo_root(monkeypatch, tmp_path):
    project_dir = tmp_path / "sample_project"
    modules_dir = project_dir / "modules"
    modules_dir.mkdir(parents=True)
    (project_dir / "helper_module.py").write_text(
        "VALUE = 'loaded-from-root'\n",
        encoding="utf-8",
    )
    (modules_dir / "sample_module.py").write_text(
        "from helper_module import VALUE\nRESULT = VALUE\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module_loader, "__file__", str(project_dir / "module_loader.py"))
    for name in ["sample_module", "helper_module"]:
        sys.modules.pop(name, None)

    module_loader.load_modules()

    sample_module = sys.modules["sample_module"]
    assert sample_module.RESULT == "loaded-from-root"
    assert "helper_module" in sys.modules
