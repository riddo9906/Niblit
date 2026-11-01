"""Idempotent local Memory Desk launcher; does not spawn another Core."""
import argparse
from pathlib import Path
import socket
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--open',action='store_true')
    args=parser.parse_args()
    with socket.socket() as check:
        running=check.connect_ex(('127.0.0.1',8772))==0
    if not running:
        log=ROOT/'diagnostics/memory-desk-server.log'
        log.parent.mkdir(exist_ok=True)
        with log.open('a',encoding='utf-8') as output:
            subprocess.Popen([str(ROOT/'niblit-env/Scripts/pythonw.exe'),str(ROOT/'scripts/run-memory-desk.py')],
                cwd=ROOT,stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if args.open:
        import webbrowser
        for _ in range(30):
            with socket.socket() as check:
                if check.connect_ex(('127.0.0.1',8772))==0:
                    break
            time.sleep(.5)
        webbrowser.open('http://127.0.0.1:8772/')
