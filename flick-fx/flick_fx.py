"""flick_fx — flick a centre-returning gamepad stick to throw an FX's Dry/Wet.

Reads an XInput pad (left stick, up direction) and sends a MIDI CC that
jumps to the flick strength and then decays back to 0 (dry). Map the CC
to any Dry/Wet knob with Ableton's MIDI Map mode.

    python flick_fx.py --list            # show MIDI outputs
    python flick_fx.py --monitor         # no MIDI, just show stick / wet
    python flick_fx.py --port loopMIDI   # run (substring match on port name)
    python flick_fx.py --port loopMIDI --learn   # wiggle the CC for MIDI Map
"""
from __future__ import annotations

import argparse
import ctypes
import math
import sys
import time
from ctypes import wintypes


# --- XInput -----------------------------------------------------------------

class _Gamepad(ctypes.Structure):
    _fields_ = [("wButtons", wintypes.WORD), ("bLeftTrigger", ctypes.c_ubyte),
                ("bRightTrigger", ctypes.c_ubyte), ("sThumbLX", ctypes.c_short),
                ("sThumbLY", ctypes.c_short), ("sThumbRX", ctypes.c_short),
                ("sThumbRY", ctypes.c_short)]


class _State(ctypes.Structure):
    _fields_ = [("dwPacketNumber", wintypes.DWORD), ("Gamepad", _Gamepad)]


def _load_xinput():
    for name in ("XInput1_4", "XInput1_3", "XInput9_1_0"):
        try:
            return ctypes.windll.LoadLibrary(name)
        except OSError:
            continue
    sys.exit("XInput DLL not found")


class Pad:
    def __init__(self, index: int | None = None):
        self._x = _load_xinput()
        self._state = _State()
        self.index = index if index is not None else self._first_connected()

    def _first_connected(self) -> int:
        for i in range(4):
            if self._x.XInputGetState(i, ctypes.byref(self._state)) == 0:
                return i
        sys.exit("no XInput controller connected")

    def left_stick(self) -> tuple[float, float] | None:
        """(x, y) in -1..1, y up positive; None if the pad dropped out."""
        if self._x.XInputGetState(self.index, ctypes.byref(self._state)) != 0:
            return None
        g = self._state.Gamepad
        return max(-1.0, g.sThumbLX / 32767), max(-1.0, g.sThumbLY / 32767)


# --- flick envelope -----------------------------------------------------------

class FlickEnvelope:
    """Wet follows the stick's peak while it is deflected, then decays.

    A flick is just a very short deflection, so the same rule gives an
    instant "throw" for a flick and a natural hold when the stick is held.
    """

    def __init__(self, deadzone=0.20, curve=1.0, decay_s=0.8, release_s=0.0):
        self.deadzone = deadzone
        self.curve = curve
        self.decay_s = decay_s
        self.release_s = release_s   # extra hold after the stick returns
        self.wet = 0.0
        self._held = False
        self._since_release = 0.0

    def amount(self, x: float, y: float) -> float:
        """Up-direction deflection mapped past the deadzone to 0..1."""
        up = y if y > 0 and y >= abs(x) * 0.6 else 0.0   # ignore mostly-sideways
        if up <= self.deadzone:
            return 0.0
        return min(1.0, (up - self.deadzone) / (1 - self.deadzone)) ** self.curve

    def step(self, x: float, y: float, dt: float) -> float:
        a = self.amount(x, y)
        if a > 0:
            self._held = True
            self.wet = max(self.wet, a)          # attack is instant; retrigger keeps the max
        else:
            if self._held:
                self._held = False
                self._since_release = 0.0
            self._since_release += dt
            if self._since_release > self.release_s and self.wet > 0:
                # exponential fall that reaches ~1/127 after decay_s
                self.wet *= math.exp(-dt * math.log(127) / max(self.decay_s, 1e-3))
                if self.wet < 1 / 127:
                    self.wet = 0.0
        return self.wet


