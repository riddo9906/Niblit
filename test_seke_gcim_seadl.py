#!/usr/bin/env python3
"""
Tests for the three new SEKE/GCIM/SEADL subsystems.
"""

import os
import sys
import tempfile
import textwrap
import time
import unittest

# ── Ensure repo root is on path ───────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# =============================================================================
# SEKE — Self-Expanding Knowledge Engine
# =============================================================================

class TestCodeParser(unittest.TestCase):
    def setUp(self):
        from modules.knowledge_engine.code_parser import CodeParser
        self.parser = CodeParser()

    def test_parse_simple_file(self):
        code = textwrap.dedent("""\
            \"\"\"Module docstring.\"\"\"
            import os

            def hello(name: str) -> str:
                \"\"\"Return greeting.\"\"\"
                return f"hello {name}"

            class Greeter:
                def greet(self): ...
        """)
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as fh:
            fh.write(code)
            path = fh.name
        try:
            result = self.parser.parse_file(path)
            self.assertIsNone(result["error"])
            self.assertEqual(result["docstring"], "Module docstring.")
            func_names = [f["name"] for f in result["functions"]]
            self.assertIn("hello", func_names)
            class_names = [c["name"] for c in result["classes"]]
            self.assertIn("Greeter", class_names)
            self.assertIn("os", result["imports"])
        finally:
            os.unlink(path)

    def test_parse_syntax_error(self):
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as fh:
            fh.write("def broken(:\n    pass\n")
            path = fh.name
        try:
            result = self.parser.parse_file(path)
            self.assertIsNotNone(result["error"])
            self.assertIn("SyntaxError", result["error"])
        finally:
            os.unlink(path)

    def test_extract_snippets(self):
        code = textwrap.dedent("""\
            def foo():
                pass
            class Bar:
                pass
        """)
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as fh:
            fh.write(code)
            path = fh.name
        try:
            snippets = self.parser.extract_snippets(path)
            kinds = {s["kind"] for s in snippets}
            self.assertIn("function", kinds)
            self.assertIn("class", kinds)
        finally:
            os.unlink(path)


class TestPatternExtractor(unittest.TestCase):
    def setUp(self):
        from modules.knowledge_engine.pattern_extractor import PatternExtractor
        self.extractor = PatternExtractor()

    def test_singleton_detection(self):
        result = {
            "path": "test.py",
            "functions": [{"name": "get_instance"}],
            "classes": [{"name": "Logger", "methods": ["get_instance"]}],
            "imports": [],
        }
        patterns = self.extractor.detect_patterns(result)
        names = [p["pattern"] for p in patterns]
        self.assertIn("singleton", names)

    def test_observer_detection(self):
        result = {
            "path": "test.py",
            "functions": [{"name": "subscribe"}, {"name": "notify"}],
            "classes": [],
            "imports": [],
        }
        patterns = self.extractor.detect_patterns(result)
        names = [p["pattern"] for p in patterns]
        self.assertIn("observer", names)

    def test_context_manager_detection(self):
        result = {
            "path": "test.py",
            "functions": [{"name": "__enter__"}, {"name": "__exit__"}],
            "classes": [],
            "imports": [],
        }
        patterns = self.extractor.detect_patterns(result)
        names = [p["pattern"] for p in patterns]
        self.assertIn("context_manager", names)

    def test_analyse_directory_patterns(self):
        results = [
            {"path": "a.py", "functions": [{"name": "get_instance"}],
             "classes": [], "imports": []},
            {"path": "b.py", "functions": [{"name": "__enter__"}, {"name": "__exit__"}],
             "classes": [], "imports": []},
        ]
        counts = self.extractor.analyse_directory_patterns(results)
        self.assertIsInstance(counts, dict)
        self.assertGreater(len(counts), 0)


