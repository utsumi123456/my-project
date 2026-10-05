"""Offline check of PlungerEnvelope over scripted stick gestures (no pad, no Live)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flick_fx import PlungerEnvelope  # noqa: E402

DT = 0.002


def ramp(a, b, secs):
    n = max(1, round(secs / DT))
    return [a + (b - a) * (i + 1) / n for i in range(n)]


def gesture(pull, pull_s=0.3, hold_s=0.5, return_s=0.015, tail_s=2.0):
    """Stick deflection over time: pull, hold, return to centre, rest."""
    return ramp(0, pull, pull_s) + [pull] * round(hold_s / DT) + ramp(pull, 0, return_s) + [0.0] * round(tail_s / DT)


def run(name, ys):
    env = PlungerEnvelope()
    wets = [env.step(0.0, -y, DT) for y in ys]   # pulled down, like a plunger
    hold_end = next(i for i in range(len(ys) - 1, -1, -1) if ys[i] > 0)
    charged = max(wets[:hold_end])
    after = wets[hold_end:]
    peak = max(after)
    t_peak = after.index(peak) * DT
    t_dry = next((i * DT for i, w in enumerate(after) if i > after.index(peak) and w == 0), None)
    print(f"{name:<22} pulled {charged:.3f}  launch {peak:.3f} @ {t_peak * 1000:4.0f} ms  dry after {t_dry if t_dry is None else round(t_dry, 2)} s")
    return charged, peak, t_dry


half = run("half pull, release", gesture(0.6))
full = run("full pull, release", gesture(1.0))
slow = run("full pull, slow return", gesture(1.0, return_s=0.4))
flick = run("quick flick 40 ms", gesture(1.0, pull_s=0.02, hold_s=0.02))

ok = (half[0] < 0.1 and full[0] <= 0.15            # only a hint while pulled
      and full[1] > half[1] > 2 * half[0]          # release > pulled, harder pull > softer
      and full[2] > half[2]                        # harder pull rings longer
      and slow[1] <= full[0] + 1e-6                # slow return does not launch
      and flick[1] > 0.9)                          # a flick is a full-strength launch
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
