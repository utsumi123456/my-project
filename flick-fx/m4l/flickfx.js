// FlickFX engine v3: two sticks, two FX slots.
//
// Two ways an FX answers the stick:
//   plunger (Reverb, Echo)  pull = a hint, snap back = launch, then the tail decays.
//                           The pull direction bends two colour params from their base.
//   hold    (Grain Delay, Auto Filter, Phaser-Flanger, Redux)
//                           tilt = the sweet spot: the FX is fully in and its two
//                           params follow the stick. Snap back = a per-FX flick gesture
//                           (filter zap, pitch dive, jet sweep, bit drop) while the wet
//                           rings out.
// Tail buttons (D-pad L, Y/A R) step each FX's own tail parameter in 12 steps and
// the wet decay with it. Ceilings keep feedback/decay out of runaway territory.
//
// in : [gamepad] events, padinfo, tick, init, knob values, fxl/fxr menu indices
// out: 0-5  L: wet value, wet id, A value, A id, B value, B id   (to live.remote~)
//      6-11 R: same
//      12   view messages (to the jsui)
//      13   control: "decayl <ms>" / "decayr <ms>" to move the Decay dials
autowatch = 1;
inlets = 1;
outlets = 14;

var FX = ["None", "Reverb", "Echo", "Grain Delay", "Auto Filter", "Phaser-Flanger", "Redux"];
var STYLE = { "Reverb": "reverb", "Echo": "echo", "Grain Delay": "grain", "Auto Filter": "filter",
              "Phaser-Flanger": "phaser", "Redux": "redux" };
var STEPS = [100, 200, 300, 450, 650, 900, 1200, 1600, 2200, 3000, 4000, 6000];   // wet decay per tail step (ms)

function lerp(a, b, k) { return a + (b - a) * k; }
function clamp01(v) { return Math.max(0, Math.min(1, v)); }
function smooth(k) { k = clamp01(k); return k * k * (3 - 2 * k); }

