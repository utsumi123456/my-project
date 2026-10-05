// FlickFX view v2: two stages (L / R stick), one animation language per FX.
//
//   reverb  soft glowing particles that drift, swell and diffuse into a bloom
//   echo    a ball that bounces off the walls; every bounce rings a fading ripple
//   grain   a spray of short-lived sparkles scattered along the shot
//   filter  a live filter response curve; launch sweeps the cutoff, Y sets resonance
//   phaser  a rotating comb of dots orbiting the hub, faster with more wet
//   redux   quantised pixel blocks that snap to a coarse grid and flicker out
//
// D-pad tail change: the stage shows the decay curve, a ball running its length
// in real time, the value, and the step pips.
autowatch = 1;
mgraphics.init();
mgraphics.relative_coords = 0;
mgraphics.autofill = 0;

// The zoom window runs a second copy with jsarguments "big": it draws the same scene in
// the device's logical size (532 x 166) scaled up, so everything stays crisp and in proportion.
var BIG = jsarguments.length > 1 && jsarguments[1] === "big";
var LOGICAL_H = 166;
function scaleFactor() { return BIG ? (box.rect[3] - box.rect[1]) / LOGICAL_H : 1; }
function dims() {
    var sc = scaleFactor();
    return [(box.rect[2] - box.rect[0]) / sc, (box.rect[3] - box.rect[1]) / sc];
}

// Look: flat data-viz in the spirit of Dillon Bastan's Coalescence - a black field framed by
// thin grey lines, a circular scatter of tiny square dots, thin salmon rings, a mint "selected"
// node. No gradients or fake 3D on the ball and spring.
var BG = [0.105, 0.108, 0.115];          // device body
var FIELD = [0.028, 0.030, 0.034];       // stage canvas
var FRAME = [0.30, 0.31, 0.33];          // 1 px frames
var FG = [0.90, 0.91, 0.90];
var DIM = [0.50, 0.52, 0.54];
var MINT = [0.52, 0.93, 0.72];           // the ball / selected node
var SALMON = [0.93, 0.42, 0.44];         // rings
var DOT_TEAL = [0.24, 0.52, 0.58];
var DOT_OLIVE = [0.52, 0.49, 0.20];
var COLORS = {
    reverb: [0.36, 0.80, 0.93], echo: [0.98, 0.66, 0.16], grain: [0.84, 0.80, 0.32],
    filter: [0.50, 0.90, 0.70], phaser: [0.93, 0.45, 0.47], redux: [0.64, 0.56, 0.96], none: [0.5, 0.5, 0.5]
};

function Stage(idx) {
    this.idx = idx;
    this.style = "none"; this.fx = "-"; this.xname = "-"; this.yname = "-";
    this.sx = 0; this.sy = 0; this.amt = 0; this.wet = 0;
    this.parts = []; this.rings = []; this.balls = [];
    this.flash = 0; this.spin = 0;
    this.cut = 0.5; this.res = 0.2; this.dirX = 0; this.dirY = 0; this.lastS = 0;
    this.tail = null;      // {decay, step, steps, t}
    this.omega = 0; this.windup = 0; this.mode = "plunger";
    this.trail = [];       // rim positions left by circling (hold FX)
    this.sparks = [];      // thrown off the rim by spin
    this.decayS = 1.2;
}
var ST = [new Stage(0), new Stage(1)];

function dotField(s, cx, cy, R) {
    var key = Math.round(cx) + ":" + Math.round(cy) + ":" + Math.round(R);
    if (s.fieldKey === key) return s.field;
    var pts = [], step = 6.5, rr = R * 1.38, seed = 7 + s.idx * 13;
    function rnd() { seed = (seed * 16807) % 2147483647; return seed / 2147483647; }
    for (var row = -Math.ceil(rr / step); row <= Math.ceil(rr / step); row++) {
        var y = row * step * 0.866;
        for (var col = -Math.ceil(rr / step) - 1; col <= Math.ceil(rr / step) + 1; col++) {
            var x = col * step + (row % 2 ? step / 2 : 0);
            var d = Math.sqrt(x * x + y * y);
            if (d > rr || d < R * 0.18) continue;
            var r = rnd();
            if (r < 0.28) continue;                               // gaps, like a trained map
            pts.push({ x: cx + x, y: cy + y, d: d / rr, tint: r < 0.72 ? 0 : 1, tw: rnd() * 6.28 });
        }
    }
    s.field = pts; s.fieldKey = key;
    return pts;
}
var TAIL_LIFE = 1.0;          // seconds the tail overlay stays up
var padLabel = "";
var panelOpen = 0;
function panel(v) { panelOpen = v ? 1 : 0; }

// ---- messages from the engine ---------------------------------------------------
function state(x0, y0, a0, w0, o0, u0, x1, y1, a1, w1, o1, u1) {
    setStage(ST[0], x0, y0, a0, w0, o0, u0); setStage(ST[1], x1, y1, a1, w1, o1, u1);
}
function setStage(s, x, y, a, w, om, wu) { s.sx = x; s.sy = y; s.amt = a; s.wet = w; s.omega = om || 0; s.windup = wu || 0; }

