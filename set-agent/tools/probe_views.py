"""Boot the two-view workbench, measure both views from inside WebView2, quit.

  python -m tools.probe_views [playlist] [width height]

Read-only redesign (2026-09-16): the main view must carry the predicted length
as its hero and hold at a narrow width; the detail view must still show all the
lanes. This asks the view itself for numbers instead of a screenshot.
"""
from __future__ import annotations

import json
import sys
import time

import webview

from setagent.webui.api import Api
from setagent.webui.app import index_path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BOX = """
const box = sel => {
  const e = document.querySelector(sel);
  if (!e) return null;
  const b = e.getBoundingClientRect();
  return {top: Math.round(b.top), bottom: Math.round(b.bottom), h: Math.round(b.height),
          w: Math.round(b.width),
          onscreen: b.top < innerHeight && b.bottom > 0 && b.height > 0};
};
"""

MAIN = "(() => {" + BOX + """
  const txt = id => (document.getElementById(id)||{}).textContent || "";
  return {
    view: 'main',
    viewport: [innerWidth, innerHeight],
    hero: txt('hero').trim(),
    heroClass: (document.getElementById('hero')||{}).className,
    heroSub: txt('heroSub').replace(/\\s+/g,' ').trim(),
    heroFontPx: parseFloat(getComputedStyle(document.getElementById('hero')).fontSize),
    reco: {hidden: document.getElementById('reco').hidden,
           cls: document.getElementById('reco').className,
           q: document.getElementById('reco').dataset.q,
           text: txt('reco').replace(/\\s+/g,' ').trim()},
    /* the list under the hero is advice: removal candidates (over) or
       tracks to add (under), never the playlist itself */
    list: {hidden: document.getElementById('listBlock').hidden,
           head: txt('listHead').trim(), note: txt('listNote').trim(),
           rows: document.querySelectorAll('.row').length,
           rmRows: document.querySelectorAll('.row.rm').length,
           addRows: document.querySelectorAll('.row.add').length,
           fitsRows: document.querySelectorAll('.row.fits').length,
           artImgs: document.querySelectorAll('.row .art img').length,
           rowH: Math.round((document.querySelector('.row')||{getBoundingClientRect:()=>({height:0})}).getBoundingClientRect().height),
           firstRow: (document.querySelector('.row')||{}).textContent?.replace(/\\s+/g,' ').trim(),
           lastRow: [...document.querySelectorAll('.row')].pop()?.textContent.replace(/\\s+/g,' ').trim()},
    presetOptions: [...document.querySelectorAll('#preset option')].map(o => o.value + '=' + o.textContent),
    cap32Label: (document.getElementById('cap32Lbl')||{}).textContent?.trim(),
    cap32Hidden: (document.getElementById('cap32Lbl')||{}).hidden,
    tooltips: document.querySelectorAll('#app [title]').length,
    gone: ['plName','freshTxt','rescan','warns'].filter(id => document.getElementById(id)),
    /* reading order: conditions above the hero, hero above the card and list */
    order: ['.cond-row','.hero-block','#reco','#listBlock'].map(sel => box(sel)?.top),
    setBpm: {value: document.getElementById('setBpm').value, st: ST && ST.set_bpm,
             varOn: document.getElementById('bpmVar').checked, panelHidden: document.getElementById('bpmv').hidden,
             changes: (ST && ST.bpm_changes || []).map(c => c.i + ':' + c.bpm)},
    boxes: {bar: box('.bar'), main: box('#main'), hero: box('.hero-block'),
            reco: box('#reco'), conds: box('.cond-row'), list: box('#listBlock')},
    detailHidden: document.getElementById('detail').hidden,
    horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
    mainOverflowX: document.getElementById('main').scrollWidth > document.getElementById('main').clientWidth,
  };
})()"""

DETAIL = "(() => {" + BOX + """
  return {
    view: 'detail',
    mainHidden: document.getElementById('main').hidden,
    transport: box('.transport'), scroll: box('#scroll'), tracks: box('#tracks'),
    energy: box('#energy'), sections: box('#sections'), legend: box('.legend'),
    reality: box('#reality'), foot: box('.foot'),
    energySvg: !!document.querySelector('#energy svg'),
    energyPaths: document.querySelectorAll('#energy path').length,
    trackBlocks: document.querySelectorAll('.trk').length,
    altBlocks: document.querySelectorAll('.trk.alt').length,
    phraseBlocksInLane: document.querySelectorAll('.trk .ph').length,
    hatched: document.querySelectorAll('.trk .none').length,
    legendItems: [...document.querySelectorAll('.legend .lg')].map(e => e.textContent.trim()).filter(Boolean),
    warnsGone: !document.getElementById('warns'),
    zoomButtons: [...document.querySelectorAll('[data-zoom]')].map(b => b.dataset.zoom + '=' + b.textContent),
    labelledBlocks: document.querySelectorAll('.trk .trk-t').length,
    analysisMeta: (document.getElementById('analysisMeta')||{}).textContent,
    realityHidden: document.querySelector('.reality-row').hidden,
    editGone: !document.getElementById('selEdit'),
    sectionRows: document.querySelectorAll('.sec').length,
    canvasWidth: Math.round(document.getElementById('canvas').clientWidth),
    minimapChildren: document.getElementById('minimap').children.length,
    realityHead: (document.querySelector('#reality h3')||{}).textContent,
    warns: document.querySelectorAll('#warns li').length,
  };
})()"""


