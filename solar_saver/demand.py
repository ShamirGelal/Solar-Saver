"""Synthetic household demand; not observed Charlottesville utility data.

Each user is one household with one modeled flexible request that day. Appliance
powers are constant equivalent averages over whole-hour blocks, not measured
instantaneous appliance traces. Other household electricity use belongs in the
fixed background only, excluding the separately modeled flexible request.

No solar prediction, scheduling, storage discharge, or critical infrastructure
is modeled here. See data/demo/README.md for assumptions and benchmark fixtures.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .domain import CityScenario, Priority, SimulationConfig, SolarProfile, Workload


@dataclass(frozen=True)
class _Appliance:
    category: str
    power_kw: float
    duration: int
    earliest: int
    latest: int
    preferred: int
    priority: Priority
    flexibility: float


class SyntheticDemandGenerator:
    """Generate one reproducible, unscheduled request per household.

    Category probabilities are equal for demo coverage, not estimates of device
    ownership. Availability is sampled as evening (50%), daytime (30%), or tight
    (20%). All distributions are explicit synthetic scenario assumptions.
    """

    _templates = (
        _Appliance("ev_charging", 7.2, 3, 8, 24, 19, Priority.IMPORTANT, 0.7),
        _Appliance("laundry", 0.8, 1, 8, 20, 14, Priority.FLEXIBLE, 0.8),
        _Appliance("dishwasher", 1.2, 2, 8, 23, 19, Priority.FLEXIBLE, 0.7),
        _Appliance("battery", 2.0, 3, 7, 22, 13, Priority.FLEXIBLE, 0.9),
        _Appliance("water_heating", 3.0, 1, 5, 22, 18, Priority.IMPORTANT, 0.4),
    )

    def generate(
        self,
        solar_profile: SolarProfile,
        config: SimulationConfig,
    ) -> CityScenario:
        self._validate_inputs(solar_profile, config)
        rng = random.Random(config.random_seed)
        horizon = len(solar_profile.supply_kw)

        # Preserve the scaffold's synthetic 100-household reference exactly.
        # Scaling demand never scales the caller's capacity or solar input.
        reference = tuple(
            round(
                120
                + 35 * math.exp(-((hour - 8) / 2.2) ** 2)
                + 65 * math.exp(-((hour - 19) / 2.8) ** 2),
                3,
            )
            for hour in range(horizon)
        )
        base = tuple(round(value * config.number_of_users / 100, 3) for value in reference)
        if max(base) > config.grid_capacity_kw:
            raise ValueError(
                "base demand exceeds capacity: "
                f"{config.number_of_users} households require at least {max(base):g} kW "
                f"for background demand; grid_capacity_kw={config.grid_capacity_kw:g}. "
                "Supply a larger capacity or fewer households explicitly."
            )

        workloads = tuple(self._make_workload(index, rng)
                          for index in range(config.number_of_users))

        return CityScenario(
            solar_supply_kw=solar_profile.supply_kw,
            base_demand_kw=base,
            grid_capacity_kw=tuple(config.grid_capacity_kw for _ in range(horizon)),
            workloads=workloads,
        )

    @staticmethod
    def _validate_inputs(solar_profile: SolarProfile, config: SimulationConfig) -> None:
        if (isinstance(config.number_of_users, bool)
                or not isinstance(config.number_of_users, int)
                or not _finite_nonnegative(config.number_of_users)):
            raise ValueError("number_of_users must be a finite, nonnegative integer household count")
        if isinstance(config.random_seed, bool) or not isinstance(config.random_seed, int):
            raise ValueError("random_seed must be an integer for reproducible demand")
        if not _finite_nonnegative(config.grid_capacity_kw):
            raise ValueError("grid_capacity_kw must be a finite, nonnegative number")
        values = solar_profile.supply_kw
        if not isinstance(values, tuple) or len(values) != 24:
            raise ValueError("supply_kw must be a tuple of exactly 24 hourly values")
        if any(not _finite_nonnegative(value) for value in values):
            raise ValueError("supply_kw must contain finite, nonnegative numbers")
        try:
            math.fsum(values)
        except OverflowError as error:
            raise ValueError("supply_kw daily energy must be finite") from error

    def _make_workload(self, index: int, rng: random.Random) -> Workload:
        appliance = rng.choice(self._templates)
        earliest, latest = appliance.earliest, appliance.latest
        availability = rng.randrange(10)
        flexibility = appliance.flexibility
        preferred = appliance.preferred + rng.choice((-1, 0, 0, 1))

        if availability < 5:
            # Appliances/vehicles become available when the household returns.
            earliest = max(earliest, rng.randint(16, 18))
            preferred = max(18, preferred)
            flexibility *= 0.75
        elif availability < 8 and appliance.category == "ev_charging":
            # Only the daytime-available EV group may charge around midday.
            preferred = 13 + rng.choice((-1, 0, 1))

        preferred = min(latest - appliance.duration, max(earliest, preferred))
        if availability >= 8:
            # A tight household allows at most one hour either side of its
            # preferred start, with enough room for the COMPLETE task.
            earliest = max(earliest, preferred - rng.randint(0, 1))
            latest = min(latest, preferred + appliance.duration + rng.randint(0, 1))
            flexibility *= 0.25

        return Workload(
            workload_id=f"load-{index:04d}", user_id=f"user-{index:04d}",
            category=appliance.category, power_kw=appliance.power_kw,
            duration_hours=appliance.duration, earliest_start=earliest,
            latest_finish=latest, preferred_start=preferred,
            priority=appliance.priority, flexibility=round(flexibility, 3),
        )


def _finite_nonnegative(value: object) -> bool:
    """Reject booleans and nonnumeric data, including unrepresentable integers."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except OverflowError:
        return False
