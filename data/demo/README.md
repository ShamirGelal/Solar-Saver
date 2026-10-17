# Demand simulation fixtures

Christopher confirmed on October 17, 2026 that one user represents one household.
For this MVP, every household contributes exactly one modeled flexible task per
day. That is a deliberate simplification, not a claim that homes use only one
appliance per day. Multiple requests per home are deferred to preserve existing
UI integration expectations. These assumptions are synthetic, not measured
Charlottesville behavior.

## Fixed benchmark plan (recorded before implementation)

`demand_cases.json` fixes 100/500 households, seeds 7/42/2026, and four cases:
normal, evening congestion, constrained capacity, and no flexibility. Never
select only seeds/cases in which a preferred scheduling strategy wins.

- Capacity is total neighborhood demand, including solar-served demand.
- For scale comparisons the fixture explicitly supplies 5 kW capacity and 3 kW
  installed solar per household. The generator must not scale these inputs.
- Constrained capacity uses 1.9 kW per household. Background should still fit;
  some flexible work may be unfinished. Report completion together with energy.
- The evening case replaces windows with 18:00-24:00 and preference 19:00. It is
  a separately labeled hypothetical population, not inferred household behavior.
- The no-flexibility case fixes each task at its preferred time. It exposes
  cases where scheduling cannot improve solar matching.
- One generated scenario is passed to all three policies, with identical solar
  and default weights. The helper never implements a scheduler or metric.
- Generation timing: seven batches of 100 calls for each count and seed, using
  normal capacity. Report median and range of per-call batch averages. This is
  not end-to-end runtime or individual-call tail latency. Reuse the method on
  the same machine before/after changes. Working budgets: under 10 ms for 100
  households and under 50 ms for 500; these are demo goals, not guarantees.
- Acceptance: finite nonnegative 24-hour profiles, deterministic generation,
  valid complete task windows, unique IDs, preserved solar/capacity, exact
  requested-energy accounting (allowing floating-point comparison tolerance),
  all existing tests passing and no ownership violations.

Run `python data/demo/benchmark_demand.py --output outputs/demand-benchmark.json`.
Results are ignored local experiment outputs. These fixtures and the helper
are demand-owner test/demo material, not a new shared subsystem interface.

## Grading evidence

The self-review uses the requested 100-point rubric:

| Area | Max | Evidence required |
|---|---:|---|
| API and ownership | 25 | Unchanged signature/types (5), allowed paths (5), pipeline (5), UI (5), domain output (5) |
| Validity and energy | 25 | Profiles/units (5), complete windows (5), energy accounting (5), explicit capacity semantics (5), population scaling/no double count (5) |
| Determinism and edges | 15 | Same input reproducibility (5), RNG/solar independence (5), invalid/empty boundaries (5) |
| Assumptions | 15 | Documented synthetic values (5), meaningful availability (5), empirical fidelity/limitations (5) |
| Tests and integration | 15 | Focused demand tests (5), current full suite/demo (5), fixed scenario evidence (5) |
| Runtime and maintenance | 5 | Timing budget/variability (3), offline standard-library simplicity (2) |

A failed required test, broken contract, invalid output, or ownership violation
blocks completion regardless of score. This is a self-assessment of the MVP,
not independent validation of a utility model.

## Generator assumptions and integration handoff

`SyntheticDemandGenerator.generate(SolarProfile, SimulationConfig) -> CityScenario`
retains its existing signature and shared domain types. Construct it without
arguments, as before. All generation is offline with the Python standard library.
The UI and scheduling owners do not need to parse these fixtures or this file.

- `number_of_users` counts households. It must be an integer >= 0, not a boolean.
- `random_seed` must be an integer (negative seeds are supported), not a boolean
  or `None`. Same seed and inputs reproduce the same scenario in this version.
- `grid_capacity_kw` is a finite, nonnegative Python int/float; it is copied
  unchanged to all 24 hours. Solar does not increase this total-demand limit.
- `SolarProfile.supply_kw` must be an immutable tuple of exactly 24 finite,
  nonnegative numeric values, with finite total daily energy. The exact input
  tuple is passed through. Different solar/capacity inputs never alter requests.
- Zero households produce zero background and no tasks, while keeping the
  supplied solar/capacity. Zero capacity is supported for this empty population.
- At least four categories are supported; all five appear in the fixed 100/500
  household fixtures. Random sampling does not guarantee every category in
  every population, especially a small one. No extra tasks are forced in.
