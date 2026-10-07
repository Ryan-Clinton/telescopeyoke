// The console's page. It shows what console.py reports and sends what the
// person presses; it decides nothing about the telescope. No inline styles
// (the page's security headers forbid them): things are shown and hidden with
// the `hidden` attribute and classes, and drawn with SVG attributes.
"use strict";

// The key comes in the address once, and is taken out of it at once so that
// it is not left in the history, a bookmark or a screenshot.
const KEY = new URLSearchParams(location.search).get("key") || sessionStorage.getItem("key") || "";
sessionStorage.setItem("key", KEY);
history.replaceState(null, "", location.pathname + location.hash);

const $ = (id) => document.getElementById(id);
const SVG = "http://www.w3.org/2000/svg";
const STALE = 600;   // seconds after which an old measurement is taken off the bar

const seen = { state: null, night: null, targets: null, observing: null, session: null, job: null,
               doctor: null, focus: null, catalogue: null, horizon: null, report: null, system: null, gallery: null, rigs: null, characterise: null,
               polar: null, landmarks: null };
let task = "home", chosen = null, filter = null, plan = null, trail = [], lastJobId = null;
let unread = 0, logged = new Set();

// --- small helpers --------------------------------------------------------

function el(tag, attrs, ...children) {
  const svg = ["svg", "polyline", "circle", "rect", "line", "text", "path"].includes(tag);
  const node = svg ? document.createElementNS(SVG, tag) : document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === false || value == null) continue;
    if (key === "text") node.textContent = value;
    else if (key === "on") for (const [event, handler] of Object.entries(value)) node.addEventListener(event, handler);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) if (child != null) node.append(child);
  return node;
}

function fill(node, ...children) { node.replaceChildren(...children.flat().filter((c) => c != null)); }

async function ask(path, body) {
  const options = { headers: { "X-Console-Key": KEY } };
  if (body !== undefined) Object.assign(options, { method: "POST", body: JSON.stringify(body) });
  try {
    const reply = await fetch(path, options);
    return await reply.json();
  } catch (problem) {
    return { ok: false, data: {}, errors: [{ code: "INTERNAL_ERROR", message: "The console is not answering. Is console.py still running?" }] };
  }
}

