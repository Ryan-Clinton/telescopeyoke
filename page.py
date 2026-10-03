"""The status page: tonight's report laid out as a small observatory console.

Everything about the night (verdict, timeline, targets, weather) is rendered
here once per rebuild. Everything that changes by the second (the imaging
run, the pictures, the system panel) is filled in by a little JavaScript from
status.json, which serve.py keeps fresh. The page is read-only on purpose.
"""
import html
import statistics
from datetime import timedelta
from pathlib import Path
from string import Template

import tonight

e = html.escape


def level(value, good, fair, higher_is_better=False):
    """'good', 'fair' or 'bad' for colouring a number."""
    if higher_is_better:
        return "good" if value >= good else "fair" if value >= fair else "bad"
    return "good" if value <= good else "fair" if value <= fair else "bad"


def condition(code):
    """7Timer's 1-8 seeing or transparency code in a word."""
    return "Good" if code <= 3 else "Average" if code <= 5 else "Poor"


# --- the strip of cards at the top ---------------------------------------------

def card(title, big, small="", tone=""):
    return (f'<div class="card {tone}"><div class="card-title">{e(title)}</div>'
            f'<div class="card-big">{e(big)}</div><div class="card-small">{e(small)}</div></div>')


def cards(rep):
    w, moon = rep["weather"], rep["moon"]
    out = []
    if w:
        tone = {"GO": "good", "MARGINAL": "fair", "NO-GO": "bad"}[w["verdict"]]
        out.append(card("Tonight", w["verdict"], f"average cloud {w['mean_cloud']}%", tone))
        if w["clear_hours"]:
            until = w["clear_to"] + timedelta(hours=1)
            out.append(card("Clear window", f"{w['clear_from']:%H:%M}–{until:%H:%M}",
                            f"{w['clear_hours']} hours"))
        else:
            out.append(card("Clear window", "none", "no clear hour forecast", "bad"))
    else:
        out.append(card("Tonight", "?", "no forecast available"))
    events = [f"{word} {t:%H:%M}" for t, word in ((moon["rise"], "rises"), (moon["set"], "sets")) if t]
    out.append(card("Moon", f"{moon['illumination']}% {'waxing' if moon['waxing'] else 'waning'}",
                    ", ".join(events) or "no rise or set tonight"))
    if w:
        gap = min(h["temp"] - h["dew_point"] for h in w["hours"])
        risk = "HIGH" if gap <= 2 else "MODERATE" if gap <= 4 else "LOW"
        damp = next((h for h in w["hours"] if h["temp"] - h["dew_point"] <= 2), None)
        small = f"from {damp['time']:%H:%M}; gap {gap:.1f}°C" if damp else f"smallest gap {gap:.1f}°C"
        out.append(card("Dew risk", risk, small, {"HIGH": "bad", "MODERATE": "fair", "LOW": "good"}[risk]))
    return "".join(out)


def conditions(rep):
    """One line under the cards: seeing, transparency, wind, sky brightness."""
    w, bits = rep["weather"], []
    if w:
        seeing = [h["seeing"] for h in w["hours"] if h["seeing"]]
        if seeing:
            clarity = [h["transparency"] for h in w["hours"] if h["transparency"]]
            bits.append(f"Seeing: {condition(statistics.median(seeing))}")
            bits.append(f"Transparency: {condition(statistics.median(clarity))}")
        bits.append(f"Wind: {statistics.median(h['wind'] for h in w['hours']):.0f} km/h, "
                    f"gusts to {max(h['gust'] for h in w['hours']):.0f}")
    lp = rep["light_pollution"]
    if lp:
        bits.append(f"Sky: {lp['sqm']:.2f} mag/arcsec² (about Bortle {lp['bortle']})")
    return " · ".join(bits)


# --- the night on one line -----------------------------------------------------

