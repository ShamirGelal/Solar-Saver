from datetime import date
import unittest

from solar_saver.demand import SyntheticDemandGenerator
from solar_saver.domain import ForecastRequest, SchedulerWeights, SimulationConfig, Strategy
from solar_saver.forecasting import SeasonalDemoForecaster
from solar_saver.pipeline import run_comparison
from solar_saver.scheduling import GreedyLoadScheduler


class ContractSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.report = run_comparison(
            forecast_request=ForecastRequest(
                latitude=38.0293,
                longitude=-78.4767,
                target_date=date(2026, 10, 18),
                installed_capacity_kw=300.0,
            ),
            simulation_config=SimulationConfig(number_of_users=30, random_seed=7),
            scheduler_weights=SchedulerWeights(),
            forecaster=SeasonalDemoForecaster(),
            demand_generator=SyntheticDemandGenerator(),
            scheduler=GreedyLoadScheduler(),
        )

    def test_all_strategies_are_present(self) -> None:
        self.assertEqual(set(self.report.strategies), set(Strategy))

    def test_balanced_assignments_obey_windows(self) -> None:
        result = self.report.strategies[Strategy.BALANCED].result
        workloads = {load.workload_id: load for load in self.report.scenario.workloads}
        for assignment in result.assignments:
            workload = workloads[assignment.workload_id]
            self.assertGreaterEqual(assignment.scheduled_start, workload.earliest_start)
            self.assertLessEqual(assignment.scheduled_end, workload.latest_finish)

    def test_balanced_schedule_obeys_capacity(self) -> None:
        result = self.report.strategies[Strategy.BALANCED].result
        for demand, capacity in zip(result.total_demand_kw, self.report.scenario.grid_capacity_kw):
            self.assertLessEqual(demand, capacity)

    def test_profiles_have_twenty_four_hours(self) -> None:
        self.assertEqual(len(self.report.solar_profile.supply_kw), 24)
        for strategy_report in self.report.strategies.values():
            self.assertEqual(len(strategy_report.result.total_demand_kw), 24)


if __name__ == "__main__":
    unittest.main()
