// TuneScope UI (jsui / mgraphics) — Sc0pe v2 方式: メッセージ駆動・一枚描画
autowatch = 1;
mgraphics.init();
mgraphics.relative_coords = 0;
mgraphics.autofill = 0;

outlets = 1; // settempo <bpm> / reset / freeze <0|1>

// ---- 状態 ----
var st = {
  bpm: 0, bpmConf: 0,
  key: "", scale: "", keyConf: 0,
  chroma: [0,0,0,0,0,0,0,0,0,0,0,0], // HPCP: bin0 = A
  liveTempo: 0,
  frozen: 0,
  ready: 0,
  notation: 0,  // 0=Camelot 1=Open Key 2=音名
  smoothing: 1  // 0=Fast 1=Normal 2=Stable
};

// ---- カラー（Sc0pe 準拠のカラーランゲージ） ----
var COL = {
  bg:      [0.09, 0.10, 0.13, 1.0],
  cyan:    [0.0, 0.933, 1.0, 1.0],     // BPM = リズム
  amber:   [1.0, 0.725, 0.004, 1.0],   // Key = ハーモニー
  dim:     [1.0, 1.0, 1.0, 0.35],
  faint:   [1.0, 1.0, 1.0, 0.12],
  good:    [0.4, 0.9, 0.4, 1.0],
  bad:     [1.0, 0.35, 0.35, 1.0]
};

var FONT = "Ableton Sans Medium";

// ---- Camelot 変換 ----
var NOTE_INDEX = { "A":0,"A#":1,"BB":1,"B":2,"C":3,"C#":4,"DB":4,"D":5,"D#":6,"EB":6,"E":7,"F":8,"F#":9,"GB":9,"G":10,"G#":11,"AB":11 };
// index基準: A=0（半音順）
var CAMELOT_MINOR = { 0:"8A", 1:"3A", 2:"10A", 3:"5A", 4:"12A", 5:"7A", 6:"2A", 7:"9A", 8:"4A", 9:"11A", 10:"6A", 11:"1A" };
var CAMELOT_MAJOR = { 0:"11B", 1:"6B", 2:"1B", 3:"8B", 4:"3B", 5:"10B", 6:"5B", 7:"12B", 8:"7B", 9:"2B", 10:"9B", 11:"4B" };

function camelot(note, scale) {
  var idx = NOTE_INDEX[String(note).toUpperCase()];
  if (idx === undefined) return "--";
  return (String(scale).toLowerCase() === "minor") ? CAMELOT_MINOR[idx] : CAMELOT_MAJOR[idx];
}

// Open Key: Camelot 8A = 1m, 8B = 1d（番号 -7 mod 12、A→m / B→d）
function openkey(note, scale) {
  var cam = camelot(note, scale);
  if (cam === "--") return "--";
  var n = parseInt(cam, 10);
  var letter = cam.charAt(cam.length - 1);
  var openNum = ((n - 8 + 12) % 12) + 1;
  return openNum + (letter === "A" ? "m" : "d");
}

// ---- メッセージハンドラ ----
function bpm(v, conf, alt) { st.bpm = v; st.bpmConf = conf || 0; st.bpmAlt = alt || 0; mgraphics.redraw(); }
function key(name, scale, conf, altName, altScale) {
  st.key = name; st.scale = scale; st.keyConf = conf || 0;
  st.keyAlt = altName ? (altName + " " + altScale) : "";
  mgraphics.redraw();
}
function chroma() { st.chroma = arrayfromargs(arguments); mgraphics.redraw(); }
function live_tempo(v) { st.liveTempo = v; mgraphics.redraw(); }
function status(kind) {
  if (kind === "ready") st.ready = 1;
  if (kind === "reset") { st.bpm = 0; st.key = ""; st.keyConf = 0; st.bpmConf = 0; }
  mgraphics.redraw();
}
function notation(v) { st.notation = Math.max(0, Math.min(2, v | 0)); mgraphics.redraw(); }
function smoothing(v) { st.smoothing = Math.max(0, Math.min(2, v | 0)); mgraphics.redraw(); }

