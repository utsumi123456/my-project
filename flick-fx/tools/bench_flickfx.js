// --- bench only (appended by FLICKFX_BENCH=1 builds) ---------------------------
// Drives both sticks synthetically: circling at full tilt, pulls and flicks, so the
// view gets a worst-case stream of particles, rings, trails and sparks.
var benchT = 0;
var benchTick = tick;
tick = function () {
    benchT += 0.008;
    var ph = benchT % 3;                       // 3 s cycle per side, offset for R
    drive(S[0], ph, 0);
    drive(S[1], (benchT + 1.5) % 3, 1);
    // what a real pad sends between ticks: per-event device info + axis events (~750 events/s)
    for (var e = 0; e < 6; e++) {
        padinfo(1, 0, "Controller", "(GP20S-Xinput)", "unknown");
        axis_left_x(S[0].sx); axis_right_x(S[1].sx);
    }
    benchTick();
};
function drive(side, ph, k) {
    if (ph < 1.6) {                            // circle at full tilt
        var a = benchT * (6 + k * 3);
        side.sx = Math.cos(a); side.sy = Math.sin(a);
    } else if (ph < 2.2) {                     // hold a pull
        side.sx = -0.95; side.sy = -0.2;
    } else {                                   // snap back (flick) and rest
        side.sx = 0; side.sy = 0;
    }
}
