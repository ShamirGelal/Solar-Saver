"use strict";

const policies = [
  {key: "uncoordinated", name: "Uncoordinated", tag: "Baseline", description: "Household requests run as close to their preferred times as possible."},
  {key: "solar_only", name: "Solar-only", tag: "Solar first", description: "Shift household requests toward solar, respecting capacity and allowed windows."},
  {key: "balanced", name: "Balanced", tag: "Multiple goals", description: "Balance solar with capacity, preferences, priority, and fairness."},
];
const metricRows = [
  ["Grid energy used", "grid_energy_kwh", "kWh"],
  ["Solar energy used", "solar_used_kwh", "kWh"],
  ["Unused solar energy", "unused_solar_kwh", "kWh"],
  ["Renewable matching", "renewable_match_percent", "%"],
  ["Peak total demand", "peak_demand_kw", "kW"],
  ["Average preference shift", "average_preference_deviation_hours", "h"],
  ["Maximum preference shift", "maximum_preference_deviation_hours", "h"],
  ["Household-request completion", "completion_percent", "%"],
  ["Critical-request completion", "critical_completion_percent", "%"],
  ["Capacity violation hours", "capacity_violation_hours", "h"],
];
const number = (value, digits = 1) => new Intl.NumberFormat("en-US", {maximumFractionDigits: digits, minimumFractionDigits: digits}).format(value);
const byId = id => document.getElementById(id);
let report;
let selectedPolicy = "balanced";
let enteredLoads = [];
let editingId = null;
let nextLoadId = 1;
let customSupported = false;
let loading = false;
let comparisonMode = "demo";
const timeLabel = hour => `${String(hour).padStart(2, "0")}:00`;
const presets = {
  ev: {category: "EV charging", power_kw: 7.2, duration_hours: 3, earliest_start: 16, latest_finish: 24, preferred_start: 19, priority: "important", flexibility: 0.7},
  laundry: {category: "Laundry", power_kw: 0.8, duration_hours: 1, earliest_start: 8, latest_finish: 20, preferred_start: 14, priority: "flexible", flexibility: 0.8},
  dishwasher: {category: "Dishwasher", power_kw: 1.2, duration_hours: 2, earliest_start: 8, latest_finish: 23, preferred_start: 19, priority: "flexible", flexibility: 0.7},
  battery: {category: "Battery charging", power_kw: 2, duration_hours: 3, earliest_start: 7, latest_finish: 22, preferred_start: 13, priority: "flexible", flexibility: 0.9},
  water: {category: "Water heating", power_kw: 3, duration_hours: 1, earliest_start: 5, latest_finish: 22, preferred_start: 18, priority: "important", flexibility: 0.4},
  custom: {category: "Custom load", power_kw: 1, duration_hours: 1, earliest_start: 0, latest_finish: 24, preferred_start: 12, priority: "flexible", flexibility: 0.5},
};
const fieldIds = {category: "load-name", power_kw: "load-power", duration_hours: "load-duration", earliest_start: "load-earliest", latest_finish: "load-latest", preferred_start: "load-preferred", priority: "load-priority", flexibility: "load-flexibility"};

function fillForm(load) {
  for (const [key, id] of Object.entries(fieldIds)) byId(id).value = load[key];
  byId("form-error").hidden = true;
  updateFormSummary();
}

function updateFormSummary() {
  byId("flexibility-value").textContent = `${Math.round(Number(byId("load-flexibility").value) * 100)}%`;
  const energy = Number(byId("load-power").value) * Number(byId("load-duration").value);
  byId("load-energy").textContent = Number.isFinite(energy) && energy > 0 ? `${number(energy)} kWh requested` : "Enter power and duration";
}

function resetForm() {
  editingId = null;
  byId("load-preset").value = "ev";
  byId("form-title").textContent = "Add an appliance";
  byId("save-load").textContent = "+ Add load";
  byId("cancel-edit").hidden = true;
  fillForm(presets.ev);
  setEditorButtons();
}

