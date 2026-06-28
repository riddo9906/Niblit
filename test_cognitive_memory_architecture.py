from __future__ import annotations

import os

from modules.memory_graph import MemoryGraph
from modules.cognitive_memory_layer import CognitiveMemoryLayer, MemoryRouter, ConceptObject
from modules.graph_scoring_engine import GraphScoringEngine
from modules.reasoning_engine import ReasoningEngine
from modules.cognitive_synthesis_engine import CognitiveSynthesisEngine
from core.runtime_manager import RuntimeManager
from niblit_memory import PersistenceManager


def test_semantic_ingestion_creates_structured_concepts(tmp_path):
    graph = MemoryGraph(persist_path=str(tmp_path / "graph.pkl"))
    layer = CognitiveMemoryLayer(memory_graph=graph)

    document = {
        "title": "Programming Languages",
        "text": "Programming languages use syntax and semantics to express computation.",
        "source": {"document": "intro.pdf", "section": "overview", "page": 1},
    }

    concepts = layer.ingest_document(document)

    assert concepts
    assert all(isinstance(entry, ConceptObject) for entry in concepts)
    assert any(entry.name.lower() == "programming language" for entry in concepts)
    assert all(entry.memory_type in {"semantic", "procedural", "episodic"} for entry in concepts)


def test_retrieval_filters_cross_domain_noise(tmp_path):
    graph = MemoryGraph(persist_path=str(tmp_path / "graph.pkl"))
    layer = CognitiveMemoryLayer(memory_graph=graph)

    layer.ingest_document({
        "title": "Drawing Basics",
        "text": "Shading and perspective are key drawing techniques for sketching objects.",
        "source": {"document": "art.pdf", "section": "drawing", "page": 3},
    })
    layer.ingest_document({
        "title": "Programming Languages",
        "text": "Programming languages use syntax and semantics to express computation.",
        "source": {"document": "intro.pdf", "section": "overview", "page": 1},
    })

    results = layer.retrieve("give me a concept of programming languages", top_k=3)

    assert results
    assert all("drawing" not in result["name"].lower() for result in results)
    assert any("programming" in result["name"].lower() or "syntax" in result["summary"].lower() for result in results)


def test_duplicate_ingestion_is_suppressed(tmp_path):
    graph = MemoryGraph(persist_path=str(tmp_path / "graph.pkl"))
    layer = CognitiveMemoryLayer(memory_graph=graph)

    doc = {
        "title": "Programming Languages",
        "text": "Programming languages use syntax and semantics to express computation.",
        "source": {"document": "intro.pdf", "section": "overview", "page": 1},
    }

    first = layer.ingest_document(doc)
    second = layer.ingest_document(doc)

    assert len(first) == len(second)
    assert len(first) == 1


def test_memory_router_routes_queries(tmp_path):
    router = MemoryRouter()

    assert router.route_query("give me a concept of programming languages") == "semantic"
    assert router.route_query("what did I do yesterday") == "episodic"
    assert router.route_query("how do I compile this program") == "procedural"


def test_response_synthesis_omits_internal_metadata(tmp_path):
    graph = MemoryGraph(persist_path=str(tmp_path / "graph.pkl"))
    layer = CognitiveMemoryLayer(memory_graph=graph)
    layer.ingest_document({
        "title": "Programming Languages",
        "text": "Programming languages use syntax and semantics to express computation.",
        "source": {"document": "intro.pdf", "section": "overview", "page": 1},
    })

    response = layer.synthesize_response("give me a concept of programming languages")

    assert "programming" in response.lower()
    assert "source" not in response.lower()
    assert "metadata" not in response.lower()


