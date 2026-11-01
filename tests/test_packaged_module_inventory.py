import sys
from types import SimpleNamespace

import module_loader


def test_frozen_inventory_does_not_require_source_directory(monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setitem(sys.modules, 'modules.inventory_test', SimpleNamespace())
    monkeypatch.setattr(module_loader.pkgutil, 'iter_modules', lambda paths: [SimpleNamespace(name='inventory_test'), SimpleNamespace(name='not_loaded')])
    monkeypatch.setattr(module_loader, 'get_repo_root', lambda: (_ for _ in ()).throw(AssertionError('physical path scan')))
    result = module_loader.load_modules()
    assert 'inventory_test' in result['loaded']
    assert 'not_loaded' not in result['loaded']
    assert 'not_loaded' in result['discovered']
    assert result['mode'] == 'packaged'
