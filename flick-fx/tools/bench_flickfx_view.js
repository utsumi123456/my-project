// --- bench only (appended by FLICKFX_BENCH=1 builds) ---------------------------
// Logs frame-gap stats every 5 s through error() so they land in Live's Log.txt.
var benchLast = 0, benchMax = 0, benchSum = 0, benchN = 0, benchSlow = 0, benchStart = 0;
var benchFrame = frame;
frame = function () {
    var t0 = new Date().getTime();
    if (benchLast) {
        var gap = t0 - benchLast;
        benchMax = Math.max(benchMax, gap); benchSum += gap; benchN++;
        if (gap > (BIG ? 66 : 50)) benchSlow++;      // "slow" = a dropped frame at the target rate
    } else {
        benchStart = t0;
    }
    benchLast = t0;
    benchFrame();
    if ((!BIG || zoomVisible()) && t0 - benchStart > 5000 && benchN) {
        error("FlickFX bench" + (BIG ? " [zoom]" : "") + ": frames " + benchN + " avg " + (benchSum / benchN).toFixed(1) + " ms max " + benchMax + " ms dropped " + benchSlow + "\n");
        benchMax = benchSum = benchN = benchSlow = 0; benchStart = t0;
    }
};
timer.cancel();
timer = new Task(frame, this);
timer.interval = FRAME_MS;
timer.repeat();
