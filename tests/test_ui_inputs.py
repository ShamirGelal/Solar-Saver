"""Custom-load integration checks that require neither ML packages nor sockets."""

from email.message import Message
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from solar_saver.demand import SyntheticDemandGenerator
from solar_saver.domain import ForecastRequest, SimulationConfig, SolarProfile
from solar_saver.ui.__main__ import DemoHandler, build_comparison
from solar_saver.ui.inputs import EnteredLoadDemandGenerator, parse_workloads
from solar_saver.ui.export import export_site


def entered_load(**changes):
    return {
        "workload_id": "my-ev", "category": "Garage EV", "power_kw": 7.2,
        "duration_hours": 3, "earliest_start": 8, "latest_finish": 24,
        "preferred_start": 19, "priority": "important", "flexibility": 0.7,
        **changes,
    }


class FixedForecaster:
    def predict(self, request: ForecastRequest) -> SolarProfile:
        return SolarProfile(tuple(300.0 if 9 <= h < 16 else 0.0 for h in range(24)),
                            "test-solar-profile")


class EnteredLoadTests(unittest.TestCase):
    def test_entered_fields_are_preserved_as_shared_domain_objects(self):
        load, = parse_workloads({"workloads": [entered_load()]})
        self.assertEqual(load.workload_id, "my-ev")
        self.assertEqual(load.user_id, "planner")
        self.assertEqual(load.category, "Garage EV")
        self.assertEqual(load.priority.value, "important")
        self.assertEqual(load.flexibility, 0.7)
        self.assertAlmostEqual(load.power_kw * load.duration_hours, 21.6)

    def test_invalid_windows_and_preferences_are_rejected(self):
        for changes in (
            {"earliest_start": 22, "latest_finish": 24},
            {"preferred_start": 23}, {"preferred_start": 7},
            {"earliest_start": 25}, {"latest_finish": 25},
            {"duration_hours": 0}, {"duration_hours": 1.5},
            {"duration_hours": True}, {"earliest_start": "8"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                parse_workloads({"workloads": [entered_load(**changes)]})

    def test_nonfinite_negative_and_wrongly_typed_numbers_are_rejected(self):
        for field, values in (
            ("power_kw", [0, -1, float("nan"), float("inf"), "7.2", True, 10_001, 10**500]),
            ("flexibility", [-0.1, 1.1, float("nan"), float("inf"), "0.7", False]),
        ):
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    parse_workloads({"workloads": [entered_load(**{field: value})]})

    def test_names_ids_and_priorities_are_validated(self):
        for changes in (
            {"category": " "}, {"category": "x" * 65}, {"category": 1},
            {"workload_id": ""}, {"priority": "urgent"}, {"priority": None},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                parse_workloads({"workloads": [entered_load(**changes)]})
        with self.assertRaisesRegex(ValueError, "unique"):
            parse_workloads({"workloads": [entered_load(), entered_load()]})

    def test_body_shape_and_size_are_validated(self):
        for payload in (None, [], {}, {"workloads": {}}, {"workloads": [None]},
                        {"workloads": [entered_load()] * 101}):
            with self.subTest(payload=type(payload)), self.assertRaises(ValueError):
                parse_workloads(payload)
        self.assertEqual(parse_workloads({"workloads": []}), ())

    def test_full_day_load_and_exact_deadline_are_supported(self):
        load, = parse_workloads({"workloads": [entered_load(
            duration_hours=24, earliest_start=0, latest_finish=24, preferred_start=0,
        )]})
        self.assertEqual(load.duration_hours, 24)

    def test_adapter_replaces_flexible_population_and_preserves_background(self):
        loads = parse_workloads({"workloads": [entered_load()]})
        profile = SolarProfile((100.0,) * 24, "test")
        config = SimulationConfig(number_of_users=100)
        city = EnteredLoadDemandGenerator(loads).generate(profile, config)
        background = SyntheticDemandGenerator().generate(profile, config)
        self.assertEqual(city.workloads, loads)
        self.assertEqual(city.base_demand_kw, background.base_demand_kw)
        self.assertEqual(max(city.base_demand_kw), 185.0)
        self.assertEqual(city.solar_supply_kw, profile.supply_kw)
        self.assertEqual(city.grid_capacity_kw, background.grid_capacity_kw)
        self.assertEqual(city, EnteredLoadDemandGenerator(loads).generate(profile, config))

    def test_custom_pipeline_conserves_energy_and_serializes_actual_assignments(self):
        loads = parse_workloads({"workloads": [entered_load(), entered_load(
            workload_id="washer", category="Laundry", power_kw=0.8,
            duration_hours=1, earliest_start=8, latest_finish=20, preferred_start=14,
        )]})
        payload = build_comparison(loads, forecaster=FixedForecaster())
        self.assertEqual(payload["mode"], "custom")
        self.assertTrue(payload["supports_custom_loads"])
        self.assertEqual(payload["workload_count"], 2)
        self.assertAlmostEqual(payload["requested_flexible_energy_kwh"], 22.4)
        self.assertEqual(len(payload["workloads"]), 2)
        for name, result in payload["strategies"].items():
            self.assertEqual(result["completed_count"], 2)
            self.assertEqual(result["unscheduled_count"], 0)
            self.assertEqual({item["workload_id"] for item in result["assignments"]},
                             {"my-ev", "washer"})
            self.assertAlmostEqual(result["served_energy_kwh"] - sum(payload["base_demand_kw"]), 22.4)
            if name != "uncoordinated":
                self.assertEqual(result["metrics"]["capacity_violation_hours"], 0)
        json.dumps(payload, allow_nan=False)

    def test_oversized_load_is_reported_unfinished_without_partial_energy(self):
        loads = parse_workloads({"workloads": [
            entered_load(
                power_kw=10_000, duration_hours=3, earliest_start=0,
                latest_finish=3, preferred_start=0, priority="critical",
            ),
            entered_load(
                workload_id="second-large-load", power_kw=10_000,
                duration_hours=3, earliest_start=0, latest_finish=3,
                preferred_start=0, priority="critical",
            ),
        ]})
        payload = build_comparison(loads, forecaster=FixedForecaster())
        balanced = payload["strategies"]["balanced"]
        self.assertEqual(balanced["unscheduled_count"], 1)
        self.assertEqual(len(balanced["assignments"]), 1)
        self.assertEqual(balanced["metrics"]["critical_completion_percent"], 50)
        self.assertAlmostEqual(
            balanced["served_energy_kwh"] - sum(payload["base_demand_kw"]),
            30_000,
        )
        self.assertGreater(payload["strategies"]["uncoordinated"]["metrics"]["capacity_violation_hours"], 0)

    def test_edit_and_delete_inputs_recompute_without_retaining_old_loads(self):
        first = build_comparison(parse_workloads({"workloads": [entered_load()]}), forecaster=FixedForecaster())
        edited = build_comparison(parse_workloads({"workloads": [entered_load(power_kw=2)]}), forecaster=FixedForecaster())
        deleted = build_comparison((), forecaster=FixedForecaster())
        self.assertAlmostEqual(first["requested_flexible_energy_kwh"], 21.6)
        self.assertEqual(edited["requested_flexible_energy_kwh"], 6)
        self.assertEqual(deleted["requested_flexible_energy_kwh"], 0)
        self.assertEqual(deleted["workload_count"], 0)

    def test_district_demo_keeps_its_original_population(self):
        first = build_comparison(forecaster=FixedForecaster())
        second = build_comparison(forecaster=FixedForecaster())
        self.assertEqual(first, second)
        self.assertEqual(first["mode"], "demo")
        self.assertEqual(first["population_count"], 10_000)
        self.assertEqual(first["household_count"], 4_000)
        self.assertEqual(first["workload_count"], 4_000)

    def test_static_export_does_not_advertise_live_computation(self):
        payload = build_comparison(forecaster=FixedForecaster())
        with TemporaryDirectory() as temporary:
            destination = Path(temporary) / "site"
            with patch("solar_saver.ui.export.build_comparison", return_value=payload):
                export_site(destination)
            actual = json.loads((destination / "comparison.json").read_text())
            self.assertFalse(actual["supports_custom_loads"])
            self.assertEqual(actual["mode"], "demo")
            self.assertEqual(actual["workload_count"], 4_000)
            self.assertTrue((destination / "app.js").is_file())


class CustomRequestTests(unittest.TestCase):
    def request(self, body, *, path="/api/comparison", content_type="application/json", length=None):
        handler = DemoHandler.__new__(DemoHandler)
        handler.path = path
        handler.headers = Message()
        handler.headers["Content-Type"] = content_type
        handler.headers["Content-Length"] = str(len(body) if length is None else length)
        handler.rfile = BytesIO(body)
        responses = []
        handler._json = lambda status, payload: responses.append((int(status), payload))
        handler.log_error = lambda *args: None
        handler.do_POST()
        return responses[0]

    def test_post_runs_comparison_for_submitted_loads(self):
        raw = json.dumps({"workloads": [entered_load()]}).encode()
        with patch("solar_saver.ui.__main__.build_comparison",
                   side_effect=lambda loads: build_comparison(loads, forecaster=FixedForecaster())):
            status, payload = self.request(raw)
        self.assertEqual(status, 200)
        self.assertEqual(payload["mode"], "custom")
        self.assertEqual(payload["workload_count"], 1)

    def test_invalid_json_and_empty_body_return_400(self):
        for raw in (b"{", b"\xff", b""):
            with self.subTest(raw=raw):
                self.assertEqual(self.request(raw)[0], 400)

    def test_invalid_load_returns_422_without_results(self):
        status, payload = self.request(json.dumps({"workloads": [entered_load(duration_hours=30)]}).encode())
        self.assertEqual(status, 422)
        self.assertNotIn("strategies", payload)
        self.assertIn("duration_hours", payload["detail"])

    def test_request_limits_and_media_type_are_enforced(self):
        self.assertEqual(self.request(b"{}", length=65_537)[0], 413)
        self.assertEqual(self.request(b"{}", length="bad")[0], 400)
        self.assertEqual(self.request(b"{}", content_type="text/plain")[0], 415)
        self.assertEqual(self.request(b"{}", path="/README.md")[0], 404)

    def test_unexpected_failures_do_not_leak_diagnostics(self):
        raw = json.dumps({"workloads": [entered_load()]}).encode()
        with patch("solar_saver.ui.__main__.build_comparison", side_effect=RuntimeError("private diagnostic")):
            status, payload = self.request(raw)
        self.assertEqual(status, 500)
        self.assertNotIn("private diagnostic", json.dumps(payload))

    def test_missing_packages_return_actionable_setup_error(self):
        raw = json.dumps({"workloads": [entered_load()]}).encode()
        with patch("solar_saver.ui.__main__.build_comparison", side_effect=ModuleNotFoundError("joblib")):
            status, payload = self.request(raw)
        self.assertEqual(status, 503)
        self.assertIn("requirements.txt", payload["error"])


if __name__ == "__main__":
    unittest.main()
