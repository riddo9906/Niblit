"""Profile a fresh Core process with isolated state and credential-free env."""
from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import site
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--dependency-site", type=Path, required=True)
    args = parser.parse_args()
    checkout = args.checkout.resolve()
    run = args.run_dir.resolve()
    run.mkdir(parents=True, exist_ok=True)

    paths = {name: run / name for name in (
        "home", "appdata", "localappdata", "temp", "cache", "memory", "workspace"
    )}
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    safe_names = (
        "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "SYSTEMDRIVE",
        "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "OS",
    )
    safe_env = {key: os.environ[key] for key in safe_names if key in os.environ}
    safe_env.update({
        "HOME": str(paths["home"]), "USERPROFILE": str(paths["home"]),
        "APPDATA": str(paths["appdata"]), "LOCALAPPDATA": str(paths["localappdata"]),
        "TEMP": str(paths["temp"]), "TMP": str(paths["temp"]),
        "HF_HOME": str(paths["cache"] / "hf"),
        "HUGGINGFACE_HUB_CACHE": str(paths["cache"] / "hf" / "hub"),
        "TRANSFORMERS_CACHE": str(paths["cache"] / "transformers"),
        "TORCH_HOME": str(paths["cache"] / "torch"),
        "XDG_CACHE_HOME": str(paths["cache"] / "xdg"),
        "NIBLIT_MEMORY_PATH": str(paths["memory"] / "niblit_memory.json"),
        "NIBLIT_WORKSPACE_ROOT": str(paths["workspace"]),
        "NIBLIT_RUNTIME_MODE": "api", "NIBLIT_TRADING_MODE": "observe",
        "NIBLIT_TRADING_ALLOW_EXECUTION": "false",
        "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHON_DOTENV_DISABLED": "1", "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    })
    for key in ("HF_HOME", "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE", "TORCH_HOME", "XDG_CACHE_HOME"):
        Path(safe_env[key]).mkdir(parents=True, exist_ok=True)
    os.environ.clear()
    os.environ.update(safe_env)
    site.addsitedir(str(args.dependency_site.resolve()))

    repo = Path(__file__).resolve().parents[2]
    sys.path[:] = [
        entry for entry in sys.path
        if not (Path(entry or os.getcwd()).resolve() == repo
                or repo in Path(entry or os.getcwd()).resolve().parents)
    ]
    sys.path.insert(0, str(checkout))
    os.chdir(checkout)
    logging.basicConfig(
        filename=str(run / "core.log"), level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    import_started = time.perf_counter()
    from niblit_core import NiblitCore
    import_ms = (time.perf_counter() - import_started) * 1000

    waits = []
    layer_elapsed = {}
    lock = threading.Lock()
    original = NiblitCore._init_with_timeout

    def timed(core, layer_fn, layer_name, timeout=0):
        started = time.perf_counter()
        finished = threading.Event()

        def measured_layer():
            worker_started = time.perf_counter()
            try:
                layer_fn()
            finally:
                with lock:
                    layer_elapsed[layer_name] = (time.perf_counter() - worker_started) * 1000
                finished.set()

        ok = original(core, measured_layer, layer_name, timeout)
        with lock:
            waits.append({
                "layer": layer_name,
                "wait_ms": round((time.perf_counter() - started) * 1000, 3),
                "completed_in_wait": bool(ok),
                "worker_finished": finished.is_set(),
            })
        return ok

    # Install before construction starts the deferred initializer. Suppress
    # only curriculum's live research job in this timing harness; its callback
    # remains exercised with deterministic fakes in the regression tests.
    from modules.background_jobs import bg_jobs
    original_add = bg_jobs.add
    scheduled_curriculum_jobs = []

    def managed_add(fn, interval=None, name=None, push_result=False, initial_delay=0.0):
        if str(name or "").startswith("GradedCurriculum-Teach-"):
            scheduled_curriculum_jobs.append({"name": name, "initial_delay": initial_delay})
            return object()
        return original_add(fn, interval=interval, name=name,
                            push_result=push_result, initial_delay=initial_delay)

    NiblitCore._init_with_timeout = timed
    bg_jobs.add = managed_add
    construct_started = time.perf_counter()
    core = NiblitCore(memory_path=str(paths["memory"] / "niblit_memory.json"))
    constructor_ms = (time.perf_counter() - construct_started) * 1000
    ready_started = time.perf_counter()
    ready = core.wait_for_ready(timeout=900)
    ready_ms = (time.perf_counter() - ready_started) * 1000
    optional_wait_started = time.perf_counter()
    optional_finished = core._deferred_init_event.wait(timeout=180)
    optional_completion_wait_ms = (time.perf_counter() - optional_wait_started) * 1000
    readiness = core.readiness_status()
    curriculum = getattr(core, "graded_curriculum", None)
    curriculum_status = curriculum.status() if curriculum is not None else None

    frames = sys._current_frames()
    layer_threads = {}
    for thread in threading.enumerate():
        if thread.name.startswith("niblit-layer-"):
            frame = frames.get(thread.ident)
            stack = []
            while frame:
                stack.append({
                    "file": frame.f_code.co_filename,
                    "line": frame.f_lineno,
                    "function": frame.f_code.co_name,
                })
                frame = frame.f_back
            layer_threads[thread.name] = {
                "alive": thread.is_alive(), "stack_oldest_to_newest": list(reversed(stack))
            }

    result = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0], "platform": platform.platform(),
        "ready": ready, "readiness_status": readiness,
        "import_ms": round(import_ms, 3),
        "constructor_ms": round(constructor_ms, 3),
        "wait_for_ready_ms": round(ready_ms, 3),
        "optional_initialization_finished": optional_finished,
        "optional_completion_wait_ms": round(optional_completion_wait_ms, 3),
        "total_import_construct_and_ready_ms": round(import_ms + constructor_ms + ready_ms, 3),
        "layer_waits": waits,
        "layer_worker_function_elapsed_ms": {key: round(value, 3) for key, value in layer_elapsed.items()},
        "optional_curriculum_task_status": curriculum_status,
        "scheduled_curriculum_jobs": scheduled_curriculum_jobs,
        "live_layer_threads_at_ready": layer_threads,
        "network_policy": "No external credentials inherited; HF/Transformers offline; only the GradedCurriculum teaching-job registration is intercepted so this profiler does not issue its external research calls. Other startup network attempts were not instrumented.",
    }
    try:
        core.shutdown()
    finally:
        bg_jobs.add = original_add
        NiblitCore._init_with_timeout = original
        (run / "readiness.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({
        key: result[key] for key in (
            "ready", "import_ms", "constructor_ms", "wait_for_ready_ms",
        "optional_initialization_finished", "optional_completion_wait_ms",
            "total_import_construct_and_ready_ms", "readiness_status",
            "layer_waits", "optional_curriculum_task_status",
        )
    }, indent=2))
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
