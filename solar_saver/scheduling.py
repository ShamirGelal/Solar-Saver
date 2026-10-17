"""Deterministic greedy placement using hourly kW profiles.

Integration notes
-----------------
Capacity means total demand (background plus flexible load), including demand
served by solar. Coordinated policies reject a scenario whose fixed background
already exceeds capacity; scheduling flexible work cannot repair that input.
A valid workload with no feasible contiguous placement is returned in
unscheduled_workload_ids and contributes no flexible energy.

Critical workloads are considered before important and flexible workloads,
regardless of objective weights. Within each priority, tighter windows precede
larger loads, then workload IDs break ties. This is an explicit protection rule,
not a guarantee that every critical workload can finish under scarce capacity.

Balanced scores use these finite, nonnegative SchedulerWeights:
* grid_energy: incremental grid kWh coefficient (default 1).
* preference: absolute start deviation in hours, multiplied by priority
  (8/3/1 for critical/important/flexible) and (1 - 0.75 * flexibility)
  (default 0.5).
* peak: maximum total-demand/capacity ratio within the candidate's hours;
  feasible ratios are in [0, 1] (default 0.25).
* fairness: squared start deviation in hours (default 0.25), discouraging a
  large individual shift. This is per workload, not cumulative user fairness.
Zero disables a term. Start tuning with grid_energy=1, preference=0..2,
peak=0..5, fairness=0..1; these are experimental ranges, not validated policy
settings. Power scale and window length change their relative influence.
Solar-only ignores weights and uses preference solely to break equal-grid ties.

For N workloads, H slots, and maximum duration D, runtime is
O(N log N + N H D + H), at worst O(N log N + N H**2); memory is O(N + H).
Greedy choices are not revisited, so feasible global schedules may be missed.
There is no global optimality or cross-day fairness guarantee. Completion and
energy metrics must be read together: omitted work is not an energy saving.
"""

from __future__ import annotations

from math import isfinite

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
        self._validate_inputs(scenario, strategy, weights)
        flexible = [0.0] * scenario.horizon_hours
        assignments: list[Assignment] = []
        unscheduled: list[str] = []

        workloads = sorted(
            scenario.workloads,
            key=lambda load: (
                -_PRIORITY_WEIGHT[load.priority],
                (load.latest_finish - load.earliest_start) - load.duration_hours,
                -load.power_kw,
                load.workload_id,
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

    @staticmethod
    def _validate_inputs(
        scenario: CityScenario,
        strategy: Strategy,
        weights: SchedulerWeights,
    ) -> None:
        # Domain contracts remain shared; validate scheduler preconditions here.
        if not isinstance(strategy, Strategy):
            raise ValueError("strategy must be a Strategy member")
        for name in ("solar_supply_kw", "base_demand_kw", "grid_capacity_kw"):
            if any(not isfinite(value) or value < 0 for value in getattr(scenario, name)):
                raise ValueError(f"{name} must contain finite, nonnegative values")
        for name in ("grid_energy", "preference", "peak", "fairness"):
            value = getattr(weights, name)
            if not isfinite(value) or value < 0:
                raise ValueError(f"{name} weight must be finite and nonnegative")
        seen = set()
        for workload in scenario.workloads:
            if workload.workload_id in seen:
                raise ValueError("workload IDs must be unique")
            seen.add(workload.workload_id)
            if not isfinite(workload.power_kw) or workload.power_kw <= 0:
                raise ValueError("workload power must be finite and positive")
            times = (workload.earliest_start, workload.latest_finish,
                     workload.preferred_start, workload.duration_hours)
            if any(not isinstance(value, int) for value in times):
                raise ValueError("workload times must be integer hourly slots")
            if workload.latest_finish > scenario.horizon_hours:
                raise ValueError("workload window must fit inside the scenario horizon")
        if strategy is not Strategy.UNCOORDINATED and any(
            base > capacity
            for base, capacity in zip(scenario.base_demand_kw, scenario.grid_capacity_kw)
        ):
            raise ValueError("base demand exceeds capacity; coordinated schedule is infeasible")

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

        candidates: list[tuple[float, int, int]] = []
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
            candidates.append((score, deviation, start))

        return min(candidates)[2] if candidates else None
