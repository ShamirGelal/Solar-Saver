"""Evaluation helpers for the trained model and historical baseline."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error

from solar_saver.data.features import HISTORICAL_MEAN_COLUMN, ModelSplit
from solar_saver.forecasting.model import SolarModelArtifact, predict_irradiance


@dataclass(frozen=True)
class RegressionMetrics:
    rows: int
    mae_wh_m2: float
    rmse_wh_m2: float


@dataclass(frozen=True)
class SplitEvaluation:
    split_name: str
    model_all_hours: RegressionMetrics
    baseline_all_hours: RegressionMetrics
    model_daylight: RegressionMetrics
    baseline_daylight: RegressionMetrics


def evaluate_split(
    artifact: SolarModelArtifact,
    split: ModelSplit,
    *,
    split_name: str,
) -> SplitEvaluation:
    """Compare model and historical-average baseline on one fixed partition."""

    target = split.target.to_numpy(dtype=float)
    model_prediction = predict_irradiance(artifact, split.features)
    baseline_prediction = split.features[HISTORICAL_MEAN_COLUMN].to_numpy(
        dtype=float
    )
    daylight = split.features["is_daylight"].to_numpy(dtype=bool)
    baseline_prediction = np.where(daylight, baseline_prediction, 0.0)
    if not daylight.any():
        raise ValueError("evaluation split contains no daylight observations")

    return SplitEvaluation(
        split_name=split_name,
        model_all_hours=_metrics(target, model_prediction),
        baseline_all_hours=_metrics(target, baseline_prediction),
        model_daylight=_metrics(target[daylight], model_prediction[daylight]),
        baseline_daylight=_metrics(target[daylight], baseline_prediction[daylight]),
    )


def _metrics(target: np.ndarray, prediction: np.ndarray) -> RegressionMetrics:
    return RegressionMetrics(
        rows=len(target),
        mae_wh_m2=float(mean_absolute_error(target, prediction)),
        rmse_wh_m2=float(math.sqrt(mean_squared_error(target, prediction))),
    )
