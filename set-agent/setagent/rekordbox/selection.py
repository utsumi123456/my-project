"""Which playlist the DJ is looking at in rekordbox right now.

rekordbox never writes its tree selection anywhere while it runs (measured
2026-10-09: browseSetting.xml only changes on save/exit, the database not at
all). What it does show, live, is the browser's status line under the track
list -- "96 トラック, 10 時間 55 分, 1.5 GB" -- and rekordbox's UI (JUCE)
exposes that text to the OS accessibility API. Track count, total length and
total size together are a fingerprint of the list on screen; matching it
against every playlist in the library names the selection.

Reading is geometry-free and needs the Accessibility permission on macOS
(the same one docking's split mode asks for). Windows reads the same text
through UI Automation. When nothing can be read -- no permission, rekordbox
closed, the collection or a search result on screen -- `read()` says so and
the panel keeps showing what it showed.
"""
from __future__ import annotations

import re
import sqlite3
import sys
from dataclasses import dataclass, field

_SIZE = re.compile(r"([\d.,]+)\s*(KB|MB|GB|TB)", re.I)
_NUMS = re.compile(r"\d+")


@dataclass(frozen=True)
class Status:
    tracks: int
    minutes: int              # total length, floored to whole minutes as rekordbox prints it
    size_mib: float           # in MiB
    size_step: float          # how coarse the printed size is, in MiB (0.1 MB, 0.1 GB, ...)
    text: str


def parse(text: str) -> Status | None:
    """'22 トラック, 1 時間 37 分, 175.9 MB' / '96 tracks, 10 hr 55 min, 1.5 GB'."""
    if not text:
        return None
    m = _SIZE.search(text)
    if not m:
        return None
    head = text[:m.start()]
    nums = [int(x) for x in _NUMS.findall(head)]
    if not nums:
        return None
    count, rest = nums[0], nums[1:]
    if len(rest) >= 3:                        # h m s
        minutes = rest[0] * 60 + rest[1]
    elif len(rest) == 2:                      # h m
        minutes = rest[0] * 60 + rest[1]
    elif len(rest) == 1:
        minutes = rest[0] * (60 if re.search(r"時間|hr|hour|h\b", head) and not re.search(r"分|min", head) else 1)
    else:
        minutes = 0
    raw = m.group(1).replace(",", ".")
    try:
        val = float(raw)
    except ValueError:
        return None
    unit = {"KB": 1 / 1024, "MB": 1, "GB": 1024, "TB": 1024 * 1024}[m.group(2).upper()]
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    return Status(count, minutes, val * unit, unit * (10 ** -decimals), text)


# ------------------------------------------------------------------ matching