function readForm() {
  const load = {};
  for (const [key, id] of Object.entries(fieldIds)) {
    load[key] = ["category", "priority"].includes(key) ? byId(id).value.trim() : Number(byId(id).value);
  }
  if (!load.category || load.category.length > 64) throw new Error("Give this load a name of 1–64 characters.");
  if (!Number.isFinite(load.power_kw) || load.power_kw <= 0 || load.power_kw > 10000) throw new Error("Power must be greater than 0 and at most 10,000 kW.");
  if (!Number.isInteger(load.duration_hours) || load.duration_hours < 1 || load.duration_hours > 24) throw new Error("Duration must be a whole number from 1 to 24 hours.");
  if (load.earliest_start + load.duration_hours > load.latest_finish) throw new Error("This load cannot finish within its allowed window. Increase the deadline or shorten the duration.");
  if (load.preferred_start < load.earliest_start || load.preferred_start + load.duration_hours > load.latest_finish) throw new Error("Choose a preferred start that leaves enough time to finish within the allowed window.");
  return load;
}

function setEditorButtons() {
  byId("compare-loads").disabled = loading || editingId !== null || !customSupported || !enteredLoads.length;
  byId("compare-loads").title = customSupported ? "" : "Custom comparisons require the local Python app.";
  byId("load-fields").disabled = loading;
  byId("example-loads").disabled = loading;
  byId("view-demo").disabled = loading;
  byId("reload").disabled = loading;
  document.querySelectorAll("[data-load-action]").forEach(button => { button.disabled = loading; });
}

function renderLoads() {
  const list = byId("load-list");
  list.replaceChildren();
  byId("empty-loads").hidden = enteredLoads.length > 0;
  byId("load-count").textContent = String(enteredLoads.length);
  byId("total-load-energy").textContent = `${number(enteredLoads.reduce((sum, load) => sum + load.power_kw * load.duration_hours, 0))} kWh requested`;
  for (const load of enteredLoads) {
    const row = document.createElement("li");
    row.className = "load-item";
    const heading = document.createElement("div");
    heading.className = "load-item-heading";
    const name = document.createElement("strong");
    name.textContent = load.category;
    const priority = document.createElement("span");
    priority.className = `priority-label ${load.priority}`;
    priority.textContent = load.priority;
    heading.append(name, priority);
    const details = document.createElement("p");
    details.textContent = `${number(load.power_kw)} kW · ${load.duration_hours} h · ${number(load.power_kw * load.duration_hours)} kWh`;
    const window = document.createElement("p");
    window.textContent = `${timeLabel(load.earliest_start)}–${timeLabel(load.latest_finish)} · Prefers ${timeLabel(load.preferred_start)} · ${Math.round(load.flexibility * 100)}% willing to shift`;
    const actions = document.createElement("div");
    actions.className = "load-item-actions";
    for (const [action, label] of [["edit", "Edit"], ["remove", "Remove"]]) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.dataset.loadAction = action;
      button.dataset.loadId = load.workload_id;
      button.setAttribute("aria-label", `${label} ${load.category}`);
      actions.append(button);
    }
    row.append(heading, details, window, actions);
    list.append(row);
  }
  setEditorButtons();
}

function loadsChanged(message) {
  renderLoads();
  byId("editor-status").textContent = message;
  if (report?.mode === "custom") {
    byId("results").hidden = true;
    byId("status").textContent = enteredLoads.length
      ? "Your loads changed. Compare again to update the schedules."
      : "No loads remain. Add an appliance or view the district demo.";
    byId("comparison-context").textContent = "Inputs changed · comparison needs updating";
  }
}

function renderSchedule() {
  const panel = byId("schedule-panel");
  panel.hidden = report.mode !== "custom";
  if (panel.hidden) return;
  const item = report.strategies[selectedPolicy];
  const assignments = new Map(item.assignments.map(assignment => [assignment.workload_id, assignment]));
  const body = byId("schedule-table").querySelector("tbody");
  body.replaceChildren();
  byId("schedule-summary").textContent = `${policies.find(policy => policy.key === selectedPolicy).name} · ${item.completed_count}/${report.workload_count} loads completed`;
  for (const load of report.workloads) {
    const assignment = assignments.get(load.workload_id);
    const row = document.createElement("tr");
    const values = [load.category, load.priority, timeLabel(load.preferred_start),
      assignment ? `${timeLabel(assignment.scheduled_start)}–${timeLabel(assignment.scheduled_end)}` : "Not scheduled — no feasible slot",
      assignment ? `${Math.abs(assignment.scheduled_start - load.preferred_start)} h` : "—",
      `${number(load.power_kw * load.duration_hours)} kWh`];
    values.forEach((value, index) => {
      const cell = document.createElement(index ? "td" : "th");
      if (!index) cell.scope = "row";
      cell.textContent = value;
      if (!assignment && index === 3) cell.className = "unscheduled";
      row.append(cell);
    });
    body.append(row);
  }
}