- There are no critical tasks. IMPORTANT prioritizes the appliance request,
  not a person's worth. UI empty-set critical completion is not a safety claim.

| Category | Equivalent kW | Whole hours | Requested kWh | Priority | Broad daytime window | Usual preferred start |
|---|---:|---:|---:|---|---|---|
| EV charging | 7.2 | 3 | 21.6 | Important | 08:00-24:00 | 13:00 for daytime availability; 19:00 otherwise |
| Laundry | 0.8 | 1 | 0.8 | Flexible | 08:00-20:00 | 14:00 |
| Dishwasher | 1.2 | 2 | 2.4 | Flexible | 08:00-23:00 | 19:00 |
| Battery charging | 2.0 | 3 | 6.0 | Flexible | 07:00-22:00 | 13:00 |
| Water heating | 3.0 | 1 | 3.0 | Important | 05:00-22:00 | 18:00 |

`IMPORTANT` is the household demo's high-priority tier; `FLEXIBLE` is its low-
priority tier. Lighting and other always-needed household electricity remain in
fixed background demand, so the scheduler cannot delay or drop them. They are
not added again as flexible tasks because that would double-count their energy.
The existing scheduler places important tasks before flexible tasks when they
compete for limited capacity.

The category selection is uniform (20% each). These are synthetic daily request
shares, not appliance ownership rates. Values retain the scaffold's power and
duration assumptions. They are not manufacturer ratings or measured cycle data.

Every household samples one availability pattern: 50% evening, 30% daytime,
20% tight. Evening availability begins at 16:00, 17:00, or 18:00 and preferred
starts move to at least 18:00 (subject to task completion before its deadline).
Daytime EVs can charge midday because the vehicle is assumed present. Tight
windows permit zero or one hour before/after the preferred start. A task never
wraps past midnight or runs in fragments. The preferred start is always a
complete feasible placement within its window, before considering capacity.

Preferred times have a small seeded jitter. Base flexibility coefficients are
EV 0.7, laundry 0.8, dishwasher 0.7, battery 0.9, and water heating 0.4. Evening
availability multiplies them by 0.75; tight availability by 0.25. These describe
assumed willingness, not learned behavior. Actual availability is enforced by
the windows, not inferred by the scheduler from the flexibility coefficient.

### Background demand and capacity

For 100 households the original synthetic curve is preserved:

```text
reference_kw[h] = round(120 + 35*exp(-((h-8)/2.2)^2)
                          + 65*exp(-((h-19)/2.8)^2), 3)
background_kw[h] = round(reference_kw[h] * households / 100, 3)
```

It represents residual fixed household demand, excluding the single flexible
request already modeled separately for that household. It is not an imported
whole-home trace with extra tasks added on top. The curve is an assumption;
there is no appliance-level measurement proving that decomposition. Other
appliances and unmodeled consumption remain in the background aggregate.

This gives 185 kW peak background at 100 households, and 925 kW at 500. The
default 500 kW capacity therefore supports the ordinary 100-household case but
not 500 households. Callers must explicitly provide sufficient capacity (the
scale benchmark uses 2500 kW). If background alone exceeds capacity, generation
raises a descriptive ValueError with the required minimum. It neither clips
demand nor raises capacity automatically. Equality at the background peak is
allowed and does not guarantee that all additional tasks can finish.

### Limits

This is aggregate hourly demand, not voltage/power-flow analysis, a feeder
network, a thermal water-heater model, or a battery state-of-charge simulation.
Battery charging has no discharge. Day boundaries, variable-power cycles,
household correlations, multiple requests, and measured calibration are future
work. No total-kWh, monetary, or carbon savings are claimed from load shifting.
Capacity can leave tasks unfinished; always show completion with energy.

The implementation is O(households + 24) in time and output memory. The tested
workload range is 0-500 households; larger allocations have no runtime/memory
guarantee. Repeatability is for the same implementation/runtime, not a promise
of unchanged random populations after future code revisions.

## Review record and results (October 17, 2026)

Baseline commit: `d2d84ed726e8b9ed7bb19dbb8d8c854f9f3ab20c`.
Working branch: `feature/demand-simulation`.
Recovery branch: `checkpoint/demand-baseline-d2d84ed`.
The fresh baseline working tree was clean. No shared contracts, scheduler,
forecasting, metrics, UI files, or dependency declarations were changed.

The scores below are provisional self-review estimates at each stage, using
the rubric above. They are not independent assessments; pending gates remained
blocking regardless of the score. Each pass inspected a distinct requirement;
passes without a justified code change retained the verified implementation.