const clockTime = (when) => new Date(when).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
const hms = (seconds) => new Date(seconds * 1000).toLocaleTimeString([], { hour12: false });
function age(seconds) {
  if (seconds == null) return "";
  if (seconds < 90) return `${Math.round(seconds)} s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  return `${Math.round(seconds / 3600)} h ago`;
}

function notice(text, kind) {
  const node = el("div", { class: `notice ${kind || ""}`, text });
  $("notices").append(node);
  setTimeout(() => node.remove(), kind === "failed" ? 12000 : 6000);
}

function spark(node, values, flags) {
  const points = values.map((v, i) => [i, v]).filter(([, v]) => v != null);
  if (points.length < 2) return fill(node);
  const [w, h] = node.getAttribute("viewBox").split(" ").slice(2).map(Number);
  const low = Math.min(...points.map(([, v]) => v)), high = Math.max(...points.map(([, v]) => v));
  const x = (i) => (i / (values.length - 1)) * w, y = (v) => h - 3 - ((v - low) / (high - low || 1)) * (h - 6);
  fill(node, el("polyline", { points: points.map(([i, v]) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ") }),
       (flags || []).map((ok, i) => (ok === false && values[i] != null) ? el("circle", { cx: x(i), cy: y(values[i]), r: 1.6 }) : null));
}

// --- what may be pressed, and why not ----------------------------------------

function unavailable(needs) {
  const state = seen.state;
  if (!state) return "Waiting for the console.";
  const caps = state.capabilities, parts = caps.components || {};
  const failing = (...names) => names.map((n) => parts[n]).find((p) => p && p.status === "fail");
  if (needs === "mount" || needs === "imaging") {
    if (caps.motion.locked && needs === "mount") return `Motion is locked: ${caps.motion.lock_reason}`;
    const bad = failing("serial_access", "mount_lead");
    if (bad) return bad.message;
  }
  if (needs === "camera" || needs === "imaging") {
    const bad = failing("camera_transport", "camera");
    if (bad) return bad.message;
  }
  if (needs === "imaging") {
    const bad = failing("plate_solver", "star_database");
    if (bad) return bad.message;
  }
  return null;
}

function gate(button, action, needs) {
  // A control that cannot be used says why, beside it. Never a bare grey button.
  const state = seen.state;
  let why = unavailable(needs);
  if (state && state.demo && action && !state.available.includes(action)) why = "Not in the demo: it tests or sets up real equipment.";
  const running = seen.job && seen.job.running;
  if (!why && running && action !== "stop") why = `Busy: ${running.label} is running.`;
  button.disabled = !!why;
  let note = button.nextElementSibling;
  if (!note || !note.classList.contains("why")) {
    note = el("span", { class: "why" });
    button.after(note);
  }
  note.hidden = !why;
  note.textContent = why ? `${button.textContent.trim()}: ${why}` : "";
}

function gateAll() {
  for (const button of document.querySelectorAll("button[data-needs]")) {
    gate(button, button.dataset.plan || button.dataset.action || button.dataset.gate, button.dataset.needs);
  }
}

// --- acting -------------------------------------------------------------------

async function act(action, params) {
  const reply = await ask(`/api/action/${action}`, params || {});
  if (!reply.ok) notice(reply.errors[0].message, "failed");
  else notice(`${reply.data.job.label} started`);
  refresh();
}

async function makePlan(action, params) {
  const reply = await ask(`/api/plan/${action}`, params || {});
  if (!reply.ok) return showOutcome("failed", "Could not plan", reply.errors[0]);
  if (reply.data.refused) return showOutcome("refused", "Plan refused", reply.data.refused);
  showPlan(reply.data);
}

async function confirmPlan() {
  const reply = await ask(`/api/confirm/${plan.id}`, {});
  if (!reply.ok) return showOutcome("failed", "Not started", reply.errors[0]);
  if (reply.data.refused) return showOutcome("refused", "Plan refused", reply.data.refused);
  if (reply.data.changed) {
    notice(reply.data.message, "refused");
    return showPlan(reply.data);
  }
  closeCard();
  notice(`${reply.data.job.label} started`);
  refresh();
}

async function stop() {
  $("stop").disabled = true;
  const reply = await ask("/api/stop", {});
  $("stop").disabled = false;
  if (reply.ok && reply.data.stopped) notice(`Mount stopped in ${reply.data.seconds} s`);
  else notice(`Stop did not get an answer from the mount: ${(reply.data.error || reply.errors[0] || {}).message || ""}`, "failed");
  closeCard();
  refresh();
}

// --- the move plan ---------------------------------------------------------------

function closeCard() {
  plan = null;
  $("plan").hidden = $("shade").hidden = $("sheet").hidden = true;
}

function planLines(data) {
  const p = data.plan, move = p.goto || p, limits = seen.state.capabilities.motion.limits, lines = [];
  const facts = el("dl", { class: "facts" });
  const fact = (name, value) => facts.append(el("dt", { text: name }), el("dd", { text: value }));
  if (move.altitude_deg != null) fact("Height at the end", `${move.altitude_deg}°`);
  if (move.hour_angle_hours != null) fact("Hour angle", `${move.hour_angle_hours > 0 ? "+" : ""}${move.hour_angle_hours} h`);
  if (move.pier_side) fact("Side of the mount", move.pier_side.toUpperCase());
  if (seen.job.position) fact("Mount now", `RA ${seen.job.position.ra_hours} h, Dec ${seen.job.position.dec_deg}° (read ${age(Date.now() / 1000 - seen.job.position.read)})`);
  const checks = el("ul");
  if (move.altitude_deg != null) {
    checks.append(el("li", { class: "ok", text: `Above the ${limits.min_altitude_deg}° altitude limit` }),
                  el("li", { class: "ok", text: `Within ${limits.max_hour_angle_hours} h of the meridian` }),
                  el("li", { class: "ok", text: `More than ${limits.sun_exclusion_deg}° from the Sun, or the Sun is down` }));
  }
  for (const warning of new Set([...(p.warnings || []), ...(move.warnings || [])])) checks.append(el("li", { class: "caution", text: warning }));
  if (p.says) checks.append(el("li", { class: "caution", text: p.says }));
  if (data.action === "run") {
    lines.push(el("p", { class: "quiet", text: "Before imaging" }),
               el("p", { text: p.would_move ? `The telescope slews to ${p.target}, plate-solves and centres it.` : "The mount will not be moved." }),
               el("p", { class: "quiet", text: "During imaging" }),
               el("p", { text: p.would_move ? `It may re-centre ${p.target} when it has drifted more than 20% of the frame.` : "The mount will not be moved." }),
               el("p", { text: $("run-assist").checked ? "Drift assist will adjust the Dec motor." : "Drift assist is off; switching it on during the run adjusts the Dec motor." }),
               el("p", { class: "quiet", text: "Capture" }),
               el("p", { text: `${p.frames} frames · ${p.exposure === "auto" ? "exposure chosen from the tracking" : p.exposure + " s each"} · gain ${p.gain}` }));
  }
  return [facts, ...lines, checks];
}

function showPlan(data) {
  plan = data;
  // The webcam's picture is always tried; with no webcam it fails to load and is taken out.
  const picture = el("img", { src: "/pictures/scope.jpg", alt: "" });
  const beside = el("div", { class: "scope" }, picture, el("div", { class: "quiet", text: "The telescope, from the webcam" }));
  picture.addEventListener("error", () => beside.remove());
  const cancel = el("button", { type: "button", text: "Cancel", on: { click: closeCard } });
  fill($("plan"),
       el("div", { class: "kind", text: data.action === "run" ? "IMAGING PLAN" : "MOVE PLAN" }),
       el("h3", { text: data.label }),
       el("div", { class: "body" }, el("div", {}, planLines(data)), beside),
       el("div", { class: "buttons" }, cancel,
          el("button", { type: "button", class: "confirm", text: data.label.toUpperCase(), on: { click: confirmPlan } })));
  $("plan").className = "card";
  $("sheet").hidden = true;
  $("plan").hidden = $("shade").hidden = false;
  cancel.focus();   // never Confirm: Enter must not move the mount
}

function showOutcome(kind, title, error) {
  plan = null;
  const close = el("button", { type: "button", text: "Close", on: { click: closeCard } });
  fill($("plan"), el("div", { class: "kind", text: title.toUpperCase() }),
       el("h3", { text: error.message || "" }),
       error.advice ? el("p", { class: "quiet", text: error.advice }) : null,
       el("div", { class: "buttons" }, close));
  $("plan").className = `card ${kind}`;
  $("sheet").hidden = true;
  $("plan").hidden = $("shade").hidden = false;
  close.focus();
  record({ time: Date.now() / 1000, text: `${title}: ${error.message}`, kind });
}

// --- the frame -------------------------------------------------------------------

function mode() {
  // What is happening now decides the right-hand panel and the main controls.
  const running = seen.job && seen.job.running, imaging = seen.state && seen.state.imaging;
  if (running && ["goto", "home", "zenith", "compensate", "horizon", "drift"].includes(running.action)) return "moving";
  if (running && running.action === "focus") return "focusing";
  if ((running && running.action === "run") || (imaging && imaging.state === "capturing")) return "imaging";
  return "idle";
}

function drawTop() {
  const state = seen.state, night = seen.night;
  if (!state) return;
  $("site").textContent = [state.rig, state.site].filter(Boolean).join(" · ");
  $("demo").hidden = $("demo-mount").hidden = !state.demo;
  if (night) {
    // The same words as the Clear window card, when the report has arrived.
    const card = seen.report && seen.report.cards.find((c) => c.title === "Clear window");
    const until = card ? ` · clear ${card.big}` : night.clear_window ? ` · clear ${clockTime(night.clear_window[0])} to ${clockTime(night.clear_window[1])}` : "";
    $("verdict").textContent = `${night.verdict}${until}`;
    $("verdict").className = `verdict ${night.verdict === "GO" ? "good" : night.verdict === "NO-GO" ? "bad" : "warn"}`;
  }
  const word = (name, value) => el("span", {}, `${name} `, el("b", { text: (value || "unknown").toUpperCase() }));
  fill($("top-states"), word("Mount", state.mount.state), word("Camera", state.camera.state));
  $("clock").textContent = new Date().toLocaleTimeString([], { hour12: false });
}

function drawBottom() {
  const state = seen.state, run = seen.session;
  if (!state) return;
  const bits = [["Mount", state.mount.state], ["Camera", state.camera.state], ["Solver", state.solver.state]]
    .map(([name, value]) => el("span", {}, `${name} `, el("b", { text: (value || "unknown").toUpperCase() })));
  // A measurement is shown bare only while its job runs; then with its age;
  // then not at all. A number from twenty minutes ago must not look like now.
  if (run && run.latest && run.age != null && run.age < STALE) {
    const live = mode() === "imaging" && run.age < 60, old = live ? "" : ` · ${age(run.age)}`;
    bits.push(el("span", {}, "FWHM ", el("b", { text: run.latest.fwhm[0] }), old),
              el("span", {}, el("b", { text: run.latest.stars[0] }), ` stars${old}`));
  }
  const focus = seen.focus && seen.focus.reading;
  if (focus && focus.age_s < STALE) bits.push(el("span", {}, "Focus HFR ", el("b", { text: focus.hfr }), mode() === "focusing" ? "" : ` · ${age(focus.age_s)}`));
  const solve = state.mount.last_plate_solve_age_s;
  if (solve != null && solve < STALE) bits.push(el("span", {}, `Plate solve ${age(solve)}`));
  fill($("statusline"), bits);
}

function drawRail() {
  const now = mode(), job = seen.job && seen.job.running, run = seen.session, best = bestNow();
  const button = (text, handler, extra) => el("button", Object.assign({ type: "button", text, on: { click: handler } }, extra || {}));
  if (now === "moving") {
    return fill($("rail"), el("div", { class: "quiet", text: "MOVING" }), el("div", { class: "name", text: job.label }),
                el("p", { text: `${Math.round(Date.now() / 1000 - job.started)} s so far` }),
                el("p", { class: "quiet", text: job.lines.length ? job.lines[job.lines.length - 1].text : "" }),
                el("div", { class: "buttons" }, button("STOP", stop, { class: "stop" })));
  }
  if (now === "focusing") {
    const reading = (seen.focus && (seen.focus.live || seen.focus.reading)) || {};
    return fill($("rail"), el("div", { class: "quiet", text: "FOCUSING" }), el("div", { class: "big", text: reading.hfr ?? "–" }),
                el("p", { class: "quiet", text: reading.best_hfr ? `Best ${reading.best_hfr}` : "" }),
                el("div", { class: "buttons" }, button("Finish focusing", finish)));
  }
  if (now === "imaging" && run) {
    const share = run.captured ? Math.round(100 * run.accepted / run.captured) : 0;
    return fill($("rail"), el("div", { class: "name", text: run.title || run.name }),
                el("div", { class: "good word", text: "IMAGING" }),
                el("p", { class: "big", text: `${run.captured}${run.planned ? " / " + run.planned : ""}` }),
                run.planned ? el("progress", { max: run.planned, value: run.captured }) : null,
                el("p", { text: `${run.integration ?? 0} s kept · ${share}% kept` }),
                el("p", { class: "quiet", text: `Exposure ${run.exposure} s` }),
                // Orders that move the mount are offered only in a run started here with re-centring.
                el("div", { class: "buttons" }, button("Finish run", () => act("run-finish")),
                   ...(seen.job.run_scope && seen.job.run_scope.mount
                     ? [button("Re-centre", () => act("run-recentre")), button("Drift assist on", () => act("run-assist-on")),
                        button("Drift assist off", () => act("run-assist-off"))]
                     : [el("p", { class: "quiet", text: seen.job.run_scope ? "Started without re-centring: this run does not move the mount."
                                                                           : "This run was started from a terminal, so only Finish is offered here." })])));
  }
  const nodes = [el("div", { class: "quiet", text: job ? "WORKING" : "NO RUN" })];
  if (job) nodes.push(el("div", { class: "name", text: job.label }), el("div", { class: "buttons" }, button("Finish", finish)));
  else if (best) {
    nodes.push(el("p", { class: "quiet", text: "Best now" }), el("div", { class: "name", text: `${best.id} ${best.name || ""}` }),
               el("p", { text: `${best.best_altitude_deg}° ${best.direction}` }));
    const go = button(`Go to ${best.id}`, () => makePlan("goto", { target: best.id }), { "data-needs": "mount", "data-gate": "goto" });
    const image = button("Start imaging", () => openSheet(best.id), { "data-needs": "imaging", "data-gate": "run" });
    nodes.push(el("div", { class: "buttons" }, go, image));
  } else nodes.push(el("p", { class: "quiet", text: "Nothing is well placed just now. Choose from Targets." }));
  fill($("rail"), nodes);
  gateAll();
}

async function finish() {
  const reply = await ask("/api/finish", {});
  if (!reply.ok) notice(reply.errors[0].message, "failed");
  refresh();
}

// --- home ---------------------------------------------------------------------

function bestNow() {
  const list = (seen.targets && seen.targets.targets) || [];
  return list.find((t) => t.observable_now) || null;
}

// A picture is fetched again every ten seconds: the address changes, so the
// browser asks; the console ignores what follows the "?".
function picture(node, name) {
  const src = `/pictures/${name}?v=${Math.floor(Date.now() / 10000)}`;
  if (node.getAttribute("src") !== src) node.setAttribute("src", src);
}

function showOnlyIfThere(image, part) {
  // A picture that is not there (no webcam, no satellite image yet) takes its heading with it.
  image.addEventListener("error", () => { part.hidden = true; });
  image.addEventListener("load", () => { part.hidden = false; });
}

function targetCard(t, rank) {
  return el("div", { class: "target", on: { click: () => { choose(t.id); show("targets"); } } },
            el("div", { class: "head" }, el("span", { class: "rank", text: rank }),
               el("span", { class: "name", text: `${t.id} ${t.name || ""}`.trim() }), el("span", { class: "score", text: t.score })),
            el("div", { class: "quiet", text: `${t.kind} · best ${clockTime(t.best)} · ${t.best_alt}° ${t.direction} · ${clockTime(t.start)}–${clockTime(t.end)}` }),
            el("div", { class: "tags", text: (t.tags || []).join(" · ") }),
            el("button", { type: "button", text: "Go to", "data-needs": "mount", "data-gate": "goto",
                           on: { click: (event) => { event.stopPropagation(); makePlan("goto", { target: t.id }); } } }));
}

function drawTimeline(report) {
  const night = report.night, moon = report.moon, svg = $("timeline");
  const start = new Date(night.sunset).getTime(), end = new Date(night.sunrise).getTime();
  if (!(end > start)) return fill(svg);
  const left = 70, width = 820, at = (t) => left + width * Math.min(Math.max((new Date(t).getTime() - start) / (end - start), 0), 1);
  const parts = [], lanes = [["Darkness", 4], ["Moon up", 30], ["Cloud %", 56]];
  for (const [name, y] of lanes) parts.push(el("text", { x: 0, y: y + 14, text: name }), el("rect", { class: "lane", x: left, y, width, height: 20 }));
  const band = (kind, y, a, b) => { if (a && b && new Date(b) > new Date(a)) parts.push(el("rect", { class: kind, x: at(a), y, width: Math.max(1, at(b) - at(a)), height: 20 })); };
  band("dark", 4, night.dark_start, night.dark_end);
  if (moon.up_at_sunset) band("moon", 30, night.sunset, moon.set || night.sunrise);
  if (moon.rise) band("moon", 30, moon.rise, moon.set && new Date(moon.set) > new Date(moon.rise) ? moon.set : night.sunrise);
  for (const hour of report.hours) {
    const from = new Date(hour.time).getTime();
    if (from < start || from >= end) continue;
    const x = at(from), w = at(from + 3600000) - x;
    parts.push(el("rect", { class: hour.level, x, y: 56, width: Math.max(1, w - 1), height: 20 }),
               el("text", { class: "cell-text", x: x + w / 2 - 6, y: 70, text: hour.cloud }));
  }
  for (let t = Math.ceil(start / 3600000) * 3600000; t < end; t += 3600000) {
    parts.push(el("text", { x: at(t) - 6, y: 96, text: String(new Date(t).getHours()).padStart(2, "0") }));
  }
  const now = Date.now();
  if (now >= start && now <= end) parts.push(el("rect", { class: "now", x: at(now), y: 0, width: 2, height: 80 }));
  fill(svg, parts);
  $("night-words").textContent = `Sunset ${clockTime(night.sunset)} · ${night.dark_level} dark ${clockTime(night.dark_start)}–${clockTime(night.dark_end)} · sunrise ${clockTime(night.sunrise)}. The white mark is now.`;
}

function table(head, rows, pick) {
  const cell = (tag, c) => Array.isArray(c) ? el(tag, { class: c[1], text: c[0] }) : el(tag, { text: c });
  return el("table", {}, el("thead", {}, el("tr", {}, head.map((h) => cell("th", h)))),
            el("tbody", {}, rows.map((row, i) => el("tr", pick ? { class: "pick", on: { click: () => pick(i) } } : {}, row.map((c) => cell("td", c))))));
}

function drawHome() {
  const watch = seen.observing, report = seen.report;
  if (watch) {
    const notes = watch.notes || [], run = watch.imaging || {}, alert = notes.length > 0;
    const reasons = [];
    if (!alert) {
      if (watch.optics && watch.optics.focus_state === "good") reasons.push("Focus is near tonight's best.");
      if (run.acceptance_rate != null) reasons.push(`${Math.round(100 * run.acceptance_rate)}% of frames are being kept.`);
      if (watch.sky && watch.sky.verdict) reasons.push(`The sky: ${watch.sky.verdict}, ${watch.sky.cloud_percent}% cloud.`);
    }
    const trend = run.trend ? el("p", { class: "quiet", text: `FWHM ${run.trend.fwhm_change_percent >= 0 ? "+" : ""}${run.trend.fwhm_change_percent}% · stars ${run.trend.stars_change_percent >= 0 ? "+" : ""}${run.trend.stars_change_percent}%` }) : null;
    const remedy = alert && notes.join(" ").includes("focus")
      ? el("button", { type: "button", text: "Start focusing", on: { click: () => show("focus") } })
      : alert ? el("button", { type: "button", text: "Look at the newest frame", on: { click: () => show("imaging") } }) : null;
    fill($("attention"), el("div", { class: `title ${alert ? "warn" : "good"}`, text: alert ? "ATTENTION" : "EVERYTHING LOOKS GOOD" }),
         el("ul", {}, (alert ? notes : reasons).map((text) => el("li", { text }))), alert ? trend : null, remedy);
    $("attention").className = `attention ${alert ? "alert" : ""}`;
  }
  if (!report) return;
  fill($("cards"), report.cards.map((c) => el("div", {}, el("div", { class: "title", text: c.title }),
       el("div", { class: `big ${c.tone === "fair" ? "warn" : c.tone}`, text: c.big }), el("div", { class: "quiet", text: c.small }))));
  $("conditions").textContent = report.conditions;
  const now = report.targets.filter((t) => t.now).slice(0, 5);
  const later = report.targets.filter((t) => !t.now && new Date(t.start) > new Date()).slice(0, 5);
  $("best-title").hidden = $("best").hidden = !now.length;
  fill($("best"), now.map((t, i) => targetCard(t, i + 1)));
  $("later-title").textContent = now.length ? "Later tonight" : "Best tonight";
  $("later-title").hidden = $("later").hidden = !later.length;
  fill($("later"), later.map((t, i) => targetCard(t, i + 1)));
  drawTimeline(report);
  if (!$("ranked-table").firstChild || $("ranked-table").dataset.made !== String(report.targets.length)) {
    fill($("ranked-table"), table(report.target_head, report.targets.map((t) => t.row), (i) => { choose(report.targets[i].id); show("targets"); }));
    $("ranked-table").dataset.made = String(report.targets.length);
    fill($("weather-table"), table(report.weather_head, report.weather_rows));
  }
  picture($("clouds"), "clouds.jpg");
  gateAll();
}

function targetRow(t, first) {
  const go = el("button", { type: "button", text: "Go to", "data-needs": "mount", "data-gate": "goto",
                           on: { click: (event) => { event.stopPropagation(); makePlan("goto", { target: t.id }); } } });
  return el("div", { class: `row pick ${first ? "first" : ""}`, on: { click: () => { choose(t.id); show("targets"); } } },
            el("span", { class: "id", text: t.id }),
            el("span", { class: "what", text: [t.name, t.kind, t.best_altitude_deg != null ? `${t.best_altitude_deg}° ${t.direction}` : "", t.best_time ? `best ${clockTime(t.best_time)}` : ""].filter(Boolean).join(" · ") }),
            el("span", { class: "score", text: t.score != null ? Math.round(t.score) : "" }), go);
}

// --- targets ------------------------------------------------------------------

function matches(t, words) {
  const text = `${t.id} ${t.alt_id || ""} ${t.name || ""}`.toLowerCase().replace(/\s+/g, "");
  return text.includes(words);
}

function drawTargets() {
  const words = $("search").value.toLowerCase().replace(/\s+/g, ""), kind = filter;
  const keep = (t) => (!words || matches(t, words)) && (!kind || kind === "now" ? true : (t.kind || "").includes(kind)) && (kind !== "now" || t.observable_now);
  const ranked = ((seen.targets && seen.targets.targets) || []).filter(keep);
  fill($("ranked"), ranked.length ? ranked.slice(0, 15).map((t) => targetRow(t)) : el("p", { class: "quiet", text: "None match." }));
  const rankedIds = new Set(ranked.map((t) => t.id));
  const rest = words || (kind && kind !== "now")
    ? ((seen.catalogue && seen.catalogue.targets) || []).filter((t) => !rankedIds.has(t.id) && kind !== "now" && keep(t)).slice(0, 40) : [];
  fill($("catalogue"), rest.length ? rest.map((t) => el("div", { class: "row pick", on: { click: () => choose(t.id) } },
         el("span", { class: "id", text: t.id }), el("span", { class: "what", text: [t.alt_id, t.name, t.kind].filter(Boolean).join(" · ") })))
       : el("p", { class: "quiet", text: words ? "Nothing else in the catalogue matches." : "Type a name to search all of it." }));
  for (const button of $("filters").children) button.classList.toggle("on", button.dataset.filter === filter);
  gateAll();
}

function framing(t) {
  // How the target fits the camera: the field as a rectangle, the target drawn to scale inside it.
  const f = t.framing;
  if (!f) return null;
  const [wide, high] = f.field_deg, w = 280, h = Math.round(280 * high / wide), parts = [];
  parts.push(el("rect", { class: "field", x: 1, y: 1, width: w - 2, height: h - 2 }));
  let words = `Field ${wide.toFixed(2)}° × ${high.toFixed(2)}° · ${f.scale_arcsec_px}″ per pixel.`;
  if (f.size_arcmin) {
    const across = f.size_arcmin / 60, down = (f.minor_arcmin || f.size_arcmin) / 60, px = w / wide;
    parts.push(el("ellipse", { class: "object", cx: w / 2, cy: h / 2, rx: Math.max(1.5, across * px / 2), ry: Math.max(1.5, down * px / 2) }));
    const share = Math.round(100 * across / wide);
    words += ` ${t.id} is ${f.size_arcmin}′ across: ` + (across > wide ? "larger than the frame, so only part of it fits." : share < 3 ? "very small in the frame." : `about ${share}% of the frame's width.`);
  } else {
    parts.push(el("circle", { class: "object", cx: w / 2, cy: h / 2, r: 2 }));
    words += " The catalogue gives no size for it.";
  }
  return el("div", { class: "framing" }, el("svg", { viewBox: `0 0 ${w} ${h}` }, parts), el("p", { class: "quiet", text: words }));
}

