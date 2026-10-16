"use strict";

// Every value from the server is written with textContent, never innerHTML.
// The CSRF token is read from the page and sent on every POST.
const TOKEN = document.querySelector('meta[name="csrf-token"]').getAttribute("content");
const RUN_ID_PATTERN = /^[0-9a-f]{16}$/;

let pendingHash = null;

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
  const message = document.getElementById("message");
  message.textContent = text;
  message.className = isError ? "error" : "ok";
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
      line.appendChild(el("td", cell));
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

function renderDomains(status) {
  const box = document.getElementById("domains");
  clear(box);
  for (const name of Object.keys(status.domains)) {
    const info = status.domains[name];
    const row = el("div", null, "domain");
    row.appendChild(el("strong", name));
    row.appendChild(el("span", info.running ? "running on port " + info.port : "stopped",
                       info.running ? "up" : "down"));
    const button = el("button", info.running ? "Stop" : "Start");
    button.type = "button";
    button.addEventListener("click", () => toggleDomain(name, info.running));
    row.appendChild(button);
    box.appendChild(row);
  }
}

async function loadStatus() {
  const status = await api("GET", "/api/status");
  renderDomains(status);
  const requests = document.getElementById("requests");
  if (!requests.value) {
    requests.value = status.default_requests.join("\n");
  }
}

async function toggleDomain(name, running) {
  const path = "/api/domains/" + name + (running ? "/stop" : "/start");
  try {
    renderDomains(await api("POST", path, {}));
    say((running ? "Stopped " : "Started ") + name + ".", false);
  } catch (err) {
    say(err.message, true);
  }
}

function showPlan(made) {
  pendingHash = made.plan_hash;
  const section = document.getElementById("plan-section");
  const box = document.getElementById("plan");
  clear(box);
  box.appendChild(el("p", "Subject: " + made.plan.subject));
  box.appendChild(el("p", "Planner: " + made.planner));
  box.appendChild(el("p", "Plan hash: " + made.plan_hash, "hash"));
  const rows = made.plan.steps.map((step) => [
    step.domain, step.action, step.classification, JSON.stringify(step.params),
  ]);
  box.appendChild(table(["domain", "action", "classification", "params"], rows));
  for (const line of made.warnings) {
    box.appendChild(el("p", "Warning: " + line, "warning"));
  }
  section.hidden = false;
}

function showRun(result) {
  const section = document.getElementById("run-section");
  const box = document.getElementById("run");
  clear(box);
  box.appendChild(el("p", "Run " + result.run_id + ": status " + result.status +
                     ", exchanges so far " + result.exchange_count));
  if (result.abort_code) {
    box.appendChild(el("p", "Aborted: " + result.abort_code, "warning"));
  }
  const rows = result.rows.map((row) => [
    row.domain, row.action, row.classification, row.outcome, row.reason || "",
  ]);
  box.appendChild(table(["domain", "action", "classification", "outcome", "reason"], rows));
  section.hidden = false;
}

function renderRebuild(view) {
  const box = document.getElementById("rebuild");
  clear(box);
  box.appendChild(el("p", "Rebuilt from the three domain ledgers, run " + view.run_id +
                     ": chains " + (view.chain_ok ? "ok" : "BROKEN")));
  const rows = view.domains.map((domain) => [
    domain.domain,
    domain.chain_ok ? "ok" : domain.chain_error,
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

document.getElementById("plan-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const subject = document.getElementById("subject").value.trim();
  const planner = document.getElementById("planner").value;
  const payload = { subject: subject, planner: planner };
  if (planner === "model") {
    payload.request_text = document.getElementById("request-text").value.trim();
  } else {
    payload.requests = document.getElementById("requests").value
      .split("\n").map((line) => line.trim()).filter((line) => line.length > 0);
  }
  try {
    showPlan(await api("POST", "/api/plans", payload));
    say("Plan ready. Check the steps and warnings, then approve.", false);
  } catch (err) {
    say(err.message, true);
  }
});

document.getElementById("planner").addEventListener("change", (event) => {
  const model = event.currentTarget.value === "model";
  document.getElementById("requests-label").hidden = model;
  document.getElementById("request-text-label").hidden = !model;
  document.getElementById("model-note").hidden = !model;
});

document.getElementById("approve").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  if (!pendingHash) {
    return;
  }
  button.disabled = true;
  const digest = pendingHash;
  pendingHash = null;
  try {
    const result = await api("POST", "/api/plans/" + digest + "/approve", {});
    document.getElementById("plan-section").hidden = true;
    showRun(result);
    await loadRebuild(result.run_id);
    say("Run " + result.run_id + " finished with status " + result.status + ".", false);
  } catch (err) {
    say(err.message, true);
  } finally {
    button.disabled = false;
  }
});

document.getElementById("run-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const runId = document.getElementById("run-id").value.trim();
  if (!RUN_ID_PATTERN.test(runId)) {
    say("A run id is 16 lowercase hex characters.", true);
    return;
  }
  try {
    await loadRebuild(runId);
    say("Showing run " + runId + ".", false);
  } catch (err) {
    say(err.message, true);
  }
});

loadStatus().catch((err) => say(err.message, true));
