"""Strategy-independent evaluation of valid scheduler results.

One-hour power slots sum to kWh. Renewable matching uses total served demand
(background plus completed workloads) as its denominator. Preference deviations
cover completed workloads only; completion metrics expose omitted work. Empty
workload sets count as 100% complete, and zero demand has 0% renewable matching.
Lower energy use with lower completion must not be reported as energy savings.
"""

from __future__ import annotations

from .domain import CityScenario, Priority, ScheduleMetrics, ScheduleResult


def evaluate_schedule(
    scenario: CityScenario,
    result: ScheduleResult,
) -> ScheduleMetrics:
    workloads = {workload.workload_id: workload for workload in scenario.workloads}
    deviations = [
        abs(assignment.scheduled_start - workloads[assignment.workload_id].preferred_start)
        for assignment in result.assignments
    ]
    critical_ids = {
        workload.workload_id
        for workload in scenario.workloads
        if workload.priority is Priority.CRITICAL
    }
    scheduled_ids = {assignment.workload_id for assignment in result.assignments}
    total_energy = sum(result.total_demand_kw)
    solar_used = sum(result.solar_used_kw)

    return ScheduleMetrics(
        grid_energy_kwh=sum(result.grid_draw_kw),
        solar_used_kwh=solar_used,
        unused_solar_kwh=sum(
            max(0.0, supply - used)
            for supply, used in zip(scenario.solar_supply_kw, result.solar_used_kw)
        ),
        renewable_match_percent=(100 * solar_used / total_energy) if total_energy else 0.0,
        peak_demand_kw=max(result.total_demand_kw, default=0.0),
        average_preference_deviation_hours=(sum(deviations) / len(deviations)) if deviations else 0.0,
        maximum_preference_deviation_hours=max(deviations, default=0),
        completion_percent=(100 * len(scheduled_ids) / len(workloads)) if workloads else 100.0,
        critical_completion_percent=(
            100 * len(critical_ids & scheduled_ids) / len(critical_ids)
            if critical_ids
            else 100.0
        ),
        capacity_violation_hours=sum(
            demand > capacity
            for demand, capacity in zip(result.total_demand_kw, scenario.grid_capacity_kw)
        ),
    )