async function choose(id) {
  chosen = id;
  const reply = await ask(`/api/target/${encodeURIComponent(id)}`);
  if (chosen !== id) return;
  if (!reply.ok) return fill($("chosen"), el("p", { class: "warn", text: reply.errors[0].message }));
  const t = reply.data, ranked = ((seen.targets && seen.targets.targets) || []).find((r) => r.id === t.id) || {};
  const facts = el("dl", { class: "facts" });
  const fact = (name, value) => { if (value != null && value !== "") facts.append(el("dt", { text: name }), el("dd", { text: value })); };
  fact("Kind", t.kind); fact("Height now", t.altitude_deg != null ? `${t.altitude_deg}°` : null);
  fact("Score", ranked.score != null ? Math.round(ranked.score) : null); fact("Direction at best", ranked.direction);
  fact("Best", ranked.best_time ? clockTime(ranked.best_time) : null);
  fact("Window", ranked.window ? `${clockTime(ranked.window[0])} to ${clockTime(ranked.window[1])}` : null);
  fact("Notes", (ranked.tags || []).join(", ").toLowerCase());
  const allowed = t.goto && t.goto.allowed;
  const go = el("button", { type: "button", text: `Go to ${t.id}`, "data-needs": "mount", "data-gate": "goto", on: { click: () => makePlan("goto", { target: t.id }) } });
  const centre = el("button", { type: "button", text: "Centre with plate solve", "data-needs": "imaging", "data-gate": "goto", on: { click: () => makePlan("goto", { target: t.id, solve: true }) } });
  const image = el("button", { type: "button", text: "Start imaging", "data-needs": "imaging", "data-gate": "run", on: { click: () => openSheet(t.id) } });
  fill($("chosen"), el("div", { class: "strong", text: `${t.id} ${t.name || ""}` }), facts, framing(t),
       allowed === false ? el("p", { class: "warn", text: `A GoTo is not allowed now: ${(t.goto.refusal || {}).message || t.goto.reason || "outside the limits"}` }) : null,
       el("div", { class: "buttons" }, go, centre, image));
  gateAll();
}

