"""Build FlickFX.amxd — a frozen Max for Live audio effect, one file, no helpers.

    python m4l/build.py            # frozen dist/FlickFX.amxd (+ install copies)
    python m4l/build.py --dev      # unfrozen m4l/FlickFX.amxd that loads the .js files beside it

Frozen layout (same as tunescope/tools/build-frozen.js, verified in Live):
  ampf[4]"aaaa" | meta[4]u32le(7) | ptch[u32le]( mx@c hdr16 + JSON + deps + dlst )
  dlst > dire{type,fnam,sz32,of32,vers,flag,mdat}, all chunk sizes u32be incl. 8-byte header,
  of32 relative to the ptch payload, JSON entry flag 0x11, mx@c last u32 = dlst offset.
"""
import json
import os
import shutil
import struct
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
NAME = "FlickFX.amxd"
DEPS = ["flickfx.js", "flickfx_view.js"]

# ---- patch -------------------------------------------------------------------
boxes, lines = [], []
_n = [0]


def box(cls, text=None, ins=1, outs=1, rect=(0, 0, 60, 22), outtype=None, **extra):
    _n[0] += 1
    bid = f"obj-{_n[0]}"
    b = {"id": bid, "maxclass": cls, "numinlets": ins, "numoutlets": outs,
         "outlettype": outtype if outtype is not None else [""] * outs,
         "patching_rect": list(rect)}
    if text is not None:
        b["text"] = text
    b.update(extra)
    boxes.append({"box": b})
    return bid


def wire(src, so, dst, di=0):
    lines.append({"patchline": {"source": [src, so], "destination": [dst, di]}})


def dial(longname, short, lo, hi, init, unit, prect, prect_patch, exponent=1.0):
    """live.dial; unitstyle 2 = ms, 5 = %."""
    return box("live.dial", None, 1, 2, prect_patch, ["", "float"],
               parameter_enable=1, presentation=1, presentation_rect=list(prect),
               varname=longname, **DIAL_STYLE,
               saved_attribute_attributes={"valueof": {
                   "parameter_longname": longname, "parameter_shortname": short,
                   "parameter_type": 0, "parameter_mmin": lo, "parameter_mmax": hi,
                   "parameter_initial": [init], "parameter_initial_enable": 1,
                   "parameter_unitstyle": unit, "parameter_exponent": exponent}})


# audio passes straight through; FlickFX sits first in the chain and the managed
# native Limiter at the end of its group catches stacked launches
pin = box("newobj", "plugin~", 2, 2, (20, 20, 60, 22), ["signal", "signal"])
pout = box("newobj", "plugout~", 2, 0, (20, 600, 60, 22), [])
wire(pin, 0, pout, 0)
wire(pin, 1, pout, 1)

engine = box("newobj", "js flickfx.js", 1, 14, (300, 300, 400, 22),
             saved_object_attributes={"filename": "flickfx.js", "parameter_enable": 0})

# device lifecycle: push stored knob/menu values, start the clock, then sync FX slots
dev = box("newobj", "live.thisdevice", 1, 3, (300, 20, 100, 22), ["bang", "int", "int"])
trig = box("newobj", "t b b b", 1, 3, (300, 50, 60, 22), ["bang", "bang", "bang"])
initmsg = box("message", "init", 2, 1, (300, 250, 40, 22))
startmsg = box("message", "1", 2, 1, (380, 80, 30, 22))
metro = box("newobj", "metro 8 @active 0", 2, 1, (380, 110, 110, 22), ["bang"])
tickmsg = box("message", "tick", 2, 1, (380, 140, 40, 22))
wire(dev, 0, trig)
wire(trig, 2, startmsg)
wire(startmsg, 0, metro)
wire(metro, 0, tickmsg)
wire(tickmsg, 0, engine)
wire(trig, 0, initmsg)
wire(initmsg, 0, engine)

# gamepad: events + per-event device info
pad = box("newobj", "gamepad", 1, 3, (520, 20, 70, 22), ["", "", ""])
padinfo = box("newobj", "prepend padinfo", 1, 1, (600, 60, 100, 22))
wire(pad, 0, engine)
wire(pad, 1, padinfo)
wire(padinfo, 0, engine)

DEVW, DEVH = 532, 166

# control styling (matches the view: cyan pill buttons, thin grey frames, cyan dial arcs)
CYAN = [0.36, 0.80, 0.93, 1.0]
INK = [0.05, 0.06, 0.07, 1.0]
FRAMEC = [0.30, 0.31, 0.33, 1.0]
TEXTC = [0.90, 0.91, 0.90, 1.0]
DIMC = [0.32, 0.33, 0.35, 1.0]
BUTTON_STYLE = dict(bgcolor=CYAN, bgoncolor=CYAN, activebgcolor=CYAN, activebgoncolor=CYAN,
                    textcolor=INK, textoncolor=INK, activetextcolor=INK, activetextoncolor=INK, bordercolor=CYAN, focusbordercolor=CYAN, rounded=8.0)
