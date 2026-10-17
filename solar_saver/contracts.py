"""High-level interfaces. Implementations may change; these contracts should not."""

from __future__ import annotations

from typing import Protocol

from .domain import (
    CityScenario,
    ForecastRequest,
    ScheduleResult,
    SchedulerWeights,
    SimulationConfig,
    SolarProfile,
    Strategy,
)


class SolarForecaster(Protocol):
    def predict(self, request: ForecastRequest) -> SolarProfile:
        """Return one predicted solar-supply value per requested hour."""


class DemandGenerator(Protocol):
    def generate(
        self,
        solar_profile: SolarProfile,
        config: SimulationConfig,
    ) -> CityScenario:
        """Create a deterministic city scenario when given the same seed."""


class LoadScheduler(Protocol):
    def schedule(
        self,
        scenario: CityScenario,
        strategy: Strategy,
        weights: SchedulerWeights,
    ) -> ScheduleResult:
        """Schedule workloads and return complete aggregate profiles."""