class PlungerEnvelope:
    """Pinball plunger: pull to charge, let go to launch.

    pulled         -> wet = preload * pull            (a hint of the FX)
    snap to centre -> wet rises to launch * peak_pull (the sweet spot), holds,
                      then decays; a harder pull also rings longer
    slow return    -> no launch, the preload just fades out

    "Snap" means the stick was still near its peak pull within `snap_s`
    before reaching the centre, which a spring return always is.
    """

    def __init__(self, deadzone=0.20, curve=1.0, decay_s=1.2, preload=0.15,
                 launch=1.0, attack_s=0.03, hold_s=0.08, snap_s=0.10,
                 decay_scale=0.6, direction="any"):
        self.deadzone = deadzone
        self.curve = curve
        self.decay_s = decay_s
        self.preload = preload
        self.launch = launch
        self.attack_s = attack_s
        self.hold_s = hold_s
        self.snap_s = snap_s
        self.decay_scale = decay_scale   # 0 = fixed decay, 1 = decay fully proportional to pull
        self.direction = direction
        self.wet = 0.0
        self._peak = 0.0        # strongest pull of the current charge
        self._near_peak_t = 0.0  # seconds since the stick was last >= half the peak
        self._target = 0.0      # launch level while attacking
        self._phase = "idle"    # idle | charge | attack | hold | decay
        self._t = 0.0           # time in phase
        self._decay = decay_s

    def amount(self, x: float, y: float) -> float:
        if self.direction == "up":
            v = y if y > 0 and y >= abs(x) * 0.6 else 0.0
        elif self.direction == "down":
            v = -y if y < 0 and -y >= abs(x) * 0.6 else 0.0
        else:
            v = min(1.0, math.hypot(x, y))
        if v <= self.deadzone:
            return 0.0
        return min(1.0, (v - self.deadzone) / (1 - self.deadzone)) ** self.curve

    def _fall(self, dt: float) -> None:
        self.wet *= math.exp(-dt * math.log(127) / max(self._decay, 1e-3))
        if self.wet < 1 / 127:
            self.wet = 0.0

    def step(self, x: float, y: float, dt: float) -> float:
        a = self.amount(x, y)
        self._t += dt
        if a > 0:
            if self._phase != "charge":
                self._phase, self._peak, self._t = "charge", 0.0, 0.0
            self._peak = max(self._peak, a)
            self._near_peak_t = 0.0 if a >= 0.5 * self._peak else self._near_peak_t + dt
            # a still-ringing launch keeps sounding while you pull again
            self._fall(dt)
            self.wet = max(self.wet, self.preload * a)
            return self.wet

        if self._phase == "charge":
            if self._near_peak_t + dt <= self.snap_s:
                self._target = min(1.0, self.launch * self._peak)
                self._decay = self.decay_s * ((1 - self.decay_scale) + self.decay_scale * self._peak)
                self._phase, self._t = "attack", 0.0
            else:
                self._decay = self.decay_s * 0.5
                self._phase, self._t = "decay", 0.0

        if self._phase == "attack":
            if self._t >= self.attack_s:
                self.wet = max(self.wet, self._target)
                self._phase, self._t = "hold", 0.0
            else:
                # ease-out rise from wherever the preload left it
                k = 1 - (1 - self._t / self.attack_s) ** 2
                self.wet = max(self.wet, self._target * k)
        elif self._phase == "hold":
            if self._t >= self.hold_s:
                self._phase, self._t = "decay", 0.0
        elif self._phase == "decay":
            self._fall(dt)
            if self.wet == 0.0:
                self._phase = "idle"
        return self.wet


# --- main ---------------------------------------------------------------------

class OscOut:
    """Minimal OSC-over-UDP sender for the FlickFX M4L device ([udpreceive])."""

    def __init__(self, port: int, host="127.0.0.1"):
        import socket
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._addr = (host, port)

    @staticmethod
    def _pad(b: bytes) -> bytes:
        return b + b"\0" * (4 - len(b) % 4)

    def send(self, address: str, value: float | None = None) -> None:
        import struct
        if value is None:
            pkt = self._pad(address.encode()) + self._pad(b",")
        else:
            pkt = self._pad(address.encode()) + self._pad(b",f") + struct.pack(">f", value)
        self._sock.sendto(pkt, self._addr)


def open_port(name_part: str):
    import mido
    names = mido.get_output_names()
    for n in names:
        if name_part.lower() in n.lower():
            return mido.open_output(n), n
    sys.exit(f"no MIDI output matching {name_part!r}; available: {names}")


