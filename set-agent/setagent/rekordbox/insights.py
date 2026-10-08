"""Library and DJ-history reads for the agent (C, 2026-10-08).

The tool list follows rekordbox-mcp (davehenke/rekordbox-mcp): history
sessions, session tracks, track details, library statistics, the playlist tree.
It is reimplemented here as plain SQL over Set Agent's own decrypted,
read-only copy -- the same stdlib-only path as the rest of the reader -- so the
agent gains the reach of that MCP server without a second database stack or
any write access.

What history adds that the playlist alone cannot: which tracks this DJ has
actually played after which (co-occurrence). recommend.candidates uses it as a
tie-breaker, and lib.get_play_history finally answers instead of "not wired".
"""
from __future__ import annotations

import sqlite3
import statistics
from collections import Counter
from datetime import datetime, timedelta

from setagent.agent.recommend import camelot


def _camelot_str(key: str) -> str:
    c = camelot(key)
    return f"{c[0]}{c[1]}" if c else ""


def _date(s: str | None) -> str:
    return (s or "")[:10]


# ------------------------------------------------------------------ history

def history_sessions(con: sqlite3.Connection, days: int | None = None, query: str = "",
                     min_tracks: int = 1, limit: int = 30) -> list[dict]:
    """DJ history sessions, newest first. Folders (year/month) are skipped."""
    rows = con.execute(
        """select h.ID, h.Name, coalesce(h.DateCreated, h.created_at) as d,
                  (select count(*) from djmdSongHistory s
                    where s.HistoryID = h.ID and s.rb_local_deleted = 0) as n
           from djmdHistory h
           where h.rb_local_deleted = 0 and coalesce(h.Attribute, 0) = 0
           order by d desc""").fetchall()
    since = None
    if days:
        since = (datetime.now() - timedelta(days=int(days))).strftime("%Y-%m-%d")
    q = (query or "").lower()
    out = []
    for hid, name, d, n in rows:
        if n < min_tracks:
            continue
        if since and _date(d) < since:
            continue
        if q and q not in (name or "").lower() and q not in _date(d):
            continue
        out.append({"session_id": hid, "name": name or "", "date": _date(d), "tracks": n})
        if len(out) >= limit:
            break
    return out


def session_tracks(con: sqlite3.Connection, session_id: str) -> list[dict]:
    rows = con.execute(
        """select s.TrackNo, c.ID, coalesce(c.Title,''), coalesce(a.Name,''), coalesce(c.BPM,0),
                  coalesce(k.ScaleName,''), coalesce(c.Length,0)
           from djmdSongHistory s
           join djmdContent c on c.ID = s.ContentID
           left join djmdArtist a on a.ID = c.ArtistID
           left join djmdKey k on k.ID = c.KeyID
           where s.HistoryID = ? and s.rb_local_deleted = 0
           order by s.TrackNo""", (str(session_id),)).fetchall()
    return [{"no": no, "track_id": tid, "title": t, "artist": a, "bpm": round(b / 100.0, 2),
             "key": k, "camelot": _camelot_str(k), "length_s": int(ln)}
            for no, tid, t, a, b, k, ln in rows]


def _sequences(con: sqlite3.Connection) -> dict[str, list[str]]:
    seqs: dict[str, list[str]] = {}
    for hid, cid in con.execute(
            "select HistoryID, ContentID from djmdSongHistory where rb_local_deleted = 0 "
            "order by HistoryID, TrackNo"):
        seqs.setdefault(hid, []).append(cid)
    return seqs


class HistoryIndex:
    """Who followed whom in the DJ's own sessions. Built once per library load."""

    def __init__(self, con: sqlite3.Connection):
        self.after: dict[str, Counter] = {}
        self.before: dict[str, Counter] = {}
        self.sessions_of: dict[str, set[str]] = {}
        for hid, ids in _sequences(con).items():
            for i, cid in enumerate(ids):
                self.sessions_of.setdefault(cid, set()).add(hid)
                if i + 1 < len(ids) and ids[i + 1] != cid:
                    self.after.setdefault(cid, Counter())[ids[i + 1]] += 1
                    self.before.setdefault(ids[i + 1], Counter())[cid] += 1

    def followers(self, track_id: str) -> Counter:
        return self.after.get(str(track_id), Counter())

    def leaders(self, track_id: str) -> Counter:
        return self.before.get(str(track_id), Counter())

    def session_count(self, track_id: str) -> int:
        return len(self.sessions_of.get(str(track_id), ()))


def _titles(con: sqlite3.Connection, ids) -> dict[str, str]:
    ids = list(ids)
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return {r[0]: r[1] or "" for r in con.execute(
        f"select ID, Title from djmdContent where ID in ({marks})", ids)}


