"""
test_nextgen_architecture.py — Unit tests for the next-gen architecture modules.

Run with::

    pytest test_nextgen_architecture.py -v
"""

import os
import time
from unittest.mock import MagicMock, patch

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Config additions
# ─────────────────────────────────────────────────────────────────────────────

class TestConfigAdditions:
    def test_new_config_fields_present(self):
        from config import Config
        assert hasattr(Config, "OPENAI_API_KEY")
        assert hasattr(Config, "ANTHROPIC_API_KEY")
        assert hasattr(Config, "STACKOVERFLOW_API_KEY")
        assert hasattr(Config, "PYPI_API_URL")
        assert hasattr(Config, "QDRANT_URL")
        assert hasattr(Config, "QDRANT_API_KEY")
        assert hasattr(Config, "QDRANT_COLLECTION")
        assert hasattr(Config, "EMBEDDING_MODEL")
        assert hasattr(Config, "SANDBOX_ENABLED")
        assert hasattr(Config, "SANDBOX_IMAGE")
        assert hasattr(Config, "SANDBOX_TIMEOUT")
        assert hasattr(Config, "SANDBOX_MEMORY_MB")

    def test_pypi_default(self):
        from config import Config
        assert Config.PYPI_API_URL == "https://pypi.org/pypi"

    def test_qdrant_collection_default(self):
        from config import Config
        assert Config.QDRANT_COLLECTION == "niblit_knowledge"


# ─────────────────────────────────────────────────────────────────────────────
# OpenAI adapter
# ─────────────────────────────────────────────────────────────────────────────

class TestOpenAIAdapter:
    def test_not_available_without_key(self):
        from modules.openai_adapter import OpenAIAdapter
        a = OpenAIAdapter(api_key="")
        assert not a.is_available()

    def test_available_with_key(self):
        from modules.openai_adapter import OpenAIAdapter
        a = OpenAIAdapter(api_key="sk-fake-key")
        assert a.is_available()

    def test_query_returns_none_without_key(self):
        from modules.openai_adapter import OpenAIAdapter
        a = OpenAIAdapter(api_key="")
        assert a.query([{"role": "user", "content": "hello"}]) is None

    @patch("modules.openai_adapter.requests.post")
    def test_query_success(self, mock_post):
        from modules.openai_adapter import OpenAIAdapter
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "hello world"}}]
        }
        mock_post.return_value = mock_resp

        a = OpenAIAdapter(api_key="sk-fake")
        result = a.query([{"role": "user", "content": "hi"}])
        assert result == "hello world"

    @patch("modules.openai_adapter.requests.post")
    def test_query_network_error_returns_none(self, mock_post):
        from modules.openai_adapter import OpenAIAdapter
        mock_post.side_effect = Exception("network error")
        a = OpenAIAdapter(api_key="sk-fake")
        result = a.query([{"role": "user", "content": "hi"}])
        assert result is None

    @patch("modules.openai_adapter.requests.post")
    def test_generate_code_returns_string(self, mock_post):
        from modules.openai_adapter import OpenAIAdapter
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "def foo(): pass"}}]
        }
        mock_post.return_value = mock_resp

        a = OpenAIAdapter(api_key="sk-fake")
        code = a.generate_code("python", "make a function named foo")
        assert "foo" in code

    def test_generate_code_empty_without_key(self):
        from modules.openai_adapter import OpenAIAdapter
        a = OpenAIAdapter(api_key="")
        code = a.generate_code("python", "something")
        assert code == ""


# ─────────────────────────────────────────────────────────────────────────────
# Anthropic adapter
# ─────────────────────────────────────────────────────────────────────────────