MENU_STYLE = dict(textcolor=TEXTC, activetextcolor=TEXTC, tricolor=CYAN, activetricolor=CYAN, bordercolor=FRAMEC, activebgcolor=[0.03, 0.03, 0.035, 1.0],
                  bgcolor=[0.03, 0.03, 0.035, 1.0])
DIAL_STYLE = dict(activedialcolor=CYAN, activeneedlecolor=TEXTC, dialcolor=DIMC, needlecolor=DIMC, textcolor=TEXTC)
GAP = 4
STAGEW = (DEVW - GAP * 3) / 2

# the animation fills the device; everything else floats on top of it
view = box("jsui", None, 1, 1, (760, 300, 266, 166), filename="flickfx_view.js",
           jsarguments=[], presentation=1, presentation_rect=[0, 0, DEVW, DEVH],
           border=0, parameter_enable=0, background=1)
wire(engine, 12, view)
viewsend = box("newobj", "s ---ffview", 1, 0, (760, 480, 80, 22), [])
wire(engine, 12, viewsend)

ZW, ZH = 1100, 344          # same aspect as the device (532 x 166); fits a 150 %-scaled 1080p screen
zoom_patcher = {
    "fileversion": 1,
    "appversion": {"major": 9, "minor": 1, "revision": 5, "architecture": "x64", "modernui": 1},
    "classnamespace": "box",
    "rect": [60.0, 100.0, float(ZW), float(ZH)],
    "openinpresentation": 1,
    "toolbarvisible": 0, "statusbarvisible": 0, "enablehscroll": 0, "enablevscroll": 0,
    "title": "FlickFX",
    "boxes": [
        {"box": {"id": "z-1", "maxclass": "inlet", "numinlets": 0, "numoutlets": 1, "outlettype": [""],
                 "patching_rect": [20.0, 20.0, 30.0, 30.0], "comment": ""}},
        {"box": {"id": "z-2", "maxclass": "newobj", "text": "r ---ffview", "numinlets": 0, "numoutlets": 1,
                 "outlettype": [""], "patching_rect": [80.0, 20.0, 80.0, 22.0]}},
        {"box": {"id": "z-3", "maxclass": "jsui", "filename": "flickfx_view.js", "jsarguments": ["big"],
                 "numinlets": 1, "numoutlets": 1, "outlettype": [""], "border": 0, "parameter_enable": 0,
                 "patching_rect": [80.0, 60.0, float(ZW), float(ZH)],
                 "presentation": 1, "presentation_rect": [0.0, 0.0, float(ZW), float(ZH)]}},
    ],
    "lines": [{"patchline": {"source": ["z-2", 0], "destination": ["z-3", 0]}},
              {"patchline": {"source": ["z-3", 0], "destination": ["z-4", 0]}}],
}
# the zoom view reports whether its window is visible, so the device view can pause
zoom_patcher["boxes"].append({"box": {"id": "z-4", "maxclass": "newobj", "text": "s ---ffzs", "numinlets": 1,
                                      "numoutlets": 0, "outlettype": [], "patching_rect": [80.0, 440.0, 70.0, 22.0]}})
zsrecv = box("newobj", "r ---ffzs", 0, 1, (760, 520, 70, 22))
wire(zsrecv, 0, view)
zoomwin = box("newobj", "p zoom", 1, 0, (900, 480, 60, 22), [], patcher=zoom_patcher,
              saved_object_attributes={"description": "", "digest": "", "globalpatchername": "", "tags": ""})
zbtn = box("live.text", None, 1, 2, (900, 400, 44, 15), ["", ""],
           presentation=1, presentation_rect=[DEVW - GAP - 46 - 44, GAP + 3, 40, 15],
           texton="zoom", mode=1, parameter_enable=0, varname="zbtn", **BUTTON_STYLE)
boxes[-1]["box"]["text"] = "zoom"
zsel = box("newobj", "sel 1", 2, 2, (900, 430, 50, 22), ["bang", ""])
zopen = box("message", "open", 2, 1, (900, 455, 40, 22))
zpc = box("newobj", "pcontrol", 1, 1, (950, 455, 60, 22))
wire(zbtn, 0, zsel)
wire(zsel, 0, zopen)
wire(zopen, 0, zpc)
wire(zpc, 0, zoomwin)

