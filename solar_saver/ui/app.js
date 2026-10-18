"use strict";

const policies = [
  {key: "uncoordinated", name: "Uncoordinated", tag: "Convenience first", description: "Every flexible group starts at its preferred time, with no community coordination."},
  {key: "solar_only", name: "Solar-only", tag: "Solar first", description: "Move work aggressively into daylight, even when that means a much larger time shift."},
  {key: "balanced", name: "Balanced", tag: "Practical compromise", description: "Spread work across safe hours while keeping useful solar gains and shorter shifts."},
];
const metricRows = [
  ["Grid energy used", "grid_energy_kwh", "kWh"],
  ["Renewable matching", "renewable_match_percent", "%"],
  ["Peak total demand", "peak_demand_kw", "kW"],
  ["Average preference shift", "average_preference_deviation_hours", "h"],
  ["Load-group completion", "completion_percent", "%"],
  ["Capacity violation hours", "capacity_violation_hours", "h"],
];
const technicalMetricRows = [
  ["Solar energy used", "solar_used_kwh", "kWh"],
  ["Unused solar energy", "unused_solar_kwh", "kWh"],
  ["Maximum preference shift", "maximum_preference_deviation_hours", "h"],
  ["Critical-load completion", "critical_completion_percent", "%"],
  ["Total served energy", "served_energy_kwh", "kWh"],
];
const allMetricRows = [...metricRows, ...technicalMetricRows];
const number = (value, digits = 1) => new Intl.NumberFormat("en-US", {maximumFractionDigits: digits, minimumFractionDigits: digits}).format(value);
const displayPower = value => value >= 1000 ? `${number(value / 1000)} MW` : `${number(value)} kW`;
const displayEnergy = value => value >= 1000 ? `${number(value / 1000)} MWh` : `${number(value)} kWh`;
const byId = id => document.getElementById(id);
let report;
let selectedPolicy = "balanced";
let enteredLoads = [];
let enteredLoadScale = "household";
let editingId = null;
let nextLoadId = 1;
let customSupported = false;
let loading = false;
let comparisonMode = "showcase";
let showcaseLoads = [];
const maxEnteredLoads = 100;
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
const reportLoadLabel = () => report?.workload_scale === "aggregate"
  ? "aggregate groups" : report?.mode === "custom" ? "loads" : "load groups";

function fillForm(load) {
  for (const [key, id] of Object.entries(fieldIds)) byId(id).value = load[key];
  byId("form-error").hidden = true;
  updateFormSummary();
}

function updateFormSummary() {
  byId("flexibility-value").textContent = `${Math.round(Number(byId("load-flexibility").value) * 100)}%`;
  const energy = Number(byId("load-power").value) * Number(byId("load-duration").value);
  byId("load-energy").textContent = Number.isFinite(energy) && energy > 0 ? `${displayEnergy(energy)} requested` : "Enter power and duration";
}

function resetForm() {
  editingId = null;
  byId("load-preset").value = "ev";
  byId("form-title").textContent = "Add an appliance";
  byId("save-load").textContent = "+ Add load";
  byId("cancel-edit").hidden = true;
  byId("advanced-settings").open = false;
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
  byId("example-loads").disabled = loading || !showcaseLoads.length;
  byId("view-demo").disabled = loading;
  byId("reload").disabled = loading;
  document.querySelectorAll("[data-load-action]").forEach(button => { button.disabled = loading; });
}

function renderLoads() {
  const list = byId("load-list");
  list.replaceChildren();
  byId("empty-loads").hidden = enteredLoads.length > 0;
  byId("load-count").textContent = String(enteredLoads.length);
  byId("total-load-energy").textContent = `${displayEnergy(enteredLoads.reduce((sum, load) => sum + load.power_kw * load.duration_hours, 0))} requested`;
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
    details.textContent = `${displayPower(load.power_kw)} · ${load.duration_hours} h · ${displayEnergy(load.power_kw * load.duration_hours)}`;
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
  if (!enteredLoads.length) enteredLoadScale = "household";
  renderLoads();
  byId("editor-status").textContent = message;
  if (report?.mode === "custom") {
    byId("results").hidden = true;
    byId("status").textContent = enteredLoads.length
      ? "Your loads changed. Compare again to update the schedules."
      : "No loads remain. Add an appliance or reset the showcase.";
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
  byId("schedule-summary").textContent = `${policies.find(policy => policy.key === selectedPolicy).name} · ${item.completed_count}/${report.workload_count} ${reportLoadLabel()} completed`;
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
      || !count(data.workload_count) || !count(data.critical_workload_count)
      || !count(data.population_count) || !count(data.household_count)
      || !count(data.represented_appliance_count)
      || !["household", "aggregate"].includes(data.workload_scale)) {
    throw new Error("The backend returned an invalid 24-hour scenario.");
  }
  for (const policy of policies) {
    const item = data.strategies[policy.key];
    if (!item || ![item.total_demand_kw, item.grid_draw_kw, item.solar_used_kw].every(profile)
        || !count(item.completed_count) || !count(item.unscheduled_count)
        || !Number.isFinite(item.served_energy_kwh)
        || !allMetricRows.every(([, key]) => Number.isFinite(
          key === "served_energy_kwh" ? item[key] : item.metrics?.[key]
        ))) {
      throw new Error("The backend returned an incomplete policy comparison.");
    }
  }
}

