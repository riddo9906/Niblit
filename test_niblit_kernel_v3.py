"""
test_niblit_kernel_v3.py — Test suite for Cognitive Kernel v3
"""
from __future__ import annotations

import threading
import time
import uuid

import pytest

# ── Imports from the module under test ───────────────────────────────────────
from modules.niblit_kernel_v3 import (
    KernelMessage,
    KernelCommunicationBus,
    RewardEngine,
    KernelScheduler,
    TaskNode,
    BaseAgent,
    ResearchAgent,
    CoderAgent,
    CriticAgent,
    TeacherAgent,
    ExplorerAgent,
    NiblitCognitiveKernelV3,
    KernelV3Result,
    get_niblit_kernel_v3,
    _build_task_graph,
    _AGENT_RESEARCH, _AGENT_CODER, _AGENT_CRITIC, _AGENT_TEACHER, _AGENT_EXPLORER,
    _KERNEL_ID,
)


# ═════════════════════════════════════════════════════════════════════════════
# KernelMessage
# ═════════════════════════════════════════════════════════════════════════════

class TestKernelMessage:
    def test_defaults(self):
        msg = KernelMessage()
        assert msg.id
        assert msg.sender == _KERNEL_ID
        assert msg.target == "broadcast"
        assert msg.intent == "respond"
        assert isinstance(msg.payload, dict)
        assert msg.reward == 0.0
        assert msg.result is None

    def test_custom_fields(self):
        msg = KernelMessage(
            sender="research_agent",
            target="coder_agent",
            intent="generate_code",
            payload={"topic": "web scraping"},
            priority=9,
        )
        assert msg.sender == "research_agent"
        assert msg.target == "coder_agent"
        assert msg.intent == "generate_code"
        assert msg.payload["topic"] == "web scraping"
        assert msg.priority == 9

    def test_to_dict(self):
        msg = KernelMessage(sender="test", intent="research")
        d = msg.to_dict()
        assert d["sender"] == "test"
        assert d["intent"] == "research"
        assert "id" in d
        assert "timestamp" in d

    def test_from_dict_roundtrip(self):
        msg = KernelMessage(
            sender="a", target="b", intent="debug",
            payload={"x": 1}, priority=3, trace_id="abc",
        )
        d = msg.to_dict()
        msg2 = KernelMessage.from_dict(d)
        assert msg2.sender == "a"
        assert msg2.intent == "debug"
        assert msg2.priority == 3

    def test_unique_ids(self):
        ids = {KernelMessage().id for _ in range(50)}
        assert len(ids) == 50

    def test_unique_trace_ids(self):
        tids = {KernelMessage().trace_id for _ in range(50)}
        assert len(tids) == 50


# ═════════════════════════════════════════════════════════════════════════════
# KernelCommunicationBus
# ═════════════════════════════════════════════════════════════════════════════

class TestKernelCommunicationBus:
    def _bus(self):
        return KernelCommunicationBus()

    def test_route_to_specific_agent(self):
        bus = self._bus()
        msg = KernelMessage(target=_AGENT_RESEARCH, intent="research")
        bus.route(msg)
        assert bus.inbox_size(_AGENT_RESEARCH) == 1
        assert bus.inbox_size(_AGENT_CODER) == 0

    def test_route_broadcast(self):
        bus = self._bus()
        msg = KernelMessage(target="broadcast")
        bus.route(msg)
        from modules.niblit_kernel_v3 import _ALL_AGENTS
        for agent_id in _ALL_AGENTS:
            assert bus.inbox_size(agent_id) == 1

    def test_dequeue_returns_message(self):
        bus = self._bus()
        msg = KernelMessage(target=_AGENT_CODER, intent="code")
        bus.route(msg)
        got = bus.dequeue(_AGENT_CODER)
        assert got is not None
        assert got.intent == "code"

    def test_dequeue_empty_returns_none(self):
        bus = self._bus()
        assert bus.dequeue(_AGENT_RESEARCH) is None

    def test_dequeue_fifo(self):
        bus = self._bus()
        for i in range(5):
            bus.route(KernelMessage(target=_AGENT_TEACHER, intent=f"intent_{i}"))
        intents = [bus.dequeue(_AGENT_TEACHER).intent for _ in range(5)]
        assert intents == [f"intent_{i}" for i in range(5)]

    def test_submit_response_routes_to_kernel(self):
        bus = self._bus()
        original = KernelMessage(target=_AGENT_CODER, intent="code")
        response = bus.submit_response(_AGENT_CODER, original, "result text")
        assert response.sender == _AGENT_CODER
        assert response.target == _KERNEL_ID
        assert response.result == "result text"
        assert bus.inbox_size(_KERNEL_ID) == 1

    def test_trace_snapshot(self):
        bus = self._bus()
        for _ in range(5):
            bus.route(KernelMessage(target=_AGENT_RESEARCH))
        snap = bus.trace_snapshot(last_n=3)
        assert len(snap) == 3

    def test_clear(self):
        bus = self._bus()
        bus.route(KernelMessage(target=_AGENT_RESEARCH))
        bus.clear()
        assert bus.inbox_size(_AGENT_RESEARCH) == 0
        assert bus.trace_snapshot() == []

    def test_thread_safety(self):
        bus = self._bus()
        errors = []

        def writer():
            try:
                for _ in range(20):
                    bus.route(KernelMessage(target=_AGENT_RESEARCH))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors

    def test_max_inbox_bounded(self):
        bus = KernelCommunicationBus(max_inbox=3)
        for _ in range(10):
            bus.route(KernelMessage(target=_AGENT_RESEARCH))
        # Deque is bounded — should not exceed max_inbox
        assert bus.inbox_size(_AGENT_RESEARCH) <= 3


