"""Verifica o motor do desktop real, sem exigir Qt ou uma sessão gráfica."""
import json
import socket
import tempfile
import time
import unittest
from urllib.request import urlopen

from app.desktop import LocalApplicationServer


def fixture_factory(*, data_dir, demo):
    async def application(scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                event = await receive()
                if event["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif event["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        elif scope["type"] == "http":
            body = json.dumps({"status": "ok", "data_dir": data_dir, "demo": demo}).encode()
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": body})
    return application


class DesktopLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.server = LocalApplicationServer(fixture_factory)

    def tearDown(self):
        self.server.stop()
        self.assertTrue(self.server.wait_stopped(5), "A thread local não encerrou")
        self.directory.cleanup()

    def wait_running(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = self.server.snapshot()
            if state["state"] == "running":
                return state
            if state["state"] == "error":
                self.fail(state["error"])
            time.sleep(0.02)
        self.fail("A aplicação local não ficou pronta")

    def test_start_health_stop_and_restart_preserve_explicit_context(self):
        self.assertTrue(self.server.start(self.directory.name, demo=True))
        initial = self.wait_running()
        self.assertTrue(initial["url"].startswith("http://127.0.0.1:"))
        with urlopen(initial["url"] + "/api/health", timeout=2) as response:
            payload = json.load(response)
        self.assertEqual(payload["data_dir"], self.directory.name)
        self.assertTrue(payload["demo"])
        self.assertFalse(self.server.start(self.directory.name), "Não deve abrir uma segunda instância")
        self.server.stop()
        self.assertTrue(self.server.wait_stopped(5))
        self.assertEqual(self.server.snapshot()["state"], "stopped")
        self.assertTrue(self.server.start(self.directory.name, initial["port"], demo=False))
        restarted = self.wait_running()
        self.assertGreater(restarted["generation"], initial["generation"])
        with urlopen(restarted["url"] + "/api/health", timeout=2) as response:
            self.assertFalse(json.load(response)["demo"])

    def test_port_conflict_is_reported_without_connecting_to_foreign_process(self):
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen(1)
            self.assertFalse(self.server.start(self.directory.name, occupied.getsockname()[1]))
        state = self.server.snapshot()
        self.assertEqual(state["state"], "error")
        self.assertIn("porta local", state["error"])
        self.assertFalse(state["alive"])

    def test_factory_failure_can_be_recovered_by_starting_again(self):
        def failed_factory(**kwargs):
            raise ValueError("Falha controlada na abertura dos dados")
        self.server = LocalApplicationServer(failed_factory)
        with self.assertLogs("app.desktop", level="ERROR"):
            self.assertTrue(self.server.start(self.directory.name))
            self.assertTrue(self.server.wait_stopped(5))
        self.assertEqual(self.server.snapshot()["state"], "error")
        self.assertIn("Falha controlada", self.server.snapshot()["error"])
        self.server._factory = fixture_factory
        self.assertTrue(self.server.start(self.directory.name))
        self.wait_running()


if __name__ == "__main__":
    unittest.main()