def test_graph_scoring_engine_ranks_multi_hop_support(tmp_path):
    graph = MemoryGraph(persist_path=str(tmp_path / "graph.pkl"))
    engine = GraphScoringEngine(memory_graph=graph)

    graph.add("prog", "Programming languages use syntax and semantics to express computation.", metadata={"confidence": 0.95, "authority": 0.9})
    graph.add("syntax", "Syntax defines the grammar of a programming language.", metadata={"confidence": 0.8, "authority": 0.7})
    graph.add("compiler", "A compiler translates source code into executable instructions.", metadata={"confidence": 0.7, "authority": 0.6})
    graph.link("prog", "syntax", 0.88, metadata={"strength": 0.88})
    graph.link("syntax", "compiler", 0.72, metadata={"strength": 0.72})

    ranked = engine.rank_candidates("give me a concept of programming languages", top_k=3)

    assert ranked
    assert ranked[0]["node_id"] == "prog"
    assert ranked[0]["final_score"] >= ranked[1]["final_score"]


def test_graph_scoring_suppresses_contradictions(tmp_path):
    graph = MemoryGraph(persist_path=str(tmp_path / "graph.pkl"))
    engine = GraphScoringEngine(memory_graph=graph)

    graph.add("prog", "Programming languages use syntax and semantics to express computation.", metadata={"confidence": 0.95, "authority": 0.9})
    graph.add("conflict", "Programming languages are not useful for computation.", metadata={"confidence": 0.4, "authority": 0.3})
    graph.link("prog", "conflict", 0.4, metadata={"strength": 0.4})

    ranked = engine.rank_candidates("give me a concept of programming languages", top_k=3)
    ranked_ids = [entry["node_id"] for entry in ranked]

    assert "prog" in ranked_ids
    assert "conflict" not in ranked_ids


def test_reasoning_engine_uses_ranked_graph_context(tmp_path):
    graph = MemoryGraph(persist_path=str(tmp_path / "graph.pkl"))
    engine = GraphScoringEngine(memory_graph=graph)
    reasoning = ReasoningEngine(memory_graph=graph, graph_scoring_engine=engine)

    graph.add("prog", "Programming languages use syntax and semantics to express computation.", metadata={"confidence": 0.95, "authority": 0.9})
    graph.add("syntax", "Syntax defines the grammar of a programming language.", metadata={"confidence": 0.8, "authority": 0.7})
    graph.link("prog", "syntax", 0.85, metadata={"strength": 0.85})

    cot = reasoning.chain_of_thought("give me a concept of programming languages")

    assert cot.conclusion
    assert cot.steps
    assert cot.confidence >= 0.2


def test_persistence_manager_bootstraps_required_runtime_assets(tmp_path):
    manager = PersistenceManager(root_dir=str(tmp_path / "runtime"))

    required_paths = [
        manager.root_dir,
        manager.memory_dir,
        manager.cache_dir,
        manager.logs_dir,
        manager.snapshots_dir,
        manager.backups_dir,
        manager.indexes_dir,
        manager.memory_path,
        os.path.join(manager.root_dir, "knowledge_graph.json"),
        os.path.join(manager.root_dir, "runtime_state.json"),
        os.path.join(manager.root_dir, "cognitive_cache.json"),
    ]

    for path in required_paths:
        assert os.path.exists(path)


def test_cognitive_memory_layer_restores_from_persisted_graph(tmp_path):
    runtime_root = tmp_path / "runtime"
    manager = PersistenceManager(root_dir=str(runtime_root))
    graph = MemoryGraph(persist_path=str(runtime_root / "memory" / "knowledge_graph.json"), persistence_manager=manager)
    layer = CognitiveMemoryLayer(memory_graph=graph, persistence_manager=manager)

    layer.ingest_document({
        "title": "Programming Languages",
        "text": "Programming languages use syntax and semantics to express computation.",
        "source": {"document": "intro.pdf", "section": "overview", "page": 1},
    })

    reloaded_graph = MemoryGraph(persist_path=str(runtime_root / "memory" / "knowledge_graph.json"), persistence_manager=manager)
    reloaded_layer = CognitiveMemoryLayer(memory_graph=reloaded_graph, persistence_manager=manager)
    results = reloaded_layer.retrieve("give me a concept of programming languages", top_k=3)

    assert results
    assert any("programming" in result["name"].lower() or "syntax" in result["summary"].lower() for result in results)


