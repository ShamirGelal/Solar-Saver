"""Synthetic Charlottesville demand generation."""

from __future__ import annotations

import math
import random

from .domain import CityScenario, Priority, SimulationConfig, SolarProfile, Workload


class SyntheticDemandGenerator:
    """Generate reproducible flexible loads and a fixed background profile."""

    _templates = (
        ("ev_charging", 7.2, 3, 16, 24, 19, Priority.IMPORTANT, 0.7),
        ("laundry", 0.8, 1, 8, 20, 14, Priority.FLEXIBLE, 0.8),
        ("dishwasher", 1.2, 2, 8, 23, 19, Priority.FLEXIBLE, 0.7),
        ("battery", 2.0, 3, 7, 22, 13, Priority.FLEXIBLE, 0.9),
        ("water_heating", 3.0, 1, 5, 22, 18, Priority.IMPORTANT, 0.4),
    )

    def generate(
        self,
        solar_profile: SolarProfile,
        config: SimulationConfig,
    ) -> CityScenario:
        rng = random.Random(config.random_seed)
        horizon = len(solar_profile.supply_kw)
        if horizon != 24:
            raise ValueError("MVP demand generator currently requires 24 hourly slots")

        base = tuple(
            round(
                120
                + 35 * math.exp(-((hour - 8) / 2.2) ** 2)
                + 65 * math.exp(-((hour - 19) / 2.8) ** 2),
                3,
            )
            for hour in range(horizon)
        )

        workloads: list[Workload] = []
        for user_index in range(config.number_of_users):
            template = rng.choice(self._templates)
            category, power, duration, earliest, latest, preferred, priority, flexibility = template
            jittered_preference = min(latest - duration, max(earliest, preferred + rng.choice((-1, 0, 0, 1))))
            workloads.append(
                Workload(
                    workload_id=f"load-{user_index:04d}",
                    user_id=f"user-{user_index:04d}",
                    category=category,
                    power_kw=power,
                    duration_hours=duration,
                    earliest_start=earliest,
                    latest_finish=latest,
                    preferred_start=jittered_preference,
                    priority=priority,
                    flexibility=flexibility,
                )
            )

        return CityScenario(
            solar_supply_kw=solar_profile.supply_kw,
            base_demand_kw=base,
            grid_capacity_kw=tuple(config.grid_capacity_kw for _ in range(horizon)),
            workloads=tuple(workloads),
        )
