"""Start only Niblit's dedicated Docker memory service; never reset its volume."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    from dotenv import dotenv_values
    values = dotenv_values(ROOT / ".env")
    report = {"ready": False, "service": "niblit-memory-lab-qdrant-1"}
    destination = ROOT / "diagnostics/memory-service-startup.json"
    from sys import path
    path.insert(0, str(ROOT))
    from modules.memory_laboratory.setup import Config
    profile_values = dotenv_values(values.get("NIBLIT_MEMORY_LAB_ENV_FILE", str(ROOT / ".env.memory-laboratory")))
    config = Config.from_values(profile_values)
    from urllib.parse import urlsplit
    if urlsplit(config.url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        import httpx
        report["service"] = "configured_remote_qdrant"
        try:
            report["ready"] = httpx.get(config.url + "/collections", headers={"api-key": config.api_key}, timeout=10, follow_redirects=False).is_success
        except httpx.HTTPError:
            report["error"] = "RemoteConnectionUnavailable"
        destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    docker = shutil.which("docker")
    if not docker:
        report["error"] = "DockerNotInstalled"
    else:
        def run(arguments, timeout=15):
            return subprocess.run([docker, *arguments], stdin=subprocess.DEVNULL,
                capture_output=True, timeout=timeout, creationflags=flags)
        try:
            try:
                online = run(["info", "--format", "{{.ServerVersion}}"], timeout=10).returncode == 0
            except subprocess.TimeoutExpired:
                online = False
            if not online:
                desktop = Path(docker).resolve().parents[2] / "Docker Desktop.exe"
                if not desktop.is_file():
                    raise FileNotFoundError("Docker Desktop")
                subprocess.Popen([str(desktop)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, creationflags=flags)
                for _ in range(20):
                    try:
                        if run(["info", "--format", "{{.ServerVersion}}"], timeout=3).returncode == 0:
                            break
                    except subprocess.TimeoutExpired:
                        pass
                    time.sleep(2)
            existing = run(["container", "inspect", "niblit-memory-lab-qdrant-1"])
            if existing.returncode == 0:
                result = run(["start", "niblit-memory-lab-qdrant-1"], timeout=30)
            else:
                profile = values.get("NIBLIT_MEMORY_LAB_ENV_FILE", str(ROOT / ".env.memory-laboratory"))
                result = run(["compose", "--env-file", profile, "-f", str(ROOT / "deploy/memory-laboratory.compose.yml"),
                              "-p", "niblit-memory-lab", "up", "-d", "qdrant"], timeout=120)
            report["container_started"] = result.returncode == 0
            # A running container is not a verified database connection.
            import httpx
            for _ in range(15):
                try:
                    response = httpx.get(config.url + "/collections", headers={"api-key": config.api_key}, timeout=2, follow_redirects=False)
                    if response.is_success:
                        report["ready"] = True
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(1)
        except Exception as exc:
            report["error"] = type(exc).__name__
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