// --- mount, focus, imaging -------------------------------------------------------

function drawMount() {
  const state = seen.state, watch = seen.observing, position = seen.job && seen.job.position;
  if (!state) return;
  $("mount-state").textContent = (state.mount.state || "").toUpperCase();
  const locked = state.capabilities.motion.locked;
  $("lock").hidden = !locked;
  $("lock").textContent = locked ? `Motion is locked: ${state.capabilities.motion.lock_reason}. A person must remove the MOTION_LOCKED file; the console never does.` : "";
  const facts = (node, pairs) => fill(node, pairs.filter(([, v]) => v != null && v !== "").flatMap(([k, v]) => [el("dt", { text: k }), el("dd", { text: v })]));
  const limits = state.capabilities.motion.limits;
  facts($("position"), position ? [
    ["RA", `${position.ra_hours} h`], ["Dec", `${position.dec_deg}°`], ["Side", position.pier_side], ["At home", position.at_home ? "yes" : "no"],
    ["Read", age(Date.now() / 1000 - position.read)],
  ] : [["Position", "Not read yet. Press Read position."],
       ["Limits", `at least ${limits.min_altitude_deg}° up, within ${limits.max_hour_angle_hours} h of the meridian, ${limits.sun_exclusion_deg}° from the Sun`]]);
  facts($("pointing"), [["Last plate solve", state.mount.last_plate_solve_age_s != null ? age(state.mount.last_plate_solve_age_s) : "none yet"]]);
  const t = (watch && watch.tracking) || {};
  facts($("tracking"), [["Natural Dec drift", t.natural_dec_drift_arcsec_s != null ? `${t.natural_dec_drift_arcsec_s} "/s` : null],
                        ["Correction applied", t.dec_creep_arcsec_s != null ? `${t.dec_creep_arcsec_s} "/s` : null],
                        ["Drift left", t.drift_arcsec_s != null ? `${t.drift_arcsec_s} "/s` : null],
                        ["Longest exposure advised", t.max_recommended_exposure_s != null ? `${t.max_recommended_exposure_s} s` : null]]);
  picture($("scope-picture"), "scope.jpg");
  gateAll();
}

const FOCUS_LEVELS = { 1: "COARSE", 2: "STARS", 3: "FINE" };
const FOCUS_TRENDS = { improving: "IMPROVING", worse: "GETTING WORSE", steady: "STEADY", uncertain: "TOO FEW STARS", lost: "NO STAR IN VIEW" };

function drawFocus() {
  const focusing = mode() === "focusing", kept = seen.focus && seen.focus.reading, live = seen.focus && seen.focus.live;
  // While the aid runs, every frame's reading; afterwards, the last one taken on stars.
  const reading = focusing && live && live.age_s < STALE ? live : kept;
  $("focus-start").hidden = focusing;
  $("focus-finish").hidden = !focusing;
  if (!reading || (!focusing && reading.age_s > STALE)) {
    $("hfr").textContent = "–";
    for (const id of ["focus-level", "focus-trend", "focus-advice", "focus-timing"]) fill($(id));
    $("focus-meter").hidden = true;
    $("focus-unit").textContent = "HFR, pixels";
    $("focus-best").textContent = reading ? `Last reading ${reading.hfr}, ${age(reading.age_s)}` : "No reading yet.";
    return gateAll();
  }
  if (focusing && reading.hfr != null && (!trail.length || trail[trail.length - 1].saved !== reading.saved)) trail.push({ saved: reading.saved, hfr: reading.hfr });
  trail = trail.slice(-40);
  const good = reading.state === "good", poor = ["worse", "uncertain", "lost"].includes(reading.trend);
  $("focus-level").textContent = reading.level ? `LEVEL ${reading.level} · ${FOCUS_LEVELS[reading.level]}` : "";
  $("hfr").textContent = reading.hfr ?? "–";
  $("focus-unit").textContent = (reading.kind === "ring" ? "radius of the brightest star, pixels" : "HFR, pixels")
    + (reading.hfr_arcsec != null ? ` · ${reading.hfr_arcsec}″` : "");
  $("focus-meter").hidden = reading.meter == null;
  $("focus-meter").value = reading.meter || 0;
  $("focus-trend").textContent = good ? "✓ FOCUS GOOD" : FOCUS_TRENDS[reading.trend] || "";
  $("focus-trend").className = `trend ${poor && !good ? "warn" : "good"}`;
  $("focus-best").textContent = [reading.best_hfr != null ? `Best ${reading.best_hfr}` : null,
                                 reading.stars ? `${reading.stars} stars` : null,
                                 reading.scatter ? `scatter ±${reading.scatter}` : null,
                                 focusing ? null : age(reading.age_s)].filter(Boolean).join(" · ");
  $("focus-advice").textContent = reading.advice || "";
  const timing = reading.timing;
  $("focus-timing").textContent = timing
    ? `Heard ${timing.feedback_s} s after each exposure begins: ${timing.capture_s} s for the frame, ${timing.process_s} s to measure it`
    : "";
  spark($("focus-trail"), trail.map((r) => r.hfr));
  gateAll();
}

function drawImaging() {
  const run = seen.session;
  picture($("picture-now"), "latest.jpg");
  picture($("picture-stack"), "stack.jpg");
  if (!run || !run.latest) {
    $("picture-note").textContent = "No imaging run yet.";
    fill($("measures")); fill($("reasons"));
  } else {
    $("now-note").textContent = run.now ? `${run.now.detail} · ${age(run.now.age)}` : "the newest frame";
    $("stack-title").textContent = (run.stack && run.stack.kind ? run.stack.kind : `stack of ${run.name}`).toUpperCase();
    $("stack-note").textContent = run.stack ? run.stack.detail : `${run.accepted} accepted frames · ${run.integration ?? 0} s`;
    $("picture-note").textContent = mode() === "imaging" ? "Click a picture to see it alone." : `${run.name}: ${run.state || "finished"}, ${age(run.age)}. Click a picture to see it alone.`;
    const series = run.series || {}, measure = (label, key, unit) => {
      const [value, word] = run.latest[key] || [null, ""];
      const line = el("svg", { class: "spark", viewBox: "0 0 120 26", preserveAspectRatio: "none" });
      spark(line, series[key] || [], series.accepted);
      return el("div", { class: "measure" }, el("div", { class: "label", text: label }),
                el("div", { class: "value" }, `${value ?? "–"}${unit || ""} `, el("span", { class: `word ${word}`, text: (word || "").toUpperCase() })), line);
    };
    fill($("measures"), measure("FWHM", "fwhm", " px"), measure("Roundness", "roundness"), measure("Stars", "stars"),
         measure("Drift", "drift", "%"), measure("Rotation", "rotation", "°"));
    const reasons = Object.entries(run.reasons || {});
    fill($("reasons"), reasons.length ? ["Rejected: ", ...reasons.flatMap(([why, count]) => [el("b", { text: count }), ` ${why}   `])] : "No frames rejected.");
  }
  const found = (seen.gallery && seen.gallery.pictures) || [];
  $("gallery-part").hidden = !found.length;
  if ($("gallery").dataset.made !== found.map((p) => p.file + p.time).join()) {
    fill($("gallery"), found.map((p) => el("figure", {}, el("figcaption", { text: `${p.target} ${p.kind}`.trim() }),
         el("img", { src: `/pictures/${encodeURIComponent(p.file)}`, alt: `${p.target} ${p.kind}`, loading: "lazy" }))));
    $("gallery").dataset.made = found.map((p) => p.file + p.time).join();
  }
}