function launch(idx, dx, dy, strength, decaySec) {
    var s = ST[idx];
    s.flash = 1; s.dirX = -dx; s.dirY = -dy; s.lastS = strength; s.decayS = decaySec;
    s.zap = 0; s.zapLen = Math.max(0.25, Math.min(1.6, 0.35 + 0.5 * decaySec));
    var g = geom(idx);
    var cx = g.x + g.w / 2, cy = g.y + g.h * 0.56;
    var ang = Math.atan2(dy, dx);
    var i, n;
    if (s.style === "reverb") {
        n = Math.round(30 + 90 * strength);
        for (i = 0; i < n; i++) {
            var a = ang + gauss() * 0.9, sp = (60 + 220 * strength) * (0.35 + Math.random());
            s.parts.push({ x: cx, y: cy, vx: Math.cos(a) * sp, vy: -Math.sin(a) * sp, age: 0,
                life: 0.5 + decaySec * (0.6 + Math.random() * 0.7), r: 1 + Math.random() * 2, grow: 3 + Math.random() * 5 });
        }
    } else if (s.style === "echo") {
        var sp2 = 120 + 260 * strength;
        s.balls.push({ x: cx, y: cy, vx: Math.cos(ang) * sp2, vy: -Math.sin(ang) * sp2, e: strength, life: decaySec + 0.3, age: 0, trail: [] });
        s.rings.push({ x: cx, y: cy, r: 4, e: strength });
    } else if (s.style === "grain") {
        n = Math.round(40 + 120 * strength);
        for (i = 0; i < n; i++) {
            var a3 = ang + gauss() * 0.35, sp3 = (80 + 300 * strength) * Math.random();
            s.parts.push({ x: cx, y: cy, vx: Math.cos(a3) * sp3, vy: -Math.sin(a3) * sp3, age: 0,
                life: 0.15 + Math.random() * (0.25 + decaySec * 0.4), r: 0.6 + Math.random() * 1.4, hue: Math.random() });
        }
    } else if (s.style === "phaser") {
        s.spin += 1.5 * strength;
        s.whoosh = 1;
    } else if (s.style === "redux") {
        // bit drop: a wall of coarse blocks that falls apart in steps
        n = Math.round(30 + 70 * strength);
        for (i = 0; i < n; i++) {
            s.parts.push({ x: g.x + 8 + Math.random() * (g.w - 16), y: g.y + 22 + Math.random() * (g.h - 40), age: 0,
                life: 0.15 + Math.random() * (0.3 + decaySec * 0.6), r: 6 + Math.random() * 10 * strength, step: 1 });
        }
    }
    s.rings.push({ x: cx, y: cy, r: 2, e: 0.6 * strength, hub: 1 });
}

// kind: DECAY (reverb time) / FEEDBACK (repeats) / RESONANCE (ringing peak) / TAIL (wet envelope)
function tail(idx, kind, text, step, steps, decaySec, frac) {
    ST[idx].tail = { kind: String(kind), text: String(text), decay: decaySec, step: step, steps: steps, frac: frac, t: 0 };
    ST[idx].decayS = decaySec;
}

function slot(idx, style, fx, xname, yname, mode) {
    var s = ST[idx];
    if (s.style !== style) { s.parts = []; s.rings = []; s.balls = []; }
    s.style = style; s.fx = fx; s.xname = xname; s.yname = yname; s.mode = mode || "plunger";
    invalidate();
}

function pad() { padLabel = arrayfromargs(arguments).join(" ").replace(/\s+unknown$/i, "").replace(/^Controller\s*/i, ""); invalidate(); }

function anything() { }

// ---- simulation -----------------------------------------------------------------
var lastT = new Date().getTime();
var frameTime = 0;
var zoomOn = 0, zoomWasVisible = false;

function zoomstate(v) { zoomOn = v ? 1 : 0; mgraphics.redraw(); }

function zoomVisible() {
    try { return this.patcher.wind.visible ? true : false; } catch (e) { return true; }
}

function frame() {
    var now = new Date().getTime();
    var dt = Math.min(0.05, (now - lastT) / 1000);
    lastT = now;
    frameTime = now / 1000;
    if (BIG) {
        var vis = zoomVisible();
        if (vis !== zoomWasVisible) { zoomWasVisible = vis; outlet(0, "zoomstate", vis ? 1 : 0); }
        if (!vis) return;                         // nobody is looking: skip the work entirely
    }
    for (var k = 0; k < 2; k++) simulate(ST[k], geom(k), dt);
    if (!BIG && zoomOn) return;                   // the zoom window is drawing the scene
    mgraphics.redraw();
}