def timeline(rep):
    start, end = rep["sunset"], rep["sunrise"]
    if not (start and end and end > start):
        return ""
    span = (end - start).total_seconds()

    def at(t):
        return 100 * min(max((t - start).total_seconds() / span, 0), 1)

    def band(kind, a, b, label=""):
        if not (a and b) or b <= a:
            return ""
        return (f'<div class="band {kind}" style="left:{at(a):.2f}%;width:{at(b) - at(a):.2f}%" '
                f'title="{e(label)}"></div>')

    rows = []
    dark = band("dark", rep["dark_start"], rep["dark_end"],
                f"{rep['dark_level']} darkness {tonight.hm(rep['dark_start'])}–{tonight.hm(rep['dark_end'])}")
    rows.append(("Darkness", dark))
    moon = rep["moon"]
    up = ""
    if moon["up_at_sunset"]:
        up += band("moon", start, moon["set"] or end, "Moon up")
    if moon["rise"]:
        later_set = moon["set"] if moon["set"] and moon["set"] > moon["rise"] else end
        up += band("moon", moon["rise"], later_set, f"Moon up from {moon['rise']:%H:%M}")
    rows.append(("Moon up", up))
    w = rep["weather"]
    if w:
        cells = "".join(
            f'<div class="band cloud {level(h["cloud"], 25, 60)}" '
            f'style="left:{at(h["time"]):.2f}%;width:{at(h["time"] + timedelta(hours=1)) - at(h["time"]):.2f}%" '
            f'title="{h["time"]:%H:%M}: {h["cloud"]}% cloud">{h["cloud"]}</div>'
            for h in w["hours"] if start <= h["time"] < end)
        rows.append(("Cloud %", cells))
    hour = start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    ticks = ""
    while hour < end:
        ticks += f'<div class="tick" style="left:{at(hour):.2f}%">{hour:%H}</div>'
        hour += timedelta(hours=1)
    marker = ""
    if start <= rep["now"] <= end:
        marker = f'<div class="now" style="left:{at(rep["now"]):.2f}%" title="now"></div>'
    body = "".join(f'<div class="lane"><div class="lane-name">{name}</div>'
                   f'<div class="lane-track">{content}{marker}</div></div>'
                   for name, content in rows)
    return (f'<h2>The night</h2><div class="timeline">{body}'
            f'<div class="lane"><div class="lane-name"></div><div class="lane-track ticks">{ticks}</div></div>'
            f'<div class="dim">Sunset {start:%H:%M} · dark {tonight.hm(rep["dark_start"])}–'
            f'{tonight.hm(rep["dark_end"])} · sunrise {end:%H:%M}</div></div>')


# --- targets -------------------------------------------------------------------

def target_card(rank, t):
    name = f"{t['id']} {t['name']}".strip()
    tags = "".join(f'<span class="pill">{e(tag)}</span>' for tag in t["tags"])
    return (f'<div class="target"><div class="target-head"><span class="rank">{rank}</span>'
            f'<span class="target-name">{e(name)}</span>'
            f'<span class="score">{t["score"]:.0f}</span></div>'
            f'<div class="dim">{e(t["kind"])} · best {tonight.hm(t["best"])} · '
            f'{t["best_alt"]:.0f}° {t["direction"]} · {tonight.hm(t["start"])}–{tonight.hm(t["end"])}</div>'
            f'<div class="pills">{tags}</div></div>')


def best_targets(rep, count=5):
    """The few targets worth pointing at now, and the best still to come."""
    now = [t for t in rep["targets"] if t["now"]][:count]
    later = [t for t in rep["targets"] if not t["now"] and t["start"] > rep["now"]][:count]
    out = ""
    if now:
        out += "<h2>Best now</h2><div class='targets'>" + "".join(
            target_card(i, t) for i, t in enumerate(now, 1)) + "</div>"
    if later:
        title = "Later tonight" if now else "Best tonight"
        out += f"<h2>{title}</h2><div class='targets'>" + "".join(
            target_card(i, t) for i, t in enumerate(later, 1)) + "</div>"
    return out