function renderCards() {
  const requestLabel = reportLoadLabel();
  byId("policy-cards").innerHTML = policies.map(policy => {
    const item = report.strategies[policy.key];
    const m = item.metrics;
    return `<article class="policy-card ${policy.key === selectedPolicy ? "selected" : ""}" data-policy-card="${policy.key}">
      <div class="policy-top"><h3>${policy.name}</h3><span class="policy-tag">${policy.tag}</span></div>
      <p class="policy-desc">${policy.description}</p>
      <div class="match-value">${number(m.renewable_match_percent)}<span>%</span></div>
      <div class="match-label">of served energy matched by solar</div>
      <div class="meter" aria-hidden="true"><div class="meter-fill" data-match="${m.renewable_match_percent}"></div></div>
      <div class="card-stats"><div><strong>${displayPower(m.peak_demand_kw)}</strong><span>peak demand</span></div><div><strong>${displayEnergy(m.grid_energy_kwh)}</strong><span>from the grid</span></div><div><strong>${number(m.average_preference_deviation_hours, 2)} h</strong><span>average shift</span></div></div>
      <div class="card-health"><span class="${item.unscheduled_count ? "warn" : ""}">${item.completed_count}/${report.workload_count} ${requestLabel} completed</span><span class="${m.capacity_violation_hours ? "warn" : ""}">${m.capacity_violation_hours} h over capacity</span></div>
      <button class="policy-view" type="button" data-policy="${policy.key}" aria-pressed="${policy.key === selectedPolicy}">Show ${policy.name.toLowerCase()} curve</button>
    </article>`;
  }).join("");
  document.querySelectorAll(".meter-fill").forEach(element => {
    element.style.transform = `scaleX(${Math.max(0, Math.min(100, Number(element.dataset.match))) / 100})`;
  });
}

function renderPolicySelection() {
  document.querySelectorAll("[data-policy-card]").forEach(card => {
    const selected = card.dataset.policyCard === selectedPolicy;
    card.classList.toggle("selected", selected);
    const button = card.querySelector("[data-policy]");
    if (button) button.setAttribute("aria-pressed", String(selected));
  });
  const radio = document.querySelector(`input[name="policy"][value="${selectedPolicy}"]`);
  if (radio) radio.checked = true;
}

function renderPolicyInsight() {
  const baseline = report.strategies.uncoordinated.metrics;
  const solar = report.strategies.solar_only.metrics;
  const balanced = report.strategies.balanced.metrics;
  const balancedPeakDifference = solar.peak_demand_kw - balanced.peak_demand_kw;
  const balancedPeakComparison = balancedPeakDifference >= 0
    ? `${displayPower(balancedPeakDifference)} below solar-only`
    : `${displayPower(Math.abs(balancedPeakDifference))} above solar-only`;
  const balancedSolarDifference = balanced.renewable_match_percent - baseline.renewable_match_percent;
  const balancedSolarComparison = balancedSolarDifference >= 0
    ? `a ${number(balancedSolarDifference)}-point solar gain`
    : `${number(Math.abs(balancedSolarDifference))} points less solar matching`;
  const titles = {
    uncoordinated: "Convenience first creates the evening surge.",
    solar_only: "Solar-only moves work aggressively into daylight.",
    balanced: "Balanced weighs the peak, solar, and preferred times together.",
  };
  const details = {
    uncoordinated: `${displayPower(baseline.peak_demand_kw)} peak · ${baseline.capacity_violation_hours} overload hour${baseline.capacity_violation_hours === 1 ? "" : "s"} · no preference shift`,
    solar_only: `Renewable matching rises ${number(solar.renewable_match_percent - baseline.renewable_match_percent)} points, with a ${number(solar.average_preference_deviation_hours, 2)} h average shift.`,
    balanced: `${displayPower(balanced.peak_demand_kw)} peak—${balancedPeakComparison}—with ${number(balanced.average_preference_deviation_hours, 2)} h average shifting and ${balancedSolarComparison}.`,
  };
  byId("policy-insight-title").textContent = titles[selectedPolicy];
  byId("policy-insight-detail").textContent = details[selectedPolicy];
}