function simulate(s, g, dt) {
    var i, p;
    s.flash = Math.max(0, s.flash - dt * 5);
    if (s.tail) { s.tail.t += dt; if (s.tail.t > TAIL_LIFE) s.tail = null; }

    var left = g.x + 3, right = g.x + g.w - 3, top = g.y + 20, bottom = g.y + g.h - 14;
    for (i = s.parts.length - 1; i >= 0; i--) {
        p = s.parts[i];
        p.age += dt;
        if (p.age >= p.life) { s.parts.splice(i, 1); continue; }
        if (s.style === "reverb") {
            p.vx += (gauss() * 70 - p.vx * 2.4) * dt;
            p.vy += (gauss() * 70 - p.vy * 2.4) * dt;
            p.r += p.grow * dt;
        } else if (s.style === "grain") {
            p.vx -= p.vx * 1.2 * dt; p.vy -= p.vy * 1.2 * dt;
        }
        if (p.vx !== undefined) {
            p.x += p.vx * dt; p.y += p.vy * dt;
            if (p.x < left || p.x > right) { p.vx *= -0.5; p.x = clamp(p.x, left, right); }
            if (p.y < top || p.y > bottom) { p.vy *= -0.5; p.y = clamp(p.y, top, bottom); }
        }
    }
    for (i = s.balls.length - 1; i >= 0; i--) {
        var b = s.balls[i];
        b.age += dt;
        b.x += b.vx * dt; b.y += b.vy * dt;
        var hit = false;
        if (b.x < left || b.x > right) { b.vx = -b.vx; b.x = clamp(b.x, left, right); hit = true; }
        if (b.y < top || b.y > bottom) { b.vy = -b.vy; b.y = clamp(b.y, top, bottom); hit = true; }
        if (hit) { b.e *= 0.72; s.rings.push({ x: b.x, y: b.y, r: 2, e: b.e }); }
        b.trail.push([b.x, b.y]);
        if (b.trail.length > 14) b.trail.shift();
        if (b.age > b.life || b.e < 0.04) s.balls.splice(i, 1);
    }
    for (i = s.rings.length - 1; i >= 0; i--) {
        var r = s.rings[i];
        r.r += (r.hub ? 120 : 70) * dt;
        r.e -= dt * (r.hub ? 1.6 : 0.9);
        if (r.e <= 0) s.rings.splice(i, 1);
    }
    if (s.style === "grain" && s.wet > 0.05 && Math.random() < s.wet * 0.9) {
        // the cloud keeps sputtering while the tail rings
        var cx = g.x + g.w / 2 + s.dirX * g.w * 0.25 * Math.random(), cy = g.y + g.h * 0.56 - s.dirY * g.h * 0.25 * Math.random();
        s.parts.push({ x: cx + gauss() * 10, y: cy + gauss() * 10, vx: gauss() * 30, vy: gauss() * 30, age: 0, life: 0.12 + Math.random() * 0.3, r: 0.5 + Math.random(), hue: Math.random() });
    }
    var spin = Math.abs(s.omega);
    var R0 = Math.min(g.w, g.h) * 0.27, ccx = g.x + g.w / 2, ccy = g.y + g.h * 0.56;
    if (s.mode === "hold" && s.amt > 0.6) {
        var ang = Math.atan2(s.sy, s.sx);
        s.trail.push({ a: ang, e: Math.min(1, 0.3 + spin / 10) });
        if (spin > 3 && Math.random() < Math.min(1, spin / 14)) {
            // a spark leaves the rim tangentially, faster with the spin
            var dir = s.omega > 0 ? 1 : -1, px = ccx + Math.cos(ang) * R0, py = ccy - Math.sin(ang) * R0;
            var tx = -Math.sin(ang) * dir, ty = -Math.cos(ang) * dir, sp = 30 + spin * 9;
            s.sparks.push({ x: px, y: py, vx: (tx + Math.cos(ang) * 0.6) * sp, vy: (ty - Math.sin(ang) * 0.6) * sp, age: 0, life: 0.25 + Math.random() * 0.35 });
        }
    }
    for (var ti = s.trail.length - 1; ti >= 0; ti--) {
        s.trail[ti].e -= dt * 2.2;
        if (s.trail[ti].e <= 0) s.trail.splice(ti, 1);
    }
    if (s.trail.length > 90) s.trail.splice(0, s.trail.length - 90);
    for (var si = s.sparks.length - 1; si >= 0; si--) {
        var sk = s.sparks[si];
        sk.age += dt; sk.x += sk.vx * dt; sk.y += sk.vy * dt; sk.vx *= 0.96; sk.vy *= 0.96;
        if (sk.age > sk.life) s.sparks.splice(si, 1);
    }
    if (s.zap !== undefined && s.zap < 1) s.zap += dt / s.zapLen;
    var zapping = s.zap !== undefined && s.zap < 1;
    s.whoosh = Math.max(0, (s.whoosh || 0) - dt * 1.5);
    s.spin += dt * (0.4 + 7 * s.wet + 14 * s.whoosh + 3 * s.amt * (s.sy + 1));
    var cutTarget, resTarget;
    if (s.amt > 0) {                         // tilted: the curve follows the stick
        cutTarget = 0.15 + 0.75 * (s.sx + 1) / 2; resTarget = 0.15 + 0.6 * Math.max(0, s.sy);
    } else if (zapping) {                    // flick: top-to-bottom resonant zap
        cutTarget = 0.1 + 0.85 * Math.exp(-6 * s.zap); resTarget = 0.3 + 0.5 * s.lastS;
    } else {
        cutTarget = 0.9; resTarget = 0.12;
    }
    s.cut += (cutTarget - s.cut) * Math.min(1, dt * 20);
    s.res += (resTarget - s.res) * Math.min(1, dt * 12);
    if (s.style === "redux" && s.wet > 0.05 && s.amt > 0 && Math.random() < 0.35 + 0.6 * s.amt) {
        // crushing while tilted: blocks sized by the tilt, spawned around the ball
        var bx = g.x + g.w / 2 + s.sx * Math.min(g.w, g.h) * 0.27, by = g.y + g.h * 0.56 - s.sy * Math.min(g.w, g.h) * 0.27;
        s.parts.push({ x: bx + gauss() * 30, y: by + gauss() * 20, age: 0, life: 0.1 + Math.random() * 0.25, r: 3 + 12 * s.amt });
    }
    if (s.style === "grain" && s.amt > 0 && Math.random() < 0.5 + 0.5 * s.amt) {
        var gx = g.x + g.w / 2 + s.sx * Math.min(g.w, g.h) * 0.27, gy = g.y + g.h * 0.56 - s.sy * Math.min(g.w, g.h) * 0.27;
        s.parts.push({ x: gx + gauss() * 14 * s.amt, y: gy + gauss() * 14 * s.amt, vx: gauss() * 40, vy: gauss() * 40, age: 0, life: 0.1 + Math.random() * 0.3, r: 0.5 + Math.random(), hue: (s.sx + 1) / 2 });
    }
    if (s.parts.length > 260) s.parts.splice(0, s.parts.length - 260);
    if (s.rings.length > 24) s.rings.splice(0, s.rings.length - 24);
    if (s.sparks.length > 60) s.sparks.splice(0, s.sparks.length - 60);
}

