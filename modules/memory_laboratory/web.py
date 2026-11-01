"""Loopback-only operator desk. Keys and Docker authority stay on the host.

No arbitrary Docker command, shell, model inference, financial order or public
proxy is exposed. Mutations require the same-origin session token and the
existing scoped operator permission checks.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import secrets
import subprocess
import threading
import time
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from .gateway import MemoryGateway
from .runtime import MemoryRuntime, SECRET
from .setup import Config

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets/memory-desk"
CONTAINERS = {"qdrant": "niblit-memory-lab-qdrant-1", "freqtrade": "freqtrade"}


class Review(BaseModel):
    verification: Literal["verified", "rejected"]
    confidence: float = Field(ge=0, le=1)
    evidence: str = Field(min_length=8, max_length=2000)
    source_checked: Literal[True]


class Search(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=8, ge=1, le=20)


class ContainerAction(BaseModel):
    action: Literal["start", "stop", "restart"]


class TutorObservation(BaseModel):
    source_id: str = Field(pattern=r'^[a-zA-Z0-9_.-]{1,80}$')
    content: str = Field(min_length=1,max_length=12000)

class TaskRequest(BaseModel):
    owner: Literal['portal_chat','local_tutor','core_tool_loop','core_inference','autonomous_step']

class TaskFinish(BaseModel):
    token: str = Field(min_length=32,max_length=120)
    uncertain: bool = False


def docker(arguments, timeout=12):
    result = subprocess.run(["docker", *arguments], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError("Docker service unavailable")
    return result.stdout + (result.stderr if arguments and arguments[0]=="logs" else "")


def inspect_containers():
    answer = []
    for alias, name in CONTAINERS.items():
        try:
            info = json.loads(docker(["inspect", name]))[0]
            state = info["State"]
            answer.append({"alias": alias, "name": name, "id": info["Id"][:12],
                "image": info["Config"]["Image"], "status": state["Status"],
                "running": state["Running"], "started_at": state.get("StartedAt"),
                "restart_count": info.get("RestartCount", 0),
                "health": state.get("Health", {}).get("Status", "not_configured"),
                "volumes": [{"type": v["Type"], "destination": v["Destination"]} for v in info.get("Mounts", [])]})
        except Exception as exc:
            answer.append({"alias": alias, "name": name, "running": False, "status": "unavailable", "error": type(exc).__name__})
    try:
        running=[item["name"] for item in answer if item.get("running")]
        metrics=[json.loads(line) for line in docker(["stats","--no-stream","--format","{{json .}}",*running], timeout=6).splitlines()] if running else []
        by_name={item.get("Name"):item for item in metrics}
        for item in answer:
            sample=by_name.get(item["name"],{})
            item["resources"]={"cpu":sample.get("CPUPerc"),"memory":sample.get("MemUsage"),"processes":sample.get("PIDs")}
    except Exception:
        pass
    return answer


def freqtrade_status():
    """Read-only authenticated configuration; never serialize credentials."""
    try:
        config = json.loads((ROOT.parent / "freqtrade/user_data/config.json").read_text())
        api = config.get("api_server", {})
        response = httpx.get("http://127.0.0.1:8080/api/v1/show_config", auth=(api.get("username", ""), api.get("password", "")), timeout=4)
        response.raise_for_status()
        data = response.json()
        return {"available": True, **{key: data.get(key) for key in
            ("dry_run", "state", "strategy", "timeframe", "exchange", "trading_mode", "version")}}
    except Exception as exc:
        return {"available": False, "error": type(exc).__name__}


def local_get(url):
    try:
        result = httpx.get(url, timeout=5)
        result.raise_for_status()
        return {"available": True, "data": result.json()}
    except Exception as exc:
        return {"available": False, "error": type(exc).__name__}


def create_app(gateway=None, *, root=ROOT, port=8766):
    root = Path(root)
    if gateway is None:
        from dotenv import dotenv_values
        values = dotenv_values(root / ".env")
        if values.get("NIBLIT_PERMISSION_FILE"):
            os.environ["NIBLIT_PERMISSION_FILE"] = values["NIBLIT_PERMISSION_FILE"]
        permission_file = Path(values["NIBLIT_PERMISSION_FILE"])
        def authorize(action, namespace, principal):
            # Same existing operator authority, without importing/initializing
            # a second Core or KnowledgeDB in this read/control process.
            try:
                grants = json.loads(permission_file.read_text(encoding="utf-8"))
                return principal == "desktop_operator" and bool(grants.get(f"memory.{action}.{namespace}", False))
            except (OSError, ValueError):
                return False
        gateway = MemoryGateway(Config.from_values(dotenv_values(values["NIBLIT_MEMORY_LAB_ENV_FILE"])), values["NIBLIT_MEMORY_LAB_LEDGER"], authorize=authorize)
    runtime = MemoryRuntime(gateway)
    from modules.task_admission import TaskAuthority,AdmissionBusy
    authority=TaskAuthority(gateway)
    scope = runtime.scope
    token = secrets.token_urlsafe(32)
    origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    app = FastAPI(title="Niblit Memory Desk", docs_url=None, redoc_url=None)
    app.state.session_token = token
    cache, lock = {}, threading.Lock()
    tutor_memory_lock=threading.Lock()

    @app.middleware("http")
    async def local_operator(request: Request, call_next):
        if request.url.path in {'/api/local-tutor/recall','/api/local-tutor/observation','/api/local-tutor/task/acquire','/api/local-tutor/task/finish','/api/local-tutor/task/status'}:
            # Dedicated local tutor capability: read-only, fixed scope and
            # authenticated with the existing private local-model service key.
            # Writes can only append unverified episodic model observations;
            # no fact review, Docker or desktop authority is delegated.
            try:
                local_key=(root/'runtime/client-portal/gguf-api-key').read_text().strip()
                allowed=request.method=='POST' and len(local_key)>=32 and secrets.compare_digest(
                    request.headers.get('authorization',''),'Bearer '+local_key)
            except OSError:allowed=False
            if not allowed:return JSONResponse({'error':'Local tutor authentication required'},status_code=403)
            return await call_next(request)
        if request.headers.get("host") not in {f"127.0.0.1:{port}", f"localhost:{port}", "testserver"}:
            return JSONResponse({"error": "Local host required"}, status_code=403)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if (request.headers.get("origin") not in origins or
                    not secrets.compare_digest(request.headers.get("x-niblit-desk-token", ""), token)):
                return JSONResponse({"error": "Use the local Memory Desk to perform this action"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; frame-src http://127.0.0.1:5000; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.exception_handler(PermissionError)
    async def denied(request, exc):
        return JSONResponse({"error": "This operator action is not enabled in the permission file"}, status_code=403)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"error": str(exc)[:180]}, status_code=400)

    @app.exception_handler(RuntimeError)
    async def unavailable(request, exc):
        return JSONResponse({"error": "The requested local service is unavailable"}, status_code=503)

    @app.exception_handler(httpx.HTTPError)
    async def connection_failed(request, exc):
        return JSONResponse({"error": "The local runtime did not complete the request"}, status_code=503)

    @app.get("/", response_class=HTMLResponse)
    def page():
        return (ASSETS / "index.html").read_text(encoding="utf-8").replace("__SESSION_TOKEN__", html.escape(token))

    @app.get('/api/health')
    def health():
        return {'service':'niblit-memory-desk','tutor_bridge':'scoped_read_and_unverified_observations'}

    @app.post('/api/local-tutor/task/acquire')
    def acquire_task(body:TaskRequest):
        try:return authority.acquire(body.owner)
        except AdmissionBusy as exc:raise HTTPException(409,str(exc))

    @app.post('/api/local-tutor/task/finish')
    def finish_task(body:TaskFinish):
        return authority.finish(body.token,body.uncertain)

    @app.post('/api/local-tutor/task/status')
    def task_status():return authority.status()

    @app.post('/api/local-tutor/recall')
    def tutor_recall(body:Search):
        # The caller cannot select a namespace, principal, URL or model.
        if not tutor_memory_lock.acquire(blocking=False):raise HTTPException(409,'Memory task already active; no queue')
        try:return gateway.retrieve(body.query,**scope,limit=min(body.limit,3))
        finally:tutor_memory_lock.release()

    @app.post('/api/local-tutor/observation')
    def tutor_observation(body:TutorObservation):
        if SECRET.search(body.content):raise ValueError('Credential-like content rejected')
        source='local-tutor://'+body.source_id
        segments=[(body.content[i:i+1000],source+f'#offset={i}') for i in range(0,len(body.content),1000)]
        if not tutor_memory_lock.acquire(blocking=False):raise HTTPException(409,'Memory task already active; no queue')
        try:
            gateway.ingest(segments,source=source,**scope,category='episodic',
                metadata={'source_type':'local_model_reflection','confidence':.2,
                          'provenance':{'source_type':'local_model_reflection','truth_verified':False}})
        finally:tutor_memory_lock.release()
        return {'stored':True,'verification':'unverified','category':'episodic'}

    @app.get("/desk.js")
    def script():
        from fastapi.responses import Response
        return Response((ASSETS / "desk.js").read_text(encoding="utf-8"), media_type="text/javascript")

    @app.get("/desk.css")
    def style():
        from fastapi.responses import Response
        return Response((ASSETS / "desk.css").read_text(encoding="utf-8"), media_type="text/css")

    @app.get("/api/status")
    def status():
        with lock:
            if cache.get("expires", 0) > time.monotonic():
                return cache["status"]
            with ThreadPoolExecutor(max_workers=5) as pool:
                core = pool.submit(local_get, "http://127.0.0.1:5000/api/memory/framework")
                lean = pool.submit(local_get, "http://127.0.0.1:8100/health")
                containers = pool.submit(inspect_containers)
                freqtrade = pool.submit(freqtrade_status)
                qdrant = {"available": False}
                try:
                    response = gateway.backend.client.get("/")
                    response.raise_for_status()
                    items = gateway.backend.request("GET", "/collections")["collections"]
                    qdrant = {"available": True, "version": response.json().get("version"), "collections": len(items), "mode": "local" if httpx.URL(gateway.config.url).host in {"127.0.0.1","localhost","::1"} else "remote"}
                except Exception as exc:
                    qdrant["error"] = type(exc).__name__
                core_status = core.result()
                memory_status = runtime.status()
                memory_status["worker_running"] = core_status.get("data", {}).get("worker_running") if core_status.get("available") else None
                memory_status["worker_owner"] = "niblit_core"
                result = {"checked_at": datetime.now(timezone.utc).isoformat(), "memory": memory_status,
                    "core": core_status, "lean": lean.result(), "containers": containers.result(),
                    "freqtrade": freqtrade.result(), "qdrant": qdrant}
            cache.update(status=result, expires=time.monotonic()+5)
            return result

    @app.get("/api/records")
    def records(query: str="", offset: int=0, limit: int=20, verification: str="", category: str=""):
        gateway.require("read", **scope)
        if not 0 <= offset <= 1000000 or not 1 <= limit <= 100 or len(query)>500:
            raise ValueError("Invalid record browser bounds")
        conditions = ["namespace=?", "principal=?", "active=1"]
        args = [scope["namespace"], scope["principal"]]
        if query:
            conditions.append("json_extract(payload,'$.content') LIKE ?")
            args.append("%"+query+"%")
        for name, value in (("verification",verification), ("category",category)):
            if value:
                conditions.append(f"json_extract(payload,'$.{name}')=?")
                args.append(value)
        where = " AND ".join(conditions)
        with gateway.db() as db:
            total = db.execute("SELECT count(*) FROM records WHERE "+where, args).fetchone()[0]
            rows = db.execute("SELECT payload FROM records WHERE "+where+" ORDER BY rowid DESC LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
        return {"total":total,"offset":offset,"records":[json.loads(r[0]) for r in rows]}

    @app.post("/api/search")
    def search(body: Search):
        # Use the running Core's embedding model rather than loading another.
        response = httpx.post("http://127.0.0.1:5000/api/memory/search", json=body.model_dump(), timeout=60)
        if not response.is_success:
            raise HTTPException(503, "Niblit Core memory search is unavailable")
        return response.json()

    @app.post("/api/records/{record_id}/review")
    def review(record_id: str, body: Review):
        if SECRET.search(body.evidence):
            raise ValueError("Do not include credentials in review evidence")
        cache.clear()
        return gateway.review_record(record_id, **scope, verification=body.verification,
            confidence=body.confidence, evidence=body.evidence)

    @app.post("/api/backup")
    def backup():
        gateway.require("read", **scope)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        result = runtime.backup(root / "runtime/memory-framework/backups" / (stamp+"-"+uuid4().hex[:6]+".sqlite3"))
        with gateway.db() as db:
            gateway.audit(db, "operator.backup.created", None, filename=Path(result["path"]).name)
        return result

    @app.post("/api/retry")
    def retry():
        gateway.require("ingest", **scope)
        with gateway.db() as db:
            cursor = db.execute("UPDATE ingestion_outbox SET next_attempt=0 WHERE state='pending' AND json_extract(body,'$.namespace')=? AND json_extract(body,'$.principal')=?", (scope["namespace"], scope["principal"]))
            count = cursor.rowcount
            gateway.audit(db, "operator.queue.retry", None, count=count)
        cache.clear()
        return {"ready_for_retry": count, "worker_owned_by_core": True}

    @app.post("/api/consolidate")
    def consolidate():
        from .consolidation import Consolidator
        result = Consolidator(gateway, **scope).tick()
        return {"proposals": result["proposals"], "scanned": result["scanned"], "evidence_unchanged": True}

    @app.post("/api/documents")
    async def document(request: Request, filename: str):
        gateway.require("ingest", **scope)
        from modules.chat_attachments import AttachmentStore, MAX_BYTES
        data = bytearray()
        async for piece in request.stream():
            data.extend(piece)
            if len(data)>MAX_BYTES:
                raise HTTPException(413, "Maximum document size is 50 MB")
        def ingest():
            store = AttachmentStore()
            info = store.ingest(filename, bytes(data))
            _, chunks, _ = store.documents[info["id"]]
            ids = []
            for index, chunk in enumerate(chunks):
                source = f"document://{info['sha256']}/{info['name']}/page/{chunk['page']}/chunk/{index}"
                ids.append(runtime.enqueue(source=source, content=chunk["text"], metadata={"confidence":.5,
                    "source_type":"uploaded_document", "provenance":{"name":info["name"],"page":chunk["page"],"document_hash":info["sha256"]}}))
            return {"queued":len(ids),"name":info["name"],"pages":info["page_count"],"truncated":info["truncated"],"verification":"unverified"}
        from starlette.concurrency import run_in_threadpool
        result = await run_in_threadpool(ingest)
        cache.clear()
        return result

    @app.post("/api/containers/{alias}")
    def control(alias: str, body: ContainerAction):
        if alias not in CONTAINERS:
            raise HTTPException(404, "Unknown managed container")
        info = json.loads(docker(["inspect", CONTAINERS[alias]]))[0]
        expected = "qdrant/qdrant:" if alias=="qdrant" else "freqtradeorg/freqtrade:"
        if not info["Config"]["Image"].startswith(expected):
            raise HTTPException(409, "Container identity does not match the managed service")
        if alias=="freqtrade" and body.action in {"start","restart"}:
            config = json.loads((root.parent / "freqtrade/user_data/config.json").read_text())
            if config.get("dry_run") is not True:
                raise HTTPException(409, "This desk starts Freqtrade only in dry-run mode")
            parameters=info["Config"]
            command=parameters.get("Cmd") or []
            configured=[command[i+1] for i,item in enumerate(command[:-1]) if item in {"--config","-c"}]
            overrides=[value.split("=",1)[1].lower() for value in parameters.get("Env",[]) if value.startswith("FREQTRADE__DRY_RUN=")]
            data_mount=next((item for item in info.get("Mounts",[]) if item.get("Destination")=="/freqtrade/user_data"),None)
            expected_data=(root.parent/"freqtrade/user_data").resolve()
            if (parameters.get("Entrypoint") != ["freqtrade"] or not command or command[0]!="trade"
                    or configured != ["/freqtrade/user_data/config.json"]
                    or any(value not in {"true","1"} for value in overrides)
                    or not data_mount or Path(data_mount["Source"]).resolve()!=expected_data):
                raise HTTPException(409, "Container configuration differs from the verified dry-run environment")
        docker([body.action, CONTAINERS[alias]], timeout=40)
        with gateway.db() as db:
            gateway.audit(db, "operator.container."+body.action, None, container=CONTAINERS[alias])
        cache.clear()
        return {"requested":body.action,"container":CONTAINERS[alias],"data_volumes_preserved":True}

    @app.get("/api/containers/{alias}/logs")
    def logs(alias: str):
        if alias not in CONTAINERS:
            raise HTTPException(404, "Unknown managed container")
        output = docker(["logs","--tail","70",CONTAINERS[alias]])
        import re
        output = SECRET.sub("[credential redacted]", output)
        output = re.sub(r"(?i)(password|api_key|api-key|authorization|token)\s*[:=]\s*[^\s,;]+", r"\1=[redacted]", output)
        return {"container":CONTAINERS[alias],"logs":output[-16000:]}

    return app
