"""Run pytest in a disposable checkout with isolated user and application state.

This runner does not install or resolve dependencies. The selected Python
environment is recorded separately; use a lock file for reproducible installs.
"""

from __future__ import annotations

import argparse
import os
import site
import subprocess
import sys
from pathlib import Path


_SENSITIVE_ENV_MARKERS = (
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "CREDENTIAL",
    "API_KEY",
    "PRIVATE_KEY",
)
_SAFE_HOST_ENV = (
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "SYSTEMDRIVE",
    "PROCESSOR_ARCHITECTURE",
    "NUMBER_OF_PROCESSORS",
    "OS",
)


def _dependency_site() -> str:
    """Return the current interpreter's user site path without displaying it."""
    value = site.getusersitepackages()
    if isinstance(value, list):
        value = os.pathsep.join(value)
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    checkout = args.checkout.resolve()
    run_dir = args.run_dir.resolve()
    if not (checkout / "conftest.py").is_file():
        parser.error(f"checkout has no conftest.py: {checkout}")
    run_dir.mkdir(parents=True, exist_ok=True)
    for name in ("home", "appdata", "localappdata", "temp", "cache", "workspace", "memory"):
        (run_dir / name).mkdir(parents=True, exist_ok=True)

    env = {key: os.environ[key] for key in _SAFE_HOST_ENV if key in os.environ}
    root = str(run_dir)
    env.update(
        {
            "HOME": str(run_dir / "home"),
            "USERPROFILE": str(run_dir / "home"),
            "HOMEDRIVE": str(run_dir.drive),
            "HOMEPATH": str((run_dir / "home").relative_to(run_dir.drive + "\\")),
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
            "FLASK_ENV": "testing",
            "NIBLIT_EVOLVE_INTER_PHASE_SLEEP": "0",
            "NIBLIT_ALE_INTER_PHASE_SLEEP": "0",
            "NIBLIT_SIO_INTER_PHASE_SLEEP": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            # The checkout is nested under the developer's repo on Windows;
            # python-dotenv must not walk upward into the real repository .env.
            "PYTHON_DOTENV_DISABLED": "1",
            "NIBLIT_TEST_DEPENDENCY_SITE": _dependency_site(),
            "NIBLIT_TEST_CHECKOUT": str(checkout),
        }
    )
    # Ensure every cache path exists before third-party libraries inspect it.
    for key in ("HF_HOME", "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE", "TORCH_HOME", "XDG_CACHE_HOME"):
        Path(env[key]).mkdir(parents=True, exist_ok=True)

    code = (
        "import os, site, sys; "
        "site.addsitedir(os.environ['NIBLIT_TEST_DEPENDENCY_SITE']); "
        "sys.path.insert(0, os.environ['NIBLIT_TEST_CHECKOUT']); "
        "sys.argv = ['pytest', *sys.argv[2:]]; "
        "import pytest; raise SystemExit(pytest.main())"
    )
    extra = args.pytest_args
    if extra and extra[0] == "--":
        extra = extra[1:]
    command = [sys.executable, "-c", code, "pytest", *extra]
    (run_dir / "pytest-command.txt").write_text(
        subprocess.list2cmdline([sys.executable, "-c", "<isolated pytest bootstrap>", "pytest", *extra]) + "\n",
        encoding="utf-8",
    )
    with (run_dir / "suite.stdout.txt").open("wb") as stdout, (run_dir / "suite.stderr.txt").open("wb") as stderr:
        completed = subprocess.run(
            command,
            cwd=checkout,
            env=env,
            stdout=stdout,
            stderr=stderr,
            check=False,
        )
    (run_dir / "suite.exit-code.txt").write_text(f"{completed.returncode}\n", encoding="ascii")
    print(f"pytest exit code: {completed.returncode}")
    print(f"stdout: {run_dir / 'suite.stdout.txt'}")
    print(f"stderr: {run_dir / 'suite.stderr.txt'}")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
