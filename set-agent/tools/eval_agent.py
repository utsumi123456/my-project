"""Scenario evaluation of the agent against the real Claude, without a window.

  python -m tools.eval_agent [playlist] [scenario-id ...]

Each scenario is one fresh conversation (the CLI session is reset), so runs are
independent. For every reply it records: wall time, tools called, whether a
Change Set came back, and three automatic checks:

  numbers   every mm:ss the model wrote appears in some tool result it was shown
            (spec §7: numbers come from analysis.*, not from the model)
  titles    every track title the model mentions exists in the library
  expect    scenario-specific expectations (target reached, tool used, no
            Change Set for a plain question, ...)

Prints a table and a PASS/FAIL per scenario. Exit code 1 if any failed.
Nothing secret is printed.
"""
from __future__ import annotations

import json
import re
import sys
import time

from setagent.agent import llm as llm_mod
from setagent.analysis.timing import fmt
from setagent.webui.api import Api

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MMSS = re.compile(r"(?<!\d)(\d{1,3}):(\d{2})(?!\d)")
LIMIT_S = 30.0


def on_worker(api: Api, fn, *a):
    """master.db is bound to the api worker thread; read it there."""
    return api._pool.submit(fn, *a).result()


def scenarios(api: Api) -> list[dict]:
    tl_total = api.state()["total_s"]
    target = api.draft.constraints.target_length_s
    longest = on_worker(api, lambda: max(api.tools._timeline().placements, key=lambda p: p.play_s))
    third = on_worker(api, lambda: api.lib.track(api.draft.tracks[2].track_id).title) if len(api.draft.tracks) > 2 else ""
    over = target is not None and tl_total > target
    S = [
        {"id": "length", "q": "今のセットは何分ですか？目標との差も教えてください",
         "expect": {"mentions": [fmt(tl_total)] + ([fmt(abs(tl_total - target))] if target else []),
                    "no_change_set": True, "tools_any": ["analysis.get_set_summary", "set.get_draft"]}},
        {"id": "longest", "q": "一番長くかける曲はどれですか？",
         "expect": {"mentions": [longest.title[:20]], "no_change_set": True}},
        {"id": "structure", "q": "3 曲目のフレーズ構成を教えてください",
         "expect": {"mentions": [third[:20]], "tools_any": ["analysis.get_track_structure"],
                    "no_change_set": True}},
        {"id": "hallucination", "q": "『Blue Monday』をセットに入れてください",
         "expect": {"no_unknown_tracks": True, "tools_any": ["lib.search"]}},
    ]
    if over:
        S.append({"id": "fit", "q": f"{fmt(target)} に収めてください",
                  "expect": {"change_set": True, "reaches_target": True,
                             "tools_any": ["analysis.plan_fit_to_target"]}})
        S.append({"id": "remove_one", "q": "展開に響かない曲を 1 曲だけ外す案を出してください",
                  "expect": {"change_set": True, "items": 1,
                             "tools_any": ["analysis.removal_candidates", "analysis.plan_fit_to_target"]}})
    else:
        S.append({"id": "fill", "q": "足りない分を埋める候補曲を出してください",
                  "expect": {"tools_any": ["recommend.candidates", "lib.search"], "titles_exist": True}})
        S.append({"id": "build", "q": "マイルストーンの間を候補曲で埋めて、目標尺のプレイリストを作ってください",
                  "expect": {"change_set": True, "no_unknown_tracks": True,
                             "tools_any": ["analysis.plan_fill_sections"]}})
    return S


