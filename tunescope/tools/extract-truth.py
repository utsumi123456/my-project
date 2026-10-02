# rekordbox master.db から track_data プレイリストの正解ラベルを抽出 → truth.json
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
r = decrypt(src, dst, wal=src.with_name(src.name + "-wal"))
print(f"decrypted {r.n_pages} pages", file=sys.stderr)

db = MasterDB(dst)
pl = db.playlist_by_name("tracck_data")  # rekordbox 上の実名（track_data のタイポ）
rows = []
for tid in pl.track_ids:
    t = db.track(tid)
    rows.append({
        "title": t.title,
        "artist": t.artist,
        "bpm": t.bpm,
        "key": t.key,
        "length_s": t.length_s,
        "folder_path": t.folder_path,
        "is_cloud": t.is_cloud,
    })
out = Path(__file__).parent / "truth.json"
out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"{len(rows)} tracks -> {out}")
for x in rows:
    print(f"  {x['bpm']:7.2f}  {x['key']:4s}  {x['artist']} - {x['title']}  [{x['folder_path'][:60]}]")
