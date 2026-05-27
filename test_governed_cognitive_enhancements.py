"""Focused tests for governed cognitive enhancement hooks."""

from __future__ import annotations

import tempfile

from modules.code_compiler import CodeCompiler
from modules.code_error_fixer import CodeErrorFixer
from modules.llm_provider_manager import LLMProviderManager
from modules.self_researcher import SelfResearcher
from niblit_brain import BrainTrainer
from niblit_memory import KnowledgeDB


class _StubMemory:
    def __init__(self):
        self.records = []

    def recall(self, *_args, **_kwargs):
        return []

    def store_learning(self, payload):
        self.records.append(payload)


class _StubKnowledgeDB:
    def __init__(self):
        self.facts = []

    def add_fact(self, key, value, tags=None):
        self.facts.append({"key": key, "value": value, "tags": tags or []})


class _StubRouter:
    def generate(self, prompt, context=None):  # noqa: ARG002
        return f"router-synthesis::{len(prompt)}"


class _StubLocalBrain:
    model_name = "stub-qwen"

    def generate(self, prompt, max_new_tokens=512, system_prompt=None):  # noqa: ARG002
        return "local"


class _StubHF:
    enabled = True
    token = "token"
    model = "hf"

    def ask_single(self, prompt):  # noqa: ARG002
        return "hf"


def test_knowledge_db_builds_relationship_index():
    KnowledgeDB._instance = None
    with tempfile.TemporaryDirectory() as tmp:
        db = KnowledgeDB(path=f"{tmp}/memory.json")
        db.add_fact(
            "runtime_router_v2_localbrain_link",
            "Runtime router v2 coordinates LocalBrain and EventBus authority.",
            tags=["architecture", "runtime"],
        )
        rels = db.get_relationships("runtime")
        summary = db.relationship_summary()
        db.shutdown()
    assert rels
    assert summary["edges"] >= 1
    assert "architecture_link" in summary["types"]


def test_provider_manager_uses_quality_and_latency_feedback():
    mgr = LLMProviderManager()
    mgr.wire(local_brain=_StubLocalBrain(), hf_brain=_StubHF())
    mgr.record_provider_feedback("qwen", quality_score=0.05, latency_ms=2000)
    mgr.record_provider_feedback("hf", quality_score=0.98, latency_ms=40)
    rankings = mgr.provider_rankings(prompt="x" * 1600, prefer_long_context=True)
    assert rankings["hf"] > rankings["qwen"]


def test_self_researcher_gap_escalation_uses_router():
    sr = SelfResearcher(
        db=_StubKnowledgeDB(),
        modules_registry={"runtime_router_v2": _StubRouter()},
    )
    gap = sr._detect_knowledge_gap("python asyncio task group", ["gardening soil guide"])
    synthesis = sr._router_cognition_synthesis("python asyncio task group", ["result"])
    assert gap["escalate"] is True
    assert synthesis and synthesis.startswith("router-synthesis::")


def test_code_compiler_records_structured_telemetry():
    compiler = CodeCompiler()
    result = compiler.run("python", "print('ok')")
    telemetry = compiler.compile_telemetry(limit=1)[0]
    assert result.success is True
    assert telemetry["language"] == "python"
    assert telemetry["success"] is True


def test_code_error_fixer_groups_and_stages_repairs():
    fixer = CodeErrorFixer()
    groups = fixer.group_error_signals("SyntaxError: invalid syntax\nNameError: foo")
    stage = fixer.stage_governed_repair("python", "print(foo)", "NameError: foo")
    group_names = {g["group"] for g in groups}
    assert "syntax_chain" in group_names
    assert "symbol_chain" in group_names
    assert stage["approval_required"] is True


def test_brain_trainer_ingests_evaluation_feedback():
    memory = _StubMemory()
    kb = _StubKnowledgeDB()
    trainer = BrainTrainer(memory=memory, knowledge_db=kb)
    trainer.ingest_evaluation_feedback(
        "best retry strategy",
        "Use exponential backoff with jitter.",
        0.91,
        provider="qwen",
        telemetry={"latency_ms": 120},
    )
    assert kb.facts
    assert any("evaluation_feedback" in str(item) for item in trainer._facts)