function openSheet(target) {
  $("sheet-target").textContent = target;
  $("sheet").dataset.target = target;
  estimate();
  $("sheet").hidden = $("shade").hidden = false;
  $("sheet-cancel").focus();
}

function estimate() {
  // From the newest saved run with this camera; with none, it does not guess.
  const run = seen.session, frames = Number($("run-frames").value) || 0, exposure = Number($("run-exposure").value);
  const cycle = run && run.cycle_s;
  $("run-estimate").textContent = !exposure ? "The exposure will be chosen from the tracking."
    : `Up to ${Math.round(frames * exposure / 60)} min of exposure. ` + (cycle ? `About ${Math.round(frames * cycle / 60)} min in all, from the last run's ${cycle} s per frame.` : "How long it takes in all is not known yet: there is no earlier run to measure it from.");
}

// --- equipment, tools, system: the application's own screens ------------------

const MARKS = { ok: ["✓", "good"], warn: ["!", "warn"], fail: ["✗", "bad"] };

function checkLines(node, names) {
  // The doctor's own lines for these parts of the kit, each with its advice.
  const parts = (seen.state && seen.state.capabilities.components) || {};
  fill(node, names.filter((n) => parts[n]).map((n) => el("div", { class: "check" },
       el("span", { class: `mark ${MARKS[parts[n].status][1]}`, text: MARKS[parts[n].status][0] }), el("span", { text: parts[n].message }))));
}

function facts(node, pairs) {
  fill(node, pairs.filter(([, v]) => v != null && v !== "").flatMap(([k, v]) => [el("dt", { text: k }), el("dd", { text: v })]));
}

function drawWelcome() {
  const state = seen.state;
  if (!state) return;
  const parts = state.capabilities.components || {};
  const rows = [["Settings", state.configured ? { status: "ok", message: "config.toml is in place" } : { status: "fail", message: "No settings file yet: your location has not been set" }, "settings"],
                ["Mount", parts.mount_lead, "telescope"], ["Camera", parts.camera, "camera"], ["Plate solver", parts.plate_solver, "solver"],
                ["Star database", parts.star_database, "solver"], ["Webcam", parts.webcam, "webcam"]].filter(([, part]) => part);
  fill($("welcome-list"), rows.map(([name, part]) => el("div", { class: "step" },
       el("span", { class: `mark ${MARKS[part.status][1]}`, text: MARKS[part.status][0] }), el("span", { class: "name", text: name }), el("span", { class: "what", text: part.message }))));
  const todo = [...new Map(rows.filter(([, part]) => part.status !== "ok").map(([name, , where]) => [where, name])).entries()];
  fill($("welcome-fix"), todo.map(([where, name]) => el("button", { type: "button", text: `Set up: ${name.toLowerCase()}`, on: { click: () => show(where) } })));
  $("welcome-demo").textContent = state.demo ? "" : "To try everything with nothing plugged in, start TelescopeYoke (demo) from the applications menu.";
}

function needsWelcome() {
  const state = seen.state, parts = state.capabilities.components || {};
  return state.mode === "app" && !state.demo && (!state.configured || ["mount_lead", "camera", "plate_solver", "star_database"].some((n) => parts[n] && parts[n].status === "fail"));
}

function drawCamera() {
  const state = seen.state;
  if (!state) return;
  facts($("camera-facts"), [["Read through", state.camera_backend === "altair" ? "Altair's own library" : "the INDI driver"], ["State", state.camera.state]]);
  checkLines($("camera-checks"), ["camera_transport", "camera"]);
  gateAll();
}

function drawTelescope() {
  const state = seen.state, position = seen.job && seen.job.position;
  if (!state) return;
  const link = { handset: "a serial lead to the SynScan handset", wifi: "the SynScan Wi-Fi adapter (no handset)", eqdir: "an EQDIR lead (no handset)" }[state.mount_link] || state.mount_link;
  const limits = state.capabilities.motion.limits;
  facts($("telescope-facts"), [["Reached by", link], ["State", state.mount.state],
        ["Position", position ? `RA ${position.ra_hours} h, Dec ${position.dec_deg}°, read ${age(Date.now() / 1000 - position.read)}` : "not read yet"],
        ["Rig", state.rig],
        ["Limits", `at least ${limits.min_altitude_deg}° up, within ${limits.max_hour_angle_hours} h of the meridian, ${limits.sun_exclusion_deg}° from the Sun`],
        ["Motion lock", state.capabilities.motion.locked ? `locked: ${state.capabilities.motion.lock_reason}` : "not locked"]]);
  checkLines($("telescope-checks"), ["serial_access", "mount_lead"]);
  $("telescope-note").textContent = state.mount_link === "handset"
    ? "After every power-on the handset must be taken through its start-up screens to its main menu, with today's date."
    : "Without a handset the mount must be told where home is, and once which way its Dec motor turns. Both are done from a terminal with someone beside the mount: ./mount.py sethome and ./mount.py directions.";
  gateAll();
}

function drawPolar() {
  const found = seen.polar, plot = $("polar-plot");
  picture($("polaris-now"), "polaris.jpg");
  gateAll();
  if (!found || found.measured == null) {
    fill(plot); fill($("polar-facts"));
    $("polar-total").textContent = "";
    $("polar-note").textContent = "Not measured yet.";
    return;
  }
  // Looking north at the pole: east is to the right, higher is up.
  const east = found.azimuth_deg, high = found.altitude_deg, latitude = 55;
  const across = east * Math.cos(latitude * Math.PI / 180), total = Math.hypot(across, high);
  const reach = Math.max(1, Math.ceil(total)), px = 120 / reach, x = 150 + across * px, y = 150 - high * px, parts = [];
  for (let ring = 1; ring <= reach; ring += Math.max(1, Math.round(reach / 4))) {
    parts.push(el("circle", { class: "ring", cx: 150, cy: 150, r: ring * px }), el("text", { x: 152 + ring * px, y: 148, text: `${ring}°` }));
  }
  parts.push(el("line", { class: "to", x1: 150, y1: 150, x2: x, y2: y }), el("circle", { class: "pole", cx: 150, cy: 150, r: 6 }),
             el("text", { x: 120, y: 172, text: "the pole" }), el("circle", { class: "axis-dot", cx: x, cy: y, r: 5 }),
             el("text", { x: x + 8, y: y - 6, text: "the mount's axis" }), el("text", { x: 4, y: 12, text: "looking north" }),
             el("text", { x: 272, y: 168, text: "east" }), el("text", { x: 4, y: 168, text: "west" }));
  fill(plot, parts);
  $("polar-total").textContent = `${total.toFixed(1)}° out`;
  facts($("polar-facts"), [
    ["Left and right", `${Math.abs(east).toFixed(1)}° too far ${east > 0 ? "east" : "west"}: swing the mount's north end ${Math.abs(east).toFixed(1)}° to the ${east > 0 ? "west" : "east"}`],
    ["Up and down", `${Math.abs(high).toFixed(1)}° too ${high > 0 ? "high" : "low"}: ${high > 0 ? "lower" : "raise"} the axis by ${Math.abs(high).toFixed(1)}°`]]);
  $("polar-note").textContent = `Measured ${found.measured ? age(Date.now() / 1000 - found.measured) : "earlier"}. Adjust the mount and measure again. `
    + "If it is left as it is, the drift it causes can be cancelled from the Mount screen, but the picture will still slowly turn.";
}

let shownLandmark = null;
function drawLandmark() {
  const all = (seen.landmarks && seen.landmarks.landmarks) || [];
  fill($("landmark-list"), all.length ? all.map((mark) => {
    const check = el("button", { type: "button", text: "Check", "data-needs": "imaging", "data-gate": "landmark-check",
                                 on: { click: () => { shownLandmark = mark.name; makePlan("landmark-check", { name: mark.name }); } } });
    const stars = mark.polar_when_remembered ? "after a star measurement" : "before any star measurement: remember it again once the axis is right";
    return el("div", { class: "tool" }, el("div", {}, el("b", { text: mark.name }),
              el("span", { text: `bearing ${mark.bearing_deg.toFixed(1)}°, ${mark.height_deg.toFixed(1)}° up · ${stars}` })),
              el("button", { type: "button", text: "Show", on: { click: () => { shownLandmark = mark.name; drawLandmark(); } } }), check);
  }) : el("p", { class: "quiet", text: "None remembered yet." }));
  const chosen = all.find((mark) => mark.name === shownLandmark) || null;
  $("landmark-views").hidden = !chosen;
  if (chosen) {
    const src = `/landmarks/${encodeURIComponent(chosen.name)}.jpg`;
    if ($("landmark-ref").getAttribute("src") !== src) $("landmark-ref").setAttribute("src", src);
    $("landmark-then").textContent = chosen.name;
    picture($("landmark-now"), "landmark.jpg");
  }
  gateAll();
}

