from types import SimpleNamespace
from unittest.mock import Mock
import logging

from niblit_memory import KnowledgeDB


def store(tmp_path):
    return SimpleNamespace(path=str(tmp_path/'memory.json'), backup_path=str(tmp_path/'backup.json'),
        snapshot_path=str(tmp_path/'snapshot.json'), _save=Mock(), _repair_json=lambda raw:(None, []),
        _record_quarantine=Mock(), _extract_error_snippet=lambda raw,pos:'invalid test data')


def test_first_run_is_not_reported_as_recovery(tmp_path, caplog):
    memory = store(tmp_path)
    with caplog.at_level(logging.INFO):
        KnowledgeDB._load(memory)
    assert 'partial recovery' not in caplog.text
    assert 'initialized a new store' in caplog.text
    memory._save.assert_called_once_with(blocking=False)


def test_unrecoverable_existing_store_keeps_warning(tmp_path, caplog):
    memory = store(tmp_path)
    (tmp_path/'memory.json').write_text('not json', encoding='utf-8')
    with caplog.at_level(logging.WARNING):
        KnowledgeDB._load(memory)
    assert 'partial recovery' in caplog.text
