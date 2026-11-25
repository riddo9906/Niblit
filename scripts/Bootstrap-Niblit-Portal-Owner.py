"""Create a unique Niblit Portal admin once, without printing credentials.

Run locally and open the protected bootstrap file on your Windows desktop.
Change the password via the Portal after first sign-in and delete the file.
"""
from pathlib import Path
import os
import secrets
import sqlite3
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from modules.server_manager import ServerManager

manager=ServerManager(ROOT/"runtime/client-portal/session.sqlite3")
with manager.db() as db:
    exists=db.execute("SELECT name FROM users WHERE role='admin' AND active=1 LIMIT 1").fetchone()
if exists:
    print("EXISTING_ADMIN_PRESERVED; no credentials regenerated")
    raise SystemExit(0)
username="niblit_owner"
password=secrets.token_urlsafe(34)
destination=Path(r"D:\NiblitAIOS\config\client-portal\owner-initial-credentials.txt")
destination.parent.mkdir(parents=True,exist_ok=True)
if destination.exists():
    raise SystemExit("Existing initial credential file detected; bootstrap not repeated")
manager.add_user(username,password,"admin")
destination.write_text(
    "NIBLIT PORTAL INITIAL ADMIN\n"
    + "Portal: http://127.0.0.1:8768/admin\n"
    + "Username: "+username+"\n"
    + "Password: "+password+"\n"
    + "This file contains temporary initial credentials. After login, change your "
      "password in My Niblit identity and delete this file.\n",
    encoding="utf-8")
subprocess.run(["icacls",str(destination),"/inheritance:r"],capture_output=True,text=True)
user=os.environ.get("USERNAME", "")
if user:
    subprocess.run(["icacls",str(destination),"/grant:r",user+":(R)"],capture_output=True,text=True)
print("ADMIN_CREATED; credentials securely written to local D: file only")
print("CREDENTIAL_FILE_PATH="+str(destination))