| Pass | Review and action | Evidence / outcome | Provisional score |
|---|---|---|---:|
| 1 | Repository, baseline, recovery | Read current ownership/consumers; 39 original tests pass; original demo succeeds | 66 |
| 2 | Contracts and fixed benchmark | Preserved one task/user expected by UI; recorded 24 baseline cases; new acceptance tests exposed 22 failing subtests and 3 errors in old generator | 66 |
| 3 | Availability assumptions | Added daytime/evening/tight windows and named immutable appliance records; 4 targeted availability/energy/pipeline tests pass | 74 |
| 4 | Population and capacity | Scaled fixed background; empty population has no demand; reject insufficient capacity; 3 targeted boundary tests pass | 81 |
| 5 | Units, windows, input validation | Reject malformed counts/seeds/capacity/solar; keep complete valid preferences and documented energy; 19 demand tests pass | 89 |
| 6 | Determinism and edge cases | Added mutable-input and overflowing-energy checks; verified independent RNG, solar independence and stable population prefixes | 92 |
| 7 | Scenario robustness | Added fixture integration/unfinished-work checks; 24 demand tests pass across fixed counts/seeds/cases | 94 |
| 8 | Runtime and simplicity | Same benchmark method stays well below stated budgets; no optimization or extra dependencies justified | 95 |
| 9 | Full integration | 63 tests pass, including scheduler, metrics, UI HTTP and static export; demo runs through unchanged pipeline | 96 |
| 10 | Canceled at user request | No additional review or test cycle; handoff only uses existing final evidence | N/A |

Nine review passes are complete. The tenth was canceled at Christopher's request. During handoff, the existing final test log was collected: 63 tests passed in 1.474 seconds, including the final large-integer validation case. No additional test run was started. The file audit and git diff --check passed within the demand ownership boundary.

Final rubric breakdown: API/ownership 25/25; validity/energy 25/25;
determinism/edges 15/15; assumptions 11/15; tests/integration 15/15;
runtime/maintenance 5/5. Total: **96/100 for this scoped MVP**.

Remaining deductions and next improvements:

- 3 points: appliance/background values and population shares are synthetic,
  uncalibrated assumptions. Improve with an appropriately selected residential
  end-use dataset, document provenance, and compare daily energy and hourly
  peaks against that reference. Do not introduce that dataset as a runtime
  requirement or claim that a modeled dataset is observed Charlottesville use.
- 1 point: one constant-power task per household, hourly blocks, and no thermal
  or battery-state model limit physical fidelity. Finer time steps or multiple
  tasks require team agreement and consumer tests; they are deferred rather
  than changing shared contracts during this implementation.

All implementation defects found within the assigned scope were addressed.
The remaining deductions are disclosed model limitations, not hidden failures.

### Generation benchmark

Measured on the same Windows machine using CPython 3.13.7. Each value is the
median per-call time from seven batches of 100 calls. Final ranges show the
smallest/largest batch-average per-call time. Results are machine-dependent.

| Households | Seed | Baseline ms | Final ms | Final range ms |
|---|---:|---:|---:|---|
| 100 | 7 | 0.2107 | 0.2676 | 0.2556-0.3517 |
| 100 | 42 | 0.2092 | 0.2946 | 0.2518-0.3356 |
| 100 | 2026 | 0.1726 | 0.2898 | 0.2527-0.3946 |
| 500 | 7 | 0.8043 | 1.3373 | 1.2407-1.4302 |
| 500 | 42 | 0.8308 | 1.3595 | 1.3330-1.4413 |
| 500 | 2026 | 0.8213 | 1.3298 | 1.2318-1.4254 |

The final version is modestly slower because it validates inputs and generates
more varied availability. It remains far below the 10/50 ms demo budgets. No
speedup is claimed. Baseline and final use identical configuration inputs but
the improved generator changes the population, so energy differences between
versions are not an optimizer comparison.

### Example output and policy comparison

At 100 households, seed 42, output has 100 tasks: 23 EV, 27 laundry, 15 water
heating, 18 dishwasher and 17 battery tasks. Requested flexible energy is
708.6 kWh. Background energy is 3335.579 kWh and peak background is 185 kW.
The first task is:

```json
{
  "workload_id": "load-0000",
  "user_id": "user-0000",
  "category": "ev_charging",
  "power_kw": 7.2,
  "duration_hours": 3,
  "earliest_start": 16,
  "latest_finish": 24,
  "preferred_start": 19,
  "priority": "important",
  "flexibility": 0.525
}
```

