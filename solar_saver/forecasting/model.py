"""Gradient-boosting architecture and SolarForecaster implementation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.utils.validation import check_is_fitted

from solar_saver.data.features import (
    HISTORICAL_MEAN_COLUMN,
    MODEL_FEATURE_COLUMNS,
    MonthHourMeanEncoder,
    PreparedModelData,
    add_deterministic_features,
)
from solar_saver.data.nasa_power import (
    CHARLOTTESVILLE_LATITUDE,
    CHARLOTTESVILLE_LONGITUDE,
    CHARLOTTESVILLE_TIMEZONE,
)
from solar_saver.domain import ForecastRequest, SolarProfile


ARTIFACT_SCHEMA_VERSION = "1"
DEFAULT_ARTIFACT_PATH = Path("artifacts/solar_forecaster.joblib")


@dataclass(frozen=True)
class SolarModelConfig:
    """Inspectable starting configuration for the tabular regressor."""

    learning_rate: float = 0.05
    max_iter: int = 250
    max_leaf_nodes: int = 31
    max_depth: int = 6
    min_samples_leaf: int = 20
    l2_regularization: float = 1.0
    random_state: int = 42

    def __post_init__(self) -> None:
        if self.learning_rate <= 0 or self.max_iter <= 0:
            raise ValueError("learning_rate and max_iter must be positive")
        if self.max_leaf_nodes < 2 or self.max_depth < 1:
            raise ValueError("tree size settings are invalid")
        if self.min_samples_leaf < 1 or self.l2_regularization < 0:
            raise ValueError("regularization settings are invalid")


@dataclass
class SolarModelArtifact:
    """Everything required to reproduce inference without training data."""

    regressor: HistGradientBoostingRegressor
    historical_encoder: MonthHourMeanEncoder
    config: SolarModelConfig
    feature_names: tuple[str, ...]
    training_start_utc: str
    training_end_utc: str
    training_rows: int
    trained_at_utc: str
    latitude: float = CHARLOTTESVILLE_LATITUDE
    longitude: float = CHARLOTTESVILLE_LONGITUDE
    local_timezone: str = CHARLOTTESVILLE_TIMEZONE
    performance_ratio: float = 0.85
    reference_irradiance_wh_m2: float = 1000.0
    schema_version: str = ARTIFACT_SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != ARTIFACT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported artifact schema {self.schema_version!r}; "
                f"expected {ARTIFACT_SCHEMA_VERSION!r}"
            )
        if tuple(self.feature_names) != MODEL_FEATURE_COLUMNS:
            raise ValueError("artifact feature schema does not match this code version")
        if self.training_rows <= 0:
            raise ValueError("artifact must record at least one training row")
        if not 0 < self.performance_ratio <= 1:
            raise ValueError("performance_ratio must be between zero and one")
        if self.reference_irradiance_wh_m2 <= 0:
            raise ValueError("reference irradiance must be positive")
        check_is_fitted(self.regressor)


def build_regressor(
    config: SolarModelConfig = SolarModelConfig(),
) -> HistGradientBoostingRegressor:
    """Create the unfitted model with no random internal validation split."""

    return HistGradientBoostingRegressor(
        loss="squared_error",
        learning_rate=config.learning_rate,
        max_iter=config.max_iter,
        max_leaf_nodes=config.max_leaf_nodes,
        max_depth=config.max_depth,
        min_samples_leaf=config.min_samples_leaf,
        l2_regularization=config.l2_regularization,
        early_stopping=False,
        random_state=config.random_state,
    )


def fit_solar_model(
    prepared: PreparedModelData,
    *,
    config: SolarModelConfig = SolarModelConfig(),
    latitude: float = CHARLOTTESVILLE_LATITUDE,
    longitude: float = CHARLOTTESVILLE_LONGITUDE,
    local_timezone: str = CHARLOTTESVILLE_TIMEZONE,
) -> SolarModelArtifact:
    """Fit one candidate using only the training partition."""

    if tuple(prepared.training.features.columns) != MODEL_FEATURE_COLUMNS:
        raise ValueError("training features do not match the model schema")
    regressor = build_regressor(config)
    regressor.fit(prepared.training.features, prepared.training.target)

    artifact = SolarModelArtifact(
        regressor=regressor,
        historical_encoder=prepared.historical_encoder,
        config=config,
        feature_names=MODEL_FEATURE_COLUMNS,
        training_start_utc=prepared.training.timestamps_utc.min().isoformat(),
        training_end_utc=prepared.training.timestamps_utc.max().isoformat(),
        training_rows=len(prepared.training.target),
        trained_at_utc=datetime.now(timezone.utc).isoformat(),
        latitude=latitude,
        longitude=longitude,
        local_timezone=local_timezone,
    )
    artifact.validate()
    return artifact


def predict_irradiance(
    artifact: SolarModelArtifact, features: pd.DataFrame
) -> np.ndarray:
    """Predict physically constrained hourly irradiance in Wh/m^2."""

    artifact.validate()
    if tuple(features.columns) != tuple(artifact.feature_names):
        raise ValueError("prediction features do not match the artifact schema")
    prediction = np.asarray(artifact.regressor.predict(features), dtype=float)
    if not np.isfinite(prediction).all():
        raise ValueError("model produced a non-finite irradiance prediction")
    prediction = np.clip(
        prediction, 0.0, artifact.reference_irradiance_wh_m2
    )
    daylight = features["is_daylight"].to_numpy(dtype=bool)
    return np.where(daylight, prediction, 0.0)


def save_model_artifact(
    artifact: SolarModelArtifact,
    path: Path = DEFAULT_ARTIFACT_PATH,
) -> Path:
    artifact.validate()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    joblib.dump(artifact, temporary_path)
    temporary_path.replace(path)
    return path


def load_model_artifact(
    path: Path = DEFAULT_ARTIFACT_PATH,
) -> SolarModelArtifact:
    artifact = joblib.load(Path(path))
    if not isinstance(artifact, SolarModelArtifact):
        raise TypeError("file does not contain a SolarModelArtifact")
    artifact.validate()
    return artifact


class TrainedSolarForecaster:
    """Adapter from a fitted artifact to the shared SolarForecaster contract."""

    def __init__(self, artifact: SolarModelArtifact) -> None:
        artifact.validate()
        self._artifact = artifact

    @classmethod
    def from_path(
        cls, path: Path = DEFAULT_ARTIFACT_PATH
    ) -> "TrainedSolarForecaster":
        return cls(load_model_artifact(path))

    def predict(self, request: ForecastRequest) -> SolarProfile:
        if request.horizon_hours <= 0:
            raise ValueError("horizon_hours must be positive")
        if request.installed_capacity_kw <= 0:
            raise ValueError("installed_capacity_kw must be positive")

        features = _build_request_features(self._artifact, request)
        irradiance = predict_irradiance(self._artifact, features)
        normalized_irradiance = (
            irradiance / self._artifact.reference_irradiance_wh_m2
        )
        supply_kw = (
            request.installed_capacity_kw
            * self._artifact.performance_ratio
            * normalized_irradiance
        )
        supply_kw = np.clip(supply_kw, 0.0, request.installed_capacity_kw)
        if len(supply_kw) != request.horizon_hours or not np.isfinite(supply_kw).all():
            raise ValueError("forecaster produced an invalid supply profile")

        return SolarProfile(
            supply_kw=tuple(float(round(value, 3)) for value in supply_kw),
            model_name="hist-gradient-boosting-expected-solar-v1",
            metadata={
                "artifact_schema": self._artifact.schema_version,
                "forecast_type": "expected solar availability",
                "irradiance_unit": "Wh/m^2",
                "performance_ratio": self._artifact.performance_ratio,
                "training_start_utc": self._artifact.training_start_utc,
                "training_end_utc": self._artifact.training_end_utc,
            },
        )


def _build_request_features(
    artifact: SolarModelArtifact, request: ForecastRequest
) -> pd.DataFrame:
    local_start = pd.Timestamp(request.target_date).tz_localize(
        artifact.local_timezone
    )
    local_timestamps = pd.date_range(
        start=local_start, periods=request.horizon_hours, freq="h"
    )
    future = pd.DataFrame(
        {"timestamp_utc": local_timestamps.tz_convert("UTC")}
    )
    future = add_deterministic_features(
        future,
        latitude=request.latitude,
        longitude=request.longitude,
        local_timezone=artifact.local_timezone,
    )
    future[HISTORICAL_MEAN_COLUMN] = artifact.historical_encoder.transform(future)
    return future.loc[:, artifact.feature_names].astype(float)
