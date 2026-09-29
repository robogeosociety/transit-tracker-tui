"""HTML page generators for the Transit Tracker web server.

Contains the inline HTML/CSS/JS templates for the index, logs, and
simulator pages. (The dashboard and network-topology monitor views
were retired in favor of Grafana — see CLAUDE.md "Observability
stack". A lean /logs tail is kept for ad-hoc, no-Grafana debugging.)
"""

import json
import os
from typing import Dict, List


def generate_index_html(pages: List[Dict[str, str]]) -> str:
    """Generate an index page listing available web pages."""
    cards = "".join(
        '<a href="' + p["path"] + '" class="card"><h2>' + p["name"] + '</h2><p>' + p["description"] + '</p></a>'
        for p in pages
    )
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Transit Tracker</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'><rect width='10' height='3' rx='1.5' fill='%23e8a830'/></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root { --bg:#06080e;--bg1:#0c0f1a;--border:#1a1e35;--text0:#eae8e4;--text2:#5c6080;--amber:#e8a830;--amber-bg:rgba(232,168,48,0.08); }
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Outfit',system-ui,sans-serif;background:var(--bg);color:var(--text0);display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:100vh;padding:40px 20px}
body::after{content:'';position:fixed;inset:0;background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.5'/%3E%3C/svg%3E");opacity:0.018;pointer-events:none;z-index:9999}
.brand{font-weight:700;font-size:12px;letter-spacing:2.5px;text-transform:uppercase;color:var(--amber);display:flex;align-items:center;gap:10px;margin-bottom:6px}
.brand svg{opacity:0.8}
p.sub{color:var(--text2);font-size:13px;margin-bottom:28px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;max-width:600px;width:100%}
.card{display:block;text-decoration:none;color:var(--text0);background:var(--bg1);border:1px solid var(--border);border-radius:8px;padding:14px 16px;transition:border-color 0.2s,transform 0.15s}
.card:hover{border-color:var(--amber);transform:translateY(-2px)}
.card h2{font-size:14px;font-weight:600;margin-bottom:3px;color:var(--amber)}
.card p{font-size:11.5px;color:var(--text2);line-height:1.4}
@keyframes fi{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.card{animation:fi 0.4s cubic-bezier(0.22,1,0.36,1) both}
.card:nth-child(1){animation-delay:.04s}.card:nth-child(2){animation-delay:.08s}.card:nth-child(3){animation-delay:.12s}
.card:nth-child(4){animation-delay:.16s}.card:nth-child(5){animation-delay:.2s}.card:nth-child(6){animation-delay:.24s}
.card:nth-child(7){animation-delay:.28s}.card:nth-child(8){animation-delay:.32s}.card:nth-child(9){animation-delay:.36s}
</style>
</head>
<body>
  <div class="brand">
    <svg width="18" height="13" viewBox="0 0 18 13" fill="none"><rect width="18" height="2.4" rx="1.2" fill="currentColor"/><rect y="5" width="12" height="2.4" rx="1.2" fill="currentColor" opacity="0.55"/><rect y="10" width="7" height="2.4" rx="1.2" fill="currentColor" opacity="0.25"/></svg>
    Transit Tracker
  </div>
  <p class="sub">Available pages</p>
  <div class="grid">""" + cards + """</div>
</body>
</html>"""


def generate_logs_html() -> str:
    """Generate the lean live log-tail page.

    Polls /api/logs (the in-memory ring buffer) and appends entries to a
    scrolling list. This is the only observability view kept in-app after
    the dashboard + network monitor were retired in favor of Grafana —
    it exists for ad-hoc debugging when you don't want to tail
    ``~/Library/Logs/transit-tracker.log`` on the host.
    """
    return r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Transit Tracker — Logs</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'><rect width='10' height='3' rx='1.5' fill='%23e8a830'/></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root { --bg:#06080e;--bg1:#0c0f1a;--bg2:#141828;--border:#1a1e35;--text0:#eae8e4;--text1:#9498b0;--text2:#5c6080;--text3:#353850;--amber:#e8a830;--amber-bg:rgba(232,168,48,0.08);--cyan:#3d80d0;--green:#40b868;--red:#d84050;--purple:#9060c0; }
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Outfit',system-ui,sans-serif;background:var(--bg);color:var(--text0);display:flex;flex-direction:column;height:100vh}
.nav{display:flex;align-items:center;justify-content:space-between;padding:0 28px;height:50px;background:var(--bg1);border-bottom:1px solid var(--border);flex-shrink:0}
.nav-left{display:flex;align-items:center;gap:24px}
.nav-brand{font-weight:700;font-size:12px;letter-spacing:2.5px;text-transform:uppercase;color:var(--amber)}
.nav-links{display:flex;gap:2px}
.nav-link{font-size:12.5px;font-weight:500;color:var(--text2);text-decoration:none;padding:5px 12px;border-radius:5px;transition:all .2s}
.nav-link:hover{color:var(--text0);background:var(--bg2)}
.nav-link.active{color:var(--amber);background:var(--amber-bg)}
.nav-right{display:flex;align-items:center;gap:14px}
.ctl{font-size:11.5px;background:#1a1a24;border:1px solid var(--border);color:var(--text1);padding:4px 8px;border-radius:5px;font-family:inherit}
.live-badge{display:flex;align-items:center;gap:6px;font-size:11.5px;font-weight:500;color:var(--green)}
.live-dot{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 8px rgba(64,184,104,.5);animation:pulse 2.5s ease-in-out infinite}
.live-dot.off{background:var(--red);box-shadow:0 0 8px rgba(216,64,80,.4);animation:none}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.35;transform:scale(.8)}}
.log-list{flex:1;overflow-y:auto;font-family:'IBM Plex Mono',monospace;font-size:11.5px;padding:6px 0}
.log-row{display:grid;grid-template-columns:88px 58px 110px 1fr;gap:10px;padding:2px 20px;border-bottom:1px solid rgba(20,24,40,.4);white-space:pre-wrap;word-break:break-word}
.log-row:hover{background:var(--bg2)}
.log-ts{color:var(--text3)}
.log-comp{color:var(--cyan)}
.log-msg{color:var(--text0)}
.lvl{font-weight:600;text-align:center;border-radius:3px;font-size:10px;padding:1px 0;align-self:start}
.lvl-INFO{color:var(--green)}.lvl-DEBUG{color:var(--text2)}.lvl-WARNING{color:var(--amber)}.lvl-ERROR{color:var(--red)}.lvl-CRITICAL{color:#fff;background:var(--red)}
.empty{color:var(--text2);padding:24px 20px;font-family:'Outfit',sans-serif;font-size:13px}
::-webkit-scrollbar{width:6px}::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
</style>
</head>
<body>
<nav class="nav">
  <div class="nav-left">
    <div class="nav-brand">Transit Tracker</div>
    <div class="nav-links">
      <a href="/transit-tracker/logs" class="nav-link active">Logs</a>
      <a href="/transit-tracker/simulator" class="nav-link">Simulator</a>
      <a href="/transit-tracker/spec" class="nav-link">API</a>
    </div>
  </div>
  <div class="nav-right">
    <select id="level-filter" class="ctl">
      <option value="">All levels</option>
      <option value="DEBUG">Debug+</option>
      <option value="INFO">Info+</option>
      <option value="WARNING">Warning+</option>
      <option value="ERROR">Error only</option>
    </select>
    <label class="ctl" style="display:flex;align-items:center;gap:5px;cursor:pointer"><input type="checkbox" id="follow" checked style="accent-color:var(--amber)"> Follow</label>
    <div class="live-badge"><span class="live-dot" id="dot"></span><span id="conn">Connecting</span></div>
  </div>
</nav>
<div class="log-list" id="list"><div class="empty" id="empty">Waiting for log entries…</div></div>
<script>
(function(){
'use strict';
var list=document.getElementById('list');
var empty=document.getElementById('empty');
var dot=document.getElementById('dot');
var conn=document.getElementById('conn');
var levelFilter=document.getElementById('level-filter');
var follow=document.getElementById('follow');
var lastTs=0;
var ORDER={DEBUG:10,INFO:20,WARNING:30,WARN:30,ERROR:40,CRITICAL:50};
function esc(s){var d=document.createElement('div');d.textContent=(s==null?'':s);return d.innerHTML;}
function fmt(ts){var d=new Date(ts*1000);return d.toLocaleTimeString([],{hour12:false})+'.'+String(d.getMilliseconds()).padStart(3,'0');}
function passes(level){var min=levelFilter.value;if(!min)return true;return (ORDER[level]||20)>=(ORDER[min]||0);}
function render(entries){
  var atBottom=list.scrollHeight-list.scrollTop-list.clientHeight<50;
  var frag=document.createDocumentFragment();var added=0;
  for(var i=0;i<entries.length;i++){
    var e=entries[i];var level=(e.level||'INFO').toUpperCase();
    if(!passes(level))continue;
    var comp=e.component||e.logger||'';var msg=e.msg||e.message||'';
    var row=document.createElement('div');row.className='log-row';
    row.innerHTML='<span class="log-ts">'+fmt(e.ts)+'</span>'+
      '<span class="lvl lvl-'+esc(level)+'">'+esc(level)+'</span>'+
      '<span class="log-comp">'+esc(comp)+'</span>'+
      '<span class="log-msg">'+esc(msg)+'</span>';
    frag.appendChild(row);added++;
  }
  if(added){if(empty){empty.remove();empty=null;}list.appendChild(frag);
    while(list.children.length>1000)list.removeChild(list.firstChild);
    if(follow.checked&&atBottom)list.scrollTop=list.scrollHeight;}
}
function poll(){
  fetch('/transit-tracker/api/logs?since='+lastTs+'&limit=200').then(function(r){return r.json();}).then(function(d){
    dot.className='live-dot';conn.textContent='Live';
    if(d.logs&&d.logs.length){render(d.logs);lastTs=d.logs[d.logs.length-1].ts+0.0001;}
  }).catch(function(){dot.className='live-dot off';conn.textContent='Error';});
}
levelFilter.addEventListener('change',function(){
  list.innerHTML='';lastTs=0;poll();
});
poll();
setInterval(poll,2000);
})();
</script>
</body>
</html>
"""


def generate_simulator_html() -> str:
    """Generate a self-contained browser-based LED matrix simulator.

    Connects to the WebSocket server client-side, renders a pixel-perfect
    HUB75 LED matrix on an HTML5 Canvas, with MicroFont glyph data, realtime
    icon animation, and headsign scrolling.
    """
    from ..simulator import BaseSimulator, MicroFont

    # Export glyph data as JSON for the JS renderer
    glyphs_json = json.dumps({k: v for k, v in MicroFont.GLYPHS.items()})
    icon_json = json.dumps(MicroFont.REALTIME_ICON)

    # Build subscribe payload from current config so the web simulator
    # sends real subscription data instead of relying on server defaults.
    try:
        from ..config import TransitConfig, get_last_config_path, load_service_settings

        svc = load_service_settings()
        config_path = (
            get_last_config_path()
            or os.environ.get("CONFIG_PATH")
            or ("/config/config.yaml" if os.path.exists("/config/config.yaml") else None)
            or "config.yaml"
        )
        config = TransitConfig.load(config_path, service_settings=svc)

        class _Stub(BaseSimulator):
            async def run(self):
                pass

        stub = _Stub(config, force_live=True)
        sub_payload = stub.build_subscribe_payload(
            client_name="WebSimulator",
            limit=10,
        )
        subscribe_json = json.dumps(sub_payload)
    except Exception:
        subscribe_json = json.dumps({
            "event": "schedule:subscribe",
            "client_name": "WebSimulator",
            "data": {"routeStopPairs": "", "limit": 10},
        })

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Transit Tracker — LED Simulator</title>
<style>
:root {{
  --bg: #0a0a0a;
  --bg-card: #141418;
  --border: #252530;
  --text: #dde1ed;
  --text2: #8891b0;
  --muted: #505872;
  --green: #00c853;
  --red: #ff1744;
  --purple: #7c4dff;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'SF Mono','Menlo','Consolas',monospace; background: var(--bg); color: var(--text); }}
.header {{
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 24px; border-bottom: 1px solid var(--border); background: var(--bg-card);
}}
.header h1 {{ font-size: 14px; font-weight: 600; }}
.header h1 span {{ color: var(--purple); }}
.controls {{
  display: flex; align-items: center; gap: 16px; font-size: 12px; color: var(--text2);
}}
.controls select, .controls input {{
  background: #1a1a24; border: 1px solid var(--border); color: var(--text);
  padding: 4px 8px; border-radius: 4px; font-family: inherit; font-size: 12px;
}}
.status-dot {{
  display: inline-block; width: 8px; height: 8px; border-radius: 50%;
  background: var(--red); transition: background 0.3s;
}}
.status-dot.connected {{ background: var(--green); animation: pulse 2s infinite; }}
@keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.4}} }}
.sim-container {{
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  min-height: calc(100vh - 49px); padding: 40px;
}}
canvas {{
  image-rendering: pixelated; border: 2px solid #333;
  border-radius: 4px; background: #000;
}}
.info {{
  margin-top: 16px; font-size: 11px; color: var(--muted); text-align: center;
}}
a {{ color: var(--purple); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
/* Embed mode: canvas fills entire viewport, no chrome */
body.embed {{ background: #000; margin: 0; padding: 0; overflow: hidden; }}
body.embed .header {{ display: none; }}
body.embed .sim-container {{ min-height: 0; height: 100vh; padding: 0; display: block; }}
body.embed .info {{ display: none; }}
body.embed canvas {{ border: none; border-radius: 0; display: block; width: 100%; height: 100%; }}
</style>
</head>
<body>
<script>if(location.search.indexOf('embed=1')>=0)document.body.classList.add('embed');</script>
<div class="header">
  <h1><span>Transit Tracker</span> &mdash; LED Simulator</h1>
  <div class="controls">
    <span><span class="status-dot" id="ws-dot"></span> <span id="ws-label">Disconnected</span></span>
    <label>Endpoint:
      <select id="endpoint-select">
        <option value="local">Local (via /transit-tracker/ws proxy)</option>
        <option value="cloud">Cloud (tt.horner.tj)</option>
        <option value="custom">Custom...</option>
      </select>
    </label>
    <input type="text" id="custom-url" placeholder="ws://host:port" style="display:none;width:200px;">
    <a href="/transit-tracker/logs">Logs &rarr;</a>
  </div>
</div>
<div class="sim-container">
  <canvas id="led-canvas"></canvas>
  <div class="info">
    <div id="trip-info">Waiting for data...</div>
    <div style="margin-top:8px;">Pixel scale: <input type="range" id="scale-range" min="2" max="12" value="6" style="vertical-align:middle;width:100px;">
    <span id="scale-label">6x</span></div>
  </div>
</div>

<script>
// ---- Config ----
const PANEL_W = 64, PANEL_H = 32, NUM_PANELS = 2;
const DISPLAY_W = PANEL_W * NUM_PANELS;
const DISPLAY_H = PANEL_H;
let PIXEL_SCALE = (location.search.indexOf('embed=1') >= 0) ? 3 : 6;
const PIXEL_GAP = 1;

// ---- Glyph data from Python MicroFont ----
const GLYPHS = {glyphs_json};
const REALTIME_ICON = {icon_json};

// ---- Subscribe payload from config ----
const SUBSCRIBE_PAYLOAD = {subscribe_json};

// ---- State ----
let ws = null;
let trips = [];
let startTime = Date.now();
let subscribePayload = null;

// ---- Canvas setup ----
const canvas = document.getElementById('led-canvas');
const ctx = canvas.getContext('2d');

function resizeCanvas() {{
  canvas.width = DISPLAY_W * PIXEL_SCALE;
  canvas.height = DISPLAY_H * PIXEL_SCALE;
}}
resizeCanvas();

// ---- Scale slider ----
const scaleRange = document.getElementById('scale-range');
const scaleLabel = document.getElementById('scale-label');
scaleRange.addEventListener('input', () => {{
  PIXEL_SCALE = parseInt(scaleRange.value);
  scaleLabel.textContent = PIXEL_SCALE + 'x';
  resizeCanvas();
}});

// ---- Font rendering ----
function getGlyphBitmap(ch) {{
  const key = ch.toUpperCase();
  const glyph = GLYPHS[key] || GLYPHS[ch] || GLYPHS['?'];
  if (!glyph) return Array.from({{length:7}}, () => []);
  const rows = [];
  for (let i = 0; i < 7; i++) {{
    const bits = glyph[i];
    const row = [];
    for (let b = 4; b >= 0; b--) {{
      row.push((bits >> b) & 1);
    }}
    row.push(0); // gap
    rows.push(row);
  }}
  return rows;
}}

function getTextBitmap(text) {{
  const rows = Array.from({{length:7}}, () => []);
  for (const ch of text) {{
    const glyph = getGlyphBitmap(ch);
    for (let i = 0; i < 7; i++) {{
      rows[i].push(...glyph[i]);
    }}
  }}
  return rows;
}}

function getIconFrame(elapsed) {{
  const cycleMs = Math.floor(elapsed * 1000) % 4000;
  let frame = 0;
  if (cycleMs >= 3000) {{
    frame = Math.min(Math.floor((cycleMs - 3000) / 200) + 1, 5);
  }}
  const rows = Array.from({{length:7}}, () => []);
  for (let r = 0; r < 6; r++) {{
    for (let c = 0; c < 6; c++) {{
      const seg = REALTIME_ICON[r][c];
      if (seg === 0) {{ rows[r].push(0); continue; }}
      let lit = false;
      if (seg === 1 && [1,2,3].includes(frame)) lit = true;
      else if (seg === 2 && [2,3,4].includes(frame)) lit = true;
      else if (seg === 3 && [3,4,5].includes(frame)) lit = true;
      rows[r].push(lit ? 2 : 1);
    }}
  }}
  rows[6] = [0,0,0,0,0,0];
  return rows;
}}

// ---- Color helpers ----
function parseColor(c) {{
  if (!c) return '#cccc00';
  if (c === 'hot_pink') return '#ff69b4';
  if (c === 'yellow') return '#cccc00';
  if (c === 'white') return '#ffffff';
  if (c === 'bright_blue') return '#5599ff';
  if (c === 'grey74') return '#bbbbbb';
  if (c.startsWith('#')) return c;
  return '#cccc00';
}}

function dimColor(c) {{
  // Return a very dim version for the "dim segment" of the icon
  return '#223366';
}}

// ---- Trip processing (mirrors BaseSimulator._process_trip) ----
function processDepartures(rawTrips) {{
  const now = Date.now();
  const deps = [];
  for (const trip of rawTrips) {{
    const tripId = trip.tripId;
    if (!tripId) continue;
    let arrVal = trip.arrivalTime || trip.predictedArrivalTime || 0;
    if (!arrVal) continue;
    const baseMs = arrVal > 1e12 ? arrVal : arrVal * 1000;
    const diffMin = Math.floor((baseMs - now) / 60000);
    if (diffMin < -1) continue;

    const routeName = trip.routeName || '?';
    const headsign = trip.headsign || 'Transit';
    const isLive = !!trip.isRealtime;
    const colorHex = trip.routeColor;
    let color = 'yellow';
    if (routeName.includes('14')) color = 'hot_pink';
    else if (colorHex) color = '#' + colorHex;

    deps.push({{
      trip_id: tripId,
      diff: Math.max(0, diffMin),
      route: routeName,
      headsign: headsign,
      color: color,
      live: isLive,
      stop_id: trip.stopId || '',
    }});
  }}
  deps.sort((a,b) => a.diff - b.diff);
  // Diversity cap: 1 per stop, then fill to 3
  const final = [];
  const seen = new Set();
  for (const d of deps) {{
    if (!seen.has(d.stop_id)) {{ final.push(d); seen.add(d.stop_id); }}
    if (final.length >= 3) break;
  }}
  if (final.length < 3) {{
    for (const d of deps) {{
      if (!final.includes(d)) final.push(d);
      if (final.length >= 3) break;
    }}
  }}
  final.sort((a,b) => a.diff - b.diff);
  return final;
}}

// ---- Render frame ----
function renderFrame() {{
  const elapsed = (Date.now() - startTime) / 1000;
  ctx.fillStyle = '#000000';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const deps = processDepartures(trips);

  if (deps.length === 0) {{
    const msg = trips.length === 0 ? 'Connecting...' : 'No Live Buses';
    const bm = getTextBitmap(msg);
    for (let r = 0; r < 7; r++) {{
      for (let c = 0; c < bm[r].length; c++) {{
        if (bm[r][c]) {{
          ctx.fillStyle = '#00cccc';
          ctx.fillRect(c * PIXEL_SCALE, r * PIXEL_SCALE,
                       PIXEL_SCALE - PIXEL_GAP, PIXEL_SCALE - PIXEL_GAP);
        }}
      }}
    }}
    requestAnimationFrame(renderFrame);
    return;
  }}

  let rowY = 0;
  for (let di = 0; di < Math.min(deps.length, 3); di++) {{
    const dep = deps[di];
    const timeStr = dep.diff <= 0 ? 'Now' : dep.diff + 'm';
    const routeColor = parseColor(dep.color);
    const timeColor = dep.live ? '#5599ff' : '#bbbbbb';

    // Compute segment widths
    const routeBm = getTextBitmap(dep.route + '  ');
    const headsignBm = getTextBitmap(dep.headsign);
    const timeBm = getTextBitmap(' ' + timeStr);
    const iconW = dep.live ? 8 : 0;
    const fixedW = routeBm[0].length + timeBm[0].length + iconW;
    const headsignAreaW = Math.max(0, DISPLAY_W - fixedW);

    let x = 0;
    // Route
    for (let r = 0; r < 7; r++) {{
      for (let c = 0; c < routeBm[r].length; c++) {{
        if (routeBm[r][c]) {{
          ctx.fillStyle = routeColor;
          ctx.fillRect((x + c) * PIXEL_SCALE, (rowY + r) * PIXEL_SCALE,
                       PIXEL_SCALE - PIXEL_GAP, PIXEL_SCALE - PIXEL_GAP);
        }}
      }}
    }}
    x += routeBm[0].length;

    // Headsign (clipped to area)
    for (let r = 0; r < 7; r++) {{
      for (let c = 0; c < Math.min(headsignBm[r].length, headsignAreaW); c++) {{
        if (headsignBm[r][c]) {{
          ctx.fillStyle = '#ffffff';
          ctx.fillRect((x + c) * PIXEL_SCALE, (rowY + r) * PIXEL_SCALE,
                       PIXEL_SCALE - PIXEL_GAP, PIXEL_SCALE - PIXEL_GAP);
        }}
      }}
    }}
    x += headsignAreaW;

    // Live icon
    if (dep.live) {{
      const icon = getIconFrame(elapsed);
      const ix = x + 1;
      for (let r = 0; r < 6; r++) {{
        for (let c = 0; c < 6; c++) {{
          const val = icon[r][c];
          if (val === 2) {{
            ctx.fillStyle = '#ffffff';
            ctx.fillRect((ix + c) * PIXEL_SCALE, (rowY + r) * PIXEL_SCALE,
                         PIXEL_SCALE - PIXEL_GAP, PIXEL_SCALE - PIXEL_GAP);
          }} else if (val === 1) {{
            ctx.fillStyle = dimColor();
            ctx.fillRect((ix + c) * PIXEL_SCALE, (rowY + r) * PIXEL_SCALE,
                         PIXEL_SCALE - PIXEL_GAP, PIXEL_SCALE - PIXEL_GAP);
          }}
        }}
      }}
      x += 8;
    }}

    // Time
    for (let r = 0; r < 7; r++) {{
      for (let c = 0; c < timeBm[r].length; c++) {{
        if (timeBm[r][c]) {{
          ctx.fillStyle = timeColor;
          ctx.fillRect((x + c) * PIXEL_SCALE, (rowY + r) * PIXEL_SCALE,
                       PIXEL_SCALE - PIXEL_GAP, PIXEL_SCALE - PIXEL_GAP);
        }}
      }}
    }}

    rowY += 11; // 7 rows + 4 spacer
  }}

  // Update info text
  const infoEl = document.getElementById('trip-info');
  const lines = deps.map(d => d.route + '  ' + d.headsign + '  ' + (d.live ? '\\u25c9' : '\\u25cb') + ' ' + (d.diff <= 0 ? 'Now' : d.diff + 'm'));
  infoEl.textContent = lines.join('  |  ');

  requestAnimationFrame(renderFrame);
}}

// ---- WebSocket ----
function getWsUrl() {{
  const sel = document.getElementById('endpoint-select').value;
  const custom = document.getElementById('custom-url');
  const wsProt = location.protocol === 'https:' ? 'wss://' : 'ws://';
  // Connect via /transit-tracker/ws on the same origin — the web server
  // proxies to the internal WS server on :8000.
  if (sel === 'local') return wsProt + location.host + '/transit-tracker/ws';
  if (sel === 'cloud') return 'wss://tt.horner.tj/';
  return custom.value || (wsProt + location.host + '/transit-tracker/ws');
}}

function connect() {{
  const url = getWsUrl();
  const dot = document.getElementById('ws-dot');
  const label = document.getElementById('ws-label');

  if (ws) {{ try {{ ws.close(); }} catch(e) {{}} }}
  label.textContent = 'Connecting...';
  dot.className = 'status-dot';

  try {{
    ws = new WebSocket(url);
  }} catch(e) {{
    label.textContent = 'Error: ' + e.message;
    setTimeout(connect, 5000);
    return;
  }}

  ws.onopen = () => {{
    dot.className = 'status-dot connected';
    label.textContent = 'Connected to ' + url.replace('wss://', '').replace('ws://', '').split('/')[0];
    ws.send(JSON.stringify(SUBSCRIBE_PAYLOAD));
  }};

  ws.onmessage = (ev) => {{
    try {{
      const msg = JSON.parse(ev.data);
      if (msg.event === 'schedule') {{
        trips = (msg.data || {{}}).trips || [];
      }}
    }} catch(e) {{}}
  }};

  ws.onclose = () => {{
    dot.className = 'status-dot';
    label.textContent = 'Disconnected';
    setTimeout(connect, 3000);
  }};

  ws.onerror = () => {{
    dot.className = 'status-dot';
    label.textContent = 'Connection error';
  }};
}}

// ---- Endpoint selector ----
document.getElementById('endpoint-select').addEventListener('change', (e) => {{
  const custom = document.getElementById('custom-url');
  custom.style.display = e.target.value === 'custom' ? 'inline-block' : 'none';
  connect();
}});
document.getElementById('custom-url').addEventListener('change', connect);

// ---- Start ----
connect();
requestAnimationFrame(renderFrame);
</script>
</body>
</html>"""
