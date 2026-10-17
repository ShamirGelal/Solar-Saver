"""Demand-owned acceptance and consumer compatibility tests."""

from collections import Counter
from dataclasses import replace
from datetime import date
from decimal import Decimal
import importlib.util
import inspect
import json
import math
from pathlib import Path
import random
import unittest
from unittest.mock import Mock

from solar_saver.demand import SyntheticDemandGenerator
from solar_saver.domain import (
    CityScenario, ForecastRequest, Priority, SchedulerWeights, SimulationConfig,
    SolarProfile, Strategy,
)
from solar_saver.forecasting import SeasonalDemoForecaster
from solar_saver.pipeline import run_comparison
from solar_saver.scheduling import GreedyLoadScheduler


def profile():
    return SolarProfile(tuple(float(max(0, 240 - abs(hour - 12) * 50))
                              for hour in range(24)), "test-solar")


class DemandTests(unittest.TestCase):
    def setUp(self):
        self.generator = SyntheticDemandGenerator()
        self.solar = profile()

    def generate(self, count=100, seed=42, capacity=500.0):
        return self.generator.generate(self.solar, SimulationConfig(count, seed, capacity))

    def test_public_signature_and_domain_output(self):
        self.assertEqual(list(inspect.signature(self.generator.generate).parameters),
                         ["solar_profile", "config"])
        self.assertIsInstance(self.generate(), CityScenario)

    def test_identical_seed_is_reproducible_across_instances_and_calls(self):
        expected = self.generate()
        self.generate(seed=999)
        self.assertEqual(expected, self.generate())
        self.assertEqual(expected, SyntheticDemandGenerator().generate(self.solar, SimulationConfig()))

    def test_different_seeds_change_population_but_not_background(self):
        first, second = self.generate(seed=7), self.generate(seed=42)
        self.assertNotEqual(first.workloads, second.workloads)
        self.assertEqual(first.base_demand_kw, second.base_demand_kw)

    def test_generation_does_not_modify_global_rng(self):
        before = random.getstate()
        self.generate()
        self.assertEqual(before, random.getstate())

    def test_demand_is_independent_of_solar_and_capacity(self):
        original = self.generate()
        changed_solar = replace(self.solar, supply_kw=(500.0,) * 24, model_name="different")
        changed = self.generator.generate(changed_solar, SimulationConfig(grid_capacity_kw=1000))
        self.assertEqual(original.workloads, changed.workloads)
        self.assertEqual(original.base_demand_kw, changed.base_demand_kw)
        self.assertEqual(changed.grid_capacity_kw, (1000,) * 24)
        self.assertIs(changed.solar_supply_kw, changed_solar.supply_kw)

    def test_smaller_population_is_prefix_of_larger_population(self):
        self.assertEqual(self.generate(count=10).workloads,
                         self.generate(count=100).workloads[:10])

    def test_background_scales_with_households_and_preserves_100_household_reference(self):
        reference = self.generate()
        for hour, value in enumerate(reference.base_demand_kw):
            expected = round(120 + 35 * math.exp(-((hour - 8) / 2.2) ** 2)
                             + 65 * math.exp(-((hour - 19) / 2.8) ** 2), 3)
            self.assertEqual(value, expected)
        large = self.generate(count=500, capacity=2500)
        for small, big in zip(reference.base_demand_kw, large.base_demand_kw):
            self.assertAlmostEqual(big, small * 5, places=3)
        self.assertEqual(max(large.base_demand_kw), 925.0)

    def test_zero_households_has_no_demand_and_preserves_supplied_profiles(self):
        empty = self.generate(count=0, capacity=0)
        self.assertEqual(empty.workloads, ())
        self.assertEqual(empty.base_demand_kw, (0.0,) * 24)
        self.assertEqual(empty.grid_capacity_kw, (0,) * 24)
        self.assertIs(empty.solar_supply_kw, self.solar.supply_kw)
        for strategy in Strategy:
            result = GreedyLoadScheduler().schedule(empty, strategy, SchedulerWeights())
            self.assertEqual(result.assignments, ())
            self.assertEqual(result.total_demand_kw, (0.0,) * 24)

    def test_profiles_workloads_windows_and_energy_across_populations(self):
        for count in (1, 2, 4, 100, 500):
            for seed in (0, 7, 42, 2026):
                with self.subTest(count=count, seed=seed):
                    scenario = self.generate(count, seed, max(5.0 * count, 10.0))
                    for values in (scenario.solar_supply_kw, scenario.base_demand_kw,
                                   scenario.grid_capacity_kw):
                        self.assertIsInstance(values, tuple)
                        self.assertEqual(len(values), 24)
                        self.assertTrue(all(math.isfinite(x) and x >= 0 for x in values))
                    self.assertEqual(len(scenario.workloads), count)
                    self.assertEqual(len({w.workload_id for w in scenario.workloads}), count)
                    self.assertEqual(len({w.user_id for w in scenario.workloads}), count)
                    hourly = [Decimal(0)] * 24
                    requested = Decimal(0)
                    for task in scenario.workloads:
                        self.assertTrue(math.isfinite(task.power_kw) and task.power_kw > 0)
                        self.assertIsInstance(task.duration_hours, int)
                        self.assertGreater(task.duration_hours, 0)
                        self.assertLessEqual(0, task.earliest_start)
                        self.assertLessEqual(task.latest_finish, 24)
                        self.assertLessEqual(task.earliest_start, task.preferred_start)
                        self.assertLessEqual(task.preferred_start + task.duration_hours, task.latest_finish)
                        self.assertTrue(0 <= task.flexibility <= 1)
                        self.assertIn(task.priority, (Priority.IMPORTANT, Priority.FLEXIBLE))
                        power = Decimal(str(task.power_kw))
                        requested += power * task.duration_hours
                        for hour in range(task.preferred_start, task.preferred_start + task.duration_hours):
                            hourly[hour] += power
                    self.assertEqual(sum(hourly), requested)
                    if count >= 100:
                        self.assertEqual(set(Counter(w.category for w in scenario.workloads)),
                                         {"ev_charging", "laundry", "dishwasher", "battery", "water_heating"})

    def test_population_has_daytime_evening_and_narrow_availability(self):
        tasks = self.generate(count=500, capacity=2500).workloads
        evs = [w for w in tasks if w.category == "ev_charging"]
        self.assertTrue(any(w.earliest_start <= 12 and w.latest_finish >= 15 for w in evs))
        self.assertTrue(any(w.earliest_start >= 16 for w in evs))
        self.assertTrue(any(w.latest_finish - w.earliest_start - w.duration_hours <= 2 for w in tasks))
        self.assertTrue(any(w.latest_finish - w.earliest_start - w.duration_hours >= 6 for w in tasks))

    def test_task_units_match_documented_constant_power_assumptions(self):
        expected = {"ev_charging": (7.2, 3), "laundry": (0.8, 1),
                    "dishwasher": (1.2, 2), "battery": (2.0, 3), "water_heating": (3.0, 1)}
        for task in self.generate().workloads:
            self.assertEqual((task.power_kw, task.duration_hours), expected[task.category])

    def test_category_priorities_match_household_rules(self):
        expected = {
            "ev_charging": Priority.IMPORTANT,
            "water_heating": Priority.IMPORTANT,
            "laundry": Priority.FLEXIBLE,
            "dishwasher": Priority.FLEXIBLE,
            "battery": Priority.FLEXIBLE,
        }
        for task in self.generate().workloads:
            self.assertEqual(task.priority, expected[task.category])

    def test_invalid_household_counts_are_rejected(self):
        for value in (-1, 1.5, True, "100", None, 10 ** 400):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "number_of_users"):
                self.generate(count=value)

    def test_invalid_seeds_are_rejected(self):
        for value in (None, True, 1.5, "42"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "random_seed"):
                self.generate(seed=value)
        self.assertEqual(self.generate(seed=-7), self.generate(seed=-7))

    def test_invalid_capacity_is_rejected(self):
        for value in (-1, float("nan"), float("inf"), True, "500", None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "grid_capacity_kw"):
                self.generate(capacity=value)

    def test_capacity_is_not_silently_scaled_or_background_clipped(self):
        with self.assertRaisesRegex(ValueError, "base demand exceeds capacity"):
            self.generate(count=500, capacity=500)
        peak = max(self.generate().base_demand_kw)
        exact = self.generate(capacity=peak)
        self.assertEqual(exact.grid_capacity_kw, (peak,) * 24)
        with self.assertRaisesRegex(ValueError, "base demand exceeds capacity"):
            self.generate(capacity=peak - 0.001)

    def test_bad_solar_horizons_are_rejected(self):
        for size in (0, 1, 23, 25):
            # Simulate malformed upstream output even when domain construction
            # would reject it. Validation belongs at our component boundary.
            solar = Mock(spec=SolarProfile, supply_kw=(0.0,) * size)
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, "24"):
                self.generator.generate(solar, SimulationConfig())

    def test_invalid_solar_values_are_rejected(self):
        for value in (-1.0, float("nan"), float("inf"), True, "1", None):
            solar = Mock(spec=SolarProfile, supply_kw=(value,) + (0.0,) * 23)
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "supply_kw"):
                self.generator.generate(solar, SimulationConfig())

    def test_mutable_or_missing_solar_profile_is_rejected(self):
        for values in ([0.0] * 24, None):
            solar = Mock(spec=SolarProfile, supply_kw=values)
            with self.subTest(values=values), self.assertRaisesRegex(ValueError, "tuple"):
                self.generator.generate(solar, SimulationConfig())

    def test_unrepresentable_solar_energy_and_capacity_are_rejected(self):
        solar = SolarProfile((1e308,) * 24, "overflow")
        with self.assertRaisesRegex(ValueError, "daily energy"):
            self.generator.generate(solar, SimulationConfig())
        with self.assertRaisesRegex(ValueError, "grid_capacity_kw"):
            self.generate(capacity=10 ** 400)

    def test_generator_does_not_mutate_inputs(self):
        config = SimulationConfig()
        solar_before, config_before = repr(self.solar), repr(config)
        self.generator.generate(self.solar, config)
        self.assertEqual(repr(self.solar), solar_before)
        self.assertEqual(repr(config), config_before)

    def test_pipeline_accepts_generated_demand_without_contract_changes(self):
        report = run_comparison(
            forecast_request=ForecastRequest(38.0293, -78.4767, date(2026, 10, 18), 300),
            simulation_config=SimulationConfig(), scheduler_weights=SchedulerWeights(),
            forecaster=SeasonalDemoForecaster(), demand_generator=self.generator,
            scheduler=GreedyLoadScheduler(),
        )
        self.assertEqual(set(report.strategies), set(Strategy))
        self.assertEqual(len(report.scenario.workloads), 100)
        for strategy, entry in report.strategies.items():
            self.assertEqual(len(entry.result.assignments) + len(entry.result.unscheduled_workload_ids), 100)
            if strategy is not Strategy.UNCOORDINATED:
                self.assertEqual(entry.metrics.capacity_violation_hours, 0)


class DemandFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = Path(__file__).resolve().parents[1] / "data" / "demo"
        cls.recipe = json.loads((directory / "demand_cases.json").read_text())
        spec = importlib.util.spec_from_file_location("demand_fixture_helper", directory / "benchmark_demand.py")
        cls.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.helper)

    def test_fixed_cases_preserve_requests_and_integrate_with_scheduler(self):
        generator, scheduler = SyntheticDemandGenerator(), GreedyLoadScheduler()
        for count in self.recipe["household_counts"]:
            for seed in self.recipe["seeds"]:
                for case in self.recipe["cases"]:
                    with self.subTest(count=count, seed=seed, case=case["name"]):
                        raw = generator.generate(profile(), SimulationConfig(
                            count, seed, case["capacity_kw_per_household"] * count))
                        scenario = self.helper.fixture_scenario(raw, case["window_mode"])
                        self.assertEqual(scenario.solar_supply_kw, raw.solar_supply_kw)
                        self.assertEqual(scenario.base_demand_kw, raw.base_demand_kw)
                        self.assertEqual(scenario.grid_capacity_kw, raw.grid_capacity_kw)
                        self.assertEqual([(w.workload_id, w.power_kw, w.duration_hours) for w in raw.workloads],
                                         [(w.workload_id, w.power_kw, w.duration_hours) for w in scenario.workloads])
                        by_id = {w.workload_id: w for w in scenario.workloads}
                        for strategy in Strategy:
                            result = scheduler.schedule(scenario, strategy, SchedulerWeights())
                            completed = [a.workload_id for a in result.assignments]
                            unfinished = result.unscheduled_workload_ids
                            self.assertEqual(len(completed), len(set(completed)))
                            self.assertFalse(set(completed) & set(unfinished))
                            self.assertEqual(set(completed) | set(unfinished), set(by_id))
                            expected = math.fsum(by_id[i].power_kw * by_id[i].duration_hours for i in completed)
                            self.assertAlmostEqual(math.fsum(result.flexible_demand_kw), expected)
                            for assignment in result.assignments:
                                task = by_id[assignment.workload_id]
                                self.assertLessEqual(task.earliest_start, assignment.scheduled_start)
                                self.assertLessEqual(assignment.scheduled_end, task.latest_finish)
                                self.assertEqual(assignment.scheduled_end - assignment.scheduled_start,
                                                 task.duration_hours)
                            if strategy is not Strategy.UNCOORDINATED:
                                self.assertTrue(all(d <= c for d, c in zip(
                                    result.total_demand_kw, scenario.grid_capacity_kw)))
                            if case["name"] == "no_flexibility":
                                self.assertEqual(len(unfinished), 0)
                                self.assertTrue(all(a.scheduled_start == by_id[a.workload_id].preferred_start
                                                    for a in result.assignments))

    def test_constrained_fixture_exposes_unfinished_work(self):
        scenario = SyntheticDemandGenerator().generate(profile(), SimulationConfig(grid_capacity_kw=190))
        result = GreedyLoadScheduler().schedule(scenario, Strategy.BALANCED, SchedulerWeights())
        self.assertGreater(len(result.unscheduled_workload_ids), 0)
        requested = math.fsum(w.power_kw * w.duration_hours for w in scenario.workloads)
        self.assertLess(math.fsum(result.flexible_demand_kw), requested)

    def test_fixture_rejects_unknown_mode(self):
        scenario = SyntheticDemandGenerator().generate(profile(), SimulationConfig())
        with self.assertRaisesRegex(ValueError, "window_mode"):
            self.helper.fixture_scenario(scenario, "typo")


if __name__ == "__main__":
    unittest.main()