# ═════════════════════════════════════════════════════════════════════════════
# RewardEngine
# ═════════════════════════════════════════════════════════════════════════════

class TestRewardEngine:
    def _engine(self):
        return RewardEngine(floor=0.2)

    def test_score_perfect(self):
        re = self._engine()
        reward = re.score("agent_a", accuracy=1.0, usefulness=1.0, efficiency=1.0, safety=1.0)
        assert abs(reward - 1.0) < 1e-6

    def test_score_zero(self):
        re = self._engine()
        reward = re.score("agent_a", accuracy=0.0, usefulness=0.0, efficiency=0.0, safety=0.0)
        assert reward == 0.0

    def test_score_weighted(self):
        re = self._engine()
        # accuracy=1(0.4) + usefulness=0(0.3) + efficiency=0(0.2) + safety=0(0.1) = 0.4
        reward = re.score("agent_b", accuracy=1.0, usefulness=0.0, efficiency=0.0, safety=0.0)
        assert abs(reward - 0.4) < 1e-6

    def test_score_clamped(self):
        re = self._engine()
        reward = re.score("agent_c", accuracy=2.0, usefulness=2.0, efficiency=2.0, safety=2.0)
        assert reward <= 1.0

    def test_mean_reward(self):
        re = self._engine()
        for _ in range(5):
            re.score("agent_d", accuracy=0.8, usefulness=0.8, efficiency=0.8, safety=1.0)
        mean = re.agent_mean_reward("agent_d")
        expected = 0.8 * 0.4 + 0.8 * 0.3 + 0.8 * 0.2 + 1.0 * 0.1
        assert abs(mean - expected) < 0.01

    def test_mean_reward_empty(self):
        re = self._engine()
        assert re.agent_mean_reward("unknown") == 0.0

    def test_below_floor_true(self):
        re = self._engine()
        re.score("lazy_agent", accuracy=0.0, usefulness=0.0, efficiency=0.0, safety=0.0)
        assert re.below_floor("lazy_agent")

    def test_below_floor_false(self):
        re = self._engine()
        for _ in range(3):
            re.score("good_agent", accuracy=0.9, usefulness=0.9, efficiency=0.9, safety=1.0)
        assert not re.below_floor("good_agent")

    def test_evolution_signals(self):
        re = self._engine()
        re.score("a1", accuracy=0.5, usefulness=0.5, efficiency=0.5, safety=0.5)
        re.score("a2", accuracy=1.0, usefulness=1.0, efficiency=1.0, safety=1.0)
        signals = re.evolution_signals()
        assert "a1" in signals
        assert "a2" in signals
        assert signals["a2"] > signals["a1"]

    def test_score_from_latency(self):
        re = self._engine()
        reward = re.score_from_latency("fast_agent", latency_ms=100, result_len=200, safe=True)
        assert 0.0 <= reward <= 1.0

    def test_score_from_latency_unsafe(self):
        re = self._engine()
        r_safe = re.score_from_latency("x", latency_ms=100, result_len=200, safe=True)
        r_unsafe = re.score_from_latency("y", latency_ms=100, result_len=200, safe=False)
        assert r_safe > r_unsafe

    def test_history_capped_at_200(self):
        re = self._engine()
        for _ in range(250):
            re.score("big_agent")
        with re._lock:
            assert len(re._histories["big_agent"]) <= 200