def bar(v: float, width=30) -> str:
    n = round(v * width)
    return "#" * n + "." * (width - n)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="list MIDI outputs and exit")
    ap.add_argument("--monitor", action="store_true", help="no MIDI output, print only")
    ap.add_argument("--learn", action="store_true", help="wiggle the CC so Ableton MIDI Map can learn it")
    ap.add_argument("--midi", action="store_true", help="send MIDI CC instead of UDP to the FlickFX device")
    ap.add_argument("--udp", type=int, default=9031, help="UDP port of the FlickFX M4L device")
    ap.add_argument("--port", default="loopMIDI", help="MIDI output name (substring), with --midi")
    ap.add_argument("--channel", type=int, default=1, help="MIDI channel 1-16")
    ap.add_argument("--cc", type=int, default=20, help="CC number")
    ap.add_argument("--mode", choices=("plunger", "flick"), default="plunger",
                    help="plunger: pull to charge, release to launch / flick: wet follows the stick")
    ap.add_argument("--decay", type=float, default=None, help="seconds to fall back to dry (plunger 1.2, flick 0.8)")
    ap.add_argument("--hold", type=float, default=None, help="seconds to hold the peak (plunger 0.08, flick 0)")
    ap.add_argument("--preload", type=float, default=0.15, help="plunger: wet while pulled, at full pull")
    ap.add_argument("--launch", type=float, default=1.0, help="plunger: wet at release from full pull")
    ap.add_argument("--attack", type=float, default=0.03, help="plunger: seconds to rise to the launch level")
    ap.add_argument("--snap", type=float, default=0.10, help="plunger: max seconds from pull to centre that still launches")
    ap.add_argument("--decay-scale", type=float, default=0.6, help="plunger: how much a harder pull lengthens the tail (0-1)")
    ap.add_argument("--dir", choices=("any", "up", "down"), default="any", help="plunger: pull direction")
    ap.add_argument("--deadzone", type=float, default=0.20)
    ap.add_argument("--curve", type=float, default=1.0, help=">1 softer small flicks, <1 hotter")
    ap.add_argument("--pad", type=int, default=None, help="XInput index 0-3")
    args = ap.parse_args()

    if args.list:
        import mido
        print("\n".join(mido.get_output_names()) or "(none)")
        return

    out = None
    osc = None
    if not args.monitor and not args.midi:
        osc = OscOut(args.udp)
        print(f"UDP -> FlickFX device on 127.0.0.1:{args.udp}")
    elif not args.monitor:
        import mido
        out, name = open_port(args.port)
        print(f"MIDI -> {name}  ch{args.channel} CC{args.cc}")
        if args.learn:
            print("learn: Ableton で MIDI Map を ON → Dry/Wet をクリックしてから待つ（3秒間送信）")
            t_end = time.time() + 3
            while time.time() < t_end:
                for v in (0, 127):
                    out.send(mido.Message("control_change", channel=args.channel - 1, control=args.cc, value=v))
                    time.sleep(0.15)
            out.send(mido.Message("control_change", channel=args.channel - 1, control=args.cc, value=0))
            print("done")
            return

    pad = Pad(args.pad)
    if args.mode == "plunger":
        env = PlungerEnvelope(args.deadzone, args.curve,
                              1.2 if args.decay is None else args.decay,
                              args.preload, args.launch, args.attack,
                              0.08 if args.hold is None else args.hold,
                              args.snap, args.decay_scale, args.dir)
        print(f"pad #{pad.index}  plunger: 左スティックを引いて離す  (Ctrl+C で終了)")
    else:
        env = FlickEnvelope(args.deadzone, args.curve,
                            0.8 if args.decay is None else args.decay,
                            0.0 if args.hold is None else args.hold)
        print(f"pad #{pad.index}  flick: 左スティックを上にはじく  (Ctrl+C で終了)")

    last_cc, last_sent, last_print = -1, -1.0, 0.0
    prev = time.perf_counter()
    try:
        while True:
            now = time.perf_counter()
            dt, prev = now - prev, now
            stick = pad.left_stick()
            if stick is None:
                time.sleep(0.2)
                continue
            wet = env.step(*stick, dt)
            cc = round(wet * 127)
            if osc is not None and abs(wet - last_sent) > 0.001:
                last_sent = wet
                osc.send("/wet", wet)
            if cc != last_cc:
                last_cc = cc
                if out is not None:
                    import mido
                    out.send(mido.Message("control_change", channel=args.channel - 1, control=args.cc, value=cc))
            if now - last_print > 0.03:
                last_print = now
                print(f"\r y={stick[1]:+.2f}  wet {bar(wet)} {cc:3d}", end="", flush=True)
            time.sleep(0.002)   # ~500 Hz poll
    except KeyboardInterrupt:
        if osc is not None:
            osc.send("/wet", 0.0)
        if out is not None:
            import mido
            out.send(mido.Message("control_change", channel=args.channel - 1, control=args.cc, value=0))
        print()


if __name__ == "__main__":
    main()
