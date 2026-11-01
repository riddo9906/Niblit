"""Owner-only admission status/recovery. Never registered as a model tool."""
import argparse
import json
from pathlib import Path
import socket
import sqlite3
import httpx
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--recover',action='store_true')
    parser.add_argument('--confirm-producers-stopped',action='store_true')
    args=parser.parse_args()
    values=dotenv_values(ROOT/'.env')
    ledger=values.get('NIBLIT_MEMORY_LAB_LEDGER')
    if not ledger or not Path(ledger).is_file():raise SystemExit('Configured authority ledger is unavailable')
    with sqlite3.connect(ledger,timeout=5) as db:
        row=db.execute('SELECT state,owner,started FROM task_admission WHERE singleton=1').fetchone()
        if not args.recover:
            print(json.dumps({'state':row[0],'owner':row[1],'started':row[2]} if row else {'state':'idle'}));return
        if not args.confirm_producers_stopped:raise SystemExit('Stop all request producers and supply the explicit confirmation flag')
        for port in (5000,8000,8100,8769):
            with socket.socket() as sock:
                sock.settimeout(1)
                if sock.connect_ex(('127.0.0.1',port))==0:raise SystemExit('Stop Core/Cloud/Lean/portal before recovery')
        with socket.socket() as sock:
            sock.settimeout(1);model_running=sock.connect_ex(('127.0.0.1',8766))==0
        if model_running:
            key=(ROOT/'runtime/client-portal/gguf-api-key').read_text().strip()
            with httpx.Client(trust_env=False,timeout=3) as client:
                response=client.get('http://127.0.0.1:8766/slots',headers={'Authorization':'Bearer '+key})
                response.raise_for_status();slots=response.json()
            if not isinstance(slots,list) or any(slot.get('is_processing',True) for slot in slots):
                raise SystemExit('Local model is busy or idle state is unverified; recovery refused')
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM task_admission WHERE singleton=1')
        print('Admission reset after producer-stop confirmation and local model idle check. No inference or trading started.')


if __name__=='__main__':main()
