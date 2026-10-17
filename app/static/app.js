"use strict";

// Every value from the server is written with textContent only.
// The CSRF token is read from the page and sent on every POST.
const TOKEN = document.querySelector('meta[name="csrf-token"]').getAttribute("content");
const RUN_ID_PATTERN = /^[0-9a-f]{16}$/;
const DOMAIN_ORDER = ["hr", "it", "facilities"];
const DOMAIN_TITLES = { hr: "HR", it: "IT", facilities: "Facilities" };
const LOG_LIMIT = 5;

let pendingHash = null;
let expiryTimer = null;
let lastStatus = null;
const recentRuns = [];
const messageLog = [];

function byId(id) {
  return document.getElementById(id);
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) {
    node.textContent = String(text);
  }
  if (className) {
    node.className = className;
  }
  return node;
}

function clear(node) {
  while (node.firstChild) {
    node.removeChild(node.firstChild);
  }
}

function say(text, isError) {
  const message = byId("message");
  message.textContent = text;
  message.className = isError ? "error" : "ok";
  messageLog.unshift({ text: text, isError: isError });
  messageLog.length = Math.min(messageLog.length, LOG_LIMIT + 1);
  const list = byId("message-log");
  clear(list);
  for (const entry of messageLog.slice(1)) {
    list.appendChild(el("li", entry.text, entry.isError ? "error" : ""));
  }
}

// Disable a button and change its label while a request runs.
async function busy(button, label, work) {
  const original = button.textContent;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.textContent = label;
  try {
    return await work();
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.textContent = original;
  }
}

function table(headers, rows) {
  const wrap = el("div", null, "scroll");
  const grid = el("table");
  const head = el("tr");
  for (const header of headers) {
    head.appendChild(el("th", header));
  }
  grid.appendChild(head);
  for (const row of rows) {
    const line = el("tr");
    for (const cell of row) {
      if (cell && typeof cell === "object") {
        line.appendChild(el("td", cell.text, cell.className));
      } else {
        line.appendChild(el("td", cell));
      }
    }
    grid.appendChild(line);
  }
  wrap.appendChild(grid);
  return wrap;
}

async function api(method, path, body) {
  const options = { method: method, headers: {} };
  if (method === "POST") {
    options.headers["Content-Type"] = "application/json";
    options.headers["X-CSRF-Token"] = TOKEN;
    options.body = JSON.stringify(body || {});
  }
  const response = await fetch(path, options);
  let data = {};
  try {
    data = await response.json();
  } catch (err) {
    data = {};
  }
  if (!response.ok) {
    const code = data.error ? " (" + data.error + ")" : "";
    throw new Error((data.message || "HTTP " + response.status) + code);
  }
  return data;
}

// Domains rail

function renderDomains(status) {
  lastStatus = status;
  const box = byId("domains");
  clear(box);
  const names = DOMAIN_ORDER.filter((name) => name in status.domains);
  for (const name of names) {
    const info = status.domains[name];
    const row = el("div", null, "domain " + name);
    row.appendChild(el("strong", DOMAIN_TITLES[name] || name));
    row.appendChild(el("span", info.running ? "Running on port " + info.port : "Stopped",
                       "state " + (info.running ? "up" : "down")));
    const button = el("button", info.running ? "Stop" : "Start", "quiet");
    button.type = "button";
    button.addEventListener("click", () => toggleDomain(name, info.running));
    row.appendChild(button);
    box.appendChild(row);
  }
}

async function loadStatus() {
  const status = await api("GET", "/api/status");
  renderDomains(status);
  const requests = byId("requests");
  if (!requests.value) {
    requests.value = status.default_requests.join("\n");
  }
}

async function toggleDomain(name, running) {
  const path = "/api/domains/" + name + (running ? "/stop" : "/start");
  try {
    renderDomains(await api("POST", path, {}));
    say((running ? "Stopped " : "Started ") + (DOMAIN_TITLES[name] || name) + ".", false);
  } catch (err) {
    say(err.message, true);
  }
}

// Start or stop all three in the fixed order, stopping at the first error. No retry.
async function setAll(start) {
  if (!lastStatus) {
    await loadStatus();
  }
  const names = DOMAIN_ORDER.filter((name) => name in lastStatus.domains);
  for (const name of names) {
    if (lastStatus.domains[name].running === start) {
      continue;
    }
    try {
      renderDomains(await api("POST", "/api/domains/" + name + (start ? "/start" : "/stop"), {}));
    } catch (err) {
      say((DOMAIN_TITLES[name] || name) + ": " + err.message, true);
      return;
    }
  }
  say(start ? "All three domains are running." : "All three domains are stopped.", false);
}

