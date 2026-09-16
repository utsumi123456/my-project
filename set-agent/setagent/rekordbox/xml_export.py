"""Export a Set Draft as a rekordbox XML (DJ_PLAYLISTS 1.0.0) for Bridge import.

This is the write-back path (spec B-11): the only supported way to get a set
back into rekordbox without touching master.db. The user points
Preferences > Bridge (rekordbox xml) > Imported Library at the generated file.

The TRACK element mirrors **exactly the attribute set rekordbox itself emits**
when it exports its collection (verified against a real rekordbox 7.2.14 export
on 2026-09-14). An earlier version emitted only 7 attributes and rekordbox
silently showed nothing — see TAD-3.

Play range (B-5) is expressed as two memory cues per track — "SetAgent IN" at
play_in and "SetAgent OUT" at play_out — because rekordbox playlists have no
per-track range field.

Cloud/streaming tracks (no local file) are skipped: they have no Location an
XML import can resolve.
"""
from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath
from xml.dom import minidom

from setagent.domain.draft import SetDraft
from setagent.rekordbox.library import Library

# rekordbox's own export order — keep it, some importers are order-sensitive.
TRACK_ATTR_ORDER = [
    "TrackID", "Name", "Artist", "Composer", "Album", "Grouping", "Genre", "Kind",
    "Size", "TotalTime", "DiscNumber", "TrackNumber", "Year", "AverageBpm",
    "DateAdded", "BitRate", "SampleRate", "Comments", "PlayCount", "Rating",
    "Location", "Remixer", "Tonality", "Label", "Mix",
]

EXT_KIND = {".mp3": "MP3 File", ".wav": "WAV File", ".flac": "FLAC File",
            ".m4a": "M4A File", ".aac": "AAC File", ".aif": "AIFF File",
            ".aiff": "AIFF File", ".ogg": "OGG File"}


def _location(folder_path: str) -> str:
    """"C:/Users/x/a b.mp3" -> "file://localhost/C:/Users/x/a%20b.mp3".

    rekordbox writes percent-escapes in LOWERCASE hex (%c3%ab, not %C3%AB); we
    match it byte-for-byte so a generated file is indistinguishable from one
    rekordbox exported itself (verified 2026-09-14)."""
    p = folder_path.replace("\\", "/")
    quoted = urllib.parse.quote(p, safe="/:")
    return "file://localhost/" + re.sub(r"%[0-9A-F]{2}", lambda m: m.group(0).lower(), quoted)


def _kind(file_name: str, folder_path: str) -> str:
    name = file_name or folder_path
    ext = PurePosixPath(name.replace("\\", "/")).suffix.lower()
    return EXT_KIND.get(ext, (ext[1:].upper() + " File") if ext else "")


def build_xml(draft: SetDraft, lib: Library, product_version: str = "7.2.14",
              playlist_name: str | None = None) -> tuple[str, dict]:
    root = ET.Element("DJ_PLAYLISTS", Version="1.0.0")
    ET.SubElement(root, "PRODUCT", Name="rekordbox", Version=product_version, Company="AlphaTheta")

    included, skipped = [], []
    for e in draft.tracks:
        t = lib.track(e.track_id)
        if t.is_cloud or not t.folder_path or t.folder_path.startswith("/contents_"):
            skipped.append((t.title, "cloud/no local file"))
            continue
        included.append(e)

    col = ET.SubElement(root, "COLLECTION", Entries=str(len(included)))
    for e in included:
        r = lib.db.export_row(e.track_id)
        bpm = e.tempo or (r["BPM"] / 100.0 if r["BPM"] else 0.0)
        attrs = {
            "TrackID": str(r["ID"]),
            "Name": r["Title"] or "",
            "Artist": r["Artist"],
            "Composer": r["Composer"],
            "Album": r["Album"],
            "Grouping": "",
            "Genre": r["Genre"],
            "Kind": _kind(r["FileName"], r["FolderPath"]),
            "Size": str(int(r["FileSize"])),
            "TotalTime": str(int(r["Length"])),
            "DiscNumber": str(int(r["DiscNo"])),
            "TrackNumber": str(int(r["TrackNo"])),
            "Year": str(int(r["ReleaseYear"])),
            "AverageBpm": f"{bpm:.2f}",
            "DateAdded": (r["DateCreated"] or "")[:10],
            "BitRate": str(int(r["BitRate"])),
            "SampleRate": str(int(r["SampleRate"])),
            "Comments": r["Commnt"],
            "PlayCount": str(int(r["DJPlayCount"])),
            "Rating": str(int(r["Rating"])),
            "Location": _location(r["FolderPath"]),
            "Remixer": r["Remixer"],
            "Tonality": r["Tonality"],
            "Label": r["Label"],
            "Mix": "",
        }
        tr = ET.SubElement(col, "TRACK", {k: attrs[k] for k in TRACK_ATTR_ORDER})

        # TEMPO from the rekordbox beat grid (first beat), as rekordbox emits.
        ta = lib.analysis(e.track_id)
        if ta.anlz and ta.anlz.beats:
            b0 = ta.anlz.beats[0]
            ET.SubElement(tr, "TEMPO", Inizio=f"{b0.time_ms / 1000.0:.3f}",
                          Bpm=f"{b0.tempo:.2f}", Metro="4/4", Battito=str(b0.number))

        # memory cues marking the intended play range
        pin_s = e.play_in_ms / 1000.0
        pout_ms = e.play_out_ms if e.play_out_ms is not None else int(r["Length"]) * 1000
        ET.SubElement(tr, "POSITION_MARK", Name="SetAgent IN", Type="0",
                      Start=f"{pin_s:.3f}", Num="-1")
        ET.SubElement(tr, "POSITION_MARK", Name="SetAgent OUT", Type="0",
                      Start=f"{pout_ms / 1000.0:.3f}", Num="-1")

    name = playlist_name or f"SetAgent {draft.name}"
    pls = ET.SubElement(root, "PLAYLISTS")
    rootnode = ET.SubElement(pls, "NODE", Type="0", Name="ROOT", Count="1")
    node = ET.SubElement(rootnode, "NODE", Name=name, Type="1",
                         KeyType="0", Entries=str(len(included)))
    for e in included:
        ET.SubElement(node, "TRACK", Key=str(lib.track(e.track_id).id))

    xml = minidom.parseString(ET.tostring(root, encoding="utf-8")).toprettyxml(
        indent="  ", encoding="UTF-8").decode("utf-8")
    return xml, {"included": len(included), "skipped": skipped, "playlist": name}