class TestArchitectureAnalyzer(unittest.TestCase):
    def setUp(self):
        from modules.knowledge_engine.architecture_analyzer import ArchitectureAnalyzer
        self.analyzer = ArchitectureAnalyzer()

    def test_mvc_detection(self):
        with tempfile.TemporaryDirectory() as d:
            for sub in ["controllers", "models", "views"]:
                os.makedirs(os.path.join(d, sub))
            result = self.analyzer.analyze(d)
            self.assertEqual(result["architecture"], "mvc")
            self.assertIn("confidence", result)

    def test_layered_detection(self):
        with tempfile.TemporaryDirectory() as d:
            for sub in ["api", "service", "repository"]:
                os.makedirs(os.path.join(d, sub))
            result = self.analyzer.analyze(d)
            self.assertEqual(result["architecture"], "layered")

    def test_unknown_for_nonexistent(self):
        result = self.analyzer.analyze("/tmp/nonexistent_seke_dir_xyz")
        self.assertEqual(result["architecture"], "unknown")

    def test_architecture_template(self):
        template = self.analyzer.architecture_template("mvc")
        self.assertIn("controller", template)


class TestKnowledgeGraphBuilder(unittest.TestCase):
    def setUp(self):
        from modules.knowledge_engine.knowledge_graph_builder import KnowledgeGraphBuilder
        self.kg = KnowledgeGraphBuilder()

    def test_add_and_query_edge(self):
        self.kg.add_edge("FastAPI", "Python", "uses_language")
        nbrs = self.kg.neighbors("FastAPI")
        targets = [n["target"] for n in nbrs]
        self.assertIn("Python", targets)

    def test_path_finding(self):
        self.kg.add_edge("A", "B", "related")
        self.kg.add_edge("B", "C", "related")
        path = self.kg.path("A", "C")
        self.assertEqual(path[0], "A")
        self.assertEqual(path[-1], "C")

    def test_bulk_add(self):
        edges = [("X", "Y", "r1"), ("Y", "Z", "r2"), ("Z", "W", "r3")]
        self.kg.add_edges_bulk(edges)
        summary = self.kg.summary()
        self.assertGreaterEqual(summary["edges"], 3)

    def test_related_concepts(self):
        self.kg.add_edge("P", "Q", "rel")
        self.kg.add_edge("Q", "R", "rel")
        related = self.kg.related_concepts("P", depth=2)
        self.assertIn("Q", related)
        self.assertIn("R", related)


class TestEmbeddingPipeline(unittest.TestCase):
    def setUp(self):
        from modules.knowledge_engine.embedding_pipeline import EmbeddingPipeline
        self.pipeline = EmbeddingPipeline()

    def test_ingest_snippet(self):
        ids = self.pipeline.ingest_snippet("test_func", "def foo(): pass")
        self.assertIsInstance(ids, list)
        self.assertGreater(len(ids), 0)

    def test_ingest_parse_result(self):
        result = {
            "path": "test.py",
            "functions": [{"name": "bar", "docstring": "Does bar."}],
            "classes": [{"name": "Baz", "methods": ["run"], "docstring": ""}],
        }
        count = self.pipeline.ingest_parse_result(result)
        self.assertEqual(count, 2)

    def test_search_returns_list(self):
        self.pipeline.ingest_snippet("search_test", "async def handler(): pass")
        results = self.pipeline.search("async handler", top_k=3)
        self.assertIsInstance(results, list)


class TestLearningScheduler(unittest.TestCase):
    def test_instantiation(self):
        from modules.knowledge_engine.learning_scheduler import LearningScheduler
        scheduler = LearningScheduler()
        self.assertIsNotNone(scheduler)
        self.assertIsNotNone(scheduler.graph)

    def test_stats_initial(self):
        from modules.knowledge_engine.learning_scheduler import LearningScheduler
        scheduler = LearningScheduler()
        stats = scheduler.stats()
        self.assertEqual(stats["cycles_completed"], 0)
        self.assertEqual(stats["total_repos_processed"], 0)


# =============================================================================
# GCIM — Global Code Intelligence Map
# =============================================================================