// The zoom window is ~1 MP that Max re-composites on every redraw; at 60 fps it cannot keep up
// and frames arrive unevenly (the visible stutter). A steady 30 fps reads smoother than an
// erratic 25-40, and motion is dt-based so speeds are unchanged.
var FRAME_MS = BIG ? 33 : 16;
var timer = new Task(frame, this);
timer.interval = FRAME_MS;
timer.repeat();

// ---- drawing --------------------------------------------------------------------
function geom(k) {
    var d = dims(), W = d[0], H = d[1];
    var gap = 4, w = (W - gap * 3) / 2;
    return { x: gap + k * (w + gap), y: gap, w: w, h: H - gap * 2 };
}

// Everything that does not move (body, fields, frames, base dots, labels) is rendered once
// into an offscreen image at 2x device resolution and blitted each frame. Large zoom windows
// were stalling on re-filling ~1 MP of software-rendered layers 60 times a second.
var CACHE_RES = BIG ? 1 : 2;      // the zoom copy blits 1:1 (no per-frame downscale of a huge image)
var cacheImg = null, cacheKey = "", cacheW = 0, cacheH = 0;

function invalidate() { cacheKey = ""; }

function staticKey(W, H, sc) {
    var k = W + "x" + H + "@" + sc + "|" + padLabel;
    for (var i = 0; i < 2; i++) k += "|" + ST[i].style + "/" + ST[i].fx + "/" + ST[i].xname + "/" + ST[i].yname;
    return k;
}

function staticLayer(W, H, sc) {
    var key = staticKey(W, H, sc);
    if (cacheImg && key === cacheKey) return cacheImg;
    var f = sc * CACHE_RES;
    cacheW = Math.ceil(W * f); cacheH = Math.ceil(H * f);
    var mg = new MGraphics(cacheW, cacheH);
    mg.relative_coords = 0;
    mg.autofill = 0;
    mg.scale(f, f);
    mg.set_source_rgb(BG[0], BG[1], BG[2]); mg.rectangle(0, 0, W, H); mg.fill();
    for (var k = 0; k < 2; k++) drawStageStatic(mg, ST[k], geom(k));
    cacheImg = new Image(mg);
    cacheKey = key;
    return cacheImg;
}

function paint() {
    var g = mgraphics;
    var sc = scaleFactor();
    var d = dims(), W = d[0], H = d[1];
    if (!BIG && zoomOn) {                        // the zoom window is showing this scene
        g.image_surface_draw(staticLayer(W, H, sc), [0, 0, cacheW, cacheH], [0, 0, W, H]);
        g.select_font_face("Arial"); g.set_font_size(10);
        g.set_source_rgba(DIM[0], DIM[1], DIM[2], 1);
        var msg = "showing in zoom window";
        g.move_to(W / 2 - g.text_measure(msg)[0] / 2, H * 0.56); g.show_text(msg);
        return;
    }
    g.image_surface_draw(staticLayer(W, H, sc), [0, 0, cacheW, cacheH], [0, 0, W * sc, H * sc]);
    if (sc !== 1) g.scale(sc, sc);
    for (var k = 0; k < 2; k++) drawStage(g, ST[k], geom(k));
    if (panelOpen) {
        roundRect(g, 4, 26, W - 8, H - 30, 6);
        g.set_source_rgba(BG[0], BG[1], BG[2], 0.94); g.fill();
        g.select_font_face("Arial");
        g.set_font_size(8.5);
        g.set_source_rgb(DIM[0], DIM[1], DIM[2]);
        g.move_to(14, H - 9);
        g.show_text("tail  L: D-pad \u2191\u2193   R: Y \u2191 / A \u2193   (Decay L/R = how long the wet hangs)");
    }
}

function stageGeo(r) {
    return { cx: r.x + r.w / 2, cy: r.y + r.h * 0.56, R: Math.min(r.w, r.h) * 0.27 };
}

// static part of a stage: field, frame, header rule, unlit dots, labels
function drawStageStatic(g, s, r) {
    var col = COLORS[s.style] || COLORS.none, sg = stageGeo(r), i;
    g.set_source_rgb(FIELD[0], FIELD[1], FIELD[2]); g.rectangle(r.x, r.y, r.w, r.h); g.fill();
    g.set_line_width(1);
    g.set_source_rgb(FRAME[0], FRAME[1], FRAME[2]); g.rectangle(r.x + 0.5, r.y + 0.5, r.w - 1, r.h - 1); g.stroke();
    g.move_to(r.x, r.y + 22.5); g.line_to(r.x + r.w, r.y + 22.5); g.stroke();
    var pts = dotField(s, sg.cx, sg.cy, sg.R);
    for (i = 0; i < pts.length; i++) {
        var p = pts[i], base = p.tint ? DOT_OLIVE : DOT_TEAL;
        g.set_source_rgba(base[0], base[1], base[2], 0.55);
        g.rectangle(p.x - 0.8, p.y - 0.8, 1.6, 1.6); g.fill();
    }
    g.select_font_face("Arial");
    g.set_font_size(9);
    g.set_source_rgb(col[0], col[1], col[2]);
    g.move_to(r.x + 6, r.y + 13); g.show_text(s.idx === 0 ? "L" : "R");
    if (BIG) {
        g.set_source_rgb(FG[0], FG[1], FG[2]);
        g.move_to(r.x + 20, r.y + 13); g.show_text(s.fx === "-" ? "" : s.fx);
    }
    g.set_source_rgb(DIM[0], DIM[1], DIM[2]);
    if (s.style !== "none") {
        g.move_to(r.x + 6, r.y + r.h - 4);
        g.show_text("\u2194 " + s.xname + "   \u2195 " + s.yname);
    } else {
        var msg = "choose an FX";
        g.move_to(sg.cx - g.text_measure(msg)[0] / 2, sg.cy + sg.R + 18); g.show_text(msg);
    }
    if (s.idx === 0 && padLabel) {
        g.set_font_size(8);
        var pw = g.text_measure(padLabel)[0];
        g.move_to(r.x + r.w - pw - 6, r.y + 13); g.show_text(padLabel);
    }
}

