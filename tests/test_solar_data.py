from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

from solar_saver.data.nasa_power import (
    NasaPowerRequest,
    download_hourly_data,
    load_hourly_table,
)


def sample_payload() -> dict:
    return {
        "header": {"fill_value": -999.0, "time_standard": "UTC"},
        "properties": {
            "parameter": {
                "ALLSKY_SFC_SW_DWN": {
                    "2024060104": 0.0,
                    "2024060105": -999.0,
                    "2024060106": 12.5,
                },
                "T2M": {
                    "2024060104": 15.0,
                    "2024060105": 14.5,
                    "2024060106": 14.0,
                },
                "RH2M": {
                    "2024060104": 80.0,
                    "2024060105": 82.0,
                    "2024060106": 84.0,
                },
                "WS10M": {
                    "2024060104": 1.0,
                    "2024060105": 1.5,
                    "2024060106": 2.0,
                },
            }
        },
    }


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class NasaPowerDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = NasaPowerRequest(
            latitude=38.0293,
            longitude=-78.4767,
            start_date=date(2024, 6, 1),
            end_date=date(2024, 6, 1),
        )

    def test_invalid_request_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            NasaPowerRequest(
                latitude=100.0,
                longitude=-78.4767,
                start_date=date(2024, 6, 1),
                end_date=date(2024, 6, 1),
            )

    def test_download_is_cached(self) -> None:
        calls: list[dict] = []

        def fake_get(url: str, **kwargs: object) -> FakeResponse:
            calls.append({"url": url, **kwargs})
            return FakeResponse(sample_payload())

        with tempfile.TemporaryDirectory() as directory:
            first = download_hourly_data(
                self.request, Path(directory), http_get=fake_get
            )
            second = download_hourly_data(
                self.request, Path(directory), http_get=fake_get
            )

        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["params"]["time-standard"], "UTC")

    def test_table_has_explicit_units_timezone_and_missing_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.json"
            path.write_text(json.dumps(sample_payload()), encoding="utf-8")
            table = load_hourly_table(path)

        self.assertEqual(
            list(table.columns),
            [
                "timestamp_local",
                "solar_irradiance_wh_m2",
                "temperature_c",
                "relative_humidity_percent",
                "wind_speed_m_s",
                "local_date",
                "local_hour",
            ],
        )
        self.assertEqual(str(table.index.tz), "UTC")
        self.assertEqual(str(table["timestamp_local"].dt.tz), "America/New_York")
        self.assertTrue(table["solar_irradiance_wh_m2"].isna().iloc[1])
        self.assertEqual(table["local_hour"].tolist(), [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
