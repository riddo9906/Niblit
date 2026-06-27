import importlib
import sys

import module_loader


def test_load_modules_supports_relative_imports_and_repo_root_independence(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    modules_dir = repo_root / "modules"
    modules_dir.mkdir(parents=True)
    (modules_dir / "__init__.py").write_text("", encoding="utf-8")
    (modules_dir / "helper.py").write_text("VALUE = 'ok'\n", encoding="utf-8")
    (modules_dir / "demo_optional.py").write_text(
        "from .helper import VALUE\n\n\ndef get_value():\n    return VALUE\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module_loader, "get_repo_root", lambda: repo_root)

    for name in ["modules", "modules.helper", "modules.demo_optional"]:
        sys.modules.pop(name, None)

    report = module_loader.load_modules()

    assert "demo_optional.py" in report["loaded"]
    assert report["failed"] == []

    imported_module = importlib.import_module("modules.demo_optional")
    assert imported_module.get_value() == "ok"
