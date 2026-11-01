from pathlib import Path
import socket
import subprocess
ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    with socket.socket() as probe:
        running=probe.connect_ex(('127.0.0.1',8767))==0
    if not running:
        log=ROOT/'diagnostics/trading-desk.log'
        log.parent.mkdir(exist_ok=True)
        with log.open('a') as out:
            subprocess.Popen([str(ROOT/'niblit-env/Scripts/pythonw.exe'),str(ROOT/'scripts/run-trading-desk.py')],
                cwd=ROOT,stdin=subprocess.DEVNULL,stdout=out,stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
