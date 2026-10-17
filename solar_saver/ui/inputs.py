"""User-input validation and a demand adapter owned by the UI.

Custom workloads replace the synthetic flexible population. The existing demand
generator still supplies the same clearly labelled simulated district background.
Shared domain types, component protocols, and scheduling algorithms stay intact.
"""

from __future__ import annotations

from dataclasses import replace
from math import isfinite

from solar_saver.demand import SyntheticDemandGenerator
from solar_saver.domain import (
    CityScenario, Priority, SimulationConfig, SolarProfile, Workload,
)


MAX_WORKLOADS = 100


def parse_workloads(payload: object) -> tuple[Workload, ...]:
    if not isinstance(payload, dict) or not isinstance(payload.get("workloads"), list):
        raise ValueError("Provide a JSON object containing a workloads list.")
    rows = payload["workloads"]
    if len(rows) > MAX_WORKLOADS:
        raise ValueError(f"Enter no more than {MAX_WORKLOADS} loads per comparison.")

    workloads = []
    seen = set()
    for index, row in enumerate(rows, start=1):
        prefix = f"Load {index}"
        if not isinstance(row, dict):
            raise ValueError(f"{prefix} must be an object.")
        identifier = _text(row, "workload_id", prefix)
        if identifier in seen:
            raise ValueError("Every load must have a unique workload_id.")
        seen.add(identifier)
        category = _text(row, "category", prefix)
        power = _number(row, "power_kw", prefix)
        flexibility = _number(row, "flexibility", prefix)
        if not 0 < power <= 10_000:
            raise ValueError(f"{prefix}: power must be greater than 0 and at most 10,000 kW.")
        if not 0 <= flexibility <= 1:
            raise ValueError(f"{prefix}: flexibility must be between 0 and 1.")
        duration = _hour(row, "duration_hours", 1, 24, prefix)
        earliest = _hour(row, "earliest_start", 0, 23, prefix)
        latest = _hour(row, "latest_finish", 1, 24, prefix)
        preferred = _hour(row, "preferred_start", 0, 23, prefix)
        if earliest + duration > latest:
            raise ValueError(f"{prefix}: the duration must fit within the allowed window.")
        if not earliest <= preferred <= latest - duration:
            raise ValueError(f"{prefix}: the preferred start must allow the whole load to finish within its window.")
        try:
            priority = Priority(row.get("priority"))
        except (ValueError, TypeError):
            raise ValueError(f"{prefix}: choose critical, important, or flexible priority.") from None
        workloads.append(Workload(
            workload_id=identifier, user_id="planner", category=category,
            power_kw=power, duration_hours=duration, earliest_start=earliest,
            latest_finish=latest, preferred_start=preferred, priority=priority,
            flexibility=flexibility,
        ))
    return tuple(workloads)


class EnteredLoadDemandGenerator:
    """Implement DemandGenerator using validated user-entered Workload objects."""

    def __init__(self, workloads: tuple[Workload, ...]) -> None:
        self.workloads = workloads

    def generate(self, solar_profile: SolarProfile, config: SimulationConfig) -> CityScenario:
        background = SyntheticDemandGenerator().generate(
            solar_profile, replace(config, number_of_users=0),
        )
        return replace(background, workloads=self.workloads)


def _text(row: dict, field: str, prefix: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 64:
        raise ValueError(f"{prefix}: {field} must contain 1–64 characters.")
    return value.strip()


def _number(row: dict, field: str, prefix: str) -> float:
    value = row.get(field)
    if type(value) not in (int, float):
        raise ValueError(f"{prefix}: {field} must be a finite number.")
    try:
        value = float(value)
    except (OverflowError, ValueError):
        raise ValueError(f"{prefix}: {field} must be a finite number.") from None
    if not isfinite(value):
        raise ValueError(f"{prefix}: {field} must be a finite number.")
    return value


def _hour(row: dict, field: str, lower: int, upper: int, prefix: str) -> int:
    value = row.get(field)
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f"{prefix}: {field} must be a whole number from {lower} to {upper}.")
    return value
