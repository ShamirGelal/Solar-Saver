from dataclasses import replace
import random
import unittest

from solar_saver.domain import CityScenario, Priority, SchedulerWeights, Strategy, Workload
from solar_saver.scheduling import GreedyLoadScheduler


def load(identifier="task", *, power=2.0, duration=2, earliest=0,
         latest=24, preferred=0, priority=Priority.FLEXIBLE, flexibility=0.5):
    return Workload(identifier, identifier, "test", power, duration, earliest,
                    latest, preferred, priority, flexibility)


def scenario(workloads=(), *, solar=None, base=None, capacity=None):
    return CityScenario(
        tuple(solar if solar is not None else [0.0] * 24),
        tuple(base if base is not None else [1.0] * 24),
        tuple(capacity if capacity is not None else [10.0] * 24),
        tuple(workloads),
    )


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.scheduler = GreedyLoadScheduler()

    def schedule(self, city, strategy=Strategy.BALANCED, weights=SchedulerWeights()):
        return self.scheduler.schedule(city, strategy, weights)

    def assert_invariants(self, city, result):
        workloads = {item.workload_id: item for item in city.workloads}
        ids = [assignment.workload_id for assignment in result.assignments]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(set(ids) & set(result.unscheduled_workload_ids))
        self.assertEqual(set(workloads), set(ids) | set(result.unscheduled_workload_ids))
        expected = [0.0] * city.horizon_hours
        for assignment in result.assignments:
            item = workloads[assignment.workload_id]
            self.assertGreaterEqual(assignment.scheduled_start, item.earliest_start)
            self.assertLessEqual(assignment.scheduled_end, item.latest_finish)
            self.assertEqual(assignment.scheduled_end - assignment.scheduled_start,
                             item.duration_hours)
            for hour in range(assignment.scheduled_start, assignment.scheduled_end):
                expected[hour] += item.power_kw
        for profile in (result.flexible_demand_kw, result.total_demand_kw,
                        result.solar_used_kw, result.grid_draw_kw):
            self.assertEqual(len(profile), city.horizon_hours)
        for hour, extra in enumerate(expected):
            self.assertAlmostEqual(result.flexible_demand_kw[hour], extra)
            total = city.base_demand_kw[hour] + extra
            self.assertAlmostEqual(result.total_demand_kw[hour], total)
            self.assertAlmostEqual(result.solar_used_kw[hour],
                                   min(total, city.solar_supply_kw[hour]))
            self.assertAlmostEqual(result.grid_draw_kw[hour],
                                   max(0, total - city.solar_supply_kw[hour]))
            if result.strategy != Strategy.UNCOORDINATED:
                self.assertLessEqual(total, city.grid_capacity_kw[hour])
        self.assertAlmostEqual(sum(result.flexible_demand_kw), sum(
            workloads[identifier].power_kw * workloads[identifier].duration_hours
            for identifier in ids))

    def test_invariants_and_determinism_across_seeded_scenarios(self):
        for seed in range(8):
            rng = random.Random(seed)
            items = []
            for index in range(20):
                duration = rng.randint(1, 4)
                earliest = rng.randint(0, 24 - duration)
                latest = rng.randint(earliest + duration, 24)
                items.append(load(str(index), power=rng.choice([0.5, 2, 4]),
                                  duration=duration, earliest=earliest, latest=latest,
                                  preferred=rng.randrange(earliest, latest),
                                  priority=rng.choice(list(Priority))))
            city = scenario(items, solar=[rng.uniform(0, 10) for _ in range(24)])
            for strategy in Strategy:
                with self.subTest(seed=seed, strategy=strategy):
                    result = self.schedule(city, strategy)
                    self.assertEqual(result, self.schedule(city, strategy))
                    self.assert_invariants(city, result)

    def test_uncoordinated_clamps_preference_to_last_valid_start(self):
        city = scenario([load(earliest=20, preferred=23, duration=3)])
        result = self.schedule(city, Strategy.UNCOORDINATED)
        self.assertEqual(result.assignments[0].scheduled_start, 21)

    def test_uncoordinated_exposes_capacity_violations(self):
        city = scenario([load(power=20)])
        result = self.schedule(city, Strategy.UNCOORDINATED)
        self.assertEqual(result.assignments[0].scheduled_start, 0)
        self.assertGreater(result.total_demand_kw[0], city.grid_capacity_kw[0])

    def test_no_feasible_slot_reports_task_without_partial_energy(self):
        city = scenario([load(power=20)])
        for strategy in (Strategy.SOLAR_ONLY, Strategy.BALANCED):
            result = self.schedule(city, strategy)
            self.assertEqual(result.unscheduled_workload_ids, ("task",))
            self.assertEqual(result.assignments, ())
            self.assertEqual(sum(result.flexible_demand_kw), 0)

    def test_critical_load_gets_capacity_before_lower_priorities(self):
        city = scenario([
            load("flexible", duration=1, latest=1),
            load("important", duration=1, latest=1, priority=Priority.IMPORTANT),
            load("critical", duration=1, latest=1, priority=Priority.CRITICAL),
        ], capacity=[3.0] * 24)
        for strategy in (Strategy.SOLAR_ONLY, Strategy.BALANCED):
            result = self.schedule(city, strategy)
            self.assertEqual([item.workload_id for item in result.assignments], ["critical"])
            self.assertEqual(set(result.unscheduled_workload_ids), {"flexible", "important"})

    def test_solar_only_uses_residual_solar_over_whole_duration(self):
        # Hour 0 has more solar but no surplus after fixed demand.
        city = scenario([load(duration=2, latest=4)],
                        solar=[10, 0, 4, 4] + [0] * 20,
                        base=[10, 0, 0, 0] + [0] * 20,
                        capacity=[20] * 24)
        self.assertEqual(self.schedule(city, Strategy.SOLAR_ONLY)
                         .assignments[0].scheduled_start, 2)

    def test_each_balanced_weight_changes_the_chosen_placement(self):
        item = load(duration=1, latest=3, preferred=0, flexibility=0)
        city = scenario([item], solar=[0, 0, 5] + [0] * 21,
                        base=[4, 0, 0] + [0] * 21)
        cases = [
            (SchedulerWeights(1, 0, 0, 0), 2),
            (SchedulerWeights(0, 1, 0, 0), 0),
            (SchedulerWeights(0, 0, 1, 0), 1),
            (SchedulerWeights(0, 0, 0, 1), 0),
        ]
        for weights, expected in cases:
            with self.subTest(weights=weights):
                self.assertEqual(self.schedule(city, weights=weights)
                                 .assignments[0].scheduled_start, expected)

    def test_priority_and_flexibility_affect_displacement(self):
        item = load(power=2, duration=1, latest=2, preferred=0, flexibility=0)
        weights = SchedulerWeights(1, 1, 0, 0)
        def start(workload):
            city = scenario([workload], solar=[0, 4] + [0] * 22)
            return self.schedule(city, weights=weights).assignments[0].scheduled_start
        self.assertEqual(start(item), 1)
        self.assertEqual(start(replace(item, priority=Priority.IMPORTANT)), 0)
        self.assertEqual(start(replace(item, priority=Priority.IMPORTANT, flexibility=1)), 1)

    def test_empty_scenario_has_background_profiles(self):
        city = scenario()
        for strategy in Strategy:
            self.assert_invariants(city, self.schedule(city, strategy))

    def test_solar_ties_prefer_nearest_preference_then_earliest_hour(self):
        city = scenario([load(duration=1, preferred=8)])
        self.assertEqual(self.schedule(city, Strategy.SOLAR_ONLY)
                         .assignments[0].scheduled_start, 8)
        capacity = [1.0] * 24
        capacity[7] = capacity[9] = 3
        city = replace(city, grid_capacity_kw=tuple(capacity))
        self.assertEqual(self.schedule(city, Strategy.SOLAR_ONLY)
                         .assignments[0].scheduled_start, 7)

    def test_fairness_penalty_discourages_large_individual_displacement(self):
        city = scenario([load(duration=1, latest=4)], base=[0] * 24,
                        solar=[0, 1, 0, 2] + [0] * 20)
        self.assertEqual(self.schedule(city, weights=SchedulerWeights(1, 0, 0, 0))
                         .assignments[0].scheduled_start, 3)
        self.assertEqual(self.schedule(city, weights=SchedulerWeights(1, 0, 0, 0.3))
                         .assignments[0].scheduled_start, 1)

    def test_equal_priority_order_does_not_depend_on_input_order(self):
        items = [load("a", duration=1, latest=1), load("b", duration=1, latest=1)]
        city = scenario(items, capacity=[3] * 24)
        self.assertEqual(self.schedule(city),
                         self.schedule(replace(city, workloads=tuple(reversed(items)))))

    def test_duplicate_ids_are_rejected(self):
        for strategy in Strategy:
            with self.subTest(strategy=strategy), self.assertRaisesRegex(ValueError, "unique"):
                self.schedule(scenario([load(), load()]), strategy)

    def test_out_of_horizon_window_is_rejected(self):
        for strategy in Strategy:
            with self.subTest(strategy=strategy), self.assertRaisesRegex(ValueError, "horizon"):
                self.schedule(scenario([load(latest=25)]), strategy)

    def test_nonfinite_and_negative_profiles_are_rejected(self):
        for name in ("solar_supply_kw", "base_demand_kw", "grid_capacity_kw"):
            for value in (-1, float("nan"), float("inf")):
                city = replace(scenario(), **{name: (value,) + (1.0,) * 23})
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    self.schedule(city)

    def test_invalid_workload_power_is_rejected(self):
        for value in (float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.schedule(scenario([load(power=value)]))

    def test_invalid_weights_are_rejected(self):
        for name in ("grid_energy", "preference", "peak", "fairness"):
            for value in (-1, float("nan"), float("inf")):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    self.schedule(scenario(), weights=replace(SchedulerWeights(), **{name: value}))

    def test_background_over_capacity_is_infeasible_for_coordinated_policies(self):
        city = scenario(base=[11] * 24)
        for strategy in (Strategy.SOLAR_ONLY, Strategy.BALANCED):
            with self.subTest(strategy=strategy), self.assertRaisesRegex(ValueError, "base demand"):
                self.schedule(city, strategy)
        self.assertEqual(self.schedule(city, Strategy.UNCOORDINATED).total_demand_kw,
                         city.base_demand_kw)

    def test_zero_capacity_hours_are_skipped_and_exact_capacity_is_allowed(self):
        city = scenario([load(duration=1, latest=2)], base=[0] * 24,
                        capacity=[0, 2] + [0] * 22)
        for strategy in (Strategy.SOLAR_ONLY, Strategy.BALANCED):
            result = self.schedule(city, strategy)
            self.assertEqual(result.assignments[0].scheduled_start, 1)
            self.assert_invariants(city, result)

    def test_unknown_strategy_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "strategy"):
            self.schedule(scenario(), "unknown")


if __name__ == "__main__":
    unittest.main()