// Parameter values are absolute (Live units); A/B carry {min,max,base}.
// hold(s, A, B) -> [a, b] while tilted; flick(u, st, A, B) -> [a, b] for u = 0..1 of the gesture.
var MAP = {
    "Reverb": {
        mode: "plunger", wet: [/^dry\/wet$/i], a: [/^hishelf gain$/i], b: [/^decay time$/i],
        tail: "DECAY", tailParam: "b", span: [0.10, 0.80], ceilB: 0.85
    },
    "Echo": {
        mode: "plunger", wet: [/^dry wet$/i, /dry.?wet/i], a: [/^reverb level$/i, /stereo width/i], b: [/^feedback$/i],
        tail: "FEEDBACK", tailParam: "b", span: [0.0, 0.80], ceilB: 0.82
    },
    // Hold FX think in polar terms: s.theta (angle, up = +pi/2), s.amt (tilt), s.spin (|rad/s|
    // while circling at full tilt). Full tilt is the sweet spot and must stay musical.
    "Grain Delay": {
        mode: "hold", wet: [/dry.?wet/i], a: [/^pitch$/i], b: [/^spray$/i], glide: 0.15,
        tail: "FEEDBACK", tailName: /^feedback$/i, span: [0.0, 0.85],
        // tilt: pitch leans +-7 st with the angle on a gentle curve; circling scatters the grains
        hold: function (s, A, B) {
            var k = smooth(s.amt);
            return [A.base + 7 * Math.sin(s.theta) * k * k, lerp(B.base, 0.2 + 0.55 * Math.min(1, s.spin / 12), k)];
        },
        // flick: "pew" - pitch leaps up with the strength and dives back, a spray burst
        flick: function (u, st, A, B) { return [A.base + 7 * st * Math.exp(-5 * u) - 3 * st * smooth(u) * (1 - u), lerp(lerp(B.base, 0.8, st), B.base, smooth(u))]; }
    },
    "Auto Filter": {
        mode: "hold", wet: [/^dry\/wet$/i, /dry.?wet/i], a: [/^frequency$/i], b: [/^resonance$/i], glide: 0.05,
        tail: "", span: [0, 1],
        // tilt: the angle picks the cutoff (down = darker, up = brighter, never closed);
        // circling winds the resonance up into a wah wheel
        hold: function (s, A, B) {
            var k = smooth(s.amt / 0.7);
            return [lerp(A.base, 0.52 + 0.42 * (1 + Math.sin(s.theta)) / 2, k),
                    lerp(B.base, 0.12 + 0.15 * s.amt + 0.4 * Math.min(1, s.spin / 10), k)];
        },
        // flick: a resonant zap from the top down to a still-audible floor, then home
        flick: function (u, st, A, B) {
            var zap = 0.4 + 0.55 * Math.exp(-6 * u);
            return [lerp(zap, A.base, smooth((u - 0.6) / 0.4)), lerp(0.25 + 0.4 * st, B.base, smooth((u - 0.5) / 0.5))];
        }
    },
    "Phaser-Flanger": {
        mode: "hold", wet: [/^dry\/wet$/i, /dry.?wet/i], a: [/^center freq$/i], b: [/^amount$/i], glide: 0.06,
        tail: "FEEDBACK", tailName: /^feedback$/i, span: [0.0, 0.90],
        // tilt: the angle places the notches, full tilt = full depth; circling sweeps them like a jet
        hold: function (s, A, B) {
            var k = smooth(s.amt / 0.6);
            return [lerp(A.base, 0.1 + 0.8 * (1 + Math.sin(s.theta)) / 2, k), lerp(B.base, 1.0, k)];
        },
        // flick: a jet whoosh - the notches race bottom to top at full depth
        flick: function (u, st, A, B) { return [lerp(lerp(0.05, 0.95, smooth(u * 1.4)), A.base, smooth((u - 0.7) / 0.3)), lerp(1.0, B.base, smooth((u - 0.6) / 0.4))]; }
    },
    "Redux": {
        mode: "hold", wet: [/^dry\/wet$/i, /dry.?wet/i], a: [/^sample rate$/i], b: [/^bit depth$/i], glide: 0.03,
        // tail buttons set how hard it crushes (s.crush 0..1), not a time
        tail: "CRUSH", crush: true, span: [0, 1],
        // tilt: more tilt = coarser sample rate, up drops bits; CRUSH scales both; circling wobbles the rate
        hold: function (s, A, B) {
            var depth = lerp(0.3, 0.97, s.crush), bits = lerp(3, 14, s.crush);
            var wob = 0.12 * Math.min(1, s.spin / 8) * Math.sin(s.theta * 2);
            return [lerp(A.base, Math.max(0.02, 1 - s.amt * depth * (0.8 + 0.2 * s.sx) + wob), smooth(s.amt / 0.4)),
                    lerp(B.base, 16 - bits * Math.max(0, s.sy) * s.amt, smooth(s.amt / 0.4))];
        },
        // flick: a bit drop to a floor set by CRUSH, then recovers in hard steps
        flick: function (u, st, A, B, s) {
            var floorSr = lerp(0.5, 0.02, s.crush * st), floorBits = lerp(10, 1, s.crush * st);
            return [lerp(floorSr, A.base, Math.floor(u * 6) / 6), lerp(floorBits, B.base, Math.floor(u * 5) / 5)];
        }
    }
};
var GENERIC = { mode: "plunger", wet: [/dry.?wet/i, /^mix$/i], a: [/freq/i], b: [/feedback/i, /decay/i], tail: "", span: [0, 1] };

// ---- shared knobs -------------------------------------------------------------
var P = { preload: 0.15, launch: 1.0, attack: 0.03, hold: 0.08, weight: 0.6, snap: 0.10, spread: 0.3 };
var DEADZONE = 0.2;

function preload(v) { P.preload = v / 100; }
function launch(v) { P.launch = v / 100; }
function attack(v) { P.attack = v / 1000; }
function hold(v) { P.hold = v / 1000; }
function weight(v) { P.weight = v / 100; }
function snap(v) { P.snap = v / 1000; }
function spread(v) { P.spread = v / 100; S[0].applyRest(); S[1].applyRest(); }
function decayl(v) { S[0].decay = v / 1000; }
function decayr(v) { S[1].decay = v / 1000; }
function crushl(v) { S[0].crush = v / 100; if (S[0].map.crush) S[0].tailStep = Math.round(S[0].crush * (STEPS.length - 1)); }
function crushr(v) { S[1].crush = v / 100; if (S[1].map.crush) S[1].tailStep = Math.round(S[1].crush * (STEPS.length - 1)); }
function fxl(i) { S[0].want = FX[Math.max(0, Math.min(FX.length - 1, i | 0))]; syncTask.schedule(50); }
function fxr(i) { S[1].want = FX[Math.max(0, Math.min(FX.length - 1, i | 0))]; syncTask.schedule(50); }