@dataclass
class Fingerprints:
    """(count, minutes, MiB) of every playlist, built once per library load."""
    rows: list[tuple[str, str, int, float, float, bool]] = field(default_factory=list)
    # (playlist_id, name, count, seconds, MiB, in_set_agent_folder)

    @classmethod
    def build(cls, con: sqlite3.Connection, set_agent_folder: str = "Set Agent") -> "Fingerprints":
        folder = {r[0] for r in con.execute(
            "select ID from djmdPlaylist where ParentID='root' and Name=? and Attribute=1 "
            "and rb_local_deleted=0", (set_agent_folder,))}
        rows = []
        for pid, name, parent, n, secs, size in con.execute(
                """select p.ID, p.Name, p.ParentID, count(s.ID), coalesce(sum(c.Length),0),
                          coalesce(sum(c.FileSize),0)
                   from djmdPlaylist p
                   join djmdSongPlaylist s on s.PlaylistID = p.ID and s.rb_local_deleted = 0
                   join djmdContent c on c.ID = s.ContentID
                   where p.rb_local_deleted = 0 and p.Attribute = 0
                   group by p.ID"""):
            rows.append((pid, name or "", int(n), float(secs), size / 1048576, parent in folder))
        return cls(rows)

    def match(self, st: Status, prefer: str | None = None) -> list[tuple[str, str, bool]]:
        """Playlists whose fingerprint fits, best first: the one already shown
        (`prefer`), then playlists outside the Set Agent folder."""
        tol = max(st.size_step * 0.55, 0.06)
        hits = [(pid, name, mine) for pid, name, n, secs, mib, mine in self.rows
                if n == st.tracks and abs(int(secs // 60) - st.minutes) <= 1 and abs(mib - st.size_mib) <= tol]
        hits.sort(key=lambda h: (h[0] != prefer, h[2]))
        return hits


# ------------------------------------------------------------------ reading

def _mac_status_text() -> tuple[str | None, str]:
    try:
        import AppKit
        import ApplicationServices as AS
    except Exception:
        return None, "unsupported"
    if not AS.AXIsProcessTrusted():
        return None, "no_permission"
    pids = [int(a.processIdentifier()) for a in AppKit.NSWorkspace.sharedWorkspace().runningApplications()
            if (a.localizedName() or "") == "rekordbox"]
    if not pids:
        return None, "not_running"

    def attr(e, a):
        err, v = AS.AXUIElementCopyAttributeValue(e, a, None)
        return None if err else v

    def find(e, depth):
        for c in attr(e, "AXChildren") or []:
            if attr(c, "AXRole") == "AXStaticText":
                v = attr(c, "AXValue")
                if v and _SIZE.search(str(v)) and _NUMS.match(str(v).strip()):
                    return str(v)
            if depth < 3:
                r = find(c, depth + 1)
                if r:
                    return r
        return None

    app = AS.AXUIElementCreateApplication(pids[0])
    for w in attr(app, "AXWindows") or []:
        t = find(w, 0)
        if t:
            return t, "ok"
    return None, "not_found"


def _win_status_text() -> tuple[str | None, str]:
    """UI Automation over comtypes. JUCE exposes the same static text on
    Windows; untested on hardware yet (2026-10-09)."""
    try:
        import comtypes.client
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as UIA
    except Exception:
        return None, "unsupported"
    try:
        uia = comtypes.client.CreateObject("{ff48dba4-60ef-4201-aa87-54103eef594e}", interface=UIA.IUIAutomation)
        root = uia.GetRootElement()
        cond = uia.CreatePropertyCondition(UIA.UIA_NamePropertyId, "rekordbox")
        win = root.FindFirst(UIA.TreeScope_Children, cond)
        if not win:
            return None, "not_running"
        texts = win.FindAll(UIA.TreeScope_Descendants,
                            uia.CreatePropertyCondition(UIA.UIA_ControlTypePropertyId, UIA.UIA_TextControlTypeId))
        for i in range(texts.Length):
            el = texts.GetElement(i)
            for v in (el.CurrentName, _uia_value(el, UIA)):
                if v and _SIZE.search(v) and _NUMS.match(v.strip()):
                    return v, "ok"
        return None, "not_found"
    except Exception:
        return None, "not_found"


def _uia_value(el, UIA) -> str:
    try:
        p = el.GetCurrentPattern(UIA.UIA_ValuePatternId)
        return p.QueryInterface(UIA.IUIAutomationValuePattern).CurrentValue or ""
    except Exception:
        return ""


def status_text() -> tuple[str | None, str]:
    """(text, why). why: ok | no_permission | not_running | not_found | unsupported"""
    try:
        if sys.platform == "darwin":
            return _mac_status_text()
        if sys.platform.startswith("win"):
            return _win_status_text()
    except Exception:
        return None, "not_found"
    return None, "unsupported"


def request_permission() -> bool:
    """macOS: show the system prompt that adds Set Agent to Accessibility."""
    if sys.platform != "darwin":
        return True
    try:
        import ApplicationServices as AS
        return bool(AS.AXIsProcessTrustedWithOptions({AS.kAXTrustedCheckOptionPrompt: True}))
    except Exception:
        return False


def read(fp: Fingerprints | None, prefer: str | None = None) -> dict:
    """{playlist_id, name, ambiguous, why, text}. playlist_id None = keep what is shown."""
    text, why = status_text()
    out = {"playlist_id": None, "name": "", "ambiguous": False, "why": why, "text": text or ""}
    if why != "ok" or fp is None:
        return out
    st = parse(text)
    if st is None:
        out["why"] = "not_found"
        return out
    hits = fp.match(st, prefer)
    if not hits:
        out["why"] = "no_match"               # the collection, a search, a device list...
        return out
    out.update(playlist_id=hits[0][0], name=hits[0][1], ambiguous=len(hits) > 1)
    return out