def table(head, rows):
    """rows: lists of cells, each a string or a (string, css class) pair."""
    def cell(tag, c):
        text, css = c if isinstance(c, tuple) else (c, "")
        return f'<{tag} class="{css}">{e(text)}</{tag}>' if css else f"<{tag}>{e(text)}</{tag}>"
    body = "".join("<tr>" + "".join(cell("td", c) for c in r) + "</tr>" for r in rows)
    return ("<table><thead><tr>" + "".join(cell("th", c) for c in head)
            + f"</tr></thead><tbody>{body}</tbody></table>")


def weather_rows(w):
    rows = []
    for h in w["hours"]:
        plain = tonight.weather_row(h)
        gap = h["temp"] - h["dew_point"]
        plain[1] = (plain[1], level(h["cloud"], 25, 60))
        plain[3] = (plain[3], level(h["rain_chance"], 19, 49))
        plain[5] = (plain[5], level(gap, 4, 2, higher_is_better=True))
        plain[6] = (plain[6], level(h["gust"], 24, 34))
        rows.append(plain)
    return rows


# --- the page ------------------------------------------------------------------

PAGE = Template(r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="600">
<title>telescopeyoke</title>
<style>
  :root { --bg: #0b0d12; --panel: #141821; --line: #262c3a; --text: #d7dce6; --dim: #8a93a6;
          --good: #4cc38a; --fair: #e0b341; --bad: #e5636b; --accent: #6ea8fe; }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 18px 16px 40px; background: var(--bg); color: var(--text);
         font: 15px/1.5 system-ui, sans-serif; }
  main { max-width: 1180px; margin: 0 auto; }
  header { display: flex; justify-content: space-between; align-items: baseline; gap: 12px;
           flex-wrap: wrap; }
  h1 { font-size: 20px; margin: 0; letter-spacing: .02em; }
  h1 span { color: var(--dim); font-weight: 400; }
  h2 { font-size: 13px; margin: 26px 0 8px; color: var(--dim); text-transform: uppercase;
       letter-spacing: .08em; }
  .dim { color: var(--dim); font-size: 13px; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px;
           margin-top: 12px; }
  .card, .panel, .target { background: var(--panel); border: 1px solid var(--line);
                           border-radius: 8px; padding: 12px 14px; }
  .card-title { color: var(--dim); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }
  .card-big { font-size: 24px; font-weight: 700; line-height: 1.25; }
  .card-small { color: var(--dim); font-size: 13px; }
  .card.good .card-big, .good { color: var(--good); }
  .card.fair .card-big, .fair, .watch { color: var(--fair); }
  .card.bad .card-big, .bad, .poor { color: var(--bad); }
  .conditions { margin: 10px 2px 0; color: var(--dim); font-size: 14px; }

  .live { display: grid; grid-template-columns: minmax(300px, 5fr) 7fr; gap: 12px; align-items: start; }
  @media (max-width: 820px) { .live { grid-template-columns: 1fr; } }
  .run-head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
  .run-title { font-size: 18px; font-weight: 700; }
  .state { font-size: 12px; text-transform: uppercase; letter-spacing: .08em; color: var(--dim);
           white-space: nowrap; }
  .state.running { color: var(--good); }
  .state.running::before { content: "\25cf  "; }
  .bar { height: 10px; background: var(--line); border-radius: 5px; overflow: hidden; margin: 10px 0 4px; }
  .bar div { height: 100%; background: var(--accent); width: 0; transition: width .6s; }
  .figures { display: flex; flex-wrap: wrap; gap: 4px 16px; margin: 8px 0; }
  .figures b { font-size: 18px; }
  .metrics { display: grid; grid-template-columns: auto auto auto 1fr; gap: 4px 12px;
             align-items: center; margin-top: 8px; font-variant-numeric: tabular-nums; }
  .metrics .name { color: var(--dim); }
  .metrics .tag { font-size: 11px; letter-spacing: .08em; text-transform: uppercase; }
  .metrics svg { width: 100%; height: 26px; display: block; }
  .pills { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
  .pill { border: 1px solid var(--line); border-radius: 999px; padding: 1px 9px; font-size: 12px;
          color: var(--dim); white-space: nowrap; }
  figure { margin: 0; }
  figcaption { color: var(--dim); font-size: 13px; margin-bottom: 6px; }
  figcaption b { color: var(--text); letter-spacing: .06em; }
  img { max-width: 100%; border-radius: 8px; border: 1px solid var(--line); display: block; }

  .targets { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 10px; }
  .target-head { display: flex; gap: 8px; align-items: baseline; }
  .rank { color: var(--dim); }
  .target-name { font-weight: 700; flex: 1; }
  .score { color: var(--accent); font-weight: 700; }

  .timeline { background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
              padding: 12px 14px; }
  .lane { display: grid; grid-template-columns: 76px 1fr; align-items: center; margin: 3px 0; }
  .lane-name { color: var(--dim); font-size: 12px; }
  .lane-track { position: relative; height: 20px; background: #0e1118; border-radius: 4px; overflow: hidden; }
  .lane-track.ticks { background: none; height: 16px; overflow: visible; }
  .band { position: absolute; top: 0; bottom: 0; font-size: 11px; text-align: center;
          line-height: 20px; color: #0b0d12; overflow: hidden; }
  .band.dark { background: #33415e; }
  .band.moon { background: #c9c3a5; }
  .band.cloud.good { background: var(--good); }
  .band.cloud.fair { background: var(--fair); }
  .band.cloud.bad { background: var(--bad); }
  .tick { position: absolute; transform: translateX(-50%); color: var(--dim); font-size: 11px; }
  .now { position: absolute; top: 0; bottom: 0; width: 2px; background: #fff; }

  .system { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 2px 18px; }
  .system div { display: flex; justify-content: space-between; gap: 10px;
                border-bottom: 1px solid var(--line); padding: 3px 0; }
  .system span:first-child { color: var(--dim); }
  .gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 12px; }
  .gallery a { color: var(--text); text-decoration: none; font-size: 13px; }
  .gallery a:hover { text-decoration: underline; }
  .gallery img { width: 100%; aspect-ratio: 3 / 2; object-fit: cover; margin-bottom: 4px; }
  .gallery span { color: var(--dim); display: block; }
  details { margin-top: 22px; }
  summary { cursor: pointer; color: var(--dim); font-size: 13px; text-transform: uppercase;
            letter-spacing: .08em; }
  .scroll { overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; margin-top: 8px; }
  table { border-collapse: collapse; width: 100%; background: var(--panel);
          font-variant-numeric: tabular-nums; white-space: nowrap; }
  th, td { padding: 5px 10px; text-align: left; border-bottom: 1px solid var(--line); }
  th { color: var(--dim); font-weight: 600; font-size: 13px; }
  tr:last-child td { border-bottom: 0; }
  #moving { border-color: var(--fair); }
  #moving h2 { margin-top: 0; color: var(--fair); }
</style></head><body><main>
<header>
  <h1>telescopeyoke <span>— $site</span></h1>
  <div class="dim">night of $date · report made $generated · <span id="clock"></span></div>
</header>
<div class="cards">$cards</div>
<div class="conditions">$conditions</div>

<div id="moving" class="panel" hidden style="margin-top:16px">
  <h2>Mount moving</h2>
  <img data-live="scope.jpg" alt="The telescope, from the webcam">
</div>

<div id="live-section" hidden>
  <h2>Imaging</h2>
  <div class="live">
    <div class="panel" id="run" hidden>
      <div class="run-head"><div class="run-title" id="run-title"></div>
        <div class="state" id="run-state"></div></div>
      <div class="bar"><div id="run-bar"></div></div>
      <div class="dim" id="run-count"></div>
      <div class="figures" id="run-figures"></div>
      <div class="metrics" id="run-metrics"></div>
      <div class="pills" id="run-pills"></div>
      <div class="dim" id="run-last" style="margin-top:8px"></div>
    </div>
    <figure id="stack" hidden>
      <figcaption><b id="stack-kind"></b> <span id="stack-detail"></span></figcaption>
      <img data-live="latest.jpg" alt="The newest picture through the telescope">
    </figure>
  </div>
</div>

<div id="pictures" hidden>
  <h2>Pictures</h2>
  <div class="gallery" id="gallery"></div>
</div>

$best
$timeline

<h2>System</h2>
<div class="panel"><div class="system" id="system"><div><span>Waiting for status…</span></div></div></div>

<details><summary>All $count ranked targets</summary>
<div class="scroll">$targets</div>
<p class="dim">Sky is the background brightness at each target's best time, including moonlight;
higher is darker.</p></details>

<details open><summary>Weather hour by hour</summary>
<div class="scroll">$weather</div></details>

$clouds
$scope
<p class="dim" style="margin-top:24px">Weather: Open-Meteo. Seeing: 7Timer. Light pollution: D. Lorenz
atlas. Comets: COBS and JPL Horizons. Cloud imagery: EUMETSAT. Catalogue: OpenNGC (CC-BY-SA-4.0).</p>
</main>
<script>
  const $$ = id => document.getElementById(id);
  const make = (tag, text, css) => {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (css) el.className = css;
    return el;
  };
  function ago(seconds) {
    if (seconds == null) return "never";
    if (seconds < 90) return Math.round(seconds) + " s ago";
    if (seconds < 5400) return Math.round(seconds / 60) + " min ago";
    return Math.round(seconds / 3600) + " h ago";
  }

  // A tiny line graph of recent values; gaps where a frame had no reading.
  function sparkline(values, rejected) {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 120 26");
    svg.setAttribute("preserveAspectRatio", "none");
    const real = values.filter(v => v != null);
    if (real.length < 2) return svg;
    const low = Math.min(...real), high = Math.max(...real), range = (high - low) || 1;
    const step = 120 / Math.max(values.length - 1, 1);
    let path = "", pen = false;
    values.forEach((v, i) => {
      if (v == null) { pen = false; return; }
      path += (pen ? "L" : "M") + (i * step).toFixed(1) + " " + (23 - 20 * (v - low) / range).toFixed(1);
      pen = true;
    });
    const line = document.createElementNS(ns, "path");
    line.setAttribute("d", path);
    line.setAttribute("fill", "none");
    line.setAttribute("stroke", "#6ea8fe");
    line.setAttribute("stroke-width", "1.5");
    line.setAttribute("vector-effect", "non-scaling-stroke");
    svg.append(line);
    rejected.forEach((bad, i) => {
      if (!bad) return;
      const mark = document.createElementNS(ns, "rect");
      mark.setAttribute("x", (i * step - 0.6).toFixed(1));
      mark.setAttribute("y", "24");
      mark.setAttribute("width", "1.2");
      mark.setAttribute("height", "2");
      mark.setAttribute("fill", "#e5636b");
      svg.append(mark);
    });
    return svg;
  }

  function showRun(run) {
    if (!run.name || !run.captured) return false;
    $$("run-title").textContent = run.title || run.name;
    const running = !run.finished && run.age <= 180;
    const state = run.restacked ? "finished" : run.finished ? "making the final picture"
      : running ? "running" : "paused " + ago(run.age).replace(" ago", "");
    $$("run-state").textContent = state;
    $$("run-state").className = "state" + (running ? " running" : "");
    const share = run.planned ? Math.min(100, 100 * run.captured / run.planned) : 100;
    $$("run-bar").style.width = share + "%";
    $$("run-count").textContent = run.captured + (run.planned ? " of " + run.planned : "") + " frames"
      + (run.exposure ? " of " + run.exposure + " s" : "");
    const figures = [[run.accepted, "accepted"], [run.rejected, "rejected"]];
    if (run.integration != null) figures.push([run.integration + " s", "integration"]);
    figures.push([Math.round(100 * run.accepted / run.captured) + "%", "kept"]);
    $$("run-figures").replaceChildren(...figures.map(([value, label]) => {
      const item = make("span");
      item.append(make("b", String(value)), " " + label);
      return item;
    }));
    const rows = [];
    if (run.latest) {
      const series = run.series || {};
      const rejected = (series.accepted || []).map(ok => !ok);
      [["FWHM", "fwhm", " px"], ["Roundness", "roundness", ""], ["Stars", "stars", ""],
       ["Drift", "drift", "% of frame"], ["Rotation", "rotation", "°"]].forEach(([label, key, unit]) => {
        const [value, verdict] = run.latest[key];
        rows.push(make("span", label, "name"), make("span", value + unit),
                  make("span", verdict, "tag " + verdict),
                  series[key] ? sparkline(series[key], rejected) : make("span"));
      });
    }
    $$("run-metrics").replaceChildren(...rows);
    $$("run-pills").replaceChildren(...Object.entries(run.reasons || {}).map(
      ([why, n]) => make("span", n + " " + why, "pill")));
    $$("run-last").textContent = run.last ? "Newest frame " + ago(run.age) + ": " + run.last : "";
    $$("run").hidden = false;
    return true;
  }

  function showImage(image) {
    if (!image) return false;
    $$("stack-kind").textContent = image.kind.toUpperCase();
    $$("stack-detail").textContent = [image.detail, ago(image.age)].filter(Boolean).join(" · ");
    $$("stack").hidden = false;
    return true;
  }

  let shownPictures = "";
  function showPictures(pictures) {
    const key = JSON.stringify(pictures.map(p => [p.file, Math.round(p.time)]));
    if (!pictures.length || key === shownPictures) return;
    shownPictures = key;
    $$("gallery").replaceChildren(...pictures.map(p => {
      const link = make("a");
      link.href = p.file;
      link.target = "_blank";
      const thumb = make("img");
      thumb.src = p.file + "?t=" + Math.round(p.time);
      thumb.loading = "lazy";
      thumb.alt = (p.target + " " + p.kind).trim();
      const when = new Date(p.time * 1000).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
      link.append(thumb, p.target || "Comparison", make("span", p.kind + " · " + when));
      return link;
    }));
    $$("pictures").hidden = false;
  }

  function showSystem(system) {
    if (!system) return;
    $$("system").replaceChildren(...system.map(item => {
      const row = make("div");
      row.append(make("span", item.label), make("span", item.text, item.level));
      return row;
    }));
  }

  async function refresh() {
    $$("clock").textContent = new Date().toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"});
    let status;
    try {
      status = await (await fetch("status.json?t=" + Date.now())).json();
    } catch (error) {
      return;
    }
    const run = showRun(status), image = showImage(status.image);
    $$("live-section").hidden = !(run || image);
    showPictures(status.pictures || []);
    showSystem(status.system);
    // The webcam comes to the top while the mount is slewing.
    $$("moving").hidden = !(status.scope_age != null && status.scope_age < 20);
  }
  refresh();
  setInterval(refresh, 2000);

  // Reload the telescope pictures without reloading the whole page.
  setInterval(() => {
    for (const img of document.querySelectorAll("img[data-live]")) {
      if (img.offsetParent !== null) img.src = img.dataset.live + "?t=" + Date.now();
    }
  }, 1500);
</script>
</body></html>
""")


def render(rep, top, out_dir):
    w = rep["weather"]
    clouds = ""
    if (out_dir / "clouds.jpg").exists():
        clouds = ('<h2>Cloud from the satellite (bright = cloud, dark = clear)</h2>'
                  '<img src="clouds.jpg" alt="Infrared satellite image of cloud over the site">')
    scope = ""
    if (out_dir / "scope.jpg").exists():
        scope = ('<h2>The telescope (webcam, updates during slews)</h2>'
                 '<img src="scope.jpg" data-live="scope.jpg" alt="View of the telescope">')
    shown = rep["targets"][:top]
    return PAGE.substitute(
        site=e(rep["site"]), date=f"{rep['date']:%A %d %B %Y}",
        generated=f"{rep['generated']:%H:%M}",
        cards=cards(rep), conditions=e(conditions(rep)),
        best=best_targets(rep), timeline=timeline(rep), count=len(shown),
        targets=table(tonight.TARGET_HEAD, [tonight.target_row(i, t) for i, t in enumerate(shown, 1)]),
        weather=table(tonight.WEATHER_HEAD, weather_rows(w)) if w
        else "<p class='dim'>No forecast available.</p>",
        clouds=clouds, scope=scope)


def write(rep, top, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(rep, top, path.parent))
