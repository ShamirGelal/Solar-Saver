# Solar Saver repository instructions

Solar Saver is a backend-first hackathon prototype. It predicts a 24-hour solar
supply profile for a simulated Charlottesville district, generates synthetic
flexible electrical workloads, and compares scheduling policies that balance
renewable-energy matching, grid capacity, user preference, priority, and
fairness.

## Before working

- Read `PROJECT_CONTEXT.md` for the product decisions and architecture relevant
  to the task.
- Read the matching file under `instructions/` when assigned a subsystem.
- Check the current branch and working tree before editing.
- Run the existing tests before changing shared behavior.

## Stable boundaries

- `solar_saver/domain.py` owns shared domain types.
- `solar_saver/contracts.py` owns component protocols.
- `solar_saver/pipeline.py::run_comparison` is the backend entry point for the
  future UI.
- Do not change these shared contracts independently. Propose the change to the
  integration owner and every affected subsystem owner first.
- Subsystems exchange domain objects. Do not make undocumented files under
  `data/`, `artifacts/`, or `outputs/` into cross-team APIs.

## Ownership

- Solar data and forecasting: `solar_saver/data/`,
  `solar_saver/forecasting/`, training scripts, and forecasting tests.
- Demand simulation: `solar_saver/demand.py`, demand tests, and documented demo
  fixtures.
- Scheduling and metrics: `solar_saver/scheduling.py`,
  `solar_saver/metrics.py`, and their tests.
- Integration and UI: `solar_saver/pipeline.py`, end-to-end tests, dependency
  hygiene, documentation, deployment, and later UI files.

Stay within the assigned ownership boundary. Do not rewrite another subsystem
to make local work easier. Coordinate through the shared contracts.

## Required invariants

- Time is represented by 24 one-hour slots for the MVP.
- Power profiles use kW. Summed one-hour slots are reported as kWh.
- Solar predictions contain exactly 24 finite, nonnegative values.
- Synthetic scenarios are deterministic for the same seed.
- Scheduled workloads remain inside their allowed windows and run for their
  requested duration.
- Balanced and solar-only schedules do not exceed configured capacity.
- A completed workload's requested energy is conserved when it is rescheduled.
- Never describe synthetic Charlottesville demand as observed utility data.
- Scheduling generally shifts energy use; do not claim total energy savings
  unless the implementation actually reduces kWh.
- Do not let an ML model decide which person deserves electricity. Critical
  workload protection must be an explicit, inspectable rule.

## Verification

From the repository root, run:

```bash
python3 -m unittest discover -s tests -v
PYTHONPATH=. python3 scripts/run_demo.py
```

Add focused tests for changed behavior. After edits, also run `git diff --check`.
Report observed test results; do not treat intended behavior as verification.

## Collaboration

- Work on the assigned feature branch; do not push directly to `main`.
- Pull and merge current `main` before opening or updating a pull request.
- Prefer small commits limited to one subsystem.
- Never force-push shared branches or commit secrets, raw large downloads,
  trained artifacts, caches, or generated outputs.
- The integration owner merges one subsystem at a time and reruns the full test
  suite after every merge.
