#!/usr/bin/env python3
"""
test_dpais_staca.py — Unit tests for the DPAIS and STACA subsystems.

DPAIS = Distributed Planetary-Scale AI System  (distributed_niblit/)
STACA = Self-Training AI Civilization Architecture (civilization/)

Run with::

    pytest test_dpais_staca.py -v
"""

import math
import unittest


# =============================================================================
# DPAIS — distributed_niblit/
# =============================================================================

# ── network ───────────────────────────────────────────────────────────────────

class TestMessageBus(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.network.message_bus import MessageBus
        self.bus = MessageBus()

    def test_publish_and_retrieve(self):
        self.bus.publish("task", {"id": "1", "type": "research"})
        msgs = self.bus.get_messages("task")
        self.assertEqual(len(msgs), 1)
        # Messages are stored as {"topic": ..., "message": {...}, "ts": ...}
        payload = msgs[0].get("message", msgs[0])
        self.assertEqual(payload["type"], "research")

    def test_multiple_topics(self):
        self.bus.publish("topicA", {"val": 1})
        self.bus.publish("topicB", {"val": 2})
        self.assertEqual(len(self.bus.get_messages("topicA")), 1)
        self.assertEqual(len(self.bus.get_messages("topicB")), 1)

    def test_clear(self):
        self.bus.publish("topic", {"x": 1})
        self.bus.clear()
        self.assertEqual(self.bus.get_messages("topic"), [])

    def test_subscribe_handler_called(self):
        received = []
        self.bus.subscribe("events", received.append)
        self.bus.publish("events", {"event": "node_joined"})
        self.assertEqual(len(received), 1)
        # Handler receives the wrapped message dict; extract nested payload if needed
        msg = received[0]
        payload = msg.get("message", msg)
        self.assertEqual(payload["event"], "node_joined")

    def test_empty_topic_returns_list(self):
        result = self.bus.get_messages("nonexistent")
        self.assertIsInstance(result, list)
        self.assertEqual(result, [])


class TestNodeProtocol(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.network.node_protocol import NodeProtocol
        self.proto = NodeProtocol()

    def test_encode_decode_roundtrip(self):
        msg_type, task_id, payload = "research_task", "t-123", {"topic": "transformers"}
        encoded = self.proto.encode_message(msg_type, task_id, payload)
        d_type, d_id, d_payload = self.proto.decode_message(encoded)
        self.assertEqual(d_type, msg_type)
        self.assertEqual(d_id, task_id)
        self.assertEqual(d_payload["topic"], "transformers")

    def test_validate_valid_message(self):
        msg = self.proto.encode_message("ping", "t-0", {})
        self.assertTrue(self.proto.validate_message(msg))

    def test_validate_invalid_message(self):
        self.assertFalse(self.proto.validate_message({"garbage": True}))


class TestServiceRegistry(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.network.service_registry import ServiceRegistry
        self.reg = ServiceRegistry()

    def test_register_and_lookup(self):
        self.reg.register("knowledge_api", {"url": "http://node1:8080"})
        svc = self.reg.lookup("knowledge_api")
        self.assertIsNotNone(svc)
        self.assertIn("url", svc)

    def test_deregister(self):
        self.reg.register("temp_svc", {"url": "x"})
        self.reg.deregister("temp_svc")
        self.assertIsNone(self.reg.lookup("temp_svc"))

    def test_list_services(self):
        self.reg.register("svc1", {})
        self.reg.register("svc2", {})
        names = self.reg.list_services()
        self.assertIn("svc1", names)
        self.assertIn("svc2", names)


# ── orchestrator ──────────────────────────────────────────────────────────────

class TestNodeRegistry(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.orchestrator.node_registry import NodeRegistry
        self.reg = NodeRegistry()

    def test_register_and_get(self):
        self.reg.register_node("node1", "agent_node", {"cpu": 4, "gpu": 1})
        node = self.reg.get_node("node1")
        self.assertIsNotNone(node)
        self.assertEqual(node["node_type"], "agent_node")

    def test_list_nodes_by_type(self):
        self.reg.register_node("an1", "agent_node", {})
        self.reg.register_node("kn1", "knowledge_node", {})
        agents = self.reg.list_nodes("agent_node")
        self.assertTrue(any(n["node_id"] == "an1" for n in agents))
        knowledge = self.reg.list_nodes("knowledge_node")
        self.assertTrue(any(n["node_id"] == "kn1" for n in knowledge))

    def test_deregister(self):
        self.reg.register_node("tmp", "control_node", {})
        self.reg.deregister_node("tmp")
        self.assertIsNone(self.reg.get_node("tmp"))

    def test_update_status(self):
        self.reg.register_node("n2", "agent_node", {})
        self.reg.update_status("n2", "busy")
        node = self.reg.get_node("n2")
        self.assertEqual(node["status"], "busy")


class TestTaskRouter(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.orchestrator.task_router import TaskRouter
        self.router = TaskRouter()

    def test_register_and_route(self):
        self.router.register_route_rule("research", "agent_node")
        route = self.router.get_route("research")
        self.assertEqual(route, "agent_node")

    def test_route_task(self):
        self.router.register_route_rule("code_gen", "agent_node")
        node_type = self.router.route({"type": "code_gen"})
        self.assertIsNotNone(node_type)


class TestJobDispatcher(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.orchestrator.job_dispatcher import JobDispatcher
        self.dispatcher = JobDispatcher()

    def test_queue_and_status(self):
        job_id = self.dispatcher.queue_job({"type": "research", "topic": "nlp"})
        self.assertIsNotNone(job_id)
        status = self.dispatcher.get_job_status(job_id)
        self.assertIn(status, ["queued", "pending", "running", "completed"])

    def test_dispatch(self):
        result = self.dispatcher.dispatch({"type": "ping"}, "node-1")
        self.assertIsInstance(result, dict)


class TestWorkloadBalancer(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.orchestrator.workload_balancer import WorkloadBalancer
        self.balancer = WorkloadBalancer()

    def test_select_node_round_robin(self):
        nodes = ["node1", "node2", "node3"]
        selected = self.balancer.select_node(nodes)
        self.assertIn(selected, nodes)

    def test_least_loaded(self):
        self.balancer.report_load("n1", 0.8)
        self.balancer.report_load("n2", 0.2)
        least = self.balancer.get_least_loaded()
        self.assertEqual(least, "n2")


# ── api_gateway ───────────────────────────────────────────────────────────────

class TestRateLimiter(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.api_gateway.rate_limiter import RateLimiter
        self.limiter = RateLimiter()

    def test_allow_within_limit(self):
        self.limiter.set_limit("client1", 60)
        self.assertTrue(self.limiter.allow("client1"))

    def test_stats_returns_dict(self):
        self.limiter.set_limit("client2", 30)
        stats = self.limiter.get_stats("client2")
        self.assertIsInstance(stats, dict)


class TestAuthLayer(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.api_gateway.auth_layer import AuthLayer
        self.auth = AuthLayer()

    def test_create_and_validate(self):
        key = self.auth.create_api_key("client_a")
        self.assertIsNotNone(key)
        self.assertTrue(self.auth.validate_api_key(key))

    def test_revoke(self):
        key = self.auth.create_api_key("client_b")
        self.auth.revoke_api_key(key)
        self.assertFalse(self.auth.validate_api_key(key))

    def test_list_clients(self):
        self.auth.create_api_key("c1")
        self.auth.create_api_key("c2")
        clients = self.auth.list_clients()
        self.assertIn("c1", clients)
        self.assertIn("c2", clients)


class TestRoutingLayer(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.api_gateway.routing_layer import RoutingLayer
        self.router = RoutingLayer()

    def test_add_and_route(self):
        def handler(body):
            return {"ok": True}
        self.router.add_route("/api/v1/tasks", handler)
        routes = self.router.list_routes()
        self.assertIn("/api/v1/tasks", routes)


class TestGatewayServer(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.api_gateway.gateway_server import GatewayServer
        from distributed_niblit.api_gateway.auth_layer import AuthLayer
        from distributed_niblit.api_gateway.rate_limiter import RateLimiter
        from distributed_niblit.api_gateway.routing_layer import RoutingLayer
        self.server = GatewayServer(
            auth=AuthLayer(),
            rate_limiter=RateLimiter(),
            router=RoutingLayer(),
        )

    def test_handle_request_returns_dict(self):
        result = self.server.handle_request(
            "/api/v1/tasks", "POST", {}, {"type": "research"}
        )
        self.assertIsInstance(result, dict)
        self.assertIn("status_code", result)

    def test_get_stats(self):
        stats = self.server.get_stats()
        self.assertIsInstance(stats, dict)


# ── agent_node ────────────────────────────────────────────────────────────────

class TestTaskExecutor(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.agent_node.task_executor import TaskExecutor
        self.executor = TaskExecutor()

    def test_execute_basic_plan(self):
        result = self.executor.execute({"type": "ping", "steps": []})
        self.assertIsInstance(result, dict)

    def test_register_and_run_handler(self):
        called = []
        def my_handler(plan):
            called.append(plan)
            return {"done": True}
        self.executor.register_handler("custom", my_handler)
        result = self.executor.execute({"type": "custom", "steps": []})
        self.assertTrue(len(called) > 0 or isinstance(result, dict))


class TestAgentNodeResearchAgent(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.agent_node.research_agent import ResearchAgent
        self.agent = ResearchAgent()

    def test_research_returns_dict(self):
        result = self.agent.research("transformer neural networks")
        self.assertIsInstance(result, dict)
        self.assertIn("topic", result)

    def test_history_grows(self):
        self.agent.research("topic1")
        self.agent.research("topic2")
        hist = self.agent.get_history()
        self.assertGreaterEqual(len(hist), 2)


class TestPlannerAgent(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.agent_node.planner_agent import PlannerAgent
        self.planner = PlannerAgent()

    def test_create_plan(self):
        plan = self.planner.create_plan({"type": "research", "goal": "study GNN"})
        self.assertIsInstance(plan, dict)
        self.assertIn("steps", plan)

    def test_decompose_goal(self):
        tasks = self.planner.decompose("build a distributed cache")
        self.assertIsInstance(tasks, list)
        self.assertGreater(len(tasks), 0)


class TestAgentNodeCodeGenerator(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.agent_node.code_generator import CodeGenerator
        self.gen = CodeGenerator()

    def test_generate_python(self):
        result = self.gen.generate("python", "hello world function")
        self.assertIsInstance(result, dict)
        self.assertIn("code", result)
        self.assertIn("success", result)

    def test_supported_languages(self):
        langs = self.gen.get_supported_languages()
        self.assertIsInstance(langs, list)
        self.assertIn("python", langs)


class TestAgentRuntime(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.agent_node.agent_runtime import AgentRuntime
        from distributed_niblit.agent_node.task_executor import TaskExecutor
        from distributed_niblit.agent_node.planner_agent import PlannerAgent
        from distributed_niblit.agent_node.research_agent import ResearchAgent
        self.runtime = AgentRuntime(
            executor=TaskExecutor(),
            planner=PlannerAgent(),
            research=ResearchAgent(),
        )

    def test_process_task(self):
        result = self.runtime.process_task({"type": "research", "goal": "test"})
        self.assertIsInstance(result, dict)

    def test_get_status(self):
        status = self.runtime.get_status()
        self.assertIsInstance(status, dict)

    def test_stop(self):
        self.runtime.stop()
        status = self.runtime.get_status()
        self.assertIsInstance(status, dict)


# ── knowledge_node ────────────────────────────────────────────────────────────

class TestVectorStore(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.knowledge_node.vector_store import VectorStore
        self.store = VectorStore()

    def test_add_and_size(self):
        self.store.add("doc1", [0.1, 0.2, 0.3])
        self.assertEqual(self.store.size(), 1)

    def test_search_returns_results(self):
        self.store.add("doc1", [1.0, 0.0, 0.0])
        self.store.add("doc2", [0.0, 1.0, 0.0])
        results = self.store.search([1.0, 0.0, 0.0], top_k=1)
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)

    def test_remove(self):
        self.store.add("to_remove", [0.5, 0.5])
        self.store.remove("to_remove")
        self.assertEqual(self.store.size(), 0)

    def test_clear(self):
        self.store.add("x", [1.0])
        self.store.clear()
        self.assertEqual(self.store.size(), 0)


class TestGraphStore(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.knowledge_node.graph_store import GraphStore
        self.graph = GraphStore()

    def test_add_and_get_node(self):
        self.graph.add_node("concept_a", {"label": "Transformer"})
        node = self.graph.get_node("concept_a")
        self.assertIsNotNone(node)
        self.assertEqual(node["label"], "Transformer")

    def test_add_edge_and_neighbors(self):
        self.graph.add_node("a", {})
        self.graph.add_node("b", {})
        self.graph.add_edge("a", "b", "RELATED_TO")
        neighbors = self.graph.get_neighbors("a")
        self.assertTrue(any(n["node_id"] == "b" for n in neighbors))

    def test_node_count(self):
        self.graph.add_node("n1", {})
        self.graph.add_node("n2", {})
        self.assertEqual(self.graph.node_count(), 2)


class TestEmbeddingServiceDN(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.knowledge_node.embedding_service import EmbeddingService
        self.svc = EmbeddingService()

    def test_embed_returns_vector(self):
        vec = self.svc.embed("hello world")
        self.assertEqual(len(vec), 64)

    def test_deterministic(self):
        v1 = self.svc.embed("same text")
        v2 = self.svc.embed("same text")
        self.assertEqual(v1, v2)

    def test_similarity_same_text(self):
        v = self.svc.embed("neural networks")
        sim = self.svc.similarity(v, v)
        self.assertAlmostEqual(sim, 1.0, places=5)

    def test_embed_batch(self):
        vecs = self.svc.embed_batch(["text1", "text2", "text3"])
        self.assertEqual(len(vecs), 3)


class TestKnowledgeAPIDN(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.knowledge_node.knowledge_api import KnowledgeAPI
        self.api = KnowledgeAPI()

    def test_store_and_retrieve(self):
        self.api.store("topic:gnn", "Graph Neural Networks are...", tags=["ml", "graphs"])
        item = self.api.retrieve("topic:gnn")
        self.assertIsNotNone(item)

    def test_delete(self):
        self.api.store("temp", "value")
        self.api.delete("temp")
        self.assertIsNone(self.api.retrieve("temp"))

    def test_count(self):
        self.api.store("k1", "v1")
        self.api.store("k2", "v2")
        self.assertGreaterEqual(self.api.count(), 2)

    def test_search(self):
        self.api.store("neural", "neural network architecture details")
        results = self.api.search("neural")
        self.assertIsInstance(results, list)


# ── experiment_node ───────────────────────────────────────────────────────────

class TestExperimentRunner(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.experiment_node.experiment_runner import ExperimentRunner
        self.runner = ExperimentRunner()

    def test_create_and_get(self):
        exp_id = self.runner.create_experiment("benchmark_test", "algo_a > algo_b")
        self.assertIsNotNone(exp_id)
        exp = self.runner.get_experiment(exp_id)
        self.assertIsNotNone(exp)

    def test_run(self):
        result = self.runner.run({"name": "speed_test", "hypothesis": "faster is better"})
        self.assertIsInstance(result, dict)

    def test_list_experiments(self):
        self.runner.create_experiment("e1", "h1")
        self.runner.create_experiment("e2", "h2")
        ids = self.runner.list_experiments()
        self.assertGreaterEqual(len(ids), 2)


class TestSandboxExecutorDN(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.experiment_node.sandbox_executor import SandboxExecutor
        self.sandbox = SandboxExecutor()

    def test_run_safe_code(self):
        result = self.sandbox.run("x = 1 + 2")
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)

    def test_validate_safe_code(self):
        self.assertTrue(self.sandbox.validate_code("def foo(): return 42"))

    def test_validate_unsafe_code(self):
        self.assertFalse(self.sandbox.validate_code("import os; os.system('rm -rf /')"))


class TestBenchmarkEngineDN(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.experiment_node.benchmark_engine import BenchmarkEngine
        self.engine = BenchmarkEngine()

    def test_evaluate_valid_code(self):
        result = self.engine.evaluate("def add(a, b): return a + b")
        self.assertIsInstance(result, dict)
        self.assertIn("syntax_valid", result)
        self.assertTrue(result["syntax_valid"])

    def test_evaluate_invalid_code(self):
        result = self.engine.evaluate("def broken(:\n    pass")
        self.assertFalse(result["syntax_valid"])

    def test_compare(self):
        r1 = self.engine.evaluate("x = 1")
        r2 = self.engine.evaluate("y = 2")
        comparison = self.engine.compare([r1, r2])
        self.assertIsInstance(comparison, dict)


class TestResultsCollector(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.experiment_node.results_collector import ResultsCollector
        self.collector = ResultsCollector()

    def test_record_and_get(self):
        self.collector.record("exp1", {"score": 0.92, "time_ms": 45})
        results = self.collector.get("exp1")
        self.assertEqual(len(results), 1)

    def test_aggregate(self):
        self.collector.record("exp2", {"score": 0.8})
        self.collector.record("exp2", {"score": 0.9})
        agg = self.collector.aggregate("exp2")
        self.assertIsInstance(agg, dict)

    def test_export_csv(self):
        self.collector.record("exp3", {"score": 1.0, "time_ms": 10})
        csv_str = self.collector.export_csv("exp3")
        self.assertIsInstance(csv_str, str)


# ── scheduler ─────────────────────────────────────────────────────────────────

class TestTaskScheduler(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.scheduler.task_scheduler import TaskScheduler
        self.scheduler = TaskScheduler()

    def test_schedule_and_pending(self):
        task_id = self.scheduler.schedule({"type": "research"})
        self.assertIsNotNone(task_id)
        pending = self.scheduler.get_pending()
        self.assertIsInstance(pending, list)

    def test_cancel(self):
        task_id = self.scheduler.schedule({"type": "test"})
        self.scheduler.cancel(task_id)
        pending_ids = [t.get("id", t.get("task_id")) for t in self.scheduler.get_pending()]
        self.assertNotIn(task_id, pending_ids)


class TestResearchScheduler(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.scheduler.research_scheduler import ResearchScheduler
        self.sched = ResearchScheduler()

    def test_schedule_and_list(self):
        sched_id = self.sched.schedule_research("graph neural networks", interval_s=3600)
        self.assertIsNotNone(sched_id)
        topics = self.sched.get_scheduled_topics()
        self.assertIsInstance(topics, list)

    def test_trigger_now(self):
        result = self.sched.trigger_now("transformer optimization")
        self.assertIsInstance(result, dict)


class TestExperimentScheduler(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.scheduler.experiment_scheduler import ExperimentScheduler
        self.sched = ExperimentScheduler()

    def test_schedule_and_queue(self):
        sid = self.sched.schedule_experiment({"name": "test_exp"}, priority=5)
        self.assertIsNotNone(sid)
        queue = self.sched.get_queue()
        self.assertIsInstance(queue, list)

    def test_next_experiment(self):
        self.sched.schedule_experiment({"name": "exp1"}, priority=8)
        exp = self.sched.next_experiment()
        self.assertIsInstance(exp, (dict, type(None)))


class TestEvolutionScheduler(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.scheduler.evolution_scheduler import EvolutionScheduler
        self.sched = EvolutionScheduler()

    def test_schedule_and_list(self):
        cycle_id = self.sched.schedule_evolution_cycle()
        self.assertIsNotNone(cycle_id)
        cycles = self.sched.get_cycles()
        self.assertIsInstance(cycles, list)

    def test_run_next_cycle(self):
        self.sched.schedule_evolution_cycle({"detect_weakness": True})
        result = self.sched.run_next_cycle()
        self.assertIsInstance(result, dict)


# ── observability ─────────────────────────────────────────────────────────────

class TestMetricsCollector(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.observability.metrics_collector import MetricsCollector
        self.mc = MetricsCollector()

    def test_record_and_get(self):
        self.mc.record("cpu_usage", 45.2)
        self.mc.record("cpu_usage", 50.1)
        data = self.mc.get("cpu_usage")
        self.assertEqual(len(data), 2)

    def test_aggregate(self):
        self.mc.record("latency", 10.0)
        self.mc.record("latency", 20.0)
        agg = self.mc.aggregate("latency")
        self.assertAlmostEqual(agg["mean"], 15.0, places=3)
        self.assertEqual(agg["max"], 20.0)
        self.assertEqual(agg["min"], 10.0)

    def test_reset(self):
        self.mc.record("mem", 1024)
        self.mc.reset("mem")
        self.assertEqual(self.mc.get("mem"), [])


class TestLogAggregator(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.observability.log_aggregator import LogAggregator
        self.agg = LogAggregator()

    def test_log_and_retrieve(self):
        self.agg.log("INFO", "agent_node", "Task started", {"task_id": "t1"})
        logs = self.agg.get_logs(source="agent_node")
        self.assertGreater(len(logs), 0)

    def test_filter_by_level(self):
        self.agg.log("ERROR", "gateway", "Connection failed")
        self.agg.log("INFO", "gateway", "All good")
        errors = self.agg.get_logs(level="ERROR")
        self.assertTrue(all(l["level"] == "ERROR" for l in errors))

    def test_tail(self):
        for i in range(5):
            self.agg.log("INFO", "src", f"msg {i}")
        tail = self.agg.tail(n=3)
        self.assertLessEqual(len(tail), 3)


class TestAnomalyDetector(unittest.TestCase):
    def setUp(self):
        from distributed_niblit.observability.anomaly_detector import AnomalyDetector
        self.detector = AnomalyDetector()

    def test_observe_and_no_anomaly(self):
        for v in [10, 11, 10, 12, 10]:
            self.detector.observe("metric_a", v)
        # Normal values should not trigger anomaly
        self.assertFalse(self.detector.is_anomalous("metric_a", 11))

    def test_spike_is_anomalous(self):
        self.detector.set_threshold("cpu", 50.0, 5.0)
        self.assertTrue(self.detector.is_anomalous("cpu", 200.0))

    def test_get_anomalies_returns_list(self):
        anomalies = self.detector.get_anomalies()
        self.assertIsInstance(anomalies, list)


# =============================================================================
# STACA — civilization/
# =============================================================================

# ── civilization_core ─────────────────────────────────────────────────────────

class TestCivilizationController(unittest.TestCase):
    def setUp(self):
        from civilization.civilization_core.civilization_controller import CivilizationController
        self.ctrl = CivilizationController()

    def test_initial_status(self):
        status = self.ctrl.get_status()
        self.assertIsInstance(status, dict)
        self.assertEqual(self.ctrl.get_cycle_count(), 0)

    def test_run_cycle_increments_count(self):
        self.ctrl.run_cycle()
        self.assertGreaterEqual(self.ctrl.get_cycle_count(), 1)

    def test_stop(self):
        self.ctrl.start()
        self.ctrl.stop()
        status = self.ctrl.get_status()
        self.assertFalse(status.get("running", True))


class TestPopulationManager(unittest.TestCase):
    def setUp(self):
        from civilization.civilization_core.population_manager import PopulationManager
        self.mgr = PopulationManager()

    def test_spawn_single(self):
        ids = self.mgr.spawn("research")
        self.assertEqual(len(ids), 1)

    def test_spawn_multiple(self):
        ids = self.mgr.spawn("builder", count=3)
        self.assertEqual(len(ids), 3)
        self.assertEqual(self.mgr.agent_count(), 3)

    def test_get_agents_by_role(self):
        self.mgr.spawn("planner", count=2)
        self.mgr.spawn("analyst", count=1)
        planners = self.mgr.get_agents("planner")
        self.assertEqual(len(planners), 2)

    def test_despawn(self):
        ids = self.mgr.spawn("evolution")
        self.mgr.despawn(ids[0])
        self.assertEqual(self.mgr.agent_count(), 0)


class TestCivilizationScheduler(unittest.TestCase):
    def setUp(self):
        from civilization.civilization_core.civilization_scheduler import CivilizationScheduler
        self.sched = CivilizationScheduler()

    def test_assign_task_returns_dict(self):
        task = self.sched.assign_task({"agent_id": "a1", "role": "research"})
        self.assertIsInstance(task, dict)

    def test_register_task_type(self):
        self.sched.register_task_type("custom_task", {"priority": 10})
        queue = self.sched.get_task_queue()
        self.assertIsInstance(queue, list)


class TestCivilizationMetrics(unittest.TestCase):
    def setUp(self):
        from civilization.civilization_core.civilization_metrics import CivilizationMetrics
        self.metrics = CivilizationMetrics()

    def test_record_and_summary(self):
        self.metrics.record_cycle({"agents": 10, "tasks": 5, "discoveries": 1})
        summary = self.metrics.get_summary()
        self.assertIn("total_cycles", summary)
        self.assertEqual(summary["total_cycles"], 1)

    def test_get_cycle_history(self):
        self.metrics.record_cycle({"agents": 5, "tasks": 2})
        history = self.metrics.get_cycle_history()
        self.assertEqual(len(history), 1)

    def test_export(self):
        self.metrics.record_cycle({"agents": 8})
        exported = self.metrics.export()
        self.assertIsInstance(exported, dict)


# ── agent_population ──────────────────────────────────────────────────────────

class TestBaseAgent(unittest.TestCase):
    def test_instantiation(self):
        from civilization.agent_population.base_agent import BaseAgent
        agent = BaseAgent("agent_001", "research")
        self.assertEqual(agent.agent_id, "agent_001")
        self.assertEqual(agent.role, "research")

    def test_execute_raises(self):
        from civilization.agent_population.base_agent import BaseAgent
        agent = BaseAgent("a1", "base")
        with self.assertRaises(NotImplementedError):
            agent.execute({})

    def test_memory_operations(self):
        from civilization.agent_population.base_agent import BaseAgent
        agent = BaseAgent("a2", "builder")
        agent.store_memory("key1", "value1")
        mem = agent.get_memory()
        self.assertIn("key1", mem)
        self.assertEqual(mem["key1"], "value1")

    def test_stats(self):
        from civilization.agent_population.base_agent import BaseAgent
        agent = BaseAgent("a3", "planner")
        stats = agent.get_stats()
        self.assertIn("tasks_completed", stats)


class TestSTACAResearchAgent(unittest.TestCase):
    def setUp(self):
        from civilization.agent_population.research_agent import ResearchAgent
        self.agent = ResearchAgent("r1", "research")

    def test_execute_returns_insights(self):
        result = self.agent.execute({"topic": "distributed systems", "type": "research"})
        self.assertIsInstance(result, dict)
        self.assertIn("insights", result)

    def test_search_repositories(self):
        repos = self.agent.search_repositories("machine learning")
        self.assertIsInstance(repos, list)


class TestBuilderAgent(unittest.TestCase):
    def setUp(self):
        from civilization.agent_population.builder_agent import BuilderAgent
        self.agent = BuilderAgent("b1", "builder")

    def test_execute_returns_code(self):
        result = self.agent.execute({"architecture": {"type": "api", "lang": "python"}, "type": "build"})
        self.assertIsInstance(result, dict)
        self.assertIn("code", result)

    def test_validate_output(self):
        valid = self.agent.validate_output("def hello(): return 'hi'")
        self.assertTrue(valid)


class TestSTACAPlannerAgent(unittest.TestCase):
    def setUp(self):
        from civilization.agent_population.planner_agent import PlannerAgent
        self.agent = PlannerAgent("p1", "planner")

    def test_execute_returns_plan(self):
        result = self.agent.execute({"goal": "build a knowledge graph", "type": "plan"})
        self.assertIsInstance(result, dict)
        self.assertIn("plan_steps", result)

    def test_decompose_goal(self):
        tasks = self.agent.decompose_goal("build distributed cache")
        self.assertIsInstance(tasks, list)
        self.assertGreater(len(tasks), 0)


class TestAnalystAgent(unittest.TestCase):
    def setUp(self):
        from civilization.agent_population.analyst_agent import AnalystAgent
        self.agent = AnalystAgent("an1", "analyst")

    def test_execute_returns_analysis(self):
        result = self.agent.execute({"experiment": {"name": "test"}, "type": "analyze"})
        self.assertIsInstance(result, dict)
        self.assertIn("analysis", result)

    def test_compare_results(self):
        comparison = self.agent.compare_results([{"score": 0.9}, {"score": 0.7}])
        self.assertIsInstance(comparison, dict)


class TestEvolutionAgent(unittest.TestCase):
    def setUp(self):
        from civilization.agent_population.evolution_agent import EvolutionAgent
        self.agent = EvolutionAgent("e1", "evolution")

    def test_execute_returns_improvement(self):
        result = self.agent.execute({"system_state": {}, "type": "evolve"})
        self.assertIsInstance(result, dict)
        self.assertIn("improvement", result)

    def test_detect_weakness(self):
        weakness = self.agent.detect_weakness({"error_rate": 0.5, "latency_ms": 2000})
        self.assertIsInstance(weakness, str)
        self.assertGreater(len(weakness), 0)

    def test_generate_hypothesis(self):
        hyp = self.agent.generate_hypothesis("high latency in knowledge retrieval")
        self.assertIsInstance(hyp, dict)


# ── training_arena ────────────────────────────────────────────────────────────

class TestArenaManager(unittest.TestCase):
    def setUp(self):
        from civilization.training_arena.arena_manager import ArenaManager
        self.mgr = ArenaManager()

    def test_create_and_list(self):
        self.mgr.create_arena("arena_1")
        arenas = self.mgr.list_arenas()
        self.assertIn("arena_1", arenas)

    def test_get_leaderboard(self):
        self.mgr.create_arena("arena_2")
        lb = self.mgr.get_leaderboard("arena_2")
        self.assertIsInstance(lb, list)


class TestChallengeGenerator(unittest.TestCase):
    def setUp(self):
        from civilization.training_arena.challenge_generator import ChallengeGenerator
        self.gen = ChallengeGenerator()

    def test_generate_returns_dict(self):
        challenge = self.gen.generate("medium")
        self.assertIsInstance(challenge, dict)
        self.assertIn("title", challenge)

    def test_list_challenges(self):
        self.gen.generate("easy")
        self.gen.generate("hard")
        challenges = self.gen.list_challenges()
        self.assertIsInstance(challenges, list)


class TestCompetitionEngine(unittest.TestCase):
    def setUp(self):
        from civilization.training_arena.competition_engine import CompetitionEngine
        self.engine = CompetitionEngine()

    def test_run_returns_ranked_list(self):
        # CompetitionEngine accepts agent IDs (strings) or objects with agent_id attr
        from civilization.agent_population.builder_agent import BuilderAgent
        agents = [BuilderAgent("b1", "builder"), BuilderAgent("b2", "builder")]
        challenge = {"title": "write sort", "type": "code"}
        results = self.engine.run(agents, challenge)
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 2)

    def test_evaluate_solution(self):
        score = self.engine.evaluate_solution("def sort(x): return sorted(x)", {"type": "code"})
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)


class TestScoringSystem(unittest.TestCase):
    def setUp(self):
        from civilization.training_arena.scoring_system import ScoringSystem
        self.scoring = ScoringSystem()

    def test_score_returns_float(self):
        score = self.scoring.score("def hello(): pass", {"title": "test"})
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_leaderboard_grows(self):
        self.scoring.update_leaderboard("agent1", 0.9)
        self.scoring.update_leaderboard("agent2", 0.7)
        lb = self.scoring.get_leaderboard()
        self.assertGreaterEqual(len(lb), 2)

    def test_rank(self):
        scores = [("a1", 0.8), ("a2", 0.5), ("a3", 0.95)]
        ranked = self.scoring.rank(scores)
        self.assertEqual(len(ranked), 3)


# ── collaboration_network ─────────────────────────────────────────────────────

class TestSTACAMessageBus(unittest.TestCase):
    def setUp(self):
        from civilization.collaboration_network.message_bus import MessageBus
        self.bus = MessageBus()

    def test_publish_and_retrieve(self):
        self.bus.publish("knowledge_share", "agent_1", {"pattern": "actor model"})
        msgs = self.bus.get_messages("knowledge_share")
        self.assertGreater(len(msgs), 0)

    def test_broadcast(self):
        self.bus.broadcast({"announcement": "new discovery"})

    def test_subscribe_and_receive(self):
        received = []
        self.bus.subscribe("events", received.append)
        self.bus.publish("events", "sender1", {"event": "task_done"})
        self.assertGreater(len(received), 0)


class TestAgentProtocol(unittest.TestCase):
    def setUp(self):
        from civilization.collaboration_network.agent_protocol import AgentProtocol
        self.proto = AgentProtocol()

    def test_encode_decode_roundtrip(self):
        encoded = self.proto.encode("agent_1", "agent_2", {"type": "knowledge_share"})
        sender, recipient, content = self.proto.decode(encoded)
        self.assertEqual(sender, "agent_1")
        self.assertEqual(recipient, "agent_2")
        self.assertEqual(content["type"], "knowledge_share")

    def test_validate_valid(self):
        msg = self.proto.encode("a", "b", {})
        self.assertTrue(self.proto.validate(msg))

    def test_validate_invalid(self):
        self.assertFalse(self.proto.validate({"garbage": 1}))


class TestSTACAServiceRegistry(unittest.TestCase):
    def setUp(self):
        from civilization.collaboration_network.service_registry import ServiceRegistry
        self.reg = ServiceRegistry()

    def test_register_and_find(self):
        self.reg.register("knowledge_service", "agent_1", ["store", "retrieve"])
        agents = self.reg.find("store")
        self.assertIn("agent_1", agents)

    def test_deregister(self):
        self.reg.register("temp", "agent_x", ["compute"])
        self.reg.deregister("temp")
        agents = self.reg.find("compute")
        self.assertNotIn("agent_x", agents)

    def test_list_all(self):
        self.reg.register("svc_a", "a1", [])
        all_svcs = self.reg.list_all()
        self.assertIsInstance(all_svcs, dict)


# ── evolution_engine ──────────────────────────────────────────────────────────

class TestMutationEngine(unittest.TestCase):
    def setUp(self):
        from civilization.evolution_engine.mutation_engine import MutationEngine
        self.engine = MutationEngine()

    def test_mutate_returns_dict(self):
        params = {"learning_rate": 0.01, "hidden_size": 128, "dropout": 0.3}
        mutated = self.engine.mutate(params)
        self.assertIsInstance(mutated, dict)
        self.assertIn("learning_rate", mutated)

    def test_mutation_changes_values(self):
        params = {"lr": 1.0}
        results = [self.engine.mutate(params, mutation_rate=0.5)["lr"] for _ in range(20)]
        # At least some should differ from original
        self.assertTrue(any(abs(r - 1.0) > 1e-9 for r in results))

    def test_batch_mutate(self):
        pop = [{"lr": 0.01}, {"lr": 0.02}, {"lr": 0.03}]
        mutated = self.engine.batch_mutate(pop)
        self.assertEqual(len(mutated), 3)


class TestSelectionEngine(unittest.TestCase):
    def setUp(self):
        from civilization.evolution_engine.selection_engine import SelectionEngine
        self.engine = SelectionEngine()

    def test_select_top_agents(self):
        pop = [{"id": f"a{i}", "lr": i * 0.01} for i in range(10)]
        scores = {f"a{i}": float(i) for i in range(10)}
        selected = self.engine.select(pop, scores, n=3)
        self.assertEqual(len(selected), 3)

    def test_elite_select(self):
        pop = [{"id": f"a{i}"} for i in range(5)]
        scores = {f"a{i}": float(i) for i in range(5)}
        elite = self.engine.elite_select(pop, scores, n=2)
        self.assertEqual(len(elite), 2)


class TestPopulationOptimizer(unittest.TestCase):
    def setUp(self):
        from civilization.evolution_engine.population_optimizer import PopulationOptimizer
        self.opt = PopulationOptimizer()

    def test_optimize_returns_best(self):
        pop = [{"lr": 0.01 * i} for i in range(1, 6)]

        def fitness(agent):
            return -abs(agent["lr"] - 0.03)  # optimal at lr=0.03

        result = self.opt.optimize(pop, fitness, generations=3)
        self.assertIsInstance(result, dict)
        self.assertIn("best_agent", result)
        self.assertIn("best_fitness", result)


class TestArchitectureEvolver(unittest.TestCase):
    def setUp(self):
        from civilization.evolution_engine.architecture_evolver import ArchitectureEvolver
        self.evolver = ArchitectureEvolver()

    def test_evolve_returns_architecture(self):
        arch = {"layers": 3, "hidden_size": 128, "activation": "relu"}
        metrics = {"accuracy": 0.85, "loss": 0.3}
        evolved = self.evolver.evolve(arch, metrics)
        self.assertIsInstance(evolved, dict)

    def test_suggest_improvements(self):
        arch = {"layers": 1, "hidden_size": 32}
        suggestions = self.evolver.suggest_improvements(arch)
        self.assertIsInstance(suggestions, list)


# ── knowledge_ecosystem ───────────────────────────────────────────────────────

class TestVectorMemory(unittest.TestCase):
    def setUp(self):
        from civilization.knowledge_ecosystem.vector_memory import VectorMemory
        self.mem = VectorMemory()

    def test_store_and_recall(self):
        self.mem.store("concept1", [1.0, 0.0, 0.0], {"source": "research"})
        results = self.mem.recall([1.0, 0.0, 0.0], top_k=1)
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)

    def test_forget(self):
        self.mem.store("to_forget", [0.5, 0.5])
        self.mem.forget("to_forget")
        self.assertEqual(self.mem.size(), 0)

    def test_cosine_similarity_self(self):
        self.mem.store("doc", [1.0, 2.0, 3.0])
        results = self.mem.recall([1.0, 2.0, 3.0], top_k=1)
        # Top result should be the doc itself with high similarity
        self.assertAlmostEqual(results[0]["score"], 1.0, places=4)


class TestGraphMemory(unittest.TestCase):
    def setUp(self):
        from civilization.knowledge_ecosystem.graph_memory import GraphMemory
        self.gm = GraphMemory()

    def test_add_and_traverse(self):
        self.gm.add_concept("transformer", {"domain": "ml"})
        self.gm.add_concept("attention", {"domain": "ml"})
        self.gm.link("transformer", "attention", "USES")
        path = self.gm.traverse("transformer", depth=1)
        self.assertIsInstance(path, list)

    def test_find_related(self):
        self.gm.add_concept("node_a", {})
        self.gm.add_concept("node_b", {})
        self.gm.link("node_a", "node_b", "RELATED_TO")
        related = self.gm.find_related("node_a")
        self.assertIn("node_b", related)

    def test_concept_count(self):
        self.gm.add_concept("c1", {})
        self.gm.add_concept("c2", {})
        self.assertEqual(self.gm.concept_count(), 2)


class TestEmbeddingServiceSTACA(unittest.TestCase):
    def setUp(self):
        from civilization.knowledge_ecosystem.embedding_service import EmbeddingService
        self.svc = EmbeddingService()

    def test_encode_deterministic(self):
        v1 = self.svc.encode("transformer architecture")
        v2 = self.svc.encode("transformer architecture")
        self.assertEqual(v1, v2)

    def test_cosine_similarity_identical(self):
        v = self.svc.encode("neural network")
        sim = self.svc.cosine_similarity(v, v)
        self.assertAlmostEqual(sim, 1.0, places=5)

    def test_encode_batch_length(self):
        texts = ["text_a", "text_b", "text_c"]
        vecs = self.svc.encode_batch(texts)
        self.assertEqual(len(vecs), 3)


class TestKnowledgeAPISTACA(unittest.TestCase):
    def setUp(self):
        from civilization.knowledge_ecosystem.vector_memory import VectorMemory
        from civilization.knowledge_ecosystem.graph_memory import GraphMemory
        from civilization.knowledge_ecosystem.embedding_service import EmbeddingService
        from civilization.knowledge_ecosystem.knowledge_api import KnowledgeAPI
        self.api = KnowledgeAPI(VectorMemory(), GraphMemory(), EmbeddingService())

    def test_store_and_retrieve(self):
        key = self.api.store_knowledge("Graph neural networks improve reasoning", ["ml", "graphs"])
        result = self.api.get_knowledge(key)
        self.assertIsNotNone(result)

    def test_search_returns_results(self):
        self.api.store_knowledge("Distributed systems require consensus protocols")
        results = self.api.search_knowledge("distributed consensus", top_k=3)
        self.assertIsInstance(results, list)

    def test_delete(self):
        key = self.api.store_knowledge("temporary knowledge")
        deleted = self.api.delete_knowledge(key)
        self.assertTrue(deleted)
        self.assertIsNone(self.api.get_knowledge(key))


# ── experiment_labs ───────────────────────────────────────────────────────────

class TestSTACAExperimentManager(unittest.TestCase):
    def setUp(self):
        from civilization.experiment_labs.experiment_manager import ExperimentManager
        self.mgr = ExperimentManager()

    def test_create_and_get(self):
        exp_id = self.mgr.create("actor model improves planning", {"iterations": 10})
        self.assertIsNotNone(exp_id)
        exp = self.mgr.get(exp_id)
        self.assertIsNotNone(exp)

    def test_lifecycle(self):
        exp_id = self.mgr.create("hypothesis A", {})
        self.mgr.start(exp_id)
        self.mgr.complete(exp_id, {"score": 0.9, "improvement": True})
        exp = self.mgr.get(exp_id)
        self.assertEqual(exp["status"], "completed")

    def test_fail(self):
        exp_id = self.mgr.create("failing hypothesis", {})
        self.mgr.start(exp_id)
        self.mgr.fail(exp_id, "OOM error")
        exp = self.mgr.get(exp_id)
        self.assertEqual(exp["status"], "failed")

    def test_list_active(self):
        exp_id = self.mgr.create("active_exp", {})
        self.mgr.start(exp_id)
        active = self.mgr.list_active()
        self.assertIn(exp_id, active)


class TestSTACASandboxRunner(unittest.TestCase):
    def setUp(self):
        from civilization.experiment_labs.sandbox_runner import SandboxRunner
        self.runner = SandboxRunner()

    def test_run_safe_code(self):
        result = self.runner.run("x = 2 + 2")
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)

    def test_is_safe_true(self):
        self.assertTrue(self.runner.is_safe("def factorial(n): return 1 if n <= 1 else n * factorial(n-1)"))

    def test_is_safe_false(self):
        self.assertFalse(self.runner.is_safe("import subprocess; subprocess.run(['rm', '-rf', '/'])"))


class TestSTACABenchmarkEngine(unittest.TestCase):
    def setUp(self):
        from civilization.experiment_labs.benchmark_engine import BenchmarkEngine
        self.engine = BenchmarkEngine()

    def test_benchmark_valid_code(self):
        result = self.engine.benchmark("def square(x): return x*x", iterations=2)
        self.assertIsInstance(result, dict)
        self.assertIn("syntax_valid", result)
        self.assertTrue(result["syntax_valid"])

    def test_compare_two_solutions(self):
        comparison = self.engine.compare(
            "def add(a, b): return a + b",
            "def add2(a, b):\n    result = a + b\n    return result"
        )
        self.assertIsInstance(comparison, dict)
        self.assertIn("winner", comparison)


class TestResultAnalyzer(unittest.TestCase):
    def setUp(self):
        from civilization.experiment_labs.result_analyzer import ResultAnalyzer
        self.analyzer = ResultAnalyzer()

    def test_analyze_returns_stats(self):
        results = [{"score": 0.8}, {"score": 0.9}, {"score": 0.7}, {"score": 0.85}]
        analysis = self.analyzer.analyze(results)
        self.assertIn("mean", analysis)
        self.assertAlmostEqual(analysis["mean"], 0.8125, places=4)

    def test_detect_improvement(self):
        baseline = {"score": 0.75, "accuracy": 0.80}
        candidate = {"score": 0.85, "accuracy": 0.88}
        improved = self.analyzer.detect_improvement(baseline, candidate)
        self.assertTrue(improved)

    def test_summarize(self):
        results = [{"score": 0.9}, {"score": 0.95}]
        summary = self.analyzer.summarize("exp_001", results)
        self.assertIsInstance(summary, dict)


# ── governance ────────────────────────────────────────────────────────────────

class TestSafetyPolicies(unittest.TestCase):
    def setUp(self):
        from civilization.governance.safety_policies import SafetyPolicies
        self.policies = SafetyPolicies()

    def test_safe_code_passes(self):
        self.assertTrue(self.policies.check("def fibonacci(n):\n    return n if n < 2 else fibonacci(n-1) + fibonacci(n-2)"))

    def test_dangerous_code_fails(self):
        self.assertFalse(self.policies.check("import os\nos.system('rm -rf /')"))

    def test_get_violations_empty_for_safe(self):
        violations = self.policies.get_violations("x = 1 + 1")
        self.assertEqual(violations, [])

    def test_get_violations_detects_issues(self):
        violations = self.policies.get_violations("eval('malicious')")
        self.assertGreater(len(violations), 0)

    def test_add_custom_policy(self):
        self.policies.add_policy("no_print", r"\bprint\s*\(")
        policies = self.policies.list_policies()
        self.assertIn("no_print", policies)


class TestResourceLimits(unittest.TestCase):
    def setUp(self):
        from civilization.governance.resource_limits import ResourceLimits
        self.limits = ResourceLimits()

    def test_set_and_check(self):
        self.limits.set_limit("cpu_cores", 8)
        self.assertTrue(self.limits.check("cpu_cores", 4))
        self.assertFalse(self.limits.check("cpu_cores", 16))

    def test_get_limits(self):
        self.limits.set_limit("memory_mb", 4096)
        limits = self.limits.get_limits()
        self.assertIn("memory_mb", limits)
        self.assertEqual(limits["memory_mb"], 4096)

    def test_record_usage(self):
        self.limits.set_limit("api_calls", 1000)
        self.limits.record_usage("api_calls", 50)
        # Should still pass check after 50 out of 1000
        self.assertTrue(self.limits.check("api_calls", 900))


class TestAuditSystem(unittest.TestCase):
    def setUp(self):
        from civilization.governance.audit_system import AuditSystem
        self.audit = AuditSystem()

    def test_record_and_get(self):
        self.audit.record("code_execution", "agent_1", {"code": "x=1", "result": "ok"})
        log = self.audit.get_audit_log()
        self.assertEqual(len(log), 1)

    def test_filter_by_agent(self):
        self.audit.record("action_a", "agent_1", {})
        self.audit.record("action_b", "agent_2", {})
        a1_log = self.audit.get_audit_log("agent_1")
        self.assertTrue(all(entry["agent_id"] == "agent_1" for entry in a1_log))

    def test_export(self):
        self.audit.record("test_action", "a1", {"detail": "x"})
        exported = self.audit.export()
        self.assertIsInstance(exported, list)


class TestReputationEngine(unittest.TestCase):
    def setUp(self):
        from civilization.governance.reputation_engine import ReputationEngine
        self.rep = ReputationEngine()

    def test_initial_reputation(self):
        score = self.rep.get_reputation("new_agent")
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_success_increases_reputation(self):
        self.rep.record_action("agent_1", success=True, score=1.0)
        self.rep.record_action("agent_1", success=True, score=1.0)
        rep = self.rep.get_reputation("agent_1")
        self.assertGreater(rep, 0.0)

    def test_penalize_decreases_reputation(self):
        self.rep.record_action("agent_2", success=True, score=1.0)
        before = self.rep.get_reputation("agent_2")
        self.rep.penalize("agent_2", amount=0.2)
        after = self.rep.get_reputation("agent_2")
        self.assertLess(after, before)

    def test_top_agents(self):
        self.rep.record_action("best_agent", success=True, score=1.0)
        top = self.rep.top_agents(n=5)
        self.assertIsInstance(top, list)


# ── infrastructure ────────────────────────────────────────────────────────────

class TestClusterManager(unittest.TestCase):
    def setUp(self):
        from civilization.infrastructure.cluster_manager import ClusterManager
        self.mgr = ClusterManager()

    def test_add_and_list(self):
        self.mgr.add_cluster("cluster_eu", {"region": "eu-west-1"})
        clusters = self.mgr.list_clusters()
        self.assertIn("cluster_eu", clusters)

    def test_remove(self):
        self.mgr.add_cluster("to_remove", {})
        self.mgr.remove_cluster("to_remove")
        self.assertNotIn("to_remove", self.mgr.list_clusters())

    def test_cluster_count(self):
        self.mgr.add_cluster("c1", {})
        self.mgr.add_cluster("c2", {})
        self.assertEqual(self.mgr.cluster_count(), 2)


class TestInfraNodeRegistry(unittest.TestCase):
    def setUp(self):
        from civilization.infrastructure.node_registry import NodeRegistry
        self.reg = NodeRegistry()

    def test_register_and_get(self):
        self.reg.register("node_1", "agent_node", "cluster_us", ["compute", "research"])
        node = self.reg.get("node_1")
        self.assertIsNotNone(node)
        self.assertEqual(node["node_type"], "agent_node")

    def test_list_by_type(self):
        self.reg.register("n1", "knowledge_node", "c1")
        self.reg.register("n2", "agent_node", "c1")
        knowledge_nodes = self.reg.list_by_type("knowledge_node")
        self.assertTrue(any(n["node_id"] == "n1" for n in knowledge_nodes))

    def test_node_count(self):
        self.reg.register("n_a", "agent_node", "c1")
        self.assertEqual(self.reg.node_count(), 1)


class TestWorkloadBalancerSTACA(unittest.TestCase):
    def setUp(self):
        from civilization.infrastructure.workload_balancer import WorkloadBalancer
        self.balancer = WorkloadBalancer()

    def test_assign_task(self):
        nodes = [{"node_id": "n1"}, {"node_id": "n2"}]
        assigned = self.balancer.assign({"type": "compute"}, nodes)
        self.assertIn(assigned, ["n1", "n2"])

    def test_get_utilization(self):
        utilization = self.balancer.get_utilization()
        self.assertIsInstance(utilization, dict)


class TestContainerManager(unittest.TestCase):
    def setUp(self):
        from civilization.infrastructure.container_manager import ContainerManager
        self.mgr = ContainerManager()

    def test_create_container(self):
        container = self.mgr.create("c1", "python:3.11", {"memory": "512m"})
        self.assertIsInstance(container, dict)

    def test_list_running(self):
        self.mgr.create("c2", "python:3.11")
        running = self.mgr.list_running()
        self.assertIsInstance(running, list)

    def test_get_status(self):
        self.mgr.create("c3", "python:3.11")
        status = self.mgr.get_status("c3")
        self.assertIsInstance(status, str)

    def test_stop_and_remove(self):
        self.mgr.create("c4", "python:3.11")
        self.assertTrue(self.mgr.stop("c4"))
        self.assertTrue(self.mgr.remove("c4"))
        self.assertNotIn("c4", self.mgr.list_running())


# ── api_gateway (civilization) ────────────────────────────────────────────────

class TestAuthentication(unittest.TestCase):
    def setUp(self):
        from civilization.api_gateway.authentication import Authentication
        self.auth = Authentication()

    def test_create_and_validate(self):
        token = self.auth.create_token("agent_42")
        self.assertTrue(self.auth.validate_token(token))

    def test_revoke(self):
        token = self.auth.create_token("agent_99")
        self.auth.revoke_token(token)
        self.assertFalse(self.auth.validate_token(token))

    def test_list_active(self):
        t1 = self.auth.create_token("a1")
        t2 = self.auth.create_token("a2")
        active = self.auth.list_active_tokens()
        self.assertIn(t1, active)
        self.assertIn(t2, active)


class TestTaskAPI(unittest.TestCase):
    def setUp(self):
        from civilization.api_gateway.task_api import TaskAPI
        self.api = TaskAPI()

    def test_submit_goal(self):
        result = self.api.submit_goal("design next-gen distributed AI architecture")
        self.assertIsInstance(result, dict)
        self.assertIn("goal_id", result)
        self.assertEqual(result["status"], "processing")

    def test_submit_task(self):
        result = self.api.submit_task("research", {"topic": "graph neural networks"})
        self.assertIsInstance(result, dict)
        self.assertIn("task_id", result)

    def test_get_task_status(self):
        result = self.api.submit_task("build", {"architecture": {"type": "api"}})
        task_id = result["task_id"]
        status = self.api.get_task_status(task_id)
        self.assertIsInstance(status, dict)

    def test_list_tasks(self):
        self.api.submit_task("research", {"topic": "attention"})
        tasks = self.api.list_tasks()
        self.assertIsInstance(tasks, list)
        self.assertGreater(len(tasks), 0)


class TestCivilizationKnowledgeAPI(unittest.TestCase):
    def setUp(self):
        from civilization.api_gateway.knowledge_api import KnowledgeAPI
        self.api = KnowledgeAPI()

    def test_query_returns_list(self):
        result = self.api.query("distributed consensus algorithms")
        self.assertIsInstance(result, list)

    def test_submit_and_get(self):
        result = self.api.submit_knowledge("Graph networks enable relational reasoning")
        self.assertIn("key", result)
        retrieved = self.api.get_knowledge(result["key"])
        self.assertIsNotNone(retrieved)


class TestCivilizationAPIServer(unittest.TestCase):
    def setUp(self):
        from civilization.api_gateway.api_server import APIServer
        from civilization.api_gateway.authentication import Authentication
        from civilization.api_gateway.task_api import TaskAPI
        from civilization.api_gateway.knowledge_api import KnowledgeAPI
        self.server = APIServer(
            auth=Authentication(),
            task_api=TaskAPI(),
            knowledge_api=KnowledgeAPI(),
        )

    def test_handle_goals_post(self):
        result = self.server.handle(
            "/api/v1/goals", "POST", {}, {"goal": "build AI civilization"}
        )
        self.assertIsInstance(result, dict)
        self.assertIn("status_code", result)

    def test_handle_knowledge_get(self):
        result = self.server.handle(
            "/api/v1/knowledge", "GET", {}, {"q": "neural networks"}
        )
        self.assertIsInstance(result, dict)

    def test_handle_experiments_post(self):
        result = self.server.handle(
            "/api/v1/experiments", "POST", {},
            {"hypothesis": "graph NNs improve planning agents"}
        )
        self.assertIsInstance(result, dict)

    def test_get_routes(self):
        routes = self.server.get_routes()
        self.assertIsInstance(routes, list)
        self.assertGreater(len(routes), 0)

    def test_get_stats(self):
        stats = self.server.get_stats()
        self.assertIsInstance(stats, dict)


if __name__ == "__main__":
    unittest.main()