def run(window):
    try:
        for i in range(60):
            time.sleep(1)
            try:
                if window.evaluate_js("!document.getElementById('app').hidden"):
                    print(f"ready after {i + 1}s")
                    break
            except Exception:
                pass
        else:
            print("never became ready")
        time.sleep(1)
        m = window.evaluate_js(MAIN)
        print(json.dumps(m, ensure_ascii=False, indent=2))

        # a removal row selects that track; the same track must be selected in detail
        window.evaluate_js("(document.querySelectorAll('.row.rm')[2]||{click(){}}).click()")
        time.sleep(0.5)
        sel = window.evaluate_js(
            "[...document.querySelectorAll('.row')].findIndex(r => r.dataset.sel === '1')")
        print("selected row after click:", sel)

        # the settings sheet holds the manual reload now
        window.evaluate_js("document.getElementById('settings').click()")
        time.sleep(0.8)
        print("settings sheet:", json.dumps(window.evaluate_js("""({
            open: !document.getElementById('modal').hidden,
            fresh: (document.getElementById('freshTxt')||{}).textContent,
            rescan: (document.getElementById('rescan')||{}).textContent,
            hasKey: !!document.getElementById('fKey')})"""), ensure_ascii=False))
        window.evaluate_js("closeModal()")

        window.evaluate_js("document.querySelector('[data-view=detail]').click()")
        time.sleep(1)
        d = window.evaluate_js(DETAIL)
        print(json.dumps(d, ensure_ascii=False, indent=2))
        selTitle = window.evaluate_js("document.getElementById('selTitle').textContent")
        print("inspector shows:", selTitle)

        # double-click a track block: the phrase sheet carries the colours now
        window.evaluate_js("document.querySelector('.trk').dispatchEvent(new MouseEvent('dblclick',{bubbles:true}))")
        time.sleep(0.5)
        print("phrase sheet:", json.dumps(window.evaluate_js("""({
            open: !document.getElementById('modal').hidden,
            title: document.getElementById('mTitle').textContent,
            strip: document.querySelectorAll('.phrase-strip .ph').length,
            items: document.querySelectorAll('.ph-list .lg').length})"""), ensure_ascii=False))
        window.evaluate_js("closeModal()")
        lanes = {k: d[k] for k in ("tracks", "energy", "sections")}
        bad = [k for k, v in lanes.items() if not (v and v["onscreen"])]
        print("\nTier lanes off screen in detail:", bad or "none")

        # at the detail density every block carries its number and name
        window.evaluate_js("document.querySelector('[data-zoom=detail]').click()")
        time.sleep(0.8)
        print("detail zoom labels:", window.evaluate_js(
            "({blocks: document.querySelectorAll('.trk').length, labelled: document.querySelectorAll('.trk .trk-t').length,"
            "  first: (document.querySelector('.trk .trk-t')||{}).textContent})"))
        window.evaluate_js("document.querySelector('[data-zoom=section]').click()")

        window.evaluate_js("document.querySelector('[data-view=main]').click()")
        time.sleep(0.3)
        print("back to main, detail hidden:",
              window.evaluate_js("document.getElementById('detail').hidden"))

        # set tempo: 160 for the whole set, then a change point from track 4 on
        hero0 = window.evaluate_js("document.getElementById('hero').textContent")
        window.evaluate_js("const e=document.getElementById('setBpm'); e.value='160'; e.dispatchEvent(new Event('change'))")
        time.sleep(2.5)
        print("set BPM 160:", json.dumps(window.evaluate_js("""({
            hero: document.getElementById('hero').textContent, was: %r,
            sub: document.getElementById('heroSub').textContent.replace(/\\s+/g,' ').trim(),
            tempos: [...new Set(ST.tracks.map(t => t.set_tempo))]})""" % hero0), ensure_ascii=False))
        window.evaluate_js("document.getElementById('bpmVar').click()")
        time.sleep(0.5)
        window.evaluate_js("document.getElementById('cpTrack').value='3'; document.getElementById('cpBpm').value='170';"
                           "document.getElementById('cpAdd').click()")
        time.sleep(2.5)
        print("change point:", json.dumps(window.evaluate_js("""({
            hero: document.getElementById('hero').textContent,
            panelHidden: document.getElementById('bpmv').hidden,
            rows: document.querySelectorAll('#cpList .cp').length,
            tempos: ST.tracks.slice(0,6).map(t => t.set_tempo),
            changes: ST.bpm_changes})"""), ensure_ascii=False))
        window.evaluate_js("document.getElementById('undo').click()")
        time.sleep(2)
        window.evaluate_js("const e=document.getElementById('setBpm'); e.value=''; e.dispatchEvent(new Event('change'))")
        time.sleep(2.5)
        print("cleared:", window.evaluate_js(
            "({hero: document.getElementById('hero').textContent, st: ST.set_bpm, changes: ST.bpm_changes.length})"))
    except Exception as ex:
        print("probe failed:", type(ex).__name__, ex)
    finally:
        window.destroy()


if __name__ == "__main__":
    pl = sys.argv[1] if len(sys.argv) > 1 else "acid"
    w_, h_ = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (1280, 820)
    api = Api(pl)
    w = webview.create_window("Set Agent — probe", index_path(), js_api=api,
                              width=w_, height=h_, background_color="#0d1014",
                              maximized=(len(sys.argv) <= 3))
    api._window = w
    webview.start(run, w)