# ═════════════════════════════════════════════════════════════════════════════
# KernelScheduler
# ═════════════════════════════════════════════════════════════════════════════

class TestKernelScheduler:
    def _sched(self):
        return KernelScheduler()

    def test_empty(self):
        assert self._sched().plan([]) == []

    def test_single_node(self):
        nodes = [TaskNode(agent="a", intent="research")]
        result = self._sched().plan(nodes)
        assert len(result) == 1
        assert result[0].agent == "a"

    def test_dependency_order(self):
        nodes = [
            TaskNode(agent="coder", intent="code", depends=["researcher"]),
            TaskNode(agent="researcher", intent="research"),
        ]
        result = self._sched().plan(nodes)
        agents = [n.agent for n in result]
        assert agents.index("researcher") < agents.index("coder")

    def test_deep_chain(self):
        # a -> b -> c -> d
        nodes = [
            TaskNode(agent="a", intent="r"),
            TaskNode(agent="b", intent="r", depends=["a"]),
            TaskNode(agent="c", intent="r", depends=["b"]),
            TaskNode(agent="d", intent="r", depends=["c"]),
        ]
        result = self._sched().plan(nodes)
        agents = [n.agent for n in result]
        for i in range(3):
            assert agents.index(agents[i]) < agents.index(agents[i + 1])

    def test_independent_nodes_all_returned(self):
        nodes = [TaskNode(agent=a, intent="r") for a in ["x", "y", "z"]]
        result = self._sched().plan(nodes)
        assert len(result) == 3

    def test_unknown_dependency_skipped(self):
        nodes = [TaskNode(agent="coder", intent="code", depends=["nonexistent"])]
        result = self._sched().plan(nodes)
        assert len(result) == 1


# ═════════════════════════════════════════════════════════════════════════════
# Agents
# ═════════════════════════════════════════════════════════════════════════════

class TestBaseAgent:
    def test_handle_raises(self):
        agent = BaseAgent()
        with pytest.raises(NotImplementedError):
            agent.handle(KernelMessage())


class TestResearchAgent:
    def _agent(self):
        return ResearchAgent(kernel=None)

    def test_handle_no_topic(self):
        result = self._agent().handle(KernelMessage(payload={}))
        assert "No topic" in result

    def test_handle_with_topic(self):
        msg = KernelMessage(payload={"topic": "machine learning"})
        result = self._agent().handle(msg)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_handle_with_query(self):
        msg = KernelMessage(payload={"query": "neural networks"})
        result = self._agent().handle(msg)
        assert isinstance(result, str)


class TestCoderAgent:
    def _agent(self):
        return CoderAgent(kernel=None)

    def test_handle_no_prompt(self):
        result = self._agent().handle(KernelMessage(payload={}))
        assert "No coding" in result

    def test_handle_with_prompt(self):
        msg = KernelMessage(payload={"prompt": "write hello world", "language": "python"})
        result = self._agent().handle(msg)
        assert isinstance(result, str)
        assert len(result) > 0


class TestCriticAgent:
    def _agent(self):
        return CriticAgent(kernel=None)

    def test_handle_empty(self):
        result = self._agent().handle(KernelMessage(payload={}))
        assert "Nothing to critique" in result

    def test_safety_violation(self):
        msg = KernelMessage(payload={"content": "rm -rf /"})
        result = self._agent().handle(msg)
        assert "Safety violation" in result

    def test_short_content_issue(self):
        msg = KernelMessage(payload={"content": "hi"})
        result = self._agent().handle(msg)
        assert "too short" in result

    def test_good_content_passes(self):
        msg = KernelMessage(payload={"content": "This is a well-structured output\nWith multiple lines\nAnd sufficient length to pass all checks."})
        result = self._agent().handle(msg)
        assert "passed" in result.lower()

    def test_todo_flag(self):
        msg = KernelMessage(payload={"content": "Some code here\n# TODO: fix this later\nMore lines"})
        result = self._agent().handle(msg)
        assert "TODO" in result or "quality" in result.lower()