class TestDependencyMapper(unittest.TestCase):
    def setUp(self):
        from modules.global_code_intelligence.dependency_mapper import DependencyMapper
        self.mapper = DependencyMapper()

    def test_add_and_retrieve_deps(self):
        self.mapper.add_package_deps("fastapi", ["starlette>=0.27", "pydantic>=2.0"])
        deps = self.mapper.get_direct_deps("fastapi")
        self.assertIn("starlette", deps)
        self.assertIn("pydantic", deps)

    def test_dependency_tree(self):
        self.mapper.add_package_deps("a", ["b", "c"])
        self.mapper.add_package_deps("b", ["d"])
        tree = self.mapper.get_dependency_tree("a", depth=2)
        self.assertEqual(tree["package"], "a")
        children = [c["package"] for c in tree["deps"]]
        self.assertIn("b", children)

    def test_most_depended_on(self):
        self.mapper.add_package_deps("x", ["common"])
        self.mapper.add_package_deps("y", ["common"])
        self.mapper.add_package_deps("z", ["common"])
        top = self.mapper.most_depended_on(top_n=3)
        self.assertEqual(top[0][0], "common")
        self.assertEqual(top[0][1], 3)

    def test_from_imports(self):
        self.mapper.add_from_imports("myapp", ["requests", "flask", "sqlalchemy"])
        deps = self.mapper.get_direct_deps("myapp")
        self.assertIn("requests", deps)


class TestArchitectureDetector(unittest.TestCase):
    def setUp(self):
        from modules.global_code_intelligence.architecture_detector import ArchitectureDetector
        self.detector = ArchitectureDetector()

    def test_structure_mvc(self):
        arch, conf = self.detector.detect_from_structure(["controllers", "models", "views"])
        self.assertEqual(arch, "mvc")
        self.assertGreater(conf, 0.0)

    def test_topics_event_driven(self):
        arch, conf = self.detector.detect_from_topics(["kafka", "event-driven"])
        self.assertEqual(arch, "event_driven")

    def test_imports_plugin(self):
        arch, conf = self.detector.detect_from_imports(["pluggy", "stevedore"])
        self.assertEqual(arch, "plugin")

    def test_combined_returns_dict(self):
        result = self.detector.detect_combined(
            folder_names=["api", "service"],
            topics=["microservices"],
        )
        self.assertIn("architecture", result)
        self.assertIn("confidence", result)
        self.assertIn("method", result)

    def test_describe(self):
        desc = self.detector.describe("mvc")
        self.assertIn("Model", desc)


class TestPatternGraphBuilder(unittest.TestCase):
    def setUp(self):
        from modules.global_code_intelligence.pattern_graph_builder import PatternGraphBuilder
        self.pgb = PatternGraphBuilder()

    def test_seed_world_model(self):
        count = self.pgb.seed_world_model()
        self.assertGreater(count, 10)

    def test_add_repo_knowledge(self):
        repos = [
            {"name": "myrepo/fastapi-app", "language": "Python",
             "domain": "web_api", "topics": ["fastapi", "async"]},
        ]
        added = self.pgb.add_repo_knowledge(repos)
        self.assertGreater(added, 0)

    def test_find_architectures(self):
        self.pgb.seed_world_model()
        archs = self.pgb.find_architectures_for("build a REST API service")
        self.assertIsInstance(archs, list)
        self.assertGreater(len(archs), 0)

    def test_find_frameworks_by_language(self):
        self.pgb.seed_world_model()
        frameworks = self.pgb.find_frameworks_by_language("Python")
        self.assertIn("FastAPI", frameworks)


class TestCodeEmbeddingIndex(unittest.TestCase):
    def setUp(self):
        from modules.global_code_intelligence.code_embedding_index import CodeEmbeddingIndex
        self.idx = CodeEmbeddingIndex()

    def test_add_and_search(self):
        self.idx.add_snippet("test", "from fastapi import FastAPI", lang="python")
        results = self.idx.search("FastAPI web framework", top_k=3)
        self.assertIsInstance(results, list)

    def test_add_repo_records(self):
        records = [
            {"name": "torchvision", "source": "github", "language": "python",
             "domain": "machine_learning", "topics": ["pytorch", "vision"], "stars": 10000},
        ]
        count = self.idx.add_repo_records(records)
        self.assertGreater(count, 0)