// Seal: the plan hash drawn as an 8x8 grid. Decoration only; the text hash is the record.

function renderSeal(box, digest) {
  clear(box);
  for (const ch of digest) {
    box.appendChild(el("i", null, "n" + ch));
  }
}

// Lanes

function laneNames(items) {
  const names = DOMAIN_ORDER.slice();
  for (const item of items) {
    if (!names.includes(item.domain)) {
      names.push(item.domain);
    }
  }
  return names;
}

function renderLanes(box, items, buildItem) {
  clear(box);
  for (const name of laneNames(items)) {
    const lane = el("div", null, "lane " + name);
    lane.appendChild(el("h3", DOMAIN_TITLES[name] || name));
    const mine = items.filter((item) => item.domain === name);
    if (mine.length === 0) {
      lane.appendChild(el("p", "No actions here.", "empty"));
    }
    for (const item of mine) {
      lane.appendChild(buildItem(item));
    }
    box.appendChild(lane);
  }
}

// A warning belongs under a step when it starts with "<domain>: <action> ".
function warningsFor(step, warnings) {
  const prefix = step.domain + ": " + step.action + " ";
  return warnings.filter((line) => line.startsWith(prefix));
}

function showPlan(made) {
  pendingHash = made.plan_hash;
  byId("plan-meta").textContent = "Subject: " + made.plan.subject + ". Planner: " + made.planner + ".";
  const shown = new Set();
  renderLanes(byId("plan"), made.plan.steps, (step) => {
    const item = el("div", null, "item" + (step.classification === "will_not" ? " refused" : ""));
    item.appendChild(el("div", step.action, "action"));
    item.appendChild(el("div", step.classification + " " + JSON.stringify(step.params), "detail"));
    for (const line of warningsFor(step, made.warnings)) {
      shown.add(line);
      item.appendChild(el("p", "Warning: " + line, "warning"));
    }
    return item;
  });
  const extra = byId("plan-extra");
  clear(extra);
  for (const line of made.warnings) {
    if (!shown.has(line)) {
      extra.appendChild(el("p", "Warning: " + line, "warning"));
    }
  }
  byId("plan-hash").textContent = made.plan_hash;
  renderSeal(byId("plan-seal"), made.plan_hash);
  byId("plan-section").hidden = false;
  startCountdown(made.expires_at);
}

function hidePlan() {
  pendingHash = null;
  stopCountdown();
  byId("plan-section").hidden = true;
}

function stopCountdown() {
  if (expiryTimer !== null) {
    clearInterval(expiryTimer);
    expiryTimer = null;
  }
}

function startCountdown(expiresAt) {
  stopCountdown();
  const approve = byId("approve");
  const label = byId("plan-expiry");
  approve.disabled = false;
  if (typeof expiresAt !== "number") {
    label.textContent = "";
    return;
  }
  const tick = () => {
    const left = Math.floor(expiresAt - Date.now() / 1000);
    if (left <= 0) {
      stopCountdown();
      pendingHash = null;
      approve.disabled = true;
      label.textContent = "Plan expired, make it again.";
      return;
    }
    const seconds = String(left % 60).padStart(2, "0");
    label.textContent = "Approve within " + Math.floor(left / 60) + ":" + seconds + ".";
  };
  tick();
  if (pendingHash !== null) {
    expiryTimer = setInterval(tick, 1000);
  }
}

// Run

function showRun(result, digest) {
  byId("run-summary").textContent = "Run " + result.run_id + ": status " + result.status +
    ", exchanges so far " + result.exchange_count + ".";
  const box = byId("run");
  const items = result.rows.map((row) => row);
  renderLanes(box, items, (row) => {
    const refused = row.outcome === "refused";
    const item = el("div", null, "item" + (refused ? " refused" : ""));
    item.appendChild(el("div", row.action, "action"));
    const outcome = refused ? "Refused" : row.outcome;
    item.appendChild(el("div", outcome, "outcome " + row.outcome));
    const reason = row.reason && row.reason !== row.classification ? row.reason + ". " : "";
    item.appendChild(el("div", reason + row.classification, "detail"));
    return item;
  });
  if (result.abort_code) {
    byId("run-summary").textContent += " Aborted: " + result.abort_code + ".";
  }
  renderSeal(byId("run-seal"), digest);
  box.classList.remove("reveal");
  void box.offsetWidth;
  box.classList.add("reveal");
  byId("run-section").hidden = false;
  rememberRun(result.run_id);
}

