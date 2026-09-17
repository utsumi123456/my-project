"""Optional LLM front end (spec Part E).

The LLM is a *narrator with tools*, not a source of facts. It may only call the
tools in agent/tools.py, so every number it says came from the analysis engines
and every track it names is a real row in the DJ's library.

Two ways to reach Claude, tried in this order (docs/llm_backend_2026-09-17.md):

  1. Claude Code CLI, headless (`claude -p`). Uses the sign-in the CLI already
     holds -- on an enterprise account that is the company seat, no API key.
     Our tools are served to the child over a local MCP server (mcp_server.py).
     The CLI shipped inside Claude Desktop is found automatically.
  2. The Messages API with a key (plain urllib, no SDK), for machines that have
     a key and no Claude Code.

If neither works the deterministic Advisor answers, and says so -- spec B-7
requires everything else to keep working.

Environment (all optional):
    SETAGENT_LLM_BACKEND    auto | cli | api | off        (default auto)
    SETAGENT_CLAUDE_EXE     path to claude.exe            (default: search)
    SETAGENT_LLM_KEY  (or ANTHROPIC_API_KEY)
    SETAGENT_LLM_MODEL      cli: sonnet | opus | <model id>; api: <model id>
    SETAGENT_LLM_ENDPOINT   api only, for a proxy or a gateway
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from setagent.agent.advisor import Advisor, Intervention, Reply, OFF_TEXT
from setagent.agent.mcp_server import SERVER_NAME, ToolServer
from setagent.agent.tools import TOOL_SCHEMA, AgentTools

SYSTEM_PROMPT = """\
あなたは rekordbox のコンパニオン「Set Agent」です。DJ がセットを組むときの相談相手として、
セット全体の時間配分と展開を一緒に考えます。セットの主導権は常に DJ にあります。
あなたの提案は選択肢の一つであり、決定ではありません。
口調は丁寧語（です・ます）で、簡潔に。命令形や乱暴な言い回しは使いません。

原則:
1. 数値はツールから取る。尺・開始時刻・BPM・Key・エネルギー・目標カーブとの乖離は、必ず
   analysis.* や lib.* のツールで取得した値を使う。推測や暗算で数値を答えてはいけない。
2. 変更は提案として出す。set.propose_changes で Change Set を作る。自分で適用はできない。
3. 意図を上書きしない。ユーザーの明示した希望、ロックされた項目、マイルストーンの目標時刻が最優先。
   希望どうしが矛盾するときは、解消案を2〜3個示して選んでもらう。
4. 余地を残す。セットを丸ごと組み直す提案はしない。依頼された範囲の最小の変更にとどめる。
   テーマ・攻め具合・選曲の好みは DJ のもの。求められたときだけ意見を言う。
5. 根拠を短く示す。提案には一行の理由を付ける。
6. 不確かさを隠さない。フレーズ解析が無い曲や信頼度の低い値は、そうだと明示する。
7. 候補は実在曲だけ。曲の提案は recommend.candidates か lib.search が返した曲に限る。
   曲名を自分で作ってはいけない。

振る舞い:
- 質問に答えるだけで済むなら Change Set を作らない。
- 依頼が曖昧なら確認の質問を一つだけしてから進める。合理的な仮定を置けるなら、仮定を明示して進めてよい。
- 却下された提案をそのまま繰り返さない。
- 提案は1回につき1件。

