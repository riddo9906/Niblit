from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from modules.adaptive_retrieval_cognition import AdaptiveRetrievalCognition
from modules.unified_runtime import NiblitUnifiedRuntime, ProviderRuntimeManager, RuntimeEventBus


class _FakeDB:
    def search(self, _query: str, limit: int = 14):
        return [
            {
                "key": "doc_a",
                "source": "book_a",
                "topic": "ai architecture",
                "value": "Technique X improve latency and increase throughput with strong benchmark citation http://a",
                "evaluation_score": 0.81,
                "reflection": "reflection quality is strong and validated",
            }
        ][:limit]

    def recall(self, _query: str, limit: int = 12):
        return [
            {
                "key": "doc_b",
                "source": "book_b",
                "topic": "ai architecture",
                "value": "Technique X degrade latency and decrease throughput under production load",
                "evaluation_score": 0.69,
                "reflection_summary": "requires contradiction analysis",
            }
        ][:limit]

    def list_facts(self, limit: int = 260):
        return [
            {
                "key": "fact_1",
                "source": "governed_document_cognition",
                "topic": "ai architecture",
                "value": "Technique X improve throughput when context windows are tuned",
                "evaluation_score": 0.74,
                "tags": ["document_cognition"],
            }
        ][:limit]


class _FakeCore:
    def __init__(self):
        self.db = _FakeDB()


def test_adaptive_retrieval_builds_bundle_with_contradictions() -> None:
    arc = AdaptiveRetrievalCognition()
    bundle = arc.build_retrieval_bundle(query="Technique X latency throughput", core=_FakeCore())
    assert bundle.retrievals
    assert bundle.contradictions
    assert bundle.telemetry["contradiction_count"] >= 1
    assert bundle.topic_mastery


def test_adaptive_retrieval_command_aliases_work() -> None:
    arc = AdaptiveRetrievalCognition()
    arc.build_retrieval_bundle(query="networking reliability", core=_FakeCore())
    raw = arc.render_command("adaptive-retrieval status")
    data = json.loads(raw)
    assert "queries" in data
    assert data["queries"] >= 1


def test_provider_runtime_includes_adaptive_telemetry() -> None:
    adaptive = AdaptiveRetrievalCognition()
    mgr = ProviderRuntimeManager(RuntimeEventBus(), adaptive_retrieval=adaptive)
    fake_mgr = MagicMock()
    fake_mgr.ask.return_value = "provider reply"
    fake_mgr.switch.return_value = "ok"
    fake_mgr.status.return_value = {"active": "qwen", "qwen": True, "hf": True, "anthropic": True, "ruflo": True}

    with patch("modules.llm_provider_manager.get_llm_provider_manager", return_value=fake_mgr), patch(
        "modules.runtime_router_v2.NiblitUnifiedRuntimeRouterV2"
    ) as fake_rr_cls:
        fake_rr = MagicMock()
        fake_rr.generate.return_value = ""
        fake_rr_cls.return_value = fake_rr
        out = mgr.generate(prompt="Technique X", core=_FakeCore(), local_first=False)

    assert out["status"] == "ok"
    assert "adaptive_retrieval" in out["telemetry"]


def test_unified_runtime_dispatches_retrieval_command(tmp_path) -> None:
    rt = NiblitUnifiedRuntime(state_file=tmp_path / "runtime_state.json")
    rt.provider_runtime._adaptive_retrieval.build_retrieval_bundle(  # pylint: disable=protected-access
        query="ai architecture", core=SimpleNamespace(db=_FakeDB())
    )
    raw = rt.dispatch_command(command="retrieval status", core=SimpleNamespace(db=_FakeDB(), handle=lambda x: x))
    data = json.loads(raw)
    assert "queries" in data
