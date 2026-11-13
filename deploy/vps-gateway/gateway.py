"""Account-bound observation gateway. Run on loopback behind Windows OpenSSH."""
import argparse
from contextlib import closing
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import uuid
import sqlite3
import subprocess
import sys
import threading
import tempfile
import os
import time

from funded_risk import BINDING, decimal, evaluate

POLL_SECONDS = 15
STALE_SECONDS = 30
PROBE_SECONDS = 10
ROOT = Path(__file__).resolve().parent
VERSION = "0.5.1"


def unique_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"Duplicate configuration key: {key}")
        result[key] = value
    return result


def load_config(path):
    cfg = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)
    if set(cfg) != {"account", "terminal", "port", "limits"}:
        raise ValueError("Expected account, terminal, port and limits")
    account = cfg["account"]
    if (set(account) != set(BINDING) or any(type(v) is not str or not v.strip() for v in account.values())
            or not account["login"].isdigit() or int(account["login"]) < 1
            or not account["server"].upper().startswith("XM")
            or account["environment"] not in {"live", "demo", "contest"}
            or not re.fullmatch("[0-9a-f]{20}", account["terminal_id"])):
        raise ValueError("Invalid XM account binding")
    terminal = Path(cfg["terminal"])
    if not terminal.is_absolute() or terminal.name.lower() != "terminal64.exe" or not terminal.is_file():
        raise ValueError("Configure an existing absolute terminal64.exe path")
    if type(cfg["port"]) is not int or not 1024 <= cfg["port"] <= 65535:
        raise ValueError("Invalid local port")
    limits = cfg["limits"]
    if (set(limits) != {"max_positions", "min_equity", "max_margin_fraction"}
            or type(limits["max_positions"]) is not int or limits["max_positions"] < 0
            or decimal(limits["min_equity"]) <= 0
            or not 0 <= decimal(limits["max_margin_fraction"]) <= 1):
        raise ValueError("Invalid monitoring limits")
    return cfg


