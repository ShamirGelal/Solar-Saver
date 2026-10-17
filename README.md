# Solar Saver

> New teammate or new coding chat? Start with [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md),
> then read your assignment under [`instructions/`](instructions/). Codex and
> compatible coding agents should also read the root [`AGENTS.md`](AGENTS.md)
> automatically when opened from this repository.

Solar Saver is a backend-first prototype that predicts a 24-hour solar supply
profile and coordinates synthetic Charlottesville workloads against that supply.
It compares three policies:

1. uncoordinated user-preferred scheduling;
2. solar-only scheduling;
3. balanced scheduling using solar supply, grid capacity, priority, preference,
   and fairness penalties.

The application uses the trained weather-aware forecaster when its local artifact
is available. Missing artifacts or unavailable weather data trigger a clearly
labeled synthetic seasonal fallback.

## Recommended team

Three primary implementers are optimal:

- Solar data and forecasting
- Demand simulation
- Scheduling and metrics

A fourth teammate is useful as integration, testing, deployment, and demo owner.
Using only two computers creates a bottleneck between modeling and scheduling and
does not simplify the interfaces.

## Stable API

Shared objects live in `solar_saver/domain.py`. Component protocols live in
`solar_saver/contracts.py`. Do not change either file independently after work
is divided. Propose shared changes to the whole team first.

The future UI should call only:

```python
from solar_saver.pipeline import run_comparison
```

The pipeline accepts one implementation of each protocol:

- `SolarForecaster`
- `DemandGenerator`
- `LoadScheduler`

This makes implementations replaceable without changing their consumers.

## Run locally

From this directory, use Python 3.10+ and install dependencies in an isolated
environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
PYTHONPATH=. .venv/bin/python scripts/run_demo.py
```

Install requirements even for the seasonal demo: the forecasting package currently
exports its trained model eagerly, which imports the ML packages. After installation,
explicit seasonal demo mode needs no network connection or trained artifact.

To produce the trained artifact, follow
[`solar_saver/forecasting/README.md`](solar_saver/forecasting/README.md).
The runtime loads `artifacts/solar_forecaster.joblib` relative to the repository,
and requests live Open-Meteo weather with a five-second connection/read timeout.
Missing artifacts, weather request failures, and unusable weather responses
select `SeasonalDemoForecaster`; its original synthetic warning is retained and
a fallback reason is added. Invalid model artifacts and unrelated backend errors
remain errors. The command-line demo prints the model and warnings to stderr,
keeping its existing metrics JSON on stdout.

For a deterministic offline run, set `SOLAR_SAVER_FORECAST_MODE=demo` (PowerShell:
`$env:SOLAR_SAVER_FORECAST_MODE='demo'`). Set it to `auto` to restore automatic
selection. This setting applies to the CLI, local UI server, and static exporter.
Dependencies must still be installed for offline mode. Tests use controlled
forecasters and weather responses; they do not require a local artifact or internet.

## Open the demo UI

From the repository root, run:

```bash
.venv/bin/python -m solar_saver.ui
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in a browser. Python 3.10+
is recommended. Install the dependencies above first; no frontend build step is
needed. Automatic trained prediction needs an artifact and internet; the seasonal
fallback works offline. Stop
the server with Ctrl+C. If port 8000 is busy, run
`.venv/bin/python -m solar_saver.ui --port 8001` and open that port instead. The server
listens on your computer's loopback address and is intended for a local demo.

The page offers two modes:

- **My loads:** add, edit, and remove up to 100 appliance loads. Editable presets
  cover EV charging, laundry, dishwashing, battery charging, and water heating;
  custom names and values are supported. Enter power in kW, whole-hour duration,
  earliest start, finish deadline, preferred start, priority, and willingness to
  shift (0–1). The entire duration must fit within the same day's allowed window,
  including at the preferred start; 24:00 means the end of the day. Presets are
  simulation assumptions, not measured appliance data. Entries live in the tab
  and are cleared by a page refresh.
- **District demo:** the original deterministic 100-household synthetic scenario.
  “View district demo” restores this comparison without clearing entered loads.

“Compare my loads” runs the three existing scheduling policies on the entered
loads plus the existing simulated district background. Entered loads replace the
synthetic flexible population. Both modes use October 18, 2026, seed 42, 500 kW
of community solar, a 310 kW total-demand feeder limit, and default scheduler weights.
These remain district-scale simulation settings, not a household service rating.
The feeder limit is intentionally set just below the uncoordinated peak so the
demo represents a constrained local grid; it is an explicit scenario assumption,
not a measured Charlottesville feeder rating.
Solar supply uses the same automatic trained-model selection and labeled fallback as the district demo. The selected model and forecast warnings appear above the results.

