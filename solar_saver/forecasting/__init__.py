"""Solar forecasting implementations."""

from .baseline import SeasonalDemoForecaster
from .model import TrainedSolarForecaster

__all__ = ["SeasonalDemoForecaster", "TrainedSolarForecaster"]