function drawStage(g, s, r) {
    var col = COLORS[s.style] || COLORS.none, sg = stageGeo(r);
    var cx = sg.cx, cy = sg.cy, R = sg.R;
    drawField(g, s, cx, cy, R, col);

    // bloom, kept to the bowl area (a full-stage gradient was the most expensive fill)
    if (s.wet > 0.003 && !BIG) {
        var BR = R * 1.9;
        var bloom = g.pattern_create_radial(cx + s.dirX * R, cy - s.dirY * R, 0, cx, cy, BR);
        bloom.add_color_stop_rgba(0, col[0], col[1], col[2], 0.12 * s.wet);
        bloom.add_color_stop_rgba(1, col[0], col[1], col[2], 0);
        g.set_source(bloom); g.ellipse(cx - BR, cy - BR, BR * 2, BR * 2); g.fill();
    }

    if (s.style === "filter") drawFilter(g, s, r, col);
    if (s.style === "phaser") drawPhaser(g, s, cx, cy, R, col);

    var i, p, k, a;
    for (i = 0; i < s.rings.length; i++) {
        var rg = s.rings[i];
        g.set_line_width(rg.hub ? 1.5 : 1.2);
        var rc = rg.hub ? col : SALMON;
        g.set_source_rgba(rc[0], rc[1], rc[2], Math.max(0, rg.e) * 0.85);
        g.ellipse(rg.x - rg.r, rg.y - rg.r, rg.r * 2, rg.r * 2); g.stroke();
    }
    for (i = 0; i < s.parts.length; i++) {
        p = s.parts[i];
        k = 1 - p.age / p.life;
        if (s.style === "reverb") {
            a = k * k * (0.35 + 0.65 * Math.min(1, s.wet * 1.5 + 0.1));
            if (!BIG) dot(g, p.x, p.y, p.r * 2.6, col, a * 0.18);
            dotRGB(g, p.x, p.y, p.r, col[0] * 0.6 + 0.4, col[1] * 0.6 + 0.4, 1, a * 0.8);
        } else if (s.style === "grain") {
            var h = p.hue;
            if (!BIG) dotRGB(g, p.x, p.y, p.r * 2.2, col[0] + (0.4 - col[0]) * h, col[1] + (0.9 - col[1]) * h, col[2] + (1.0 - col[2]) * h, k * 0.25);
            dotRGB(g, p.x, p.y, p.r, col[0] + (0.4 - col[0]) * h, col[1] + (0.9 - col[1]) * h, col[2] + (1.0 - col[2]) * h, k);
        } else if (s.style === "redux") {
            var q = p.step ? 12 : 6;
            var qx = Math.round(p.x / q) * q, qy = Math.round(p.y / q) * q;
            var on = Math.random() > 0.15 ? 1 : 0.3;
            g.set_source_rgba(col[0], col[1], col[2], k * 0.85 * on);
            g.rectangle(qx - p.r / 2, qy - p.r / 2, p.r, p.r); g.fill();
        }
    }
    for (i = 0; i < s.balls.length; i++) {
        var b = s.balls[i];
        for (var t = 0; t < b.trail.length; t++) {
            var tk = t / b.trail.length;
            dot(g, b.trail[t][0], b.trail[t][1], 1 + 3 * tk, col, tk * 0.35 * Math.min(1, b.e * 2));
        }
        dot(g, b.x, b.y, 9, col, 0.25 * b.e);
        dot(g, b.x, b.y, 4, FG, 0.9);
    }

    drawPlunger(g, s, cx, cy, R, col);

    if (s.tail) drawTail(g, s, r, col);
}

// the scatter: dim teal/olive squares; they light in the FX colour near the ball and with the wet
function drawField(g, s, cx, cy, R, col) {
    var pts = dotField(s, cx, cy, R);
    var bx = cx + s.sx * R, by = cy - s.sy * R, now = frameTime;
    for (var i = 0; i < pts.length; i++) {
        var p = pts[i];
        var dx = p.x - bx, dy = p.y - by;
        var near = Math.max(0, 1 - Math.sqrt(dx * dx + dy * dy) / (22 + 26 * s.amt));
        var glow = Math.min(1, near * (0.4 + 0.6 * s.amt) + s.wet * (0.35 + 0.35 * Math.sin(now * 3 + p.tw)) * (1 - p.d * 0.6));
        if (glow < 0.04) continue;
        var base = p.tint ? DOT_OLIVE : DOT_TEAL;
        var sz = 1.6 + 1.2 * glow;
        g.set_source_rgba(base[0] + (col[0] - base[0]) * glow, base[1] + (col[1] - base[1]) * glow,
                          base[2] + (col[2] - base[2]) * glow, 0.55 + 0.45 * glow);
        g.rectangle(p.x - sz / 2, p.y - sz / 2, sz, sz); g.fill();
    }
}

