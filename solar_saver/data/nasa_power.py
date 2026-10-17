"""NASA POWER data boundary.

The forecasting owner should implement downloading, caching, validation, and
feature preparation here or in adjacent modules. No other subsystem should
depend on NASA response formats.
"""

from __future__ import annotations

from pathlib import Path


def prepare_training_dataset(cache_directory: Path) -> Path:
    """Return a path to a clean training table.

    This deliberate stub documents the boundary while allowing the rest of the
    backend to run with SeasonalDemoForecaster.
    """

    raise NotImplementedError("Forecasting owner must implement NASA POWER ingestion")
