from __future__ import annotations

from datetime import date
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from solar_saver.data.features import (
    HISTORICAL_MEAN_COLUMN,
    MODEL_FEATURE_COLUMNS,
    MonthHourMeanEncoder,
    add_deterministic_features,
)
from solar_saver.demand import SyntheticDemandGenerator
from solar_saver.domain import (
    ForecastRequest,
    SchedulerWeights,
    SimulationConfig,
)
from solar_saver.forecasting.model import (
    SolarModelArtifact,
    SolarModelConfig,
    TrainedSolarForecaster,
    build_regressor,
    load_model_artifact,
    save_model_artifact,
)
from solar_saver.pipeline import run_comparison
from solar_saver.scheduling import GreedyLoadScheduler


def fitted_test_artifact() -> SolarModelArtifact:
    timestamps = pd.date_range(
        "2020-01-01 00:00:00+00:00", periods=24 * 90, freq="h"
    )
    history = pd.DataFrame({"timestamp_utc": timestamps})
    featured = add_deterministic_features(history)
    daylight = featured["is_daylight"].to_numpy(dtype=float)
    target = np.maximum(
        0.0,
        850.0
        * daylight
        * np.sin(np.pi * (featured["local_hour"].to_numpy() - 6.0) / 14.0),
    )
    featured["solar_irradiance_wh_m2"] = target
    encoder = MonthHourMeanEncoder()
    featured[HISTORICAL_MEAN_COLUMN] = encoder.fit_transform_training(featured)
    features = featured.loc[:, MODEL_FEATURE_COLUMNS].astype(float)
    config = SolarModelConfig(max_iter=10, max_depth=3, min_samples_leaf=5)
    regressor = build_regressor(config)
    regressor.fit(features, target)
    return SolarModelArtifact(
        regressor=regressor,
        historical_encoder=encoder,
        config=config,
        feature_names=MODEL_FEATURE_COLUMNS,
        training_start_utc=timestamps.min().isoformat(),
        training_end_utc=timestamps.max().isoformat(),
        training_rows=len(timestamps),
        trained_at_utc="2026-10-17T00:00:00+00:00",
    )


class SolarModelArchitectureTests(unittest.TestCase):
    def test_regressor_does_not_use_random_internal_validation(self) -> None:
        regressor = build_regressor()
        self.assertFalse(regressor.early_stopping)
        self.assertEqual(regressor.loss, "squared_error")

    def test_trained_forecaster_obeys_shared_output_contract(self) -> None:
        forecaster = TrainedSolarForecaster(fitted_test_artifact())
        profile = forecaster.predict(
            ForecastRequest(
                latitude=38.0293,
                longitude=-78.4767,
                target_date=date(2026, 6, 21),
                installed_capacity_kw=500.0,
            )
        )

        self.assertEqual(len(profile.supply_kw), 24)
        self.assertTrue(np.isfinite(profile.supply_kw).all())
        self.assertTrue(all(0.0 <= value <= 500.0 for value in profile.supply_kw))
        self.assertEqual(profile.supply_kw[0], 0.0)
        self.assertEqual(profile.model_name, "hist-gradient-boosting-expected-solar-v1")

    def test_artifact_round_trip_preserves_predictions(self) -> None:
        artifact = fitted_test_artifact()
        request = ForecastRequest(
            latitude=38.0293,
            longitude=-78.4767,
            target_date=date(2026, 7, 1),
            installed_capacity_kw=300.0,
        )
        expected = TrainedSolarForecaster(artifact).predict(request)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.joblib"
            save_model_artifact(artifact, path)
            loaded = load_model_artifact(path)
            actual = TrainedSolarForecaster(loaded).predict(request)

        self.assertEqual(actual.supply_kw, expected.supply_kw)

    def test_trained_forecaster_plugs_into_existing_pipeline(self) -> None:
        report = run_comparison(
            forecast_request=ForecastRequest(
                latitude=38.0293,
                longitude=-78.4767,
                target_date=date(2026, 6, 21),
                installed_capacity_kw=300.0,
            ),
            simulation_config=SimulationConfig(number_of_users=10, random_seed=7),
            scheduler_weights=SchedulerWeights(),
            forecaster=TrainedSolarForecaster(fitted_test_artifact()),
            demand_generator=SyntheticDemandGenerator(),
            scheduler=GreedyLoadScheduler(),
        )
        self.assertEqual(len(report.solar_profile.supply_kw), 24)
        self.assertEqual(
            report.solar_profile.model_name,
            "hist-gradient-boosting-expected-solar-v1",
        )


if __name__ == "__main__":
    unittest.main()
