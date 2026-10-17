"""Stable data contracts shared by every Solar Saver subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Mapping, Sequence


class Priority(str, Enum):
    CRITICAL = "critical"
    IMPORTANT = "important"
    FLEXIBLE = "flexible"


class Strategy(str, Enum):
    UNCOORDINATED = "uncoordinated"
    SOLAR_ONLY = "solar_only"
    BALANCED = "balanced"


@dataclass(frozen=True)
class ForecastRequest:
    latitude: float
    longitude: float
    target_date: date
    installed_capacity_kw: float
    horizon_hours: int = 24


@dataclass(frozen=True)
class SolarProfile:
    """Predicted aggregate solar supply, one value per hourly slot."""

    supply_kw: tuple[float, ...]
    model_name: str
    metadata: Mapping[str, str | float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.supply_kw or any(value < 0 for value in self.supply_kw):
            raise ValueError("supply_kw must contain nonnegative hourly values")


@dataclass(frozen=True)
class Workload:
    workload_id: str
    user_id: str
    category: str
    power_kw: float
    duration_hours: int
    earliest_start: int
    latest_finish: int
    preferred_start: int
    priority: Priority
    flexibility: float = 0.5

    def __post_init__(self) -> None:
        if self.power_kw <= 0 or self.duration_hours <= 0:
            raise ValueError("workload power and duration must be positive")
        if not 0 <= self.earliest_start < self.latest_finish:
            raise ValueError("workload window is invalid")
        if self.latest_finish - self.earliest_start < self.duration_hours:
            raise ValueError("workload does not fit inside its allowed window")
        if not self.earliest_start <= self.preferred_start < self.latest_finish:
            raise ValueError("preferred_start must be inside the allowed window")
        if not 0 <= self.flexibility <= 1:
            raise ValueError("flexibility must be between 0 and 1")


@dataclass(frozen=True)
class SimulationConfig:
    number_of_users: int = 100
    random_seed: int = 42
    grid_capacity_kw: float = 500.0


@dataclass(frozen=True)
class CityScenario:
    solar_supply_kw: tuple[float, ...]
    base_demand_kw: tuple[float, ...]
    grid_capacity_kw: tuple[float, ...]
    workloads: tuple[Workload, ...]

    def __post_init__(self) -> None:
        horizon = len(self.solar_supply_kw)
        if horizon == 0:
            raise ValueError("scenario must contain at least one time slot")
        if len(self.base_demand_kw) != horizon or len(self.grid_capacity_kw) != horizon:
            raise ValueError("all scenario profiles must use the same horizon")

    @property
    def horizon_hours(self) -> int:
        return len(self.solar_supply_kw)


@dataclass(frozen=True)
class SchedulerWeights:
    grid_energy: float = 1.0
    preference: float = 0.5
    peak: float = 0.25
    fairness: float = 0.25


@dataclass(frozen=True)
class Assignment:
    workload_id: str
    scheduled_start: int
    scheduled_end: int


@dataclass(frozen=True)
class ScheduleResult:
    strategy: Strategy
    assignments: tuple[Assignment, ...]
    unscheduled_workload_ids: tuple[str, ...]
    flexible_demand_kw: tuple[float, ...]
    total_demand_kw: tuple[float, ...]
    solar_used_kw: tuple[float, ...]
    grid_draw_kw: tuple[float, ...]


@dataclass(frozen=True)
class ScheduleMetrics:
    grid_energy_kwh: float
    solar_used_kwh: float
    unused_solar_kwh: float
    renewable_match_percent: float
    peak_demand_kw: float
    average_preference_deviation_hours: float
    maximum_preference_deviation_hours: int
    completion_percent: float
    critical_completion_percent: float
    capacity_violation_hours: int


@dataclass(frozen=True)
class StrategyReport:
    result: ScheduleResult
    metrics: ScheduleMetrics


@dataclass(frozen=True)
class SimulationReport:
    scenario: CityScenario
    solar_profile: SolarProfile
    strategies: Mapping[Strategy, StrategyReport]


NumericProfile = Sequence[float]