def track_history(con: sqlite3.Connection, idx: HistoryIndex, track_id: str, limit: int = 8) -> dict:
    tid = str(track_id)
    r = con.execute("select coalesce(Title,''), coalesce(DJPlayCount,0) from djmdContent where ID = ?",
                    (tid,)).fetchone()
    if r is None:
        return {"error": f"曲 {tid} はライブラリにありません"}
    last = con.execute(
        """select max(coalesce(h.DateCreated, h.created_at)) from djmdSongHistory s
           join djmdHistory h on h.ID = s.HistoryID
           where s.ContentID = ? and s.rb_local_deleted = 0""", (tid,)).fetchone()[0]
    fol, lead = idx.followers(tid).most_common(limit), idx.leaders(tid).most_common(limit)
    names = _titles(con, [i for i, _ in fol] + [i for i, _ in lead])
    return {
        "track_id": tid, "title": r[0],
        "play_count": int(r[1]),
        "sessions": idx.session_count(tid),
        "last_played": _date(last),
        "followed_by": [{"track_id": i, "title": names.get(i, ""), "times": n} for i, n in fol],
        "preceded_by": [{"track_id": i, "title": names.get(i, ""), "times": n} for i, n in lead],
    }


# ------------------------------------------------------------------ tracks

def track_details(con: sqlite3.Connection, track_id: str) -> dict:
    r = con.execute(
        """select c.ID, coalesce(c.Title,'') Title, coalesce(a.Name,'') Artist,
                  coalesce(al.Name,'') Album, coalesce(g.Name,'') Genre, coalesce(lb.Name,'') Label,
                  coalesce(rm.Name,'') Remixer, coalesce(k.ScaleName,'') Key,
                  coalesce(c.BPM,0) BPM, coalesce(c.Length,0) Length, coalesce(c.Rating,0) Rating,
                  coalesce(c.DJPlayCount,0) Plays, coalesce(c.ReleaseYear,0) Year,
                  coalesce(c.Commnt,'') Comment, coalesce(c.StockDate,'') Added,
                  coalesce(c.FolderPath,'') Path, coalesce(c.FileType,0) FileType,
                  coalesce(c.ColorID,0) Color
           from djmdContent c
           left join djmdArtist a on a.ID = c.ArtistID
           left join djmdArtist rm on rm.ID = c.RemixerID
           left join djmdAlbum al on al.ID = c.AlbumID
           left join djmdGenre g on g.ID = c.GenreID
           left join djmdLabel lb on lb.ID = c.LabelID
           left join djmdKey k on k.ID = c.KeyID
           where c.ID = ? and c.rb_local_deleted = 0""", (str(track_id),)).fetchone()
    if r is None:
        return {"error": f"曲 {track_id} はライブラリにありません"}
    path = r["Path"]
    return {
        "track_id": r["ID"], "title": r["Title"], "artist": r["Artist"], "album": r["Album"],
        "genre": r["Genre"], "label": r["Label"], "remixer": r["Remixer"],
        "bpm": round(r["BPM"] / 100.0, 2), "key": r["Key"], "camelot": _camelot_str(r["Key"]),
        "length_s": int(r["Length"]), "rating": int(r["Rating"]), "play_count": int(r["Plays"]),
        "year": int(r["Year"]) or None, "comment": r["Comment"], "added": _date(r["Added"]),
        "cloud": path.startswith("/contents_") or path.startswith("spotify:") or r["FileType"] == 25,
    }


def compatible_keys(key: str) -> list[str]:
    """Camelot-compatible keys (same, +-1, relative major/minor) as rekordbox
    ScaleNames, so they can be matched against the Key column directly."""
    from setagent.agent.recommend import _MAJOR, _MINOR
    c = camelot(key)
    if not c:
        return []
    n, mode = c
    want = {(n, mode), ((n % 12) + 1, mode), ((n - 2) % 12 + 1, mode), (n, "B" if mode == "A" else "A")}
    out = []
    for name, num in _MINOR.items():
        if (num, "A") in want:
            out.append(name)
    for name, num in _MAJOR.items():
        if (num, "B") in want:
            out.append(name)
    return out