出力形式:
- 通常の回答は簡潔な文章。数値はツールの値をそのまま使う。
- 変更提案は「一言の要約 → set.propose_changes → 適用前後の主要な差分を1〜2行」。
- 候補曲は最大5曲、1曲ごとに「曲名／BPM／Key／その区間での長さ／理由（一行）」。
"""

# The CLI exposes our tools as mcp__setagent__analysis_get_sections etc.; the
# prompt talks about "analysis.get_sections". Say so once, in the prompt.
CLI_PROMPT_NOTE = (
    "\n\nツールは mcp__setagent__ で始まる名前で提供されています（analysis.get_sections は "
    "mcp__setagent__analysis_get_sections）。数値はすべてこれらのツールから取ります。"
)

DEFAULT_MODEL = "claude-sonnet-5"          # api
DEFAULT_CLI_MODEL = "sonnet"               # cli alias; the seat picks the current Sonnet
DEFAULT_ENDPOINT = "https://api.anthropic.com/v1/messages"
CLI_TIMEOUT_S = 90
AUTH_CACHE_S = 600

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


@dataclass
class LLMConfig:
    api_key: str = ""
    model: str = ""                         # "" = backend default
    endpoint: str = DEFAULT_ENDPOINT
    max_tokens: int = 1500
    timeout_s: int = 60
    backend: str = "auto"                   # auto | cli | api | off
    claude_exe: str = ""                    # "" = search (find_claude)

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            api_key=os.environ.get("SETAGENT_LLM_KEY") or os.environ.get("ANTHROPIC_API_KEY", ""),
            model=os.environ.get("SETAGENT_LLM_MODEL", ""),
            endpoint=os.environ.get("SETAGENT_LLM_ENDPOINT", DEFAULT_ENDPOINT),
            backend=os.environ.get("SETAGENT_LLM_BACKEND", "auto").strip().lower() or "auto",
            claude_exe=os.environ.get("SETAGENT_CLAUDE_EXE", ""),
        )

    @property
    def available(self) -> bool:
        """API path usable (a key is set). The CLI path is checked at runtime."""
        return bool(self.api_key)

    @property
    def api_model(self) -> str:
        m = (self.model or "").strip()
        return m if m and m not in ("sonnet", "opus", "haiku") else DEFAULT_MODEL

    @property
    def cli_model(self) -> str:
        return (self.model or "").strip() or DEFAULT_CLI_MODEL


class LLMError(RuntimeError):
    pass


# ============================================================ Claude Code CLI
def find_claude(explicit: str = "") -> str:
    """First claude executable that exists. Desktop's bundled copy is preferred
    because on an enterprise PC it is the one that is signed in."""
    if explicit:
        return explicit if Path(explicit).is_file() else ""
    cands: list[str] = []
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        bundled = glob.glob(os.path.join(appdata, "Claude", "claude-code", "*", "claude.exe"))
        cands += sorted(bundled, key=_version_key, reverse=True)
    home = Path.home()
    cands.append(str(home / ".local" / "bin" / ("claude.exe" if sys.platform == "win32" else "claude")))
    for name in ("claude.exe", "claude", "claude.cmd"):
        p = shutil.which(name)
        if p:
            cands.append(p)
    for c in cands:
        if c and Path(c).is_file():
            return c
    return ""


def _version_key(path: str) -> tuple:
    parts = Path(path).parent.name.split(".")
    return tuple(int(p) if p.isdigit() else -1 for p in parts)


def _child_env() -> dict:
    """Do not let a parent Claude Code session (this very tool being developed
    inside one) leak its session variables into the child."""
    env = dict(os.environ)
    for k in list(env):
        if k == "CLAUDECODE" or k.startswith("CLAUDE_CODE_") or k.startswith("CLAUDE_AGENT_"):
            env.pop(k, None)
    return env


def _run_cli(argv: list[str], timeout_s: float, cwd: str | None = None) -> tuple[int, str, str]:
    """Run to completion with stdin closed and no console window."""
    try:
        p = subprocess.run(argv, input=b"", capture_output=True, timeout=timeout_s, cwd=cwd,
                           env=_child_env(), creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as ex:
        raise LLMError(f"Claude Code が {int(timeout_s)} 秒以内に応答しませんでした") from ex
    except OSError as ex:
        raise LLMError(f"Claude Code を起動できませんでした: {ex}") from ex
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


_AUTH_CACHE: dict[str, tuple[float, dict]] = {}


def cli_status(argv: list[str], *, refresh: bool = False) -> dict:
    """`claude auth status` (+ version), cached for a while. Never raises.
    Keys: found, logged_in, subscription, org, version, error, exe."""
    key = "\x00".join(argv)
    now = time.time()
    if not refresh and key in _AUTH_CACHE and now - _AUTH_CACHE[key][0] < AUTH_CACHE_S:
        return _AUTH_CACHE[key][1]
    st = {"found": bool(argv), "logged_in": False, "subscription": "", "org": "",
          "version": "", "error": "", "exe": argv[0] if argv else ""}
    if argv:
        try:
            _, out, err = _run_cli(argv + ["auth", "status"], 20)
            data = json.loads(out[out.find("{"):]) if "{" in out else {}
            st["logged_in"] = bool(data.get("loggedIn"))
            st["subscription"] = str(data.get("subscriptionType") or "")
            st["org"] = str(data.get("orgName") or "")
            if not data:
                st["error"] = (err or out).strip()[:200]
            _, v, _ = _run_cli(argv + ["--version"], 20)
            st["version"] = v.strip().split(" ")[0]
        except LLMError as ex:
            st["error"] = str(ex)
    _AUTH_CACHE[key] = (now, st)
    return st


def forget_cli_status() -> None:
    _AUTH_CACHE.clear()


def open_login_console(argv: list[str]) -> bool:
    """Start `claude auth login` in a visible console for the DJ to complete.
    The one action we cannot do for them."""
    try:
        if sys.platform == "win32":
            subprocess.Popen(["cmd", "/c", "start", "", *argv, "auth", "login"],
                             creationflags=subprocess.CREATE_NEW_CONSOLE, env=_child_env())
        else:
            subprocess.Popen(argv + ["auth", "login"], env=_child_env())
        return True
    except OSError:
        return False


_SERVER: ToolServer | None = None


def tool_server(tools: AgentTools) -> ToolServer:
    """One MCP server per process; the tools it serves follow the current set."""
    global _SERVER
    if _SERVER is None:
        _SERVER = ToolServer(tools)
        _SERVER.start()
    _SERVER.tools = tools
    return _SERVER


@dataclass
class CliBackend:
    argv: list[str]                          # [exe] normally; tests pass [python, stub]
    model: str = DEFAULT_CLI_MODEL
    timeout_s: float = CLI_TIMEOUT_S
    max_turns: int = 8
    session_id: str = ""                     # continuity across asks (--resume)
    work_dir: str = ""                       # where the CLI keeps the session files

    def ask(self, prompt: str, server: ToolServer) -> tuple[str, dict]:
        """One headless turn. Returns (text, raw result dict). Raises LLMError."""
        cwd = self.work_dir or _default_work_dir()
        Path(cwd).mkdir(parents=True, exist_ok=True)
        cfg_path = Path(cwd) / "mcp.json"
        cfg_path.write_text(json.dumps(server.mcp_config()), encoding="utf-8")
        resume = bool(self.session_id)
        if not resume:
            self.session_id = str(uuid.uuid4())
        argv = self.argv + [
            "-p", "--output-format", "json", "--model", self.model,
            "--system-prompt", SYSTEM_PROMPT + CLI_PROMPT_NOTE,
            "--setting-sources", "", "--strict-mcp-config", "--mcp-config", str(cfg_path),
            "--allowedTools", f"mcp__{SERVER_NAME}__*", "--tools", "",
            "--max-turns", str(self.max_turns),
            ("--resume" if resume else "--session-id"), self.session_id,
            prompt,
        ]
        out_f = tempfile.TemporaryFile()
        err_f = tempfile.TemporaryFile()
        try:
            try:
                proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out_f, stderr=err_f,
                                        cwd=cwd, env=_child_env(), creationflags=CREATE_NO_WINDOW)
            except OSError as ex:
                raise LLMError(f"Claude Code を起動できませんでした: {ex}") from ex
            # While the child thinks, this (worker) thread runs the tool calls it makes.
            if not server.pump_until(lambda: proc.poll() is None, self.timeout_s):
                proc.kill()
                proc.wait(5)
                raise LLMError(f"Claude Code が {int(self.timeout_s)} 秒以内に応答しませんでした")
            out_f.seek(0); err_f.seek(0)
            out = out_f.read().decode("utf-8", "replace")
            err = err_f.read().decode("utf-8", "replace")
        finally:
            out_f.close(); err_f.close()
        data = _last_json(out)
        if data is None:
            raise LLMError(f"Claude Code の応答を読めませんでした: {(err or out).strip()[:200]}")
        text = str(data.get("result") or "")
        if data.get("is_error"):
            if resume and "No conversation found" in text:
                self.session_id = ""                     # the session file is gone; start over
                return self.ask(prompt, server)
            raise LLMError(text.strip()[:300] or "Claude Code がエラーを返しました")
        if data.get("subtype") == "error_max_turns" and not text:
            text = "ツール呼び出しが続きすぎたため打ち切りました。もう少し具体的に指示してください"
        return text, data

    def reset(self) -> None:
        self.session_id = ""


def _default_work_dir() -> str:
    from setagent.settings import app_home
    return str(app_home() / "claude")


def _last_json(out: str) -> dict | None:
    """`--output-format json` prints one object; be tolerant of a warning line before it."""
    s = out.strip()
    if not s:
        return None
    try:
        v = json.loads(s)
    except ValueError:
        i = s.find("{")
        if i < 0:
            return None
        try:
            v = json.loads(s[i:])
        except ValueError:
            return None
    if isinstance(v, list):                             # stream-json style array
        v = next((x for x in reversed(v) if isinstance(x, dict) and x.get("type") == "result"), None)
    return v if isinstance(v, dict) else None


# ================================================================= API path
def _post(cfg: LLMConfig, payload: dict) -> dict:
    req = urllib.request.Request(
        cfg.endpoint, data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json", "x-api-key": cfg.api_key,
                 "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_s) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        raise LLMError(f"HTTP {ex.code}: {ex.read()[:300].decode('utf-8', 'replace')}") from ex
    except Exception as ex:
        raise LLMError(str(ex)) from ex


# =================================================================== agent
@dataclass
class LLMAgent:
    """Picks a backend per ask and falls back to `advisor` whenever it cannot."""
    tools: AgentTools
    advisor: Advisor
    cfg: LLMConfig = field(default_factory=LLMConfig.from_env)
    max_turns: int = 6
    history: list[dict] = field(default_factory=list)
    cli: CliBackend | None = None

    def __post_init__(self):
        if self.cli is None and self.cfg.backend in ("auto", "cli"):
            exe = find_claude(self.cfg.claude_exe)
            if exe:
                self.cli = CliBackend([exe], model=self.cfg.cli_model)

    # ------------------------------------------------------------- status
    def cli_state(self, refresh: bool = False) -> dict:
        if not self.cli or self.cfg.backend not in ("auto", "cli"):
            return {"found": False, "logged_in": False, "subscription": "", "org": "",
                    "version": "", "error": "", "exe": ""}
        return cli_status(self.cli.argv, refresh=refresh)

    @property
    def mode(self) -> str:
        """cli | api | advisor -- what the next ask will use."""
        b = self.cfg.backend
        if b == "off":
            return "advisor"
        if b in ("auto", "cli") and self.cli and self.cli_state()["logged_in"]:
            return "cli"
        if b in ("auto", "api") and self.cfg.available:
            return "api"
        return "advisor"

    @property
    def available(self) -> bool:
        return self.mode != "advisor"

    def status(self) -> str:
        m = self.mode
        if m == "cli":
            return f"LLM: Claude Code（{_seat_label(self.cli_state())}・{self.cli.model}）"
        if m == "api":
            return f"LLM: {self.cfg.api_model}（API キー）"
        st = self.cli_state()
        if self.cfg.backend == "api":
            why = "API キーが未設定です"
        elif self.cfg.backend == "off":
            why = "LLM はオフに設定されています"
        elif st["found"] and not st["logged_in"]:
            why = "Claude Code はありますがログインしていません"
        elif not st["found"]:
            why = "Claude Code も API キーも見つかりません（未設定）"
        else:
            why = "LLM は未設定です"
        return f"{why}。ルールベースのアドバイザで動いています。分析・提案・候補出しはすべて使えます"

    # ---------------------------------------------------------------- ask
    def ask(self, text: str, selected_index: int | None = None) -> Reply:
        if self.advisor.level is Intervention.OFF:
            return Reply(OFF_TEXT)
        m = self.mode
        if m == "advisor":
            return self.advisor.ask(text, selected_index)
        try:
            if m == "cli":
                try:
                    return self._ask_cli(text, selected_index)
                except LLMError:
                    if not (self.cfg.backend == "auto" and self.cfg.available):
                        raise
                    return self._ask_api(text, selected_index)      # key as the second try
            return self._ask_api(text, selected_index)
        except LLMError as ex:
            r = self.advisor.ask(text, selected_index)
            r.text = f"（LLM に接続できませんでした: {ex}。ルールベースで回答します）\n{r.text}"
            return r

    def _context(self, selected_index: int | None) -> str:
        if selected_index is not None and selected_index < len(self.tools.draft.tracks):
            e = self.tools.draft.tracks[selected_index]
            return (f"\n\n[選択中の曲] index={selected_index} "
                    f"track_ref={e.track_id} title={self.tools.title_of(e.track_id)}")
        return ""

    def _ask_cli(self, text: str, selected_index: int | None) -> Reply:
        proposed: list = []
        self.tools.on_proposal = proposed.append
        server = tool_server(self.tools)
        n0 = len(server.calls)
        said, _ = self.cli.ask(text + self._context(selected_index), server)
        used = server.calls[n0:]
        return Reply(said.strip() or "（応答が空でした）",
                     change_set=proposed[-1] if proposed else None, used_tools=used)

    def _ask_api(self, text: str, selected_index: int | None) -> Reply:
        proposed: list = []
        self.tools.on_proposal = proposed.append
        self.history.append({"role": "user", "content": text + self._context(selected_index)})
        used: list[str] = []

        for _ in range(self.max_turns):
            data = _post(self.cfg, {
                "model": self.cfg.api_model, "max_tokens": self.cfg.max_tokens,
                "system": SYSTEM_PROMPT, "tools": TOOL_SCHEMA,
                "messages": self.history,
            })
            content = data.get("content", [])
            self.history.append({"role": "assistant", "content": content})
            calls = [b for b in content if b.get("type") == "tool_use"]
            if not calls:
                said = "\n".join(b.get("text", "") for b in content if b.get("type") == "text")
                return Reply(said.strip() or "（応答が空でした）",
                             change_set=proposed[-1] if proposed else None, used_tools=used)
            results = []
            for b in calls:
                used.append(b["name"])
                out = self.tools.call(b["name"], b.get("input") or {})
                results.append({"type": "tool_result", "tool_use_id": b["id"],
                                "content": json.dumps(out, ensure_ascii=False, default=str)[:12000]})
            self.history.append({"role": "user", "content": results})

        return Reply("ツール呼び出しが続きすぎたため打ち切りました。もう少し具体的に指示してください",
                     change_set=proposed[-1] if proposed else None, used_tools=used)

    def reset(self) -> None:
        self.history.clear()
        if self.cli:
            self.cli.reset()


def _seat_label(st: dict) -> str:
    sub = st.get("subscription", "")
    return {"enterprise": "企業アカウント", "team": "チームアカウント",
            "max": "Max", "pro": "Pro"}.get(sub, sub or "ログイン済み")
