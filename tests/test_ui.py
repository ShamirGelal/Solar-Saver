"""Integration coverage for the local UI's domain adapter and HTTP boundary."""

from dataclasses import asdict
from functools import partial
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen
from urllib.parse import urljoin

from solar_saver.domain import SchedulerWeights, SimulationConfig, Strategy
from solar_saver.pipeline import run_comparison
from solar_saver.ui.__main__ import DemoHandler, build_comparison
from solar_saver.ui.export import export_site


class QuietHandler(DemoHandler):
    def log_message(self, *args):
        pass


class OfflineDemoTestCase(unittest.TestCase):
    def setUp(self):
        mode = patch.dict(os.environ, {"SOLAR_SAVER_FORECAST_MODE": "demo"})
        mode.start()
        self.addCleanup(mode.stop)


class DemoIntegrationTests(OfflineDemoTestCase):
    def test_page_describes_the_presentation_scenario_and_uses_one_source(self):
        source = Path(__file__).parents[1] / "solar_saver" / "ui"
        page = (source / "index.html").read_text(encoding="utf-8")
        client = (source / "app.js").read_text(encoding="utf-8")

        self.assertIn("40,000 synthetic people", page)
        self.assertIn("16,000 modeled households", page)
        self.assertIn("20,000 flexible", page)
        self.assertIn("all prefer the same evening hour", page)
        self.assertIn("Demand is synthetic and uncalibrated", page)
        self.assertNotIn("synthetic users", page)
        self.assertIn('"load groups"', client)
        self.assertIn("Load-group completion", client)
        self.assertIn("showcaseLoads = data.workloads.map", client)
        self.assertIn("enteredLoads = showcaseLoads.map", client)
        self.assertNotIn("demoLoadCount", client)
        self.assertNotIn("demoGroupSize", client)
        self.assertIn("renderPolicyInsight", client)
        self.assertIn("Uncoordinated baseline", page)

    def test_adapter_uses_pipeline_and_preserves_profiles_metrics_and_completion(self):
        with patch("solar_saver.ui.__main__.run_comparison", wraps=run_comparison) as pipeline:
            payload = build_comparison()
        pipeline.assert_called_once()
        self.assertEqual(
            pipeline.call_args.kwargs["scheduler_weights"],
            SchedulerWeights(grid_energy=0.01, preference=2.0, peak=5.0, fairness=1.0),
        )
        domain_report = run_comparison(**pipeline.call_args.kwargs)
        self.assertEqual(set(payload["strategies"]), {item.value for item in Strategy})
        self.assertEqual(payload["population_count"], 40_000)
        self.assertEqual(payload["household_count"], 16_000)
        self.assertEqual(payload["mode"], "showcase")
        self.assertEqual(payload["workload_scale"], "aggregate")
        self.assertEqual(payload["scenario_name"], "Evening surge showcase")
        self.assertEqual(payload["workload_count"], 100)
        self.assertEqual(payload["represented_appliance_count"], 20_000)
        self.assertEqual(payload["critical_workload_count"], 0)
        self.assertEqual(payload["requested_flexible_energy_kwh"], 135_200)
        self.assertEqual({item["preferred_start"] for item in payload["workloads"]}, {18})
        self.assertEqual({item["priority"] for item in payload["workloads"]}, {"flexible"})
        self.assertEqual({item["flexibility"] for item in payload["workloads"]}, {1.0})
        self.assertEqual(payload["installed_capacity_kw"], 80_000.0)
        self.assertEqual(set(payload["grid_capacity_kw"]), {80_000.0})
        self.assertEqual(payload["model_name"], "seasonal-demo-baseline")
        self.assertEqual(payload["forecast_metadata"], domain_report.solar_profile.metadata)
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

    def test_showcase_policies_make_visible_and_honest_tradeoffs(self):
        payload = build_comparison()
        uncoordinated = payload["strategies"]["uncoordinated"]
        solar_only = payload["strategies"]["solar_only"]
        balanced = payload["strategies"]["balanced"]
        u, s, b = (item["metrics"] for item in (uncoordinated, solar_only, balanced))

        self.assertEqual(
            {item["completed_count"] for item in (uncoordinated, solar_only, balanced)},
            {payload["workload_count"]},
        )
        self.assertEqual(
            {item["served_energy_kwh"] for item in (uncoordinated, solar_only, balanced)},
            {uncoordinated["served_energy_kwh"]},
        )
        self.assertGreater(u["capacity_violation_hours"], 0)
        self.assertEqual(s["capacity_violation_hours"], 0)
        self.assertEqual(b["capacity_violation_hours"], 0)
        self.assertLess(s["grid_energy_kwh"], b["grid_energy_kwh"])
        self.assertLess(b["grid_energy_kwh"], u["grid_energy_kwh"])
        self.assertGreater(s["renewable_match_percent"], b["renewable_match_percent"] + 5)
        self.assertGreater(b["renewable_match_percent"], u["renewable_match_percent"] + 5)
        self.assertLess(b["peak_demand_kw"], s["peak_demand_kw"])
        self.assertLess(s["peak_demand_kw"], u["peak_demand_kw"])
        self.assertEqual(u["average_preference_deviation_hours"], 0)
        self.assertLess(b["average_preference_deviation_hours"],
                        s["average_preference_deviation_hours"] * 0.4)
        self.assertGreater(b["average_preference_deviation_hours"], 0)
        for first, second in ((uncoordinated, solar_only),
                              (uncoordinated, balanced), (solar_only, balanced)):
            curve_distance = sum(abs(a - b) for a, b in zip(
                first["total_demand_kw"], second["total_demand_kw"],
            ))
            self.assertGreater(curve_distance,
                               payload["requested_flexible_energy_kwh"] * 0.2)

    def test_adapter_does_not_hide_unfinished_work(self):
        # Background still fits, but some flexible work has no feasible capacity.
        with patch("solar_saver.ui.__main__.SimulationConfig", return_value=SimulationConfig(grid_capacity_kw=190)):
            payload = build_comparison()
        balanced = payload["strategies"]["balanced"]
        self.assertGreater(balanced["unscheduled_count"], 0)
        self.assertLess(balanced["metrics"]["completion_percent"], 100)
        self.assertEqual(balanced["completed_count"] + balanced["unscheduled_count"], 100)


