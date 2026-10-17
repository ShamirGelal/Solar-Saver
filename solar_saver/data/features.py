"""Feature preparation for the Solar Saver irradiance model.

The model uses calendar and solar-position values known in advance together
with forecast-style Open-Meteo weather fields. NASA's observed weather columns
remain excluded so that hindsight measurements do not leak into evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from solar_saver.data.open_meteo import (
    WEATHER_FEATURE_COLUMNS,
    validate_weather_table,
)
from solar_saver.data.nasa_power import (
    CHARLOTTESVILLE_LATITUDE,
    CHARLOTTESVILLE_LONGITUDE,
    CHARLOTTESVILLE_TIMEZONE,
)


TARGET_COLUMN = "solar_irradiance_wh_m2"
HISTORICAL_MEAN_COLUMN = "historical_month_hour_mean_wh_m2"

MODEL_FEATURE_COLUMNS = (
    "month",
    "local_hour",
    "hour_sin",
    "hour_cos",
    "day_of_year_sin",
    "day_of_year_cos",
    "solar_elevation_deg",
    "is_daylight",
    HISTORICAL_MEAN_COLUMN,
    *WEATHER_FEATURE_COLUMNS,
)

_NUMERIC_SOURCE_COLUMNS = (
    TARGET_COLUMN,
    "temperature_c",
    "relative_humidity_percent",
    "wind_speed_m_s",
)


@dataclass(frozen=True)
class ChronologicalSplitConfig:
    """Exclusive UTC boundaries for the three fixed model partitions."""

    training_start: date = date(2022, 1, 1)
    validation_start: date = date(2023, 1, 1)
    test_start: date = date(2024, 1, 1)
    test_end_exclusive: date = date(2025, 1, 1)

    def __post_init__(self) -> None:
        if not (
            self.training_start
            < self.validation_start
            < self.test_start
            < self.test_end_exclusive
        ):
            raise ValueError("split boundaries must be strictly increasing")


@dataclass(frozen=True)
class ModelSplit:
    """One chronological partition ready for scikit-learn."""

    timestamps_utc: pd.Series
    features: pd.DataFrame
    target: pd.Series


@dataclass(frozen=True)
class PreparedModelData:
    """Training, validation, and test data with an identical feature schema."""

    training: ModelSplit
    validation: ModelSplit
    test: ModelSplit
    historical_encoder: MonthHourMeanEncoder
    feature_names: tuple[str, ...] = MODEL_FEATURE_COLUMNS


class MonthHourMeanEncoder:
    """Leakage-safe historical irradiance averages by local month and hour."""

    def __init__(self) -> None:
        self._means: pd.Series | None = None
        self._global_mean: float | None = None

    def fit(self, training_frame: pd.DataFrame) -> "MonthHourMeanEncoder":
        _require_columns(training_frame, ("month", "local_hour", TARGET_COLUMN))
        target = training_frame[TARGET_COLUMN]
        if target.isna().any():
            raise ValueError("training target contains missing values")
        self._means = training_frame.groupby(
            ["month", "local_hour"], observed=True
        )[TARGET_COLUMN].mean()
        self._global_mean = float(target.mean())
        return self

    def transform(self, frame: pd.DataFrame) -> pd.Series:
        """Apply averages learned only from the training partition."""

        if self._means is None or self._global_mean is None:
            raise RuntimeError("MonthHourMeanEncoder must be fitted first")
        _require_columns(frame, ("month", "local_hour"))
        keys = pd.MultiIndex.from_frame(frame[["month", "local_hour"]])
        encoded = self._means.reindex(keys).to_numpy(dtype=float)
        encoded = np.where(np.isnan(encoded), self._global_mean, encoded)
        return pd.Series(encoded, index=frame.index, name=HISTORICAL_MEAN_COLUMN)

    def fit_transform_training(self, training_frame: pd.DataFrame) -> pd.Series:
        """Encode training rows with leave-one-out means to avoid self-leakage."""

        self.fit(training_frame)
        groups = training_frame.groupby(["month", "local_hour"], observed=True)[
            TARGET_COLUMN
        ]
        group_sum = groups.transform("sum")
        group_count = groups.transform("count")
        target = training_frame[TARGET_COLUMN]

        total_sum = float(target.sum())
        total_count = int(target.count())
        if total_count < 2:
            raise ValueError("at least two training observations are required")
        global_leave_one_out = (total_sum - target) / (total_count - 1)
        group_leave_one_out = (group_sum - target) / (group_count - 1)
        encoded = group_leave_one_out.where(group_count > 1, global_leave_one_out)
        encoded.name = HISTORICAL_MEAN_COLUMN
        return encoded.astype(float)


def load_clean_history(csv_path: Path) -> pd.DataFrame:
    """Load and revalidate the cleaned hourly NASA table."""

    frame = pd.read_csv(csv_path)
    _require_columns(frame, ("timestamp_utc", *_NUMERIC_SOURCE_COLUMNS))

    frame["timestamp_utc"] = pd.to_datetime(
        frame["timestamp_utc"], utc=True, errors="raise"
    )
    for column in _NUMERIC_SOURCE_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame = frame.sort_values("timestamp_utc").reset_index(drop=True)
    if frame["timestamp_utc"].duplicated().any():
        raise ValueError("history contains duplicate UTC timestamps")
    if len(frame) > 1:
        elapsed_seconds = (
            frame["timestamp_utc"].diff().dropna().dt.total_seconds()
        )
        if not elapsed_seconds.eq(3600.0).all():
            raise ValueError("history must be a continuous hourly series")

    numeric_values = frame.loc[:, _NUMERIC_SOURCE_COLUMNS].to_numpy(dtype=float)
    if not np.isfinite(numeric_values).all():
        raise ValueError("history contains missing or non-finite numeric values")
    if (frame[TARGET_COLUMN] < 0).any():
        raise ValueError("solar irradiance cannot be negative")
    return frame


def add_deterministic_features(
    history: pd.DataFrame,
    *,
    latitude: float = CHARLOTTESVILLE_LATITUDE,
    longitude: float = CHARLOTTESVILLE_LONGITUDE,
    local_timezone: str = CHARLOTTESVILLE_TIMEZONE,
) -> pd.DataFrame:
    """Add calendar and approximate solar-position features."""

    _require_columns(history, ("timestamp_utc",))
    frame = history.copy()
    timestamps_utc = pd.to_datetime(frame["timestamp_utc"], utc=True, errors="raise")
    timestamps_local = timestamps_utc.dt.tz_convert(local_timezone)

    local_hour = timestamps_local.dt.hour.astype(int)
    local_day_of_year = timestamps_local.dt.dayofyear.astype(int)
    days_in_local_year = np.where(timestamps_local.dt.is_leap_year, 366.0, 365.0)

    hour_angle = 2.0 * np.pi * (local_hour + 0.5) / 24.0
    year_angle = 2.0 * np.pi * (local_day_of_year - 1) / days_in_local_year

    frame["month"] = timestamps_local.dt.month.astype(int)
    frame["local_hour"] = local_hour
    frame["hour_sin"] = np.sin(hour_angle)
    frame["hour_cos"] = np.cos(hour_angle)
    frame["day_of_year_sin"] = np.sin(year_angle)
    frame["day_of_year_cos"] = np.cos(year_angle)
    frame["solar_elevation_deg"] = _solar_elevation_degrees(
        timestamps_utc, latitude=latitude, longitude=longitude
    )
    frame["is_daylight"] = (frame["solar_elevation_deg"] > 0.0).astype(int)
    return frame


def prepare_model_data(
    csv_path: Path,
    weather_csv_path: Path,
    *,
    split_config: ChronologicalSplitConfig = ChronologicalSplitConfig(),
    latitude: float = CHARLOTTESVILLE_LATITUDE,
    longitude: float = CHARLOTTESVILLE_LONGITUDE,
    local_timezone: str = CHARLOTTESVILLE_TIMEZONE,
) -> PreparedModelData:
    """Build the exact feature matrices used by the gradient-boosting model."""

    history = load_clean_history(csv_path)
    weather = validate_weather_table(pd.read_csv(weather_csv_path))
    history = _join_weather(history, weather)
    featured = add_deterministic_features(
        history,
        latitude=latitude,
        longitude=longitude,
        local_timezone=local_timezone,
    )

    training, validation, test = _split_chronologically(featured, split_config)
    encoder = MonthHourMeanEncoder()
    training[HISTORICAL_MEAN_COLUMN] = encoder.fit_transform_training(training)
    validation[HISTORICAL_MEAN_COLUMN] = encoder.transform(validation)
    test[HISTORICAL_MEAN_COLUMN] = encoder.transform(test)

    return PreparedModelData(
        training=_to_model_split(training),
        validation=_to_model_split(validation),
        test=_to_model_split(test),
        historical_encoder=encoder,
    )


def combine_model_splits(prepared: PreparedModelData) -> pd.DataFrame:
    """Return one auditable table with an explicit chronological split label."""

    partitions: list[pd.DataFrame] = []
    for split_name, split in (
        ("training", prepared.training),
        ("validation", prepared.validation),
        ("test", prepared.test),
    ):
        partition = split.features.reset_index(drop=True).copy()
        partition.insert(
            0, "timestamp_utc", split.timestamps_utc.reset_index(drop=True)
        )
        partition.insert(1, "split", split_name)
        partition[TARGET_COLUMN] = split.target.reset_index(drop=True)
        partitions.append(partition)
    return pd.concat(partitions, ignore_index=True)


def _split_chronologically(
    frame: pd.DataFrame, config: ChronologicalSplitConfig
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    timestamp = frame["timestamp_utc"]
    training_start = _utc_timestamp(config.training_start)
    validation_start = _utc_timestamp(config.validation_start)
    test_start = _utc_timestamp(config.test_start)
    test_end = _utc_timestamp(config.test_end_exclusive)

    training = frame[
        (timestamp >= training_start) & (timestamp < validation_start)
    ].copy()
    validation = frame[
        (timestamp >= validation_start) & (timestamp < test_start)
    ].copy()
    test = frame[(timestamp >= test_start) & (timestamp < test_end)].copy()

    if training.empty or validation.empty or test.empty:
        raise ValueError("training, validation, and test partitions must be nonempty")
    if not (
        training["timestamp_utc"].max() < validation["timestamp_utc"].min()
        and validation["timestamp_utc"].max() < test["timestamp_utc"].min()
    ):
        raise ValueError("chronological partitions overlap")
    return training, validation, test


def _join_weather(history: pd.DataFrame, weather: pd.DataFrame) -> pd.DataFrame:
    joined = history.merge(
        weather,
        on="timestamp_utc",
        how="inner",
        validate="one_to_one",
    )
    if joined.empty:
        raise ValueError("NASA and Open-Meteo data have no overlapping timestamps")
    joined = joined.sort_values("timestamp_utc").reset_index(drop=True)
    if len(joined) > 1:
        elapsed = joined["timestamp_utc"].diff().dropna().dt.total_seconds()
        if not elapsed.eq(3600.0).all():
            raise ValueError("joined NASA and Open-Meteo data is not continuous")
    return joined


def _to_model_split(frame: pd.DataFrame) -> ModelSplit:
    features = frame.loc[:, MODEL_FEATURE_COLUMNS].astype(float)
    feature_values = features.to_numpy(dtype=float)
    if not np.isfinite(feature_values).all():
        raise ValueError("engineered features contain missing or non-finite values")
    return ModelSplit(
        timestamps_utc=frame["timestamp_utc"].copy(),
        features=features,
        target=frame[TARGET_COLUMN].astype(float).copy(),
    )


def _solar_elevation_degrees(
    timestamps_utc: pd.Series,
    *,
    latitude: float,
    longitude: float,
) -> np.ndarray:
    """Approximate solar elevation at the midpoint of each hourly interval.

    This uses NOAA's fractional-year approximation. It is deterministic and
    requires only the timestamp and location, so it is safe at prediction time.
    """

    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("latitude or longitude is outside its valid range")

    day_of_year = timestamps_utc.dt.dayofyear.to_numpy(dtype=float)
    utc_hour_midpoint = timestamps_utc.dt.hour.to_numpy(dtype=float) + 0.5
    gamma = 2.0 * np.pi / 365.0 * (
        day_of_year - 1.0 + (utc_hour_midpoint - 12.0) / 24.0
    )

    equation_of_time_minutes = 229.18 * (
        0.000075
        + 0.001868 * np.cos(gamma)
        - 0.032077 * np.sin(gamma)
        - 0.014615 * np.cos(2.0 * gamma)
        - 0.040849 * np.sin(2.0 * gamma)
    )
    declination = (
        0.006918
        - 0.399912 * np.cos(gamma)
        + 0.070257 * np.sin(gamma)
        - 0.006758 * np.cos(2.0 * gamma)
        + 0.000907 * np.sin(2.0 * gamma)
        - 0.002697 * np.cos(3.0 * gamma)
        + 0.00148 * np.sin(3.0 * gamma)
    )

    true_solar_minutes = (
        utc_hour_midpoint * 60.0 + equation_of_time_minutes + 4.0 * longitude
    ) % 1440.0
    hour_angle = np.deg2rad(true_solar_minutes / 4.0 - 180.0)
    latitude_radians = np.deg2rad(latitude)
    cosine_zenith = (
        np.sin(latitude_radians) * np.sin(declination)
        + np.cos(latitude_radians) * np.cos(declination) * np.cos(hour_angle)
    )
    zenith = np.arccos(np.clip(cosine_zenith, -1.0, 1.0))
    return 90.0 - np.rad2deg(zenith)


def _utc_timestamp(value: date) -> pd.Timestamp:
    return pd.Timestamp(value).tz_localize("UTC")


def _require_columns(frame: pd.DataFrame, columns: tuple[str, ...]) -> None:
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError("missing required columns: " + ", ".join(sorted(missing)))
