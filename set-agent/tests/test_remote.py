"""The phone view: key check, PC-only calls, boot reuse, and the sync revision."""
import contextvars
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from setagent.webui import remote
from setagent.webui.api import Api


class FakeApi:
    def __init__(self):
        self.origin = contextvars.ContextVar("o", default="pc")
        self.calls = []

    def boot(self, reuse=False):
        self.calls.append(("boot", reuse))
        return {"playlists": [], "reuse": reuse}

    def set_target(self, seconds):
        self.calls.append(("set_target", seconds, self.origin.get()))
        return {"target_s": seconds}

    def set_llm(self, *a):
        raise AssertionError("a phone must never reach set_llm")


class RemoteServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        page = Path(self.tmp.name) / "index.html"
        page.write_text("<html><head><title>x</title></head><body><script>boot()</script>"
                        "</body></html>", encoding="utf-8")
        self.api = FakeApi()
        self.srv = remote.RemoteServer(self.api, page, host="127.0.0.1")
        self.srv.start()
        self.base = f"http://127.0.0.1:{self.srv.port}"

    def tearDown(self):
        self.srv.stop()
        self.tmp.cleanup()

    def get(self, path):
        return urllib.request.urlopen(self.base + path, timeout=5)

    def post(self, name, args, key=None):
        req = urllib.request.Request(
            f"{self.base}/api/{name}", data=json.dumps(args).encode(), method="POST",
            headers={"X-SetAgent-Key": key if key is not None else self.srv.key,
                     "X-SetAgent-Client": "phone-test", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())

    def test_page_needs_the_key_and_carries_the_shim_before_page_script(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.get("/?k=wrong")
        self.assertEqual(e.exception.code, 403)
        html = self.get("/?k=" + self.srv.key).read().decode()
        self.assertIn("window.SETAGENT_REMOTE = true", html)
        self.assertIn('name="viewport"', html)
        self.assertLess(html.index("SETAGENT_REMOTE"), html.index("boot()"))

    def test_api_needs_the_key(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.post("set_target", [3000], key="nope")
        self.assertEqual(e.exception.code, 403)
        self.assertEqual(self.api.calls, [])

    def test_call_runs_as_the_phone(self):
        self.assertEqual(self.post("set_target", [3000]), {"target_s": 3000})
        self.assertEqual(self.api.calls, [("set_target", 3000, "phone-test")])
        self.assertEqual(self.api.origin.get(), "pc")        # reset after the call

    def test_pc_only_calls_are_refused(self):
        for name in ("set_llm", "claude_login", "restart_rekordbox", "export_xml",
                     "remote_start", "remote_stop", "__init__"):
            self.assertEqual(self.post(name, ["k"]), {"error": remote.PC_ONLY}, name)

    def test_phone_boot_reuses_the_open_set(self):
        self.assertTrue(self.post("boot", [])["reuse"])
        self.assertEqual(self.api.calls, [("boot", True)])

    def test_a_busy_port_is_skipped_not_shared(self):
        other = remote.RemoteServer(self.api, self.srv.index_html, host="127.0.0.1")
        other.start()
        try:
            self.assertNotEqual(other.port, self.srv.port)
        finally:
            other.stop()

    def test_url_and_qr(self):
        url = self.srv.url()
        self.assertTrue(url.endswith(f":{self.srv.port}/?k={self.srv.key}"))
        self.assertIn("<svg", remote.qr_svg(url))


class LanIpTest(unittest.TestCase):
    def test_wifi_beats_the_vpn_and_junk_is_dropped(self):
        infos = [(2, 0, 0, "", (a, 0)) for a in
                 ("10.28.58.121", "172.20.10.3", "169.254.1.2", "127.0.0.1", "8.8.8.8")]
        with mock.patch("socket.getaddrinfo", return_value=infos),              mock.patch.object(remote, "_route_ip", return_value="10.28.58.121"):
            self.assertEqual(remote.lan_ips(), ["172.20.10.3", "10.28.58.121"])
        with mock.patch("socket.getaddrinfo", return_value=[(2, 0, 0, "", ("192.168.1.9", 0))] + infos):
            self.assertEqual(remote.lan_ip(), "192.168.1.9")

    def test_nothing_usable(self):
        with mock.patch("socket.getaddrinfo", side_effect=OSError),              mock.patch.object(remote, "_route_ip", return_value=None):
            self.assertEqual(remote.lan_ips(), ["127.0.0.1"])


class PrivateOnlyTest(unittest.TestCase):
    def test_private(self):
        for a in ("192.168.1.20", "10.0.0.5", "172.16.3.4", "127.0.0.1", "fe80::1"):
            self.assertTrue(remote._private(a), a)
        for a in ("8.8.8.8", "1.1.1.1", "garbage"):
            self.assertFalse(remote._private(a), a)


class SyncRevTest(unittest.TestCase):
    def setUp(self):
        with mock.patch("setagent.webui.api.Settings.load") as load:
            load.return_value = mock.MagicMock(preset="full", cap32=False, set_bpm="",
                                               level="passive", playlist=None)
            self.api = Api()

    def test_only_other_views_count(self):
        start = self.api.sync_rev()["rev"]
        self.api.set_target(3000)                       # from the PC (no draft: an error, still a change)
        self.assertFalse(self.api.sync_rev(start, "pc")["other"])
        self.assertTrue(self.api.sync_rev(start, "phone-a")["other"])
        tok = self.api.origin.set("phone-a")
        try:
            self.api.undo()
        finally:
            self.api.origin.reset(tok)
        now = self.api.sync_rev()["rev"]
        self.assertEqual(now, start + 2)
        self.assertTrue(self.api.sync_rev(start + 1, "pc")["other"])
        self.assertFalse(self.api.sync_rev(start + 1, "phone-a")["other"])

    def test_reads_do_not_bump(self):
        start = self.api.sync_rev()["rev"]
        self.api.state()
        self.api.agent_status()
        self.assertEqual(self.api.sync_rev()["rev"], start)

    def test_fell_off_the_log_means_refetch(self):
        for _ in range(80):
            self.api.set_target(3000)
        self.assertTrue(self.api.sync_rev(0, "pc")["other"])


if __name__ == "__main__":
    unittest.main()
