"""Run the backend end to end without a UI or network connection."""

from dataclasses import asdict
from datetime import date
import json

from solar_saver.demand import SyntheticDemandGenerator
from solar_saver.domain import ForecastRequest, SchedulerWeights, SimulationConfig
from solar_saver.forecasting import SeasonalDemoForecaster
from solar_saver.pipeline import run_comparison
from solar_saver.scheduling import GreedyLoadScheduler


def main() -> None:
    report = run_comparison(
        forecast_request=ForecastRequest(
            latitude=38.0293,
            longitude=-78.4767,
            target_date=date(2026, 10, 18),
            installed_capacity_kw=300.0,
        ),
        simulation_config=SimulationConfig(number_of_users=100, random_seed=42),
        scheduler_weights=SchedulerWeights(),
        forecaster=SeasonalDemoForecaster(),
        demand_generator=SyntheticDemandGenerator(),
        scheduler=GreedyLoadScheduler(),
    )
    summary = {
        strategy.value: asdict(strategy_report.metrics)
        for strategy, strategy_report in report.strategies.items()
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