function selectPolicy(policyKey) {
  if (!report?.strategies[policyKey]) return;
  selectedPolicy = policyKey;
  renderPolicySelection();
  renderPolicyInsight();
  renderChart();
}

function renderOutcome() {
  const baseline = report.strategies.uncoordinated;
  const solarOnly = report.strategies.solar_only;
  const balanced = report.strategies.balanced;
  const capacity = Math.min(...report.grid_capacity_kw);
  const peakReduction = Math.max(0, baseline.metrics.peak_demand_kw - balanced.metrics.peak_demand_kw);
  const gridReduction = Math.max(0, baseline.metrics.grid_energy_kwh - balanced.metrics.grid_energy_kwh);
  const shiftMinutes = Math.round(balanced.metrics.average_preference_deviation_hours * 60);
  const avoidedViolations = Math.max(0, baseline.metrics.capacity_violation_hours - balanced.metrics.capacity_violation_hours);
  const solarShift = solarOnly.metrics.average_preference_deviation_hours;
  const inconvenienceReduction = solarShift > 0
    ? Math.max(0, Math.round((1 - balanced.metrics.average_preference_deviation_hours / solarShift) * 100))
    : 0;
  const requestLabel = reportLoadLabel();
  byId("outcome-title").textContent = balanced.unscheduled_count === 0 && avoidedViolations > 0
    ? peakReduction > 0
      ? `Balanced avoids the evening overload and cuts the peak by ${displayPower(peakReduction)}.`
      : "Balanced completes every load group without exceeding the demand limit."
    : balanced.unscheduled_count === 0 && balanced.metrics.capacity_violation_hours === 0
      ? `All ${report.workload_count} ${requestLabel} served within the ${displayPower(capacity)} limit.`
    : `${balanced.completed_count} of ${report.workload_count} ${requestLabel} served by the balanced policy.`;
  const details = [`All ${balanced.completed_count}/${report.workload_count} ${requestLabel} complete`];
  if (gridReduction > 0) details.push(`${displayEnergy(gridReduction)} less grid energy than uncoordinated use`);
  const renewableDifference = balanced.metrics.renewable_match_percent - baseline.metrics.renewable_match_percent;
  details.push(renewableDifference >= 0
    ? `${number(renewableDifference)} percentage-point solar gain`
    : `${number(Math.abs(renewableDifference))} percentage points less solar matching`);
  if (report.mode === "custom" && report.critical_workload_count > 0) {
    const assignments = new Map(balanced.assignments.map(item => [item.workload_id, item]));
    const protectedCritical = report.workloads.filter(load => load.priority === "critical")
      .every(load => assignments.get(load.workload_id)?.scheduled_start === load.preferred_start);
    if (protectedCritical) details.push("critical load kept at its preferred time");
  }
  details.push(shiftMinutes >= 60
    ? `${number(shiftMinutes / 60, shiftMinutes % 60 ? 1 : 0)} h average shift`
    : `${shiftMinutes}-minute average shift`);
  if (inconvenienceReduction > 0) details.push(`${inconvenienceReduction}% less shifting than solar-only`);
  byId("outcome-detail").textContent = details.join(" · ");
}

function renderMetrics() {
  renderMetricTable("metrics-table", metricRows);
  renderMetricTable("metrics-extra-table", technicalMetricRows);
}