class TestKnowledgeReasoner(unittest.TestCase):
    def setUp(self):
        from modules.global_code_intelligence.pattern_graph_builder import PatternGraphBuilder
        from modules.global_code_intelligence.code_embedding_index import CodeEmbeddingIndex
        from modules.global_code_intelligence.knowledge_reasoner import KnowledgeReasoner
        pgb = PatternGraphBuilder()
        pgb.seed_world_model()
        idx = CodeEmbeddingIndex()
        idx.add_snippet("fastapi", "from fastapi import FastAPI, APIRouter")
        self.reasoner = KnowledgeReasoner(graph=pgb, index=idx)

    def test_answer_returns_dict(self):
        result = self.reasoner.answer("real-time chat system")
        self.assertIn("architectures", result)
        self.assertIn("explanation", result)
        self.assertIsInstance(result["architectures"], list)

    def test_augment_prompt(self):
        augmented = self.reasoner.augment_prompt("Write a web server", "REST API")
        self.assertIn("Write a web server", augmented)


class TestGCIMDiscoveryEngine(unittest.TestCase):
    def setUp(self):
        from modules.global_code_intelligence.discovery_engine import DiscoveryEngine
        self.engine = DiscoveryEngine()

    def test_record_and_trend(self):
        records_v1 = [
            {"topics": ["rust", "async"], "language": "rust", "domain": "systems", "stars": 500},
            {"topics": ["rust", "async"], "language": "rust", "domain": "systems", "stars": 300},
        ]
        records_v2 = [
            {"topics": ["rust", "async"], "language": "rust", "domain": "systems", "stars": 2000},
            {"topics": ["rust", "async"], "language": "rust", "domain": "systems", "stars": 1500},
        ]
        self.engine.record_snapshot(records_v1)
        self.engine.record_snapshot(records_v2)
        trends = self.engine.detect_trends(min_velocity=0.1)
        self.assertIsInstance(trends, list)

    def test_detect_breakthroughs(self):
        results = [{"performance": 0.9}, {"performance": 0.3}]
        discovery = self.engine.detect_breakthroughs(results, threshold=0.7)
        self.assertIsNotNone(discovery)
        self.assertEqual(discovery["type"], "breakthrough")


class TestEcosystemScanner(unittest.TestCase):
    def setUp(self):
        from modules.global_code_intelligence.ecosystem_scanner import EcosystemScanner
        self.scanner = EcosystemScanner()

    def test_normalise_npm(self):
        from modules.global_code_intelligence.ecosystem_scanner import EcosystemScanner
        pkg = {"name": "express", "links": {"npm": "https://npmjs.com/package/express"},
               "keywords": ["web", "framework"]}
        record = EcosystemScanner._normalise_npm(pkg)
        self.assertEqual(record["name"], "express")
        self.assertEqual(record["source"], "npm")

    def test_infer_domain_web(self):
        domain = self.scanner._infer_domain("fastapi REST api web framework")
        self.assertEqual(domain, "web_api")


# =============================================================================
# SEADL — Self-Evolving AI Dev Lab
# =============================================================================

