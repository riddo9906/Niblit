"""Niblit mobile control service: loopback-only, Client-Portal-authenticated.

Runs as a second FastAPI listener *inside* packaged niblit.exe when Core API
starts. A private TLS/Tailscale proxy may forward to 127.0.0.1:8214.
Never exposes raw Core API, arbitrary shell commands or funded trading.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal
import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from modules.mobile_portal_session import (
    portal_login, portal_logout, portal_session, portal_signup,
)

app = FastAPI(title="Niblit private Android gateway", docs_url=None,
              redoc_url=None, openapi_url=None)
OWNER_ROLES = frozenset({"owner", "admin", "administrator", "superadmin"})
MODEL_PORTS = {"qwen2.5-coder-3b": 8966, "qwen2.5-coder-14b": 8967}
ALLOWED_SYMBOLS = frozenset({"ETHUSDm", "BTCUSDm", "EURUSD", "EURUSDm"})


def require_local(request: Request):
    if request.client is None or request.client.host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(403, "Use the private TLS mobile proxy")


def authorized(request: Request, authorization: str | None, *, control=False) -> dict:
    require_local(request)
    account = portal_session(authorization)
    if control and account.get("role", "").lower() not in OWNER_ROLES:
        raise HTTPException(403, "Client Portal administrator role required for trading controls")
    return account


def core_url() -> str:
    value = os.getenv("NIBLIT_API_PORT", "5000")
    if not value.isascii() or not value.isdigit() or not 1024 <= int(value) <= 65535:
        raise HTTPException(503, "Core API port unavailable")
    return f"http://127.0.0.1:{int(value)}"


def core_json(path: str, *, body: dict | None = None) -> dict:
    # Only fixed routes authored below. No user-supplied API path.
    with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
        try:
            if body is None:
                r = client.get(core_url() + path)
            else:
                # Operator nonce is exclusively obtained on local loopback and never
                # returned to the mobile client.
                session = client.get(core_url() + "/api/trading/sessions")
                session.raise_for_status()
                nonce = session.json().get("operator_nonce")
                if not isinstance(nonce, str) or len(nonce) < 20:
                    raise HTTPException(503, "Core operator session unavailable")
                r = client.post(core_url() + path, json=body,
                                headers={"Origin":core_url(), "x-niblit-trading-nonce":nonce})
            r.raise_for_status()
            result = r.json()
            if not isinstance(result, dict):
                raise HTTPException(502, "Invalid Core response")
            return result
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            raise HTTPException(code if code in (400, 401, 403, 404, 409, 422, 429, 503) else 502,
                                "Niblit Core declined the requested operation") from exc
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise HTTPException(503, "Niblit Core is unavailable") from exc


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=256)


class Signup(Credentials):
    shared_workspace_acknowledged: bool = False


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system","user","assistant"]
    content: str = Field(min_length=1, max_length=6000)


class Chat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: Literal["qwen2.5-coder-3b","qwen2.5-coder-14b"]
    messages: list[ChatMessage] = Field(min_length=1, max_length=12)
    max_tokens: int = Field(default=384, ge=1, le=768)


class DemoConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: Literal["ETHUSDm","BTCUSDm","EURUSD","EURUSDm"]
    minutes: int = Field(ge=15, le=240)
    volume_lots: float = Field(gt=0, le=.10)
    max_trades: int = Field(ge=1, le=10)
    max_positions: int = Field(ge=1, le=5)
    risk_pct: float = Field(gt=0, le=.25)
    risk_cash: float = Field(gt=0, le=25)


class Activation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=32,max_length=32,pattern=r"^[0-9a-f]{32}$")
    spec_hash: str = Field(min_length=16,max_length=128)


class StopSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = Field(default=None,max_length=64)


def validated_scope(body: DemoConfiguration) -> dict:
    # Broker precision, minimum step and cumulative risk are also checked
    # downstream by Core's native MT5 session review.
    return {
        "adapter":"mt5", "symbol":body.symbol, "seconds":body.minutes * 60,
        "limits":{
            "max_volume":body.volume_lots,
            "max_entries":body.max_trades,
            "max_positions":body.max_positions,
            "risk_fraction":body.risk_pct / 100.0,
            "risk_cash":body.risk_cash,
        },
    }


@app.get("/mobile/health")
def health(request:Request):
    require_local(request)
    return {"status":"ok", "service":"niblit-mobile-in-core", "binding":"127.0.0.1",
            "core_port":int(os.getenv("NIBLIT_API_PORT", "5000"))}


@app.post("/mobile/signup", status_code=202)
def signup(body:Signup,request:Request):
    require_local(request)
    return portal_signup(body.username,body.password,body.shared_workspace_acknowledged)


@app.post("/mobile/login")
def login(body:Credentials,request:Request):
    require_local(request)
    return portal_login(body.username,body.password)


@app.get("/mobile/me")
def me(request:Request,authorization:str|None=Header(default=None)):
    return authorized(request,authorization)


@app.post("/mobile/logout")
def logout(request:Request,authorization:str|None=Header(default=None)):
    authorized(request,authorization)
    return portal_logout(authorization)


@app.get("/mobile/system")
def system(request:Request,authorization:str|None=Header(default=None)):
    user=authorized(request,authorization)
    try:
        status=core_json("/health")
        core_online=True
    except HTTPException:
        status={}
        core_online=False
    return {"core_online":core_online, "runtime":"R14", "service":"mobile gateway in Niblit.exe",
            "role":user.get("role","viewer"),
            "demo_controls_available":user.get("role","").lower() in OWNER_ROLES,
            "core_health":status.get("status","unavailable")}


@app.get("/mobile/models")
def models(request:Request,authorization:str|None=Header(default=None)):
    authorized(request,authorization)
    online=[]
    with httpx.Client(timeout=1.0,trust_env=False) as client:
        for name,port in MODEL_PORTS.items():
            try:
                r=client.get(f"http://127.0.0.1:{port}/health")
                if r.status_code==200:
                    online.append({"id":name,"object":"model"})
            except httpx.HTTPError:
                continue
    return {"object":"list","data":online}


@app.post("/mobile/chat")
def chat(body:Chat,request:Request,authorization:str|None=Header(default=None)):
    authorized(request,authorization)
    key_path=Path(os.getenv("NIBLIT_MOBILE_INFERENCE_KEY_FILE",
                    r"D:\NiblitAIOS\config\trading-software-20261115\inference-key"))
    try:
        key=key_path.read_text(encoding="utf-8").strip()
        if len(key)<32: raise ValueError("Inference key unavailable")
        with httpx.Client(timeout=240,trust_env=False) as client:
            response=client.post(f"http://127.0.0.1:{MODEL_PORTS[body.model]}/v1/chat/completions",
                json={"model":body.model,"messages":[x.model_dump() for x in body.messages],
                      "max_tokens":body.max_tokens,"stream":False,"temperature":.2},
                headers={"Authorization":"Bearer "+key})
            response.raise_for_status()
            result=response.json()
        if result.get("model")!=body.model or not result.get("choices"):
            raise ValueError("Model response mismatch")
        answer=result["choices"][0]["message"]["content"]
        if not isinstance(answer,str): raise ValueError("Missing model content")
        return {"model":body.model,"choices":[{"message":{"role":"assistant","content":answer}}]}
    except (httpx.HTTPError,OSError,ValueError,KeyError,TypeError,IndexError) as exc:
        raise HTTPException(503,"Local inference is unavailable") from exc


@app.get("/mobile/observations")
def observations(request:Request,authorization:str|None=Header(default=None)):
    authorized(request,authorization)
    status=core_json("/api/trading/sessions")
    rows=[]
    for row in status.get("observers",[])[:50]:
        if not isinstance(row,dict):continue
        assessment=row.get("assessment") or {}
        rows.append({
            "adapter":str(row.get("adapter",""))[:24],
            "symbol":str(row.get("symbol",""))[:80],
            "running":row.get("running") is True,
            "side":assessment.get("side","wait") if isinstance(assessment,dict) else "wait",
            "error":str(row.get("error") or "")[:160],
        })
    return {"observers":rows,"execution_available":False}


@app.get("/mobile/trading/sessions")
def sessions(request:Request,authorization:str|None=Header(default=None)):
    user=authorized(request,authorization)
    raw=core_json("/api/trading/sessions")
    active=[{"id":x.get("id"),"state":x.get("state"),"expires":x.get("expires"),
             "adapter":(x.get("spec") or {}).get("adapter"),
             "symbol":(x.get("spec") or {}).get("symbol"),
             "duration_seconds":(x.get("spec") or {}).get("seconds")}
            for x in raw.get("sessions",[])[:30] if isinstance(x,dict)]
    positions=[{"symbol":x.get("symbol"),"state":x.get("state"),"action":x.get("action"),
                "updated":x.get("updated")} for x in raw.get("orders",[])[:40]
               if isinstance(x,dict) and x.get("adapter")=="mt5"]
    return {"sessions":active,"orders":positions,"real_money_enabled":False,
            "can_control_demo":user.get("role","").lower() in OWNER_ROLES}


@app.post("/mobile/trading/readiness")
def readiness(body:DemoConfiguration,request:Request,authorization:str|None=Header(default=None)):
    authorized(request,authorization,control=True)
    review=core_json("/api/trading/sessions/readiness",body=validated_scope(body))
    return {"activation_eligible":review.get("activation_eligible",False),
            "blockers":[{"code":str(x.get("code",""))[:64],
                         "reason":str(x.get("reason",""))[:240]}
                        for x in review.get("blockers",[]) if isinstance(x,dict)],
            "requested":body.model_dump(),"execution_performed":False}


@app.post("/mobile/trading/propose")
def propose(body:DemoConfiguration,request:Request,authorization:str|None=Header(default=None)):
    authorized(request,authorization,control=True)
    raw=core_json("/api/trading/sessions/propose",body=validated_scope(body))
    return {"id":raw.get("id"),"spec_hash":raw.get("spec_hash"),"state":raw.get("state"),
            "symbol":(raw.get("spec") or {}).get("symbol"),"duration_seconds":(raw.get("spec") or {}).get("seconds"),
            "execution_performed":False}


@app.post("/mobile/trading/activate")
def activate(body:Activation,request:Request,authorization:str|None=Header(default=None)):
    authorized(request,authorization,control=True)
    raw=core_json("/api/trading/sessions/activate",body={
        "id":body.id,"spec_hash":body.spec_hash,"acknowledgement":"ACTIVATE_BOUNDED_DEMO_SESSION"})
    return {"id":raw.get("id"),"state":raw.get("state"),
            "symbol":(raw.get("spec") or {}).get("symbol"),
            "expires":raw.get("expires"),"real_money_enabled":False}


@app.post("/mobile/trading/stop")
def stop(body:StopSession,request:Request,authorization:str|None=Header(default=None)):
    authorized(request,authorization,control=True)
    raw=core_json("/api/trading/sessions/stop",body={"id":body.id})
    return {"state":raw.get("state"),"observation_continues":raw.get("observation_continues",False)}


@app.get("/mobile/apk")
def apk(request:Request):
    require_local(request)
    apk_path=Path(r"D:\NiblitAIOS\releases\mobile\niblit-ai-v0.3.0-debug.apk")
    if not apk_path.is_file(): raise HTTPException(503,"Mobile APK not yet built")
    return FileResponse(apk_path, filename="niblit-ai-v0.3.0-debug.apk",
                        media_type="application/vnd.android.package-archive",
                        headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"})


def start_mobile_gateway(*,emit=print,port:int=8214):
    """Start packaged Portal + mobile API under the same desktop Core process."""
    import threading,uvicorn
    if os.getenv("NIBLIT_MOBILE_GATEWAY_AUTOSTART","0")!="1":
        return None
    if port!=8214: raise ValueError("Mobile port is fixed to private loopback 8214")
    # Restore only the approved Client Portal mail configuration in memory.
    mail_file=Path(r"D:\NiblitAIOS\config\client-portal\portal-mail.env")
    if mail_file.is_file():
        keys={"NIBLIT_PORTAL_ADMIN_EMAIL", "NIBLIT_PORTAL_SMTP_USERNAME",
              "NIBLIT_PORTAL_SMTP_HOST", "NIBLIT_PORTAL_SMTP_PORT",
              "NIBLIT_PORTAL_SMTP_PASSWORD_FILE", "NIBLIT_PORTAL_REVIEW_ORIGIN"}
        for line in mail_file.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key,value=line.split("=",1)
                if key in keys and value.strip():
                    os.environ.setdefault(key,value.strip())
    # A normal main niblit.exe boot now owns the Portal too; no extra Python
    # command or independently maintained mobile backend is needed.
    from modules.server_manager import create_app
    from modules.server_manager import ServerManager
    portal_db=Path(os.getenv("NIBLIT_PORTAL_DB_PATH",""))
    if not portal_db.is_file():
        raise RuntimeError("Original approved Client Portal database is missing")
    portal_app=create_app(manager=ServerManager(portal_db))
    portal=uvicorn.Server(uvicorn.Config(portal_app,host="127.0.0.1",port=8768,
                             log_level="warning",access_log=False,proxy_headers=False))
    portal_thread=threading.Thread(target=portal.run,name="NiblitClientPortal",daemon=True)
    portal_thread.start()
    server=uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",port=port,
                              log_level="warning",access_log=False,proxy_headers=False))
    thread=threading.Thread(target=server.run,name="NiblitMobileGateway",daemon=True)
    thread.start()
    emit("Niblit Client Portal and Android gateway starting on private loopback")
    # A reference keeps the Portal server tied to this Core's lifecycle.
    server._niblit_portal_server=portal
    server._niblit_portal_thread=portal_thread
    return server,thread
