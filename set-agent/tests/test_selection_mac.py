"""selection's macOS path and follow_check, against fake AppKit / ApplicationServices.

No Mac in CI on Linux: these stand-ins answer the pyobjc calls the code makes
(the (err, value) tuples, runningApplications, activationPolicy...) so the
control flow -- which process is read, permission, the remembered element --
is exercised everywhere. The real read is checked with --follow-check on a Mac.
"""
import io
import sys
import types
import unittest
from contextlib import redirect_stdout

from setagent.rekordbox import selection as S


class App:
    def __init__(self, name, bid, pid, policy=0):
        self.n, self.b, self.p, self.pol = name, bid, pid, policy

    def localizedName(self): return self.n
    def bundleIdentifier(self): return self.b
    def processIdentifier(self): return self.p
    def activationPolicy(self): return self.pol


def node(role, *kids, value=None):
    return {"AXRole": role, "AXValue": value, "AXChildren": list(kids), "AXTitle": None, "AXDescription": None}


STATUS = "22 トラック, 1 時間 37 分, 175.9 MB"


def fakes(trusted=True, apps=None, trees=None):
    trees = trees or {}
    calls = []

    def copy(e, a, _):
        calls.append(a)
        if isinstance(e, tuple) and e[0] == "app":
            return (0, trees.get(e[1], [])) if a == "AXWindows" else (-25205, None)
        v = e.get(a) if isinstance(e, dict) else None
        return (0, v) if v is not None else (-25212, None)

    AS = types.SimpleNamespace(
        AXIsProcessTrusted=lambda: trusted,
        AXUIElementCreateApplication=lambda pid: ("app", pid),
        AXUIElementCreateSystemWide=lambda: ("sys",),
        AXUIElementSetMessagingTimeout=lambda e, t: 0,
        AXUIElementCopyAttributeValue=copy,
        AXIsProcessTrustedWithOptions=lambda o: trusted,
        kAXTrustedCheckOptionPrompt="prompt",
    )
    ws = types.SimpleNamespace(runningApplications=lambda: apps or [])
    AppKit = types.SimpleNamespace(
        NSWorkspace=types.SimpleNamespace(sharedWorkspace=lambda: ws),
        NSBundle=types.SimpleNamespace(mainBundle=lambda: types.SimpleNamespace(
            bundlePath=lambda: "/Applications/SetAgent.app", bundleIdentifier=lambda: "jp.alphatheta.setagent")),
    )
    return AppKit, AS, calls


class MacPathTests(unittest.TestCase):
    def setUp(self):
        self.saved = {k: sys.modules.get(k) for k in ("AppKit", "ApplicationServices")}
        S._found.clear()

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        S._found.clear()

    def install(self, **kw):
        AppKit, AS, calls = fakes(**kw)
        sys.modules["AppKit"], sys.modules["ApplicationServices"] = AppKit, AS
        return calls

    def window(self):
        return [node("AXWindow", node("AXGroup", node("AXScrollArea", node("AXTable", *[node("AXRow")] * 50)),
                                      node("AXStaticText", value=STATUS)))]

    def test_reads_rekordbox_not_its_agent(self):
        self.install(apps=[App("rekordboxAgent", "com.pioneerdj.rekordboxagent", 11, policy=1),
                           App("rekordbox", "com.pioneerdj.rekordboxdj", 22)],
                     trees={11: [], 22: self.window()})
        self.assertEqual(S._mac_status_text(4.0), (STATUS, "ok"))

    def test_remembered_element_is_one_call(self):
        calls = self.install(apps=[App("rekordbox", "com.pioneerdj.rekordboxdj", 22)], trees={22: self.window()})
        S._mac_status_text(4.0)
        calls.clear()
        self.assertEqual(S._mac_status_text(4.0), (STATUS, "ok"))
        self.assertEqual(calls, ["AXValue"])

    def test_no_permission_and_not_running(self):
        self.install(trusted=False, apps=[App("rekordbox", "x", 1)])
        self.assertEqual(S._mac_status_text(), (None, "no_permission"))
        self.install(apps=[App("Finder", "com.apple.finder", 3)])
        self.assertEqual(S._mac_status_text(), (None, "not_running"))

    def test_follow_check_reports_each_link(self):
        from setagent.rekordbox import follow_check as F
        self.install(apps=[App("rekordbox", "com.pioneerdj.rekordboxdj", 22)], trees={22: self.window()})
        out = F.Out()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(F._mac(out), STATUS)
        text = "\n".join(out.lines)
        self.assertIn("[OK] アクセシビリティの許可", text)
        self.assertIn("<== status line", text)
        self.assertIn("(data view: not entered)", text)


if __name__ == "__main__":
    unittest.main()