class TestSafetyGuard(unittest.TestCase):
    def setUp(self):
        from modules.ai_dev_lab.safety_guard import SafetyGuard
        self.guard = SafetyGuard()

    def test_safe_code_passes(self):
        code = "def add(a, b): return a + b"
        self.assertTrue(self.guard.validate(code))

    def test_os_system_blocked(self):
        code = "import os; os.system('rm -rf /')"
        with self.assertRaises(ValueError):
            self.guard.validate(code)

    def test_eval_blocked(self):
        code = "result = eval('1+1')"
        with self.assertRaises(ValueError):
            self.guard.validate(code)

    def test_exec_blocked(self):
        code = "exec('print(1)')"
        with self.assertRaises(ValueError):
            self.guard.validate(code)

    def test_is_safe_returns_bool(self):
        self.assertTrue(self.guard.is_safe("x = 1 + 2"))
        self.assertFalse(self.guard.is_safe("eval('x')"))

    def test_audit(self):
        report = self.guard.audit("def foo(): return 42")
        self.assertIn("safe", report)
        self.assertIn("warnings", report)


class TestBenchmarkEngine(unittest.TestCase):
    def setUp(self):
        from modules.ai_dev_lab.benchmark_engine import BenchmarkEngine
        self.engine = BenchmarkEngine()

    def test_evaluate_valid_code(self):
        code = "def greet(name): return f'Hello {name}'"
        result = self.engine.evaluate(code)
        self.assertTrue(result["syntax_valid"])
        self.assertGreater(result["performance"], 0.0)

    def test_evaluate_syntax_error(self):
        code = "def bad(:"
        result = self.engine.evaluate(code)
        self.assertFalse(result["syntax_valid"])
        self.assertEqual(result["performance"], 0.0)

    def test_test_cases(self):
        code = "def add(a, b): return a + b"
        tests = [{"function": "add", "args": [2, 3], "expected": 5}]
        result = self.engine.evaluate(code, test_cases=tests)
        self.assertTrue(result["test_results"][0]["passed"])

    def test_quality_score_range(self):
        code = 'class Foo:\n    """Docstring."""\n    def run(self) -> None:\n        pass\n'
        result = self.engine.evaluate(code)
        self.assertGreaterEqual(result["quality_score"], 0.0)
        self.assertLessEqual(result["quality_score"], 1.0)


class TestHypothesisGenerator(unittest.TestCase):
    def setUp(self):
        from modules.ai_dev_lab.hypothesis_generator import HypothesisGenerator
        self.gen = HypothesisGenerator(seed=42)

    def test_generate_returns_dict(self):
        h = self.gen.generate()
        self.assertIn("hypothesis", h)
        self.assertIn("tech_a", h)
        self.assertIn("domain", h)
        self.assertIsInstance(h["hypothesis"], str)
        self.assertGreater(len(h["hypothesis"]), 10)

    def test_generate_batch(self):
        hypotheses = self.gen.generate_batch(3)
        self.assertEqual(len(hypotheses), 3)
        texts = [h["hypothesis"] for h in hypotheses]
        self.assertEqual(len(texts), len(set(texts)))  # all unique

    def test_generate_from_weakness(self):
        h = self.gen.generate_from_weakness("memory retrieval is slow")
        self.assertIn("hypothesis", h)


class TestArchitectureDesigner(unittest.TestCase):
    def setUp(self):
        from modules.ai_dev_lab.architecture_designer import ArchitectureDesigner
        self.designer = ArchitectureDesigner()

    def test_design_returns_spec(self):
        hypothesis = {"hypothesis": "actor model for planning agent",
                      "tech_a": "actor model", "tech_b": "attention", "domain": "planning"}
        spec = self.designer.design(hypothesis)
        self.assertIn("name", spec)
        self.assertIn("components", spec)
        self.assertIsInstance(spec["components"], list)

    def test_list_architectures(self):
        archs = self.designer.list_architectures()
        self.assertGreater(len(archs), 2)

    def test_design_custom(self):
        spec = self.designer.design_custom(["ingestion", "transform", "output"])
        self.assertEqual(spec["name"], "custom")
        self.assertEqual(len(spec["components"]), 3)