function drawRigs() {
  const found = (seen.rigs && seen.rigs.rigs) || [];
  const links = { handset: "SynScan handset", wifi: "SynScan Wi-Fi adapter", eqdir: "EQDIR lead" };
  fill($("rig-cards"), found.length ? found.map((rig) => {
    const run = rig.imaging, kept = run && run.acceptance_rate != null ? ` · ${Math.round(100 * run.acceptance_rate)}% kept` : "";
    return el("div", {}, el("div", { class: "title", text: rig.name + (rig.current ? " (this window)" : "") }),
              rig.problem ? el("div", { class: "warn", text: rig.problem })
                          : el("div", { class: "quiet", text: `${links[rig.mount_link] || rig.mount_link} · ${rig.focal_length_mm} mm · camera through ${rig.camera_backend}` }),
              el("div", { class: `big ${run && run.state === "capturing" ? "good" : ""}`, text: run ? `${run.name} ${(run.state || "").toUpperCase()}` : "NO RUN YET" }),
              run ? el("div", { class: "quiet", text: `${run.captured}${run.planned ? " / " + run.planned : ""} frames${kept}${run.median_fwhm ? " · FWHM " + run.median_fwhm : ""} · ${age(run.age)}` }) : null);
  }) : el("p", { class: "quiet", text: "No rigs yet: this is the only telescope." }));
}

function drawSolver() { checkLines($("solver-checks"), ["plate_solver", "star_database"]); }

function drawWebcam() {
  checkLines($("webcam-checks"), ["webcam"]);
  picture($("webcam-picture"), "scope.jpg");
}

// The Horizon screen: the skyline in use, and a phone panorama being turned into one.
let panoShown = 1, panoPending = null, panoDrawing = null;

function drawHorizon() {
  const h = seen.horizon;
  if (h) {
    const plot = $("horizon-plot"), x = (az) => 30 + (az / 360) * 680, y = (alt) => 180 - (Math.max(alt, 0) / 90) * 170, parts = [];
    for (const alt of [0, 30, 60, 90]) parts.push(el("line", { class: "axis", x1: 30, x2: 710, y1: y(alt), y2: y(alt) }), el("text", { x: 4, y: y(alt) + 3, text: `${alt}°` }));
    ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"].forEach((name, i) => parts.push(el("text", { x: x(i * 45) - 4, y: 196, text: name })));
    for (const b of h.blocked || []) {
      const spans = b.from <= b.to ? [[b.from, b.to]] : [[b.from, 360], [0, b.to]];
      for (const [from, to] of spans) parts.push(el("rect", { class: "blocked", x: x(from), y: y(b.altitude), width: x(to) - x(from), height: y(0) - y(b.altitude) }));
    }
    if (h.skyline) {
      // What was measured, filled; and the line targets are kept above, with the margin on.
      const round = (points) => [{ az: 0, alt: points[points.length - 1].alt }, ...points, { az: 360, alt: points[0].alt }];
      const line = (points) => round(points).map((p) => `${x(p.az).toFixed(1)},${y(p.alt).toFixed(1)}`);
      parts.push(el("path", { class: "skyline", d: `M${x(0)},${y(0)} L${line(h.skyline).join(" L")} L${x(360)},${y(0)} Z` }),
                 el("path", { class: "usable", d: `M${line(h.usable).join(" L")}` }));
    }
    parts.push(el("line", { class: "limit", x1: 30, x2: 710, y1: y(h.min_altitude), y2: y(h.min_altitude) }),
               el("text", { x: 600, y: y(h.min_altitude) - 4, text: `${h.min_altitude}° altitude limit` }));
    if (!(h.blocked || []).length && !h.skyline) parts.push(el("text", { x: 230, y: 90, text: "No skyline measured and no blocked directions written yet." }));
    fill(plot, parts);
    const from = { panorama: "a phone panorama", telescope: "the telescope's own survey", "panorama+telescope": "a phone panorama, checked by the telescope" };
    $("horizon-status").textContent = h.skyline
      ? `Measured ${new Date(h.surveyed * 1000).toLocaleDateString()} from ${from[h.source] || h.source}. ` +
        (h.in_use ? `The planner keeps targets ${h.margin}° above it (the line); change the margin in Settings.` : "The planner is not using it: that is switched off in Settings.")
      : "No skyline has been measured yet. The planner keeps targets above the altitude limit and whatever is blocked in config.toml.";
    fill($("horizon-warnings"), (h.warnings || []).map((text) => el("p", { class: "warn", text: `Check: ${text}` })));
    $("horizon-forget").hidden = !h.skyline;
    drawPanorama(h.panorama);
  }
  gateAll();
}

function drawPanorama(pano) {
  const pictures = (pano && pano.pictures) || [];
  $("pano-work").hidden = !pictures.length;
  $("pano-also").hidden = !pictures.length || pictures.length >= 3;
  if (!pictures.length || panoDrawing) return;
  const shown = pictures[Math.min(panoShown, pictures.length) - 1], image = $("pano-picture"), over = $("pano-over");
  panoShown = shown.number;
  fill($("pano-pictures"), pictures.map((p) => el("button", { type: "button", class: p.number === panoShown ? "chosen" : "",
    text: p.number === 1 ? "Picture 1: the one that counts" : `Picture ${p.number}: another height`,
    on: { click: () => { panoShown = p.number; panoPending = null; drawHorizon(); } } })));
  const src = `/horizon/${shown.file}?v=${Math.floor(shown.taken)}`;
  if (image.getAttribute("src") !== src) image.setAttribute("src", src);
  if (!image.naturalWidth) return image.addEventListener("load", drawHorizon, { once: true });
  // The overlay is 1000 units across whatever the picture's shape.
  const tall = 1000 * image.naturalHeight / image.naturalWidth, parts = [];
  over.setAttribute("viewBox", `0 0 1000 ${tall}`);
  parts.push(el("polyline", { points: shown.line.map(([px, py]) => `${(px * 1000).toFixed(1)},${(py * tall).toFixed(1)}`).join(" ") }));
  shown.marks.forEach((mark, i) => parts.push(el("circle", { cx: mark.x * 1000, cy: mark.y * tall, r: 6 }),
    el("text", { x: mark.x * 1000 + 10, y: mark.y * tall + 4, text: `${i + 1}: ${mark.az}° / ${mark.alt}°` })));
  if (panoPending) parts.push(el("circle", { class: "pending", cx: panoPending[0] * 1000, cy: panoPending[1] * tall, r: 8 }));
  fill(over, parts);
  $("pano-mark").hidden = !panoPending;
  if (panoPending) $("pano-at").textContent = `The place clicked, ${(panoPending[0] * 100).toFixed(0)}% across:`;
  const marks = (seen.landmarks && seen.landmarks.landmarks) || [];
  $("pano-landmark").hidden = $("pano-mark-landmark").hidden = !marks.length;
  if ($("pano-landmark").options.length !== marks.length) fill($("pano-landmark"), marks.map((m) => el("option", { value: m.name, text: `${m.name} (${m.bearing_deg}° / ${m.height_deg}°)` })));
  fill($("pano-marks"), shown.marks.map((mark, i) => el("div", { class: "check" },
    el("span", { text: `Mark ${i + 1}: bearing ${mark.az}°, ${mark.alt}° up (${mark.from})` }),
    el("button", { type: "button", text: "Remove", on: { click: () => act("panorama-unmark", { mark: i + 1, picture: panoShown }) } }))));
  const fit = shown.fit;
  $("pano-fit").textContent = [
    !fit ? `This picture needs ${2 - shown.marks.length} more mark${shown.marks.length ? "" : "s"}.`
      : fit.problem ? fit.problem
      : `By its marks the picture is ${fit.degrees_wide}° wide` + (shown.marks.length > 2 ? `, and the marks agree on height to within ${fit.worst_deg}°.` : "."),
    shown.changed ? `${shown.changed} points of the line put right by hand.` : "",
    shown.above_picture ? `In ${shown.above_picture} places the top is above the picture: there it can only say "at least this high".` : "",
  ].filter(Boolean).join(" ");
  $("pano-save").disabled = !pano.ready;
}

function panoPlace(event) {
  const box = $("pano-over").getBoundingClientRect();
  return [Math.min(Math.max((event.clientX - box.left) / box.width, 0), 1), Math.min(Math.max((event.clientY - box.top) / box.height, 0), 1)];
}

function panoLine() { return seen.horizon.panorama.pictures[panoShown - 1].line; }

function panoDrag(event) {
  // Every point of the line the pointer passes over goes to the pointer's height.
  const [px, py] = panoPlace(event), line = panoLine(), from = Math.min(panoDrawing.last, px), to = Math.max(panoDrawing.last, px);
  let nearest = 0;
  line.forEach((point, i) => { if (Math.abs(point[0] - px) < Math.abs(line[nearest][0] - px)) nearest = i; });
  line.forEach((point, i) => { if (i === nearest || (point[0] >= from && point[0] <= to)) { point[1] = py; panoDrawing.moved.add(i); } });
  panoDrawing.last = px;
  const tall = Number($("pano-over").getAttribute("viewBox").split(" ")[3]);
  $("pano-over").querySelector("polyline").setAttribute("points", line.map(([lx, ly]) => `${(lx * 1000).toFixed(1)},${(ly * tall).toFixed(1)}`).join(" "));
}

function drawProcessing() {
  const run = seen.session;
  $("restack-name").textContent = run && run.name ? `${run.name}, from its saved raw frames.` : "No session saved yet.";
  $("restack-run").disabled = $("restack-all").disabled = !(run && run.name) || !!(seen.job && seen.job.running) || (seen.state && seen.state.demo);
}