function validateReport(data) {
  if (!data || !data.strategies || !Object.keys(data.strategies).length) {
    throw new Error("No comparison results were returned. Try reloading the comparison.");
  }
  const profile = values => Array.isArray(values) && values.length === 24 && values.every(value => Number.isFinite(value) && value >= 0);
  const count = value => Number.isInteger(value) && value >= 0;
  if (![data.solar_supply_kw, data.base_demand_kw, data.grid_capacity_kw].every(profile)
      || !count(data.workload_count) || !count(data.critical_workload_count)) {
    throw new Error("The backend returned an invalid 24-hour scenario.");
  }
  for (const policy of policies) {
    const item = data.strategies[policy.key];
    if (!item || ![item.total_demand_kw, item.grid_draw_kw, item.solar_used_kw].every(profile)
        || !count(item.completed_count) || !count(item.unscheduled_count)
        || !Number.isFinite(item.served_energy_kwh)
        || !metricRows.every(([, key]) => Number.isFinite(item.metrics?.[key]))) {
      throw new Error("The backend returned an incomplete policy comparison.");
    }
  }
}

function renderCards() {
  byId("policy-cards").innerHTML = policies.map(policy => {
    const item = report.strategies[policy.key];
    const m = item.metrics;
    return `<article class="policy-card ${policy.key === "balanced" ? "balanced" : ""}">
      <div class="policy-top"><h3>${policy.name}</h3><span class="policy-tag">${policy.tag}</span></div>
      <p class="policy-desc">${policy.description}</p>
      <div class="match-value">${number(m.renewable_match_percent)}<span>%</span></div>
      <div class="match-label">of served energy matched by solar</div>
      <div class="meter" aria-hidden="true"><div class="meter-fill" data-match="${m.renewable_match_percent}"></div></div>
      <div class="card-stats"><div><strong>${number(m.grid_energy_kwh)}</strong><span>kWh drawn from the grid</span></div><div><strong>${number(m.average_preference_deviation_hours, 2)} h</strong><span>average preference shift</span></div></div>
      <div class="card-health"><span class="${item.unscheduled_count ? "warn" : ""}">${item.completed_count}/${report.workload_count} household requests completed</span><span class="${m.capacity_violation_hours ? "warn" : ""}">${m.capacity_violation_hours} h over capacity</span></div>
    </article>`;
  }).join("");
  document.querySelectorAll(".meter-fill").forEach(element => {
    element.style.transform = `scaleX(${Math.max(0, Math.min(100, Number(element.dataset.match))) / 100})`;
  });
}

function renderMetrics() {
  const body = byId("metrics-table").querySelector("tbody");
  body.replaceChildren();
  for (const [label, key, unit] of [...metricRows, ["Total served energy", "served_energy_kwh", "kWh"]]) {
    const row = document.createElement("tr");
    const heading = document.createElement("th");
    heading.scope = "row";
    heading.textContent = label;
    row.append(heading);
    for (const policy of policies) {
      const cell = document.createElement("td");
      const value = key === "served_energy_kwh" ? report.strategies[policy.key][key] : report.strategies[policy.key].metrics[key];
      cell.textContent = key === "critical_completion_percent" && !report.critical_workload_count
        ? "No critical requests" : `${number(value, key === "average_preference_deviation_hours" ? 2 : 1)} ${unit}`;
      row.append(cell);
    }
    body.append(row);
  }
}

function svgElement(tag, attributes = {}, text = "") {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  element.textContent = text;
  return element;
}

