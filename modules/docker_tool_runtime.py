"""Niblit's governed Docker Desktop capability adapter.

All commands use subprocess argument arrays (never a shell). Read-only
inspection tools are available automatically; container and compose mutations
are routed through Core's one-time approval mechanism.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger("Niblit.DockerTools")
_CONTAINER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_IMAGE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254}$")
_PORT_MAP = re.compile(r"^(?P<host>\d{1,5}):(?P<container>\d{1,5})(?:/(?P<proto>tcp|udp))?$", re.I)
_SERVICE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")


def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True, text=True, timeout=4, check=False, shell=False,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except Exception:
        return False


def _run(args: list[str], *, cwd: str | None = None, timeout: int = 30):
    try:
        result = subprocess.run(
            ["docker", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return {"error": "docker_command_timed_out"}
    except FileNotFoundError:
        return {"error": "docker_cli_not_found"}
    except Exception as exc:
        log.warning("Docker command failed: %s", type(exc).__name__)
        return {"error": f"docker_{type(exc).__name__}"}
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Docker command failed").strip()
        return {"error": detail[:4000], "returncode": result.returncode}
    return {"output": (result.stdout or "").strip(), "returncode": 0}


def _container(value: Any) -> str:
    text = str(value or "").strip()
    if not _CONTAINER_NAME.fullmatch(text):
        raise ValueError("invalid_container_name_or_id")
    return text


def _compose_dir(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("project_dir_required")
    path = Path(raw).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError("project_dir_must_be_a_directory")
    if any(part.casefold().startswith(".env") or part.casefold() in {".git", ".ssh"} for part in path.parts):
        raise ValueError("blocked_by_niblit_sensitive_path_policy")
    if not any((path / name).is_file() for name in ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml")):
        raise ValueError("docker_compose_file_not_found")
    return str(path)


def _services(values: Any) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list) or len(values) > 20:
        raise ValueError("services_must_be_a_list_of_at_most_20_names")
    result = []
    for value in values:
        name = str(value)
        if not _SERVICE_NAME.fullmatch(name):
            raise ValueError("invalid_compose_service_name")
        result.append(name)
    return result


def _schema(name: str, description: str, properties: dict, required: list[str] | None = None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


def register_docker_tools(loop) -> list[str]:
    # Registration is deterministic and independent of daemon timing. Runtime
    # availability is evaluated by the governed metadata predicate, so a
    # transient Docker Desktop startup delay cannot permanently erase tools
    # from this process's capability registry.
    if not docker_available():
        log.info("Docker Desktop daemon unavailable; registering tools as unavailable")

    from modules.core_tool_runtime import COMMAND_PERMISSION_ACTIONS, GOVERNED_COMMAND_METADATA

    tools = [
        ("docker_status", "Read Docker Desktop daemon version and availability.", {}, [], lambda **kw: _run(["version", "--format", "{{.Server.Version}}"])),
        ("docker_list_containers", "List Docker containers and their state without exposing environment variables.", {}, [], lambda **kw: _run(["ps", "--all", "--format", "{{json .}}"])),
        ("docker_list_images", "List local Docker images and their tags.", {}, [], lambda **kw: _run(["images", "--format", "{{json .}}"])),
        ("docker_compose_list", "List Docker Compose projects and their status.", {}, [], lambda **kw: _run(["compose", "ls", "--all", "--format", "json"])),
        ("docker_inspect_container", "Inspect safe container metadata only (name, state, image and restart policy; no environment values).", {"container": {"type": "string", "minLength": 1, "maxLength": 128}}, ["container"], lambda container, **kw: _inspect_container(container)),
        ("docker_container_logs", "Read the last 1–200 lines of a container log. Logs may contain secrets and require approval.", {"container": {"type": "string"}, "tail": {"type": "integer", "minimum": 1, "maximum": 200, "default": 80}}, ["container"], lambda container, tail=80, **kw: _container_logs(container, tail)),
        ("docker_run_container", "Start a detached container from an image with optional name and port mappings. Requires approval.", {"image": {"type": "string", "minLength": 1, "maxLength": 255}, "name": {"type": "string", "maxLength": 128}, "ports": {"type": "array", "items": {"type": "string"}}, "restart_policy": {"type": "string", "enum": ["no", "always", "unless-stopped", "on-failure"]}}, ["image"], lambda image, name=None, ports=None, restart_policy="no", **kw: _run_container(image, name, ports, restart_policy)),
        ("docker_start_container", "Start an existing stopped Docker container. Requires approval.", {"container": {"type": "string"}}, ["container"], lambda container, **kw: _container_action("start", container)),
        ("docker_stop_container", "Stop a running Docker container. Requires approval.", {"container": {"type": "string"}}, ["container"], lambda container, **kw: _container_action("stop", container)),
        ("docker_compose_up", "Start Docker Compose services in a directory containing a Compose file. Requires approval.", {"project_dir": {"type": "string"}, "services": {"type": "array", "items": {"type": "string"}}}, ["project_dir"], lambda project_dir, services=None, **kw: _compose_action("up", project_dir, services)),
        ("docker_compose_down", "Stop and remove Compose containers and networks (never removes volumes). Requires approval.", {"project_dir": {"type": "string"}, "services": {"type": "array", "items": {"type": "string"}}}, ["project_dir"], lambda project_dir, services=None, **kw: _compose_action("down", project_dir, services)),
    ]

    read_only = {
        "docker_status", "docker_list_containers", "docker_list_images",
        "docker_compose_list", "docker_inspect_container",
    }
    registered = []
    for name, description, properties, required, handler in tools:
        schema = _schema(name, description, properties, required)
        loop.register_capability(name, handler, schema)
        safe = name in read_only
        GOVERNED_COMMAND_METADATA[name] = {
            "category": "Docker Desktop",
            "risk_class": "low" if safe else "high",
            "side_effect_level": "read_only" if safe else "mutation",
            "requires_authorization": not safe,
            "availability": lambda core: docker_available(),
        }
        if not safe:
            COMMAND_PERMISSION_ACTIONS[name] = f"command.docker.{name}"
        registered.append(name)
    log.info("Registered %d governed Docker Desktop tools", len(registered))
    return registered


def _inspect_container(container: str):
    try:
        name = _container(container)
    except ValueError as exc:
        return {"error": str(exc)}
    return _run([
        "inspect", "--format",
        "{{.Name}}|{{.State.Status}}|{{.Config.Image}}|{{.HostConfig.RestartPolicy.Name}}",
        name,
    ])


def _container_logs(container: str, tail: int = 80):
    try:
        name = _container(container)
        count = max(1, min(200, int(tail)))
    except (ValueError, TypeError) as exc:
        return {"error": str(exc)}
    return _run(["logs", "--tail", str(count), name], timeout=20)


def _run_container(image: str, name: str | None, ports: list[str] | None, restart_policy: str):
    image_ref = str(image or "").strip()
    if not _IMAGE_REF.fullmatch(image_ref):
        return {"error": "invalid_image_reference"}
    args = ["run", "--detach"]
    if name:
        if not _CONTAINER_NAME.fullmatch(str(name)):
            return {"error": "invalid_container_name"}
        args.extend(["--name", str(name)])
    if restart_policy not in {"no", "always", "unless-stopped", "on-failure"}:
        return {"error": "invalid_restart_policy"}
    if restart_policy != "no":
        args.extend(["--restart", restart_policy])
    if ports is not None and not isinstance(ports, list):
        return {"error": "ports_must_be_a_list"}
    for port in ports or []:
        match = _PORT_MAP.fullmatch(str(port))
        if not match or not (1 <= int(match.group("host")) <= 65535 and 1 <= int(match.group("container")) <= 65535):
            return {"error": f"invalid_port_mapping:{port}"}
        args.extend(["--publish", str(port)])
    args.append(image_ref)
    return _run(args, timeout=120)


def _container_action(action: str, container: str):
    try:
        name = _container(container)
    except ValueError as exc:
        return {"error": str(exc)}
    return _run([action, name], timeout=60)


def _compose_action(action: str, project_dir: str, services: list[str] | None):
    try:
        directory = _compose_dir(project_dir)
        selected = _services(services)
    except (ValueError, OSError) as exc:
        return {"error": str(exc)}
    if action == "up":
        args = ["compose", "up", "--detach", *selected]
    else:
        if selected:
            return {"error": "compose_down_stops_the_whole_project; use docker_stop_container for a single container"}
        args = ["compose", "down", "--remove-orphans"]
    return _run(args, cwd=directory, timeout=240)