class TestAnthropicAdapter:
    def test_not_available_without_key(self):
        from modules.anthropic_adapter import AnthropicAdapter
        a = AnthropicAdapter(api_key="")
        assert not a.is_available()

    def test_available_with_key(self):
        from modules.anthropic_adapter import AnthropicAdapter
        a = AnthropicAdapter(api_key="sk-ant-fake")
        assert a.is_available()

    def test_query_returns_none_without_key(self):
        from modules.anthropic_adapter import AnthropicAdapter
        a = AnthropicAdapter(api_key="")
        assert a.query([{"role": "user", "content": "hello"}]) is None

    @patch("modules.anthropic_adapter.requests.post")
    def test_query_success(self, mock_post):
        from modules.anthropic_adapter import AnthropicAdapter
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "content": [{"type": "text", "text": "I am Claude"}]
        }
        mock_post.return_value = mock_resp

        a = AnthropicAdapter(api_key="sk-ant-fake")
        result = a.query([{"role": "user", "content": "who are you?"}])
        assert result == "I am Claude"

    @patch("modules.anthropic_adapter.requests.post")
    def test_query_network_error_returns_none(self, mock_post):
        from modules.anthropic_adapter import AnthropicAdapter
        mock_post.side_effect = Exception("timeout")
        a = AnthropicAdapter(api_key="sk-ant-fake")
        assert a.query([{"role": "user", "content": "hi"}]) is None

    @patch("modules.anthropic_adapter.requests.post")
    def test_generate_code(self, mock_post):
        from modules.anthropic_adapter import AnthropicAdapter
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "content": [{"type": "text", "text": "def bar(): return 42"}]
        }
        mock_post.return_value = mock_resp

        a = AnthropicAdapter(api_key="sk-ant-fake")
        code = a.generate_code("python", "function bar")
        assert "bar" in code


# ─────────────────────────────────────────────────────────────────────────────
# Stack Overflow search
# ─────────────────────────────────────────────────────────────────────────────

class TestStackOverflowSearch:
    def test_always_available(self):
        from modules.stackoverflow_search import StackOverflowSearch
        s = StackOverflowSearch()
        assert s.is_available()

    @patch("modules.stackoverflow_search.requests.get")
    def test_search_returns_results(self, mock_get):
        from modules.stackoverflow_search import StackOverflowSearch
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "items": [
                {
                    "title": "How to use decorators",
                    "body": "<p>Decorators wrap functions.</p>",
                    "link": "https://stackoverflow.com/q/1",
                    "score": 10,
                    "tags": ["python"],
                    "is_answered": True,
                    "answer_count": 5,
                }
            ]
        }
        mock_get.return_value = mock_resp

        s = StackOverflowSearch()
        results = s.search("python decorators", max_results=2)
        assert len(results) == 1
        assert results[0]["source"] == "stackoverflow"
        assert "decorator" in results[0]["title"].lower()

    @patch("modules.stackoverflow_search.requests.get")
    def test_search_network_error_returns_empty(self, mock_get):
        from modules.stackoverflow_search import StackOverflowSearch
        mock_get.side_effect = Exception("timeout")
        s = StackOverflowSearch()
        assert s.search("anything") == []

    @patch("modules.stackoverflow_search.requests.get")
    def test_search_for_error(self, mock_get):
        from modules.stackoverflow_search import StackOverflowSearch
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"items": []}
        mock_get.return_value = mock_resp
        s = StackOverflowSearch()
        results = s.search_for_error("AttributeError", "python")
        assert isinstance(results, list)

    @patch("modules.stackoverflow_search.requests.get")
    def test_research_for_code_generation(self, mock_get):
        from modules.stackoverflow_search import StackOverflowSearch
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"items": []}
        mock_get.return_value = mock_resp
        s = StackOverflowSearch()
        results = s.research_for_code_generation("python", "async io")
        assert isinstance(results, list)


# ─────────────────────────────────────────────────────────────────────────────
# PyPI search
# ─────────────────────────────────────────────────────────────────────────────

class TestPyPISearch:
    def test_always_available(self):
        from modules.pypi_search import PyPISearch
        p = PyPISearch()
        assert p.is_available()

    @patch("modules.pypi_search.requests.get")
    def test_get_package_info(self, mock_get):
        from modules.pypi_search import PyPISearch
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "info": {
                "name": "requests",
                "version": "2.31.0",
                "summary": "Python HTTP for Humans.",
                "requires_dist": ["urllib3"],
                "description": "Requests is ...",
            }
        }
        mock_get.return_value = mock_resp

        p = PyPISearch()
        info = p.get_package_info("requests")
        assert info is not None
        assert info["name"] == "requests"
        assert info["version"] == "2.31.0"
        assert "urllib3" in info["requires_dist"]

    @patch("modules.pypi_search.requests.get")
    def test_get_package_info_network_error(self, mock_get):
        from modules.pypi_search import PyPISearch
        mock_get.side_effect = Exception("timeout")
        p = PyPISearch()
        assert p.get_package_info("nonexistent-pkg-xyz") is None

    def test_infer_package_names_nlp(self):
        from modules.pypi_search import PyPISearch
        p = PyPISearch()
        names = p._infer_package_names("nlp transformers")
        assert "transformers" in names

    def test_research_for_non_python_returns_empty(self):
        from modules.pypi_search import PyPISearch
        p = PyPISearch()
        results = p.research_for_code_generation("javascript", "async patterns")
        assert results == []