def test_multi_intent_decomposition_splits_queries():
    synthesis = CognitiveSynthesisEngine()

    plan = synthesis.build_reasoning_plan("Explain programming languages and how compilers work")

    assert plan.primary_intent == "programming languages"
    assert len(plan.subqueries) >= 2
    assert any("compiler" in sub.lower() for sub in plan.subqueries)


def test_explanation_structure_enforcement():
    synthesis = CognitiveSynthesisEngine()

    response = synthesis.synthesize(
        "Give me a concept of programming languages",
        reasoning_trace={
            "summary": "Programming languages use syntax and semantics to express computation.",
            "confidence": 0.9,
            "steps": [{"question": "What is a programming language?", "answer": "A language for expressing instructions.", "confidence": 0.9}],
        },
    )

    lower = response.lower()
    assert "definition" in lower
    assert "core concept breakdown" in lower
    assert "relationships" in lower
    assert "examples" in lower
    assert "summary" in lower


def test_confidence_based_narration_filters_low_confidence():
    synthesis = CognitiveSynthesisEngine()

    response = synthesis.synthesize(
        "Explain programming languages",
        reasoning_trace={
            "summary": "Programming languages use syntax and semantics.",
            "confidence": 0.3,
            "steps": [{"question": "What is a programming language?", "answer": "A tool for writing instructions.", "confidence": 0.2}],
        },
    )

    assert "may" in response.lower() or "likely" in response.lower()


def test_synthesis_output_removes_internal_artifacts():
    synthesis = CognitiveSynthesisEngine()

    response = synthesis.synthesize(
        "Give me a concept of programming languages",
        reasoning_trace={
            "summary": "Programming languages define instructions.",
            "confidence": 0.8,
            "steps": [{"question": "What is it?", "answer": "A syntax-driven notation.", "confidence": 0.8, "node_id": "node-123"}],
            "node_ids": ["node-123"],
            "scores": [{"node_id": "node-123", "score": 0.9}],
        },
    )

    assert "node-123" not in response
    assert "score" not in response.lower()
    assert "graph" not in response.lower()


def test_reasoning_plan_is_built_before_synthesis():
    synthesis = CognitiveSynthesisEngine()
    plan = synthesis.build_reasoning_plan("Explain programming languages and how compilers work")

    assert plan.steps
    assert any("programming" in step.lower() for step in plan.steps)
    assert any("compiler" in step.lower() for step in plan.steps)


def test_end_to_end_plan_reasoning_and_synthesis(tmp_path):
    graph = MemoryGraph(persist_path=str(tmp_path / "graph.pkl"))
    graph.add("prog", "Programming languages use syntax and semantics to express computation.", metadata={"confidence": 0.95, "authority": 0.9})
    graph.add("compiler", "Compilers translate source code into machine instructions.", metadata={"confidence": 0.9, "authority": 0.8})
    graph.link("prog", "compiler", 0.84, metadata={"strength": 0.84})

    scoring = GraphScoringEngine(memory_graph=graph)
    reasoning = ReasoningEngine(memory_graph=graph, graph_scoring_engine=scoring)
    synthesis = CognitiveSynthesisEngine(reasoning_engine=reasoning, graph_scoring_engine=scoring)

    response = synthesis.synthesize_from_query("Explain programming languages and how compilers work")

    lower = response.lower()
    assert "programming" in lower
    assert "compiler" in lower
    assert "definition" in lower
    assert "summary" in lower
    assert "node" not in lower
    assert "score" not in lower


def test_runtime_manager_exposes_cognitive_memory_services():
    runtime = RuntimeManager()

    layer = runtime.get_cognitive_memory_layer()
    router = runtime.get_memory_router()

    assert layer is not None
    assert router is not None
    assert layer is runtime.get_cognitive_memory_layer()
    assert router is runtime.get_memory_router()