function statusRows(node) {
  const rows = (seen.system && seen.system.rows) || [];
  fill(node, rows.flatMap((row) => [el("dt", { text: row.label }), el("dd", { class: row.level === "fair" ? "warn" : row.level, text: row.text })]));
}

function drawMeasured() {
  // What the rig has had measured about itself, and the command for each thing it has not.
  const rig = seen.characterise;
  if (!rig) return;
  $("rig-measured-summary").textContent = `${rig.summary}. Each of these is something that would otherwise be assumed.`;
  fill($("rig-measured"), rig.items.map((item) => el("div", { class: "check" },
    el("span", { class: `mark ${item.measured ? "good" : "quiet"}`, text: item.measured ? "✓" : "·" }),
    el("span", { text: item.measured
      ? `${item.what}: ${item.value}` + (item.age_days != null ? ` (${item.age_days} days ago)` : "")
      : `${item.what}: not measured. ${item.how}` }))));
}

function drawDoctor() {
  const report = seen.doctor;
  statusRows($("system-rows"));
  drawMeasured();
  if (!report) return;
  fill($("doctor-checks"), Object.entries(report.components).flatMap(([section, checks]) => [
    el("h2", { text: `${section} ${report.ready && report.ready[section.toLowerCase()] === false ? "· not ready" : ""}` }),
    ...checks.map((check) => el("div", { class: "check" }, el("span", { class: `mark ${MARKS[check.status][1]}`, text: MARKS[check.status][0] }), el("span", { text: check.message }))),
  ]));
}

const SECTIONS = { site: "Where the telescope is", horizon: "Horizon", scope: "Telescope", camera: "Camera", mount: "Mount",
                   solver: "Plate solver", webcam: "Webcam", indi: "INDI" };

async function loadSettings() {
  const reply = await ask("/api/settings");
  if (!reply.ok) return;
  const all = reply.data, form = $("settings-form"), parts = [];
  let section = null;
  for (const f of all.fields) {
    if (f.section !== section) parts.push(el("h2", { text: SECTIONS[f.section] || f.section }));
    section = f.section;
    const name = `${f.section}.${f.key}`, id = `set-${f.section}-${f.key}`;
    let input;
    if (f.kind === "choice") {
      input = el("select", { id, name }, f.optional ? el("option", { value: "", text: "(the usual)" }) : null,
                 f.choices.map((c) => el("option", { value: c, text: c, selected: c === f.value })));
    } else if (f.kind === "yesno") {
      input = el("input", { id, name, type: "checkbox", checked: f.value === true });
    } else {
      input = el("input", { id, name, type: f.kind === "text" ? "text" : "number", value: f.value ?? "", step: f.kind === "whole" ? 1 : "any",
                            min: f.min, max: f.max, placeholder: f.optional ? "blank: the usual" : "" });
    }
    input.dataset.kind = f.kind;
    parts.push(el("label", { for: id, text: f.label }), input, el("span", { class: "help", text: f.help }));
  }
  fill(form, parts);
  $("settings-note").textContent = all.demo ? "The demo uses the example settings; they cannot be changed here."
    : all.exists ? `Saved in ${all.file}.` : `No settings file yet. Saving makes ${all.file}; put your own location in first.`;
  $("save-settings").disabled = $("open-settings").disabled = !!all.demo;
  $("settings-wrong").hidden = true;
}

function drawSettings() {
  // The form is built when the screen is opened, and not again while someone is typing in it.
  if (!$("settings-form").firstChild) loadSettings();
}

async function saveSettings() {
  const values = {};
  for (const input of $("settings-form").querySelectorAll("[name]")) {
    values[input.name] = input.dataset.kind === "yesno" ? input.checked : input.value;
  }
  const reply = await ask("/api/settings", { values });
  $("settings-wrong").hidden = reply.ok;
  if (!reply.ok) { $("settings-wrong").textContent = reply.errors[0].message; return notice("The settings were not saved.", "failed"); }
  notice(reply.data.saved ? `Saved ${reply.data.saved} setting${reply.data.saved === 1 ? "" : "s"}.` : "Nothing had changed.");
  seen.report = seen.night = seen.targets = null;      // the night is worked out again for the new place
  await loadSettings();
  refresh();
}

function drawDemoSky() {
  const sky = seen.state && seen.state.sky;
  if (!sky) return;
  const away = Math.abs(sky.focus);
  facts($("sky-facts"), [["Focuser", away ? `${away} turn${away === 1 ? "" : "s"} ${sky.focus > 0 ? "outside" : "inside"} best focus` : "at best focus"],
        ["Cloud", sky.cloud ? "clouded over" : "clear"], ["Drift", sky.drift ? "the stars drift between frames" : "none"],
        ["Camera's lead", sky.unplugged ? "pulled out" : "plugged in"], ["Frames taken", sky.frames]]);
  $("sky-cloud").textContent = sky.cloud ? "Clear the cloud" : "Cloud over";
  $("sky-drift").textContent = sky.drift ? "Stop the drift" : "Start the drift";
  $("sky-unplugged").textContent = sky.unplugged ? "Plug the camera back in" : "Pull the camera's lead out";
}

async function tellSky(change) {
  const reply = await ask("/api/demo", change);
  if (!reply.ok) return notice(reply.errors[0].message, "failed");
  seen.state.sky = reply.data.sky;
  drawDemoSky();
}

function drawAbout() {
  const state = seen.state;
  if (state) facts($("about-facts"), [["Version", state.version], ["Running on", { linux: "Linux", win32: "Windows", darwin: "macOS" }[state.system] || state.system],
                                      ["Source", "github.com/Ryan-Clinton/telescopeyoke"], ["Licence", "MIT"]]);
}

// --- the activity log ---------------------------------------------------------------

function record(entry) {
  const id = `${entry.time}|${entry.text}`;
  if (logged.has(id)) return;
  logged.add(id);
  for (const where of ["log-lines", "logs-lines"]) {
    $(where).append(el("div", { class: `line ${entry.kind || ""}` }, el("span", { class: "t", text: hms(entry.time) }), entry.text));
  }
  $("log-newest").textContent = `${hms(entry.time)}  ${entry.text}`;
  if ($("log").hidden) unread += 1;
  $("log-count").textContent = unread ? `${unread} new` : "";
  $("log").scrollTop = $("log").scrollHeight;
}

function drawLog() {
  const jobs = seen.job;
  if (!jobs) return;
  for (const job of [...jobs.recent, jobs.running].filter(Boolean)) {
    record({ time: job.started, text: `${job.label}: started`, kind: "head" });
    for (const line of job.lines) record({ time: line.time, text: line.text, kind: $("technical").checked ? "" : "" });
    if (job.state === "ended") {
      const words = { finished: "finished", failed: `FAILED: ${(job.error || {}).message || ""}`, stopped: "ended by Stop" }[job.outcome];
      record({ time: job.ended, text: `${job.label}: ${words}`, kind: job.outcome === "failed" ? "failed" : "head" });
      if (($("technical").checked || $("technical-logs").checked) && job.result) record({ time: job.ended + 0.001, text: JSON.stringify(job.result), kind: "technical" });
      if (job.id !== lastJobId && job === jobs.recent[jobs.recent.length - 1]) {
        if (lastJobId !== null || job.ended > started) notice(`${job.label}: ${words}`, job.outcome === "failed" ? "failed" : "");
        lastJobId = job.id;
        if (job.action.startsWith("camera-") && job.result) {
          const box = $(["camera-setup", "camera-capabilities"].includes(job.action) ? "camera-result" : "tool-result");
          box.hidden = false;
          box.textContent = job.action === "camera-setup" ? setupWords(job.result) : JSON.stringify(job.result, null, 1);
        }
      }
    }
  }
}
// The camera setup's answer in words: each check, then the verdict.
function setupWords(result) {
  const marks = { ok: "\u2713", fixed: "\u2713", warn: "!", todo: "\u2192", fail: "\u2717" };
  const lines = (result.steps || []).map((step) => `${marks[step.status] || "?"} ${step.message}`);
  lines.push("", result.ready ? "The camera is ready." : "Not ready yet. Do what the marked line says, then press Set up again.");
  return lines.join("\n");
}
const started = Date.now() / 1000;
$("log-newest").textContent = "Activity log";

// --- navigation, polling, keys -----------------------------------------------------

let welcomed = false;
function show(name) {
  const section = $(name), mode = seen.state && seen.state.mode;
  // A screen that belongs to the other mode is not shown: back to Tonight.
  if (!section || !section.classList.contains("task") || (mode && section.dataset.only && section.dataset.only !== mode)) name = "home";
  task = name;
  for (const other of document.querySelectorAll(".task")) other.hidden = other.id !== name;
  for (const link of document.querySelectorAll(".tasks a")) link.classList.toggle("on", link.dataset.task === name);
  if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
  draw();
  refresh();
}

const SCREENS = { home: drawHome, targets: drawTargets, mount: drawMount, focus: drawFocus, imaging: drawImaging,
                  status: () => statusRows($("status-rows")), welcome: drawWelcome, camera: drawCamera, telescope: drawTelescope,
                  solver: drawSolver, webcam: drawWebcam, horizon: drawHorizon, polar: drawPolar, landmark: drawLandmark, calibration: gateAll, testing: gateAll,
                  processing: drawProcessing, rigs: drawRigs, doctor: drawDoctor, settings: drawSettings, logs: () => {}, about: drawAbout,
                  "demo-sky": drawDemoSky };

