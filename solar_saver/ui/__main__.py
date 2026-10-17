"""Run with python -m solar_saver.ui. No third-party dependencies required."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit

from solar_saver.demand import SyntheticDemandGenerator
from solar_saver.domain import (
    ForecastRequest, Priority, SchedulerWeights, SimulationConfig, SimulationReport,
)
from solar_saver.forecasting import SeasonalDemoForecaster
from solar_saver.pipeline import run_comparison
from solar_saver.scheduling import GreedyLoadScheduler


DEMO_DATE = date(2026, 10, 18)
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


def serialize_report(report: SimulationReport) -> dict:
    """Adapt domain objects for this UI, without changing shared contracts."""
    return {
        "target_date": DEMO_DATE.isoformat(),
        "model_name": report.solar_profile.model_name,
        "workload_count": len(report.scenario.workloads),
        "critical_workload_count": sum(
            load.priority is Priority.CRITICAL for load in report.scenario.workloads
        ),
        "seed": 42,
        "installed_capacity_kw": 300.0,
        "requested_flexible_energy_kwh": sum(
            load.power_kw * load.duration_hours for load in report.scenario.workloads
        ),
        "solar_supply_kw": report.scenario.solar_supply_kw,
        "base_demand_kw": report.scenario.base_demand_kw,
        "grid_capacity_kw": report.scenario.grid_capacity_kw,
        "strategies": {
            strategy.value: {
                "metrics": asdict(item.metrics),
                "completed_count": len(item.result.assignments),
                "unscheduled_count": len(item.result.unscheduled_workload_ids),
                "total_demand_kw": item.result.total_demand_kw,
                "grid_draw_kw": item.result.grid_draw_kw,
                "solar_used_kw": item.result.solar_used_kw,
                "served_energy_kwh": sum(item.result.total_demand_kw),
            }
            for strategy, item in report.strategies.items()
        },
    }


def build_comparison() -> dict:
    report = run_comparison(
        forecast_request=ForecastRequest(
            latitude=38.0293, longitude=-78.4767, target_date=DEMO_DATE,
            installed_capacity_kw=300.0,
        ),
        simulation_config=SimulationConfig(number_of_users=100, random_seed=42),
        scheduler_weights=SchedulerWeights(),
        forecaster=SeasonalDemoForecaster(),
        demand_generator=SyntheticDemandGenerator(),
        scheduler=GreedyLoadScheduler(),
    )
    return serialize_report(report)


class DemoHandler(BaseHTTPRequestHandler):
    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, "application/json; charset=utf-8",
                   json.dumps(payload, allow_nan=False).encode("utf-8"))

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/comparison":
            try:
                payload = build_comparison()
                self._json(HTTPStatus.OK, payload)
            except ValueError as error:
                self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {
                    "error": "The comparison could not be completed.",
                    "detail": str(error),
                })
            except Exception:
                self.log_error("Unexpected failure while building the comparison")
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {
                    "error": "The comparison is unavailable. Try again or check the local server.",
                })
            return
        if path in STATIC_FILES:
            filename, content_type = STATIC_FILES[path]
            body = Path(__file__).with_name(filename).read_bytes()
            self._send(HTTPStatus.OK, content_type, body)
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "Page not found."})


def main() -> None:
    parser = argparse.ArgumentParser(description="Solar Saver local demo UI")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), DemoHandler)
    except OSError as error:
        parser.exit(1, f"Could not start the demo: {error}\nTry --port with another port.\n")
    print(f"Solar Saver demo: http://127.0.0.1:{args.port} (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