function renderMetricTable(tableId, rows) {
  const body = byId(tableId).querySelector("tbody");
  body.replaceChildren();
  for (const [originalLabel, key, unit] of rows) {
    const label = report.mode === "custom" && originalLabel === "Load-group completion"
      ? "Load completion" : originalLabel;
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
  const requestLabel = reportLoadLabel();
  byId("chart-summary").textContent = `${name} policy · ${item.completed_count} of ${report.workload_count} ${requestLabel} completed${item.unscheduled_count ? ` · ${item.unscheduled_count} could not be scheduled` : ""}`;
  const svg = svgElement("svg", {viewBox: "0 0 1080 350", role: "img", "aria-labelledby": "plot-title plot-description"});
  svg.append(svgElement("title", {id: "plot-title"}, `${name}: 24-hour solar supply and total demand`));
  svg.append(svgElement("desc", {id: "plot-description"}, "Hourly step chart. Gold shows expected solar supply; green shows the selected policy's total demand; gray dashes show capacity. Coordinated policies also show the uncoordinated demand as a faint orange dashed reference. The hourly data table below provides exact values in kW."));
  const left = 53, right = 1060, top = 32, bottom = 306;
  const everyDemandProfile = policies.flatMap(policy => report.strategies[policy.key].total_demand_kw);
  const maximum = Math.max(100, ...report.solar_supply_kw, ...report.grid_capacity_kw, ...everyDemandProfile);
  const provisionalCeiling = Math.ceil(maximum / 100) * 100 + 100;
  const tickSize = provisionalCeiling <= 1000 ? 100 : Math.ceil(provisionalCeiling / 5000) * 1000;
  const ceiling = Math.ceil(provisionalCeiling / tickSize) * tickSize;
  const axisUsesMegawatts = ceiling >= 1000;
  const x = hour => left + hour / 24 * (right - left);
  const y = value => bottom - value / ceiling * (bottom - top);
  for (let value = 0; value <= ceiling; value += tickSize) {
    svg.append(svgElement("line", {x1: left, x2: right, y1: y(value), y2: y(value), stroke: "#e5e9df", "stroke-width": 1}));
    svg.append(svgElement("text", {x: left - 12, y: y(value) + 4, "text-anchor": "end", fill: "#65755f", "font-size": 12}, String(axisUsesMegawatts ? value / 1000 : value)));
  }
  svg.append(svgElement("text", {x: left - 12, y: 16, "text-anchor": "end", fill: "#65755f", "font-size": 11}, axisUsesMegawatts ? "MW" : "kW"));
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
  if (selectedPolicy !== "uncoordinated") {
    svg.append(svgElement("path", {d: step(report.strategies.uncoordinated.total_demand_kw), fill: "none", stroke: "#c87658", "stroke-width": 1.8, "stroke-dasharray": "5 5", opacity: .85}));
  }
  svg.append(svgElement("path", {d: step(item.total_demand_kw), fill: "none", stroke: "#23634d", "stroke-width": 2.8, "stroke-linejoin": "round"}));
  const peakValue = Math.max(...item.total_demand_kw);
  const peakHour = item.total_demand_kw.indexOf(peakValue);
  const peakOverCapacity = peakValue > report.grid_capacity_kw[peakHour];
  svg.append(svgElement("circle", {cx: x(peakHour + .5), cy: y(peakValue), r: 4.5, fill: peakOverCapacity ? "#a84e36" : "#23634d", stroke: "#fff", "stroke-width": 2}));
  svg.append(svgElement("text", {
    x: x(peakHour + .5) + (peakHour > 18 ? -9 : 9),
    y: Math.max(top + 12, y(peakValue) - 10),
    "text-anchor": peakHour > 18 ? "end" : "start",
    fill: peakOverCapacity ? "#8a3f2b" : "#23634d",
    "font-size": 11,
    "font-weight": 650,
  }, `${displayPower(peakValue)} peak${peakOverCapacity ? " · over limit" : ""}`));
  byId("chart").replaceChildren(svg);
  byId("baseline-legend").hidden = selectedPolicy === "uncoordinated";
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
  renderPolicySelection();
  renderPolicyInsight();
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
      ...(mode === "custom" ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({workloads: enteredLoads, workload_scale: enteredLoadScale})} : {}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error([data.error, data.detail].filter(Boolean).join(" ") || "The comparison could not be completed.");
    validateReport(data);
    report = data;
    customSupported = data.supports_custom_loads === true;
    if (data.mode === "showcase") {
      showcaseLoads = data.workloads.map(load => ({
        workload_id: load.workload_id,
        category: load.category,
        power_kw: load.power_kw,
        duration_hours: load.duration_hours,
        earliest_start: load.earliest_start,
        latest_finish: load.latest_finish,
        preferred_start: load.preferred_start,
        priority: load.priority,
        flexibility: load.flexibility,
      }));
      selectedPolicy = "balanced";
    }
    byId("planner-availability").textContent = customSupported
      ? `Presets are editable simulation assumptions. Add up to ${maxEnteredLoads} loads or load the presentation groups below.`
      : "This published demo shows precomputed results. You can prepare loads here; custom scheduling requires the local app.";
    byId("comparison-context").textContent = data.mode === "custom"
      ? data.workload_scale === "aggregate"
        ? `My ${data.workload_count} aggregate groups represent ${number(data.represented_appliance_count, 0)} appliance events + district background`
        : `My ${data.workload_count} loads + simulated ${number(data.population_count, 0)}-person district background`
      : `${data.scenario_name} · ${number(data.workload_count, 0)} groups represent ${number(data.represented_appliance_count, 0)} flexible appliance events`;
    byId("metrics-step").textContent = data.mode === "custom"
      ? "04 / THE TRADE-OFFS" : "03 / THE TRADE-OFFS";
    byId("scenario-label").textContent = data.mode === "custom"
      ? `24 hourly slots · ${number(data.population_count, 0)}-person district · ${data.workload_count} entered ${data.workload_scale === "aggregate" ? "aggregate groups" : "loads"}`
      : `${number(data.population_count, 0)} synthetic people · ${number(data.household_count, 0)} modeled households · 24 hours`;
    byId("scenario-story").hidden = data.mode !== "showcase";
    byId("represented-appliances").textContent = number(data.represented_appliance_count, 0);
    byId("showcase-energy").textContent = displayEnergy(data.requested_flexible_energy_kwh);
    byId("solar-capacity").textContent = displayPower(data.installed_capacity_kw);
    byId("grid-capacity").textContent = displayPower(Math.min(...data.grid_capacity_kw));
    byId("forecast-model").textContent = report.model_name;
    const metadata = report.forecast_metadata || {};
    byId("forecast-warning").textContent = [metadata.fallback_reason, metadata.warning].filter(Boolean).join(" ");
    byId("forecast-warning").hidden = !byId("forecast-warning").textContent;
    renderCards();
    renderOutcome();
    renderMetrics();
    renderChart();
    byId("results").hidden = false;
    byId("status").textContent = data.mode === "custom"
      ? "Your comparison is ready. Switch policies to explore your appliance timings."
      : "Presentation scenario ready · Choose each policy to watch the demand curve change.";
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
  selectPolicy(event.target.value);
}));
byId("policy-cards").addEventListener("click", event => {
  const button = event.target.closest("button[data-policy]");
  if (button) selectPolicy(button.dataset.policy);
});
byId("reload").addEventListener("click", () => loadComparison());
byId("compare-loads").addEventListener("click", () => loadComparison("custom"));
byId("view-demo").addEventListener("click", () => {
  enteredLoads = [];
  enteredLoadScale = "household";
  renderLoads();
  loadComparison("showcase");
});
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
    if (!editingId && enteredLoads.length >= maxEnteredLoads) throw new Error(`You can compare up to ${maxEnteredLoads} loads. Edit or remove an existing load first.`);
    if (!editingId && !enteredLoads.length) enteredLoadScale = "household";
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
    byId("advanced-settings").open = true;
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
  enteredLoads = showcaseLoads.map(load => ({...load}));
  enteredLoadScale = "aggregate";
  nextLoadId = Math.max(nextLoadId, enteredLoads.length + 1);
  loadsChanged(`Presentation scenario loaded: ${enteredLoads.length} aggregate groups representing ${number(report.represented_appliance_count, 0)} appliance events, all flexible and all preferring 18:00.`);
});
resetForm();
renderLoads();
loadComparison();

