#!/usr/bin/python
"""framefan_qam - a "Fan cap" slider in the Quick Access menu's Performance tab.

Runs as the steamos user (framefan-qam.service). Steam's UI is Chromium; Developer Mode
leaves its DevTools port open on 127.0.0.1:8080. This connects to the Quick Access popup
page, injects a slider (cloned from one of Steam's own Performance-tab rows, so it looks
native and survives Steam's class-name churn), and writes the chosen percentage to
/etc/framefan/cap, which the root fan service applies within a second.

The page can only hand back a number through the `framefanSet` binding; anything outside
55-100 is dropped here, and again by the fan service.
"""
import asyncio
import glob
import json
import sys

import aiohttp

DEVTOOLS = "http://127.0.0.1:8080/json"
POPUP_KEY = "vrOverlayKey=valve.steam.gamepadui.barpopup"
CAP_FILE = "/etc/framefan/cap"
FAN_NAME = "slg4ax46073v"
MIN_PCT, MAX_PCT, STOCK_DUTY = 55, 100, 55

INJECT = r"""
(() => {
  window.__framefan?.remove();
  const MIN = %(min)d, MAX = %(max)d, STOCK = %(stock)d, ID = 'framefan-section';
  const S = { cap: null, live: null, drag: null, events: {} };
  const stop = e => e.stopPropagation();

  const perf = () => document.querySelector('.tab_Perf');
  const norm = v => (v - MIN) / (MAX - MIN);

  // Steam's generated class names change between builds, so copy a live row instead of naming them.
  function build(panel) {
    const sliders = [...panel.querySelectorAll('[role=slider]')];
    const sectionOf = el => { while (el && el.parentElement !== panel) el = el.parentElement; return el; };
    const rowOf = el => { while (el && el.parentElement?.parentElement !== panel) el = el.parentElement; return el; };
    // Prefer a row that shows its value next to the label (Frame Limit), else any slider row.
    const pick = sliders.find(s => [...rowOf(s).querySelectorAll('div')].some(d => d.children.length === 2 &&
        [...d.children].every(c => !c.children.length && c.textContent.trim()))) || sliders[sliders.length - 1];
    if (!pick) return false;
    const srcRow = rowOf(pick), srcSection = sectionOf(pick);
    // A section title ("Common Settings" etc.): a section's first child that holds only text.
    const isHeader = el => el && !el.querySelector('[role]') && el.textContent.trim() && el.nextElementSibling;
    const header = [srcSection, ...panel.children].map(s => s.firstElementChild).find(isHeader);

    const section = srcSection.cloneNode(false);
    section.id = ID;
    if (header) {
      const h = header.cloneNode(true);
      const leaf = [...h.querySelectorAll('*')].find(e => !e.children.length) || h;
      leaf.textContent = 'Fan';
      S.headerText = leaf;
      section.append(h);
    }
    const row = srcRow.cloneNode(true);
    section.append(row);

    const slider = row.querySelector('[role=slider]');
    const control = slider.firstElementChild;  // carries --normalized-slider-value
    slider.classList.remove('gpfocus');
    // Label (+ value) live in the first text-bearing block before the slider.
    const pair = [...row.querySelectorAll('div')].find(d => !d.contains(slider) && d.children.length === 2 &&
        [...d.children].every(c => !c.children.length));
    const leaves = [...row.querySelectorAll('div')].filter(d => !d.contains(slider) && !d.children.length && d.textContent.trim());
    S.label = pair ? pair.children[0] : leaves[0];
    S.value = pair ? pair.children[1] : null;
    if (S.label) S.label.textContent = 'Fan Cap';
    // Notch labels under the track: reuse the first and last for the range ends, drop the rest.
    const notches = slider.children[1] ? [...slider.children[1].children] : [];
    notches.forEach((n, i) => {
      const t = [...n.querySelectorAll('*')].find(e => !e.children.length) || n;
      if (i === 0) t.textContent = MIN + '%%';
      else if (i === notches.length - 1) t.textContent = MAX + '%%';
      else n.remove();
    });
    S.slider = slider; S.control = control;

    // Drag like Steam's own sliders: grab on the track, then follow the pointer anywhere on the
    // page until release. touch-action stops the laser's motion being taken as a scroll gesture,
    // which would cancel the drag after a few pixels.
    for (const el of [slider, control]) { el.style.touchAction = 'none'; el.style.userSelect = 'none'; }
    for (const ev of ['click', 'mousedown', 'mouseup', 'pointerdown', 'pointerup', 'touchstart', 'keydown']) section.addEventListener(ev, stop);
    const count = e => { S.events[e.type] = (S.events[e.type] || 0) + 1; };
    const xOf = e => e.touches?.length ? e.touches[0].clientX : e.changedTouches?.length ? e.changedTouches[0].clientX : e.clientX;
    const valueAt = x => {
      const r = control.getBoundingClientRect();
      const n = Math.min(1, Math.max(0, (x - r.left) / r.width));
      return Math.round(MIN + n * (MAX - MIN));
    };
    let cancelTimer = null;
    const move = e => {
      count(e);
      if (S.drag === null) return;
      clearTimeout(cancelTimer);
      const x = xOf(e);
      if (x != null) { S.drag = valueAt(x); render(); }
      if (e.cancelable && e.type === 'touchmove') e.preventDefault();
    };
    const end = e => {
      count(e);
      if (S.drag === null) return;
      S.cap = S.drag; S.drag = null; render();
      window.framefanSet?.(String(S.cap));
      for (const t of MOVES) window.removeEventListener(t, move, true);
      for (const t of ENDS) window.removeEventListener(t, end, true);
      window.removeEventListener('pointercancel', cancelled, true);
    };
    // A cancel (e.g. a gesture the browser claimed) only ends the drag if movement doesn't continue.
    const cancelled = e => { count(e); clearTimeout(cancelTimer); cancelTimer = setTimeout(() => end(e), 300); };
    const MOVES = ['pointermove', 'mousemove', 'touchmove'], ENDS = ['pointerup', 'mouseup', 'touchend', 'touchcancel'];
    const start = e => {
      count(e);
      stop(e);
      if (S.drag !== null) return;  // pointerdown and mousedown both arrive for one press
      try { if (e.pointerId != null) control.setPointerCapture(e.pointerId); } catch (_) {}
      S.drag = valueAt(xOf(e)); render();
      for (const t of MOVES) window.addEventListener(t, move, { capture: true, passive: false });
      for (const t of ENDS) window.addEventListener(t, end, true);
      window.addEventListener('pointercancel', cancelled, true);
    };
    for (const t of ['pointerdown', 'mousedown', 'touchstart']) slider.addEventListener(t, start, { passive: false });

    // Right below the first section (System Profile), i.e. above Common Settings.
    const first = sectionOf(sliders[0]);
    panel.insertBefore(section, first.nextSibling);
    render();
    return true;
  }

  function render() {
    if (!S.control || !S.control.isConnected) return;
    const v = S.drag ?? S.cap ?? MAX;
    S.control.style.setProperty('--normalized-slider-value', norm(v));
    S.slider.setAttribute('aria-valuenow', v);
    const duty = Math.floor(STOCK * v / 100);
    const text = `${v}%% · ≤${(duty * 100).toLocaleString()} rpm`;
    // Live readings: the temperature sits on the slider row so it's visible even without a header.
    const l = S.live || {};
    const temp = l.hot != null ? `${Math.round(l.hot)}°C` : '';
    if (S.value) {
      S.value.textContent = text;
      if (S.label) S.label.textContent = 'Fan Cap' + (temp ? `  ·  ${temp}` : '');
    } else if (S.label) {
      S.label.textContent = `Fan Cap  ${text}` + (temp ? `  ·  ${temp}` : '');
    }
    if (S.headerText) S.headerText.textContent = 'Fan' + (l.rpm != null ? ` · now ${l.rpm.toLocaleString()} rpm` : '') +
        (temp ? ` · hottest ${temp}` : '');
  }

  let pending = false;
  const obs = new MutationObserver(() => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => {
      pending = false;
      const panel = perf();
      if (panel && !panel.querySelector('#' + ID) && panel.querySelector('[role=slider]')) build(panel);
    });
  });
  obs.observe(document.body, { childList: true, subtree: true });

  window.__framefan = {
    update(state) { S.cap = state.cap; S.live = state.live; render(); },
    debug: () => ({ drag: S.drag, cap: S.cap, events: S.events, header: !!S.headerText }),
    remove() { obs.disconnect(); document.getElementById(ID)?.remove(); delete window.__framefan; },
  };
  const panel = perf();
  if (panel && panel.querySelector('[role=slider]')) build(panel);
  return 'framefan injected';
})()
""" % {"min": MIN_PCT, "max": MAX_PCT, "stock": STOCK_DUTY}


