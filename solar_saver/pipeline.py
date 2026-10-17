"""One stable backend entry point for scripts and the future UI."""

from __future__ import annotations

from .contracts import DemandGenerator, LoadScheduler, SolarForecaster
from .domain import (
    ForecastRequest,
    SchedulerWeights,
    SimulationConfig,
    SimulationReport,
    Strategy,
    StrategyReport,
)
from .metrics import evaluate_schedule


def run_comparison(
    *,
    forecast_request: ForecastRequest,
    simulation_config: SimulationConfig,
    scheduler_weights: SchedulerWeights,
    forecaster: SolarForecaster,
    demand_generator: DemandGenerator,
    scheduler: LoadScheduler,
) -> SimulationReport:
    solar_profile = forecaster.predict(forecast_request)
    scenario = demand_generator.generate(solar_profile, simulation_config)
    reports: dict[Strategy, StrategyReport] = {}

    for strategy in Strategy:
        result = scheduler.schedule(scenario, strategy, scheduler_weights)
        reports[strategy] = StrategyReport(
            result=result,
            metrics=evaluate_schedule(scenario, result),
        )

    return SimulationReport(
        scenario=scenario,
        solar_profile=solar_profile,
        strategies=reports,
    )
