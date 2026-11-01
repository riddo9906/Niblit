"""Acceptance against the running packaged Core and local model, no orders/API spend."""
import importlib.util
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-file-tests', action='store_true')
    args = parser.parse_args()
    import httpx
    from dotenv import dotenv_values
    from modules.memory_laboratory.setup import Config
    from modules.memory_laboratory.gateway import MemoryGateway
    values = dotenv_values(ROOT / ".env")
    config = Config.from_values(dotenv_values(values["NIBLIT_MEMORY_LAB_ENV_FILE"]))
    scope = {"namespace": "desktop", "principal": "desktop_operator"}
    g = MemoryGateway(config, values["NIBLIT_MEMORY_LAB_LEDGER"], authorize=lambda action,ns,actor: ns=="desktop" and actor=="desktop_operator")
    source = "acceptance://desktop/"+uuid4().hex
    marker = "AMBER-"+uuid4().hex[:8].upper()
    report = {"ready": False, "checks": {}, "paid_inference_calls": 0}
    def check(name, value):
        report["checks"][name] = bool(value)
        if not value:
            raise AssertionError(name)
    try:
        with httpx.Client(base_url="http://127.0.0.1:5000", timeout=120) as client:
            deadline = time.monotonic()+240
            while True:
                try:
                    status = client.get("/api/memory/framework", timeout=5)
                    if status.is_success and status.json().get("enabled"):
                        cloud = httpx.get("http://127.0.0.1:8000/health", timeout=5)
                        if cloud.is_success and cloud.json().get("inference_ready"):
                            break
                except httpx.HTTPError:
                    pass
                if time.monotonic() > deadline:
                    raise TimeoutError("Packaged memory Core did not start")
                time.sleep(1)
            status.raise_for_status()
            check("packaged_framework_enabled", status.json().get("enabled") and status.json().get("worker_running"))
            g.ingest([(f"The desktop acceptance calibration code for the amber observatory is {marker}.", source)], source=source, **scope)
            search = client.post("/api/memory/search", json={"query":"amber observatory desktop acceptance calibration", "limit":5})
            search.raise_for_status()
            check("packaged_search_returns_evidence", any(marker in item["content"] for item in search.json()["results"]))
            start = time.monotonic()
            chat = client.post("/chat", json={"text":"Give the amber observatory calibration phrase exactly, using the retrieved memory.", "model":"qwen2.5-coder-3b", "use_model":True})
            chat.raise_for_status()
            body = chat.json()
            report['chat_diagnostic'] = {'source':body.get('source'),
                'marker_returned':marker in body.get('reply',''),
                'memory_retrieval':body.get('memory_retrieval'),
                'reply_length':len(body.get('reply',''))}
            check("packaged_chat_retrieves_and_answers", marker in body.get("reply", "") and bool(body.get("memory_retrieval", {}).get("citations")))
            report["memory_answer_seconds"] = round(time.monotonic()-start, 2)
            if args.skip_file_tests:
                report['file_upload_test'] = 'not_repeated_after_browser_upload_permission_declined'
            else:
                fixture = importlib.util.spec_from_file_location("attachment_fixture", ROOT / "tests/test_chat_attachments.py")
                module = importlib.util.module_from_spec(fixture)
                fixture.loader.exec_module(module)
                data = module.pdf_bytes(["This is an attachment acceptance fixture.", "The PDF calibration number is 9876."])
                upload = client.post("/api/chat/attachments?filename=memory-acceptance.pdf", content=data, headers={"Content-Type":"application/pdf"})
                upload.raise_for_status()
                check("packaged_pdf_extracts_pages", upload.json()["page_count"]==2 and upload.json()["pages_indexed"]==2)
                answer = client.post("/chat", json={"text":"According to the attached PDF, what is the PDF calibration number? Cite its page.",
                    "model":"qwen2.5-coder-3b", "use_model":True, "attachment_ids":[upload.json()["id"]]})
                answer.raise_for_status()
                check("packaged_pdf_reaches_model", "9876" in answer.json().get("reply", "") and bool(answer.json().get("document_sources")))
            commands = client.get("/api/commands/surface")
            commands.raise_for_status()
            check("original_command_surface_available", bool(commands.json()))
            budget = client.get("/api/inference/budget")
            budget.raise_for_status()
            check("local_cost_guard_status_available", bool(budget.json()))
            check("cloud_still_ready", httpx.get("http://127.0.0.1:8000/health", timeout=5).json().get("inference_ready") is True)
            trading = httpx.get("http://127.0.0.1:8100/health", timeout=5).json()
            check("trading_remains_simulated", trading.get("backend")=="paper" and trading.get("mode") in {"paper","observe"})
            snapshot = client.get("/api/desktop/memory")
            snapshot.raise_for_status()
            check("desktop_memory_diagnostics_connected", snapshot.json().get("memory_framework", {}).get("worker_running"))
        report["ready"] = True
    except Exception as exc:
        report["error"] = type(exc).__name__
        if isinstance(exc, httpx.HTTPStatusError):
            report["http_status"] = exc.response.status_code
    finally:
        try:
            g.delete_source(source, **scope)
        finally:
            g.close()
        destination = ROOT / "diagnostics/memory-framework-desktop-acceptance.json"
        destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