# ─────────────────────────────────────────────────────────────────────────────
# Vector store
# ─────────────────────────────────────────────────────────────────────────────

class TestVectorStore:
    def test_memory_backend_default(self):
        """Without Qdrant URL and FAISS, uses in-memory backend."""
        from modules.vector_store import VectorStore
        vs = VectorStore(qdrant_url="")
        assert vs.backend in ("memory", "faiss")  # FAISS may be installed

    def test_add_and_count(self):
        from modules.vector_store import VectorStore
        vs = VectorStore(qdrant_url="")
        vs.add("doc1", "Python decorators wrap functions cleanly")
        vs.add("doc2", "Docker containers isolate processes")
        assert vs.count() == 2

    def test_search_returns_list(self):
        from modules.vector_store import VectorStore
        vs = VectorStore(qdrant_url="")
        vs.add("doc1", "neural network deep learning")
        vs.add("doc2", "python decorators")
        results = vs.search("deep learning", top_k=2)
        assert isinstance(results, list)

    def test_search_result_schema(self):
        from modules.vector_store import VectorStore
        vs = VectorStore(qdrant_url="")
        vs.add("key1", "test document content")
        results = vs.search("test document", top_k=1)
        if results:
            r = results[0]
            assert "id" in r
            assert "text" in r
            assert "score" in r

    def test_duplicate_add_replaces(self):
        from modules.vector_store import VectorStore
        vs = VectorStore(qdrant_url="")
        vs.add("dup", "original text")
        vs.add("dup", "updated text")
        assert vs.count() == 1  # deduplication


# ─────────────────────────────────────────────────────────────────────────────
# Core: EventBus
# ─────────────────────────────────────────────────────────────────────────────

class TestEventBus:
    def test_subscribe_and_publish(self):
        from core.event_bus import EventBus, Event, EventType
        bus = EventBus()
        received = []
        bus.subscribe(EventType.RESEARCH_REQUEST, received.append)
        bus.publish(Event(EventType.RESEARCH_REQUEST, payload={"topic": "nlp"}))
        assert len(received) == 1
        assert received[0].payload["topic"] == "nlp"

    def test_wildcard_subscription(self):
        from core.event_bus import EventBus, Event, EventType
        bus = EventBus()
        received = []
        bus.subscribe_all(received.append)
        bus.publish(Event(EventType.CODE_GENERATION_REQUEST))
        bus.publish(Event(EventType.RESEARCH_COMPLETED))
        assert len(received) == 2

    def test_no_handlers_no_error(self):
        from core.event_bus import EventBus, Event, EventType
        bus = EventBus()
        called = bus.publish(Event(EventType.TASK_CREATED))
        assert called == 0

    def test_handler_exception_does_not_break(self):
        from core.event_bus import EventBus, Event, EventType
        bus = EventBus()
        def bad_handler(e):
            raise ValueError("oops")
        bus.subscribe(EventType.ERROR_OCCURRED, bad_handler)
        # Should not raise
        bus.publish(Event(EventType.ERROR_OCCURRED))

    def test_unsubscribe(self):
        from core.event_bus import EventBus, Event, EventType
        bus = EventBus()
        received = []
        bus.subscribe(EventType.TASK_COMPLETED, received.append)
        bus.unsubscribe(EventType.TASK_COMPLETED, received.append)
        bus.publish(Event(EventType.TASK_COMPLETED))
        assert len(received) == 0

    def test_history(self):
        from core.event_bus import EventBus, Event, EventType
        bus = EventBus()
        bus.publish(Event(EventType.KNOWLEDGE_UPDATED))
        bus.publish(Event(EventType.REFLECTION_COMPLETED))
        history = bus.get_history()
        # SYSTEM_STARTED + the two above
        assert len(history) >= 2


# ─────────────────────────────────────────────────────────────────────────────
# Core: TaskQueue
# ─────────────────────────────────────────────────────────────────────────────