// ---- one side = one stick + one FX ---------------------------------------------
function slot() { return { id: 0, min: 0, max: 1, base: 0, name: "" }; }

function Side(idx) {
    this.idx = idx;
    this.tag = idx === 0 ? "L" : "R";
    this.out = idx * 6;
    this.sx = 0; this.sy = 0; this.amt = 0;
    this.decay = 1.2;
    this.want = "None"; this.fx = "";
    this.map = GENERIC;
    this.W = slot(); this.A = slot(); this.B = slot();
    this.tailApi = null; this.tailMin = 0; this.tailMax = 1; this.tailStep = 6;
    this.wet = 0; this.phase = "idle"; this.t = 0; this.peak = 0; this.nearPeakT = 0;
    this.target = 0; this.curDecay = 1.2; this.gestureT = 0; this.gestureLen = 0.5;
    this.pullDx = 0; this.pullDy = 0; this.launchDx = 0; this.launchDy = 0;
    this.lastWetOut = -1; this.lastA = null; this.lastB = null;
    this.theta = 0; this.prevTheta = null; this.omega = 0; this.spin = 0; this.windup = 0;
    this.ha = null; this.hb = null;
    this.crush = 0.7;
}

Side.prototype.amount = function () {
    var v = Math.min(1, Math.sqrt(this.sx * this.sx + this.sy * this.sy));
    return v <= DEADZONE ? 0 : (v - DEADZONE) / (1 - DEADZONE);
};

Side.prototype.fall = function (dt) {
    this.wet *= Math.exp(-dt * Math.log(127) / Math.max(this.curDecay, 0.001));
    if (this.wet < 1 / 127) this.wet = 0;
};

// shared pull bookkeeping: peak, its direction, and how recently we were near it
Side.prototype.track = function (a, dt) {
    lastSide = this.idx;
    if (this.phase !== "charge") { this.phase = "charge"; this.peak = 0; this.t = 0; this.windup = 0; }
    if (a >= this.peak) {
        this.peak = a;
        var m = Math.sqrt(this.sx * this.sx + this.sy * this.sy) || 1;
        this.pullDx = this.sx / m; this.pullDy = this.sy / m;
    }
    this.nearPeakT = (a >= 0.5 * this.peak) ? 0 : this.nearPeakT + dt;
};

Side.prototype.step = function (dt) {
    var a = this.amount();
    this.amt = a;
    this.t += dt;
    this.trackSpin(a, dt);
    if (this.map.mode === "hold") this.stepHold(a, dt); else this.stepPlunger(a, dt);
    if (Math.abs(this.wet - this.lastWetOut) > 0.0005) { this.lastWetOut = this.wet; this.sendWet(); }
    return a;
};

// circling at (near) full tilt: angular speed, and total angle wound while charging
Side.prototype.trackSpin = function (a, dt) {
    if (a > 0) this.theta = Math.atan2(this.sy, this.sx);
    if (a > 0.6 && dt > 0) {
        if (this.prevTheta !== null) {
            var d = this.theta - this.prevTheta;
            if (d > Math.PI) d -= 2 * Math.PI; else if (d < -Math.PI) d += 2 * Math.PI;
            this.omega += (d / dt - this.omega) * Math.min(1, dt / 0.08);
            if (this.phase === "charge") this.windup += Math.abs(d);
        }
        this.prevTheta = this.theta;
    } else {
        this.prevTheta = null;
        this.omega *= Math.exp(-dt / 0.15);
    }
    this.spin = Math.abs(this.omega);
};