This is an unscheduled request: household 0 needs 21.6 kWh from a three-hour
EV charging block between 16:00 and midnight, preferably starting at 19:00.

The normal fixture uses the existing seasonal solar fallback and 500 kW capacity:

| Policy | Completed | Grid kWh | Solar kWh | Peak kW | Mean shift hours |
|---|---|---:|---:|---:|---:|
| Uncoordinated | 100/100 | 2771.132 | 1273.047 | 336.016 | 0 |
| Solar only | 100/100 | 2723.932 | 1320.247 | 330.016 | 0.42 |
| Balanced | 100/100 | 2735.932 | 1308.247 | 336.016 | 0.11 |

Balanced uses 35.2 kWh less grid electricity than uncoordinated in this one
scenario, with identical completed task energy. It does not reduce peak here,
and solar-only uses more solar. These are illustrative scenario results, not
guarantees of savings or superiority across neighborhoods.

At 190 kW capacity, seed 42, both coordinated policies complete 60/100 tasks,
leave 40 unfinished, and have zero capacity-violation hours. Uncoordinated
completes all tasks but exceeds capacity in five hours. At 500 households and
950 kW capacity, balanced completes 298/500 tasks versus solar-only 310/500.
This exposes an actual tradeoff, not evidence that balanced always wins.

The no-flexibility case yields identical placement and energy across all three
policies. Evening-only tasks cannot use midday solar in this model; apparent
tiny energy differences from floating-point summation are not improvements.
All 24 generated benchmark cases are deterministic and have valid profiles.
The fixture acceptance tests check all three policies' task accounting,
duration/windows, completed energy, and coordinated capacity constraints.

## Verification and safe recovery

Standard commands from the repository root:

```text
python -m unittest discover -s tests -v
python data/demo/benchmark_demand.py --output outputs/demand-final.json
git diff --check
```

For the demo, set PYTHONPATH to the repository root, then run
`python scripts/run_demo.py` (PowerShell: `$env:PYTHONPATH = '.'`).

On the implementation host, the ordinary Python commands were unusable Windows
aliases. Verification used a temporary, official CPython 3.13.7 embedded runtime
outside the checkout. Initial test errors came from Windows temporary-directory
permissions, not application assertions. Setting tempfile.tempdir to a writable
workspace test directory resolved them without changing application/tests.

Actual PowerShell verification invocation on that host:

```powershell
& '..\.solar-saver-tools\python\python.exe' -c "import sys,tempfile,pathlib,unittest; sys.path.insert(0,'.'); tempfile.tempdir=str(pathlib.Path('../.solar-saver-tools/test-temp').resolve()); r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('tests')); sys.exit(not r.wasSuccessful())"
& '..\.solar-saver-tools\python\python.exe' -c "import sys,runpy;sys.path.insert(0,'.');runpy.run_path('scripts/run_demo.py',run_name='__main__')"
& '..\.solar-saver-tools\python\python.exe' data/demo/benchmark_demand.py --output outputs/demand-final.json
git diff --check
```

Observed baseline: 39 tests pass. The demand implementation originally passed
63 tests. After fast-forwarding this branch to GitHub `main` at `cf22904`, the
combined repository passes 79 tests, including 25 demand tests, the forecasting
owner's trained-model pipeline integration, scheduler priority behavior, metrics,
and UI HTTP/static export. The demo and fixed benchmark complete. This is not a
new manual visual audit or live-site deployment.

Local ignored evidence files: `outputs/demand-baseline.json`,
`outputs/demand-final.json`, `outputs/demand-tests-final.txt`, and
`outputs/demand-demo-final.json`. Do not commit generated output or caches.

To recover the untouched starting version while preserving all later work, open
a separate baseline checkout rather than resetting or cleaning this branch:

```text
git worktree add --detach ../Solar-Saver-baseline checkpoint/demand-baseline-d2d84ed
```

Use an unused destination. The recovery reference points at the original commit;
the feature checkout retains this work. Publication status is reported in the handoff; no deployment or merge into main is part of this change.

For integration: use the existing no-argument generator and pipeline unchanged.
Label users as households when the UI owner next updates copy. For 500-household
experiments, explicitly provide capacity exceeding the 925 kW background peak
with appropriate flexible-load headroom. Forecasters must return the agreed
24-value tuple. All new helpers/docs stay under the demand ownership boundary.
