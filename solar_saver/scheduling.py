"""Reference greedy scheduler implementing the shared scheduling contract."""

from __future__ import annotations

from .domain import (
    Assignment,
    CityScenario,
    Priority,
    ScheduleResult,
    SchedulerWeights,
    Strategy,
    Workload,
)


_PRIORITY_WEIGHT = {
    Priority.CRITICAL: 8.0,
    Priority.IMPORTANT: 3.0,
    Priority.FLEXIBLE: 1.0,
}


class GreedyLoadScheduler:
    def schedule(
        self,
        scenario: CityScenario,
        strategy: Strategy,
        weights: SchedulerWeights,
    ) -> ScheduleResult:
        flexible = [0.0] * scenario.horizon_hours
        assignments: list[Assignment] = []
        unscheduled: list[str] = []

        workloads = sorted(
            scenario.workloads,
            key=lambda load: (
                -_PRIORITY_WEIGHT[load.priority],
                (load.latest_finish - load.earliest_start) - load.duration_hours,
                -load.power_kw,
            ),
        )

        for workload in workloads:
            start = self._choose_start(workload, scenario, flexible, strategy, weights)
            if start is None:
                unscheduled.append(workload.workload_id)
                continue
            for hour in range(start, start + workload.duration_hours):
                flexible[hour] += workload.power_kw
            assignments.append(
                Assignment(workload.workload_id, start, start + workload.duration_hours)
            )

        total = [base + extra for base, extra in zip(scenario.base_demand_kw, flexible)]
        solar_used = [min(demand, solar) for demand, solar in zip(total, scenario.solar_supply_kw)]
        grid_draw = [max(0.0, demand - solar) for demand, solar in zip(total, scenario.solar_supply_kw)]
        return ScheduleResult(
            strategy=strategy,
            assignments=tuple(assignments),
            unscheduled_workload_ids=tuple(unscheduled),
            flexible_demand_kw=tuple(flexible),
            total_demand_kw=tuple(total),
            solar_used_kw=tuple(solar_used),
            grid_draw_kw=tuple(grid_draw),
        )

    def _choose_start(
        self,
        workload: Workload,
        scenario: CityScenario,
        flexible: list[float],
        strategy: Strategy,
        weights: SchedulerWeights,
    ) -> int | None:
        valid_starts = range(
            workload.earliest_start,
            workload.latest_finish - workload.duration_hours + 1,
        )
        if strategy is Strategy.UNCOORDINATED:
            return min(valid_starts, key=lambda value: abs(value - workload.preferred_start))

        candidates: list[tuple[float, int]] = []
        for start in valid_starts:
            hours = range(start, start + workload.duration_hours)
            if any(
                scenario.base_demand_kw[hour] + flexible[hour] + workload.power_kw
                > scenario.grid_capacity_kw[hour]
                for hour in hours
            ):
                continue

            incremental_grid = sum(
                max(
                    0.0,
                    scenario.base_demand_kw[hour]
                    + flexible[hour]
                    + workload.power_kw
                    - scenario.solar_supply_kw[hour],
                )
                - max(
                    0.0,
                    scenario.base_demand_kw[hour]
                    + flexible[hour]
                    - scenario.solar_supply_kw[hour],
                )
                for hour in hours
            )
            deviation = abs(start - workload.preferred_start)
            peak_ratio = max(
                (
                    scenario.base_demand_kw[hour]
                    + flexible[hour]
                    + workload.power_kw
                )
                / scenario.grid_capacity_kw[hour]
                for hour in hours
            )

            if strategy is Strategy.SOLAR_ONLY:
                score = incremental_grid
            else:
                score = (
                    weights.grid_energy * incremental_grid
                    + weights.preference
                    * deviation
                    * _PRIORITY_WEIGHT[workload.priority]
                    * (1.0 - 0.75 * workload.flexibility)
                    + weights.peak * peak_ratio
                    + weights.fairness * deviation * deviation
                )
            candidates.append((score, start))

        return min(candidates)[1] if candidates else None