# FX menus, one per stick, in each stage's header
FX = ["None", "Reverb", "Echo", "Grain Delay", "Auto Filter", "Phaser-Flanger", "Redux"]
for k, (name, init) in enumerate((("FX L", 1), ("FX R", 2))):
    menu = box("live.menu", None, 1, 3, (760 + k * 120, 500, 100, 15), ["", "", "float"],
               parameter_enable=1, presentation=1,
               presentation_rect=[GAP + k * (STAGEW + GAP) + 16, GAP + 3, 100, 15], varname=name, **MENU_STYLE,
               saved_attribute_attributes={"valueof": {
                   "parameter_longname": name, "parameter_shortname": name, "parameter_type": 2,
                   "parameter_enum": FX, "parameter_mmax": len(FX) - 1,
                   "parameter_initial": [init], "parameter_initial_enable": 1, "parameter_unitstyle": 9}})
    pre = box("newobj", "prepend fxl" if k == 0 else "prepend fxr", 1, 1, (760 + k * 120, 530, 80, 22))
    wire(menu, 0, pre)
    wire(pre, 0, engine)
    wire(trig, 1, menu)

# collapsible knob panel: hidden until the "knobs" toggle is on
PANEL = []
toggle = box("live.text", None, 1, 2, (1000, 20, 44, 15), ["", ""],
             presentation=1, presentation_rect=[DEVW - GAP - 46, GAP + 3, 40, 15],
             texton="knobs", mode=1, parameter_enable=0, varname="ktoggle", **BUTTON_STYLE)
boxes[-1]["box"]["text"] = "knobs"
# the panel backdrop is drawn by the jsui (background layer) so the dials stay on top
# live.text here behaves as a momentary button (always sends 1), so flip the state ourselves
press = box("newobj", "sel 1", 2, 2, (1000, 140, 50, 22), ["bang", ""])
flip = box("toggle", None, 1, 1, (1000, 170, 22, 22), ["int"], parameter_enable=0)   # bang flips 0/1
wire(toggle, 0, press)
wire(press, 0, flip)
panelmsg = box("newobj", "prepend panel", 1, 1, (1000, 320, 90, 22))
wire(flip, 0, panelmsg)
wire(panelmsg, 0, view)

dials = [
    ("Preload", "Preload", 0, 50, 15, 5),
    ("Launch", "Launch", 0, 100, 100, 5),
    ("Attack", "Attack", 1, 300, 30, 2),
    ("Hold", "Hold", 0, 1000, 80, 2),
    ("Decay L", "Decay L", 100, 6000, 1200, 2),
    ("Decay R", "Decay R", 100, 6000, 1200, 2),
    ("Weight", "Weight", 0, 100, 60, 5),
    ("Snap", "Snap", 20, 400, 100, 2),
    ("Spread", "Spread", 0, 100, 30, 5),
    ("Crush L", "Crush L", 0, 100, 73, 5),
    ("Crush R", "Crush R", 0, 100, 73, 5),
]
DW, DH = 42, 62
step = (DEVW - 2 * GAP - 20) / len(dials)
dial_ids = {}
for i, (ln, sn, lo, hi, init, unit) in enumerate(dials):
    # note: parameter_exponent != 1 makes Live read parameter_initial as a linear position
    d = dial(ln, sn, lo, hi, init, unit,
             (GAP + 10 + i * step + (step - DW) / 2, GAP + 40, DW, DH), (20 + i * 70, 400, DW, DH))
    boxes[-1]["box"]["hidden"] = 1
    vn = ln.replace(" ", "").lower()
    boxes[-1]["box"]["varname"] = ln.replace(" ", "")   # scripting names cannot contain spaces
    PANEL.append(ln.replace(" ", ""))
    dial_ids[vn] = d
    pre = box("newobj", f"prepend {vn}", 1, 1, (20 + i * 70, 480, 66, 22))
    wire(d, 0, pre)
    wire(pre, 0, engine)
    wire(trig, 1, d)                       # re-output stored value on load

# D-pad steps the Decay dials (engine outlet 13 -> the dial, which reports back)
ctl = box("newobj", "route decayl decayr crushl crushr", 1, 5, (20, 560, 200, 22), ["", "", "", "", ""])
wire(engine, 13, ctl)
wire(ctl, 0, dial_ids["decayl"])
wire(ctl, 1, dial_ids["decayr"])
wire(ctl, 2, dial_ids["crushl"])
wire(ctl, 3, dial_ids["crushr"])

# toggle -> show/hide the panel objects by scripting name
sel = box("newobj", "sel 0 1", 1, 3, (1000, 200, 60, 22), ["bang", "bang", ""])
hide = box("message", ", ".join(f"script hide {n}" for n in PANEL), 2, 1, (1000, 230, 300, 22))
show = box("message", ", ".join(f"script show {n}" for n in PANEL), 2, 1, (1000, 260, 300, 22))
tp = box("newobj", "thispatcher", 1, 2, (1000, 290, 80, 22), ["", ""])
wire(flip, 0, sel)
wire(sel, 0, hide)
wire(sel, 1, show)
wire(hide, 0, tp)
wire(show, 0, tp)

