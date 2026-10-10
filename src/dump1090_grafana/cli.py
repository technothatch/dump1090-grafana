"""Command line interface: validate the dashboards in a checkout.

``dump1090-grafana --root .`` is what ``make validate`` runs; it exits 1 and
prints every problem when a dashboard drifted away from
``schema/dashboard.schema.json`` or from one of the house rules in
:mod:`dump1090_grafana.dashboards`.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .dashboards import SCHEMA_FILE, dashboard_paths, read_document, validate_repo

#: Repository root when this file lives at ``<root>/src/dump1090_grafana/cli.py``.
DEFAULT_ROOT = Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser for the ``dump1090-grafana`` command."""
    parser = argparse.ArgumentParser(
        prog="dump1090-grafana",
        description=(
            "Validate every dashboard in dashboards/ against "
            "schema/dashboard.schema.json and the dump1090-grafana house rules."
        ),
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        metavar="PATH",
        help="repository root to validate (default: this checkout)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Validate the dashboards below ``--root`` and return a shell exit code."""
    args = build_parser().parse_args(argv)
    root: Path = args.root
    problems = validate_repo(root)
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        print(f"{len(problems)} problem(s) found in {root}", file=sys.stderr)
        return 1
    count = len(dashboard_paths(root))
    print(
        f"OK: {count} dashboard(s), {_panel_count(root)} panel(s) validated "
        f"against {root / SCHEMA_FILE}"
    )
    return 0


def _panel_count(root: Path) -> int:
    total = 0
    for path in dashboard_paths(root):
        document = read_document(path)
        panel_list = document.get("panels")
        if isinstance(panel_list, list):
            total += len(panel_list)
    return total
