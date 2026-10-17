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

From this directory:

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
PYTHONPATH=. python3 scripts/run_demo.py
```

Install the requirements in your Python environment before running either demo.
On Windows, the local environment's interpreter is `.venv\Scripts\python.exe`;
set `$env:PYTHONPATH='.'` in PowerShell before running scripts directly.

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
python -m solar_saver.ui
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in a browser. Python 3.10+
is required; use `python3` instead of `python` if that is your Python 3 command.
Install `requirements.txt` first. Automatic trained prediction needs a local
artifact and internet access; the seasonal fallback works offline. Stop the
server with Ctrl+C. If port 8000 is busy, run
`python -m solar_saver.ui --port 8001` and open that port instead. The server
listens on your computer's loopback address and is intended for a local demo.

The page compares all three policies, with a selectable 24-hour power chart,
an accessible hourly data table, completion counts, and the full metrics table.
“Reload comparison” repeats the same workload scenario: October 18, 2026,
100 synthetic households with one flexible request each, seed 42, 300 kW installed solar, 500 kW total-demand
capacity, and default scheduler weights. It is deliberately a fixed demo rather
than an experiment editor. The demand is simulated Charlottesville demand,
not observed utility data. The page displays the selected model and any fallback
warning. In automatic mode solar predictions can change as weather forecasts
update. This fixed demo date must be within the weather provider's supported
date range for trained inference; otherwise the demo displays the fallback reason.

The UI calls `run_comparison` and adapts its `SimulationReport` to a JSON response
at `/comparison.json` (also available at `/api/comparison`); it does not read
saved outputs or private subsystem files.
This endpoint is a local UI adapter, not a new shared subsystem contract. No
shared domain types, protocols, or backend algorithms are changed. Backend
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
python -m unittest discover -s tests -v
```

## GitHub Pages demo

The published demo is available at
[shamirgelal.github.io/Solar-Saver](https://shamirgelal.github.io/Solar-Saver/).
GitHub Pages serves static files, so the deployment workflow runs the existing
Python pipeline at build time and exports the fixed comparison alongside the
page. The hosted “Reload comparison” button reloads these precomputed results;
the local Python server recomputes them. Chart selection and the hourly table
work in both versions. This does not run Python or train a model in the browser.
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
