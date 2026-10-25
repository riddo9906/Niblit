"""Live permitted-document test through Qdrant and the existing Core LlmToolLoop.

Uses an isolated ledger/workspace and a narrowly scoped operator test grant.
Never imports personal knowledge, grants persistent permissions or sends keys
to the model. Restart affects ONLY the dedicated niblit-memory-lab service.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--restart-qdrant", action="store_true")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    workspace = out / "workspace"
    workspace.mkdir(exist_ok=True)
    os.environ["NIBLIT_WORKSPACE_ROOT"] = str(workspace)
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    from dotenv import dotenv_values
    import httpx
    import psutil
    from modules.memory_laboratory.gateway import MemoryGateway
    from modules.memory_laboratory.setup import Config, QdrantSetup
    from modules.llm_tool_loop import LlmToolLoop

    values = dotenv_values(ROOT / ".env.memory-laboratory")
    config = Config(url=values["QDRANT_URL"], api_key=values["QDRANT_API_KEY"])
    namespace = "acceptance_" + uuid4().hex[:12]
    principal = "phase6_test_operator"
    # Explicit test grant is limited to this generated namespace/principal.
    authorize = lambda action, ns, actor: ns == namespace and actor == principal
    phrase = "SILVER-CEDAR-" + uuid4().hex[:8].upper()
    fixture = workspace / "phase6-permitted-note.txt"
    fixture.write_text("The violet lighthouse calibration phrase is " + phrase + ".\n", encoding="utf-8")
    report = {"checks": {}, "namespace": namespace, "scope": "source Core LlmToolLoop + packaged Cloud + real local Qdrant"}
    gateway = MemoryGateway(config, out / "ledger.sqlite3", authorize=authorize)
    process, log = None, None

    def start_cloud():
        nonlocal process, log
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 28080))
        env = {k: v for k, v in os.environ.items()
               if not any(s in k.upper() for s in ("TOKEN", "API_KEY", "SECRET", "PASSWORD"))}
        env.update(PYTHON_DOTENV_DISABLED="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                   NIBLIT_PORT="28080", NIBLIT_QWEN_PORT="28081", NIBLIT_HOST="127.0.0.1",
                   NIBLIT_N_CTX="4096", NIBLIT_STORAGE_ROOT=str(out / "cloud"),
                   NIBLIT_GGUF_MODEL_DIR=str(Path.home() / "llama_migration/models"),
                   NIBLIT_LLAMA_SERVER_BIN=str(Path.home() / "llama_migration/llama.cpp/build/bin/Release/llama-server.exe"))
        binary = ROOT / "dist/testing-20261025-commands/niblit/cloud/niblit-cloud.exe"
        log = (out / "cloud.log").open("a", encoding="utf-8")
        process = subprocess.Popen([str(binary)], cwd=out, env=env, stdout=log,
                                   stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 120
        with httpx.Client(timeout=2) as client:
            while time.monotonic() < deadline:
                try:
                    if client.get("http://127.0.0.1:28080/health").is_success:
                        return
                except httpx.HTTPError:
                    pass
                if process.poll() is not None:
                    raise RuntimeError("isolated Cloud exited")
                time.sleep(.5)
        raise TimeoutError("isolated Cloud readiness timeout")

    def stop_cloud():
        nonlocal process, log
        if process and process.poll() is None:
            children = psutil.Process(process.pid).children(recursive=True)
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
            for child in reversed(children):
                try:
                    child.terminate()
                    child.wait(timeout=5)
                except psutil.NoSuchProcess:
                    pass
                except psutil.TimeoutExpired:
                    child.kill()
        if log:
            log.close()
        process, log = None, None

    def ask():
        # An inert executor is sufficient: tools=[] means no action surface.
        class NoActions:
            def niblit_status(self):
                raise AssertionError("no tools are exposed in this test")
        loop = LlmToolLoop(executor=NoActions(), cloud_root="http://127.0.0.1:28080",
                           timeout=180, memory_gateway=gateway, memory_scope=(namespace, principal))
        answer = loop.chat([
            {"role": "system", "content": "Answer briefly using the memory evidence. Include the calibration phrase exactly and cite the source filename."},
            {"role": "user", "content": "What is the violet lighthouse calibration phrase?"}
        ], tools=[], model="qwen2.5-coder-3b")
        return answer

    try:
        readiness = gateway.backend.run()
        report["checks"]["qdrant_readiness"] = readiness["ready"]
        if not readiness["ready"]:
            raise RuntimeError("Qdrant setup required")
        first = gateway.ingest_file(fixture.name, namespace=namespace, principal=principal)
        second = gateway.ingest_file(fixture.name, namespace=namespace, principal=principal)
        report["checks"]["idempotent_verified_upsert"] = first["ids"] == second["ids"]
        report["collection"] = first["collection"]
        points = gateway.backend.request("POST", f"/collections/{first['collection']}/points", json={
            "ids": first["ids"], "with_payload": True})
        report["checks"]["actual_point_and_payload"] = (len(points) == 1 and
            points[0]["payload"]["namespace"] == namespace and phrase in points[0]["payload"]["content"])
        # A separate caller without permission must be denied before retrieval.
        try:
            gateway.retrieve("violet lighthouse", namespace=namespace, principal="other")
            report["checks"]["namespace_isolation"] = False
        except PermissionError:
            report["checks"]["namespace_isolation"] = True
        start_cloud()
        before = ask()
        report["before_restart"] = before
        report["checks"]["real_model_answer_with_citation"] = (
            phrase in before["text"] and fixture.name in before["text"] and
            bool(before["memory_retrieval"]["citations"]))
        stop_cloud()
        gateway.close()
        if args.restart_qdrant:
            docker = Path(os.environ["LOCALAPPDATA"]) / "Programs/DockerDesktop/resources/bin/docker.exe"
            subprocess.run([str(docker), "compose", "--project-name", "niblit-memory-lab",
                "--env-file", str(ROOT / ".env.memory-laboratory"), "-f",
                str(ROOT / "deploy/memory-laboratory.compose.yml"), "restart", "qdrant"], check=True)
            with httpx.Client(base_url=config.url, headers={"api-key": config.api_key}, timeout=2) as client:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    try:
                        if client.get("/collections").is_success:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(.3)
            report["checks"]["qdrant_restarted"] = True
        gateway = MemoryGateway(config, out / "ledger.sqlite3", authorize=authorize)
        start_cloud()
        after = ask()
        report["after_restart"] = after
        report["checks"]["persistent_answer_with_citation"] = (
            phrase in after["text"] and fixture.name in after["text"] and
            bool(after["memory_retrieval"]["citations"]))
        report["all_passed"] = all(report["checks"].values())
    except Exception as exc:
        report["all_passed"] = False
        report["error_type"] = type(exc).__name__
        raise
    finally:
        stop_cloud()
        gateway.close()
        (out / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["checks"], indent=2))
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