class TestTaskQueue:
    def test_enqueue_and_dequeue(self):
        from core.task_queue import TaskQueue, Task, Priority
        q = TaskQueue()
        t = Task("research", payload={"topic": "ml"})
        q.enqueue(t)
        out = q.dequeue()
        assert out is not None
        assert out.task_type == "research"

    def test_priority_ordering(self):
        from core.task_queue import TaskQueue, Task, Priority
        q = TaskQueue()
        low = Task("low_task", priority=Priority.LOW)
        high = Task("high_task", priority=Priority.HIGH)
        # Enqueue in low-priority-first order
        q.enqueue(low)
        q.enqueue(high)
        out = q.dequeue()
        assert out.task_type == "high_task"

    def test_empty_dequeue_returns_none(self):
        from core.task_queue import TaskQueue
        q = TaskQueue()
        assert q.dequeue() is None

    def test_complete_task(self):
        from core.task_queue import TaskQueue, Task, TaskStatus
        q = TaskQueue()
        t = Task("test")
        q.enqueue(t)
        running = q.dequeue()
        assert running is not None
        q.complete(running.task_id, result="done")
        stats = q.get_stats()
        assert stats["completed"] == 1
        assert stats["running"] == 0

    def test_fail_task(self):
        from core.task_queue import TaskQueue, Task
        q = TaskQueue()
        t = Task("test")
        q.enqueue(t)
        running = q.dequeue()
        assert running is not None
        q.fail(running.task_id, error="it broke")
        assert q.completed_count() == 1


# ─────────────────────────────────────────────────────────────────────────────
# Core: Orchestrator
# ─────────────────────────────────────────────────────────────────────────────

class TestOrchestrator:
    def _make_orch(self):
        from core.event_bus import EventBus
        from core.task_queue import TaskQueue
        from core.orchestrator import Orchestrator
        bus = EventBus()
        q = TaskQueue()
        return Orchestrator(bus, q), bus, q

    def test_dispatch_calls_handler(self):
        from core.task_queue import Task
        orch, bus, q = self._make_orch()
        results = []
        orch.register_agent("research", lambda task, b: results.append(task.task_type) or "ok")
        t = Task("research", payload={"topic": "nlp"})
        q.enqueue(t)
        out = orch.dispatch_next()
        assert out == "ok"
        assert results == ["research"]

    def test_dispatch_unknown_type_returns_none(self):
        from core.task_queue import Task
        orch, bus, q = self._make_orch()
        t = Task("unknown_type")
        q.enqueue(t)
        result = orch.dispatch_next()
        assert result is None

    def test_dispatch_empty_queue_returns_none(self):
        orch, bus, q = self._make_orch()
        assert orch.dispatch_next() is None

    def test_get_stats(self):
        orch, bus, q = self._make_orch()
        orch.register_agent("coding", lambda t, b: "code")
        stats = orch.get_stats()
        assert stats["registered_agents"] == 1
        assert "coding" in stats["agent_types"]


# ─────────────────────────────────────────────────────────────────────────────
# Core: RuntimeManager
# ─────────────────────────────────────────────────────────────────────────────

class TestRuntimeManager:
    def test_submit_and_dispatch(self):
        from core.runtime_manager import RuntimeManager
        rm = RuntimeManager()
        received = []
        rm.register_agent("research", lambda t, b: received.append(t) or "done")
        rm.submit_task("research", payload={"topic": "ml"}, priority="high")
        rm.dispatch_pending()
        assert len(received) == 1

    def test_submit_with_unknown_priority_uses_normal(self):
        from core.runtime_manager import RuntimeManager
        from core.task_queue import Priority
        rm = RuntimeManager()
        task = rm.submit_task("test", priority="nonexistent")
        assert task.priority == Priority.NORMAL

    def test_get_stats(self):
        from core.runtime_manager import RuntimeManager
        rm = RuntimeManager()
        stats = rm.get_stats()
        assert "orchestrator" in stats
        assert "event_history" in stats


# ─────────────────────────────────────────────────────────────────────────────
# Agents: BaseAgent
# ─────────────────────────────────────────────────────────────────────────────

class TestBaseAgent:
    def test_cannot_instantiate_directly(self):
        from agents.base_agent import BaseAgent
        from core.event_bus import EventBus
        from core.task_queue import Task

        class BrokenAgent(BaseAgent):
            pass

        agent = BrokenAgent("broken")
        bus = EventBus()
        task = Task("anything")
        with pytest.raises(NotImplementedError):
            agent.handle(task, bus)

    def test_metrics_tracked(self):
        from agents.base_agent import BaseAgent, AgentState
        from core.event_bus import EventBus
        from core.task_queue import Task

        class OKAgent(BaseAgent):
            def _execute(self, task, bus):
                return "ok"

        agent = OKAgent("ok_agent")
        bus = EventBus()
        task = Task("test")
        agent.handle(task, bus)
        assert agent.metrics.tasks_handled == 1
        assert agent.state == AgentState.IDLE

    def test_get_status(self):
        from agents.base_agent import BaseAgent

        class OKAgent(BaseAgent):
            def _execute(self, task, bus):
                return "ok"

        agent = OKAgent("status_agent")
        status = agent.get_status()
        assert status["name"] == "status_agent"
        assert "metrics" in status


