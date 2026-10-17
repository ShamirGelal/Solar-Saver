"use strict";

const policies = [
  {key: "uncoordinated", name: "Uncoordinated", tag: "Baseline", description: "Workloads run as close to their preferred times as possible."},
  {key: "solar_only", name: "Solar-only", tag: "Solar first", description: "Shift toward solar, respecting capacity and allowed windows."},
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
  ["Workload completion", "completion_percent", "%"],
  ["Critical workload completion", "critical_completion_percent", "%"],
  ["Capacity violation hours", "capacity_violation_hours", "h"],
];
const number = (value, digits = 1) => new Intl.NumberFormat("en-US", {maximumFractionDigits: digits, minimumFractionDigits: digits}).format(value);
const byId = id => document.getElementById(id);
let report;
let selectedPolicy = "balanced";

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
      <div class="card-health"><span class="${item.unscheduled_count ? "warn" : ""}">${item.completed_count}/${report.workload_count} workloads completed</span><span class="${m.capacity_violation_hours ? "warn" : ""}">${m.capacity_violation_hours} h over capacity</span></div>
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
        ? "No critical workloads" : `${number(value, key === "average_preference_deviation_hours" ? 2 : 1)} ${unit}`;
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
  byId("chart-summary").textContent = `${name} policy · ${item.completed_count} of ${report.workload_count} workloads completed${item.unscheduled_count ? ` · ${item.unscheduled_count} could not be scheduled` : ""}`;
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
}

async function loadComparison() {
  byId("reload").disabled = true;
  byId("results").hidden = true;
  byId("results").setAttribute("aria-busy", "true");
  byId("error").hidden = true;
  byId("status").textContent = "Loading the comparison…";
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch("./comparison.json", {cache: "no-store", signal: controller.signal});
    const data = await response.json();
    if (!response.ok) throw new Error([data.error, data.detail].filter(Boolean).join(" ") || "The comparison could not be completed.");
    validateReport(data);
    report = data;
    renderCards();
    renderMetrics();
    renderChart();
    byId("results").hidden = false;
    byId("status").textContent = "Comparison ready · All three policies use the same scenario.";
  } catch (error) {
    byId("status").textContent = "";
    byId("error").textContent = error.name === "AbortError"
      ? "The comparison took too long to load. Please try again."
      : error instanceof TypeError ? "Could not load the comparison data. Check your connection, then try again." : error.message;
    byId("error").hidden = false;
  } finally {
    clearTimeout(timeout);
    byId("reload").disabled = false;
    byId("results").setAttribute("aria-busy", "false");
  }
}

document.querySelectorAll('input[name="policy"]').forEach(input => input.addEventListener("change", event => {
  selectedPolicy = event.target.value;
  if (report) renderChart();
}));
byId("reload").addEventListener("click", loadComparison);
loadComparison();
