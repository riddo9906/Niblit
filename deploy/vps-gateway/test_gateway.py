import copy
from contextlib import closing
import http.client
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace as Row
import unittest

from broker import observe
from gateway import GatewayServer, Handler, Monitor, load_config


class BrokerDouble:
    def __init__(self, path):
        self.terminal = Row(path=str(path.parent), data_path=str(path.parent / "data"), connected=True)
        self.account = Row(company="XM fixture", login=123, server="XM-fixture", currency="USD",
                           trade_mode=2, equity=1000, margin=0)
        self.positions = ()
        self.orders = ()
        self.detached = False

    def initialize(self, path, *, timeout):
        assert Path(path).parent == Path(self.terminal.path) and timeout == 5000
        return True

    def terminal_info(self):
        return self.terminal

    def account_info(self):
        return self.account

    def positions_get(self):
        return self.positions

    def orders_get(self):
        return self.orders

    def symbol_info(self, symbol):
        return None

    def history_orders_get(self, start, end):
        return getattr(self, "past_orders", ())

    def history_deals_get(self, start, end):
        return getattr(self, "past_deals", ())

    def shutdown(self):
        self.detached = True


class GatewayTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "terminal64.exe"
        self.path.touch()
        self.broker = BrokerDouble(self.path)
        self.account = observe(self.broker, self.path)
        self.cfg = dict(account=self.account, terminal=str(self.path), port=18765,
                        limits=dict(max_positions=0, min_equity="100", max_margin_fraction="0.25"))
        self.database = self.path.parent / "state.sqlite3"
        self.now = 10
        self.monitor = Monitor(self.cfg, self.database, lambda: self.now)

    def snapshot(self):
        return observe(self.broker, self.path, self.account)

    def test_discovery_rejects_wrong_terminal_and_disconnect(self):
        self.assertTrue(self.broker.detached)
        self.broker.terminal.connected = False
        with self.assertRaisesRegex(RuntimeError, "broker_disconnected"):
            self.snapshot()
        with self.assertRaisesRegex(ValueError, "explicit_terminal_required"):
            observe(self.broker, Path("terminal64.exe"))

    def test_identity_swap_during_inventory(self):
        def switch():
            self.broker.account.login = 124
            return ()
        self.broker.orders_get = switch
        with self.assertRaisesRegex(RuntimeError, "account_changed_during_read"):
            self.snapshot()

    def test_partial_inventory_and_wrong_account_are_rejected(self):
        self.broker.orders = None
        with self.assertRaisesRegex(RuntimeError, "incomplete_broker_inventory"):
            self.snapshot()
        self.broker.account.login = 124
        with self.assertRaisesRegex(RuntimeError, "account_binding_mismatch"):
            self.snapshot()

    def test_staleness_and_durable_loss_latch(self):
        self.monitor.reconcile(self.snapshot())
        self.assertTrue(self.monitor.status()["broker_fresh"])
        self.assertEqual(self.monitor.status()["funded_preflight"]["decision"], "REJECT")
        self.now += 30
        self.assertFalse(self.monitor.status()["broker_fresh"])
        self.monitor.reconcile({"error": "broker_disconnected"})
        self.monitor.reconcile(self.snapshot())
        restarted = Monitor(self.cfg, self.database)
        restarted.reconcile(self.snapshot())
        self.assertEqual(restarted.status()["breaker"], "RECONCILIATION_REQUIRED")

    def test_positions_and_pending_orders_are_journaled_and_never_adopted(self):
        self.monitor.reconcile(self.snapshot())
        self.broker.positions = (Row(ticket=2, symbol="EURUSD", type=0, volume=.1, sl=0, tp=0),)
        self.broker.orders = (Row(ticket=3, symbol="EURUSD", type=2, volume_current=.1,
                                  price_open=1, sl=0, tp=0),)
        self.monitor.reconcile(self.snapshot())
        self.assertEqual(self.monitor.status()["last_verified_inventory"]["positions"][0]["ticket"], 2)
        self.assertEqual(self.monitor.status()["last_verified_inventory"]["orders"][0]["ticket"], 3)
        self.assertEqual(self.monitor.status()["breaker"], "RECONCILIATION_REQUIRED")
        self.broker.positions = self.broker.orders = ()
        self.monitor.reconcile(self.snapshot())
        self.assertEqual(self.monitor.status()["breaker"], "RECONCILIATION_REQUIRED")

    def test_limit_breach_and_db_binding(self):
        self.broker.account.margin = 251
        self.monitor.reconcile(self.snapshot())
        self.assertEqual(self.monitor.status()["breaker"], "RECONCILIATION_REQUIRED")
        cfg = copy.deepcopy(self.cfg)
        cfg["account"]["login"] = "124"
        with self.assertRaisesRegex(ValueError, "another account"):
            Monitor(cfg, self.database)

    def test_configuration_rejects_duplicates_and_unknown_authority_flags(self):
        path = self.path.parent / "gateway.json"
        path.write_text(json.dumps(self.cfg))
        self.assertEqual(load_config(path), self.cfg)
        path.write_text('{"port":18765,"port":18766}')
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            load_config(path)
        path.write_text(json.dumps(dict(self.cfg, execution_enabled=True)))
        with self.assertRaises(ValueError):
            load_config(path)

    def test_http_auth_status_disabled_routes_and_persistent_stop(self):
        with GatewayServer(("127.0.0.1", 0), Handler) as server:
            server.monitor, server.authorization = self.monitor, b"Bearer fixture-only"
            server.stop_authorization = b"Bearer control-only"
            worker = threading.Thread(target=server.serve_forever)
            worker.start()
            try:
                def request(method, path, auth=True):
                    with_client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                    try:
                        headers = {"Authorization": "Bearer fixture-only"} if auth else {}
                        if auth and path == "/emergency-stop":
                            import uuid, time
                            headers = {"Authorization": "Bearer control-only",
                                       "X-Request-Id": str(uuid.uuid4()), "X-Request-Time": str(time.time())}
                        with_client.request(method, path, headers=headers)
                        response = with_client.getresponse()
                        return response.status, json.loads(response.read())
                    finally:
                        with_client.close()
                self.assertEqual(request("GET", "/health", False)[0], 401)
                self.assertEqual(request("GET", "/health")[0], 200)
                self.assertEqual(request("GET", "/status")[0], 503)
                self.monitor.reconcile(self.snapshot())
                code, body = request("GET", "/status")
                self.assertEqual(code, 200)
                self.assertFalse(any(body["operations"].values()))
                for route in ("open", "modify", "close", "cancel", "switch-account", "reset"):
                    self.assertEqual(request("POST", "/" + route)[0], 404)
                self.assertEqual(request("POST", "/emergency-stop", False)[0], 401)
                self.assertEqual(request("POST", "/emergency-stop")[0], 200)
            finally:
                server.shutdown()
                worker.join()
        restarted = Monitor(self.cfg, self.database)
        restarted.reconcile(self.snapshot())
        self.assertEqual(restarted.status()["breaker"], "EMERGENCY_STOP")


