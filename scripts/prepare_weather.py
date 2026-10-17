"""Download and validate Open-Meteo historical forecast features."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from solar_saver.data.open_meteo import prepare_historical_weather_dataset


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare Charlottesville Open-Meteo forecast history."
    )
    parser.add_argument("--cache-directory", type=Path, default=Path("data"))
    parser.add_argument("--start", type=date.fromisoformat, default=date(2022, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2024, 12, 31))
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args()

    path = prepare_historical_weather_dataset(
        args.cache_directory,
        start_date=args.start,
        end_date=args.end,
        force_refresh=args.force_refresh,
    )
    print(f"Saved validated weather history to {path}")


if __name__ == "__main__":
    main()
