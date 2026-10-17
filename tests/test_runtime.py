"""Application integration checks without live weather or local model artifacts."""

from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from io import StringIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from requests.exceptions import ConnectionError, HTTPError, Timeout

from scripts.run_demo import main
from solar_saver.domain import ForecastRequest, SolarProfile
from solar_saver.forecasting import SeasonalDemoForecaster
from solar_saver.runtime import RuntimeForecaster
from solar_saver.ui.__main__ import build_comparison
from solar_saver.ui.export import export_site


class RuntimeIntegrationTests(unittest.TestCase):
    def setUp(self):
        mode = patch.dict(os.environ, {"SOLAR_SAVER_FORECAST_MODE": "auto"})
        mode.start()
        self.addCleanup(mode.stop)
        loader = patch("solar_saver.runtime.TrainedSolarForecaster.from_path")
        self.loader = loader.start()
        self.addCleanup(loader.stop)
        self.profile = SolarProfile(
            supply_kw=tuple(100.0 if 8 <= hour < 17 else 0.0 for hour in range(24)),
            model_name="trained-test-model", metadata={"weather_source": "test weather"},
        )
        self.loader.return_value.predict.return_value = self.profile
        self.request = ForecastRequest(38.0293, -78.4767, date(2026, 10, 18), 500.0)

    def test_trained_selection_reaches_ui_and_all_three_policies(self):
        payload = build_comparison()
        self.loader.assert_called_once()
        self.loader.return_value.predict.assert_called_once_with(self.request)
        self.assertEqual(payload["model_name"], self.profile.model_name)
        self.assertEqual(payload["solar_supply_kw"], self.profile.supply_kw)
        self.assertEqual(payload["forecast_metadata"], self.profile.metadata)
        self.assertEqual(set(payload["strategies"]), {"uncoordinated", "solar_only", "balanced"})

    def test_missing_artifact_preserves_baseline_warning_and_explains_fallback(self):
        self.loader.side_effect = FileNotFoundError("private filesystem path")
        with patch("solar_saver.runtime.OpenMeteoForecastClient.hourly_forecast") as weather:
            payload = build_comparison()
        weather.assert_not_called()
        baseline = SeasonalDemoForecaster().predict(self.request)
        self.assertEqual(payload["solar_supply_kw"], baseline.supply_kw)
        self.assertEqual(payload["model_name"], baseline.model_name)
        self.assertEqual(payload["forecast_metadata"]["warning"], baseline.metadata["warning"])
        self.assertIn("missing", payload["forecast_metadata"]["fallback_reason"])
        self.assertNotIn("private filesystem", json.dumps(payload))

    def test_weather_failures_fall_back_and_service_recovery_uses_trained_model(self):
        # Exercise the provider passed into the model loader, not a broad catch
        # around the pipeline. These failures originate at the weather boundary.
        def load(path, *, weather_provider):
            def predict(request):
                weather_provider.hourly_forecast(
                    latitude=request.latitude, longitude=request.longitude,
                    timestamps_utc=[],
                )
                return self.profile
            return Mock(predict=predict)

        self.loader.side_effect = load
        for error in (Timeout("private URL"), ConnectionError(), HTTPError(), ValueError("missing hours")):
            with self.subTest(error=type(error).__name__), patch(
                "solar_saver.runtime.OpenMeteoForecastClient.hourly_forecast", side_effect=error
            ):
                payload = build_comparison()
                self.assertEqual(payload["model_name"], "seasonal-demo-baseline")
                self.assertIn("Weather forecast data is unavailable", payload["forecast_metadata"]["fallback_reason"])
                self.assertNotIn("private URL", json.dumps(payload))
        with patch("solar_saver.runtime.OpenMeteoForecastClient.hourly_forecast"):
            payload = build_comparison()
        self.assertEqual(payload["model_name"], self.profile.model_name)
        self.assertNotIn("fallback_reason", payload["forecast_metadata"])

    def test_unrelated_model_errors_are_not_hidden_as_weather_outages(self):
        self.loader.return_value.predict.side_effect = ValueError("invalid model")
        with self.assertRaisesRegex(ValueError, "invalid model"):
            build_comparison()

    def test_invalid_artifact_is_not_hidden_as_a_missing_artifact(self):
        self.loader.side_effect = ValueError("unsupported artifact schema")
        with self.assertRaisesRegex(ValueError, "unsupported artifact schema"):
            build_comparison()

    def test_explicit_demo_mode_never_loads_artifact(self):
        with patch.dict(os.environ, {"SOLAR_SAVER_FORECAST_MODE": "demo"}):
            profile = RuntimeForecaster().predict(self.request)
        self.loader.assert_not_called()
        self.assertEqual(profile.model_name, "seasonal-demo-baseline")
        self.assertIn("Offline demo mode", profile.metadata["fallback_reason"])

    def test_invalid_mode_is_rejected(self):
        with patch.dict(os.environ, {"SOLAR_SAVER_FORECAST_MODE": "typo"}):
            with self.assertRaisesRegex(ValueError, "must be auto or demo"):
                build_comparison()

    def test_cli_uses_trained_profile_and_keeps_metrics_json(self):
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            main()
        self.loader.assert_called_once()
        self.assertIn(self.profile.model_name, stderr.getvalue())
        self.assertEqual(len(json.loads(stdout.getvalue())), 3)

    def test_cli_reports_fallback_reason(self):
        self.loader.side_effect = FileNotFoundError()
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            main()
        self.assertIn("seasonal-demo-baseline", stderr.getvalue())
        self.assertIn("artifact is missing", stderr.getvalue())
        self.assertIn("Synthetic baseline", stderr.getvalue())
        self.assertEqual(len(json.loads(stdout.getvalue())), 3)

    def test_static_export_carries_the_selected_model_and_fallback_warning(self):
        for missing in (False, True):
            with self.subTest(missing=missing), TemporaryDirectory() as directory:
                self.loader.side_effect = FileNotFoundError() if missing else None
                export_site(Path(directory))
                payload = json.loads((Path(directory) / "comparison.json").read_text())
                self.assertEqual(payload["model_name"], "seasonal-demo-baseline" if missing else self.profile.model_name)
                self.assertEqual("fallback_reason" in payload["forecast_metadata"], missing)
