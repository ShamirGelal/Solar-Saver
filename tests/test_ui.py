"""Integration coverage for the local UI's domain adapter and HTTP boundary."""

from dataclasses import asdict
from http.server import ThreadingHTTPServer
import json
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from solar_saver.domain import SimulationConfig, Strategy
from solar_saver.pipeline import run_comparison
from solar_saver.ui.__main__ import DemoHandler, build_comparison


class QuietHandler(DemoHandler):
    def log_message(self, *args):
        pass


class DemoIntegrationTests(unittest.TestCase):
    def test_adapter_uses_pipeline_and_preserves_profiles_metrics_and_completion(self):
        with patch("solar_saver.ui.__main__.run_comparison", wraps=run_comparison) as pipeline:
            payload = build_comparison()
        pipeline.assert_called_once()
        domain_report = run_comparison(**pipeline.call_args.kwargs)
        self.assertEqual(set(payload["strategies"]), {item.value for item in Strategy})
        self.assertEqual(payload["workload_count"], 100)
        self.assertEqual(payload["critical_workload_count"], 0)
        self.assertEqual(payload["model_name"], "seasonal-demo-baseline")
        self.assertEqual(payload["solar_supply_kw"], domain_report.solar_profile.supply_kw)
        self.assertEqual(len(payload["solar_supply_kw"]), 24)
        for strategy, item in domain_report.strategies.items():
            actual = payload["strategies"][strategy.value]
            self.assertEqual(actual["metrics"], asdict(item.metrics))
            self.assertEqual(actual["total_demand_kw"], item.result.total_demand_kw)
            self.assertEqual(actual["grid_draw_kw"], item.result.grid_draw_kw)
            self.assertEqual(actual["solar_used_kw"], item.result.solar_used_kw)
            self.assertEqual(actual["served_energy_kwh"], sum(item.result.total_demand_kw))
            self.assertEqual(actual["completed_count"], len(item.result.assignments))
            self.assertEqual(actual["unscheduled_count"], len(item.result.unscheduled_workload_ids))
        # The adapter must remain JSON-safe with no external encoders/artifacts.
        json.dumps(payload, allow_nan=False)

    def test_repeated_demo_is_deterministic(self):
        self.assertEqual(build_comparison(), build_comparison())

    def test_adapter_does_not_hide_unfinished_work(self):
        # Background still fits, but some flexible work has no feasible capacity.
        with patch("solar_saver.ui.__main__.SimulationConfig", return_value=SimulationConfig(grid_capacity_kw=190)):
            payload = build_comparison()
        balanced = payload["strategies"]["balanced"]
        self.assertGreater(balanced["unscheduled_count"], 0)
        self.assertLess(balanced["metrics"]["completion_percent"], 100)
        self.assertEqual(balanced["completed_count"] + balanced["unscheduled_count"], 100)


class DemoHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def get_json(self):
        try:
            response = urlopen(self.url + "/api/comparison", timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def test_serves_page_and_local_assets(self):
        for path, content_type in (("/", "text/html"), ("/app.css", "text/css"), ("/app.js", "text/javascript")):
            with self.subTest(path=path), urlopen(self.url + path, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_type(), content_type)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertGreater(len(response.read()), 100)

    def test_api_returns_real_comparison(self):
        status, payload = self.get_json()
        self.assertEqual(status, 200)
        self.assertEqual(payload, json.loads(json.dumps(build_comparison())))

    def test_infeasible_background_returns_error_without_fake_results(self):
        with patch("solar_saver.ui.__main__.SimulationConfig", return_value=SimulationConfig(grid_capacity_kw=1)):
            status, payload = self.get_json()
        self.assertEqual(status, 422)
        self.assertIn("base demand exceeds capacity", payload["detail"])
        self.assertNotIn("strategies", payload)

    def test_unexpected_failure_is_an_error_without_internal_details(self):
        with patch("solar_saver.ui.__main__.run_comparison", side_effect=RuntimeError("private diagnostic")):
            status, payload = self.get_json()
        self.assertEqual(status, 500)
        self.assertNotIn("private diagnostic", json.dumps(payload))
        self.assertNotIn("strategies", payload)

    def test_unknown_paths_do_not_expose_repository_files(self):
        for path in ("/README.md", "/../domain.py", "/%2e%2e/domain.py"):
            with self.subTest(path=path), self.assertRaises(HTTPError) as result:
                urlopen(self.url + path, timeout=5)
            self.assertEqual(result.exception.code, 404)
            result.exception.close()


if __name__ == "__main__":
    unittest.main()
