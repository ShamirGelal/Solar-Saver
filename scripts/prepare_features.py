"""Create the auditable feature table consumed by model training."""

from __future__ import annotations

import argparse
from pathlib import Path

from solar_saver.data.features import (
    MODEL_FEATURE_COLUMNS,
    TARGET_COLUMN,
    combine_model_splits,
    prepare_model_data,
)


DEFAULT_INPUT = Path(
    "data/processed/charlottesville_hourly_20200101_20241231.csv"
)
DEFAULT_WEATHER = Path(
    "data/processed/charlottesville_weather_forecast_20220101_20241231.csv"
)
DEFAULT_OUTPUT = Path(
    "data/processed/charlottesville_weather_model_input_20220101_20241231.csv"
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare Solar Saver's chronological ML feature table."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--weather", type=Path, default=DEFAULT_WEATHER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    prepared = prepare_model_data(args.input, args.weather)
    model_table = combine_model_splits(prepared)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    model_table.to_csv(args.output, index=False)

    counts = model_table["split"].value_counts()
    print(f"Saved {len(model_table):,} hourly rows to {args.output}")
    print(
        "Splits: "
        f"training={counts.get('training', 0):,}, "
        f"validation={counts.get('validation', 0):,}, "
        f"test={counts.get('test', 0):,}"
    )
    print("Features: " + ", ".join(MODEL_FEATURE_COLUMNS))
    print(f"Target: {TARGET_COLUMN}")


if __name__ == "__main__":
    main()