def search(con: sqlite3.Connection, *, text: str = "", bpm_min: float | None = None,
           bpm_max: float | None = None, key: str = "", compatible_with: str = "",
           genre: str = "", rating_min: int | None = None, unplayed: bool = False,
           ids: list[str] | None = None, sort: str = "", limit: int = 20) -> list[dict]:
    """The library search behind lib.search. Filters run in SQL; `ids` limits
    to a playlist. sort: '' (library order) | plays | rating | bpm | added."""
    where, args = ["c.rb_local_deleted = 0"], []
    if text:
        where.append("(lower(c.Title) like ? or lower(coalesce(a.Name,'')) like ?)")
        args += [f"%{text.lower()}%"] * 2
    if bpm_min is not None:
        where.append("c.BPM >= ?"); args.append(int(round(float(bpm_min) * 100)))
    if bpm_max is not None:
        where.append("c.BPM <= ?"); args.append(int(round(float(bpm_max) * 100)))
    keys = [key] if key else []
    if compatible_with:
        keys = compatible_keys(compatible_with) or [compatible_with]
    if keys:
        where.append(f"k.ScaleName in ({','.join('?' * len(keys))})"); args += keys
    if genre:
        where.append("lower(coalesce(g.Name,'')) like ?"); args.append(f"%{genre.lower()}%")
    if rating_min is not None:
        where.append("coalesce(c.Rating,0) >= ?"); args.append(int(rating_min))
    if unplayed:
        where.append("coalesce(c.DJPlayCount,0) = 0")
    if ids is not None:
        if not ids:
            return []
        where.append(f"c.ID in ({','.join('?' * len(ids))})"); args += list(ids)
    order = {"plays": "coalesce(c.DJPlayCount,0) desc", "rating": "coalesce(c.Rating,0) desc",
             "bpm": "c.BPM asc", "added": "coalesce(c.StockDate,'') desc"}.get(sort, "c.rowid")
    rows = con.execute(
        f"""select c.ID, coalesce(c.Title,''), coalesce(a.Name,''), coalesce(c.BPM,0),
                   coalesce(k.ScaleName,''), coalesce(c.Length,0), coalesce(g.Name,''),
                   coalesce(c.Rating,0), coalesce(c.DJPlayCount,0), coalesce(c.FolderPath,''),
                   coalesce(c.FileType,0)
            from djmdContent c
            left join djmdArtist a on a.ID = c.ArtistID
            left join djmdKey k on k.ID = c.KeyID
            left join djmdGenre g on g.ID = c.GenreID
            where {' and '.join(where)}
            order by {order} limit ?""", (*args, int(limit))).fetchall()
    from setagent.analysis.timing import fmt
    return [{"track_id": tid, "title": t, "artist": a, "bpm": round(b / 100.0, 2), "key": k,
             "camelot": _camelot_str(k), "length": fmt(ln), "genre": g, "rating": rt, "plays": pc,
             "cloud": p.startswith("/contents_") or p.startswith("spotify:") or ft == 25}
            for tid, t, a, b, k, ln, g, rt, pc, p, ft in rows]


# ------------------------------------------------------------------ library

def library_stats(con: sqlite3.Connection, ids: list[str] | None = None, top: int = 10) -> dict:
    where, args = "c.rb_local_deleted = 0", []
    if ids is not None:
        if not ids:
            return {"tracks": 0}
        where += f" and c.ID in ({','.join('?' * len(ids))})"
        args = list(ids)
    rows = con.execute(
        f"""select coalesce(c.BPM,0), coalesce(c.Length,0), coalesce(g.Name,''), coalesce(k.ScaleName,''),
                   coalesce(c.Rating,0), coalesce(c.DJPlayCount,0)
            from djmdContent c
            left join djmdGenre g on g.ID = c.GenreID
            left join djmdKey k on k.ID = c.KeyID
            where {where}""", args).fetchall()
    if not rows:
        return {"tracks": 0}
    bpms = [b / 100.0 for b, *_ in rows if b > 0]
    total = sum(ln for _, ln, *_ in rows)
    hist = Counter(int(b // 10 * 10) for b in bpms)
    genres = Counter(g for _, _, g, *_ in rows if g)
    keys = Counter(_camelot_str(r[3]) or r[3] for r in rows if r[3])
    ratings = Counter(int(r[4]) for r in rows)
    from setagent.analysis.timing import fmt
    return {
        "tracks": len(rows),
        "total_length": fmt(total),
        "total_hours": round(total / 3600, 1),
        "bpm": {"median": round(statistics.median(bpms), 1) if bpms else None,
                "min": round(min(bpms), 1) if bpms else None,
                "max": round(max(bpms), 1) if bpms else None,
                "by_10": {f"{k}-{k + 9}": v for k, v in sorted(hist.items())}},
        "genres": [{"genre": g, "tracks": n} for g, n in genres.most_common(top)],
        "keys": [{"key": k, "tracks": n} for k, n in keys.most_common(top)],
        "ratings": {str(k): v for k, v in sorted(ratings.items())},
        "unplayed": sum(1 for r in rows if not r[5]),
        "most_played": max((r[5] for r in rows), default=0),
    }


def playlist_tree(con: sqlite3.Connection) -> list[dict]:
    """Every playlist with its folder path, the way rekordbox's sidebar shows it."""
    rows = con.execute(
        "select ID, Name, ParentID, Attribute, Seq from djmdPlaylist where rb_local_deleted = 0").fetchall()
    by_id = {r[0]: r for r in rows}
    counts = dict(con.execute(
        "select PlaylistID, count(*) from djmdSongPlaylist where rb_local_deleted = 0 group by PlaylistID"))

    def path(pid: str) -> str:
        parts, seen = [], set()
        while pid in by_id and pid not in seen:
            seen.add(pid)
            parts.append(by_id[pid][1] or "")
            pid = by_id[pid][2]
        return " / ".join(reversed(parts))

    kinds = {0: "playlist", 1: "folder", 4: "smart"}
    out = [{"playlist_id": r[0], "name": r[1] or "", "path": path(r[0]),
            "kind": kinds.get(r[3], str(r[3])), "tracks": counts.get(r[0], 0)} for r in rows]
    return sorted(out, key=lambda x: x["path"].lower())
