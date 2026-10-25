"""Verify a desktop bundle with disposable data and isolated local services."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import time
from urllib.request import Request, urlopen


def request_json(url, payload=None, timeout=3):
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(url, data=data, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--hold-seconds", type=int, default=0, help="Keep the isolated API available for browser acceptance testing")
    args = parser.parse_args()
    bundle, output = args.bundle.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    workspace = output / "workspace"
    workspace.mkdir(exist_ok=True)
    (workspace / "calculator.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    report = {"bundle": str(bundle), "checks": {}}
    processes, logs = [], []
    env = {
        key: value for key, value in os.environ.items()
        if not any(word in key.upper() for word in ("TOKEN", "API_KEY", "PASSWORD", "CREDENTIAL", "SECRET"))
    }
    env.update({
        "PYTHON_DOTENV_DISABLED": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "NIBLIT_ENV_FILE": "", "NIBLIT_MEMORY_PATH": str(output / "memory.json"),
        "NIBLIT_LLM_CHAT_DB_PATH": str(output / "chat.sqlite"),
        "FUSED_MEMORY_DB_PATH": str(output / "fused.sqlite"),
        "NIBLIT_RUNTIME_LOG_FILE": str(output / "runtime.jsonl"),
        "NIBLIT_UNIFIED_RUNTIME_STATE": str(output / "unified-runtime.json"),
        "NIBLIT_WORKSPACE_ROOT": str(workspace), "NIBLIT_TRADING_MODE": "observe",
        "NIBLIT_TRADING_BACKEND": "paper", "NIBLIT_TRADING_ALLOW_EXECUTION": "false",
        "NIBLIT_TRADING_API_PORT": "28100", "NIBLIT_PORT": "28080",
        "NIBLIT_API_PORT": "28500", "NIBLIT_CLOUD_BIND_HOST": "127.0.0.1",
        "NIBLIT_CLOUD_SERVER_URL": "http://127.0.0.1:28080",
        "NIBLIT_CLOUD_SERVER_PRIMARY_PORT": "28080", "NIBLIT_CLOUD_BASE_URL": "http://127.0.0.1:28080",
        "NIBLIT_LLM_PROVIDER": "qwen", "NIBLIT_GGUF_BACKEND": "http",
        "NIBLIT_HEADLESS": "1", "NIBLIT_LOW_RESOURCE_MODE": "0", "NIBLIT_SKIP_INIT_WAIT": "0",
        "NIBLIT_INIT_WAIT_MAX_SECONDS": "120", "QDRANT_URL": "http://127.0.0.1:1",
        "NIBLIT_API_AUTOSTART": "1",
    })
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    def spawn(name, executable, arguments=(), interactive=False):
        log = (output / f"{name}.log").open("w", encoding="utf-8")
        logs.append(log)
        process = subprocess.Popen([str(executable), *arguments], cwd=str(output), env=env,
                                   stdout=log, stderr=subprocess.STDOUT,
                                   stdin=subprocess.PIPE if interactive else subprocess.DEVNULL,
                                   creationflags=flags)
        processes.append(process)
        return process

    try:
        for name in ("niblit.exe", "niblit-ui.exe", "cloud/niblit-cloud.exe", "lean-algos/niblit-lean-algos.exe", "niblit_core.py", "niblit_core/config/paths.py"):
            assert (bundle / name).is_file(), f"Required bundle file missing: {name}"
        report["checks"]["required_files"] = True
        for port in (28080, 28100):
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", port))
        for name, executable, port in (("cloud", bundle / "cloud/niblit-cloud.exe", 28080),
                                       ("lean", bundle / "lean-algos/niblit-lean-algos.exe", 28100)):
            process = spawn(name, executable)
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    data = request_json(f"http://127.0.0.1:{port}/health")
                    if name == "lean":
                        assert data.get("healthy") is True and data.get("state") == "ready", data
                        assert data.get("mode") == "observe", data
                    report["checks"][f"{name}_health"] = True
                    break
                except Exception:
                    time.sleep(0.5)
            assert report["checks"].get(f"{name}_health"), f"{name} did not become healthy; see {name}.log"
        models = request_json("http://127.0.0.1:28080/v1/models")
        ids = [model["id"] for model in models.get("data", [])]
        report["model_ids"] = ids
        with urlopen("http://127.0.0.1:28080/ui/app.js", timeout=3) as response:
            report["checks"]["cloud_static_assets"] = response.status == 200
        model = "qwen2.5-0.5b" if "qwen2.5-0.5b" in ids else (ids[0] if ids else None)
        assert model, "No local model was discovered"
        try:
            completion = request_json("http://127.0.0.1:28080/v1/chat/completions", {
                "model": model, "messages": [{"role": "user", "content": "Reply with READY."}],
                "max_tokens": 16, "temperature": 0, "stream": False,
            }, timeout=90)
            answer = completion["choices"][0]["message"].get("content", "")
            report["checks"]["live_local_inference"] = bool(answer.strip())
            report["inference_model"] = completion.get("model")
            report["inference_excerpt"] = answer[:160]
        except Exception as exc:
            report["checks"]["live_local_inference"] = False
            report["inference_error"] = str(exc)
        marker = "niblit-packaged-memory-20261025"
        core = spawn("core-status", bundle / "niblit.exe", ["--headless", "--cli"], interactive=True)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline and core.poll() is None:
            try:
                health = request_json("http://127.0.0.1:28500/health")
                if health.get("service") == "niblit":
                    report["checks"]["core_api_identity"] = True
                    break
            except Exception:
                pass
            time.sleep(1)
        assert report["checks"].get("core_api_identity"), "Packaged Core API did not start"
        for section in ("overview", "architecture", "cognitive", "memory", "conversation", "inference", "execution", "trading", "settings"):
            snapshot = request_json(f"http://127.0.0.1:28500/api/desktop/{section}", timeout=15)
            report["checks"][f"desktop_{section}"] = snapshot.get("core_available") is True
            if section == "architecture":
                report["checks"]["architecture_wiring_verified"] = snapshot.get("all_checked_connections_ready") is True
            (output / f"desktop-{section}.json").write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
        preflight = Request("http://127.0.0.1:28500/health", method="OPTIONS", headers={
            "Origin": "http://tauri.localhost", "Access-Control-Request-Method": "GET"})
        with urlopen(preflight, timeout=5) as response:
            report["checks"]["windows_desktop_cors"] = response.headers.get("Access-Control-Allow-Origin") == "http://tauri.localhost"
        governed = request_json("http://127.0.0.1:28500/api/commands/governed", timeout=20)
        surface = request_json("http://127.0.0.1:28500/api/commands/surface", timeout=30)
        (output / "governed-commands.json").write_text(json.dumps(governed, indent=2), encoding="utf-8")
        (output / "command-surface.json").write_text(json.dumps(surface, indent=2), encoding="utf-8")
        report["checks"]["original_command_catalogue"] = len(surface.get("commands", [])) > 20
        report["command_counts"] = {"governed": governed.get("count"), "original": len(surface.get("commands", []))}
        executed = request_json("http://127.0.0.1:28500/api/commands/execute", {
            "command": "runtime_status", "arguments": {}, "request_id": "desktop-acceptance-status"}, timeout=20)
        (output / "command-execution.json").write_text(json.dumps(executed, indent=2), encoding="utf-8")
        report["checks"]["governed_command_execution"] = executed.get("status") == "success" or executed.get("ok") is True
        original = request_json("http://127.0.0.1:28500/api/commands/execute", {
            "command": "knowledge stats", "arguments": {}, "request_id": "desktop-acceptance-original"}, timeout=20)
        (output / "original-command-execution.json").write_text(json.dumps(original, indent=2), encoding="utf-8")
        report["checks"]["original_command_alias_execution"] = original.get("status") == "success" and original.get("alias_of") == "knowledge_stats"
        listing = request_json("http://127.0.0.1:28500/api/commands/execute", {
            "command": "workspace_list", "arguments": {"path": "."}}, timeout=15)
        report["checks"]["configured_workspace_listing"] = listing.get("status") == "success" and any(
            entry.get("name") == "calculator.py" for entry in listing.get("result", {}).get("entries", []))
        rendered = request_json("http://127.0.0.1:28500/api/file/render", {"path": str(workspace / "calculator.py")}, timeout=15)
        report["checks"]["workspace_code_rendering"] = rendered.get("viewer_type") == "code" and 'return a + b' in json.dumps(rendered)
        bridged = request_json("http://127.0.0.1:28500/v1/inference/chat", {
            "model": model, "messages": [{"role": "user", "content": "Reply with READY."}],
            "max_tokens": 16, "temperature": 0, "stream": False}, timeout=90)
        report["checks"]["core_cloud_inference_bridge"] = bool(bridged.get("choices", [{}])[0].get("message", {}).get("content"))
        grounded = request_json("http://127.0.0.1:28500/chat", {
            "text": "Read calculator.py and explain what add(a, b) returns in one sentence."}, timeout=120)
        (output / "file-question.json").write_text(json.dumps(grounded, indent=2), encoding="utf-8")
        report["checks"]["grounded_file_question"] = (
            "Source files inspected: calculator.py" in grounded.get("reply", "")
            and any(item.get("tool") == "workspace_read" and item.get("status") == "success"
                    for item in grounded.get("tool_trace", [])))
        print("Isolated desktop API ready at http://127.0.0.1:28500", flush=True)
        if args.hold_seconds > 0:
            deadline = time.monotonic() + min(args.hold_seconds, 1800)
            while time.monotonic() < deadline and not (output / "browser-finished").exists():
                time.sleep(1)
        core.communicate(input=f"remember build_check: {marker}\nstatus\nexit\n".encode(), timeout=200)
        text = (output / "core-status.log").read_text(encoding="utf-8", errors="replace")
        report["checks"]["core_status_exit_zero"] = core.returncode == 0
        report["checks"]["core_completed_boot"] = "Runtime staged bootstrap complete" in text and "Niblit fully initialised" in text
        report["checks"]["no_source_only_lean_import_error"] = "No module named 'niblit_lean_algos'" not in text
        report["checks"]["supervised_trading_started"] = "Trading runtime ready" in text
        report["checks"]["no_readiness_log_spin"] = text.count("Still loading") < 30
        report["core_degraded"] = "runtime mode       : degraded" in text
        assert report["checks"]["core_status_exit_zero"] and report["checks"]["core_completed_boot"], "Packaged Core startup failed; see core-status.log"
        assert report["checks"]["supervised_trading_started"], "Packaged trading bridge did not start"
        stored = json.loads((output / "memory.json").read_text(encoding="utf-8"))
        report["checks"]["packaged_memory_write"] = any(marker in json.dumps(fact) for fact in stored.get("facts", []))
        recalled = spawn("core-restart", bundle / "niblit.exe", ["--headless", "--cli"], interactive=True)
        deadline = time.monotonic() + 180
        recovered = None
        while time.monotonic() < deadline and recalled.poll() is None:
            try:
                if request_json("http://127.0.0.1:28500/health").get("service") == "niblit":
                    recovered = request_json("http://127.0.0.1:28500/api/commands/execute", {
                        "command": "recall", "arguments": {"query": marker}}, timeout=10)
                    break
            except Exception:
                pass
            time.sleep(1)
        recovered_entries = (recovered or {}).get("result", {}).get("entries", [])
        report["checks"]["packaged_memory_survives_restart"] = (
            (recovered or {}).get("status") == "success"
            and any(marker in json.dumps(entry) for entry in recovered_entries))
        (output / "restart-recall.json").write_text(json.dumps(recovered, indent=2), encoding="utf-8")
        recalled.communicate(input=b"exit\n", timeout=90)
        with sqlite3.connect(output / "chat.sqlite") as connection:
            history = connection.execute("SELECT role, content FROM chat_history ORDER BY id").fetchall()
        report["checks"]["grounded_conversation_persisted"] = any(
            role == "user" and "Read calculator.py" in content
            and index + 1 < len(history) and history[index + 1][0] == "assistant"
            and "Source files inspected: calculator.py" in history[index + 1][1]
            for index, (role, content) in enumerate(history))
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        for log in logs:
            log.close()
        (output / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if "error" not in report and all(report["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