// ---- 描画 ----
function paint() {
  var g = mgraphics;
  var w = this.box.rect[2] - this.box.rect[0];
  var h = this.box.rect[3] - this.box.rect[1];

  g.set_source_rgba(COL.bg);
  g.rectangle(0, 0, w, h);
  g.fill();

  g.select_font_face(FONT, "normal", "normal");

  // タイトル
  g.set_source_rgba(COL.dim);
  g.set_font_size(9);
  g.move_to(5, 12);
  g.text_path("TUNESCOPE");
  g.fill();
  if (!st.ready) {
    g.set_font_size(8);
    g.move_to(w - 24, 12);
    g.text_path("...");
    g.fill();
  }

  // ---- BPM セクション ----
  var yB = 18;
  g.set_source_rgba(fadeByConf(COL.cyan, st.bpmConf));
  g.select_font_face(FONT, "normal", "bold");
  g.set_font_size(26);
  var bpmTxt = st.bpm > 0 ? st.bpm.toFixed(1) : "---";
  drawCentered(g, bpmTxt, w / 2, yB + 26);
  g.select_font_face(FONT, "normal", "normal");
  confBar(g, 8, yB + 34, w - 16, st.bpmConf, COL.cyan);

  // スムージングモード表示（BPM数値クリックで切替）
  g.set_source_rgba(COL.dim);
  g.set_font_size(7);
  g.move_to(w - 14, yB + 32);
  g.text_path(["F", "N", "S"][st.smoothing]);
  g.fill();

  // 左: ×2/÷2 代替候補（クリックで切替） / 右: Live テンポ差分（クリックで反映）
  if (st.bpm > 0) {
    g.set_font_size(9);
    if (st.bpmAlt > 0) {
      g.set_source_rgba(COL.dim);
      var altLabel = (st.bpmAlt > st.bpm ? "×2 " : "÷2 ") + st.bpmAlt.toFixed(0);
      drawCentered(g, altLabel, w * 0.25, yB + 48);
    }
    if (st.liveTempo > 0) {
      var d = st.bpm - st.liveTempo;
      g.set_source_rgba(Math.abs(d) < 0.5 ? COL.good : COL.dim);
      drawCentered(g, (d >= 0 ? "+" : "") + d.toFixed(1) + " →SET", w * 0.72, yB + 48);
    }
  }

  // ---- Key セクション ----
  var yK = 74;
  g.set_source_rgba(COL.faint);
  g.move_to(5, yK); g.line_to(w - 5, yK); g.set_line_width(1); g.stroke();

  g.set_source_rgba(fadeByConf(COL.amber, st.keyConf));
  var keyTxt = st.key ? (st.key + " " + (st.scale === "minor" ? "min" : "maj")) : "";
  if (st.notation === 2) {
    // 音名のみ大表示
    g.select_font_face(FONT, "normal", "bold");
    g.set_font_size(20);
    drawCentered(g, keyTxt || "--", w / 2, yK + 26);
    g.select_font_face(FONT, "normal", "normal");
  } else {
    var big = st.key ? (st.notation === 0 ? camelot(st.key, st.scale) : openkey(st.key, st.scale)) : "--";
    g.select_font_face(FONT, "normal", "bold");
    g.set_font_size(22);
    drawCentered(g, big, w * 0.3, yK + 26);
    g.select_font_face(FONT, "normal", "normal");
    g.set_font_size(11);
    drawCentered(g, keyTxt, w * 0.72, yK + 26);
  }
  confBar(g, 8, yK + 34, w - 16, st.keyConf, COL.amber);
  // 僅差の第2候補（相対調など）を右端に小さく併記
  if (st.keyAlt) {
    g.set_source_rgba(COL.amber[0], COL.amber[1], COL.amber[2], 0.35);
    g.set_font_size(7);
    var altParts = st.keyAlt.split(" ");
    var altCam = camelot(altParts[0], altParts[1]);
    g.move_to(w - 30, yK + 32);
    g.text_path("? " + altCam);
    g.fill();
  }

  // ---- クロマ（12セグメント バー、A 起点） ----
  var yC = yK + 42;
  var names = ["A","","B","C","","D","","E","F","","G",""];
  var bw = (w - 16) / 12;
  var maxv = 0.0001;
  for (var i = 0; i < 12; i++) maxv = Math.max(maxv, st.chroma[i] || 0);
  for (var i = 0; i < 12; i++) {
    var v = (st.chroma[i] || 0) / maxv;
    var bh = 16 * v;
    g.set_source_rgba(COL.amber[0], COL.amber[1], COL.amber[2], 0.25 + 0.75 * v);
    g.rectangle(8 + i * bw, yC + 16 - bh, bw - 1, bh);
    g.fill();
    g.set_source_rgba(COL.faint);
    g.set_font_size(6);
    g.move_to(8 + i * bw + 1, yC + 24);
    g.text_path(names[i]);
    g.fill();
  }

  // ---- TAG | FREEZE ----
  var yF = h - 16;
  var half = (w - 20) / 2;
  var canTag = st.key !== "" && st.bpm > 0;
  g.set_source_rgba(canTag ? COL.amber[0] : 1, canTag ? COL.amber[1] : 1, canTag ? COL.amber[2] : 1, canTag ? 0.5 : 0.12);
  g.rectangle(8, yF, half, 12);
  g.set_line_width(1);
  g.stroke();
  g.set_source_rgba(canTag ? COL.amber : COL.faint);
  g.set_font_size(8);
  drawCentered(g, "TAG", 8 + half / 2, yF + 9);

  g.set_source_rgba(st.frozen ? COL.bad : COL.faint);
  g.rectangle(12 + half, yF, half, 12);
  st.frozen ? g.fill() : g.stroke();
  g.set_source_rgba(st.frozen ? [0,0,0,1] : COL.dim);
  drawCentered(g, "FREEZE", 12 + half + half / 2, yF + 9);
}