# ─────────────────────────────────────────────────────────────────────────────
# Agents: PlannerAgent
# ─────────────────────────────────────────────────────────────────────────────

class TestPlannerAgent:
    def test_plan_returns_subtasks(self):
        from agents.planner_agent import PlannerAgent
        from core.event_bus import EventBus
        from core.task_queue import Task

        agent = PlannerAgent()
        bus = EventBus()
        task = Task("plan", payload={"goal": "improve code quality"})
        result = agent.handle(task, bus)
        assert "subtasks" in result
        assert len(result["subtasks"]) > 0

    def test_empty_goal_returns_error(self):
        from agents.planner_agent import PlannerAgent
        from core.event_bus import EventBus
        from core.task_queue import Task

        agent = PlannerAgent()
        bus = EventBus()
        task = Task("plan", payload={"goal": ""})
        result = agent.handle(task, bus)
        assert "error" in result

    def test_subtasks_enqueued_in_task_queue(self):
        from agents.planner_agent import PlannerAgent
        from core.event_bus import EventBus
        from core.task_queue import Task, TaskQueue

        q = TaskQueue()
        agent = PlannerAgent(task_queue=q)
        bus = EventBus()
        task = Task("plan", payload={"goal": "implement a REST API"})
        agent.handle(task, bus)
        assert q.pending_count() > 0


# ─────────────────────────────────────────────────────────────────────────────
# Agents: ArchitectureAgent
# ─────────────────────────────────────────────────────────────────────────────

class TestArchitectureAgent:
    def test_analyse_current_repo(self):
        from agents.architecture_agent import ArchitectureAgent
        from core.event_bus import EventBus
        from core.task_queue import Task
        import os

        repo_root = os.path.join(os.path.dirname(__file__))
        agent = ArchitectureAgent(source_root=repo_root)
        bus = EventBus()
        task = Task("architecture_analysis", payload={"target": repo_root, "language": "python"})
        result = agent.handle(task, bus)
        assert "files_scanned" in result
        assert result["files_scanned"] > 0

    def test_empty_directory(self, tmp_path):
        from agents.architecture_agent import ArchitectureAgent
        from core.event_bus import EventBus
        from core.task_queue import Task

        agent = ArchitectureAgent(source_root=str(tmp_path))
        bus = EventBus()
        task = Task("architecture_analysis", payload={"target": str(tmp_path), "language": "python"})
        result = agent.handle(task, bus)
        assert result["files_scanned"] == 0
        assert result["issues_found"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# ALE: new params wired in
# ─────────────────────────────────────────────────────────────────────────────

class TestALENewParams:
    def test_ale_accepts_new_params(self):
        from modules.autonomous_learning_engine import AutonomousLearningEngine
        ale = AutonomousLearningEngine(
            core=None,
            stackoverflow_search=MagicMock(),
            pypi_search=MagicMock(),
        )
        assert ale.stackoverflow_search is not None
        assert ale.pypi_search is not None

    def test_initialize_factory_accepts_new_params(self):
        from modules.autonomous_learning_engine import initialize_autonomous_engine
        engine = initialize_autonomous_engine(
            core=None,
            stackoverflow_search=MagicMock(),
            pypi_search=MagicMock(),
        )
        assert engine is not None
        assert engine.stackoverflow_search is not None

    def test_get_stackoverflow_search_lazy(self):
        from modules.autonomous_learning_engine import AutonomousLearningEngine
        core = MagicMock()
        core.stackoverflow_search = MagicMock()
        ale = AutonomousLearningEngine(core=core)
        resolved = ale._get_stackoverflow_search()
        assert resolved is core.stackoverflow_search

    def test_get_pypi_search_lazy(self):
        from modules.autonomous_learning_engine import AutonomousLearningEngine
        core = MagicMock()
        core.pypi_search = MagicMock()
        ale = AutonomousLearningEngine(core=core)
        resolved = ale._get_pypi_search()
        assert resolved is core.pypi_search


if __name__ == "__main__":
    print('Running test_nextgen_architecture.py')
