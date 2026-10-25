"""Run three fresh isolated Core readiness profiles and preserve exit evidence."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--dependency-site", type=Path, required=True)
    args = parser.parse_args()
    root = args.run_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).with_name("profile_core_readiness.py").resolve()
    results = []
    for index in range(1, 4):
        run = root / f"cold-start-{index}"
        run.mkdir(parents=True, exist_ok=False)
        command = [
            sys.executable, str(script),
            "--checkout", str(args.checkout.resolve()),
            "--run-dir", str(run),
            "--dependency-site", str(args.dependency_site.resolve()),
        ]
        (run / "command.txt").write_text(
            subprocess.list2cmdline(command) + "\n", encoding="utf-8"
        )
        completed = subprocess.run(
            command, cwd=str(args.checkout.resolve()),
            text=True, capture_output=True, check=False,
        )
        (run / "profile.stdout.txt").write_text(completed.stdout, encoding="utf-8")
        (run / "profile.stderr.txt").write_text(completed.stderr, encoding="utf-8")
        (run / "exit-code.txt").write_text(f"{completed.returncode}\n", encoding="ascii")
        summary = {"run": run.name, "exit_code": completed.returncode}
        try:
            report = json.loads((run / "readiness.json").read_text(encoding="utf-8"))
            summary.update({
                "ready": report["ready"],
                "import_ms": report["import_ms"],
                "constructor_ms": report["constructor_ms"],
                "wait_for_ready_ms": report["wait_for_ready_ms"],
                "essential_layers_ms": round(sum(
                    item["wait_ms"] for item in report["layer_waits"]
                    if item["layer"] != "5-Optional"
                ), 3),
                "optional_layer_ms": next(
                    (item["wait_ms"] for item in report["layer_waits"]
                     if item["layer"] == "5-Optional"), None
                ),
                "optional_services": report["readiness_status"]["optional_services"],
                "curriculum_state": report["optional_curriculum_task_status"]["teaching"]["1"]["state"]
                    if report["optional_curriculum_task_status"]
                    and "1" in report["optional_curriculum_task_status"].get("teaching", {})
                    else None,
            })
        except (OSError, KeyError, ValueError, TypeError):
            summary["profile_json"] = "missing or invalid"
        results.append(summary)
        print(json.dumps(summary))
    (root / "cold-start-summary.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    return 0 if all(result.get("exit_code") == 0 and result.get("ready") for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
