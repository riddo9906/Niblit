#!/usr/bin/env python3
"""Reusable sidecar runtime control client (UNIX + TCP)."""

from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SidecarTarget:
    transport: str  # unix|tcp
    socket_path: str | None = None
    host: str | None = None
    port: int | None = None


@dataclass
class NormalizedResponse:
    status: str
    result: Any
    raw: dict[str, Any]
    malformed_lines: list[str]


def normalize_response(payload: dict[str, Any], malformed_lines: list[str] | None = None) -> NormalizedResponse:
    malformed = malformed_lines or []
    if not isinstance(payload, dict):
        return NormalizedResponse(
            status="error",
            result="Malformed response payload",
            raw={"payload": payload},
            malformed_lines=malformed,
        )

    status = str(payload.get("status", "ok"))
    result = payload.get("result", payload.get("message", ""))

    if status == "ok" and result in (None, ""):
        status = "ok"

    return NormalizedResponse(
        status=status,
        result=result,
        raw=payload,
        malformed_lines=malformed,
    )


class SidecarClient:
    def __init__(self, target: SidecarTarget, *, timeout: float = 300.0) -> None:
        self.target = target
        self.timeout = timeout

    def _connect(self, timeout: float) -> socket.socket:
        if self.target.transport == "unix":
            if not self.target.socket_path:
                raise OSError("UNIX transport requires socket_path")
            conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            conn.settimeout(timeout)
            conn.connect(self.target.socket_path)
            return conn

        if self.target.transport == "tcp":
            if not self.target.host or self.target.port is None:
                raise OSError("TCP transport requires host + port")
            conn = socket.create_connection((self.target.host, self.target.port), timeout=timeout)
            conn.settimeout(timeout)
            return conn

        raise OSError(f"Unsupported transport: {self.target.transport}")

    @staticmethod
    def _decode_json_lines(data: bytes) -> tuple[list[dict[str, Any]], list[str]]:
        responses: list[dict[str, Any]] = []
        malformed: list[str] = []
        for raw_line in data.decode("utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                malformed.append(line)
                continue
            if isinstance(payload, dict):
                responses.append(payload)
            else:
                malformed.append(line)
        return responses, malformed

    def send_recv(self, payload: dict[str, Any], *, timeout: float | None = None) -> NormalizedResponse:
        effective_timeout = self.timeout if timeout is None else timeout
        conn = self._connect(effective_timeout)
        malformed: list[str] = []
        try:
            conn.settimeout(effective_timeout)
            conn.sendall((json.dumps(payload) + "\n").encode("utf-8"))

            deadline = time.monotonic() + effective_timeout
            buf = b""
            while time.monotonic() < deadline:
                try:
                    chunk = conn.recv(8192)
                except TimeoutError:
                    break
                if not chunk:
                    break
                buf += chunk
                # If we have at least one complete line, continue reading until EOF/timeout
                if b"\n" in buf:
                    continue

            responses, malformed = self._decode_json_lines(buf)
            if not responses:
                return NormalizedResponse(
                    status="error",
                    result="No valid JSON response received",
                    raw={"raw": buf.decode("utf-8", errors="replace")},
                    malformed_lines=malformed,
                )
            return normalize_response(responses[-1], malformed)
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def stream_responses(self, payload: dict[str, Any], *, timeout: float | None = None) -> list[NormalizedResponse]:
        effective_timeout = self.timeout if timeout is None else timeout
        conn = self._connect(effective_timeout)
        outputs: list[NormalizedResponse] = []
        malformed: list[str] = []
        try:
            conn.settimeout(effective_timeout)
            conn.sendall((json.dumps(payload) + "\n").encode("utf-8"))

            deadline = time.monotonic() + effective_timeout
            buf = b""
            while time.monotonic() < deadline:
                try:
                    chunk = conn.recv(8192)
                except TimeoutError:
                    break
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        payload_obj = json.loads(line.decode("utf-8", errors="replace"))
                    except json.JSONDecodeError:
                        malformed.append(line.decode("utf-8", errors="replace"))
                        continue
                    if not isinstance(payload_obj, dict):
                        malformed.append(line.decode("utf-8", errors="replace"))
                        continue
                    outputs.append(normalize_response(payload_obj, malformed_lines=list(malformed)))

            if buf.strip():
                malformed.append(buf.decode("utf-8", errors="replace"))

            if not outputs:
                outputs.append(
                    NormalizedResponse(
                        status="error",
                        result="No valid response from sidecar",
                        raw={"malformed": malformed},
                        malformed_lines=malformed,
                    )
                )
            return outputs
        finally:
            try:
                conn.close()
            except OSError:
                pass


def format_response(resp: NormalizedResponse, mode: str = "pretty") -> str:
    mode = mode.lower().strip()
    if mode == "raw":
        return str(resp.raw)
    if mode == "json":
        return json.dumps(
            {
                "status": resp.status,
                "result": resp.result,
                "raw": resp.raw,
                "malformed_lines": resp.malformed_lines,
            },
            ensure_ascii=False,
        )

    parts = [f"status={resp.status}"]
    if resp.result not in (None, ""):
        parts.append(f"result={resp.result}")
    if resp.malformed_lines:
        parts.append(f"malformed_lines={len(resp.malformed_lines)}")
    return " | ".join(parts)