function draw() {
  if (seen.state) {
    document.body.classList.toggle("mode-app", seen.state.mode === "app");
    document.body.classList.toggle("mode-companion", seen.state.mode !== "app");
    document.body.classList.toggle("is-demo", !!seen.state.demo);
    // The first time the application opens with something still to set up, it opens on Welcome.
    if (!welcomed) {
      welcomed = true;
      if (task === "home" && needsWelcome()) return show("welcome");
      if ($(task) && $(task).dataset.only && $(task).dataset.only !== seen.state.mode) return show("home");
    }
  }
  drawTop(); drawBottom(); drawRail(); drawLog();
  SCREENS[task]();
}

async function load(name) {
  const reply = await ask(`/api/${name}`);
  if (reply.ok) seen[name] = reply.data;
  else if (name === "session") seen.session = null;
}

let busy = false, slow = 0;
async function refresh() {
  if (busy) return;
  busy = true;
  const wanted = ["state", "job", "session", "focus"];
  if (slow % 3 === 0) wanted.push("observing");
  if (slow % 30 === 0 || !seen.night) wanted.push("night", "targets", "report");
  if (["doctor", "status"].includes(task) || !seen.system) wanted.push("system");
  if (task === "imaging" && slow % 5 === 0 || !seen.gallery) wanted.push("gallery");
  if (!seen.catalogue) wanted.push("catalogue");
  if (task === "doctor" || !seen.doctor) wanted.push("doctor");
  if (task === "doctor") wanted.push("characterise");
  if (task === "horizon") wanted.push("horizon", "landmarks");
  if (task === "rigs") wanted.push("rigs");
  if (task === "polar") wanted.push("polar");
  if (task === "landmark") wanted.push("landmarks");
  slow += 1;
  await Promise.all(wanted.map(load));
  busy = false;
  draw();
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button || button.disabled) return;
  if (button.dataset.go) return show(button.dataset.go);
  if (button.dataset.turn) return tellSky({ turn: Number(button.dataset.turn) });
  if (button.dataset.sky) return tellSky({ [button.dataset.sky]: !(seen.state.sky || {})[button.dataset.sky] });
  if (button.dataset.plan) return makePlan(button.dataset.plan, {});
  if (button.dataset.action) return act(button.dataset.action, button.dataset.kind ? { kind: button.dataset.kind } : {});
  if (button.dataset.filter) { filter = filter === button.dataset.filter ? null : button.dataset.filter; return drawTargets(); }
});
for (const figure of document.querySelectorAll("#viewer figure")) {
  figure.addEventListener("click", () => {
    const alone = $("viewer").classList.contains("solo") && figure.classList.contains("chosen");
    for (const other of document.querySelectorAll("#viewer figure")) other.classList.toggle("chosen", other === figure && !alone);
    $("viewer").classList.toggle("solo", !alone);
  });
}
showOnlyIfThere($("clouds"), $("clouds-part"));
showOnlyIfThere($("scope-picture"), $("scope-part"));
showOnlyIfThere($("polaris-now"), $("polaris-view"));

$("stop").addEventListener("click", stop);
$("search").addEventListener("input", drawTargets);
$("focus-start").addEventListener("click", () => { trail = []; act("focus", { sound: $("focus-sound").value }); });
$("focus-finish").addEventListener("click", finish);
$("recheck").addEventListener("click", async () => { seen.doctor = null; await refresh(); notice("Checked again"); });
$("hardware-report").addEventListener("click", async () => {
  const reply = await ask("/api/hardware");
  $("hardware-text").hidden = false;
  $("hardware-text").textContent = reply.ok ? reply.data.text : reply.errors[0].message;
  // Selected ready to copy: the page may not write to the clipboard itself.
  getSelection().selectAllChildren($("hardware-text"));
  if (reply.ok) notice("Selected. Copy it (Ctrl+C) and paste it into a hardware report on GitHub.");
});
$("horizon-run").addEventListener("click", () => makePlan("horizon", { trace: $("horizon-trace").checked, daylight: $("horizon-daylight").checked, fresh: $("horizon-fresh").checked }));
$("horizon-forget").addEventListener("click", () => act("horizon-forget"));
$("pano-use").addEventListener("click", () => { panoShown = 1; panoPending = null; act("panorama-use", { file: $("pano-file").value }); });
$("pano-also").addEventListener("click", () => act("panorama-also", { file: $("pano-file").value }));
$("pano-save").addEventListener("click", () => act("panorama-save"));
$("pano-clear").addEventListener("click", () => { panoPending = null; act("panorama-clear"); });
$("pano-mark-typed").addEventListener("click", () => panoMark({ bearing: $("pano-bearing").value, height: $("pano-height").value }));
$("pano-mark-telescope").addEventListener("click", () => panoMark({ telescope: true }));
$("pano-mark-landmark").addEventListener("click", () => panoMark({ landmark: $("pano-landmark").value }));
function panoMark(what) {
  if (!panoPending) return;
  act("panorama-mark", { x: panoPending[0], y: panoPending[1], picture: panoShown, ...what });
  panoPending = null;
}
$("pano-over").addEventListener("pointerdown", (event) => {
  if (document.querySelector("input[name=pano-mode]:checked").value === "mark") {
    panoPending = panoPlace(event);
    return drawHorizon();
  }
  panoDrawing = { last: panoPlace(event)[0], moved: new Set() };
  $("pano-over").setPointerCapture(event.pointerId);
  panoDrag(event);
});
$("pano-over").addEventListener("pointermove", (event) => { if (panoDrawing) panoDrag(event); });
$("pano-over").addEventListener("pointerup", () => {
  if (!panoDrawing) return;
  const line = panoLine(), points = [...panoDrawing.moved].map((i) => [Number(line[i][0].toFixed(4)), Number(line[i][1].toFixed(4))]);
  panoDrawing = null;
  act("panorama-move", { points, picture: panoShown });
});
$("restack-run").addEventListener("click", () => act("restack", { target: seen.session.name }));
$("restack-all").addEventListener("click", () => act("restack", { target: seen.session.name, all: true }));
$("sheet-cancel").addEventListener("click", closeCard);
$("shade").addEventListener("click", closeCard);
$("run-frames").addEventListener("input", estimate);
$("run-exposure").addEventListener("change", estimate);
$("sheet-plan").addEventListener("click", () => {
  const params = { target: $("sheet").dataset.target, exposure: $("run-exposure").value, frames: Number($("run-frames").value),
                   gain: Number($("run-gain").value), recentre: $("run-recentre").checked,
                   assist: $("run-recentre").checked && $("run-assist").checked };
  // Without re-centring the run never touches the mount: there is no move to plan.
  if (params.recentre) return makePlan("run", params);
  closeCard();
  act("run", params);
});
$("run-recentre").addEventListener("change", () => {
  $("run-assist").disabled = !$("run-recentre").checked;
  $("sheet-plan").textContent = $("run-recentre").checked ? "Plan the run" : "Start (the mount is not moved)";
});
$("log-toggle").addEventListener("click", () => { $("log").hidden = !$("log").hidden; unread = 0; $("log-count").textContent = ""; });
$("technical").addEventListener("change", drawLog);
$("technical-logs").addEventListener("change", drawLog);
$("open-settings").addEventListener("click", async () => {
  const reply = await ask("/api/open/settings", {});
  notice(reply.ok ? (reply.data.created ? "Made config.toml from the example and opened it. Put your own location in it." : "Opened the settings file.") : reply.errors[0].message, reply.ok ? "" : "failed");
  fill($("settings-form"));      // edited by hand: read it afresh next time
  refresh();
});
showOnlyIfThere($("webcam-picture"), $("webcam-part"));
$("save-settings").addEventListener("click", saveSettings);
$("point-plan").addEventListener("click", () => makePlan("point", { bearing: $("point-bearing").value, height: $("point-height").value }));
$("landmark-remember").addEventListener("click", () => { shownLandmark = $("landmark-name").value.trim().replace(/ /g, "-").toLowerCase(); act("landmark-remember", { name: $("landmark-name").value }); });

for (const [id, name] of [["night", "night"], ["dim", "dim"]]) {
  $(id).checked = localStorage.getItem(name) === "1";
  document.body.classList.toggle(name, $(id).checked);
  $(id).addEventListener("change", () => { localStorage.setItem(name, $(id).checked ? "1" : "0"); document.body.classList.toggle(name, $(id).checked); });
}

document.addEventListener("keydown", (event) => {
  if (event.ctrlKey && event.shiftKey && event.code === "Space") { event.preventDefault(); return stop(); }
  if (event.key === "Escape") return closeCard();
  // No key moves the mount, and none acts while someone is typing.
  if (event.ctrlKey || event.altKey || event.metaKey || ["INPUT", "SELECT", "TEXTAREA"].includes(event.target.tagName)) return;
  const go = { g: "targets", f: "focus", i: "imaging" }[event.key.toLowerCase()];
  if (go) show(go);
  if (event.key.toLowerCase() === "l") $("log-toggle").click();
});

window.addEventListener("hashchange", () => show(location.hash.slice(1)));
show(location.hash.slice(1) || "home");
setInterval(refresh, 2000);
setInterval(drawTop, 1000);
