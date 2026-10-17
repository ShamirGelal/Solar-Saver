"""Download and normalize hourly NASA POWER data for solar forecasting.

NASA response details are intentionally contained in this module. The rest of
the forecasting code consumes a stable pandas table with explicit units and
timezone-aware timestamps.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd
import requests


POWER_HOURLY_POINT_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"
CHARLOTTESVILLE_LATITUDE = 38.0293
CHARLOTTESVILLE_LONGITUDE = -78.4767
CHARLOTTESVILLE_TIMEZONE = "America/New_York"

DEFAULT_PARAMETERS = (
    "ALLSKY_SFC_SW_DWN",
    "T2M",
    "RH2M",
    "WS10M",
)

_COLUMN_NAMES = {
    "ALLSKY_SFC_SW_DWN": "solar_irradiance_wh_m2",
    "T2M": "temperature_c",
    "RH2M": "relative_humidity_percent",
    "WS10M": "wind_speed_m_s",
}


@dataclass(frozen=True)
class NasaPowerRequest:
    """A reproducible request for one location's hourly POWER history."""

    latitude: float
    longitude: float
    start_date: date
    end_date: date
    parameters: tuple[str, ...] = DEFAULT_PARAMETERS
    time_standard: str = "UTC"

    def __post_init__(self) -> None:
        if not -90 <= self.latitude <= 90:
            raise ValueError("latitude must be between -90 and 90")
        if not -180 <= self.longitude <= 180:
            raise ValueError("longitude must be between -180 and 180")
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        if not self.parameters:
            raise ValueError("at least one NASA POWER parameter is required")
        if len(self.parameters) > 15:
            raise ValueError("NASA POWER accepts at most 15 parameters per request")
        if self.time_standard != "UTC":
            raise ValueError("Solar Saver requests UTC and converts time explicitly")

    def query_parameters(self) -> dict[str, str | float]:
        return {
            "parameters": ",".join(self.parameters),
            "community": "RE",
            "longitude": self.longitude,
            "latitude": self.latitude,
            "start": self.start_date.strftime("%Y%m%d"),
            "end": self.end_date.strftime("%Y%m%d"),
            "format": "JSON",
            "time-standard": self.time_standard,
        }

    def cache_name(self) -> str:
        canonical_query = json.dumps(
            self.query_parameters(), sort_keys=True, separators=(",", ":")
        )
        digest = hashlib.sha256(canonical_query.encode("utf-8")).hexdigest()[:12]
        return (
            f"nasa_power_hourly_{self.start_date:%Y%m%d}_"
            f"{self.end_date:%Y%m%d}_{digest}.json"
        )


def download_hourly_data(
    request: NasaPowerRequest,
    cache_directory: Path,
    *,
    force_refresh: bool = False,
    timeout_seconds: float = 60.0,
    http_get: Callable[..., Any] | None = None,
) -> Path:
    """Download a POWER response once and return its cached JSON path."""

    raw_directory = Path(cache_directory) / "raw"
    raw_directory.mkdir(parents=True, exist_ok=True)
    cache_path = raw_directory / request.cache_name()
    if cache_path.exists() and not force_refresh:
        return cache_path

    get = http_get or requests.get
    response = get(
        POWER_HOURLY_POINT_URL,
        params=request.query_parameters(),
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    _validate_payload(payload, request)

    temporary_path = cache_path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(payload), encoding="utf-8")
    temporary_path.replace(cache_path)
    return cache_path


def load_hourly_table(
    json_path: Path,
    *,
    local_timezone: str = CHARLOTTESVILLE_TIMEZONE,
) -> pd.DataFrame:
    """Convert a cached NASA response to an analysis-ready hourly table."""

    payload = json.loads(Path(json_path).read_text(encoding="utf-8"))
    parameter_data = _parameter_data(payload)
    fill_value = float(payload.get("header", {}).get("fill_value", -999.0))

    series_by_parameter: dict[str, pd.Series] = {}
    for parameter, values_by_time in parameter_data.items():
        timestamps = pd.to_datetime(
            list(values_by_time), format="%Y%m%d%H", utc=True, errors="raise"
        )
        values = pd.to_numeric(list(values_by_time.values()), errors="coerce")
        values = np.where(np.isclose(values, fill_value), np.nan, values)
        series_by_parameter[parameter] = pd.Series(values, index=timestamps)

    table = pd.DataFrame(series_by_parameter).sort_index()
    table.index.name = "timestamp_utc"
    if table.index.has_duplicates:
        raise ValueError("NASA POWER response contains duplicate UTC timestamps")
    if len(table.index) > 1:
        elapsed = table.index.to_series().diff().dropna()
        if not elapsed.dt.total_seconds().eq(3600.0).all():
            raise ValueError("NASA POWER response is not a continuous hourly series")

    table = table.rename(columns=_COLUMN_NAMES)
    table.insert(0, "timestamp_local", table.index.tz_convert(local_timezone))
    table["local_date"] = table["timestamp_local"].dt.date
    table["local_hour"] = table["timestamp_local"].dt.hour
    return table


def prepare_training_dataset(
    cache_directory: Path,
    *,
    start_date: date = date(2020, 1, 1),
    end_date: date = date(2024, 12, 31),
    latitude: float = CHARLOTTESVILLE_LATITUDE,
    longitude: float = CHARLOTTESVILLE_LONGITUDE,
    force_refresh: bool = False,
) -> Path:
    """Download, normalize, and save Charlottesville's hourly training table."""

    request = NasaPowerRequest(
        latitude=latitude,
        longitude=longitude,
        start_date=start_date,
        end_date=end_date,
    )
    raw_path = download_hourly_data(
        request,
        cache_directory,
        force_refresh=force_refresh,
    )
    table = load_hourly_table(raw_path)

    target = "solar_irradiance_wh_m2"
    if target not in table:
        raise ValueError(f"NASA POWER response is missing required target {target}")
    if table[target].isna().all():
        raise ValueError("NASA POWER solar target contains no usable observations")

    processed_directory = Path(cache_directory) / "processed"
    processed_directory.mkdir(parents=True, exist_ok=True)
    processed_path = processed_directory / (
        f"charlottesville_hourly_{start_date:%Y%m%d}_{end_date:%Y%m%d}.csv"
    )
    table.to_csv(processed_path, index=True)
    return processed_path


def _validate_payload(
    payload: Mapping[str, Any], request: NasaPowerRequest
) -> None:
    parameter_data = _parameter_data(payload)
    missing = set(request.parameters) - set(parameter_data)
    if missing:
        raise ValueError(
            "NASA POWER response is missing parameters: "
            + ", ".join(sorted(missing))
        )
    header = payload.get("header", {})
    if header.get("time_standard") != request.time_standard:
        raise ValueError("NASA POWER returned an unexpected time standard")
    if not all(parameter_data[name] for name in request.parameters):
        raise ValueError("NASA POWER returned an empty parameter series")


def _parameter_data(payload: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    try:
        parameter_data = payload["properties"]["parameter"]
    except (KeyError, TypeError) as error:
        raise ValueError("NASA POWER response has an unexpected structure") from error
    if not isinstance(parameter_data, Mapping):
        raise ValueError("NASA POWER parameter data must be a mapping")
    return parameter_data