Side.prototype.stepPlunger = function (a, dt) {
    if (a > 0) {
        this.track(a, dt);
        this.fall(dt);
        this.wet = Math.max(this.wet, P.preload * a * (1 + Math.min(0.6, this.windup / (4 * Math.PI) * 0.3)));
        return;
    }
    if (this.phase === "charge") {
        if (this.nearPeakT + dt <= P.snap) {
            // re-launching into a ringing tail only tops it up, it never stacks past the target
            this.target = Math.min(1, P.launch * this.peak);
            // winding the plunger (circling before letting go) stores extra tail, up to +80 %
            var wound = Math.min(0.8, this.windup / (4 * Math.PI) * 0.4);
            this.curDecay = this.decay * ((1 - P.weight) + P.weight * this.peak) * (1 + wound);
            this.launchDx = this.pullDx; this.launchDy = this.pullDy;
            this.applyRest();
            this.phase = "attack"; this.t = 0;
            outlet(12, "launch", this.idx, -this.pullDx, -this.pullDy, this.target, this.curDecay);
        } else {
            this.curDecay = this.decay * 0.5;
            this.phase = "decay"; this.t = 0;
        }
    }
    if (this.phase === "attack") {
        if (this.t >= P.attack) { this.wet = Math.max(this.wet, this.target); this.phase = "hold"; this.t = 0; }
        else this.wet = Math.max(this.wet, this.target * (1 - Math.pow(1 - this.t / Math.max(P.attack, 0.001), 2)));
    } else if (this.phase === "hold") {
        if (this.t >= P.hold) { this.phase = "decay"; this.t = 0; }
    } else if (this.phase === "decay") {
        this.fall(dt);
        if (this.wet === 0) { this.phase = "idle"; this.launchDx = 0; this.launchDy = 0; this.applyRest(); }
    }
};

Side.prototype.stepHold = function (a, dt) {
    var m = this.map;
    if (a > 0) {
        this.track(a, dt);
        // sweet spot: fully in by ~60 % tilt, eased so it blooms rather than switches
        var w = P.launch * Math.pow(Math.min(1, a / 0.6), 0.7);
        this.wet += (w - this.wet) * Math.min(1, dt / 0.03);
        var v = m.hold(this, this.A, this.B);
        var k = Math.min(1, dt / (m.glide || 0.05));
        this.ha = this.ha === null ? v[0] : this.ha + (v[0] - this.ha) * k;
        this.hb = this.hb === null ? v[1] : this.hb + (v[1] - this.hb) * k;
        this.sendAB(this.ha, this.hb);
        return;
    }
    if (this.phase === "charge") {
        if (this.nearPeakT + dt <= P.snap) {
            // flick gesture: length grows with the pull and the tail
            this.target = Math.min(1, P.launch * Math.max(this.peak, 0.5));
            this.wet = Math.max(this.wet, this.target);
            this.curDecay = this.decay * ((1 - P.weight) + P.weight * this.peak);
            this.gestureT = 0;
            this.gestureLen = Math.max(0.25, Math.min(1.6, 0.35 + 0.5 * this.curDecay));
            this.launchDx = this.pullDx; this.launchDy = this.pullDy;
            this.phase = "flick"; this.t = 0;
            outlet(12, "launch", this.idx, -this.pullDx, -this.pullDy, this.target, this.curDecay);
        } else {
            this.curDecay = Math.min(this.decay, 0.6);
            this.phase = "decay"; this.t = 0;
            this.applyRest();
        }
    }
    if (this.phase === "flick") {
        this.gestureT += dt;
        var u = this.gestureT / this.gestureLen;
        var g = m.flick(Math.min(1, u), this.peak, this.A, this.B, this);
        this.sendAB(g[0], g[1]);
        if (u > 0.3) this.fall(dt);
        if (u >= 1) { this.phase = "decay"; this.t = 0; this.applyRest(); }
    } else if (this.phase === "decay") {
        this.fall(dt);
        if (this.wet === 0) { this.phase = "idle"; this.applyRest(); }
    }
};

Side.prototype.sendWet = function () {
    var w = this.W;
    if (w.id) outlet(this.out, w.min + this.wet * (w.max - w.min));
};

Side.prototype.sendAB = function (va, vb) {
    var A = this.A, B = this.B, m = this.map;
    if (A.id) {
        va = Math.max(A.min, Math.min(A.max, va));
        if (this.lastA === null || Math.abs(va - this.lastA) > 1e-4) { this.lastA = va; outlet(this.out + 2, va); }
    }
    if (B.id) {
        var top = m.ceilB ? B.min + (B.max - B.min) * m.ceilB : B.max;
        vb = Math.max(B.min, Math.min(top, vb));
        if (this.lastB === null || Math.abs(vb - this.lastB) > 1e-4) { this.lastB = vb; outlet(this.out + 4, vb); }
    }
};

