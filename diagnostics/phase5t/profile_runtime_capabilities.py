"""Profile the live runtime_capabilities report in a disposable Niblit checkout.

The harness calls only NiblitCore._cmd_runtime_capabilities. It does not run
the governed tool loop or mutate production modules. State, logs, and caches
are redirected to the supplied run directory before importing Niblit.
"""

from __future__ import annotations

import cProfile
import hashlib
import json
import logging
import os
import pstats
import platform
import site
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable


def _safe_environment(run_dir: Path) -> dict[str, str]:
    user_site = site.getusersitepackages()
    if isinstance(user_site, list):
        user_site = os.pathsep.join(user_site)
    safe_names = (
        "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "SYSTEMDRIVE",
        "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "OS",
    )
    env = {name: os.environ[name] for name in safe_names if name in os.environ}
    for name in ("home", "appdata", "localappdata", "temp", "cache", "memory", "workspace"):
        (run_dir / name).mkdir(parents=True, exist_ok=True)
    home = run_dir / "home"
    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "APPDATA": str(run_dir / "appdata"),
            "LOCALAPPDATA": str(run_dir / "localappdata"),
            "TEMP": str(run_dir / "temp"),
            "TMP": str(run_dir / "temp"),
            "HF_HOME": str(run_dir / "cache" / "huggingface"),
            "HUGGINGFACE_HUB_CACHE": str(run_dir / "cache" / "huggingface" / "hub"),
            "TRANSFORMERS_CACHE": str(run_dir / "cache" / "transformers"),
            "TORCH_HOME": str(run_dir / "cache" / "torch"),
            "XDG_CACHE_HOME": str(run_dir / "cache" / "xdg"),
            "NIBLIT_MEMORY_PATH": str(run_dir / "memory" / "niblit_memory.json"),
            "NIBLIT_WORKSPACE_ROOT": str(run_dir / "workspace"),
            "NIBLIT_RUNTIME_MODE": "api",
            "NIBLIT_TRADING_MODE": "observe",
            "NIBLIT_TRADING_ALLOW_EXECUTION": "false",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHON_DOTENV_DISABLED": "1",
            "NIBLIT_PROFILE_DEPENDENCY_SITE": str(user_site),
        }
    )
    for name in ("HF_HOME", "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE", "TORCH_HOME", "XDG_CACHE_HOME"):
        Path(env[name]).mkdir(parents=True, exist_ok=True)
    return env


def _summary(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"calls": 0, "total_ms": 0.0, "mean_ms": 0.0, "median_ms": 0.0, "max_ms": 0.0}
    return {
        "calls": len(values),
        "total_ms": round(sum(values), 3),
        "mean_ms": round(statistics.mean(values), 3),
        "median_ms": round(statistics.median(values), 3),
        "max_ms": round(max(values), 3),
    }