Results include a selectable 24-hour power chart, accessible hourly data,
completion counts, and the full metrics table. In custom mode an appliance table
shows each load's actual scheduled interval, start-time shift, requested energy,
and any unfinished work. Policy selection updates both the chart and appliance
table. Editing or deleting a load hides stale custom results until recomputed.
“Reload comparison” reruns the most recently requested mode. Critical priority
is an explicit scheduling order rule, not a guarantee of completion.

The UI calls `run_comparison` and adapts its `SimulationReport` to a JSON response
at `GET /comparison.json` (also available at `GET /api/comparison`). Custom
comparisons use `POST /api/comparison` with a JSON object containing a `workloads`
list. Each item contains `workload_id`, `category`, `power_kw`, `duration_hours`,
`earliest_start`, `latest_finish`, `preferred_start`, `priority`, and `flexibility`.
IDs must be unique. Requests are limited to 100 loads, 64-character names/IDs,
finite positive power up to 10,000 kW, and a 64 KiB JSON body. Malformed JSON
returns 400; invalid loads return 422. Missing local dependencies return an
actionable 503 setup message. Responses include workloads and per-policy
assignments as well as aggregate metrics. The UI does not read
saved outputs or private subsystem files.
This endpoint is a local UI adapter, not a new shared subsystem contract. No
shared domain types, protocols, or backend algorithms are changed. A UI-owned
`EnteredLoadDemandGenerator` implements the existing demand protocol. Backend
failures produce an error with a retry button; infeasible coordinated schedules
are reported instead of replaced with made-up results. Valid scenarios with
unfinished workloads still show their completion counts and energy metrics.

Chart values are kW; one-hour slots sum to kWh in the metrics. Scheduling shifts
electricity use rather than inherently reducing requested energy. Read grid
energy alongside completion: unfinished work can reduce served energy. Average
preference deviation covers completed workloads only; a “No critical workloads”
label avoids presenting the backend's empty-set completion convention as evidence
of critical-load protection. Greedy scheduling is deterministic, but not globally
optimal and does not guarantee fairness across days.

UI integration checks are included in the regular test suite:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Input validation, request handling, static-export capabilities, and the custom
pipeline can also be tested without live weather or network sockets. These
tests inject a fixed test solar profile and exercise the real scheduler:

```bash
python3 -m unittest discover -s tests -p test_ui_inputs.py -v
```

## GitHub Pages demo

The published demo is available at
[shamirgelal.github.io/Solar-Saver](https://shamirgelal.github.io/Solar-Saver/).
GitHub Pages serves static files, so the deployment workflow runs the existing
Python pipeline at build time and exports the fixed comparison alongside the
page. The hosted “Reload comparison” button reloads these precomputed results;
the local Python server recomputes them. Chart selection and the hourly table
work in both versions. The static export sets `supports_custom_loads` to false:
the load editor remains available for preparing inputs, while custom comparison
is disabled with an explanation that it requires the local app. This does not
run Python or train a model in the browser. Interactive hosted scheduling needs
a deployed Python backend; the Pages workflow remains a fixed demo.

Export uses the same automatic model selection. GitHub's clean checkout has no
trained artifact, so the current workflow publishes a labeled seasonal fallback.
A local export with an artifact and available weather publishes trained results.
To deploy trained results from CI, provision the artifact separately before the
export step; never commit it to Git. Published results retain the model and
warning from the time of export.

To build and preview the same static site locally:

```bash
python -m solar_saver.ui.export --output-dir outputs/pages
python -m http.server 8002 --bind 127.0.0.1 --directory outputs
```

Open [http://127.0.0.1:8002/pages/](http://127.0.0.1:8002/pages/).
The subdirectory preview also checks repository-relative asset and data URLs.
Generated files stay under ignored `outputs/`; they are deployment assets, not
shared subsystem interfaces or committed experiment output.

`.github/workflows/static.yml` tests and builds pull requests. On `main`, it
deploys only the generated `outputs/pages` directory, including a root
`index.html`, styles, scripts, and JSON results. In repository Settings → Pages,
the publishing source must be **GitHub Actions**. A failing backend or test
stops deployment rather than publishing incomplete or fabricated results.

## Branch ownership

Suggested branches:

- `forecasting`
- `demand-simulation`
- `scheduler-metrics`
- `integration-ui` (optional fourth teammate)

Prefer small commits. Merge the contracts and smoke test first, then merge each
subsystem one at a time. Run the full test suite after every merge.

## Integration rule

Subsystems exchange domain objects, not files with undocumented formats. Files
under `data/`, `artifacts/`, and `outputs/` are implementation details and must
not become cross-team APIs.