// resting values: plunger FX bend around the base by the last launch direction; hold FX go home
Side.prototype.applyRest = function () {
    var A = this.A, B = this.B;
    this.ha = this.hb = null;
    if (this.map.mode === "plunger") {
        this.sendAB(A.base + this.launchDx * P.spread * (A.max - A.min), B.base + this.launchDy * P.spread * (B.max - B.min));
    } else {
        this.sendAB(A.base, B.base);
    }
};

Side.prototype.release = function () {
    if (this.A.id) outlet(this.out + 2, this.A.base);
    if (this.B.id) outlet(this.out + 4, this.B.base);
    outlet(this.out + 1, "id", 0); outlet(this.out + 3, "id", 0); outlet(this.out + 5, "id", 0);
    this.W = slot(); this.A = slot(); this.B = slot();
    this.tailApi = null; this.lastA = this.lastB = null;
};

Side.prototype.bind = function (devPath, fxName) {
    var dev = new LiveAPI(devPath);
    var n = dev.getcount("parameters");
    var params = [];
    for (var i = 0; i < n; i++) {
        var p = new LiveAPI(devPath + " parameters " + i);
        params.push({ api: p, name: String(p.get("name")), quant: parseInt(p.get("is_quantized"), 10) });
    }
    var map = MAP[fxName] || GENERIC;
    this.release();
    this.map = map;
    var w = findParam(params, map.wet);
    if (!w) return false;
    grab(this.W, w);
    var used = [w];
    var pa = findParam(params, map.a, used);
    if (pa) { grab(this.A, pa); used.push(pa); }
    var pb = findParam(params, map.b, used);
    if (pb) { grab(this.B, pb); used.push(pb); }
    // tail parameter: the held B for plunger FX, otherwise a separate (unheld) param
    var tp = map.tailParam === "b" ? pb : (map.tailName ? findParam(params, [map.tailName]) : null);
    if (map.crush) {
        this.tailStep = Math.round(this.crush * (STEPS.length - 1));
    } else if (map.tail && tp) {
        this.tailApi = tp.api;
        this.tailMin = parseFloat(tp.api.get("min")); this.tailMax = parseFloat(tp.api.get("max"));
        var cur = parseFloat(tp.api.get("value"));
        var frac = (cur - this.tailMin) / ((this.tailMax - this.tailMin) || 1);
        this.tailStep = Math.round(clamp01((frac - map.span[0]) / ((map.span[1] - map.span[0]) || 1)) * (STEPS.length - 1));
    } else {
        this.tailStep = nearestStep(this.decay * 1000);
    }
    outlet(this.out + 1, "id", this.W.id);
    outlet(this.out + 3, "id", this.A.id);
    outlet(this.out + 5, "id", this.B.id);
    this.applyRest();
    this.sendWet();
    return true;
};

var S = [new Side(0), new Side(1)];
var lastSide = 0;

// ---- gamepad -----------------------------------------------------------------
var padName = "";

function norm(v) {
    if (Math.abs(v) > 1.5) v = v / 32767;
    return Math.max(-1, Math.min(1, v));
}
// [gamepad] reports y up-positive on this setup (verified against the view)
function axis_left_x(v) { S[0].sx = norm(v); }
function axis_left_y(v) { S[0].sy = norm(v); }
function axis_right_x(v) { S[1].sx = norm(v); }
function axis_right_y(v) { S[1].sy = norm(v); }

// tail buttons: D-pad up/down -> L, Y (up) / A (down) -> R
function button_dpad_up(v) { if (v > 0) stepTail(0, +1); }
function button_dpad_down(v) { if (v > 0) stepTail(0, -1); }
function button_y(v) { if (v > 0) stepTail(1, +1); }
function button_a(v) { if (v > 0) stepTail(1, -1); }

function nearestStep(ms) {
    var best = 0;
    for (var i = 0; i < STEPS.length; i++) if (Math.abs(STEPS[i] - ms) < Math.abs(STEPS[best] - ms)) best = i;
    return best;
}

