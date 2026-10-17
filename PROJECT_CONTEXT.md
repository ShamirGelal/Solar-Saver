# Solar Saver project handoff

This document replaces the context that would otherwise have been carried by the
original planning chat. A teammate or coding agent should be able to clone the
repository, read this file and the applicable assignment under `instructions/`,
and continue without access to that chat.

## Hackathon context

Solar Saver is being developed for Girls Hoo Hack 2026. The event is space
themed. The team's intended prize strategy is:

1. Sustainability as the primary goal
2. AI/ML as a substantive technical tool
3. Best Beginner when the team satisfies the organizer's eligibility definition
4. Space relevance through satellite-derived observations and mission-control
   presentation, rather than decorative space branding alone

The team rejected an earlier food-recipe concept because ingredient-to-recipe
products already exist and the proposed implementation relied too heavily on a
pretrained generative model. The current direction deliberately gives the team
ownership of data preparation, model training, evaluation, simulation, and
scheduling logic.

## Final product vision

Solar Saver is a simulated city-scale demand-response system for a
Charlottesville district.

Many users have flexible electrical workloads, such as EV charging, laundry,
dishwashing, water heating, or battery charging. Each workload has a power
requirement, duration, allowed time window, preferred start time, priority, and
flexibility. If every user is moved to the single sunniest hour, the system can
create a new demand peak or exceed local capacity.

Solar Saver instead creates a coordinated schedule that balances:

- predicted solar availability;
- fixed and flexible demand;
- network capacity;
- workload deadlines and duration;
- user preferences;
- workload priority; and
- fairness of schedule displacement.

The project is a simulation, not a connection to a real utility or a claim to
control real Charlottesville infrastructure.

## What is innovative in the prototype

The prototype does not merely identify the hour with the most sunlight. It shows
why individually optimal decisions can produce a collectively bad outcome and
then coordinates many competing workloads.

The demonstration compares three policies:

1. `UNCOORDINATED`: users run tasks at their preferred times.
2. `SOLAR_ONLY`: workloads move toward the strongest solar supply without
   valuing convenience.
3. `BALANCED`: solar supply, capacity, preferences, priority, peak demand, and
   fairness are considered together.

The comparison is as important as the final schedule. It should demonstrate that
"send everything to noon" is not a sufficient solution.

## System architecture

```text
NASA POWER historical observations
                  |
                  v
        solar forecasting model
                  |
             SolarProfile
                  |
                  +--------------------+
                                       v
synthetic workload assumptions -> CityScenario
                                       |
                                       v
                     three scheduling strategies
                                       |
                                       v
                         ScheduleResult + metrics
                                       |
                                       v
                    future UI and comparison charts
```

The current scaffold runs without network access or trained artifacts by using
`SeasonalDemoForecaster`. That class is explicitly a placeholder. It allows the
demand and scheduling owners to work before the real model is integrated.

## Stable API contract

Shared types are defined in `solar_saver/domain.py`. Protocols are defined in
`solar_saver/contracts.py`.

### Forecasting

```python
SolarForecaster.predict(ForecastRequest) -> SolarProfile
```

`SolarProfile.supply_kw` contains one aggregate predicted solar-supply value for
each hour.

### Demand generation

```python
DemandGenerator.generate(
    solar_profile: SolarProfile,
    config: SimulationConfig,
) -> CityScenario
```

The same seed and inputs must produce an identical scenario.

### Scheduling

```python
LoadScheduler.schedule(
    scenario: CityScenario,
    strategy: Strategy,
    weights: SchedulerWeights,
) -> ScheduleResult
```

### UI and integration

```python
run_comparison(
    forecast_request=...,
    simulation_config=...,
    scheduler_weights=...,
    forecaster=...,
    demand_generator=...,
    scheduler=...,
) -> SimulationReport
```

The future UI should use `run_comparison` and `SimulationReport`. It should not
load scikit-learn models directly, parse NASA responses, or call private
scheduler helpers.

## Subproject 1: solar data and ML forecasting

Owner instructions: `instructions/01_solar_forecasting.txt`

The model architecture chosen during planning is tabular supervised regression,
preferably scikit-learn's `HistGradientBoostingRegressor`. It is not a neural
network or generative-AI wrapper.

The forecasting owner is responsible for:

- downloading and caching hourly NASA POWER data;
- cleaning timestamps and missing values;
- cyclical hour/day features and carefully shifted historical features;
- chronological train, validation, and test periods;
- a historical month/hour baseline;
- trained-model MAE and RMSE compared with that baseline;
- saving and loading the fitted artifact; and
- implementing `SolarForecaster` without changing its public interface.

Important modeling limitation: if the model does not receive genuine future
weather forecasts, describe its output as expected solar availability rather
than a precise day-ahead weather forecast. Never use future measurements as
training features for an earlier prediction.

## Subproject 2: synthetic city demand

Owner instructions: `instructions/02_demand_simulation.txt`

The demand owner creates a reproducible simulated population, initially around
100 users, with a 24-hour background-demand curve and flexible workloads.

Initial workload categories include:

- EV charging;
- laundry;
- dishwashing;
- battery charging; and
- water heating.

