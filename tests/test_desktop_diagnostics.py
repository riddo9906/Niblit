import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import server
from modules import desktop_diagnostics as diagnostics


def test_windows_tauri_origin_can_connect_to_core():
    response = TestClient(server.app).options('/api/desktop/overview', headers={
        'Origin': 'http://tauri.localhost', 'Access-Control-Request-Method': 'GET',
    })
    assert response.status_code == 200
    assert response.headers['access-control-allow-origin'] == 'http://tauri.localhost'


def test_unrelated_browser_origin_is_not_allowed():
    response = TestClient(server.app).options('/api/desktop/overview', headers={
        'Origin': 'https://unrelated.example', 'Access-Control-Request-Method': 'GET',
    })
    assert response.status_code == 400


def test_memory_view_reports_real_counts_and_queries():
    database = SimpleNamespace(data={'facts': [{'key': 'project', 'value': 'SQLite'}]}, lock=threading.RLock(), recall=Mock(return_value=[{'value': 'SQLite'}]))
    core = SimpleNamespace(db=database)
    import modules.llm_chat_memory as chat
    original = chat._instance
    try:
        chat._instance = SimpleNamespace(status=lambda: {'message_count': 2})
        result = diagnostics.desktop_snapshot(core, 'memory', query='SQLite', limit=5)
    finally:
        chat._instance = original
    assert result['memory']['counts']['facts'] == 1
    assert result['records'] == [{'value': 'SQLite'}]
    database.recall.assert_called_once_with(query='SQLite', limit=5)


def test_unknown_desktop_section_does_not_create_an_arbitrary_proxy():
    with pytest.raises(ValueError):
        diagnostics.desktop_snapshot(object(), 'https://example.com/private')


def test_architecture_does_not_claim_wiring_when_bridges_are_missing(monkeypatch):
    from modules import multi_repo_orchestrator
    orchestrator = Mock()
    monkeypatch.setattr(multi_repo_orchestrator, 'get_multi_repo_orchestrator', lambda: orchestrator)
    monkeypatch.setattr(diagnostics, 'service_snapshot', lambda *_args: {'available': False})
    result = diagnostics.desktop_snapshot(SimpleNamespace(db=object(), runtime_manager=None), 'architecture')
    assert result['all_checked_connections_ready'] is False
    assert result['wiring_checks']['runtime_manager_present'] is False
    assert result['wiring_checks']['module_event_bridge'] is False
    assert result['wiring_checks']['cloud_reachable'] is False


def test_core_database_normalizes_a_path_object(monkeypatch, tmp_path):
    import main
    import sys
    module = sys.modules[main.NiblitCore.__module__]
    constructor = Mock(return_value=object())
    monkeypatch.setattr(module, 'KnowledgeDB', constructor)
    core = SimpleNamespace(config=SimpleNamespace(memory_path=tmp_path/'memory.json'), startup_report=Mock())
    main.NiblitCore._init_database(core)
    constructor.assert_called_once_with(str(tmp_path/'memory.json'))
    core.startup_report.add.assert_called_once_with('db', 'ready')
