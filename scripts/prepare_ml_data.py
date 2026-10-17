"""Reproduce all local datasets required for solar model training."""

from __future__ import annotations

from pathlib import Path

from solar_saver.data.features import combine_model_splits, prepare_model_data
from solar_saver.data.nasa_power import prepare_training_dataset
from solar_saver.data.open_meteo import prepare_historical_weather_dataset


MODEL_TABLE_PATH = Path(
    "data/processed/charlottesville_weather_model_input_20220101_20241231.csv"
)


def main() -> None:
    data_directory = Path("data")
    nasa_path = prepare_training_dataset(data_directory)
    weather_path = prepare_historical_weather_dataset(data_directory)
    prepared = prepare_model_data(nasa_path, weather_path)
    model_table = combine_model_splits(prepared)
    MODEL_TABLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    model_table.to_csv(MODEL_TABLE_PATH, index=False)

    print(f"NASA history: {nasa_path}")
    print(f"Open-Meteo forecast history: {weather_path}")
    print(f"Model table: {MODEL_TABLE_PATH}")
    print(
        "Rows: "
        f"training={len(prepared.training.target):,}, "
        f"validation={len(prepared.validation.target):,}, "
        f"test={len(prepared.test.target):,}"
    )


if __name__ == "__main__":
    main()