function drawPlunger(g, s, cx, cy, R, col) {
    if (s.mode === "hold") { drawBowl(g, s, cx, cy, R, col); return; }
    var bx = cx + s.sx * R, by = cy - s.sy * R;
    g.set_line_width(1);
    g.set_source_rgba(FG[0], FG[1], FG[2], 0.08);
    g.ellipse(cx - R, cy - R, R * 2, R * 2); g.stroke();
    if (s.wet > 0.002) {
        g.set_line_width(2.5);
        g.set_source_rgba(col[0], col[1], col[2], 0.9);
        g.arc(cx, cy, R + 5, -Math.PI / 2, -Math.PI / 2 + s.wet * Math.PI * 2); g.stroke();
    }
    // wind-up: a spiral of stored turns around the ball (circling before release lengthens the tail)
    var turns = Math.min(2, s.windup / (2 * Math.PI));
    if (turns > 0.05 && s.amt > 0) {
        g.set_line_width(1.4);
        g.set_source_rgba(col[0], col[1], col[2], 0.75);
        var steps = Math.round(40 * turns);
        for (var q = 0; q <= steps; q++) {
            var f = q / Math.max(1, steps), ang = f * turns * 2 * Math.PI, rad = 9 + 9 * f;
            var px = bx + Math.cos(ang) * rad, py = by - Math.sin(ang) * rad;
            if (q === 0) g.move_to(px, py); else g.line_to(px, py);
        }
        g.stroke();
    }
    var len = Math.sqrt((bx - cx) * (bx - cx) + (by - cy) * (by - cy));
    if (len > 1) {
        var ux = (bx - cx) / len, uy = (by - cy) / len, coils = 7, nd = coils * 6;
        var twist = s.windup * 1.5;                       // the coils roll as the plunger winds
        var amp = 3.2 + 1.6 * (1 - s.amt);
        for (var c = 0; c <= nd; c++) {
            var f2 = c / nd;
            var ph = f2 * coils * 2 * Math.PI + twist;
            var side = Math.sin(ph) * amp;
            // front half of each turn brighter than the back half: reads as a helix, stays flat
            var front = Math.cos(ph) > 0 ? 1 : 0.45;
            var tint = s.amt * front;
            g.set_source_rgba(DIM[0] + (col[0] - DIM[0]) * tint, DIM[1] + (col[1] - DIM[1]) * tint,
                              DIM[2] + (col[2] - DIM[2]) * tint, 0.5 + 0.5 * front);
            var px = cx + ux * len * f2 - uy * side, py = cy + uy * len * f2 + ux * side, ds = front > 0.5 ? 2.2 : 1.6;
            g.rectangle(px - ds / 2, py - ds / 2, ds, ds); g.fill();
        }
    }
    dot(g, cx, cy, 5 + 6 * s.flash, col, 0.25 + 0.6 * s.flash);
    if (s.amt > 0) dot(g, bx, by, 10 + 6 * s.amt, col, 0.25 * s.amt);
    drawBall(g, bx, by);
}

// hold FX: a bowl. Tilt rolls the ball out; at full tilt it presses the rim (the sweet spot),
// circling drags a glowing trail round the rim and throws sparks off it.
function drawBowl(g, s, cx, cy, R, col) {
    var bx = cx + s.sx * R, by = cy - s.sy * R, i;
    // bowl: shaded floor + rim
    g.set_line_width(1);
    g.set_source_rgba(FG[0], FG[1], FG[2], 0.18 + 0.2 * s.amt);
    g.ellipse(cx - R, cy - R, R * 2, R * 2); g.stroke();
    // pressure: an arc of the rim lights up around the contact point, wider with more tilt
    if (s.amt > 0.05) {
        var ang = Math.atan2(s.sy, s.sx), wdt = 0.25 + 0.9 * s.amt;
        g.set_line_width(2 + 3 * s.amt);
        g.set_source_rgba(col[0], col[1], col[2], 0.35 + 0.6 * s.amt);
        g.arc(cx, cy, R, -ang - wdt / 2, -ang + wdt / 2); g.stroke();
    }
    // circling trail along the rim
    for (i = 0; i < s.trail.length; i++) {
        var tr = s.trail[i];
        var tx = cx + Math.cos(tr.a) * R, ty = cy - Math.sin(tr.a) * R;
        dot(g, tx, ty, 6, col, 0.18 * tr.e);
        dot(g, tx, ty, 2.2, col, 0.8 * tr.e);
    }
    for (i = 0; i < s.sparks.length; i++) {
        var sk = s.sparks[i], k = 1 - sk.age / sk.life;
        dotRGB(g, sk.x, sk.y, 1.6, 1, 0.95, 0.8, k);
        dot(g, sk.x, sk.y, 4, col, 0.25 * k);
    }
    // wet ring just outside the rim
    if (s.wet > 0.002) {
        g.set_line_width(2);
        g.set_source_rgba(col[0], col[1], col[2], 0.55);
        g.arc(cx, cy, R + 7, -Math.PI / 2, -Math.PI / 2 + s.wet * Math.PI * 2); g.stroke();
    }
    // the ball, squashed against the rim when pressed
    if (s.amt > 0.9) {                                // pressed into the rim: a salmon contact ring
        g.set_line_width(1.2);
        g.set_source_rgba(SALMON[0], SALMON[1], SALMON[2], 0.9);
        g.ellipse(bx - 11, by - 11, 22, 22); g.stroke();
    }
    dot(g, cx, cy, 3 + 6 * s.flash, col, 0.2 + 0.6 * s.flash);
    drawBall(g, bx, by);
}

function drawBall(g, bx, by) {
    g.set_source_rgb(FIELD[0], FIELD[1], FIELD[2]);          // knock the dots out behind it
    g.ellipse(bx - 7.5, by - 7.5, 15, 15); g.fill();
    g.set_source_rgb(MINT[0], MINT[1], MINT[2]);
    g.ellipse(bx - 4.5, by - 4.5, 9, 9); g.fill();
    g.set_line_width(1);
    g.set_source_rgba(MINT[0], MINT[1], MINT[2], 0.6);
    g.ellipse(bx - 7, by - 7, 14, 14); g.stroke();
}

