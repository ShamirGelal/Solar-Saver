"""Deterministic demo implementation of the SolarForecaster contract.

Replace this with the trained gradient-boosting implementation without changing
callers. Keeping a working baseline lets the simulator and scheduler teams work
before a trained artifact exists.
"""

from __future__ import annotations

import math

from ..domain import ForecastRequest, SolarProfile


class SeasonalDemoForecaster:
    def predict(self, request: ForecastRequest) -> SolarProfile:
        daylight_hours = 12 + 3.2 * math.sin(
            2 * math.pi * (request.target_date.timetuple().tm_yday - 80) / 365
        )
        sunrise = 12 - daylight_hours / 2
        sunset = 12 + daylight_hours / 2
        values: list[float] = []

        for hour in range(request.horizon_hours):
            if sunrise <= hour <= sunset:
                phase = math.pi * (hour - sunrise) / daylight_hours
                normalized_output = max(0.0, math.sin(phase))
                values.append(round(request.installed_capacity_kw * 0.82 * normalized_output, 3))
            else:
                values.append(0.0)

        return SolarProfile(
            supply_kw=tuple(values),
            model_name="seasonal-demo-baseline",
            metadata={"warning": "Synthetic baseline; replace with trained model."},
        )