class DemoHTTPTests(OfflineDemoTestCase):
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

    def test_relative_json_url_also_works_on_local_server(self):
        with urlopen(self.url + "/comparison.json", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.load(response), json.loads(json.dumps(build_comparison())))

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


class AssetLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "script" and "src" in values:
            self.urls.append(values["src"])
        if tag == "link" and values.get("rel") == "stylesheet":
            self.urls.append(values["href"])


class StaticPagesTests(OfflineDemoTestCase):
    def test_export_serves_complete_demo_under_repository_subpath(self):
        with TemporaryDirectory() as temporary:
            destination = Path(temporary) / "Solar-Saver"
            export_site(destination)
            handler = partial(SimpleHTTPRequestHandler, directory=temporary)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                root = f"http://127.0.0.1:{server.server_port}/Solar-Saver/"
                with urlopen(root, timeout=5) as response:
                    page = response.read().decode("utf-8")
                parser = AssetLinks()
                parser.feed(page)
                self.assertEqual(len(parser.urls), 2)
                for asset in parser.urls:
                    url = urljoin(root, asset)
                    self.assertTrue(url.startswith(root), url)
                    with urlopen(url, timeout=5) as response:
                        self.assertEqual(response.status, 200)
                        self.assertTrue(response.read())
                with urlopen(urljoin(root, "./comparison.json"), timeout=5) as response:
                    expected = json.loads(json.dumps(build_comparison()))
                    expected["supports_custom_loads"] = False
                    self.assertEqual(json.load(response), expected)
                self.assertEqual({path.name for path in destination.iterdir()},
                                 {"index.html", "app.css", "app.js", "comparison.json", ".nojekyll"})
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_export_is_reproducible(self):
        with TemporaryDirectory() as temporary:
            first, second = Path(temporary) / "first", Path(temporary) / "second"
            export_site(first)
            export_site(second)
            self.assertEqual((first / "comparison.json").read_bytes(),
                             (second / "comparison.json").read_bytes())

    def test_backend_failure_stops_export_before_writing_page(self):
        with TemporaryDirectory() as temporary:
            destination = Path(temporary) / "site"
            with patch("solar_saver.ui.export.build_comparison", side_effect=ValueError("infeasible")):
                with self.assertRaisesRegex(ValueError, "infeasible"):
                    export_site(destination)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
