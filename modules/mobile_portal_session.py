"""Portal-backed individual mobile sign-in.

Sessions are minted and verified by Niblit's existing Client Portal, not by
a second user table. Loopback-only requests to the Portal; mobile bearer
tokens are the Portal's eight-hour random session credentials.
"""
from __future__ import annotations
from http.cookies import SimpleCookie
import httpx
from fastapi import HTTPException

PORTAL = "http://127.0.0.1:8768"


def _request(method: str, path: str, *, json_body: dict | None = None, session: str = "", csrf: str = "") -> httpx.Response:
    headers = {"Origin": PORTAL}
    if csrf:
        headers["x-csrf-token"] = csrf
    with httpx.Client(timeout=15,trust_env=False,follow_redirects=False) as client:
        return client.request(method, PORTAL+path, headers=headers, json=json_body,
                              cookies={"niblit_session":session} if session else None)


def portal_signup(username: str,password: str,shared_workspace_acknowledged: bool) -> dict:
    if not shared_workspace_acknowledged:
        raise HTTPException(422,"Shared workspace visibility acknowledgement is required")
    try:
        r=_request("POST","/api/signup",json_body={
            "username":username,"password":password,
            "shared_workspace_acknowledged":shared_workspace_acknowledged})
    except httpx.HTTPError as exc:
        raise HTTPException(503,"Client Portal unavailable") from exc
    if r.status_code not in (200,202):
        raise HTTPException(r.status_code,"Client Portal registration could not be accepted")
    return {"status":"pending_approval","message":"Registration requested. Your account becomes available after the Client Portal administrator approves it."}


def portal_login(username: str,password: str) -> dict:
    try:
        r=_request("POST","/api/login",json_body={"username":username,"password":password})
    except httpx.HTTPError as exc:
        raise HTTPException(503,"Client Portal unavailable") from exc
    if r.status_code!=200:
        raise HTTPException(401 if r.status_code==401 else r.status_code,
                            "Invalid credentials, account pending approval or login temporarily unavailable")
    token=r.cookies.get("niblit_session")
    if not token or len(token)<32:
        raise HTTPException(502,"Client Portal did not issue a session")
    return {"session_token":token,"expires_in":28800,"username":username,"session_source":"niblit_client_portal"}


def portal_session(bearer: str | None) -> dict:
    token=(bearer or "").removeprefix("Bearer ").strip()
    if len(token)<32 or len(token)>256:
        raise HTTPException(401,"Client Portal sign-in required")
    try:
        r=_request("GET","/api/session",session=token)
    except httpx.HTTPError as exc:
        raise HTTPException(503,"Client Portal unavailable") from exc
    if r.status_code!=200:
        raise HTTPException(401,"Client Portal session expired or unavailable")
    data=r.json()
    user=data.get("user") or {}
    if not isinstance(user,dict) or not user.get("name"):
        raise HTTPException(502,"Client Portal returned invalid account")
    return {"name":str(user["name"])[:80],"role":str(user.get("role","viewer"))[:30],
            "account_id":str(user.get("account_id") or "")[:64],
            "tier":str(data.get("tier","community"))[:30],
            "workspace":str(data.get("session","shared"))[:80]}


def portal_logout(bearer: str | None) -> dict:
    token=(bearer or "").removeprefix("Bearer ").strip()
    portal_session(bearer)
    try:
        r=_request("GET","/api/session",session=token)
        csrf=(r.json().get("user") or {}).get("csrf","")
        result=_request("POST","/api/logout",session=token,csrf=csrf)
    except httpx.HTTPError as exc:
        raise HTTPException(503,"Client Portal unavailable") from exc
    if result.status_code!=200:
        raise HTTPException(502,"Client Portal logout not acknowledged")
    return {"signed_out":True}