function rememberRun(runId) {
  if (!recentRuns.includes(runId)) {
    recentRuns.unshift(runId);
  }
  const box = byId("recent");
  clear(box);
  if (recentRuns.length > 0) {
    box.appendChild(el("p", "Runs from this page", "note"));
  }
  for (const id of recentRuns) {
    const button = el("button", id, "quiet");
    button.type = "button";
    button.addEventListener("click", () => showRebuild(id));
    box.appendChild(button);
  }
}

function renderRebuild(view) {
  const box = byId("rebuild");
  clear(box);
  box.appendChild(el("p", "Rebuilt from the three domain ledgers, run " + view.run_id +
                     ": chains " + (view.chain_ok ? "ok" : "BROKEN"),
                     view.chain_ok ? "ok" : "error"));
  const rows = view.domains.map((domain) => [
    DOMAIN_TITLES[domain.domain] || domain.domain,
    domain.chain_ok ? "ok" : { text: "broken: " + domain.chain_error, className: "broken" },
    Object.keys(domain.outcomes).sort().map((key) => key + " " + domain.outcomes[key]).join(", "),
    domain.rejected,
  ]);
  box.appendChild(table(["domain", "chain", "outcomes", "token rejections"], rows));
  const limits = el("ul", null, "note");
  for (const line of view.limits) {
    limits.appendChild(el("li", line));
  }
  box.appendChild(limits);
}

async function loadRebuild(runId) {
  renderRebuild(await api("GET", "/api/runs/" + runId));
}

async function showRebuild(runId) {
  try {
    await loadRebuild(runId);
    say("Showing run " + runId + ".", false);
    return true;
  } catch (err) {
    say(err.message, true);
    return false;
  }
}

// Events

function chosenPlanner() {
  return document.querySelector('input[name="planner"]:checked').value;
}

byId("plan-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const subject = byId("subject").value.trim();
  const planner = chosenPlanner();
  const payload = { subject: subject, planner: planner };
  if (planner === "model") {
    payload.request_text = byId("request-text").value.trim();
  } else {
    payload.requests = byId("requests").value
      .split("\n").map((line) => line.trim()).filter((line) => line.length > 0);
  }
  const label = planner === "model" ? "Asking the model..." : "Making plan...";
  try {
    const made = await busy(byId("make-plan"), label, () => api("POST", "/api/plans", payload));
    showPlan(made);
    say("Plan ready. Check the steps and warnings, then approve.", false);
  } catch (err) {
    say(err.message, true);
  }
});

for (const radio of document.querySelectorAll('input[name="planner"]')) {
  radio.addEventListener("change", () => {
    const model = chosenPlanner() === "model";
    byId("requests-label").hidden = model;
    byId("request-text-label").hidden = !model;
    byId("model-note").hidden = !model;
  });
}

byId("approve").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  if (!pendingHash) {
    return;
  }
  const digest = pendingHash;
  pendingHash = null;
  stopCountdown();
  try {
    const result = await busy(button, "Running...",
                              () => api("POST", "/api/plans/" + digest + "/approve", {}));
    byId("plan-section").hidden = true;
    showRun(result, digest);
    await loadRebuild(result.run_id);
    say("Run " + result.run_id + " finished with status " + result.status + ".", false);
  } catch (err) {
    say(err.message, true);
  }
});

byId("discard").addEventListener("click", () => {
  hidePlan();
  say("Plan discarded. Nothing was approved or sent.", false);
});

byId("copy-hash").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(byId("plan-hash").textContent);
    say("Plan hash copied.", false);
  } catch (err) {
    say("Could not copy the hash. Select it and copy by hand.", true);
  }
});

byId("start-all").addEventListener("click", (event) => {
  busy(event.currentTarget, "Starting...", () => setAll(true));
});

byId("stop-all").addEventListener("click", (event) => {
  busy(event.currentTarget, "Stopping...", () => setAll(false));
});

byId("run-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const runId = byId("run-id").value.trim();
  if (!RUN_ID_PATTERN.test(runId)) {
    say("A run id is 16 lowercase hex characters.", true);
    return;
  }
  if (await showRebuild(runId)) {
    rememberRun(runId);
  }
});

loadStatus().catch((err) => say(err.message, true));
