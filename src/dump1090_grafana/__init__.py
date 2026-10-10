"""Grafana dashboards for the dump1090 / readsb ADS-B decoder ecosystem.

The JSON dashboards under ``dashboards/`` are the artefact; this package holds
the small validator that keeps them honest (``dump1090-grafana`` on the command
line, ``make validate`` locally, pytest in CI).
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