def _field_projection(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        projected = {}
        for key, value in row.items():
            lowered = str(key).lower()
            if key in {"name", "aliases", "category", "available", "availability_reason"} or any(
                marker in lowered for marker in ("permission", "authority", "risk")
            ):
                projected[key] = value
        result.append(projected)
    return result


def run(checkout: Path, run_dir: Path, warm_calls: int = 5) -> dict[str, Any]:
    checkout = checkout.resolve()
    run_dir = run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    env = _safe_environment(run_dir)
    os.environ.clear()
    os.environ.update(env)
    site.addsitedir(env["NIBLIT_PROFILE_DEPENDENCY_SITE"])
    source_root = Path(__file__).resolve().parents[2]
    cleaned_path = []
    for entry in sys.path:
        try:
            candidate = Path(entry or os.getcwd()).resolve()
            if candidate == source_root or source_root in candidate.parents:
                continue
        except (OSError, RuntimeError):
            pass
        cleaned_path.append(entry)
    sys.path[:] = cleaned_path
    sys.path.insert(0, str(checkout))
    os.chdir(checkout)
    logging.basicConfig(
        filename=str(run_dir / "core.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    report: dict[str, Any] = {
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "checkout": str(checkout),
            "isolated_run_dir": str(run_dir),
            "runtime_mode": env["NIBLIT_RUNTIME_MODE"],
            "trading_mode": env["NIBLIT_TRADING_MODE"],
            "trading_execution_allowed": False,
            "network_disabled": False,
            "model_artifacts_copied": False,
        },
        "status": "starting",
        "measurements": {},
    }

    start = time.perf_counter()
    import_start = time.perf_counter()
    print("loading NiblitCore after environment isolation", flush=True)
    from niblit_core import NiblitCore  # imported only after environment isolation

    report["measurements"]["module_import_ms"] = round((time.perf_counter() - import_start) * 1000, 3)
    construct_start = time.perf_counter()
    print("constructing core with isolated memory path", flush=True)
    core = NiblitCore(memory_path=str(run_dir / "memory" / "niblit_memory.json"))
    report["measurements"]["constructor_return_ms"] = round((time.perf_counter() - construct_start) * 1000, 3)
    ready_start = time.perf_counter()
    print("waiting for deferred core initialization (maximum 900 seconds)", flush=True)
    ready = bool(core.wait_for_ready(timeout=900))
    initialized_at = time.perf_counter()
    report["measurements"]["wait_for_ready_ms"] = round((time.perf_counter() - ready_start) * 1000, 3)
    report["initialization_state"] = {
        "ready": ready,
        "phase": getattr(core, "_deferred_init_phase", "unknown"),
        "current_phase": getattr(core, "_current_init_phase", ""),
    }
    print(f"core initialization state: ready={ready}, phase={report['initialization_state']['phase']}", flush=True)
    if not ready or core.command_registry is None:
        report["status"] = "initialization_failed_or_timed_out"
        report["measurements"]["total_elapsed_before_exit_ms"] = round((time.perf_counter() - start) * 1000, 3)
        (run_dir / "profile.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        try:
            core.shutdown()
        except Exception:
            pass
        return report

    registry = core.command_registry
    stage_samples: dict[str, list[float]] = defaultdict(list)
    command_samples: dict[str, list[float]] = defaultdict(list)
    event_samples: dict[str, list[float]] = defaultdict(list)
    state: dict[str, Any] = {"snapshot": None, "events": 0, "provider_status": None}

    def wrap(owner: Any, attr: str, key: str, after: Callable[[Any, tuple, dict, Any], None] | None = None) -> None:
        original = getattr(owner, attr)

        def measured(*args: Any, **kwargs: Any) -> Any:
            t0 = time.perf_counter()
            result = None
            try:
                result = original(*args, **kwargs)
                return result
            finally:
                elapsed = (time.perf_counter() - t0) * 1000
                stage_samples[key].append(elapsed)
                if after is not None:
                    after(owner, args, kwargs, result)

        setattr(owner, attr, measured)

    def capture_availability(owner: Any, args: tuple, kwargs: dict, result: Any) -> None:
        metadata = args[0] if args else None
        prefix = str(getattr(metadata, "prefix", "<unknown>"))
        # Wrapper duration is recorded separately by key after the method returns.
        command_samples[prefix].append(stage_samples["_availability"][-1])

    def capture_snapshot(owner: Any, args: tuple, kwargs: dict, result: Any) -> None:
        if isinstance(result, list):
            state["snapshot"] = _field_projection(result)

    def capture_provider_status(owner: Any, args: tuple, kwargs: dict, result: Any) -> None:
        if isinstance(result, dict):
            state["provider_status"] = {
                str(k): bool(v) if isinstance(v, (bool, int)) else str(type(v).__name__)
                for k, v in result.items()
            }

    def capture_event(owner: Any, args: tuple, kwargs: dict, result: Any) -> None:
        state["events"] += 1

    wrap(core, "_provider_status_snapshot", "provider_status_snapshot", capture_provider_status)
    wrap(core, "_command_registry_snapshot", "command_context_snapshot")
    wrap(registry, "detailed_report", "detailed_report")
    wrap(registry, "capability_snapshot", "capability_snapshot", capture_snapshot)
    wrap(registry, "_effective_context", "effective_context")
    wrap(registry, "_availability", "_availability", capture_availability)
    if registry._event_emitter is not None:
        original_emitter = registry._event_emitter

        def measured_emitter(*args: Any, **kwargs: Any) -> Any:
            t0 = time.perf_counter()
            try:
                state["events"] += 1
                return original_emitter(*args, **kwargs)
            finally:
                event_samples[str(args[0] if args else "unknown")].append((time.perf_counter() - t0) * 1000)

        registry._event_emitter = measured_emitter

    outputs: list[str] = []
    snapshots: list[list[dict[str, Any]]] = []
    run_durations: list[float] = []
    first_profiler = cProfile.Profile()
    for index in range(warm_calls + 1):
        state["snapshot"] = None
        state["events"] = 0
        query_start = time.perf_counter()
        if index == 0:
            output = first_profiler.runcall(core._cmd_runtime_capabilities, "runtime_capabilities")
        else:
            output = core._cmd_runtime_capabilities("runtime_capabilities")
        elapsed = (time.perf_counter() - query_start) * 1000
        outputs.append(str(output))
        snapshots.append(state["snapshot"] or [])
        run_durations.append(elapsed)
        print(f"capability report run {index}: {elapsed:.3f} ms", flush=True)
        report["measurements"]["cold_report_ms" if index == 0 else f"warm_report_{index}_ms"] = round(elapsed, 3)
        report.setdefault("per_run", []).append(
            {
                "index": index,
                "kind": "cold_after_initialization" if index == 0 else "warm",
                "elapsed_ms": round(elapsed, 3),
                "availability_checks": len(stage_samples["_availability"]),
                "events_forwarded": state["events"],
                "output_sha256": hashlib.sha256(outputs[-1].encode("utf-8")).hexdigest(),
                "capabilities_sha256": hashlib.sha256(
                    json.dumps(snapshots[-1], sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
                "capability_count": len(snapshots[-1]),
                "provider_count": len([key for key in (state["provider_status"] or {}) if key != "active"]),
            }
        )

    stats = pstats.Stats(first_profiler).sort_stats("cumulative")
    stats.stream = open(run_dir / "cprofile_first.txt", "w", encoding="utf-8")
    stats.print_stats(80)
    stats.stream.close()

    report["status"] = "completed"
    report["command_count"] = len(registry.commands)
    report["provider_count"] = len([key for key in (state["provider_status"] or {}) if key != "active"])
    report["reported_capability_count"] = len(snapshots[0]) if snapshots else 0
    report["repeatability"] = {
        "report_text_identical": all(value == outputs[0] for value in outputs[1:]),
        "capability_state_identical": all(value == snapshots[0] for value in snapshots[1:]),
        "runs": len(outputs),
    }
    report["timings"] = {
        key: _summary(values)
        for key, values in sorted(stage_samples.items())
    }
    report["event_timings"] = {
        key: _summary(values)
        for key, values in sorted(event_samples.items())
    }
    report["slowest_availability_checks"] = [
        {"command": key, **_summary(values)}
        for key, values in sorted(command_samples.items(), key=lambda pair: max(pair[1], default=0), reverse=True)[:30]
    ]
    report["initialization_elapsed_before_queries_ms"] = round((initialized_at - start) * 1000, 3)
    report["total_elapsed_ms"] = round((time.perf_counter() - start) * 1000, 3)
    report["provider_status"] = state["provider_status"] or {}
    report["capabilities"] = snapshots[0] if snapshots else []
    (run_dir / "profile.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    try:
        core.shutdown()
        report["shutdown"] = "completed"
    except Exception as exc:
        report["shutdown"] = f"error:{type(exc).__name__}"
    (run_dir / "profile.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--warm-calls", type=int, default=5)
    options = parser.parse_args()
    payload = run(options.checkout, options.run_dir, max(1, options.warm_calls))
    print(json.dumps({key: payload.get(key) for key in ("status", "initialization_state", "measurements", "command_count", "provider_count", "reported_capability_count", "repeatability", "total_elapsed_ms", "shutdown")}, indent=2))