function fadeByConf(col, conf) {
  var a = 0.35 + 0.65 * Math.max(0, Math.min(1, conf));
  return [col[0], col[1], col[2], a];
}

function confBar(g, x, y, w, conf, col) {
  g.set_source_rgba(COL.faint);
  g.rectangle(x, y, w, 3);
  g.fill();
  g.set_source_rgba(col[0], col[1], col[2], 0.9);
  g.rectangle(x, y, w * Math.max(0, Math.min(1, conf)), 3);
  g.fill();
}

function drawCentered(g, txt, cx, y) {
  var m = g.text_measure(txt);
  g.move_to(cx - m[0] / 2, y);
  g.text_path(txt);
  g.fill();
}

// ---- インタラクション ----
function onclick(x, y) {
  var h = this.box.rect[3] - this.box.rect[1];
  var w = this.box.rect[2] - this.box.rect[0];
  if (y > h - 20) {                 // 下段: 左=TAG（クリップ名に [Key BPM] 付与） / 右=FREEZE
    if (x < w / 2) {
      if (st.key !== "" && st.bpm > 0) {
        outlet(0, "tag", camelot(st.key, st.scale), Math.round(st.bpm));
      }
    } else {
      st.frozen = st.frozen ? 0 : 1;
      outlet(0, "freeze", st.frozen);
    }
  } else if (y > 60 && y < 74 && st.bpm > 0) { // 補助行: 左=×2/÷2 切替、右=Live テンポ反映
    if (x < w / 2) outlet(0, "bpmswap");
    else outlet(0, "settempo", st.bpm);
  } else if (y >= 18 && y < 56) {   // BPM 数値: スムージング切替 (F/N/S)
    st.smoothing = (st.smoothing + 1) % 3;
    outlet(0, "smoothing", st.smoothing);
  } else if (y >= 74 && y < 112) {  // Key 表示: 表記切替 (Camelot/Open Key/音名)
    st.notation = (st.notation + 1) % 3;
    outlet(0, "notation", st.notation);
  }
  mgraphics.redraw();
}

function ondblclick() {
  outlet(0, "reset");
  status("reset");
}