function drawFilter(g, s, r, col) {
    var x0 = r.x + 8, x1 = r.x + r.w - 8, yb = r.y + r.h - 18, yt = r.y + 26;
    var fc = s.cut, q = s.res;
    g.set_line_width(1.8);
    g.set_source_rgba(col[0], col[1], col[2], 0.35 + 0.6 * Math.min(1, s.wet * 2 + 0.1));
    for (var i = 0; i <= 80; i++) {
        var u = i / 80;
        var d = (u - fc) / 0.08;
        var mag = u < fc ? 1 : Math.exp(-d * d * 0.18) * 0 + Math.pow(Math.max(0, 1 - (u - fc) * 3.2), 2);
        var peak = q * Math.exp(-((u - fc) * (u - fc)) / 0.0012);
        var y = yb - (yb - yt) * (0.55 * mag + 0.45 * peak);
        if (i === 0) g.move_to(x0 + (x1 - x0) * u, y); else g.line_to(x0 + (x1 - x0) * u, y);
    }
    g.stroke();
}

function drawPhaser(g, s, cx, cy, R, col) {
    var n = 14;
    for (var i = 0; i < n; i++) {
        var a = s.spin + i * Math.PI * 2 / n;
        var rr = R * (0.55 + 0.55 * s.wet + 0.35 * (s.whoosh || 0) + 0.25 * s.amt * s.sx) * (1 + 0.12 * Math.sin(s.spin * 3 + i));
        var x = cx + Math.cos(a) * rr, y = cy + Math.sin(a) * rr;
        var k = 0.15 + 0.85 * s.wet * (0.5 + 0.5 * Math.sin(a * 2 - s.spin * 2));
        dot(g, x, y, 5, col, 0.2 * k);
        dot(g, x, y, 1.8, col, k);
    }
}

function drawTail(g, s, r, col) {
    var t = s.tail;
    var life = TAIL_LIFE;
    var fade = Math.min(1, t.t * 12) * Math.min(1, (life - t.t) * 4);
    g.set_source_rgba(BG[0], BG[1], BG[2], 0.86 * fade); g.rectangle(r.x, r.y + 24, r.w, r.h - 24); g.fill();
    var x0 = r.x + 12, x1 = r.x + r.w - 12, yt = r.y + 56, yb = r.y + r.h - 22;

    if (t.kind === "FEEDBACK") tailRepeats(g, t, x0, x1, yt, yb, col, fade);
    else if (t.kind === "CRUSH") tailCrush(g, t, x0, x1, yt, yb, col, fade);
    else if (t.kind === "RESONANCE") tailResonance(g, t, x0, x1, yt, yb, col, fade);
    else tailCurve(g, t, x0, x1, yt, yb, col, fade);

    // value + step pips
    g.select_font_face("Arial Bold");
    g.set_font_size(13);
    g.set_source_rgba(FG[0], FG[1], FG[2], fade);
    g.move_to(x0, r.y + 44); g.show_text(t.kind + "  " + t.text);
    var pw = 6, gap = 3, total = t.steps * (pw + gap) - gap, px = x1 - total, i;
    for (i = 0; i < t.steps; i++) {
        var on = i <= t.step;
        g.set_source_rgba(on ? col[0] : DIM[0], on ? col[1] : DIM[1], on ? col[2] : DIM[2], (i === t.step ? 1 : 0.55) * fade);
        g.rectangle(px + i * (pw + gap), r.y + 35 + (i === t.step ? 0 : 3), pw, i === t.step ? 9 : 6); g.fill();
    }
}

// reverb / envelope: exponential decay over a 6 s ruler, a ball runs it in real time
function tailCurve(g, t, x0, x1, yt, yb, col, fade) {
    var span = 6.0, i, u, y;
    g.set_line_width(1);
    g.set_source_rgba(DIM[0], DIM[1], DIM[2], 0.5 * fade);
    for (var sec = 0; sec <= span; sec++) {
        var tx = x0 + (x1 - x0) * sec / span;
        g.move_to(tx, yb); g.line_to(tx, yb + 4); g.stroke();
    }
    // filled glow under the curve
    g.move_to(x0, yb);
    for (i = 0; i <= 90; i++) {
        u = i / 90 * span;
        g.line_to(x0 + (x1 - x0) * u / span, yb - (yb - yt) * Math.exp(-u * Math.log(127) / t.decay));
    }
    g.line_to(x1, yb); g.close_path();
    g.set_source_rgba(col[0], col[1], col[2], 0.14 * fade); g.fill();
    g.set_line_width(2);
    g.set_source_rgba(col[0], col[1], col[2], fade);
    for (i = 0; i <= 90; i++) {
        u = i / 90 * span;
        y = yb - (yb - yt) * Math.exp(-u * Math.log(127) / t.decay);
        if (i === 0) g.move_to(x0, y); else g.line_to(x0 + (x1 - x0) * u / span, y);
    }
    g.stroke();
    var run = Math.min(1, t.t / 0.7) * Math.min(t.decay, span);
    if (t.t <= 0.75) {
        var bx = x0 + (x1 - x0) * run / span, by = yb - (yb - yt) * Math.exp(-run * Math.log(127) / t.decay);
        dot(g, bx, by, 8, col, 0.3 * fade);
        dot(g, bx, by, 3.2, FG, fade);
    }
}