class TestTeacherAgent:
    def _agent(self):
        return TeacherAgent(kernel=None)

    def test_handle_with_topic(self):
        msg = KernelMessage(payload={"topic": "Python decorators"})
        result = self._agent().handle(msg)
        assert "Python decorators" in result
        assert len(result) > 20

    def test_handle_with_concepts(self):
        msg = KernelMessage(payload={"topic": "ML", "concepts": ["gradient", "loss"]})
        result = self._agent().handle(msg)
        assert "gradient" in result or "loss" in result


class TestExplorerAgent:
    def _agent(self):
        return ExplorerAgent(kernel=None)

    def test_handle_empty(self):
        result = self._agent().handle(KernelMessage(payload={}))
        assert isinstance(result, str)

    def test_handle_with_topic(self):
        msg = KernelMessage(payload={"topic": "reinforcement learning"})
        result = self._agent().handle(msg)
        assert "reinforcement learning" in result.lower() or "Suggest" in result


# ═════════════════════════════════════════════════════════════════════════════
# _build_task_graph
# ═════════════════════════════════════════════════════════════════════════════

class TestBuildTaskGraph:
    def test_research_graph(self):
        nodes = _build_task_graph("research", {})
        agents = [n.agent for n in nodes]
        assert _AGENT_RESEARCH in agents

    def test_code_graph(self):
        nodes = _build_task_graph("generate_code", {})
        agents = [n.agent for n in nodes]
        assert _AGENT_CODER in agents

    def test_unknown_intent_fallback(self):
        nodes = _build_task_graph("unknown_intent_xyz", {})
        assert len(nodes) >= 1


# ═════════════════════════════════════════════════════════════════════════════
# NiblitCognitiveKernelV3
# ═════════════════════════════════════════════════════════════════════════════

