"""Open-Meteo historical-forecast and live-forecast data boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd
import requests

from solar_saver.data.nasa_power import (
    CHARLOTTESVILLE_LATITUDE,
    CHARLOTTESVILLE_LONGITUDE,
)


HISTORICAL_FORECAST_URL = (
    "https://historical-forecast-api.open-meteo.com/v1/forecast"
)
LIVE_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

OPEN_METEO_PARAMETERS = (
    "cloud_cover",
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
)

WEATHER_COLUMN_NAMES = {
    "cloud_cover": "forecast_cloud_cover_percent",
    "temperature_2m": "forecast_temperature_c",
    "relative_humidity_2m": "forecast_relative_humidity_percent",
    "precipitation": "forecast_precipitation_mm",
}

WEATHER_FEATURE_COLUMNS = tuple(WEATHER_COLUMN_NAMES.values())


@dataclass(frozen=True)
class OpenMeteoRequest:
    latitude: float
    longitude: float
    start_date: date
    end_date: date
    endpoint: str = HISTORICAL_FORECAST_URL

    def __post_init__(self) -> None:
        if not -90 <= self.latitude <= 90:
            raise ValueError("latitude must be between -90 and 90")
        if not -180 <= self.longitude <= 180:
            raise ValueError("longitude must be between -180 and 180")
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        if self.endpoint not in {HISTORICAL_FORECAST_URL, LIVE_FORECAST_URL}:
            raise ValueError("unsupported Open-Meteo endpoint")

    def query_parameters(self) -> dict[str, str | float]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "hourly": ",".join(OPEN_METEO_PARAMETERS),
            "timezone": "GMT",
        }

    def cache_name(self) -> str:
        canonical = json.dumps(
            {"endpoint": self.endpoint, **self.query_parameters()},
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
        return (
            f"open_meteo_historical_forecast_{self.start_date:%Y%m%d}_"
            f"{self.end_date:%Y%m%d}_{digest}.json"
        )


def download_weather_data(
    request: OpenMeteoRequest,
    cache_directory: Path,
    *,
    force_refresh: bool = False,
    timeout_seconds: float = 60.0,
    http_get: Callable[..., Any] | None = None,
) -> Path:
    """Download one Open-Meteo response and cache it atomically."""

    raw_directory = Path(cache_directory) / "raw"
    raw_directory.mkdir(parents=True, exist_ok=True)
    cache_path = raw_directory / request.cache_name()
    if cache_path.exists() and not force_refresh:
        return cache_path

    get = http_get or requests.get
    response = get(
        request.endpoint,
        params=request.query_parameters(),
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    _validate_payload(payload)

    temporary_path = cache_path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(payload), encoding="utf-8")
    temporary_path.replace(cache_path)
    return cache_path


def load_weather_table(json_path: Path) -> pd.DataFrame:
    payload = json.loads(Path(json_path).read_text(encoding="utf-8"))
    _validate_payload(payload)
    hourly = payload["hourly"]
    table = pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(hourly["time"], utc=True, errors="raise"),
            **{
                WEATHER_COLUMN_NAMES[parameter]: pd.to_numeric(
                    hourly[parameter], errors="coerce"
                )
                for parameter in OPEN_METEO_PARAMETERS
            },
        }
    )
    return validate_weather_table(table)


def validate_weather_table(table: pd.DataFrame) -> pd.DataFrame:
    required = ("timestamp_utc", *WEATHER_FEATURE_COLUMNS)
    missing = set(required) - set(table.columns)
    if missing:
        raise ValueError("weather data is missing columns: " + ", ".join(sorted(missing)))

    clean = table.loc[:, required].copy()
    clean["timestamp_utc"] = pd.to_datetime(
        clean["timestamp_utc"], utc=True, errors="raise"
    )
    for column in WEATHER_FEATURE_COLUMNS:
        clean[column] = pd.to_numeric(clean[column], errors="coerce")
    clean = clean.sort_values("timestamp_utc").reset_index(drop=True)

    if clean["timestamp_utc"].duplicated().any():
        raise ValueError("weather data contains duplicate timestamps")
    if len(clean) > 1:
        elapsed = clean["timestamp_utc"].diff().dropna().dt.total_seconds()
        if not elapsed.eq(3600.0).all():
            raise ValueError("weather data must be a continuous hourly series")
    if not np.isfinite(clean.loc[:, WEATHER_FEATURE_COLUMNS].to_numpy(float)).all():
        raise ValueError("weather data contains missing or non-finite values")
    if not clean["forecast_cloud_cover_percent"].between(0, 100).all():
        raise ValueError("cloud cover must be between zero and 100 percent")
    if not clean["forecast_relative_humidity_percent"].between(0, 100).all():
        raise ValueError("relative humidity must be between zero and 100 percent")
    if (clean["forecast_precipitation_mm"] < 0).any():
        raise ValueError("precipitation cannot be negative")
    return clean


def prepare_historical_weather_dataset(
    cache_directory: Path,
    *,
    start_date: date = date(2022, 1, 1),
    end_date: date = date(2024, 12, 31),
    latitude: float = CHARLOTTESVILLE_LATITUDE,
    longitude: float = CHARLOTTESVILLE_LONGITUDE,
    force_refresh: bool = False,
) -> Path:
    """Download yearly chunks and write one clean historical-forecast table."""

    yearly_tables: list[pd.DataFrame] = []
    for year in range(start_date.year, end_date.year + 1):
        chunk_start = max(start_date, date(year, 1, 1))
        chunk_end = min(end_date, date(year, 12, 31))
        request = OpenMeteoRequest(
            latitude=latitude,
            longitude=longitude,
            start_date=chunk_start,
            end_date=chunk_end,
        )
        raw_path = download_weather_data(
            request,
            cache_directory,
            force_refresh=force_refresh,
        )
        yearly_tables.append(load_weather_table(raw_path))

    combined = validate_weather_table(pd.concat(yearly_tables, ignore_index=True))
    processed_directory = Path(cache_directory) / "processed"
    processed_directory.mkdir(parents=True, exist_ok=True)
    processed_path = processed_directory / (
        f"charlottesville_weather_forecast_{start_date:%Y%m%d}_"
        f"{end_date:%Y%m%d}.csv"
    )
    combined.to_csv(processed_path, index=False)
    return processed_path


class OpenMeteoForecastClient:
    """Retrieve live hourly forecast features for exact UTC timestamps."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        http_get: Callable[..., Any] | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._http_get = http_get

    def hourly_forecast(
        self,
        *,
        latitude: float,
        longitude: float,
        timestamps_utc: Sequence[pd.Timestamp],
    ) -> pd.DataFrame:
        requested = pd.DatetimeIndex(timestamps_utc)
        if requested.empty:
            raise ValueError("at least one forecast timestamp is required")
        if requested.tz is None:
            raise ValueError("forecast timestamps must be timezone-aware")
        requested = requested.tz_convert("UTC")

        request = OpenMeteoRequest(
            latitude=latitude,
            longitude=longitude,
            start_date=requested.min().date(),
            end_date=requested.max().date(),
            endpoint=LIVE_FORECAST_URL,
        )
        get = self._http_get or requests.get
        response = get(
            request.endpoint,
            params=request.query_parameters(),
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        _validate_payload(payload)

        hourly = payload["hourly"]
        available = validate_weather_table(
            pd.DataFrame(
                {
                    "timestamp_utc": pd.to_datetime(
                        hourly["time"], utc=True, errors="raise"
                    ),
                    **{
                        WEATHER_COLUMN_NAMES[parameter]: pd.to_numeric(
                            hourly[parameter], errors="coerce"
                        )
                        for parameter in OPEN_METEO_PARAMETERS
                    },
                }
            )
        ).set_index("timestamp_utc")
        selected = available.reindex(requested)
        if selected.isna().any().any():
            raise ValueError(
                "Open-Meteo did not return every requested forecast hour"
            )
        selected.index.name = "timestamp_utc"
        return selected.reset_index()


def _validate_payload(payload: Mapping[str, Any]) -> None:
    if payload.get("timezone") not in {"GMT", "UTC"}:
        raise ValueError("Open-Meteo response must use GMT/UTC")
    hourly = payload.get("hourly")
    if not isinstance(hourly, Mapping):
        raise ValueError("Open-Meteo response is missing hourly data")
    expected = {"time", *OPEN_METEO_PARAMETERS}
    missing = expected - set(hourly)
    if missing:
        raise ValueError(
            "Open-Meteo response is missing fields: " + ", ".join(sorted(missing))
        )
    lengths = {len(hourly[name]) for name in expected}
    if len(lengths) != 1 or not lengths or next(iter(lengths)) == 0:
        raise ValueError("Open-Meteo hourly fields have inconsistent lengths")
