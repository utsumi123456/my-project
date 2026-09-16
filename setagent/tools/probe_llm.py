"""End-to-end check of the optional LLM path with a real key, without a window.

  python -m tools.probe_llm [playlist] ["question"]

The key comes from the app's settings (set it in 設定 → エージェントの LLM) or
from SETAGENT_LLM_KEY / ANTHROPIC_API_KEY. It is never printed. What is
printed: model, whether the call reached the API, which tools the model used,
and the reply -- so the tool loop, the tool schema and the voice rule in the
system prompt can be checked in one run.
"""
from __future__ import annotations

import sys
import time

from setagent.webui.api import Api

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    pl = sys.argv[1] if len(sys.argv) > 1 else "acid"
    q = sys.argv[2] if len(sys.argv) > 2 else "今のセットのバランスはどうですか？"
    api = Api(pl)
    api.boot()
    api.load({"playlist": pl})
    st = api.llm_status()
    print("configured:", st["configured"], "| source:", st["source"] or "-", "| model:", st["model"],
          "| key:", st["masked"] or "-")
    if not st["configured"]:
        print("キーが設定されていません。アプリの 設定 → エージェントの LLM で保存するか、"
              "SETAGENT_LLM_KEY を設定してから再実行してください。")
        return 2
    t = time.time()
    r = api.ask(q)
    dt = time.time() - t
    chat = r["agent"]["chat"]
    print(f"\n--- {dt:.1f}s ---")
    for m in chat[-4:]:
        print(f"[{m['who']}] {m['text'][:1200]}")
    p = r["agent"].get("pending")
    if p:
        print("\npending:", p.get("title"), "| items:", len(p.get("items", [])))
    text = " ".join(m["text"] for m in chat if m["who"] == "agent")
    reached = "LLM に接続できませんでした" not in text
    print("\nreached the API:", reached)
    return 0 if reached else 1


if __name__ == "__main__":
    sys.exit(main())