def read(p):
    try:
        with open(p) as f:
            return f.read().strip()
    except OSError:
        return None


def fan_dir():
    for h in glob.glob("/sys/class/hwmon/hwmon*"):
        if read(h + "/name") == FAN_NAME:
            return h


def saved_cap():
    try:
        pct = float(read(CAP_FILE))
        return int(pct) if MIN_PCT <= pct <= MAX_PCT else None
    except (TypeError, ValueError):
        return None


def live(fan):
    rpm = read(fan + "/fan1_input") if fan else None
    temps = [int(t) / 1000 for z in glob.glob("/sys/class/thermal/thermal_zone*/temp")
             if (t := read(z)) and t.lstrip("-").isdigit()]
    return {"rpm": int(rpm) // 2 if rpm and rpm.isdigit() else None, "hot": max(temps) if temps else None}


def save_cap(raw):
    try:
        pct = int(raw)
    except (TypeError, ValueError):
        return
    if MIN_PCT <= pct <= MAX_PCT:
        with open(CAP_FILE, "w") as f:
            f.write(f"{pct}\n")
        print(f"cap set to {pct}%", flush=True)


async def attach(session, url, fan):
    """Inject into one popup page and serve it until the page goes away."""
    try:
        await serve(session, url, fan)
    except (aiohttp.ClientError, OSError, asyncio.TimeoutError) as e:
        print(f"lost popup page ({e.__class__.__name__})", flush=True)


async def serve(session, url, fan):
    async with session.ws_connect(url, max_msg_size=0) as ws:
        ids = iter(range(1, 1 << 30))

        async def send(method, **params):
            await ws.send_json({"id": next(ids), "method": method, "params": params})

        await send("Runtime.enable")
        await send("Runtime.addBinding", name="framefanSet")
        await send("Runtime.evaluate", expression=INJECT)
        print("injected into Quick Access popup", flush=True)

        async def push():
            while True:
                state = json.dumps({"cap": saved_cap(), "live": live(fan)})
                await send("Runtime.evaluate", expression=f"window.__framefan?.update({state})")
                await asyncio.sleep(1)

        pusher = asyncio.create_task(push())
        try:
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    break
                data = json.loads(msg.data)
                method = data.get("method")
                if method == "Runtime.bindingCalled" and data["params"].get("name") == "framefanSet":
                    save_cap(data["params"].get("payload"))
                elif method == "Runtime.executionContextsCleared":  # page reloaded: inject again
                    await send("Runtime.addBinding", name="framefanSet")
                    await asyncio.sleep(0.5)
                    await send("Runtime.evaluate", expression=INJECT)
        finally:
            pusher.cancel()


async def main():
    fan = fan_dir()
    attached = {}  # page id -> task; Steam can keep more than one Quick Access popup page
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(DEVTOOLS) as r:
                    pages = await r.json(content_type=None)
                for p in pages:
                    if POPUP_KEY in p.get("url", "") and (p["id"] not in attached or attached[p["id"]].done()):
                        attached[p["id"]] = asyncio.create_task(attach(session, p["webSocketDebuggerUrl"], fan))
            except (aiohttp.ClientError, OSError, asyncio.TimeoutError) as e:
                print(f"waiting for Steam UI ({e.__class__.__name__})", flush=True)
            for pid, task in list(attached.items()):
                if task.done():
                    del attached[pid]
            await asyncio.sleep(5)


if __name__ == "__main__":
    if "--print-js" in sys.argv:
        print(INJECT)
        sys.exit(0)
    asyncio.run(main())
