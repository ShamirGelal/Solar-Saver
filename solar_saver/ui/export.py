"""Build a self-contained static demo with results from the shared pipeline.

Run: python -m solar_saver.ui.export --output-dir outputs/pages
Generated JSON is a UI deployment asset, not a shared subsystem API.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from shutil import copyfile

from .__main__ import build_comparison


def export_site(destination: Path) -> None:
    # Fail the build on backend errors, before publishing any incomplete page.
    payload = build_comparison()
    payload["supports_custom_loads"] = False
    comparison = json.dumps(payload, allow_nan=False, indent=2) + "\n"
    destination.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).parent
    for filename in ("index.html", "app.css", "app.js"):
        copyfile(source / filename, destination / filename)
    (destination / "comparison.json").write_text(comparison, encoding="utf-8")
    (destination / ".nojekyll").write_text("", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Solar Saver static demo")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/pages"))
    args = parser.parse_args()
    export_site(args.output_dir)
    print(f"Static demo built in {args.output_dir}")


if __name__ == "__main__":
    main()