class Monitor:
    def __init__(self, cfg, database, clock=time.monotonic):
        self.cfg, self.database, self.clock = cfg, database, clock
        self.started_at = time.time()
        self.last_seen = None
        self.connected = False
        self.lock = threading.Lock()
        self.binding = hashlib.sha256(json.dumps(cfg["account"], sort_keys=True).encode()).hexdigest()
        with closing(self.db()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), "
                       "binding TEXT, breaker TEXT, inventory TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS history (kind TEXT, ticket INTEGER, "
                       "fingerprint TEXT, payload TEXT, PRIMARY KEY(kind,ticket))")
            db.execute("CREATE TABLE IF NOT EXISTS checkpoints (id INTEGER PRIMARY KEY, through REAL)")
            db.execute("CREATE TABLE IF NOT EXISTS control_requests (id TEXT PRIMARY KEY, created REAL)")
            db.execute("CREATE TABLE IF NOT EXISTS journal (seq INTEGER PRIMARY KEY, "
                       "observed_at REAL, event TEXT, payload TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS observation_windows (started REAL, through REAL, received REAL, "
                       "PRIMARY KEY(started,through))")
            db.execute("CREATE TABLE IF NOT EXISTS gateway_meta (key TEXT PRIMARY KEY, value TEXT)")
            first = db.execute("SELECT observed_at,payload FROM journal WHERE event='reconciliation' "
                               "AND json_array_length(json_extract(payload,'$.reasons'))>0 ORDER BY seq LIMIT 1").fetchone()
            if first:
                db.execute("INSERT OR IGNORE INTO gateway_meta VALUES ('first_breaker_trigger',?)",
                           (json.dumps({"at": first[0], **json.loads(first[1])}),))
            count = db.execute("SELECT value FROM gateway_meta WHERE key='restart_count'").fetchone()
            db.execute("INSERT INTO gateway_meta VALUES ('restart_count',?) ON CONFLICT(key) "
                       "DO UPDATE SET value=excluded.value", (str(int(count[0])+1 if count else 1),))
            db.execute("PRAGMA user_version=1")
            db.execute("INSERT OR IGNORE INTO state VALUES (1, ?, 'ENTRY_SUSPENDED', NULL)", (self.binding,))
            if db.execute("SELECT binding FROM state").fetchone()[0] != self.binding:
                raise ValueError("Database belongs to another account")

    def db(self):
        return sqlite3.connect(self.database, timeout=2, isolation_level="IMMEDIATE")

    def record(self, db, event, payload):
        db.execute("INSERT INTO journal(observed_at,event,payload) VALUES (?,?,?)",
                   (time.time(), event, json.dumps(payload, sort_keys=True, allow_nan=False)))

    def reconcile(self, snapshot):
        with self.lock, closing(self.db()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            current, previous = db.execute("SELECT breaker, inventory FROM state").fetchone()
            reasons = []
            inventory = previous
            verified = snapshot.get("account") == self.cfg["account"]
            if verified:
                positions, orders = snapshot["positions"], snapshot["orders"]
                inventory = json.dumps({"positions": positions, "orders": orders}, sort_keys=True)
                if previous is not None and previous != inventory:
                    reasons.append("broker_inventory_changed")
                if positions or orders:
                    reasons.append("inventory_has_no_gateway_authorization")
                if any(decimal(p["sl"]) <= 0 for p in positions):
                    reasons.append("missing_protective_stop")
                equity, margin = decimal(snapshot["equity"]), decimal(snapshot["margin"])
                limits = self.cfg["limits"]
                if (equity < decimal(limits["min_equity"]) or margin < 0
                        or margin > equity * decimal(limits["max_margin_fraction"])
                        or len(positions) > limits["max_positions"]):
                    reasons.append("monitoring_limit_breach")
            else:
                reasons.append(snapshot.get("error", "account_binding_mismatch"))
            if self.last_seen is not None and self.clock() - self.last_seen >= STALE_SECONDS:
                reasons.append("observation_gap")
            next_state = current
            if reasons and current != "EMERGENCY_STOP":
                next_state = "RECONCILIATION_REQUIRED"
            db.execute("UPDATE state SET breaker=?, inventory=? WHERE id=1", (next_state, inventory))
            if reasons:
                db.execute("INSERT OR IGNORE INTO gateway_meta VALUES ('first_breaker_trigger',?)",
                           (json.dumps({"at": time.time(), "reasons": reasons,
                                        "expected_account": self.cfg["account"]}),))
            if verified:
                through = snapshot.get("history_through")
                if not isinstance(through, (int, float)) or not 0 < through <= time.time() + 5:
                    raise ValueError("Unverified history checkpoint")
                started = snapshot.get("history_from")
                if not isinstance(started, (int, float)) or not 0 <= started <= through:
                    raise ValueError("Missing history coverage")
                if not isinstance(snapshot.get("history_orders"), list) or not isinstance(snapshot.get("history_deals"), list):
                    raise ValueError("Missing broker history")
                db.execute("INSERT OR IGNORE INTO observation_windows VALUES (?,?,?)", (started, through, time.time()))
                for kind in ("history_orders", "history_deals"):
                    for item in snapshot[kind]:
                        if type(item.get("ticket")) is not int or item["ticket"] <= 0:
                            raise ValueError("Unverified broker ticket")
                        payload = json.dumps(item, sort_keys=True, allow_nan=False)
                        fingerprint = hashlib.sha256(payload.encode()).hexdigest()
                        changed = db.execute(
                            "INSERT INTO history VALUES (?,?,?,?) ON CONFLICT(kind,ticket) DO UPDATE "
                            "SET fingerprint=excluded.fingerprint,payload=excluded.payload "
                            "WHERE history.fingerprint != excluded.fingerprint",
                            (kind, item["ticket"], fingerprint, payload)).rowcount
                        if changed:
                            self.record(db, kind, {"ticket": item["ticket"], "fingerprint": fingerprint})
                db.execute("INSERT INTO checkpoints VALUES (1,?) ON CONFLICT(id) DO UPDATE "
                           "SET through=MAX(through,excluded.through)", (through,))
            self.record(db, "reconciliation", {"verified": verified, "reasons": reasons,
                                               "breaker": next_state,
                                               "snapshot": {k:v for k,v in snapshot.items() if not k.startswith("history_")} if verified else None})
            db.commit()
            self.connected = verified
            if verified:
                self.last_seen = self.clock()

    def history_since(self):
        with self.lock, closing(self.db()) as db:
            row = db.execute("SELECT through FROM checkpoints WHERE id=1").fetchone()
            return max(0, row[0] - 300) if row else time.time() - 86400

    def stop(self, request_id=None, requested_at=None):
        with self.lock, closing(self.db()) as db, db:
            if request_id is not None:
                if str(uuid.UUID(request_id)) != request_id or not __import__("math").isfinite(requested_at) or abs(time.time() - requested_at) > 60:
                    raise ValueError("Expired or malformed control request")
                db.execute("INSERT INTO control_requests VALUES (?,?)", (request_id, requested_at))
            db.execute("UPDATE state SET breaker='EMERGENCY_STOP' WHERE id=1")
            self.record(db, "emergency_stop", {"source": "authenticated_operator"})

    def status(self):
        with self.lock, closing(self.db()) as db:
            breaker, inventory = db.execute("SELECT breaker, inventory FROM state").fetchone()
            last = db.execute("SELECT observed_at, payload FROM journal WHERE event='reconciliation' "
                              "ORDER BY seq DESC LIMIT 1").fetchone()
            age = None if self.last_seen is None else self.clock() - self.last_seen
            fresh = self.connected and age is not None and age < STALE_SECONDS
            if not fresh and breaker != "EMERGENCY_STOP":
                breaker = "RECONCILIATION_REQUIRED"
            evidence = {"account": self.cfg["account"] if fresh else {},
                        "identity_verified": fresh, "connected": fresh}
            # A monitoring observation supplies no funded authorization or trade evidence.
            preflight = evaluate(None, evidence, now=time.time(), breaker=breaker)
            history = {}
            for kind in ("history_orders", "history_deals"):
                history[kind] = [json.loads(row[0]) for row in db.execute(
                    "SELECT payload FROM history WHERE kind=? ORDER BY ticket DESC LIMIT 100", (kind,))]
            checkpoint = db.execute("SELECT through FROM checkpoints WHERE id=1").fetchone()
            trigger = db.execute("SELECT value FROM gateway_meta WHERE key='first_breaker_trigger'").fetchone()
            coverage = db.execute("SELECT MIN(started),MAX(through),COUNT(*) FROM observation_windows").fetchone()
            last_good = db.execute("SELECT observed_at,payload FROM journal WHERE event='reconciliation' "
                                  "AND json_extract(payload,'$.verified')=1 ORDER BY seq DESC LIMIT 1").fetchone()
            recon = {"status": "REVIEW_REQUIRED" if breaker != "ENTRY_SUSPENDED" else "BOUNDED_OBSERVATION",
                     "complete": False, "history_scope": "bounded_windows_not_account_lifetime",
                     "history_coverage": {"from": coverage[0], "through": coverage[1], "windows": coverage[2]},
                     "trigger": json.loads(trigger[0]) if trigger else None,
                     "unresolved_delivery": "not_applicable_gateway_has_no_mutation_path",
                     "warnings": ["account_lifetime_history_not_proven"],
                     "reset_authority": "no_reset_route_in_read_only_milestone"}
            health = {"uptime_seconds": time.time()-self.started_at,
                      "restart_count": int(db.execute("SELECT value FROM gateway_meta WHERE key='restart_count'").fetchone()[0]),
                      "sqlite": "readable", "backup": {"status": "configured_separate_task_not_readback_verified"},
                      "probe": "connected" if fresh else "unavailable",
                      "reconciliation_lag_seconds": max(0,time.time()-checkpoint[0]) if checkpoint else None}
            return {"schema_version": "0.2", "gateway_version": VERSION, "gateway_id": self.binding,
                    "reconciliation": recon, "health": health,
                    "last_verified_observation": json.loads(last_good[1]).get("snapshot") if last_good else None,
                    "request_id": str(uuid.uuid4()), "reported_at": time.time(),
                    "history": history, "history_checkpoint": checkpoint[0] if checkpoint else None,
                    "readiness": "observing" if fresh and breaker == "ENTRY_SUSPENDED" else "blocked",
                    "broker_fresh": fresh, "observation_age_seconds": age, "breaker": breaker,
                    "last_probe_at_unix": last[0] if last else None,
                    "last_probe_reasons": json.loads(last[1])["reasons"] if last else [],
                    "account_observation": json.loads(last[1]).get("snapshot") if last and fresh else None,
                    "execution_enabled": False, "operations": dict(open=False, modify=False,
                    close=False, cancel=False, switch_account=False), "funded_preflight": preflight,
                    "last_verified_inventory": json.loads(inventory) if inventory is not None else None,
                    "effective_config": {"account": self.cfg["account"], "limits": self.cfg["limits"],
                                         "terminal": self.cfg["terminal"],
                                         "bind": f"127.0.0.1:{self.cfg['port']}",
                                         "transport": "ssh_forward_with_bearer",
                                         "configuration_fingerprint": hashlib.sha256(json.dumps(
                                             self.cfg, sort_keys=True).encode()).hexdigest(),
                                         "poll_seconds": POLL_SECONDS, "stale_seconds": STALE_SECONDS}}


def poll(monitor, done):
    while not done.is_set():
        try:
            # File-backed I/O avoids Windows communicate() waiting on an inherited
            # pipe after a timed-out child. Only this owned probe may be killed.
            with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as request, tempfile.TemporaryFile(
                    mode="w+t", encoding="utf-8") as output:
                json.dump({"account": monitor.cfg["account"], "since": monitor.history_since()}, request)
                request.seek(0)
                subprocess.run(
                    [sys.executable, str(ROOT / "broker.py"), monitor.cfg["terminal"], "--bound"],
                    stdin=request, stdout=output, stderr=subprocess.DEVNULL,
                    timeout=PROBE_SECONDS, check=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                output.seek(0)
                encoded = output.read(2_000_001)
                if len(encoded) > 2_000_000:
                    raise ValueError("Bounded broker response exceeded")
                monitor.reconcile(json.loads(encoded))
        except (OSError, ValueError, ArithmeticError, KeyError, TypeError, AttributeError, subprocess.SubprocessError, sqlite3.Error):
            with monitor.lock:
                monitor.connected = False
            try:
                monitor.reconcile({"error": "broker_probe_or_journal_failed"})
            except sqlite3.Error:
                logging.getLogger("niblit.gateway").error(json.dumps({
                    "event": "reconciliation_journal_unavailable", "at": time.time()}))
        done.wait(POLL_SECONDS)


class GatewayServer(HTTPServer):
    def get_request(self):
        sock, address = super().get_request()
        sock.settimeout(3)
        return sock, address


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def reply(self, code, result):
        request_id = self.headers.get("X-Request-Id", "")
        try:
            request_id = str(uuid.UUID(request_id))
        except ValueError:
            request_id = str(uuid.uuid4())
        result["request_id"] = request_id
        logging.getLogger("niblit.gateway").info(json.dumps({
            "event": "http_response", "at": time.time(), "status": code, "request_id": request_id}))
        body = json.dumps(result, allow_nan=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def dispatch(self):
        if self.path.startswith('/demo/'):
            return self.demo_dispatch()
        headers = self.headers.get_all("Authorization", [])
        if len(headers) != 1 or not hmac.compare_digest(headers[0].encode(), self.server.authorization):
            # Separate bearer scope for persistent stop controls.
            stop_auth = getattr(self.server, "stop_authorization", b"")
            if not (self.command == "POST" and self.path == "/emergency-stop"
                    and stop_auth and len(headers) == 1
                    and hmac.compare_digest(headers[0].encode(), stop_auth)):
                return self.reply(401, {"error": "authentication_required"})
        if self.headers.get("Transfer-Encoding") or self.headers.get_all("Content-Length", []) not in ([], ["0"]):
            return self.reply(400, {"error": "request_body_unsupported"})
        try:
            if self.command == "GET" and self.path == "/health":
                return self.reply(200, {"schema_version": "0.2", "service": "niblit-vps-gateway",
                                       "version": VERSION, "gateway_id": self.server.monitor.binding, "process": "up", "execution_enabled": False})
            if self.command == "GET" and self.path in ("/status", "/ready"):
                status = self.server.monitor.status()
                return self.reply(200 if status["broker_fresh"] else 503, status)
            if self.command == "POST" and self.path == "/emergency-stop":
                if not hmac.compare_digest(headers[0].encode(), getattr(self.server, "stop_authorization", b"")):
                    return self.reply(403, {"error": "stop_scope_required"})
                self.server.monitor.stop(self.headers.get("X-Request-Id", ""),
                                         float(self.headers.get("X-Request-Time", "nan")))
                return self.reply(200, {"breaker": "EMERGENCY_STOP", "execution_enabled": False})
            return self.reply(404, {"error": "unsupported_route"})
        except (ValueError, TypeError, OverflowError, sqlite3.IntegrityError):
            return self.reply(409, {"error": "invalid_or_replayed_control", "execution_enabled": False})
        except sqlite3.Error:
            return self.reply(503, {"error": "journal_unavailable", "execution_enabled": False})

    do_GET = do_POST = dispatch

    def demo_dispatch(self):
        auth = self.headers.get_all('Authorization', [])
        expected = getattr(self.server,'demo_authorization',b'')
        if not expected or len(auth)!=1 or not hmac.compare_digest(auth[0].encode(),expected):
            return self.reply(401,{'error':'demo_scope_required'})
        action=self.path[len('/demo/'):]
        if action not in ('status','identity','market','snapshot','prepare','submit','reconcile','cancel-prepared','emergency-stop'):
            return self.reply(404,{'error':'unsupported_demo_route'})
        if (self.command=='GET') != (action in ('status','identity')):
            return self.reply(405,{'error':'invalid_method'})
        try:
            lengths=self.headers.get_all('Content-Length',[])
            if self.headers.get('Transfer-Encoding') or len(lengths)>1:
                raise ValueError('Invalid framing')
            size=int(lengths[0]) if lengths else 0
            if not 0<=size<=100_000:raise ValueError('Body size exceeded')
            body=json.loads(self.rfile.read(size)) if size else {}
            if not isinstance(body,dict):raise ValueError('Object required')
            result=self.server.demo.dispatch(action,body)
            return self.reply(200,{'schema_version':'exness-demo/1',
                              'gateway_id':self.server.demo.identity,'result':result})
        except PermissionError:
            return self.reply(403,{'error':'demo_authority_or_identity_rejected','funded_execution_enabled':False})
        except (ValueError,TypeError,KeyError,OverflowError):
            return self.reply(409,{'error':'demo_preflight_rejected','funded_execution_enabled':False})
        except Exception:
            # Delivery may have begun. Never retry a failed submit automatically.
            return self.reply(503,{'error':'demo_dependency_unavailable','retry_submission':False})


def configure_logging(state_dir):
    folder = Path(state_dir) / "logs"
    folder.mkdir(exist_ok=True)
    handler = RotatingFileHandler(folder / "gateway.jsonl", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    logger = logging.getLogger("niblit.gateway")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
    return handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("state_dir", type=Path)
    parser.add_argument('--demo-config',type=Path)
    parser.add_argument('--demo-max-volume',type=float,default=.01)
    parser.add_argument('--demo-state-name',default='exness-demo')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',args.demo_state_name):
        parser.error('Demo state name must be one directory name, never a path')
    cfg = load_config(args.config)
    configure_logging(args.state_dir)
    token = (args.state_dir / "operator.token").read_bytes().strip()
    if not re.fullmatch(b"[0-9a-f]{64}", token):
        parser.error("operator.token must contain 32 random bytes encoded as lowercase hex")
    stop_token = (args.state_dir / "stop.token").read_bytes().strip()
    if not re.fullmatch(b"[0-9a-f]{64}", stop_token) or stop_token == token:
        parser.error("stop.token must be a distinct 32-byte random hex token")
    monitor = Monitor(cfg, args.state_dir / "gateway.sqlite3")
    with GatewayServer(("127.0.0.1", cfg["port"]), Handler) as server:
        server.authorization, server.monitor = b"Bearer " + token, monitor
        server.stop_authorization = b"Bearer " + stop_token
        if args.demo_config:
            from demo_execution import DemoService,load_demo_config
            import MetaTrader5
            demo_cfg=load_demo_config(args.demo_config)
            if os.path.normcase(demo_cfg['terminal']) != os.path.normcase(cfg['terminal']):
                raise ValueError('Demo must attach to the configured existing terminal')
            credential=(args.state_dir/'demo.token').read_bytes().strip()
            if not re.fullmatch(b'[0-9a-f]{64}',credential) or credential in (token,stop_token):
                raise ValueError('Distinct protected demo credential required')
            server.demo=DemoService(demo_cfg,args.state_dir/args.demo_state_name,MetaTrader5,max_volume=args.demo_max_volume)
            server.demo_authorization=b'Bearer '+credential
        done = threading.Event()
        thread = threading.Thread(target=poll, args=(monitor, done))
        thread.start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            done.set()
            thread.join()


if __name__ == "__main__":
    main()