function renderChart() {
  const item = report.strategies[selectedPolicy];
  const name = policies.find(policy => policy.key === selectedPolicy).name;
  byId("chart-summary").textContent = `${name} policy · ${item.completed_count} of ${report.workload_count} household requests completed${item.unscheduled_count ? ` · ${item.unscheduled_count} could not be scheduled` : ""}`;
  const svg = svgElement("svg", {viewBox: "0 0 1080 350", role: "img", "aria-labelledby": "plot-title plot-description"});
  svg.append(svgElement("title", {id: "plot-title"}, `${name}: 24-hour solar supply and total demand`));
  svg.append(svgElement("desc", {id: "plot-description"}, "Hourly step chart. Gold shows expected solar supply; green shows total demand; the dashed line shows capacity. The hourly data table below provides exact values in kW."));
  const left = 53, right = 1060, top = 32, bottom = 306;
  const maximum = Math.max(100, ...report.solar_supply_kw, ...report.grid_capacity_kw, ...item.total_demand_kw);
  const ceiling = Math.ceil(maximum / 100) * 100 + 100;
  const x = hour => left + hour / 24 * (right - left);
  const y = value => bottom - value / ceiling * (bottom - top);
  for (let value = 0; value <= ceiling; value += 100) {
    svg.append(svgElement("line", {x1: left, x2: right, y1: y(value), y2: y(value), stroke: "#e5e9df", "stroke-width": 1}));
    svg.append(svgElement("text", {x: left - 12, y: y(value) + 4, "text-anchor": "end", fill: "#65755f", "font-size": 12}, String(value)));
  }
  svg.append(svgElement("text", {x: left - 12, y: 16, "text-anchor": "end", fill: "#65755f", "font-size": 11}, "kW"));
  for (let hour = 0; hour <= 24; hour += 3) {
    svg.append(svgElement("text", {x: x(hour), y: bottom + 27, "text-anchor": "middle", fill: "#65755f", "font-size": 12}, `${String(hour).padStart(2, "0")}:00`));
  }
  function step(values) {
    let path = `M ${x(0)} ${y(values[0])}`;
    values.forEach((value, hour) => {
      if (hour) path += ` V ${y(value)}`;
      path += ` H ${x(hour + 1)}`;
    });
    return path;
  }
  svg.append(svgElement("path", {d: `${step(report.solar_supply_kw)} L ${x(24)} ${bottom} L ${x(0)} ${bottom} Z`, fill: "#f5e7b9", opacity: .75}));
  svg.append(svgElement("path", {d: step(report.solar_supply_kw), fill: "none", stroke: "#bc8b1e", "stroke-width": 2}));
  svg.append(svgElement("path", {d: step(report.grid_capacity_kw), fill: "none", stroke: "#899286", "stroke-width": 1.5, "stroke-dasharray": "6 5"}));
  svg.append(svgElement("path", {d: step(item.total_demand_kw), fill: "none", stroke: "#23634d", "stroke-width": 2.8, "stroke-linejoin": "round"}));
  byId("chart").replaceChildren(svg);
  const body = byId("hourly-table").querySelector("tbody");
  body.replaceChildren();
  byId("hourly-caption").textContent = `${name} hourly profile · all power values in kW`;
  for (let hour = 0; hour < 24; hour++) {
    const row = document.createElement("tr");
    const heading = document.createElement("th");
    heading.scope = "row";
    heading.textContent = `${String(hour).padStart(2, "0")}:00–${String(hour + 1).padStart(2, "0")}:00`;
    row.append(heading);
    for (const value of [report.solar_supply_kw[hour], item.total_demand_kw[hour], item.grid_draw_kw[hour], report.grid_capacity_kw[hour]]) {
      const cell = document.createElement("td");
      cell.textContent = number(value);
      row.append(cell);
    }
    body.append(row);
  }
  renderSchedule();
}

