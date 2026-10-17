from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from solar_saver.data.features import (
    HISTORICAL_MEAN_COLUMN,
    MODEL_FEATURE_COLUMNS,
    MonthHourMeanEncoder,
    TARGET_COLUMN,
    add_deterministic_features,
    combine_model_splits,
    load_clean_history,
    prepare_model_data,
)
from solar_saver.data.open_meteo import WEATHER_FEATURE_COLUMNS


def write_complete_history(path: Path) -> None:
    timestamps = pd.date_range(
        "2020-01-01 00:00:00+00:00",
        "2024-12-31 23:00:00+00:00",
        freq="h",
    )
    local_hour = timestamps.tz_convert("America/New_York").hour.to_numpy()
    daylight_shape = np.maximum(0.0, np.sin(np.pi * (local_hour - 6) / 14.0))
    frame = pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            TARGET_COLUMN: 800.0 * daylight_shape,
            "temperature_c": 15.0,
            "relative_humidity_percent": 60.0,
            "wind_speed_m_s": 2.0,
        }
    )
    frame.to_csv(path, index=False)


def write_complete_weather(path: Path) -> None:
    timestamps = pd.date_range(
        "2022-01-01 00:00:00+00:00",
        "2024-12-31 23:00:00+00:00",
        freq="h",
    )
    frame = pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "forecast_cloud_cover_percent": 40.0,
            "forecast_temperature_c": 15.0,
            "forecast_relative_humidity_percent": 60.0,
            "forecast_precipitation_mm": 0.0,
        }
    )
    frame.to_csv(path, index=False)


class SolarFeatureTests(unittest.TestCase):
    def test_preprocessing_creates_finite_ordered_model_splits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.csv"
            weather_path = Path(directory) / "weather.csv"
            write_complete_history(path)
            write_complete_weather(weather_path)
            prepared = prepare_model_data(path, weather_path)

        self.assertEqual(len(prepared.training.target), 8_760)
        self.assertEqual(len(prepared.validation.target), 8_760)
        self.assertEqual(len(prepared.test.target), 8_784)
        self.assertLess(
            prepared.training.timestamps_utc.max(),
            prepared.validation.timestamps_utc.min(),
        )
        self.assertLess(
            prepared.validation.timestamps_utc.max(),
            prepared.test.timestamps_utc.min(),
        )
        self.assertEqual(tuple(prepared.training.features), MODEL_FEATURE_COLUMNS)
        self.assertTrue(
            np.isfinite(prepared.training.features.to_numpy(dtype=float)).all()
        )

    def test_only_prediction_time_features_enter_the_model(self) -> None:
        weather_columns = {
            "temperature_c",
            "relative_humidity_percent",
            "wind_speed_m_s",
        }
        self.assertTrue(weather_columns.isdisjoint(MODEL_FEATURE_COLUMNS))
        self.assertTrue(set(WEATHER_FEATURE_COLUMNS).issubset(MODEL_FEATURE_COLUMNS))

    def test_solar_position_separates_day_and_night(self) -> None:
        frame = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    ["2024-06-21 05:00:00+00:00", "2024-06-21 17:00:00+00:00"]
                ),
                TARGET_COLUMN: [0.0, 800.0],
            }
        )
        featured = add_deterministic_features(frame)
        self.assertEqual(featured["is_daylight"].tolist(), [0, 1])
        self.assertLess(featured["solar_elevation_deg"].iloc[0], 0.0)
        self.assertGreater(featured["solar_elevation_deg"].iloc[1], 0.0)

    def test_training_historical_mean_excludes_its_own_target(self) -> None:
        frame = pd.DataFrame(
            {
                "month": [1, 1, 1],
                "local_hour": [12, 12, 12],
                TARGET_COLUMN: [100.0, 200.0, 300.0],
            }
        )
        encoded = MonthHourMeanEncoder().fit_transform_training(frame)
        self.assertEqual(encoded.tolist(), [250.0, 200.0, 150.0])

    def test_combined_table_labels_each_partition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.csv"
            weather_path = Path(directory) / "weather.csv"
            write_complete_history(path)
            write_complete_weather(weather_path)
            combined = combine_model_splits(prepare_model_data(path, weather_path))

        self.assertEqual(len(combined), 26_304)
        self.assertEqual(
            set(combined["split"]), {"training", "validation", "test"}
        )
        self.assertIn(HISTORICAL_MEAN_COLUMN, combined)
        self.assertIn(TARGET_COLUMN, combined)

    def test_loader_rejects_an_hourly_gap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gapped.csv"
            frame = pd.DataFrame(
                {
                    "timestamp_utc": pd.to_datetime(
                        ["2024-01-01 00:00:00+00:00", "2024-01-01 02:00:00+00:00"]
                    ),
                    TARGET_COLUMN: [0.0, 0.0],
                    "temperature_c": [1.0, 1.0],
                    "relative_humidity_percent": [60.0, 60.0],
                    "wind_speed_m_s": [2.0, 2.0],
                }
            )
            frame.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "continuous hourly"):
                load_clean_history(path)


if __name__ == "__main__":
    unittest.main()
