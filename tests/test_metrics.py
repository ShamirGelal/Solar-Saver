import unittest

from solar_saver.domain import (
    Assignment, CityScenario, Priority, ScheduleResult, Strategy, Workload,
)
from solar_saver.metrics import evaluate_schedule


class MetricsTests(unittest.TestCase):
    def test_hand_calculated_metrics_including_missed_critical_load(self):
        items = (
            Workload("a", "u1", "test", 2, 1, 0, 4, 0, Priority.CRITICAL),
            Workload("b", "u2", "test", 2, 1, 0, 4, 0, Priority.FLEXIBLE),
            Workload("c", "u3", "test", 8, 1, 0, 4, 0, Priority.CRITICAL),
        )
        city = CityScenario((0, 5, 2, 0) + (0,) * 20,
                            (1,) * 4 + (0,) * 20,
                            (2,) * 24, items)
        result = ScheduleResult(
            Strategy.UNCOORDINATED,
            (Assignment("a", 1, 2), Assignment("b", 3, 4)), ("c",),
            (0, 2, 0, 2) + (0,) * 20,
            (1, 3, 1, 3) + (0,) * 20,
            (0, 3, 1, 0) + (0,) * 20,
            (1, 0, 0, 3) + (0,) * 20,
        )
        metrics = evaluate_schedule(city, result)
        self.assertEqual(metrics.grid_energy_kwh, 4)
        self.assertEqual(metrics.solar_used_kwh, 4)
        self.assertEqual(metrics.unused_solar_kwh, 3)
        self.assertEqual(metrics.renewable_match_percent, 50)
        self.assertEqual(metrics.peak_demand_kw, 3)
        self.assertEqual(metrics.average_preference_deviation_hours, 2)
        self.assertEqual(metrics.maximum_preference_deviation_hours, 3)
        self.assertAlmostEqual(metrics.completion_percent, 200 / 3)
        self.assertEqual(metrics.critical_completion_percent, 50)
        self.assertEqual(metrics.capacity_violation_hours, 2)

    def test_empty_workloads_and_zero_demand(self):
        city = CityScenario((2,) * 24, (0,) * 24, (0,) * 24, ())
        result = ScheduleResult(Strategy.BALANCED, (), (), *((0,) * 24,) * 4)
        metrics = evaluate_schedule(city, result)
        self.assertEqual(metrics.grid_energy_kwh, 0)
        self.assertEqual(metrics.solar_used_kwh, 0)
        self.assertEqual(metrics.unused_solar_kwh, 48)
        self.assertEqual(metrics.renewable_match_percent, 0)
        self.assertEqual(metrics.peak_demand_kw, 0)
        self.assertEqual(metrics.average_preference_deviation_hours, 0)
        self.assertEqual(metrics.maximum_preference_deviation_hours, 0)
        self.assertEqual(metrics.completion_percent, 100)
        self.assertEqual(metrics.critical_completion_percent, 100)
        self.assertEqual(metrics.capacity_violation_hours, 0)

    def test_all_workloads_unscheduled(self):
        item = Workload("a", "u", "test", 2, 1, 0, 1, 0, Priority.CRITICAL)
        city = CityScenario((0,) * 24, (0,) * 24, (0,) * 24, (item,))
        result = ScheduleResult(Strategy.BALANCED, (), ("a",), *((0,) * 24,) * 4)
        metrics = evaluate_schedule(city, result)
        self.assertEqual(metrics.completion_percent, 0)
        self.assertEqual(metrics.critical_completion_percent, 0)
        self.assertEqual(metrics.average_preference_deviation_hours, 0)


if __name__ == "__main__":
    unittest.main()
