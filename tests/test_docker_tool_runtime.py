from pathlib import Path
from tempfile import TemporaryDirectory

from modules import docker_tool_runtime as docker


def test_register_docker_tools_goes_through_governed_registry(monkeypatch):
    from modules import core_tool_runtime

    class FakeLoop:
        def __init__(self):
            self.tools = {}

        def register_capability(self, name, handler, schema):
            self.tools[name] = (handler, schema)

    monkeypatch.setattr(docker, "docker_available", lambda: True)
    loop = FakeLoop()
    old_meta = dict(core_tool_runtime.GOVERNED_COMMAND_METADATA)
    old_actions = dict(core_tool_runtime.COMMAND_PERMISSION_ACTIONS)
    try:
        names = docker.register_docker_tools(loop)
        assert "docker_list_containers" in names
        assert "docker_run_container" in names
        assert core_tool_runtime.GOVERNED_COMMAND_METADATA["docker_list_containers"]["requires_authorization"] is False
        assert core_tool_runtime.GOVERNED_COMMAND_METADATA["docker_run_container"]["requires_authorization"] is True
        assert core_tool_runtime.COMMAND_PERMISSION_ACTIONS["docker_run_container"] == "command.docker.docker_run_container"
    finally:
        core_tool_runtime.GOVERNED_COMMAND_METADATA.clear()
        core_tool_runtime.GOVERNED_COMMAND_METADATA.update(old_meta)
        core_tool_runtime.COMMAND_PERMISSION_ACTIONS.clear()
        core_tool_runtime.COMMAND_PERMISSION_ACTIONS.update(old_actions)


def test_docker_tools_remain_registered_when_daemon_is_temporarily_unavailable(monkeypatch):
    from modules import core_tool_runtime

    class FakeLoop:
        def __init__(self):
            self.tools = {}

        def register_capability(self, name, handler, schema):
            self.tools[name] = (handler, schema)

    monkeypatch.setattr(docker, "docker_available", lambda: False)
    loop = FakeLoop()
    old_meta = dict(core_tool_runtime.GOVERNED_COMMAND_METADATA)
    old_actions = dict(core_tool_runtime.COMMAND_PERMISSION_ACTIONS)
    try:
        names = docker.register_docker_tools(loop)
        assert "docker_list_containers" in names
        assert "docker_run_container" in names
        assert core_tool_runtime.GOVERNED_COMMAND_METADATA["docker_list_containers"]["availability"](None) is False
        assert core_tool_runtime.GOVERNED_COMMAND_METADATA["docker_run_container"]["requires_authorization"] is True
    finally:
        core_tool_runtime.GOVERNED_COMMAND_METADATA.clear()
        core_tool_runtime.GOVERNED_COMMAND_METADATA.update(old_meta)
        core_tool_runtime.COMMAND_PERMISSION_ACTIONS.clear()
        core_tool_runtime.COMMAND_PERMISSION_ACTIONS.update(old_actions)


def test_docker_run_container_uses_validated_argument_array(monkeypatch):
    captured = {}
    monkeypatch.setattr(docker, "_run", lambda args, **kwargs: captured.update(args=args, kwargs=kwargs) or {"output": "container-id"})
    result = docker._run_container("nginx:latest", "niblit-web", ["8080:80", "8443:443/tcp"], "unless-stopped")
    assert result["output"] == "container-id"
    assert captured["args"] == [
        "run", "--detach", "--name", "niblit-web", "--restart", "unless-stopped",
        "--publish", "8080:80", "--publish", "8443:443/tcp", "nginx:latest",
    ]
    assert "shell" not in captured["kwargs"]


def test_docker_run_container_rejects_invalid_ports_without_execution(monkeypatch):
    calls = []
    monkeypatch.setattr(docker, "_run", lambda *args, **kwargs: calls.append(args))
    result = docker._run_container("nginx:latest", None, ["99999:80"], "no")
    assert result["error"].startswith("invalid_port_mapping")
    assert calls == []


def test_compose_up_requires_compose_file_and_down_never_accepts_service_subset(monkeypatch):
    calls = []
    monkeypatch.setattr(docker, "_run", lambda args, **kwargs: calls.append((args, kwargs)) or {"output": "ok"})
    with TemporaryDirectory(prefix=".docker-compose-test-", dir=str(Path(__file__).resolve().parents[1])) as folder:
        root = Path(folder)
        (root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
        up = docker._compose_action("up", str(root), ["web"])
        assert up["output"] == "ok"
        assert calls[0][0] == ["compose", "up", "--detach", "web"]
        down = docker._compose_action("down", str(root), ["web"])
        assert "whole_project" in down["error"]
        assert len(calls) == 1
        down_all = docker._compose_action("down", str(root), None)
        assert down_all["output"] == "ok"
        assert calls[1][0] == ["compose", "down", "--remove-orphans"]


def test_docker_runner_never_uses_a_shell(monkeypatch):
    captured = {}
    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""
    def fake_run(args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return Result()
    monkeypatch.setattr(docker.subprocess, "run", fake_run)
    result = docker._run(["ps", "--all"])
    assert result["output"] == "ok"
    assert captured["args"] == ["docker", "ps", "--all"]
    assert captured["shell"] is False
