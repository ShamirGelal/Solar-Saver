# Solar Saver

Solar Saver is a backend-first prototype that predicts a 24-hour solar supply
profile and coordinates synthetic Charlottesville workloads against that supply.
It compares three policies:

1. uncoordinated user-preferred scheduling;
2. solar-only scheduling;
3. balanced scheduling using solar supply, grid capacity, priority, preference,
   and fairness penalties.

The current forecaster is intentionally synthetic. It exists so every backend
component can be developed and tested before the ML artifact is ready.

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
python3 -m unittest discover -s tests -v
PYTHONPATH=. python3 scripts/run_demo.py
```

The demo uses only the Python standard library. Install `requirements.txt` when
the forecasting owner begins the data and scikit-learn implementation.

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