# outputs: per side three live.remote~ (Dry/Wet, X colour, Y size), each smoothed by line~
for side in (0, 1):
    for k, ms in ((0, 8), (2, 25), (4, 25)):
        o = side * 6 + k
        m = box("message", f"$1 {ms}", 2, 1, (300 + o * 50, 360, 46, 22))
        ln = box("newobj", "line~", 2, 2, (300 + o * 50, 390, 46, 22), ["signal", "bang"])
        rem = box("newobj", "live.remote~", 2, 0, (300 + o * 50, 430, 80, 22), [])
        wire(engine, o, m)
        wire(m, 0, ln)
        wire(ln, 0, rem)
        wire(engine, o + 1, rem, 1)

hfs = int(time.time()) + 2082844800
patch = {"patcher": {
    "fileversion": 1,
    "appversion": {"major": 9, "minor": 1, "revision": 5, "architecture": "x64", "modernui": 1},
    "classnamespace": "box",
    "rect": [80, 80, 1300, 700],
    "openinpresentation": 1,
    "devicewidth": float(DEVW),
    "boxes": boxes,
    "lines": lines,
    "project": {"version": 1, "creationdate": hfs, "modificationdate": hfs,
                "viewrect": [0, 0, 300, 500], "autoorganize": 1, "hideprojectwindow": 1,
                "showdependencies": 1, "autolocalize": 0, "contents": {"patchers": {}},
                "layout": {}, "searchpath": {}, "detailsvisible": 0,
                "amxdtype": 1633771873, "readonly": 0, "devpathtype": 0, "devpath": ".",
                "sortmode": 0, "viewmode": 0, "includepackages": 0},
}}

# ---- containers ---------------------------------------------------------------


def le_chunk(tag, data):
    return tag.encode() + struct.pack("<I", len(data)) + data


def be_chunk(tag, payload):
    return tag.encode() + struct.pack(">I", len(payload) + 8) + payload


def fnam(name):
    n = name.encode()
    return n + b"\0" * ((len(n) // 4 + 1) * 4 - len(n))


def dire(kind, name, size, offset, flag):
    return be_chunk("dire", b"".join([
        be_chunk("type", kind.encode()), be_chunk("fnam", fnam(name)),
        be_chunk("sz32", struct.pack(">I", size)), be_chunk("of32", struct.pack(">I", offset)),
        be_chunk("vers", struct.pack(">I", 0)), be_chunk("flag", struct.pack(">I", flag)),
        be_chunk("mdat", struct.pack(">I", hfs))]))


def header(ptch):
    return le_chunk("ampf", b"aaaa") + le_chunk("meta", struct.pack("<I", 7)) + le_chunk("ptch", ptch)


def build_dev() -> Path:
    body = (json.dumps(patch, indent=4) + "\n").encode() + b"\0"
    out = HERE / NAME
    out.write_bytes(header(body))
    return out


BENCH = os.environ.get("FLICKFX_BENCH") == "1"


def dep_bytes(dep):
    data = (HERE / dep).read_bytes()
    extra = HERE.parent / "tools" / ("bench_" + dep)
    if BENCH and extra.exists():
        data += b"\n" + extra.read_bytes()
    return data


def build_frozen() -> Path:
    js = (json.dumps(patch, indent=4) + "\n").encode() + b"\0"
    parts, entries = [js], [dire("JSON", NAME, len(js), 16, 0x11)]
    off = 16 + len(js)
    for dep in DEPS:
        data = dep_bytes(dep)
        parts.append(data)
        entries.append(dire("TEXT", dep, len(data), off, 0))
        off += len(data)
    mxc = b"mx@c" + struct.pack(">III", 16, 0, off)
    ptch = mxc + b"".join(parts) + be_chunk("dlst", b"".join(entries))
    out = ROOT / "dist" / NAME
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(header(ptch))
    return out


def _documents() -> Path:
    import ctypes
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)  # CSIDL_PERSONAL (may be OneDrive)
    return Path(buf.value)


def main():
    if "--dev" in sys.argv:
        print("built", build_dev())
        return
    out = build_frozen()
    print(f"frozen {out} ({out.stat().st_size} bytes)")
    lib = _documents() / "Ableton/User Library/Presets/Audio Effects/Max Audio Effect"
    lib.mkdir(parents=True, exist_ok=True)
    shutil.copy2(out, lib / NAME)
    print("installed ->", lib / NAME)


if __name__ == "__main__":
    main()
