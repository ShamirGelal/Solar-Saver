"""Train, evaluate, and save Solar Saver's irradiance model."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from solar_saver.data.features import prepare_model_data
from solar_saver.forecasting.evaluation import evaluate_split
from solar_saver.forecasting.model import (
    DEFAULT_ARTIFACT_PATH,
    fit_solar_model,
    save_model_artifact,
)


DEFAULT_INPUT = Path(
    "data/processed/charlottesville_hourly_20200101_20241231.csv"
)
DEFAULT_METRICS = Path("outputs/solar_model_metrics.json")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train and evaluate the Solar Saver forecasting model."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT_PATH)
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    args = parser.parse_args()

    prepared = prepare_model_data(args.input)
    artifact = fit_solar_model(prepared)
    validation = evaluate_split(
        artifact, prepared.validation, split_name="validation"
    )
    test = evaluate_split(artifact, prepared.test, split_name="test")

    artifact_path = save_model_artifact(artifact, args.artifact)
    report = {
        "model_config": asdict(artifact.config),
        "validation": asdict(validation),
        "test": asdict(test),
        "artifact": str(artifact_path),
    }
    args.metrics.parent.mkdir(parents=True, exist_ok=True)
    args.metrics.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
