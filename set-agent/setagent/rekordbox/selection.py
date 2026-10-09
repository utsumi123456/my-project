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
import time
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

_AX_CALL_S = 0.5     # one accessibility call
WALK_BOOT_S = 1.5    # boot() holds the "loading library" curtain: keep it short
WALK_POLL_S = 4.0    # the 1.2s follow poll runs off the worker; one slow walk is fine
_RECHECK_S = 15.0    # re-walk now and then even when the remembered element answers

# Roles whose children are rows of data, never the status line. rekordbox's
# track list is one of these, with an element per visible row and cell; the
# first version descended into it depth-first and could spend the whole walk
# budget there on a long list, which then read as "busy" on every poll and the
# panel silently stopped following (2026-10-09).
_SKIP_ROLES = frozenset({"AXTable", "AXOutline", "AXList", "AXRow", "AXCell",
                         "AXColumn", "AXGrid", "AXBrowser", "AXMenuBar", "AXMenu"})
_MAX_DEPTH = 6


class WalkTimeout(Exception):
    pass


def is_status(v) -> bool:
    s = str(v or "").strip()
    return bool(s) and bool(_SIZE.search(s)) and bool(_NUMS.match(s))


def find_status(roots, attr, deadline: float, clock=time.monotonic):
    """Breadth-first search for the status line under `roots`.

    `attr(element, name)` returns an AX attribute or None. Breadth-first
    because the status line sits a few levels under the window while the
    data views are deep and wide; data views are not entered at all. Returns
    (element, text) or (None, None); raises WalkTimeout past `deadline`."""
    level = list(roots)
    for _ in range(_MAX_DEPTH + 1):
        nxt = []
        for e in level:
            if clock() > deadline:
                raise WalkTimeout
            role = attr(e, "AXRole")
            if role == "AXStaticText":
                v = attr(e, "AXValue")
                if is_status(v):
                    return e, str(v).strip()
                continue
            if role in _SKIP_ROLES:
                continue
            nxt.extend(attr(e, "AXChildren") or [])
        if not nxt:
            break
        level = nxt
    return None, None


# pid -> (status-line element, when it was found). Reading one remembered
# element is a single AX call; the walk only runs when it stops answering,
# rekordbox restarts, or now and then in case rekordbox rebuilt its view.
_found: dict[int, tuple[object, float]] = {}


def _mac_status_text(budget: float = WALK_BOOT_S) -> tuple[str | None, str]:
    try:
        import AppKit
        import ApplicationServices as AS
    except Exception:
        return None, "unsupported"
    if not AS.AXIsProcessTrusted():
        return None, "no_permission"
    pids = mac_rekordbox_pids(AppKit)
    if not pids:
        _found.clear()
        return None, "not_running"

    # A busy rekordbox (analysing, loading a library) answers AX calls late, and each
    # call waits up to 6s by default; a walk of dozens of calls then held boot() --
    # and the "loading library" curtain -- for minutes. Cap each call and the walk.
    try:
        AS.AXUIElementSetMessagingTimeout(AS.AXUIElementCreateSystemWide(), _AX_CALL_S)
    except Exception:
        pass

    now = time.monotonic()
    for pid in pids:
        hit = _found.get(pid)
        if hit and now - hit[1] < _RECHECK_S:
            err, v = AS.AXUIElementCopyAttributeValue(hit[0], "AXValue", None)
            if not err and is_status(v):
                return str(v).strip(), "ok"
        _found.pop(pid, None)

    def attr(e, a):
        err, v = AS.AXUIElementCopyAttributeValue(e, a, None)
        return None if err else v

    deadline = now + budget
    for pid in pids:                          # normally one; a helper process has no windows
        app = AS.AXUIElementCreateApplication(pid)
        try:
            AS.AXUIElementSetMessagingTimeout(app, _AX_CALL_S)
        except Exception:
            pass
        try:
            el, text = find_status(attr(app, "AXWindows") or [], attr, deadline)
        except WalkTimeout:
            return None, "busy"
        if el is not None:
            _found[pid] = (el, time.monotonic())
            return text, "ok"
    return None, "not_found"


REKORDBOX_BUNDLE_IDS = ("com.pioneerdj.rekordboxdj",)


def mac_rekordbox_pids(AppKit) -> list[int]:
    """rekordbox's process, the app itself first. Matched by its bundle id or its
    exact name, never by prefix: rekordbox ships helper apps (rekordboxAgent...)
    that have no browser and would be read instead."""
    apps = AppKit.NSWorkspace.sharedWorkspace().runningApplications()
    first, rest = [], []
    for a in apps:
        name = str(a.localizedName() or "")
        bid = str(a.bundleIdentifier() or "")
        if bid in REKORDBOX_BUNDLE_IDS or name == "rekordbox":
            (first if a.activationPolicy() == 0 else rest).append(int(a.processIdentifier()))
    return first + rest


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
                if is_status(v):
                    return v.strip(), "ok"
        return None, "not_found"
    except Exception:
        return None, "not_found"


def _uia_value(el, UIA) -> str:
    try:
        p = el.GetCurrentPattern(UIA.UIA_ValuePatternId)
        return p.QueryInterface(UIA.IUIAutomationValuePattern).CurrentValue or ""
    except Exception:
        return ""


def status_text(budget: float = WALK_BOOT_S) -> tuple[str | None, str]:
    """(text, why). why: ok | busy | no_permission | not_running | not_found | unsupported"""
    try:
        if sys.platform == "darwin":
            return _mac_status_text(budget)
        if sys.platform.startswith("win"):
            return _win_status_text()
    except Exception:
        return None, "not_found"
    return None, "unsupported"


ACCESSIBILITY_PANE = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"


def request_permission() -> bool:
    """macOS: add Set Agent to the Accessibility list (the system prompt) and open
    that pane, so the DJ lands on the switch instead of hunting for it."""
    if sys.platform != "darwin":
        return True
    try:
        import ApplicationServices as AS
        ok = bool(AS.AXIsProcessTrustedWithOptions({AS.kAXTrustedCheckOptionPrompt: True}))
    except Exception:
        ok = False
    if not ok:
        try:
            import subprocess
            subprocess.Popen(["open", ACCESSIBILITY_PANE])
        except Exception:
            pass
    return ok


def read(fp: Fingerprints | None, prefer: str | None = None, budget: float | None = None) -> dict:
    """{playlist_id, name, ambiguous, why, text}. playlist_id None = keep what is shown.
    `budget`: seconds the accessibility walk may take (default: the short boot budget)."""
    text, why = status_text() if budget is None else status_text(budget)
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