class TestAlgorithmInventor(unittest.TestCase):
    def setUp(self):
        from modules.ai_dev_lab.algorithm_inventor import AlgorithmInventor
        self.inventor = AlgorithmInventor(seed=0)

    def test_invent_returns_dict(self):
        algo = self.inventor.invent("improve graph search performance")
        self.assertIn("name", algo)
        self.assertIn("description", algo)
        self.assertIn("components", algo)
        self.assertGreater(len(algo["components"]), 0)

    def test_combine_two(self):
        algo = self.inventor.combine(["binary_search", "attention"])
        self.assertIn("binary_search", algo["name"])
        self.assertIn("attention", algo["name"])

    def test_list_algorithms(self):
        algos = self.inventor.list_algorithms()
        self.assertIn("attention", algos)
        self.assertIn("bfs", algos)

    def test_algorithms_by_type(self):
        search_algos = self.inventor.algorithms_by_type("search")
        self.assertIn("binary_search", search_algos)


class TestCodeSynthesizer(unittest.TestCase):
    def setUp(self):
        from modules.ai_dev_lab.code_synthesizer import CodeSynthesizer
        self.synth = CodeSynthesizer()

    def test_generate_pipeline(self):
        arch = {"name": "pipeline", "description": "data pipeline",
                "components": ["ingestion", "transform"], "patterns": ["pipeline"]}
        result = self.synth.generate(arch)
        self.assertIn("code", result)
        self.assertIn("class", result["code"])

    def test_generate_event_driven(self):
        arch = {"name": "event_driven", "description": "event bus",
                "components": ["producer", "consumer"], "patterns": ["event_driven"]}
        result = self.synth.generate(arch)
        self.assertIn("EventBus", result["code"])

    def test_safe_flag_present(self):
        arch = {"name": "default", "description": "test", "components": [], "patterns": []}
        result = self.synth.generate(arch)
        self.assertIn("safe", result)


class TestExperimentDatabase(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.db_path = os.path.join(tempfile.mkdtemp(), "test_exp.db")
        from modules.ai_dev_lab.experiment_database import ExperimentDatabase
        self.db = ExperimentDatabase(db_path=self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_store_and_retrieve(self):
        h = {"hypothesis": "test hypothesis"}
        a = {"name": "pipeline"}
        row_id = self.db.store(h, a, code="x = 1", benchmark_results={"performance": 0.7})
        self.assertGreater(row_id, 0)
        recent = self.db.recent(limit=5)
        self.assertEqual(len(recent), 1)

    def test_best(self):
        for perf in [0.3, 0.9, 0.5]:
            self.db.store({}, {}, benchmark_results={"performance": perf})
        best = self.db.best(top_n=1)
        self.assertAlmostEqual(best[0]["performance_score"], 0.9)

    def test_count(self):
        self.assertEqual(self.db.count(), 0)
        self.db.store({}, {})
        self.assertEqual(self.db.count(), 1)


class TestDiscoveryEngine(unittest.TestCase):
    def setUp(self):
        from modules.ai_dev_lab.discovery_engine import DiscoveryEngine
        self.engine = DiscoveryEngine(threshold=0.7)

    def test_no_discovery_below_threshold(self):
        result = self.engine.detect({"performance": 0.5})
        self.assertIsNone(result)

    def test_threshold_exceeded(self):
        result = self.engine.detect({"performance": 0.8})
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "threshold_exceeded")

    def test_breakthrough_on_improvement(self):
        self.engine.set_baseline(0.5)
        result = self.engine.detect({"performance": 0.75})
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "breakthrough")

    def test_stats(self):
        stats = self.engine.stats()
        self.assertIn("threshold", stats)
        self.assertIn("baseline", stats)


class TestExperimentManager(unittest.TestCase):
    def setUp(self):
        from modules.ai_dev_lab.experiment_manager import ExperimentManager
        self.mgr = ExperimentManager()

    def test_create_and_complete(self):
        h = {"hypothesis": "test"}
        a = {"name": "pipeline"}
        exp_id = self.mgr.create(h, a)
        self.mgr.start(exp_id)
        self.mgr.complete(exp_id, code="x=1", benchmark_results={"performance": 0.6})
        exp = self.mgr.get(exp_id)
        self.assertEqual(exp["status"], "completed")

    def test_fail(self):
        exp_id = self.mgr.create({}, {})
        self.mgr.fail(exp_id, error="test error")
        exp = self.mgr.get(exp_id)
        self.assertEqual(exp["status"], "failed")

    def test_stats(self):
        stats = self.mgr.stats()
        self.assertIn("total", stats)


