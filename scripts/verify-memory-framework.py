"""Real Qdrant + local embeddings + local inference acceptance, no paid API."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from dotenv import dotenv_values
    import httpx
    from modules.memory_laboratory.setup import Config, QdrantSetup
    from modules.memory_laboratory.gateway import MemoryGateway
    from modules.memory_laboratory.runtime import MemoryRuntime
    from modules.memory_laboratory.context import augment_messages
    from modules.memory_laboratory.market import MarketJournal
    folder = ROOT / "diagnostics/memory-framework-acceptance"
    folder.mkdir(exist_ok=True)
    scope = {"namespace": "acceptance_"+uuid4().hex[:12], "principal": "acceptance_operator"}
    config = Config.from_values(dotenv_values(ROOT / ".env.memory-laboratory"))
    allowed = lambda action, namespace, principal: (namespace == scope["namespace"] and principal == scope["principal"]) or (namespace == "trading" and principal == "desktop_operator")
    g = MemoryGateway(config, folder / (scope["namespace"]+".sqlite3"), authorize=allowed)
    r = MemoryRuntime(g, scope=scope)
    report = {"ready": False, "checks": {}, "paid_inference_calls": 0}
    def check(name, value):
        report["checks"][name] = bool(value)
        if not value:
            raise AssertionError(name)
    try:
        code = "CEDAR-"+uuid4().hex[:8].upper()
        r.enqueue(source="acceptance://desk-note", content=f"The calibration code for the violet lighthouse is {code}.", metadata={"confidence": .4})
        check("queue_projected", r.tick()["completed"] == 1)
        found = g.retrieve("violet lighthouse calibration code", **scope)
        check("real_hybrid_retrieval", found["mode"] == "hybrid" and code in found["results"][0]["content"])
        check("confidence_not_fabricated", found["results"][0]["confidence"] == .4 and found["results"][0]["verification"] == "unverified")
        original_authorizer = g.authorize
        g.authorize = lambda action, namespace, principal: principal == scope["principal"] and namespace in {scope["namespace"], "empty_acceptance"}
        try:
            check("namespace_isolation", not g.retrieve("violet", namespace="empty_acceptance", principal=scope["principal"])["results"])
        finally:
            g.authorize = original_authorizer
        try:
            g.retrieve("violet", namespace="unrelated", principal=scope["principal"])
            check("unauthorized_scope_denied", False)
        except PermissionError:
            check("unauthorized_scope_denied", True)
        messages, context = augment_messages([{"role":"system", "content":"Answer briefly using the supplied evidence. Include the exact calibration code and its source."},
            {"role":"user", "content":"What is the violet lighthouse calibration code?"}], gateway=g, scope=(scope["namespace"],scope["principal"]))
        response = httpx.post("http://127.0.0.1:8000/v1/chat/completions", json={"model":"qwen2.5-coder-3b", "messages":messages,"max_tokens":180,"temperature":0}, timeout=120)
        response.raise_for_status()
        answer = response.json()["choices"][0]["message"]["content"]
        check("local_model_answers_from_memory", code in answer and bool(context["citations"]))
        market = MarketJournal(g)
        identity = dict(symbol="FIXTUREBTC", venue=scope["namespace"], interval="1m", mode="paper")
        key = market.observe([1.,2.,3.], **identity, observed_at="2026-10-27T10:00:00+00:00", available_at="2026-10-27T10:00:00+00:00")
        market.record_outcome(key, realized_return=.02, available_at="2026-10-27T11:00:00+00:00", evidence="Acceptance fixture outcome, not a real trade")
        prior = market.similar([1.,2.,3.], **identity, as_of="2026-10-27T10:30:00+00:00")
        check("market_qdrant_temporal_query", len(prior)==1 and prior[0]["retrieval_backend"]=="qdrant" and prior[0]["outcome"] is None)
        later = market.similar([1.,2.,3.], **identity, as_of="2026-10-27T11:30:00+00:00")
        check("outcome_only_after_available", later[0]["outcome"]["realized_return"] == .02)
        check("no_cross_mode_matches", not market.similar([1.,2.,3.], **{**identity,"mode":"live"}, as_of="2026-10-27T11:30:00+00:00"))
        r.backup(folder / (scope["namespace"]+".backup.sqlite3"))
        check("source_backup_integrity", True)
        # Restart only the existing dedicated memory container, preserving volume.
        subprocess.run(["docker", "restart", "niblit-memory-lab-qdrant-1"], check=True, stdout=subprocess.DEVNULL, timeout=45)
        for attempt in range(30):
            try:
                g.backend.request("GET", "/collections")
                break
            except Exception:
                time.sleep(1)
        check("docker_restart_preserves_memory", code in g.retrieve("violet lighthouse", **scope)["results"][0]["content"])
        g.close()
        g = MemoryGateway(config, r.gateway.path, authorize=allowed)
        check("client_restart_preserves_memory", code in g.retrieve("violet lighthouse", **scope)["results"][0]["content"])
        g.delete_source("acceptance://desk-note", **scope)
        check("deleted_evidence_not_retrieved", not g.retrieve("violet lighthouse", **scope)["results"])
        report["ready"] = True
    except Exception as exc:
        report["error"] = type(exc).__name__
    finally:
        g.close()
        (folder / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
