"""Optional LLM front end (spec Part E).

The LLM is a *narrator with tools*, not a source of facts. It may only call the
tools in agent/tools.py, so every number it says came from the analysis engines
and every track it names is a real row in the DJ's library.

Deliberately dependency-free: plain urllib, no SDK. The PyInstaller bundle stays
small, and a machine that cannot reach PyPI can still run this. If no key is
configured the backend reports itself unavailable and the panel falls back to the
deterministic Advisor — spec B-7 requires everything else to keep working.

Configure with an environment variable:
    SETAGENT_LLM_KEY  (or ANTHROPIC_API_KEY)
    SETAGENT_LLM_MODEL      optional
    SETAGENT_LLM_ENDPOINT   optional, for a proxy or a gateway
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from setagent.agent.advisor import Advisor, Intervention, Reply
from setagent.agent.tools import TOOL_SCHEMA, AgentTools

SYSTEM_PROMPT = """\
あなたは rekordbox のコンパニオン「Set Agent」です。DJ がセットを組むときの相談相手として、
セット全体の時間配分と展開を一緒に考えます。セットの主導権は常に DJ にあります。
あなたの提案は選択肢の一つであり、決定ではありません。

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

DEFAULT_MODEL = "claude-sonnet-4-5"
DEFAULT_ENDPOINT = "https://api.anthropic.com/v1/messages"


@dataclass
class LLMConfig:
    api_key: str = ""
    model: str = DEFAULT_MODEL
    endpoint: str = DEFAULT_ENDPOINT
    max_tokens: int = 1500
    timeout_s: int = 60

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            api_key=os.environ.get("SETAGENT_LLM_KEY") or os.environ.get("ANTHROPIC_API_KEY", ""),
            model=os.environ.get("SETAGENT_LLM_MODEL", DEFAULT_MODEL),
            endpoint=os.environ.get("SETAGENT_LLM_ENDPOINT", DEFAULT_ENDPOINT),
        )

    @property
    def available(self) -> bool:
        return bool(self.api_key)


class LLMError(RuntimeError):
    pass


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


@dataclass
class LLMAgent:
    """Runs the tool loop. Falls back to `advisor` whenever it cannot."""
    tools: AgentTools
    advisor: Advisor
    cfg: LLMConfig = field(default_factory=LLMConfig.from_env)
    max_turns: int = 6
    history: list[dict] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.cfg.available

    def status(self) -> str:
        if not self.cfg.available:
            return ("LLM は未設定（環境変数 SETAGENT_LLM_KEY）。"
                    "ルールベースのアドバイザで動いている — 分析・提案・候補出しはすべて使える")
        return f"LLM: {self.cfg.model}"

    def ask(self, text: str, selected_index: int | None = None) -> Reply:
        if self.advisor.level is Intervention.OFF:
            return Reply("エージェントはオフだ。分析とタイムラインはそのまま使える")
        if not self.cfg.available:
            return self.advisor.ask(text, selected_index)
        try:
            return self._loop(text, selected_index)
        except LLMError as ex:
            r = self.advisor.ask(text, selected_index)
            r.text = f"（LLM に届かなかった: {ex}。ルールベースで答える）\n{r.text}"
            return r

    # ------------------------------------------------------------------ loop
    def _loop(self, text: str, selected_index: int | None) -> Reply:
        proposed: list = []
        self.tools.on_proposal = proposed.append
        ctx = ""
        if selected_index is not None and selected_index < len(self.tools.draft.tracks):
            e = self.tools.draft.tracks[selected_index]
            ctx = (f"\n\n[選択中の曲] index={selected_index} "
                   f"track_ref={e.track_id} title={self.tools.title_of(e.track_id)}")
        self.history.append({"role": "user", "content": text + ctx})
        used: list[str] = []

        for _ in range(self.max_turns):
            data = _post(self.cfg, {
                "model": self.cfg.model, "max_tokens": self.cfg.max_tokens,
                "system": SYSTEM_PROMPT, "tools": TOOL_SCHEMA,
                "messages": self.history,
            })
            content = data.get("content", [])
            self.history.append({"role": "assistant", "content": content})
            calls = [b for b in content if b.get("type") == "tool_use"]
            if not calls:
                said = "\n".join(b.get("text", "") for b in content if b.get("type") == "text")
                return Reply(said.strip() or "(応答が空だった)",
                             change_set=proposed[-1] if proposed else None, used_tools=used)
            results = []
            for b in calls:
                used.append(b["name"])
                out = self.tools.call(b["name"], b.get("input") or {})
                results.append({"type": "tool_result", "tool_use_id": b["id"],
                                "content": json.dumps(out, ensure_ascii=False, default=str)[:12000]})
            self.history.append({"role": "user", "content": results})

        return Reply("ツール呼び出しが続きすぎたので打ち切った。もう少し具体的に頼め",
                     change_set=proposed[-1] if proposed else None, used_tools=used)

    def reset(self) -> None:
        self.history.clear()
