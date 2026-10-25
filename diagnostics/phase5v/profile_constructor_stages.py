"""Measure synchronous NiblitCore constructor stages in an isolated process."""
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
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--dependency-site", type=Path, required=True)
    args = parser.parse_args()
    checkout, run = args.checkout.resolve(), args.run_dir.resolve()
    run.mkdir(parents=True, exist_ok=True)
    isolated = {name: run / name for name in (
        "home", "appdata", "localappdata", "temp", "cache", "memory", "workspace"
    )}
    for path in isolated.values():
        path.mkdir(parents=True, exist_ok=True)
    env_keys = (
        "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "SYSTEMDRIVE",
        "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "OS",
    )
    env = {key: os.environ[key] for key in env_keys if key in os.environ}
    env.update({
        "HOME": str(isolated["home"]), "USERPROFILE": str(isolated["home"]),
        "APPDATA": str(isolated["appdata"]), "LOCALAPPDATA": str(isolated["localappdata"]),
        "TEMP": str(isolated["temp"]), "TMP": str(isolated["temp"]),
        "HF_HOME": str(isolated["cache"] / "hf"),
        "HUGGINGFACE_HUB_CACHE": str(isolated["cache"] / "hf" / "hub"),
        "TRANSFORMERS_CACHE": str(isolated["cache"] / "transformers"),
        "TORCH_HOME": str(isolated["cache"] / "torch"),
        "XDG_CACHE_HOME": str(isolated["cache"] / "xdg"),
        "NIBLIT_MEMORY_PATH": str(isolated["memory"] / "niblit_memory.json"),
        "NIBLIT_WORKSPACE_ROOT": str(isolated["workspace"]),
        "NIBLIT_RUNTIME_MODE": "api", "NIBLIT_TRADING_MODE": "observe",
        "NIBLIT_TRADING_ALLOW_EXECUTION": "false",
        "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHON_DOTENV_DISABLED": "1", "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    })
    os.environ.clear()
    os.environ.update(env)
    for key in ("HF_HOME", "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE", "TORCH_HOME", "XDG_CACHE_HOME"):
        Path(env[key]).mkdir(parents=True, exist_ok=True)
    site.addsitedir(str(args.dependency_site.resolve()))
    repo = Path(__file__).resolve().parents[2]
    sys.path[:] = [entry for entry in sys.path if not (
        Path(entry or os.getcwd()).resolve() == repo
        or repo in Path(entry or os.getcwd()).resolve().parents
    )]
    # The disposable venv lives under the repository diagnostics directory, so
    # the repository-path filter above also removes its site-packages. Re-add
    # this explicitly provided dependency root after filtering the checkout.
    site.addsitedir(str(args.dependency_site.resolve()))
    sys.path.insert(0, str(checkout))
    os.chdir(checkout)
    logging.basicConfig(
        filename=str(run / "core.log"), level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    from niblit_core import NiblitCore
    from modules.background_jobs import bg_jobs

    # Keep this measurement from executing external curriculum research.
    real_add = bg_jobs.add

    def intercept_curriculum(fn, interval=None, name=None, push_result=False, initial_delay=0.0):
        if str(name or "").startswith("GradedCurriculum-Teach-"):
            return object()
        return real_add(fn, interval=interval, name=name,
                        push_result=push_result, initial_delay=initial_delay)

    bg_jobs.add = intercept_curriculum
    measures: list[dict[str, object]] = []
    measure_lock = threading.Lock()

    def wrap_method(owner, name: str) -> None:
        original = getattr(owner, name, None)
        if not callable(original):
            return

        def measured(*call_args, **call_kwargs):
            started = time.perf_counter()
            outcome = "ok"
            try:
                return original(*call_args, **call_kwargs)
            except BaseException:
                outcome = "error"
                raise
            finally:
                item = {
                    "owner": getattr(owner, "__name__", type(owner).__name__),
                    "method": name,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                    "thread": threading.current_thread().name,
                    "outcome": outcome,
                }
                with measure_lock:
                    measures.append(item)

        setattr(owner, name, measured)

    methods = (
        "_init_improvements", "_initialize_core", "_start_background_services",
        "_start_trading_api", "_run_async_startup", "_register_commands",
        "_emit_capability_event", "_initialize_modules", "_init_optional_services",
    )
    for method in methods:
        wrap_method(NiblitCore, method)

    router_cls = getattr(sys.modules["niblit_core"], "NiblitRouter", None)
    if router_cls is not None:
        for method in ("__init__", "start", "register_capabilities"):
            wrap_method(router_cls, method)

    from modules.background_jobs import bg_jobs as jobs
    construct_started = time.perf_counter()
    core = NiblitCore(memory_path=str(isolated["memory"] / "niblit_memory.json"))
    constructor_ms = round((time.perf_counter() - construct_started) * 1000, 3)
    ready_started = time.perf_counter()
    ready = core.wait_for_ready(timeout=900)
    wait_for_ready_ms = round((time.perf_counter() - ready_started) * 1000, 3)
    optional_finished = core._deferred_init_event.wait(timeout=180)
    result = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "constructor_ms": constructor_ms,
        "wait_for_ready_ms": wait_for_ready_ms,
        "ready": ready,
        "readiness_status": core.readiness_status(),
        "optional_initialization_finished": optional_finished,
        "curriculum_status": core.graded_curriculum.status()
            if getattr(core, "graded_curriculum", None) else None,
        "job_threads_at_capture": [thread.name for thread in jobs.alive_threads()],
        "stage_timings": sorted(measures, key=lambda item: float(item["elapsed_ms"]), reverse=True),
        "measurement_scope": "wall time around named calls from Core construction and initialization. Background threads are separately labeled; profiler intercepts curriculum teaching registration only.",
    }
    try:
        core.shutdown()
    finally:
        bg_jobs.add = real_add
        (run / "constructor-stages.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({
        "constructor_ms": constructor_ms,
        "wait_for_ready_ms": wait_for_ready_ms,
        "ready": ready,
        "stage_timings": result["stage_timings"],
    }, indent=2))
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
