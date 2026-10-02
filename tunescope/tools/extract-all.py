# rekordbox 全ライブラリから解析済みローカル曲を抽出 → truth-all.json
# tracck_data に含まれる曲は tune セット、それ以外は holdout セットとしてタグ付け
import json
import os
import sys
import tempfile
from pathlib import Path

SETAGENT = str(Path(__file__).resolve().parents[2] / "set-agent")  # 同リポジトリ内の set-agent を利用
sys.path.insert(0, SETAGENT)
from tools.decrypt_masterdb import decrypt  # noqa: E402
from setagent.rekordbox.masterdb import MasterDB  # noqa: E402

src = Path(os.environ["APPDATA"]) / "Pioneer" / "rekordbox" / "master.db"
dst = Path(tempfile.gettempdir()) / "ts_master_plain.db"
decrypt(src, dst, wal=src.with_name(src.name + "-wal"))

db = MasterDB(dst)
tune_ids = set(db.playlist_by_name("tracck_data").track_ids)

rows = []
seen_paths = set()
n_nokey = n_cloud = n_missing = 0
for t in db.tracks():
    if t.is_cloud:
        n_cloud += 1
        continue
    if not t.key or t.bpm <= 0 or not t.analysed:
        n_nokey += 1
        continue
    p = t.folder_path
    if not p or p in seen_paths:
        continue
    if not Path(p).exists():
        n_missing += 1
        continue
    seen_paths.add(p)
    rows.append({
        "title": t.title, "artist": t.artist, "bpm": t.bpm, "key": t.key,
        "length_s": t.length_s, "folder_path": p,
        "set": "tune" if t.id in tune_ids else "holdout",
    })

out = Path(__file__).parent / "truth-all.json"
out.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
tune = sum(1 for r in rows if r["set"] == "tune")
print(f"total {len(rows)} (tune {tune} / holdout {len(rows)-tune})  excluded: cloud {n_cloud}, no-key/bpm {n_nokey}, missing-file {n_missing}")
