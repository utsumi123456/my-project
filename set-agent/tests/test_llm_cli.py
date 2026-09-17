# -*- coding: utf-8 -*-
"""The Claude Code CLI backend and its MCP tool server, against a fake `claude`.

Nothing here touches the network or a real sign-in: `tests/fake_claude.py`
stands in for the CLI and talks to our ToolServer the way the real one does.
"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from setagent.agent.advisor import Advisor
from setagent.agent.llm import (CliBackend, LLMAgent, LLMConfig, _last_json, find_claude,
                                forget_cli_status)
from setagent.agent.mcp_server import MCP_TOOLS, ToolServer, mcp_name
from setagent.agent.tools import TOOL_SCHEMA
from test_agent import draft, tools

FAKE = [sys.executable, str(Path(__file__).with_name("fake_claude.py"))]
ENV_KEYS = ("FAKE_CLAUDE_MODE", "FAKE_CLAUDE_LOGGED_IN", "FAKE_CLAUDE_RESUME_FAILS",
            "FAKE_CLAUDE_REMOVE_REF", "FAKE_CLAUDE_ARGS")


def rpc(url, method, params=None, id_=None):
    body = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        body["params"] = params
    if id_ is not None:
        body["id"] = id_
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        raw = r.read()
        return r.status, (json.loads(raw) if raw else None)


class ToolServerTests(unittest.TestCase):
    def setUp(self):
        self.t = tools(draft(*"abcdef", target=1500))
        self.srv = ToolServer(self.t, direct=True)
        self.url = self.srv.start()

    def tearDown(self):
        self.srv.stop()

    def test_names_are_mcp_safe_and_complete(self):
        self.assertEqual(len(MCP_TOOLS), len(TOOL_SCHEMA))
        for t in MCP_TOOLS:
            self.assertNotIn(".", t["name"])
            self.assertIn("inputSchema", t)
        self.assertEqual(mcp_name("analysis.get_set_summary"), "analysis_get_set_summary")

    def test_protocol_round_trip(self):
        st, r = rpc(self.url, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                             "clientInfo": {"name": "t", "version": "0"}}, 0)
        self.assertEqual(st, 200)
        self.assertEqual(r["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(r["result"]["serverInfo"]["name"], "setagent")
        st, r = rpc(self.url, "notifications/initialized")
        self.assertEqual((st, r), (202, None))
        st, r = rpc(self.url, "tools/list", {}, 1)
        self.assertEqual([t["name"] for t in r["result"]["tools"]], [t["name"] for t in MCP_TOOLS])
        st, r = rpc(self.url, "tools/call", {"name": "analysis_get_set_summary", "arguments": {}}, 2)
        out = json.loads(r["result"]["content"][0]["text"])
        self.assertIsInstance(out, dict)
        self.assertNotIn("isError", r["result"])
        self.assertEqual(self.srv.calls, ["analysis.get_set_summary"])

    def test_unknown_tool_and_method(self):
        _, r = rpc(self.url, "tools/call", {"name": "nope", "arguments": {}}, 3)
        self.assertTrue(r["result"]["isError"])
        _, r = rpc(self.url, "resources/list", {}, 4)
        self.assertEqual(r["error"]["code"], -32601)

    def test_get_is_refused(self):
        req = urllib.request.Request(self.url)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(cm.exception.code, 405)


class _Recorder:
    """Wraps AgentTools.call to note which thread ran it."""
    def __init__(self, inner):
        self.inner, self.threads = inner, []
    def call(self, name, args):
        self.threads.append(threading.get_ident())
        return self.inner.call(name, args)


class PumpTests(unittest.TestCase):
    def test_queued_calls_run_on_the_pumping_thread(self):
        rec = _Recorder(tools(draft(*"abc")))
        srv = ToolServer(rec)                      # queued mode, like production
        url = srv.start()
        done = threading.Event()
        got = {}
        def client():
            got["r"] = rpc(url, "tools/call", {"name": "set_get_draft", "arguments": {}}, 1)[1]
            done.set()
        threading.Thread(target=client, daemon=True).start()
        self.assertTrue(srv.pump_until(lambda: not done.is_set(), 5))
        srv.stop()
        self.assertIn("content", got["r"]["result"])
        self.assertEqual(rec.threads, [threading.get_ident()])

    def test_unpumped_call_times_out_cleanly(self):
        srv = ToolServer(tools(draft(*"ab")), call_timeout_s=0.2)
        url = srv.start()
        _, r = rpc(url, "tools/call", {"name": "set_get_draft", "arguments": {}}, 1)
        srv.stop()
        self.assertTrue(r["result"]["isError"])


class CliBackendTests(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.pop(k, None) for k in ENV_KEYS}
        self.tmp = tempfile.mkdtemp()
        self.args = Path(self.tmp) / "args.jsonl"
        os.environ["FAKE_CLAUDE_ARGS"] = str(self.args)
        forget_cli_status()

    def tearDown(self):
        for k in ENV_KEYS:
            os.environ.pop(k, None)
        for k, v in self.saved.items():
            if v is not None:
                os.environ[k] = v
        forget_cli_status()

    def agent(self, **cfg):
        t = tools(draft(*"abcdef", target=1500))
        c = LLMConfig(backend="cli", **cfg)
        return LLMAgent(t, Advisor(t), cfg=c, cli=CliBackend(FAKE, work_dir=self.tmp, timeout_s=20))

    def calls(self):
        return [json.loads(l) for l in self.args.read_text(encoding="utf-8").splitlines()]

    def test_status_reads_the_sign_in(self):
        a = self.agent()
        self.assertEqual(a.mode, "cli")
        self.assertTrue(a.available)
        self.assertIn("Claude Code", a.status())
        self.assertIn("企業アカウント", a.status())
        st = a.cli_state()
        self.assertEqual((st["logged_in"], st["org"], st["version"]), (True, "Fake Org", "9.9.9"))

    def test_not_logged_in_means_advisor(self):
        os.environ["FAKE_CLAUDE_LOGGED_IN"] = "0"
        a = self.agent()
        self.assertEqual(a.mode, "advisor")
        self.assertIn("ログインしていません", a.status())
        self.assertIn("30:00", a.ask("今のセット何分？").text)

    def test_round_trip_uses_our_tools_and_keeps_the_session(self):
        a = self.agent()
        r = a.ask("今のセット何分？")
        self.assertIn("analysis.get_set_summary", r.used_tools)
        self.assertIn("tools]", r.text)
        self.assertIsNone(r.change_set)
        a.ask("続きです")
        p_calls = [c for c in self.calls() if "-p" in c]
        self.assertEqual(len(p_calls), 2)
        first, second = p_calls
        self.assertIn("--session-id", first)
        self.assertIn("--resume", second)
        sid = first[first.index("--session-id") + 1]
        self.assertEqual(second[second.index("--resume") + 1], sid)
        for flag in ("--system-prompt", "--strict-mcp-config", "--mcp-config", "--allowedTools",
                     "--setting-sources", "--output-format"):
            self.assertIn(flag, first)
        self.assertEqual(first[first.index("--tools") + 1], "")
        self.assertEqual(first[first.index("--model") + 1], "sonnet")
        self.assertEqual(first[-1], "今のセット何分？")

    def test_model_setting_reaches_the_cli(self):
        a = self.agent(model="opus")
        a.cli.model = a.cfg.cli_model
        a.ask("x")
        c = [c for c in self.calls() if "-p" in c][0]
        self.assertEqual(c[c.index("--model") + 1], "opus")

    def test_proposal_becomes_a_change_set(self):
        os.environ["FAKE_CLAUDE_MODE"] = "propose"
        os.environ["FAKE_CLAUDE_REMOVE_REF"] = "b"
        r = self.agent().ask("1曲外して")
        self.assertIsNotNone(r.change_set)
        self.assertEqual(len(r.change_set.items), 1)
        self.assertIn("外す", r.change_set.items[0].op.describe(lambda ref: ref))
        self.assertIn("set.propose_changes", r.used_tools)

    def test_error_falls_back_to_the_advisor_with_a_note(self):
        os.environ["FAKE_CLAUDE_MODE"] = "error"
        r = self.agent().ask("今のセット何分？")
        self.assertIn("ルールベース", r.text)
        self.assertIn("30:00", r.text)
        self.assertIn("Not logged in", r.text)

    def test_timeout_kills_the_child_and_falls_back(self):
        os.environ["FAKE_CLAUDE_MODE"] = "slow"
        os.environ["FAKE_CLAUDE_SLEEP"] = "5"
        a = self.agent()
        a.cli.timeout_s = 1
        r = a.ask("今のセット何分？")
        self.assertIn("秒以内に応答しませんでした", r.text)
        self.assertIn("30:00", r.text)

    def test_lost_session_starts_a_new_one(self):
        a = self.agent()
        a.ask("一回目")
        os.environ["FAKE_CLAUDE_RESUME_FAILS"] = "1"
        r = a.ask("二回目")
        self.assertNotIn("ルールベース", r.text)
        p_calls = [c for c in self.calls() if "-p" in c]
        self.assertEqual(len(p_calls), 3)              # resume failed, then a fresh session
        self.assertIn("--resume", p_calls[1])
        self.assertIn("--session-id", p_calls[2])
        self.assertNotEqual(p_calls[0][p_calls[0].index("--session-id") + 1],
                            p_calls[2][p_calls[2].index("--session-id") + 1])

    def test_off_backend_is_advisor_even_when_signed_in(self):
        t = tools(draft(*"abc"))
        a = LLMAgent(t, Advisor(t), cfg=LLMConfig(backend="off"), cli=CliBackend(FAKE, work_dir=self.tmp))
        self.assertEqual(a.mode, "advisor")


class HelperTests(unittest.TestCase):
    def test_find_claude_explicit_path(self):
        self.assertEqual(find_claude(sys.executable), sys.executable)
        self.assertEqual(find_claude(r"C:\nope\claude.exe"), "")

    def test_last_json_tolerates_a_warning_line(self):
        self.assertEqual(_last_json('Warning: x\n{"type":"result","result":"a"}')["result"], "a")
        self.assertIsNone(_last_json("nothing here"))
        self.assertIsNone(_last_json(""))
        arr = _last_json('[{"type":"system"},{"type":"result","result":"b"}]')
        self.assertEqual(arr["result"], "b")

    def test_config_models(self):
        self.assertEqual(LLMConfig().cli_model, "sonnet")
        self.assertEqual(LLMConfig().api_model, "claude-sonnet-5")
        self.assertEqual(LLMConfig(model="opus").cli_model, "opus")
        self.assertEqual(LLMConfig(model="opus").api_model, "claude-sonnet-5")
        self.assertEqual(LLMConfig(model="claude-opus-5").api_model, "claude-opus-5")


if __name__ == "__main__":
    unittest.main()