async function loadComparison(mode = comparisonMode) {
  if (loading) return;
  if (mode === "custom" && (!customSupported || !enteredLoads.length)) return;
  comparisonMode = mode;
  loading = true;
  setEditorButtons();
  byId("results").hidden = true;
  byId("results").setAttribute("aria-busy", "true");
  byId("error").hidden = true;
  byId("status").textContent = "Loading the comparison…";
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(mode === "custom" ? "./api/comparison" : "./comparison.json", {
      cache: "no-store", signal: controller.signal,
      ...(mode === "custom" ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({workloads: enteredLoads})} : {}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error([data.error, data.detail].filter(Boolean).join(" ") || "The comparison could not be completed.");
    validateReport(data);
    report = data;
    customSupported = data.supports_custom_loads === true;
    byId("planner-availability").textContent = customSupported
      ? "Presets are editable simulation assumptions. Add up to 100 loads to plan this simulated day."
      : "This published demo shows precomputed results. You can prepare loads here; custom scheduling requires the local app.";
    byId("comparison-context").textContent = data.mode === "custom"
      ? `My ${data.workload_count} loads + simulated district background`
      : "District demo · 100 synthetic household requests";
    byId("scenario-label").textContent = data.mode === "custom"
      ? `24 hourly slots · ${data.workload_count} entered loads`
      : "24 hourly slots · 100 synthetic households";
    byId("forecast-model").textContent = report.model_name;
    const metadata = report.forecast_metadata || {};
    byId("forecast-warning").textContent = [metadata.fallback_reason, metadata.warning].filter(Boolean).join(" ");
    byId("forecast-warning").hidden = !byId("forecast-warning").textContent;
    renderCards();
    renderMetrics();
    renderChart();
    byId("results").hidden = false;
    byId("status").textContent = data.mode === "custom"
      ? "Your comparison is ready. Switch policies to explore your appliance timings."
      : "District demo ready · All three policies use the same scenario.";
  } catch (error) {
    byId("status").textContent = "";
    byId("error").textContent = error.name === "AbortError"
      ? "The comparison took too long to load. Please try again."
      : error instanceof TypeError ? "Could not load the comparison data. Check your connection, then try again." : error.message;
    byId("error").hidden = false;
    if (!report) byId("planner-availability").textContent = "Scheduling is unavailable. You can prepare your loads, then retry the comparison when the local app is running.";
  } finally {
    clearTimeout(timeout);
    loading = false;
    setEditorButtons();
    byId("results").setAttribute("aria-busy", "false");
  }
}

document.querySelectorAll('input[name="policy"]').forEach(input => input.addEventListener("change", event => {
  selectedPolicy = event.target.value;
  if (report) renderChart();
}));
byId("reload").addEventListener("click", () => loadComparison());
byId("compare-loads").addEventListener("click", () => loadComparison("custom"));
byId("view-demo").addEventListener("click", () => loadComparison("demo"));
for (const [id, first, last] of [["load-earliest", 0, 23], ["load-latest", 1, 24], ["load-preferred", 0, 23]]) {
  for (let hour = first; hour <= last; hour++) {
    const option = document.createElement("option");
    option.value = hour;
    option.textContent = timeLabel(hour);
    byId(id).append(option);
  }
}
byId("load-preset").addEventListener("change", event => fillForm(presets[event.target.value]));
byId("load-form").addEventListener("input", updateFormSummary);
byId("cancel-edit").addEventListener("click", () => {
  resetForm();
  byId("editor-status").textContent = "Edit canceled. Your load was unchanged.";
});
byId("load-form").addEventListener("submit", event => {
  event.preventDefault();
  try {
    if (!editingId && enteredLoads.length >= 100) throw new Error("You can compare up to 100 loads. Edit or remove an existing load first.");
    const load = {...readForm(), workload_id: editingId || `entered-${nextLoadId++}`};
    const editing = editingId !== null;
    if (editing) enteredLoads = enteredLoads.map(item => item.workload_id === editingId ? load : item);
    else enteredLoads.push(load);
    resetForm();
    loadsChanged(`${load.category} ${editing ? "updated" : "added"}.`);
  } catch (error) {
    byId("form-error").textContent = error.message;
    byId("form-error").hidden = false;
  }
});
byId("load-list").addEventListener("click", event => {
  const button = event.target.closest("button[data-load-action]");
  if (!button || loading) return;
  const load = enteredLoads.find(item => item.workload_id === button.dataset.loadId);
  if (!load) return;
  if (button.dataset.loadAction === "edit") {
    editingId = load.workload_id;
    byId("load-preset").value = "custom";
    fillForm(load);
    byId("form-title").textContent = "Edit appliance";
    byId("save-load").textContent = "Save changes";
    byId("cancel-edit").hidden = false;
    byId("editor-status").textContent = "Editing this load. Save or cancel before comparing.";
    setEditorButtons();
    byId("load-name").focus();
  } else {
    enteredLoads = enteredLoads.filter(item => item.workload_id !== load.workload_id);
    if (editingId === load.workload_id) resetForm();
    loadsChanged(`${load.category} removed.`);
    const next = byId("load-list").querySelector("button");
    (next || byId("load-name")).focus();
  }
});
byId("example-loads").addEventListener("click", () => {
  enteredLoads = [presets.ev, presets.laundry].map(load => ({...load, workload_id: `entered-${nextLoadId++}`}));
  loadsChanged("Two example loads added. You can edit every setting.");
});
resetForm();
renderLoads();
loadComparison();