class HistoryTests(unittest.TestCase):
    setUp = GatewayTests.setUp
    snapshot = GatewayTests.snapshot
    def test_idempotent_history_checkpoint_and_restart(self):
        self.broker.past_deals = (Row(ticket=77, order=20, position_id=19, time_msc=1,
                                     symbol="EURUSD", type=0, entry=1, volume=.01,
                                     price=1.1, profit=1, commission=-.1, swap=0, fee=None),)
        snapshot = self.snapshot()
        self.monitor.reconcile(snapshot)
        self.monitor.reconcile(snapshot)
        with closing(self.monitor.db()) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM history").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM journal WHERE event='history_deals'").fetchone()[0], 1)
        restart = Monitor(self.cfg, self.database)
        self.assertAlmostEqual(restart.history_since(), snapshot["history_through"] - 300)
        self.assertIsNone(restart.status()["observation_age_seconds"])
        self.assertEqual(restart.status()["history"]["history_deals"][0]["ticket"], 77)

    def test_incomplete_history_does_not_advance_checkpoint(self):
        self.broker.past_deals = None
        with self.assertRaisesRegex(RuntimeError, "incomplete_history"):
            self.snapshot()
        with closing(self.monitor.db()) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM checkpoints").fetchone()[0], 0)

    def test_control_replay_and_expiry(self):
        import uuid, time
        request_id = str(uuid.uuid4())
        self.monitor.stop(request_id, time.time())
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.monitor.stop(request_id, time.time())
        with self.assertRaises(ValueError):
            self.monitor.stop(str(uuid.uuid4()), float("nan"))
        with self.assertRaises(ValueError):
            self.monitor.stop(str(uuid.uuid4()), time.time() - 61)

    def test_wrong_server_and_ipc_timeout(self):
        self.broker.account.server = "OTHER"
        with self.assertRaises(RuntimeError):
            self.snapshot()
        self.broker.initialize = lambda *args, **kwargs: False
        self.broker.last_error = lambda: (-10005, "fixture")
        with self.assertRaisesRegex(RuntimeError, "mt5_initialize_-10005"):
            self.snapshot()

    def test_structured_operational_log_rotation(self):
        import logging
        from gateway import configure_logging
        handler = configure_logging(self.path.parent)
        logger = logging.getLogger("niblit.gateway")
        try:
            handler.maxBytes = 150
            for _ in range(10):
                logger.info(json.dumps({"event": "authentication_rejected", "status": 401}))
            handler.flush()
            assert (self.path.parent / "logs/gateway.jsonl.1").is_file()
            for path in (self.path.parent / "logs").iterdir():
                for line in path.read_text().splitlines():
                    assert json.loads(line)["status"] == 401
        finally:
            logger.removeHandler(handler)
            handler.close()

    def test_p2_missing_history_does_not_advance_checkpoint(self):
        good=self.snapshot();self.monitor.reconcile(good)
        before=self.monitor.history_since()
        bad=self.snapshot();bad["history_orders"]=None
        with self.assertRaises(ValueError):self.monitor.reconcile(bad)
        self.assertEqual(before,self.monitor.history_since())

    def test_p2_trigger_survives_valid_inventory_and_restart(self):
        self.monitor.reconcile({"error":"terminal_unavailable_or_duplicated"})
        self.monitor.reconcile(self.snapshot())
        restarted=Monitor(self.cfg,self.database,lambda:self.now)
        restarted.reconcile(self.snapshot())
        status=restarted.status()
        self.assertTrue(status["broker_fresh"])
        self.assertEqual(status["breaker"],"RECONCILIATION_REQUIRED")
        self.assertIn("terminal_unavailable_or_duplicated",status["reconciliation"]["trigger"]["reasons"])
        self.assertFalse(status["execution_enabled"])
        self.assertFalse(status["reconciliation"]["complete"])
        self.assertGreaterEqual(status["health"]["restart_count"],2)

    def test_p2_history_replay_and_account_mismatch(self):
        snap=self.snapshot()
        self.monitor.reconcile(snap);self.monitor.reconcile(snap)
        with closing(self.monitor.db()) as db:
            self.assertEqual(db.execute("select count(*) from observation_windows").fetchone()[0],1)
        wrong=dict(snap,account={**self.account,"login":"99"})
        self.monitor.reconcile(wrong)
        self.assertFalse(self.monitor.status()["broker_fresh"])
        self.assertEqual(self.monitor.status()["breaker"],"RECONCILIATION_REQUIRED")
