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
               doctor: null, focus: null, catalogue: null, horizon: null };
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
  if (state.demo) return null;
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
  if (state && state.demo && action && !state.available.includes(action)) why = "Not in the demo: it needs the real camera.";
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
               $("run-assist").checked ? el("p", { text: "Drift assist will adjust the Dec motor." }) : null,
               el("p", { class: "quiet", text: "Capture" }),
               el("p", { text: `${p.frames} frames · ${p.exposure === "auto" ? "exposure chosen from the tracking" : p.exposure + " s each"} · gain ${p.gain}` }));
  }
  return [facts, ...lines, checks];
}

function showPlan(data) {
  plan = data;
  const scope = seen.state.scope_age != null || true;
  const picture = el("img", { src: "/pictures/scope.jpg", alt: "" });
  const beside = el("div", { class: "scope" }, picture, el("div", { class: "quiet", text: "The telescope, from the webcam" }));
  picture.addEventListener("error", () => beside.remove());
  const cancel = el("button", { type: "button", text: "Cancel", on: { click: closeCard } });
  fill($("plan"),
       el("div", { class: "kind", text: data.action === "run" ? "IMAGING PLAN" : "MOVE PLAN" }),
       el("h3", { text: data.label }),
       el("div", { class: "body" }, el("div", {}, planLines(data)), scope ? beside : null),
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
  $("site").textContent = state.site || "";
  $("demo").hidden = $("demo-mount").hidden = !state.demo;
  if (night) {
    const until = night.clear_window ? ` · clear ${clockTime(night.clear_window[0])} to ${clockTime(night.clear_window[1])}` : "";
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
    const reading = (seen.focus && seen.focus.reading) || {};
    return fill($("rail"), el("div", { class: "quiet", text: "FOCUSING" }), el("div", { class: "big", text: reading.hfr ?? "–" }),
                el("p", { class: "quiet", text: reading.best_hfr ? `Best tonight ${reading.best_hfr}` : "" }),
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
                el("div", { class: "buttons" },
                   button("Finish run", () => act("run-finish")), button("Re-centre", () => act("run-recentre")),
                   button("Drift assist on", () => act("run-assist-on")), button("Drift assist off", () => act("run-assist-off"))));
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

function drawHome() {
  const night = seen.night, watch = seen.observing;
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
  if (night) {
    $("home-verdict").textContent = night.verdict;
    $("home-verdict").className = `word ${night.verdict === "GO" ? "good" : night.verdict === "NO-GO" ? "bad" : "warn"}`;
    const start = new Date(night.sunset).getTime(), end = new Date(night.sunrise).getTime(), at = (t) => 600 * (new Date(t).getTime() - start) / (end - start);
    const bar = el("svg", { viewBox: "0 0 600 26", preserveAspectRatio: "none" }, el("rect", { x: 0, y: 10, width: 600, height: 6, class: "blocked", fill: "currentColor", opacity: 0.2 }));
    if (night.clear_window) bar.append(el("rect", { x: at(night.clear_window[0]), y: 10, width: Math.max(2, at(night.clear_window[1]) - at(night.clear_window[0])), height: 6, fill: "currentColor" }));
    const now = at(Date.now());
    if (now >= 0 && now <= 600) bar.append(el("rect", { x: now, y: 2, width: 2, height: 22, fill: "currentColor" }));
    fill($("window"), bar, el("div", { class: "quiet", text: night.clear_window
      ? `Clear from ${clockTime(night.clear_window[0])} to ${clockTime(night.clear_window[1])}; dark from ${clockTime(night.darkness.start)} to ${clockTime(night.darkness.end)}. The mark is now.`
      : "No clear window tonight." }));
    const moon = night.moon;
    $("moon").textContent = `Moon ${moon.illumination}% lit` + (moon.set ? `, sets ${clockTime(moon.set)}` : moon.rise ? `, rises ${clockTime(moon.rise)}` : "");
  }
  const list = ((seen.targets && seen.targets.targets) || []).filter((t) => t.observable_now).slice(0, 5);
  fill($("best"), list.length ? list.map((t, i) => targetRow(t, i === 0)) : el("p", { class: "quiet", text: "Nothing is well placed just now." }));
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
  fill($("chosen"), el("div", { class: "strong", text: `${t.id} ${t.name || ""}` }), facts,
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
  gateAll();
}

function drawFocus() {
  const reading = seen.focus && seen.focus.reading, focusing = mode() === "focusing";
  $("focus-start").hidden = focusing;
  $("focus-finish").hidden = !focusing;
  if (!reading || (!focusing && reading.age_s > STALE)) {
    $("hfr").textContent = "–";
    fill($("focus-trend")); fill($("focus-advice"));
    $("focus-best").textContent = reading ? `Last reading ${reading.hfr}, ${age(reading.age_s)}` : "No reading yet.";
    return gateAll();
  }
  if (focusing && (!trail.length || trail[trail.length - 1].saved !== reading.saved)) trail.push({ saved: reading.saved, hfr: reading.hfr });
  trail = trail.slice(-40);
  const before = trail.length > 1 ? trail[trail.length - 2].hfr : null;
  $("hfr").textContent = reading.hfr;
  $("focus-trend").textContent = before == null ? "" : reading.hfr < before ? "IMPROVING" : reading.hfr > before ? "GETTING WORSE" : "STEADY";
  $("focus-trend").className = `trend ${before != null && reading.hfr > before ? "warn" : "good"}`;
  $("focus-best").textContent = `Best tonight ${reading.best_hfr} · ${reading.stars} stars` + (focusing ? "" : ` · ${age(reading.age_s)}`);
  $("focus-advice").textContent = reading.advice || "";
  spark($("focus-trail"), trail.map((r) => r.hfr));
  gateAll();
}

let picture = "stack.jpg";
function drawImaging() {
  const run = seen.session;
  $("picture").src = `/pictures/${picture}`;   // fetched afresh each time: nothing is cached
  for (const tab of document.querySelectorAll("[data-picture]")) tab.classList.toggle("on", tab.dataset.picture === picture);
  if (!run || !run.latest) {
    $("picture-note").textContent = "No imaging run yet.";
    return fill($("measures")), fill($("reasons"));
  }
  $("picture-note").textContent = mode() === "imaging" ? "" : `${run.name}: ${run.state || "finished"}, ${age(run.age)}`;
  const series = run.series || {}, measure = (label, key, unit) => {
    const [value, word] = run.latest[key] || [null, ""];
    const line = el("svg", { class: "spark", viewBox: "0 0 120 26", preserveAspectRatio: "none" });
    spark(line, series[key] || [], series.accepted);
    return el("div", { class: "measure" }, el("div", { class: "label", text: label }),
              el("div", { class: "value" }, `${value ?? "–"}${unit || ""} `, el("span", { class: `word ${word}`, text: (word || "").toUpperCase() })), line);
  };
  fill($("measures"), measure("FWHM", "fwhm"), measure("Roundness", "roundness"), measure("Stars", "stars"), measure("Drift", "drift", "%"));
  const reasons = Object.entries(run.reasons || {});
  fill($("reasons"), reasons.length ? ["Rejected: ", ...reasons.flatMap(([why, count]) => [el("b", { text: count }), ` ${why}   `])] : "No frames rejected.");
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

// --- tools, system ------------------------------------------------------------

function drawTools() {
  const run = seen.session, h = seen.horizon;
  $("restack-name").textContent = run && run.name ? `${run.name}, from its saved raw frames.` : "No session saved yet.";
  $("restack-run").disabled = $("restack-all").disabled = !(run && run.name) || !!(seen.job && seen.job.running) || (seen.state && seen.state.demo);
  if (h) {
    const plot = $("horizon-plot"), x = (az) => 30 + (az / 360) * 680, y = (alt) => 180 - (alt / 90) * 170, parts = [];
    for (const alt of [0, 30, 60, 90]) parts.push(el("line", { class: "axis", x1: 30, x2: 710, y1: y(alt), y2: y(alt) }), el("text", { x: 4, y: y(alt) + 3, text: `${alt}°` }));
    ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"].forEach((name, i) => parts.push(el("text", { x: x(i * 45) - 4, y: 196, text: name })));
    for (const b of h.blocked || []) {
      const spans = b.from <= b.to ? [[b.from, b.to]] : [[b.from, 360], [0, b.to]];
      for (const [from, to] of spans) parts.push(el("rect", { class: "blocked", x: x(from), y: y(b.altitude), width: x(to) - x(from), height: y(0) - y(b.altitude) }));
    }
    parts.push(el("line", { class: "limit", x1: 30, x2: 710, y1: y(h.min_altitude), y2: y(h.min_altitude) }),
               el("text", { x: 600, y: y(h.min_altitude) - 4, text: `${h.min_altitude}° altitude limit` }));
    if (!(h.blocked || []).length) parts.push(el("text", { x: 250, y: 90, text: "No blocked directions recorded in config.toml yet." }));
    fill(plot, parts);
  }
  gateAll();
}

function drawSystem() {
  const report = seen.doctor;
  if (!report) return;
  const marks = { ok: ["✓", "good"], warn: ["!", "warn"], fail: ["✗", "bad"] };
  fill($("doctor"), Object.entries(report.components).flatMap(([section, checks]) => [
    el("h2", { text: `${section} ${report.ready && report.ready[section.toLowerCase()] === false ? "· not ready" : ""}` }),
    ...checks.map((check) => el("div", { class: "check" }, el("span", { class: `mark ${marks[check.status][1]}`, text: marks[check.status][0] }), el("span", { text: check.message }))),
  ]));
}

// --- the activity log ---------------------------------------------------------------

function record(entry) {
  const id = `${entry.time}|${entry.text}`;
  if (logged.has(id)) return;
  logged.add(id);
  $("log-lines").append(el("div", { class: `line ${entry.kind || ""}` }, el("span", { class: "t", text: hms(entry.time) }), entry.text));
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
      if ($("technical").checked && job.result) record({ time: job.ended + 0.001, text: JSON.stringify(job.result), kind: "technical" });
      if (job.id !== lastJobId && job === jobs.recent[jobs.recent.length - 1]) {
        if (lastJobId !== null || job.ended > started) notice(`${job.label}: ${words}`, job.outcome === "failed" ? "failed" : "");
        lastJobId = job.id;
        if (job.action.startsWith("camera-") && job.result) { $("tool-result").hidden = false; $("tool-result").textContent = JSON.stringify(job.result, null, 1); }
      }
    }
  }
}
const started = Date.now() / 1000;
$("log-newest").textContent = "Activity log";

// --- navigation, polling, keys -----------------------------------------------------

function show(name) {
  if (!$(name) || !$(name).classList.contains("task")) name = "home";
  task = name;
  for (const section of document.querySelectorAll(".task")) section.hidden = section.id !== name;
  for (const link of document.querySelectorAll(".tasks a")) link.classList.toggle("on", link.dataset.task === name);
  if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
  draw();
  refresh();
}

function draw() {
  drawTop(); drawBottom(); drawRail(); drawLog();
  ({ home: drawHome, targets: drawTargets, mount: drawMount, focus: drawFocus, imaging: drawImaging, tools: drawTools, system: drawSystem })[task]();
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
  if (slow % 30 === 0 || !seen.night) wanted.push("night", "targets");
  if (!seen.catalogue) wanted.push("catalogue");
  if (task === "system" || !seen.doctor) wanted.push("doctor");
  if (task === "tools") wanted.push("horizon");
  slow += 1;
  await Promise.all(wanted.map(load));
  busy = false;
  draw();
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button || button.disabled) return;
  if (button.dataset.go) return show(button.dataset.go);
  if (button.dataset.plan) return makePlan(button.dataset.plan, {});
  if (button.dataset.action) return act(button.dataset.action, button.dataset.kind ? { kind: button.dataset.kind } : {});
  if (button.dataset.filter) { filter = filter === button.dataset.filter ? null : button.dataset.filter; return drawTargets(); }
  if (button.dataset.picture) { picture = button.dataset.picture; return drawImaging(); }
});

$("stop").addEventListener("click", stop);
$("search").addEventListener("input", drawTargets);
$("focus-start").addEventListener("click", () => { trail = []; act("focus", { sound: $("focus-sound").value }); });
$("focus-finish").addEventListener("click", finish);
$("recheck").addEventListener("click", async () => { seen.doctor = null; await refresh(); notice("Checked again"); });
$("horizon-run").addEventListener("click", () => makePlan("horizon", { trace: $("horizon-trace").checked, daylight: $("horizon-daylight").checked }));
$("restack-run").addEventListener("click", () => act("restack", { target: seen.session.name }));
$("restack-all").addEventListener("click", () => act("restack", { target: seen.session.name, all: true }));
$("sheet-cancel").addEventListener("click", closeCard);
$("shade").addEventListener("click", closeCard);
$("run-frames").addEventListener("input", estimate);
$("run-exposure").addEventListener("change", estimate);
$("sheet-plan").addEventListener("click", () => makePlan("run", {
  target: $("sheet").dataset.target, exposure: $("run-exposure").value, frames: Number($("run-frames").value),
  gain: Number($("run-gain").value), recentre: $("run-recentre").checked, assist: $("run-assist").checked }));
$("log-toggle").addEventListener("click", () => { $("log").hidden = !$("log").hidden; unread = 0; $("log-count").textContent = ""; });
$("technical").addEventListener("change", drawLog);

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