// echo / grain / phaser: one bar per repeat, each feedback times the last; a ball hops them
function tailRepeats(g, t, x0, x1, yt, yb, col, fade) {
    var fb = Math.min(0.97, Math.max(0.02, t.frac * 0.95));
    var n = 16, w = (x1 - x0) / n, i, h = 1;
    var hop = Math.floor(t.t / 0.05);
    for (i = 0; i < n; i++) {
        var bh = (yb - yt) * h;
        var lit = i === hop;
        g.set_source_rgba(col[0], col[1], col[2], (lit ? 1 : 0.35 + 0.4 * h) * fade);
        g.rectangle(x0 + i * w + w * 0.2, yb - bh, w * 0.6, Math.max(1, bh)); g.fill();
        if (lit && bh > 1) { dot(g, x0 + i * w + w * 0.5, yb - bh - 6, 7, col, 0.3 * fade); dot(g, x0 + i * w + w * 0.5, yb - bh - 6, 3, FG, fade); }
        h *= fb;
    }
    g.set_source_rgba(DIM[0], DIM[1], DIM[2], 0.5 * fade);
    g.set_line_width(1); g.move_to(x0, yb + 0.5); g.line_to(x1, yb + 0.5); g.stroke();
}

// redux: a sine drawn through a sample-and-hold that gets coarser (fewer, taller steps) with CRUSH
function tailCrush(g, t, x0, x1, yt, yb, col, fade) {
    var c = t.frac, mid = (yt + yb) / 2, amp = (yb - yt) * 0.45, i, u;
    var hold = 1 + Math.round(c * 22);                 // samples held per step
    var levels = Math.max(2, Math.round(lerp(32, 3, c)));
    g.set_line_width(1);
    g.set_source_rgba(DIM[0], DIM[1], DIM[2], 0.45 * fade);
    for (i = 0; i <= 120; i++) {
        u = i / 120;
        var y0 = mid - amp * Math.sin(u * Math.PI * 4 + t.t * 3);
        if (i === 0) g.move_to(x0 + (x1 - x0) * u, y0); else g.line_to(x0 + (x1 - x0) * u, y0);
    }
    g.stroke();
    g.set_line_width(2);
    g.set_source_rgba(col[0], col[1], col[2], fade);
    var n = 120, prevY = null;
    for (i = 0; i <= n; i++) {
        var si = Math.floor(i / hold) * hold;
        u = si / n;
        var yv = Math.sin(u * Math.PI * 4 + t.t * 3);
        yv = Math.round(yv * levels / 2) / (levels / 2);
        var y = mid - amp * yv, x = x0 + (x1 - x0) * i / n;
        if (prevY === null) g.move_to(x, y); else { g.line_to(x, prevY); g.line_to(x, y); }
        prevY = y;
    }
    g.stroke();
}

function lerp(a, b, k) { return a + (b - a) * k; }

// filter: the resonant peak grows and rings (a decaying sine) with the step
function tailResonance(g, t, x0, x1, yt, yb, col, fade) {
    var q = t.frac, i, u, y;
    var fc = 0.45;
    g.set_line_width(2);
    g.set_source_rgba(col[0], col[1], col[2], fade);
    for (i = 0; i <= 120; i++) {
        u = i / 120;
        var base = u < fc ? 1 : Math.pow(Math.max(0, 1 - (u - fc) * 2.6), 2);
        var peak = q * 1.3 * Math.exp(-((u - fc) * (u - fc)) / (0.0006 + 0.004 * (1 - q)));
        y = yb - (yb - yt) * Math.min(1, 0.45 * base + 0.55 * peak);
        if (i === 0) g.move_to(x0 + (x1 - x0) * u, y); else g.line_to(x0 + (x1 - x0) * u, y);
    }
    g.stroke();
    // ringing at the cutoff: longer with more resonance
    var cx = x0 + (x1 - x0) * fc, ring = 0.2 + 2.5 * q * q, ph = t.t * 18;
    g.set_line_width(1.2);
    g.set_source_rgba(FG[0], FG[1], FG[2], 0.7 * fade);
    for (i = 0; i <= 60; i++) {
        u = i / 60;
        y = (yt + yb) / 2 + Math.sin(ph + u * 30) * (yb - yt) * 0.25 * Math.exp(-u * 3 / ring) * q;
        if (i === 0) g.move_to(cx, y); else g.line_to(cx + (x1 - cx) * u, y);
    }
    g.stroke();
}

// ---- small helpers -------------------------------------------------------------------
function dotRGB(g, x, y, rad, r, gg, b, a) {
    if (a <= 0.003) return;
    g.set_source_rgba(r, gg, b, Math.min(1, a));
    g.ellipse(x - rad, y - rad, rad * 2, rad * 2); g.fill();
}

function dot(g, x, y, rad, c, a) {
    if (a <= 0.003) return;
    g.set_source_rgba(c[0], c[1], c[2], Math.min(1, a));
    g.ellipse(x - rad, y - rad, rad * 2, rad * 2); g.fill();
}

function roundRect(g, x, y, w, h, rr) {
    g.move_to(x + rr, y);
    g.line_to(x + w - rr, y); g.arc(x + w - rr, y + rr, rr, -Math.PI / 2, 0);
    g.line_to(x + w, y + h - rr); g.arc(x + w - rr, y + h - rr, rr, 0, Math.PI / 2);
    g.line_to(x + rr, y + h); g.arc(x + rr, y + h - rr, rr, Math.PI / 2, Math.PI);
    g.line_to(x, y + rr); g.arc(x + rr, y + rr, rr, Math.PI, Math.PI * 1.5);
    g.close_path();
}

function mix(a, b, k) { return [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k]; }
function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
function gauss() { return (Math.random() + Math.random() + Math.random() - 1.5) / 0.75; }

function onresize() { invalidate(); mgraphics.redraw(); }
