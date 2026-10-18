"""Presentation scenarios owned by the UI integration layer.

These workloads are deterministic aggregate demonstration assumptions. They do
not represent observed Charlottesville customers or individual households.
"""

from __future__ import annotations

from solar_saver.domain import Priority, Workload


SHOWCASE_GROUP_COUNT = 100
SHOWCASE_APPLIANCES_PER_GROUP = 200
SHOWCASE_REPRESENTED_APPLIANCES = (
    SHOWCASE_GROUP_COUNT * SHOWCASE_APPLIANCES_PER_GROUP
)
SHOWCASE_PREFERRED_START = 18

_SHOWCASE_PRESETS = (
    ("EV charging", 7.2, 3, 8, 24),
    ("Laundry", 0.8, 1, 8, 20),
    ("Dishwashing", 1.2, 2, 8, 23),
    ("Battery charging", 2.0, 3, 7, 22),
    ("Water heating", 3.0, 1, 5, 22),
)


def evening_surge_workloads() -> tuple[Workload, ...]:
    """Return 100 aggregate groups that all prefer the evening surge hour."""
    workloads = []
    for index in range(SHOWCASE_GROUP_COUNT):
        category, power, duration, earliest, latest = _SHOWCASE_PRESETS[
            index % len(_SHOWCASE_PRESETS)
        ]
        group_number = index // len(_SHOWCASE_PRESETS) + 1
        workloads.append(Workload(
            workload_id=f"showcase-{index + 1:03d}",
            user_id="synthetic-district-group",
            category=f"{category} group {group_number}",
            power_kw=power * SHOWCASE_APPLIANCES_PER_GROUP,
            duration_hours=duration,
            earliest_start=min(earliest, 8),
            latest_finish=latest,
            preferred_start=min(
                SHOWCASE_PREFERRED_START,
                latest - duration,
            ),
            priority=Priority.FLEXIBLE,
            flexibility=1.0,
        ))
    return tuple(workloads)
