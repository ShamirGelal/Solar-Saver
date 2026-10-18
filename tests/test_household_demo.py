import unittest
from solar_saver.ui.household import household_examples

class HouseholdExampleTests(unittest.TestCase):
    def test_flexibility_changes_schedule_without_dropping_work(self):
        examples = household_examples()
        for window, variants in examples.items():
            shift = {"fixed": 0, "some": 3, "open": 10}[window]
            for policy, result in variants.items():
                self.assertEqual(result['metrics']['completion_percent'], 100)
                self.assertEqual(len(result['assignments']), 3)
                for a in result['assignments']:
                    self.assertLessEqual(abs(a['scheduled_start']-18), shift)
                if policy != 'uncoordinated':
                    self.assertEqual(result['metrics']['capacity_violation_hours'], 0)
                self.assertAlmostEqual(result['metrics']['solar_used_kwh'] + result['metrics']['grid_energy_kwh'], 26)
        self.assertGreater(examples['open']['balanced']['metrics']['renewable_match_percent'], examples['fixed']['balanced']['metrics']['renewable_match_percent'])