Every parameter must be presented as a simulation assumption unless backed by a
cited real dataset. The demand generator creates the scenario; it does not place
workloads into time slots.

## Subproject 3: scheduling and metrics

Owner instructions: `instructions/03_scheduler_metrics.txt`

The initial implementation is a deterministic greedy scheduler. For every
workload, it examines valid start times and scores candidate placements. The
balanced conceptual objective is:

```text
grid energy
+ user inconvenience
+ peak-demand penalty
+ unfairness penalty
+ a very large penalty for missed critical work
```

The existing greedy scheduler is a reference implementation, not a requirement
to use a particular final optimization technique. A mixed-integer optimizer is a
stretch goal only after invariants are thoroughly tested.

Priority applies to workloads, not the social worth of people. Critical loads
should be protected through transparent hard rules. User-declared flexibility
and preference should be inspectable and overridable. Do not train a synthetic
"who deserves power" classifier.

## Optional subproject 4: integration, testing, and UI

Owner instructions: `instructions/04_integration_testing_optional.txt`

With four people, the fourth person keeps `main` runnable, enforces the contracts,
merges one component at a time, owns end-to-end testing and dependency hygiene,
and begins the UI only after backend integration.

With three people, the demand-simulation owner should assume integration and UI
responsibility after the generator is stable because that primary subproject has
the least implementation uncertainty.

## Metrics and honest claims

Required comparison metrics include:

- grid energy used;
- solar energy used;
- unused solar energy;
- renewable matching percentage;
- peak total demand;
- average and maximum preference deviation;
- overall completion percentage;
- critical completion percentage; and
- capacity-violation hours.

If every task still consumes the same energy after rescheduling, Solar Saver has
shifted demand rather than saved total energy. Prefer claims such as:

- increased demand served during solar availability;
- reduced grid energy required in the simulation;
- reduced peak demand;
- reduced unused solar generation; and
- improved renewable-energy matching.

Do not calculate carbon savings without a defensible emissions factor.

## MVP scope

The MVP is intentionally limited to:

- one simulated Charlottesville district;
- one 24-hour period;
- hourly time slots;
- approximately 100 synthetic users;
- four or five flexible workload types;
- one fixed background-demand profile;
- one solar-supply prediction;
- one capacity profile;
- three scheduling policies; and
- aggregate comparison statistics.

Non-goals for the hackathon MVP:

- real utility integration;
- individual user accounts;
- billing or electricity-market settlement;
- automatic control of physical appliances;
- a full city digital twin;
- precise carbon accounting;
- an ML system that ranks the worth of individual users; and
- production reliability or cybersecurity claims.

## Current repository state

The initial scaffold includes:

- stable domain types and protocols;
- a deterministic synthetic solar fallback;
- a deterministic synthetic workload generator;
- uncoordinated, solar-only, and balanced reference schedulers;
- strategy-independent metrics;
- an end-to-end comparison pipeline;
- an offline demo script; and
- contract smoke tests.

The following work remains intentionally incomplete:

- NASA POWER ingestion;
- feature engineering;
- trained forecasting model and artifact;
- comprehensive subsystem tests;
- validated workload assumptions;
- scheduler refinement and fairness evaluation;
- persistent experiment outputs;
- UI, visualization, and deployment; and
- final demo narrative and video.

## Team workflow

Recommended branches:

```text
feature/solar-forecasting
feature/demand-simulation
feature/scheduler-metrics
feature/integration-ui
```

Each owner should:

1. Clone the repository.
2. Read `AGENTS.md`, this file, and the matching assignment.
3. Create the assigned feature branch.
4. Run the baseline tests.
5. Work only within the documented ownership boundary.
6. Add focused tests.
7. Merge current `main` into the feature branch before handoff.
8. Push the feature branch and open a pull request into `main`.
9. Report interfaces, assumptions, commands, observed tests, and limitations.

The integration owner merges one branch at a time and reruns the complete suite
after each merge. GitHub, not chat history, is the source of truth for code.

## Local setup and verification

```bash
git clone https://github.com/ShamirGelal/Solar-Saver.git
cd Solar-Saver
python3 -m unittest discover -s tests -v
PYTHONPATH=. python3 scripts/run_demo.py
```

The existing demo requires only the standard library. Install
`requirements.txt` when beginning the real data and ML implementation.

## Suggested first message in a new coding chat

```text
I am assigned [solar forecasting / demand simulation / scheduler and metrics /
integration and UI]. Read the repository AGENTS.md, PROJECT_CONTEXT.md, and the
matching file under instructions/. Inspect the current branch and run the
baseline tests. Work only within the documented ownership boundary, preserve
the shared API contracts, and report any contract change you believe is needed
before implementing it.
```

## Open decisions

The team still needs to decide:

- the official organizer definition of a beginner team;
- exact NASA POWER parameters and historical period;
- whether the model represents expected solar availability or integrates a real
  weather forecast;
- final synthetic capacity and workload distributions;
- acceptable balanced-scheduler weight defaults;
- whether an optimization library is worth the additional integration risk; and
- the final UI framework and deployment target.

Record decisions in this document or another versioned repository document so
new chats and computers do not depend on private conversation history.
