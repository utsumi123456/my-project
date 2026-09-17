"""End-to-end check of the LLM path against the real Claude, without a window.

  python -m tools.probe_llm [playlist] ["question"] ["follow-up"]

Which backend runs is whatever the app would pick on this PC: the Claude Code
sign-in (company seat, no key) first, an API key second. Nothing secret is
printed. What is printed: the backend and its sign-in, the wall time of each
turn, which tools the model called through our MCP server, the reply, and
whether a Change Set came back -- so the tool loop, the tool schema and the
voice rule in the system prompt can be checked in one run.

Exit code 0 = reached Claude, 1 = fell back to the Advisor, 2 = nothing to try.
"""
from __future__ import annotations

import sys
import time

from setagent.webui.api import Api

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def turn(api: Api, q: str) -> tuple[dict, float]:
    t = time.time()
    r = api.ask(q)
    return r, time.time() - t


def show(r: dict, dt: float) -> bool:
    chat = r["agent"]["chat"]
    print(f"\n--- {dt:.1f}s ---")
    for m in chat[-3:]:
        print(f"[{m['who']}] {m['text'][:1200]}")
    p = r["agent"].get("pending")
    if p:
        print("\npending:", p.get("title"), "| items:", len(p.get("items", [])), "| diff:", p.get("diff", [])[:3])
    text = " ".join(m["text"] for m in chat[-3:] if m["who"] == "agent")
    return "LLM に接続できませんでした" not in text


def main() -> int:
    pl = sys.argv[1] if len(sys.argv) > 1 else "acid"
    q = sys.argv[2] if len(sys.argv) > 2 else "今のセットは目標に収まっていますか？超過なら何分削る必要がありますか"
    q2 = sys.argv[3] if len(sys.argv) > 3 else "では、その分を収めるための提案を 1 件出してください"
    api = Api(pl)
    api.boot()
    api.load({"playlist": pl})
    st = api.llm_status(True)
    cli = st["cli"]
    print("mode:", st["mode"], "| backend:", st["backend"], "| model:",
          st["cli_model"] if st["mode"] == "cli" else st["api_model"])
    print("claude:", ("found " + cli["exe"]) if cli["found"] else "not found",
          "| version:", cli["version"] or "-", "| logged in:", cli["logged_in"],
          "| seat:", cli["subscription"] or "-", "| org:", cli["org"] or "-",
          ("| error: " + cli["error"]) if cli["error"] else "")
    print("api key:", "set (" + st["source"] + ")" if st["configured"] else "-")
    print("status line:", st["status"])
    if st["mode"] == "advisor":
        print("\nClaude に接続する手段がありません。Claude Desktop にログインするか、"
              "設定 → エージェント（Claude）で API キーを保存してから再実行してください。")
        return 2

    r, dt = turn(api, q)
    ok1 = show(r, dt)
    r, dt2 = turn(api, q2)
    ok2 = show(r, dt2)
    pending = r["agent"].get("pending")
    print(f"\nreached Claude: {ok1 and ok2} | turn 1 {dt:.1f}s, turn 2 {dt2:.1f}s"
          f" | change set: {'yes' if pending else 'no'}")
    return 0 if (ok1 and ok2) else 1


if __name__ == "__main__":
    sys.exit(main())
