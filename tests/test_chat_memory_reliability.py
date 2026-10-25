"""Real SQLite tests against disposable databases, with no inference calls."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from modules.llm_chat_memory import LLMChatMemory
from modules.memory_context import select_recent_messages


def test_completed_exchange_survives_restart(tmp_path):
    path = str(tmp_path / "chat.sqlite")
    first = LLMChatMemory(path)
    assert first.add_exchange("Remember the project uses SQLite", "Understood")
    second = LLMChatMemory(path)
    assert second.load_messages() == [
        {"role": "user", "content": "Remember the project uses SQLite"},
        {"role": "assistant", "content": "Understood"},
    ]
    assert first.status()["session_id"] != second.status()["session_id"]


def test_exchange_rolls_back_if_assistant_insert_fails(tmp_path):
    memory = LLMChatMemory(str(tmp_path / "chat.sqlite"))
    with memory._connect() as conn:
        conn.execute("""CREATE TRIGGER reject_assistant BEFORE INSERT ON chat_history
                        WHEN NEW.role = 'assistant'
                        BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
    assert memory.add_exchange("Do not leave this orphaned", "Rejected") is False
    assert memory.message_count() == 0


def test_concurrent_exchanges_do_not_interleave(tmp_path):
    memory = LLMChatMemory(str(tmp_path / "chat.sqlite"))
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(pool.map(lambda i: memory.add_exchange(f"question {i}", f"answer {i}"), range(12)))
    messages = memory.load_messages(limit=24)
    assert len(messages) == 24
    for index in range(0, 24, 2):
        assert messages[index]["role"] == "user"
        assert messages[index + 1]["role"] == "assistant"
        assert messages[index]["content"].split()[-1] == messages[index + 1]["content"].split()[-1]


def test_context_budget_keeps_latest_complete_exchange_without_deleting_history(tmp_path):
    memory = LLMChatMemory(str(tmp_path / "chat.sqlite"))
    memory.add_exchange("old question", "old answer")
    memory.add_exchange("new question", "new answer")
    assert memory.load_messages(max_chars=25) == [
        {"role": "user", "content": "new question"},
        {"role": "assistant", "content": "new answer"},
    ]
    assert memory.message_count() == 4
    assert len(memory.load_messages(max_chars=None)) == 4


@pytest.mark.parametrize("limit", [0, -1])
def test_nonpositive_limit_cannot_return_entire_history(tmp_path, limit):
    memory = LLMChatMemory(str(tmp_path / "chat.sqlite"))
    memory.add_exchange("question", "answer")
    assert memory.load_messages(limit=limit) == []
    assert memory.message_count() == 2


def test_invalid_trim_does_not_delete_messages(tmp_path):
    memory = LLMChatMemory(str(tmp_path / "chat.sqlite"))
    memory.add_exchange("question", "answer")
    with pytest.raises(ValueError):
        memory.trim(-1)
    assert memory.message_count() == 2


def test_connections_are_closed_after_use(tmp_path):
    memory = LLMChatMemory(str(tmp_path / "chat.sqlite"))
    with memory._connect() as conn:
        assert conn.execute("SELECT 1").fetchone() == (1,)
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_pause_resume_preserves_history_and_changes_session(tmp_path):
    memory = LLMChatMemory(str(tmp_path / "chat.sqlite"))
    memory.add_exchange("question", "answer")
    previous = memory.status()["session_id"]
    memory.pause()
    memory.resume()
    assert not memory.is_paused
    assert memory.status()["session_id"] != previous
    assert len(memory.load_messages()) == 2


def test_too_small_budget_does_not_substitute_stale_context():
    messages = [{"role": "user", "content": "old"}, {"role": "assistant", "content": "newest long answer"}]
    assert select_recent_messages(messages, max_messages=10, max_chars=5) == []


def test_cutoff_does_not_leave_assistant_reply_without_question():
    messages = [
        {"role": "user", "content": "previous question"},
        {"role": "assistant", "content": "previous answer"},
        {"role": "user", "content": "new question"},
    ]
    assert select_recent_messages(messages, max_messages=2, max_chars=None) == messages[-1:]