class TestAIDevLab(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.db_path = os.path.join(tempfile.mkdtemp(), "lab_test.db")
        from modules.ai_dev_lab.lab_controller import AIDevLab
        self.lab = AIDevLab(db_path=self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_run_cycle_returns_dict(self):
        result = self.lab.run_cycle()
        self.assertIn("cycle", result)
        self.assertIn("hypothesis", result)
        self.assertIn("performance", result)
        self.assertEqual(result["cycle"], 1)

    def test_run_cycle_twice(self):
        r1 = self.lab.run_cycle()
        r2 = self.lab.run_cycle()
        self.assertEqual(r1["cycle"], 1)
        self.assertEqual(r2["cycle"], 2)

    def test_run_loop(self):
        results = self.lab.run_loop(max_cycles=3)
        self.assertEqual(len(results), 3)

    def test_stats(self):
        self.lab.run_cycle()
        stats = self.lab.stats()
        self.assertEqual(stats["cycles"], 1)
        self.assertGreaterEqual(stats["db_count"], 1)

    def test_generate_hypothesis(self):
        h = self.lab.generate_hypothesis()
        self.assertIn("hypothesis", h)


class TestEvolutionEngine(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.db_path = os.path.join(tempfile.mkdtemp(), "evo_test.db")
        from modules.ai_dev_lab.lab_controller import AIDevLab
        from modules.ai_dev_lab.evolution_engine import EvolutionEngine
        self.lab = AIDevLab(db_path=self.db_path)
        self.engine = EvolutionEngine(lab=self.lab, deploy=False)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_evolve_returns_dict(self):
        result = self.engine.evolve()
        self.assertIn("evolved", result)
        self.assertIn("performance", result)

    def test_stats(self):
        stats = self.engine.stats()
        self.assertIn("evolutions", stats)
        self.assertIn("baseline", stats)


class TestRepoDownloader(unittest.TestCase):
    def test_instantiation(self):
        from modules.knowledge_engine.repo_downloader import RepoDownloader
        dl = RepoDownloader()
        self.assertIsNotNone(dl)

    def test_list_cloned_empty(self):
        from modules.knowledge_engine.repo_downloader import RepoDownloader
        import tempfile
        dl = RepoDownloader(work_dir=tempfile.mkdtemp())
        self.assertEqual(dl.list_cloned(), [])


class TestRepoScanner(unittest.TestCase):
    def test_normalise(self):
        from modules.knowledge_engine.repo_scanner import RepoScanner
        item = {
            "full_name": "owner/repo",
            "description": "A test repo",
            "html_url": "https://github.com/owner/repo",
            "clone_url": "https://github.com/owner/repo.git",
            "stargazers_count": 500,
            "language": "Python",
            "topics": ["ai", "ml"],
            "pushed_at": "2024-01-01T00:00:00Z",
            "archived": False,
        }
        scanner = RepoScanner()
        normalised = scanner._normalise(item)
        self.assertEqual(normalised["stars"], 500)
        self.assertEqual(normalised["language"], "Python")
        self.assertFalse(normalised["archived"])

    def test_filter_archived(self):
        from modules.knowledge_engine.repo_scanner import RepoScanner
        scanner = RepoScanner()
        self.assertFalse(scanner._passes_filter({"archived": True, "stargazers_count": 1000}))

    def test_filter_low_stars(self):
        from modules.knowledge_engine.repo_scanner import RepoScanner
        scanner = RepoScanner(min_stars=100)
        self.assertFalse(scanner._passes_filter({"archived": False, "stargazers_count": 50}))


if __name__ == "__main__":
    unittest.main()
