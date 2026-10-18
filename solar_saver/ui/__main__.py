"""Local load planner. Run with python -m solar_saver.ui."""

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
    Workload,
)
from solar_saver.pipeline import run_comparison
from solar_saver.scheduling import GreedyLoadScheduler
from .inputs import EnteredLoadDemandGenerator, parse_workloads


DEMO_DATE = date(2026, 10, 18)
DEMO_POPULATION = 1_000
DEMO_PEOPLE_PER_HOUSEHOLD = 2.5
DEMO_HOUSEHOLDS = int(DEMO_POPULATION / DEMO_PEOPLE_PER_HOUSEHOLD)
DEMO_SOLAR_CAPACITY_KW = 2_000.0
DEMO_GRID_CAPACITY_KW = 2_000.0
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


def serialize_report(report: SimulationReport, *, mode: str = "demo") -> dict:
    """Adapt domain objects for this UI, without changing shared contracts."""
    return {
        "mode": mode,
        "supports_custom_loads": True,
        "target_date": DEMO_DATE.isoformat(),
        "model_name": report.solar_profile.model_name,
        "forecast_metadata": dict(report.solar_profile.metadata),
        "workload_count": len(report.scenario.workloads),
        "critical_workload_count": sum(
            load.priority is Priority.CRITICAL for load in report.scenario.workloads
        ),
        "population_count": DEMO_POPULATION,
        "household_count": DEMO_HOUSEHOLDS,
        "seed": 42,
        "installed_capacity_kw": DEMO_SOLAR_CAPACITY_KW,
        "requested_flexible_energy_kwh": sum(
            load.power_kw * load.duration_hours for load in report.scenario.workloads
        ),
        "solar_supply_kw": report.scenario.solar_supply_kw,
        "base_demand_kw": report.scenario.base_demand_kw,
        "grid_capacity_kw": report.scenario.grid_capacity_kw,
        "workloads": [asdict(load) for load in report.scenario.workloads],
        "strategies": {
            strategy.value: {
                "metrics": asdict(item.metrics),
                "completed_count": len(item.result.assignments),
                "unscheduled_count": len(item.result.unscheduled_workload_ids),
                "total_demand_kw": item.result.total_demand_kw,
                "grid_draw_kw": item.result.grid_draw_kw,
                "solar_used_kw": item.result.solar_used_kw,
                "served_energy_kwh": sum(item.result.total_demand_kw),
                "assignments": [asdict(assignment) for assignment in item.result.assignments],
                "unscheduled_workload_ids": item.result.unscheduled_workload_ids,
            }
            for strategy, item in report.strategies.items()
        },
    }


def build_comparison(workloads: tuple[Workload, ...] | None = None, *, forecaster=None) -> dict:
    if forecaster is None:
        # Keep the input editor/server importable before optional ML packages
        # are installed. The forecasting package currently imports its model.
        from solar_saver.runtime import RuntimeForecaster
        forecaster = RuntimeForecaster()
    report = run_comparison(
        forecast_request=ForecastRequest(
            latitude=38.0293, longitude=-78.4767, target_date=DEMO_DATE,
            installed_capacity_kw=DEMO_SOLAR_CAPACITY_KW,
        ),
        simulation_config=SimulationConfig(
            number_of_users=DEMO_HOUSEHOLDS,
            random_seed=42,
            grid_capacity_kw=DEMO_GRID_CAPACITY_KW,
        ),
        scheduler_weights=SchedulerWeights(),
        forecaster=forecaster,
        demand_generator=(SyntheticDemandGenerator() if workloads is None
                          else EnteredLoadDemandGenerator(workloads)),
        scheduler=GreedyLoadScheduler(),
    )
    return serialize_report(report, mode="demo" if workloads is None else "custom")


class DemoHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/api/comparison":
            self._json(HTTPStatus.NOT_FOUND, {"error": "Page not found."})
            return
        if self.headers.get_content_type() != "application/json":
            self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "Use application/json."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length > 65_536:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "The load list is too large."})
            return
        if length <= 0:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "Provide a JSON request body."})
            return
        try:
            payload = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "The request body must be valid JSON."})
            return
        try:
            workloads = parse_workloads(payload)
            self._json(HTTPStatus.OK, build_comparison(workloads))
        except ModuleNotFoundError:
            self._dependency_error()
        except ValueError as error:
            self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {
                "error": "Check your loads before comparing.", "detail": str(error),
            })
        except Exception:
            self.log_error("Unexpected failure while comparing entered loads")
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {
                "error": "The comparison is unavailable. Try again or check the local server.",
            })

    def _dependency_error(self) -> None:
        self._json(HTTPStatus.SERVICE_UNAVAILABLE, {
            "error": "The local app needs its Python dependencies. Install requirements.txt in the app's environment, then restart it.",
        })

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
        if path in ("/api/comparison", "/comparison.json"):
            try:
                payload = build_comparison()
                self._json(HTTPStatus.OK, payload)
            except ModuleNotFoundError:
                self._dependency_error()
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