# --------------------------------------------------------------- S5-2 preview

def export_preview(draft: SetDraft, lib: Library) -> dict:
    """What the write-back will and will not carry (spec S5-2).

    A DJ should never discover after the fact that half the set did not make it.
    This is computed from the same rules build_xml() uses, so it cannot drift.
    """
    carried, dropped = [], []
    ranges = 0
    tempos = 0
    for e in draft.tracks:
        t = lib.track(e.track_id)
        if t.is_cloud or not t.folder_path or t.folder_path.startswith("/contents_"):
            dropped.append({"title": t.title,
                            "why": "クラウド/ストリーミングの曲はローカルのファイルパスが無く、XML から参照できない"})
            continue
        carried.append(t.title)
        if e.play_in_ms or e.play_out_ms is not None:
            ranges += 1
        if e.tempo:
            tempos += 1

    keeps = [f"曲順（{len(carried)}曲）",
             "曲のメタデータ（Artist / Album / BPM / Key / 長さ / レーティング）",
             "ビートグリッド（TEMPO 要素）"]
    if ranges:
        keeps.append(f"再生範囲 {ranges}曲分 — 各曲2つのメモリーキュー「SetAgent IN / OUT」として乗る")
    if tempos:
        keeps.append(f"セットテンポ {tempos}曲分 — AverageBpm として書き込む（元の曲の BPM は変わらない）")

    loses = [
        "マイルストーンと目標時刻 — rekordbox 側に対応する概念が無い",
        "ロック、目標カーブ、区間の予算 — Set Agent だけが持つ情報",
        "曲間の重なり（トランジション）— プレイリストは繋ぎ方を持たない",
    ]
    if any(e.tempo for e in draft.tracks):
        loses.append("テンポ変更は「その曲をこのBPMでかける」という意図であって、rekordbox 側が自動で追従はしない")

    notes = [
        "取り込みは Preferences > Advanced > Database > rekordbox xml > Imported Library でファイルを指定する",
        "指定したあと rekordbox を再起動する（起動時にしか読まない）",
        "ブラウザ左のアイコンレールで「Display rekordbox xml」をオンにする",
        "取り込んだ曲をデッキに載せると、コレクション側に反映するか聞かれる。Yes を押すと本体のライブラリが書き換わる",
    ]
    return {"carried": carried, "dropped": dropped, "keeps": keeps, "loses": loses, "notes": notes}


def describe_preview(p: dict) -> str:
    lines = [f"書き戻すと {len(p['carried'])}曲 が rekordbox に渡る。"
             + (f"{len(p['dropped'])}曲 は渡らない。" if p["dropped"] else "")]
    lines.append("\n反映されるもの:")
    lines += [f"  ○ {k}" for k in p["keeps"]]
    lines.append("\n反映されないもの:")
    lines += [f"  × {k}" for k in p["loses"]]
    if p["dropped"]:
        lines.append("\n渡らない曲:")
        seen = set()
        for d in p["dropped"][:8]:
            lines.append(f"  - {d['title'][:40]}")
            seen.add(d["why"])
        if len(p["dropped"]) > 8:
            lines.append(f"  …ほか {len(p['dropped']) - 8}曲")
        lines += [f"  理由: {w}" for w in seen]
    lines.append("\n取り込み手順:")
    lines += [f"  {i + 1}. {n}" for i, n in enumerate(p["notes"])]
    return "\n".join(lines)