def run_one(api: Api, sc: dict, titles: set[str]) -> dict:
    api.agent.reset()
    api.chat.clear()
    api.pending = None
    server = llm_mod.tool_server(api.tools)          # exists before the first ask, so nothing is missed
    server.calls.clear()
    server.transcript.clear()
    t0 = time.time()
    st = api.ask(sc["q"])
    dt = time.time() - t0
    reply = next((m["text"] for m in reversed(st["agent"]["chat"]) if m["who"] == "agent"), "")
    used = list(server.calls)
    shown = "\n".join(t["text"] for t in server.transcript)
    trace = [f"{t['name']}({json.dumps(t['args'], ensure_ascii=False)[:80]}) -> {len(t['text'])}c"
             + ("  REJECTED" if '"accepted": false' in t["text"] else "")
             for t in server.transcript]
    pending = api.pending
    fails: list[str] = []

    # numbers: every mm:ss in the reply must appear in a tool result
    nums = {f"{int(m):d}:{s}" for m, s in MMSS.findall(reply)}
    invented = sorted(n for n in nums if n not in shown and n not in sc["q"])
    if invented:
        fails.append(f"numbers not from tools: {invented}")
    # titles: quoted names must be real tracks (cheap heuristic on 「」 and bold)
    quoted = re.findall(r"[「『]([^」』]{2,60})[」』]|\*\*([^*]{2,60})\*\*", reply)
    names = {a or b for a, b in quoted}
    lower = {t.lower() for t in titles}
    fake = [n for n in names if not any(n.lower() in t or t in n.lower() for t in lower)
            and not MMSS.search(n) and not re.search(r"\d", n)]
    if fake and sc["expect"].get("titles_exist"):
        fails.append(f"names not in library: {fake[:3]}")

    e = sc["expect"]
    norm = lambda x: re.sub(r"[\s\-–—_]+", "", x).lower()
    for m in e.get("mentions", []):
        if m and norm(m) not in norm(reply):
            fails.append(f"missing mention: {m}")
    if any(r.endswith("REJECTED") for r in trace):
        fails.append("a proposal was rejected (malformed operations)")
    if e.get("no_change_set") and pending is not None:
        fails.append("made a Change Set for a plain question")
    if e.get("change_set") and pending is None:
        fails.append("no Change Set")
    if e.get("items") and pending is not None and len(pending.items) != e["items"]:
        fails.append(f"items {len(pending.items)} != {e['items']}")
    if e.get("tools_any") and not any(t in used for t in e["tools_any"]):
        fails.append(f"none of {e['tools_any']} used")
    if e.get("reaches_target") and pending is not None:
        tl = on_worker(api, pending.preview, api.draft, api.lib)
        if tl.target_s and tl.total_s > tl.target_s + tl.tolerance_s:
            fails.append(f"after apply {fmt(tl.total_s)} still over {fmt(tl.target_s)}")
    if e.get("no_unknown_tracks") and pending is not None:
        for it in pending.items:
            ref = it.op.params.get("track_id") or it.op.params.get("track_ref")
            try:
                on_worker(api, api.lib.track, ref)
            except Exception:
                fails.append(f"proposed unknown track {ref}")
    if dt > LIMIT_S:
        fails.append(f"slow: {dt:.1f}s > {LIMIT_S:.0f}s")
    if "LLM に接続できませんでした" in reply:
        fails.append("fell back to the Advisor")
    return {"id": sc["id"], "q": sc["q"], "s": round(dt, 1), "tools": used,
            "change_set": None if pending is None else len(pending.items),
            "reply": reply, "fails": fails, "trace": trace}


def main() -> int:
    pl = sys.argv[1] if len(sys.argv) > 1 else "acid"
    only = set(sys.argv[2:])
    api = Api(pl)
    api.boot()
    api.load({"playlist": pl})
    st = api.llm_status(True)
    print("mode:", st["mode"], "| model:", st["cli_model"] if st["mode"] == "cli" else st["api_model"],
          "| playlist:", pl)
    if st["mode"] == "advisor":
        print("Claude に接続していません。評価できません。")
        return 2
    titles = on_worker(api, lambda: {t.title for t in api.lib.db.tracks()})
    results = []
    for sc in scenarios(api):
        if only and sc["id"] not in only:
            continue
        r = run_one(api, sc, titles)
        results.append(r)
        mark = "PASS" if not r["fails"] else "FAIL"
        print(f"\n[{mark}] {r['id']}  {r['s']}s  tools={r['tools']}  change_set={r['change_set']}")
        print("  Q:", r["q"])
        print("  A:", r["reply"][:700].replace("\n", "\n     "))
        for t in r["trace"]:
            print("  ->", t)
        for f in r["fails"]:
            print("  !!", f)
    n_fail = sum(1 for r in results if r["fails"])
    total = sum(r["s"] for r in results)
    print(f"\n{len(results) - n_fail}/{len(results)} passed | total {total:.0f}s | "
          f"mean {total / max(len(results), 1):.1f}s | max {max((r['s'] for r in results), default=0):.1f}s")
    print(json.dumps([{k: v for k, v in r.items() if k != "reply"} for r in results], ensure_ascii=False))
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
