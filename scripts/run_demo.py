"""Run the backend with automatic trained-model selection and demo fallback."""

from dataclasses import asdict
from datetime import date
import json
import sys

from solar_saver.demand import SyntheticDemandGenerator
from solar_saver.domain import ForecastRequest, SchedulerWeights, SimulationConfig
from solar_saver.runtime import RuntimeForecaster
from solar_saver.pipeline import run_comparison
from solar_saver.scheduling import GreedyLoadScheduler


def main() -> None:
    report = run_comparison(
        forecast_request=ForecastRequest(
            latitude=38.0293,
            longitude=-78.4767,
            target_date=date(2026, 10, 18),
            installed_capacity_kw=20_000.0,
        ),
        simulation_config=SimulationConfig(
            number_of_users=4_000,
            random_seed=42,
            grid_capacity_kw=20_000.0,
        ),
        scheduler_weights=SchedulerWeights(),
        forecaster=RuntimeForecaster(),
        demand_generator=SyntheticDemandGenerator(),
        scheduler=GreedyLoadScheduler(),
    )
    print(f"Solar model: {report.solar_profile.model_name}", file=sys.stderr)
    for key in ("fallback_reason", "warning"):
        if key in report.solar_profile.metadata:
            print(report.solar_profile.metadata[key], file=sys.stderr)
    summary = {
        strategy.value: asdict(strategy_report.metrics)
        for strategy, strategy_report in report.strategies.items()
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