function renderHouseholdExample() {
  const samples = report && report.household_demo;
  const panel = byId("home-results");
  if (!samples) { panel.textContent = "Household examples are unavailable. Refresh after the latest deployment."; return; }
  const selected = samples[byId("home-flex").value];
  const clock = hour => `${String(hour).padStart(2, "0")}:00`;
  const headings = {uncoordinated:"Uncoordinated", solar_only:"Solar-only", balanced:"Balanced"};
  panel.replaceChildren();
  const summary = document.createElement("p");
  summary.textContent = "Same 14.0 kWh of appliance work in every comparison. Read solar matching alongside time shifts.";
  panel.append(summary);
  const grid = document.createElement("div"); grid.className = "policy-cards";
  Object.entries(selected).forEach(([policy, result]) => {
    const card = document.createElement("article"); card.className = "home-policy";
    const title = document.createElement("h3"); title.textContent = headings[policy]; card.append(title);
    const metrics = result.metrics;
    const text = document.createElement("p"); text.textContent = `${metrics.renewable_match_percent.toFixed(1)}% solar matching · ${metrics.grid_energy_kwh.toFixed(1)} kWh grid energy · ${metrics.average_preference_deviation_hours.toFixed(1)} h average shift · ${metrics.capacity_violation_hours} overload hours`;
    card.append(text);
    result.assignments.forEach(a => {
      const row = document.createElement("p"); row.textContent = `${a.workload_id}: preferred 18:00 → ${clock(a.scheduled_start)}–${clock(a.scheduled_end)}`; card.append(row);
    });
    grid.append(card);
  });
  panel.append(grid);
}
byId("home-compare").addEventListener("click", renderHouseholdExample);
byId("home-flex").addEventListener("change", () => {
  byId("home-results").textContent = "Flexibility changed. Select Compare household schedules to update the results.";
});
