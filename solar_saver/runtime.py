"""Application-level forecast selection; shared subsystem contracts stay unchanged."""

from dataclasses import replace
import os
from pathlib import Path

from requests.exceptions import RequestException

from .data.open_meteo import OpenMeteoForecastClient
from .domain import ForecastRequest, SolarProfile
from .forecasting import SeasonalDemoForecaster, TrainedSolarForecaster


DEFAULT_ARTIFACT_PATH = Path(__file__).resolve().parent.parent / "artifacts/solar_forecaster.joblib"


class WeatherUnavailable(Exception):
    """The weather service could not supply usable forecast data."""


class DemoWeatherProvider:
    """Keep external-service failures separate from model or scheduling bugs."""

    def __init__(self) -> None:
        self.client = OpenMeteoForecastClient(timeout_seconds=5.0)

    def hourly_forecast(self, **kwargs):
        try:
            return self.client.hourly_forecast(**kwargs)
        except (RequestException, ValueError) as error:
            raise WeatherUnavailable from error


class RuntimeForecaster:
    """Prefer the trained artifact, with an explicitly labeled demo fallback.

    SOLAR_SAVER_FORECAST_MODE=demo disables artifact loading and network calls.
    The default auto mode retries selection on each comparison, allowing recovery
    after an artifact is installed or the weather service becomes available.
    """

    def __init__(self, artifact_path: Path = DEFAULT_ARTIFACT_PATH) -> None:
        self.artifact_path = artifact_path

    def predict(self, request: ForecastRequest) -> SolarProfile:
        mode = os.environ.get("SOLAR_SAVER_FORECAST_MODE", "auto")
        if mode not in {"auto", "demo"}:
            raise ValueError("SOLAR_SAVER_FORECAST_MODE must be auto or demo")
        if mode == "demo":
            return self._fallback(request, "Offline demo mode was selected.")

        try:
            forecaster = TrainedSolarForecaster.from_path(
                self.artifact_path, weather_provider=DemoWeatherProvider()
            )
        except FileNotFoundError:
            return self._fallback(request, "The trained model artifact is missing.")

        try:
            return forecaster.predict(request)
        except WeatherUnavailable:
            return self._fallback(
                request, "Weather forecast data is unavailable for the requested day."
            )

    @staticmethod
    def _fallback(request: ForecastRequest, reason: str) -> SolarProfile:
        profile = SeasonalDemoForecaster().predict(request)
        return replace(profile, metadata={**profile.metadata, "fallback_reason": reason})
