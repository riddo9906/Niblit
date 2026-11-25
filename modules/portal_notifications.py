"""Client Portal approval email delivery.

Registration creates a pending user first; email notification is best-effort and
recorded for retry. The email points to authenticated /admin review, not to an
unauthenticated account-activation token.
"""
from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote, urlsplit
import os
import smtplib
import ssl


def review_url(username: str) -> str:
    origin = os.environ.get("NIBLIT_PORTAL_REVIEW_ORIGIN",
                            os.environ.get("NIBLIT_PORTAL_REMOTE_ORIGIN", "")).strip()
    if not origin:
        origin = "http://127.0.0.1:8768"
    u=urlsplit(origin)
    if (u.scheme not in {"https","http"} or
        (u.scheme=="http" and u.hostname not in {"127.0.0.1","localhost"}) or
        not u.hostname or u.username or u.password or u.query or u.fragment or
        u.path not in {"", "/"}):
        raise ValueError("Portal review origin must be a trusted HTTPS origin or local loopback")
    return origin.rstrip("/") + "/admin?review=" + quote(username,safe="")


def smtp_settings():
    recipient=os.environ.get("NIBLIT_PORTAL_ADMIN_EMAIL", "").strip()
    username=os.environ.get("NIBLIT_PORTAL_SMTP_USERNAME", "").strip()
    password_file=os.environ.get("NIBLIT_PORTAL_SMTP_PASSWORD_FILE", "").strip()
    host=os.environ.get("NIBLIT_PORTAL_SMTP_HOST","smtp.gmail.com").strip()
    port=int(os.environ.get("NIBLIT_PORTAL_SMTP_PORT","587"))
    if not recipient or not username or not password_file:
        raise RuntimeError("Portal email is not configured")
    if any(c in value for value in (recipient,username,host) for c in "\r\n"):
        raise ValueError("Invalid mail header")
    secret=Path(password_file).read_text(encoding="utf-8").strip()
    if len(secret)<12:
        raise RuntimeError("SMTP credentials are incomplete")
    return recipient,username,secret,host,port


def send_registration_notice(username: str) -> None:
    recipient,sender,secret,host,port=smtp_settings()
    msg=EmailMessage()
    msg["From"]=sender
    msg["To"]=recipient
    msg["Subject"]="Niblit Client Portal — new account awaiting approval"
    msg.set_content(
        "A new Niblit Client Portal registration is awaiting your review.\n\n"
        + "Requested username: " + username + "\n"
        + "Review: " + review_url(username) + "\n\n"
        + "Open the link, sign in as a Client Portal administrator and approve "
          "or revoke the request. Email access alone does not approve an account.\n"
        + "If you did not expect this request, leave it pending or reject it."
    )
    with smtplib.SMTP(host,port,timeout=12) as client:
        client.ehlo()
        client.starttls(context=ssl.create_default_context())
        client.ehlo()
        client.login(sender,secret)
        client.send_message(msg)


def notify_pending_signup(manager, username: str) -> bool:
    """Attempt once and persist delivery outcome. Signup remains pending."""
    with manager.db() as db:
        row=db.execute(
            "SELECT state FROM signup_notifications WHERE name=?",(username,)
        ).fetchone()
        if row and row["state"]=="sent":
            return True
        db.execute(
            "INSERT INTO signup_notifications(name,state,attempts,updated) "
            "VALUES(?,'pending',0,strftime('%s','now')) "
            "ON CONFLICT(name) DO NOTHING",(username,))
    try:
        send_registration_notice(username)
    except (OSError,RuntimeError,ValueError,smtplib.SMTPException):
        with manager.db() as db:
            db.execute("UPDATE signup_notifications SET state='pending',"
                       "attempts=attempts+1,updated=strftime('%s','now') "
                       "WHERE name=?",(username,))
        return False
    with manager.db() as db:
        db.execute("UPDATE signup_notifications SET state='sent',"
                   "attempts=attempts+1,updated=strftime('%s','now') "
                   "WHERE name=?",(username,))
    return True
