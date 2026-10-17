from __future__ import annotations

from datetime import date
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from solar_saver.data.open_meteo import (
    OpenMeteoForecastClient,
    OpenMeteoRequest,
    download_weather_data,
    load_weather_table,
)


def sample_payload() -> dict:
    return {
        "timezone": "GMT",
        "hourly_units": {
            "time": "iso8601",
            "cloud_cover": "%",
            "temperature_2m": "°C",
            "relative_humidity_2m": "%",
            "precipitation": "mm",
        },
        "hourly": {
            "time": ["2024-10-01T00:00", "2024-10-01T01:00"],
            "cloud_cover": [80, 60],
            "temperature_2m": [18.0, 17.5],
            "relative_humidity_2m": [90, 92],
            "precipitation": [0.2, 0.0],
        },
    }


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return sample_payload()


def fake_get(url: str, **kwargs: object) -> FakeResponse:
    return FakeResponse()


class OpenMeteoTests(unittest.TestCase):
    def test_historical_response_is_cached_and_normalized(self) -> None:
        request = OpenMeteoRequest(
            latitude=38.0293,
            longitude=-78.4767,
            start_date=date(2024, 10, 1),
            end_date=date(2024, 10, 1),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = download_weather_data(
                request, Path(directory), http_get=fake_get
            )
            table = load_weather_table(path)

        self.assertEqual(len(table), 2)
        self.assertEqual(str(table["timestamp_utc"].dt.tz), "UTC")
        self.assertEqual(table["forecast_cloud_cover_percent"].tolist(), [80, 60])

    def test_live_client_returns_exact_requested_hours(self) -> None:
        client = OpenMeteoForecastClient(http_get=fake_get)
        requested = list(
            pd.date_range("2024-10-01 00:00:00+00:00", periods=2, freq="h")
        )
        table = client.hourly_forecast(
            latitude=38.0293,
            longitude=-78.4767,
            timestamps_utc=requested,
        )
        self.assertEqual(table["timestamp_utc"].tolist(), requested)
        self.assertEqual(table["forecast_precipitation_mm"].tolist(), [0.2, 0.0])


if __name__ == "__main__":
    unittest.main()