function stepTail(idx, dir) {
    var s = S[idx], n = STEPS.length - 1, m = s.map;
    s.tailStep = Math.max(0, Math.min(n, s.tailStep + dir));
    var frac = s.tailStep / n;
    if (m.crush) {
        s.crush = frac;
        outlet(13, idx === 0 ? "crushl" : "crushr", Math.round(frac * 100));
        outlet(12, "tail", idx, "CRUSH", Math.round(frac * 100) + " %", s.tailStep, STEPS.length, s.decay, frac);
        return;
    }
    s.decay = STEPS[s.tailStep] / 1000;
    outlet(13, idx === 0 ? "decayl" : "decayr", STEPS[s.tailStep]);
    var kind = "TAIL", text = s.decay < 1 ? Math.round(s.decay * 1000) + " ms" : s.decay.toFixed(1) + " s";
    if (m.tail && s.tailApi) {
        var v = s.tailMin + (s.tailMax - s.tailMin) * (m.span[0] + (m.span[1] - m.span[0]) * frac);
        if (m.tailParam === "b" && s.B.id) {
            // a parameter held by live.remote~ rejects writes: let go, store, take it back
            outlet(s.out + 5, "id", 0);
            s.tailApi.set("value", v);
            outlet(s.out + 5, "id", s.B.id);
            s.B.base = v; s.lastB = null; s.applyRest();
        } else {
            s.tailApi.set("value", v);                 // stored in the set
        }
        text = String(s.tailApi.call("str_for_value", v));
        kind = m.tail;
    }
    outlet(12, "tail", idx, kind, text, s.tailStep, STEPS.length, s.decay, frac);
}

// [gamepad] sends this before every single event (hundreds per second): only rebuild the
// name string when the pad instance changes, so the hot path allocates nothing
var padInstance = -1;
function padinfo(instance) {
    if (instance === padInstance) return;
    padInstance = instance;
    var a = arrayfromargs(arguments);
    var name = a.slice(2, a.length - 1).join(" ");
    if (name && name !== padName) { padName = name; status(); }
}

function anything() { }

// ---- clock -------------------------------------------------------------------
var lastTick = 0, viewT = 0;

function tick() {
    var now = new Date().getTime();
    var dt = lastTick ? Math.min(0.1, (now - lastTick) / 1000) : 0.005;
    lastTick = now;
    var a0 = S[0].step(dt), a1 = S[1].step(dt);
    viewT += dt;
    if (viewT >= 0.016) {
        viewT = 0;
        outlet(12, "state", S[0].sx, S[0].sy, a0, S[0].wet, S[0].omega, S[0].windup,
                            S[1].sx, S[1].sy, a1, S[1].wet, S[1].omega, S[1].windup);
    }
}

// ---- FX slot management --------------------------------------------------------
var syncTask = new Task(sync, this);
var chainPath = "", chainObs = null, busy = false;

function init() { syncTask.schedule(100); }
function bang() { sync(); }

function myPath() {
    var me = new LiveAPI("this_device");
    var m = String(me.unquotedpath).match(/^(.*) devices (\d+)$/);
    return m ? { chain: m[1], index: parseInt(m[2], 10) } : null;
}

// Managed devices live to the RIGHT of FlickFX, collapsed, so FlickFX itself never moves
// when the FX menus change: [FlickFX] [L fx] [R fx] [Limiter]. The Limiter catches
// stacked launches at the end of the chain.
var LIMITER = "FlickFX \u00b7 Limiter";

function managedName(side, fxName) { return "FlickFX " + side.tag + " \u00b7 " + fxName; }

function deviceName(me, d) { return String(new LiveAPI(me.chain + " devices " + d).get("name")); }

function deviceCount(me) { return new LiveAPI(me.chain).getcount("devices"); }

// devices right of FlickFX whose name starts with prefix: [{index, fx}]
function findPrefix(me, prefix) {
    var out = [], n = deviceCount(me);
    for (var d = me.index + 1; d < n; d++) {
        var name = deviceName(me, d);
        if (name.indexOf(prefix) === 0) out.push({ index: d, fx: name.substring(prefix.length) });
    }
    return out;
}

function findManaged(me, side) { return findPrefix(me, "FlickFX " + side.tag + " \u00b7 "); }

function collapse(me, index) {
    try { new LiveAPI(me.chain + " devices " + index + " view").set("is_collapsed", 1); } catch (e) { }
}

