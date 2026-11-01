import importlib.util
from pathlib import Path
import sqlite3
from unittest.mock import Mock

import pytest
from modules.server_manager import ServerManager


def test_private_compose_inference_url_and_no_cloud_fallback(monkeypatch):
    monkeypatch.setenv('NIBLIT_PORTAL_OLLAMA_URL','http://ollama:11434')
    client=Mock()
    client.post.return_value.json.return_value={'message':{'content':'local reply'}}
    factory=Mock()
    factory.return_value.__enter__=Mock(return_value=client)
    factory.return_value.__exit__=Mock(return_value=False)
    monkeypatch.setattr('modules.server_manager.httpx.Client',factory)
    assert ServerManager.local_reply([], 'hello')=='local reply'
    assert client.post.call_args.args[0]=='http://ollama:11434/api/chat'
    monkeypatch.setenv('NIBLIT_PORTAL_OLLAMA_URL','https://api.openai.com/v1')
    with pytest.raises(ValueError): ServerManager.local_reply([], 'hello')
    assert client.post.call_count==1


def test_backup_is_consistent_and_refuses_overwrite(tmp_path):
    script=Path(__file__).resolve().parents[1]/'scripts/backup-client-portal.py'
    spec=importlib.util.spec_from_file_location('portal_backup',script)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    source=tmp_path/'source.sqlite3';target=tmp_path/'backups'/'copy.sqlite3'
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE proof(value TEXT)')
        db.execute("INSERT INTO proof VALUES('persistent')")
    module.backup(source.resolve(),target)
    with sqlite3.connect(target) as db:
        assert db.execute('SELECT value FROM proof').fetchone()[0]=='persistent'
    with pytest.raises(ValueError,match='overwrite'): module.backup(source,target)