class TestNiblitCognitiveKernelV3:
    def _kernel(self):
        # Isolated instance with no v1/v2 to avoid import-time side-effects
        return NiblitCognitiveKernelV3(kernel_v1=None, kernel_v2=None)

    def test_instantiates(self):
        k = self._kernel()
        assert k is not None
        assert len(k._agents) == 5

    def test_classify_intent_code(self):
        k = self._kernel()
        intent = k._classify_intent("build a web scraper in python")
        assert intent in ("generate_code", "code", "research")

    def test_classify_intent_research(self):
        k = self._kernel()
        intent = k._classify_intent("research neural network architectures")
        assert intent == "research"

    def test_classify_intent_debug(self):
        k = self._kernel()
        intent = k._classify_intent("there is an error in the code fix it")
        assert intent in ("debug", "generate_code")

    def test_classify_intent_fallback(self):
        k = self._kernel()
        intent = k._classify_intent("hello world")
        assert isinstance(intent, str) and len(intent) > 0

    def test_safety_gate_blocks(self):
        k = self._kernel()
        msg = KernelMessage(intent="delete", payload={"cmd": "rm -rf /"})
        assert k._safety_gate(msg) is False

    def test_safety_gate_passes(self):
        k = self._kernel()
        msg = KernelMessage(intent="research", payload={"topic": "Python"})
        assert k._safety_gate(msg) is True

    def test_remember_no_error(self):
        k = self._kernel()
        k._remember({"event": "test"}, importance=0.5)  # should not raise

    def test_retrieve_memory_no_error(self):
        k = self._kernel()
        result = k._retrieve_memory("test query")
        assert isinstance(result, list)

    def test_dispatch_agent_research(self):
        k = self._kernel()
        msg = KernelMessage(target=_AGENT_RESEARCH, intent="research",
                            payload={"topic": "AI"})
        result = k._dispatch_agent(_AGENT_RESEARCH, msg)
        assert isinstance(result, str)

    def test_dispatch_agent_unknown(self):
        k = self._kernel()
        result = k._dispatch_agent("nonexistent_agent", KernelMessage())
        assert result is None

    def test_process_basic(self):
        k = self._kernel()
        msg = KernelMessage(
            sender=_KERNEL_ID,
            target="broadcast",
            intent="",
            payload={"topic": "artificial intelligence"},
        )
        result = k.process(msg)
        assert result is None or isinstance(result, str)

    def test_process_safety_blocked(self):
        k = self._kernel()
        msg = KernelMessage(
            sender="user",
            target=_AGENT_CODER,
            intent="execute",
            payload={"cmd": "rm -rf /"},
        )
        result = k.process(msg)
        assert result is None

    def test_orchestrate_research(self):
        k = self._kernel()
        outputs = k.orchestrate("research", {"topic": "machine learning"})
        assert isinstance(outputs, dict)
        # Should have run at least one agent
        assert len(outputs) >= 1

    def test_orchestrate_code(self):
        k = self._kernel()
        outputs = k.orchestrate("generate_code", {"topic": "hello world", "language": "python"})
        assert _AGENT_CODER in outputs or _AGENT_RESEARCH in outputs

    def test_run_cognitive_loop_basic(self):
        k = self._kernel()
        result = k.run_cognitive_loop("What is machine learning?")
        assert isinstance(result, KernelV3Result)
        assert result.decision
        assert isinstance(result.latency_ms, float)
        assert result.latency_ms >= 0

    def test_run_cognitive_loop_remembered(self):
        k = self._kernel()
        result = k.run_cognitive_loop("test input")
        assert result.remembered is True

    def test_run_cognitive_loop_no_agents(self):
        k = self._kernel()
        result = k.run_cognitive_loop("test", use_agents=False)
        assert isinstance(result, KernelV3Result)

    def test_run_cognitive_loop_rewards_populated(self):
        k = self._kernel()
        result = k.run_cognitive_loop("explain gradient descent")
        assert isinstance(result.rewards, dict)

    def test_run_cognitive_loop_action_result(self):
        k = self._kernel()
        result = k.run_cognitive_loop("build a trading bot")
        assert isinstance(result.action_result, str)

    def test_v1_compat_think(self):
        k = self._kernel()
        thought = k.think("what is python?")
        assert isinstance(thought, str)

    def test_v1_compat_decide(self):
        k = self._kernel()
        decision = k.decide("we need to research neural networks")
        assert isinstance(decision, str)

    def test_v1_compat_act(self):
        k = self._kernel()
        result = k.act("respond", "some payload")
        assert isinstance(result, str)

    def test_v1_compat_evolve_disabled(self):
        k = NiblitCognitiveKernelV3(evolve_enabled=False)
        result = k.evolve("add new capability")
        assert "disabled" in result.lower()

    def test_status(self):
        k = self._kernel()
        k.run_cognitive_loop("status check")
        s = k.status()
        assert "loop_calls" in s
        assert s["loop_calls"] == 1
        assert "agents" in s
        assert "reward_signals" in s
        assert "cycle_count" in s

    def test_stats_increment(self):
        k = self._kernel()
        for _ in range(3):
            k.run_cognitive_loop("test")
        assert k._stats["loop_calls"] == 3

    def test_concurrent_loops(self):
        k = self._kernel()
        errors = []

        def run():
            try:
                k.run_cognitive_loop("concurrent test")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=run) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert k._stats["loop_calls"] == 5

    def test_to_dict(self):
        k = self._kernel()
        result = k.run_cognitive_loop("hello")
        d = result.to_dict()
        assert "decision" in d
        assert "latency_ms" in d
        assert "agent_outputs" in d
        assert "rewards" in d

    def test_feedback_sync_no_error(self):
        k = self._kernel()
        result = KernelV3Result(input_data="test", decision="research")
        k._feedback_sync(result)  # should not raise even without SyncEngine

    def test_messages_list(self):
        k = self._kernel()
        result = k.run_cognitive_loop("test messages")
        assert isinstance(result.messages, list)


# ═════════════════════════════════════════════════════════════════════════════
# Singleton
# ═════════════════════════════════════════════════════════════════════════════

class TestSingleton:
    def test_same_instance(self):
        import modules.niblit_kernel_v3 as mod
        old = mod._kernel_v3
        mod._kernel_v3 = None  # reset for test
        try:
            k1 = get_niblit_kernel_v3()
            k2 = get_niblit_kernel_v3()
            assert k1 is k2
        finally:
            mod._kernel_v3 = old

    def test_thread_safe_singleton(self):
        import modules.niblit_kernel_v3 as mod
        old = mod._kernel_v3
        mod._kernel_v3 = None  # reset
        instances = []
        lock = threading.Lock()

        def get():
            k = get_niblit_kernel_v3()
            with lock:
                instances.append(k)

        threads = [threading.Thread(target=get) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # All threads must get the same singleton
        first = instances[0]
        assert all(i is first for i in instances)
        mod._kernel_v3 = old


if __name__ == "__main__":
    print('Running test_niblit_kernel_v3.py')