function insertAt(me, devName, at, label) {
    new LiveAPI(me.chain).call("insert_device", devName, at);
    new LiveAPI(me.chain + " devices " + at).set("name", label);
    collapse(me, at);
}

function sync() {
    if (busy) return;
    busy = true;
    try {
        var me = myPath();
        if (!me) { status(); return; }
        watchChain(me.chain);
        for (var k = 0; k < 2; k++) {
            var side = S[k];
            me = myPath();
            var found = findManaged(me, side);
            var keep = null;
            for (var j = found.length - 1; j >= 0; j--) {
                if (!keep && found[j].fx === side.want) { keep = found[j]; continue; }
                new LiveAPI(me.chain).call("delete_device", found[j].index);
                me = myPath();
            }
            if (!keep && side.want !== "None") {
                // L sits right after FlickFX, R right after L
                var at = me.index + 1;
                if (k === 1) {
                    var lDev = findManaged(me, S[0]);
                    if (lDev.length) at = lDev[0].index + 1;
                }
                insertAt(me, side.want, at, managedName(side, side.want));
                me = myPath();
            }
            keep = findManaged(me, side)[0] || null;
            if (keep) {
                side.bind(me.chain + " devices " + keep.index, keep.fx);
                side.fx = keep.fx;
            } else {
                side.release();
                side.fx = "";
                side.map = GENERIC;
            }
        }
        ensureLimiter();
    } catch (e) {
        error("FlickFX sync: " + e + "\n");
    } finally {
        busy = false;
        status();
    }
}

// one Limiter right after the managed FX, ceiling -1 dB
function ensureLimiter() {
    var me = myPath();
    var lims = findPrefix(me, LIMITER);
    for (var j = lims.length - 1; j >= 1; j--) { new LiveAPI(me.chain).call("delete_device", lims[j].index); me = myPath(); }
    var last = me.index;
    var l = findManaged(me, S[0]), r = findManaged(me, S[1]);
    if (l.length) last = Math.max(last, l[0].index);
    if (r.length) last = Math.max(last, r[0].index);
    lims = findPrefix(me, LIMITER);
    if (lims.length && lims[0].index === last + 1) return;
    if (lims.length) { new LiveAPI(me.chain).call("delete_device", lims[0].index); me = myPath(); }
    insertAt(me, "Limiter", last + 1, LIMITER);
    var path = me.chain + " devices " + (last + 1);
    var dev = new LiveAPI(path);
    var n = dev.getcount("parameters");
    for (var i = 0; i < n; i++) {
        var p = new LiveAPI(path + " parameters " + i);
        if (/^ceiling$/i.test(String(p.get("name")))) {
            var lo = parseFloat(p.get("min")), hi = parseFloat(p.get("max"));
            // ceiling is in dB on Live's Limiter; fall back to a near-top position otherwise
            p.set("value", (lo <= -1 && hi >= -1) ? -1 : lo + (hi - lo) * 0.96);
        }
    }
}

function watchChain(path) {
    if (path === chainPath) return;
    chainPath = path;
    chainObs = new LiveAPI(onChain, path);
    chainObs.property = "devices";
}

function onChain(args) {
    if (args[0] === "devices" && !busy) syncTask.schedule(150);
}

// ---- helpers -------------------------------------------------------------------
function findParam(params, patterns, exclude) {
    for (var k = 0; k < patterns.length; k++) {
        for (var i = 0; i < params.length; i++) {
            var p = params[i];
            if (p.quant || (exclude && exclude.indexOf(p) >= 0)) continue;
            if (patterns[k].test(p.name)) return p;
        }
    }
    return null;
}

function grab(slotObj, p) {
    slotObj.id = parseInt(p.api.id, 10);
    slotObj.min = parseFloat(p.api.get("min"));
    slotObj.max = parseFloat(p.api.get("max"));
    slotObj.base = parseFloat(p.api.get("value"));
    slotObj.name = p.name;
}

function status() {
    for (var k = 0; k < 2; k++) {
        var s = S[k];
        outlet(12, "slot", k, STYLE[s.fx] || "none", s.fx || "-", s.A.name || "-", s.B.name || "-", s.map.mode);
    }
    outlet(12, "pad", padName || "move a stick");
}

function notifydeleted() { S[0].release(); S[1].release(); }
