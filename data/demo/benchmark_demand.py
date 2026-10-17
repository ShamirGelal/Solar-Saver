"""Run fixed demand fixtures against the existing scheduler, offline.

From the repository root:
    python data/demo/benchmark_demand.py --output outputs/demand-benchmark.json

This is a demand-owned demo/test helper, not a subsystem API. It deliberately
does not optimize fixture choices or scheduler weights to favor any strategy.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, replace
from datetime import date
import json
import math
from pathlib import Path
import platform
import statistics
import sys
import timeit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from solar_saver.demand import SyntheticDemandGenerator
from solar_saver.domain import ForecastRequest, SchedulerWeights, SimulationConfig, Strategy
from solar_saver.forecasting import SeasonalDemoForecaster
from solar_saver.metrics import evaluate_schedule
from solar_saver.scheduling import GreedyLoadScheduler


def fixture_scenario(scenario, window_mode):
    """Make explicit what-if task windows without changing production APIs."""
    if window_mode == "generated":
        return scenario
    if window_mode == "evening":
        # A separate hypothetical population: every task is available 18:00-24:00.
        tasks = tuple(replace(task, earliest_start=18, latest_finish=24,
                              preferred_start=19) for task in scenario.workloads)
    elif window_mode == "fixed":
        tasks = tuple(replace(task, earliest_start=task.preferred_start,
                              latest_finish=task.preferred_start + task.duration_hours,
                              flexibility=0.0) for task in scenario.workloads)
    else:
        raise ValueError(f"Unknown fixture window_mode: {window_mode}")
    return replace(scenario, workloads=tasks)


def run_benchmark():
    recipe = json.loads(Path(__file__).with_name("demand_cases.json").read_text())
    generator = SyntheticDemandGenerator()
    forecaster = SeasonalDemoForecaster()
    scheduler = GreedyLoadScheduler()
    rows = []
    for count in recipe["household_counts"]:
        solar = forecaster.predict(ForecastRequest(
            38.0293, -78.4767, date(2026, 10, 18),
            recipe["installed_solar_kw_per_household"] * count,
        ))
        for seed in recipe["seeds"]:
            config = SimulationConfig(count, seed, 5.0 * count)
            timing = recipe["generation_timing"]
            samples = [seconds * 1000 / timing["calls_per_repeat"] for seconds in
                       timeit.repeat(lambda: generator.generate(solar, config),
                                     repeat=timing["repeats"],
                                     number=timing["calls_per_repeat"])]
            for case in recipe["cases"]:
                case_config = replace(config, grid_capacity_kw=case["capacity_kw_per_household"] * count)
                raw = generator.generate(solar, case_config)
                scenario = fixture_scenario(raw, case["window_mode"])
                row = {
                    "households": count, "seed": seed, "case": case["name"],
                    "generation_ms": {"median": statistics.median(samples),
                                      "min": min(samples), "max": max(samples)},
                    "timing_scope": "generator only, normal capacity; repeated for case rows",
                    "deterministic": raw == generator.generate(solar, case_config),
                    "profiles_valid": all(len(values) == 24 and all(
                        math.isfinite(value) and value >= 0 for value in values)
                        for values in (scenario.solar_supply_kw, scenario.base_demand_kw,
                                       scenario.grid_capacity_kw)),
                    "task_count": len(scenario.workloads),
                    "categories": dict(Counter(task.category for task in scenario.workloads)),
                    "requested_flexible_kwh": math.fsum(
                        task.power_kw * task.duration_hours for task in scenario.workloads),
                    "background_kwh": math.fsum(scenario.base_demand_kw),
                    "background_peak_kw": max(scenario.base_demand_kw),
                    "strategies": {},
                }
                for strategy in Strategy:
                    result = scheduler.schedule(scenario, strategy, SchedulerWeights())
                    row["strategies"][strategy.value] = {
                        "completed_tasks": len(result.assignments),
                        "unfinished_tasks": len(result.unscheduled_workload_ids),
                        "served_flexible_kwh": math.fsum(result.flexible_demand_kw),
                        "metrics": asdict(evaluate_schedule(scenario, result)),
                    }
                rows.append(row)
    return {"python": platform.python_version(), "platform": platform.platform(),
            "recipe": recipe, "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_benchmark()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Recorded {len(result['rows'])} cases in {args.output}")
