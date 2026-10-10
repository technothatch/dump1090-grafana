"""Loading and validation rules for the dashboards shipped by this repository.

The checks here are the ones a reviewer would otherwise run by eye: every
dashboard parses, carries at least four panels, keeps its panel ids unique and
positive, points every Prometheus reference at the ``${DS_PROMETHEUS}``
datasource variable, queries only metric names dump1090-exporter really emits,
declares a supported unit plus thresholds on every panel, and hardcodes no
instance URL anywhere.

Nothing in here needs Grafana, Prometheus or PyYAML: standard library ``json``
plus a handful of regular expressions, so ``make validate`` works on a fresh
checkout.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, TypeGuard

from .schema import validate_document

#: Where the dashboards live, relative to the repository root.
DASHBOARD_DIR_NAME = "dashboards"

#: Schema document every dashboard is validated against, relative to the root.
SCHEMA_FILE = Path("schema") / "dashboard.schema.json"

#: Panel and target datasource uid; also the name of the template variable.
DATASOURCE_VARIABLE = "${DS_PROMETHEUS}"

#: Name of the datasource template variable every dashboard must declare.
TEMPLATE_VARIABLE_NAME = "DS_PROMETHEUS"

#: Minimum number of panels per dashboard (REPOS.md section 18).
MIN_PANELS = 4

#: Units a panel may declare. ``kn`` is reserved for ground-speed panels; no
#: dump1090-exporter metric carries a speed, so nothing uses it yet.
ALLOWED_UNITS: frozenset[str] = frozenset(
    {"ops", "dBFS", "ft", "kn", "percent", "short", "s", "none"}
)

#: Dashboard uids must be stable, readable and unique across the repository.
DASHBOARD_UID_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")

#: Metric names emitted by dump1090-exporter, verified against
#: dump1090-exporter/internal/exporter/exporter.go and its README.
EXPORTER_METRICS: frozenset[str] = frozenset(
    {
        "dump1090_up",
        "dump1090_receiver_refresh_seconds",
        "dump1090_receiver_info",
        "dump1090_messages_total",
        "dump1090_messages_per_second",
        "dump1090_aircraft",
        "dump1090_aircraft_with_position",
        "dump1090_signal_dbfs",
        "dump1090_blocks_dropped_total",
        "dump1090_cpu_milliseconds",
        "dump1090_cpr_local_ok",
        "dump1090_cpr_local_bad",
        "dump1090_cpr_local_skipped",
        "dump1090_cpr_global_ok",
        "dump1090_cpr_global_bad",
        "dump1090_cpr_global_skipped",
        "dump1090_tracks_all",
        "dump1090_tracks_single_message",
        "dump1090_scrape_duration_seconds",
        "dump1090_aircraft_altitude",
        "dump1090_aircraft_squawk",
    }
)

#: Label dimensions carried by each labelled collector.
METRIC_LABELS: dict[str, tuple[str, ...]] = {
    "dump1090_aircraft_squawk": ("squawk",),
    "dump1090_cpu_milliseconds": ("stage",),
    "dump1090_receiver_info": ("version",),
    "dump1090_signal_dbfs": ("quantile",),
}

#: Series a histogram collector expands to in Prometheus' text format.
_HISTOGRAM_SUFFIXES = ("_bucket", "_sum", "_count")

_METRIC_RE = re.compile(r"\bdump1090_[a-z0-9_]+\b")

# --- hardcoded-URL rule -------------------------------------------------------
#
# A dashboard must talk to Prometheus only through ${DS_PROMETHEUS}. The rule
# enforced by url_violations() is therefore:
#
#   1. a string containing an IPv4 literal, `localhost`, `[::1]` or a bare
#      `host:port` pair is always a violation; and
#   2. a string containing `http://` or `https://` is a violation unless it
#      lives under a key named `url`, `links` or `href` AND the URL starts with
#      `/`, `${`, `#` or one of the documentation hosts below.
#
_SCHEME_RE = re.compile(r"https?://", re.IGNORECASE)
_IPV4_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_HOSTPORT_RE = re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*:\d{2,5}\b", re.IGNORECASE)
_LOCAL_RE = re.compile(r"localhost|\[?::1\]?", re.IGNORECASE)

#: Keys whose values may legitimately contain a URL (dashboard links, data
#: links, text-panel hrefs).
ALLOWED_URL_KEYS: frozenset[str] = frozenset({"url", "links", "href"})

#: URL prefixes that are always allowed: Grafana-internal links plus the few
#: documentation hosts a panel description may cite.
ALLOWED_URL_PREFIXES: tuple[str, ...] = (
    "/",
    "${",
    "#",
    "https://grafana.com/",
    "https://grafana.org/",
    "https://prometheus.io/",
    "https://github.com/technothatch/",
)


class DashboardError(Exception):
    """Raised when a dashboard file cannot be read or parsed."""


def dashboard_paths(root: Path) -> list[Path]:
    """Return every dashboard JSON file under *root*, sorted by name."""
    return sorted((root / DASHBOARD_DIR_NAME).glob("*.json"))


def read_document(path: Path) -> dict[str, Any]:
    """Load *path* as a JSON object or raise :class:`DashboardError`."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DashboardError(f"{path}: cannot read file: {exc}") from exc
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DashboardError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise DashboardError(f"{path}: top level is not a JSON object")
    return document


def panels(document: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield every panel, descending into nested rows if there are any."""
    yield from _walk_panels(document.get("panels"))


def _walk_panels(nodes: object) -> Iterator[dict[str, Any]]:
    if not isinstance(nodes, list):
        return
    for node in nodes:
        if isinstance(node, dict):
            yield node
            yield from _walk_panels(node.get("panels"))


def targets(panel: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield every query target of *panel*."""
    raw = panel.get("targets")
    if not isinstance(raw, list):
        return
    for node in raw:
        if isinstance(node, dict):
            yield node


def datasource_uid(node: Mapping[str, Any]) -> str | None:
    """Return the datasource uid referenced by a panel, target or annotation."""
    datasource = node.get("datasource")
    if isinstance(datasource, dict):
        uid = datasource.get("uid")
        if isinstance(uid, str):
            return uid
    return None


def metrics_in(expr: str) -> set[str]:
    """Return the dump1090 series referenced by a PromQL expression."""
    return set(_METRIC_RE.findall(expr))


def is_known_metric(name: str) -> bool:
    """Return True when *name* is a series dump1090-exporter can expose."""
    if name in EXPORTER_METRICS:
        return True
    for suffix in _HISTOGRAM_SUFFIXES:
        if name.endswith(suffix) and name.removesuffix(suffix) in EXPORTER_METRICS:
            return True
    return False


def units(document: Mapping[str, Any]) -> set[str]:
    """Return every ``fieldConfig.defaults.unit`` used by *document*."""
    found: set[str] = set()
    for panel in panels(document):
        defaults = _defaults(panel)
        if defaults is None:
            continue
        unit = defaults.get("unit")
        if isinstance(unit, str):
            found.add(unit)
    return found


def has_datasource_variable(document: Mapping[str, Any]) -> bool:
    """Return True when the dashboard declares the DS_PROMETHEUS variable."""
    templating = document.get("templating")
    if not isinstance(templating, dict):
        return False
    variables = templating.get("list")
    if not isinstance(variables, list):
        return False
    for variable in variables:
        if not isinstance(variable, dict):
            continue
        if variable.get("name") == TEMPLATE_VARIABLE_NAME and variable.get("type") == "datasource":
            return True
    return False


def url_violations(node: object, path: str = "$", key: str | None = None) -> list[str]:
    """Apply the hardcoded-URL rule to a decoded JSON document."""
    if isinstance(node, str):
        return _string_violations(node, path, key)
    problems: list[str] = []
    if isinstance(node, dict):
        for name, value in node.items():
            problems.extend(url_violations(value, f"{path}.{name}", str(name)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            problems.extend(url_violations(value, f"{path}[{index}]", key))
    return problems


def _string_violations(value: str, path: str, key: str | None) -> list[str]:
    if _IPV4_RE.search(value) or _LOCAL_RE.search(value) or _HOSTPORT_RE.search(value):
        return [f"{path}: hardcoded host in {value!r}"]
    match = _SCHEME_RE.search(value)
    if match is None:
        return []
    url = value[match.start() :]
    if key in ALLOWED_URL_KEYS and url.startswith(ALLOWED_URL_PREFIXES):
        return []
    return [f"{path}: hardcoded instance URL {value!r}"]


def validate_repo(root: Path) -> list[str]:
    """Run every dashboard rule under *root* and return the problems found."""
    try:
        schema = read_document(root / SCHEMA_FILE)
    except DashboardError as exc:
        return [str(exc)]

    paths = dashboard_paths(root)
    if not paths:
        return [f"no dashboard JSON files found in {root / DASHBOARD_DIR_NAME}"]

    problems: list[str] = []
    uids: dict[str, str] = {}
    for path in paths:
        try:
            document = read_document(path)
        except DashboardError as exc:
            problems.append(str(exc))
            continue
        problems.extend(check_dashboard(path.name, document, schema))
        uid = document.get("uid")
        if isinstance(uid, str):
            if uid in uids:
                problems.append(f"{path.name}: dashboard uid {uid!r} is also used by {uids[uid]}")
            else:
                uids[uid] = path.name
    return problems


def check_dashboard(name: str, document: Mapping[str, Any], schema: Mapping[str, Any]) -> list[str]:
    """Check one dashboard document against the schema and the house rules."""
    problems = [f"{name}: {problem}" for problem in validate_document(document, schema)]

    uid = document.get("uid")
    if not isinstance(uid, str) or not uid:
        problems.append(f"{name}: missing or empty dashboard uid")
    elif not DASHBOARD_UID_RE.fullmatch(uid):
        problems.append(f"{name}: dashboard uid {uid!r} is not kebab-case")

    if not has_datasource_variable(document):
        problems.append(f"{name}: no {TEMPLATE_VARIABLE_NAME} datasource template variable")

    found = list(panels(document))
    if len(found) < MIN_PANELS:
        problems.append(f"{name}: expected at least {MIN_PANELS} panels, found {len(found)}")

    seen_ids: dict[int, str] = {}
    for panel in found:
        problems.extend(_check_panel(name, panel, seen_ids))

    problems.extend(f"{name}: {problem}" for problem in url_violations(document))
    return problems


def _check_panel(name: str, panel: dict[str, Any], seen_ids: dict[int, str]) -> list[str]:
    problems: list[str] = []
    title = panel.get("title")
    label = title if isinstance(title, str) and title else "<untitled>"

    panel_id = panel.get("id")
    if not _is_positive_int(panel_id):
        problems.append(f"{name}: panel {label!r} has an invalid id {panel_id!r}")
    elif panel_id in seen_ids:
        problems.append(
            f"{name}: panel id {panel_id} used twice ({seen_ids[panel_id]!r} and {label!r})"
        )
    else:
        seen_ids[panel_id] = label

    if datasource_uid(panel) != DATASOURCE_VARIABLE:
        problems.append(
            f"{name}: panel {label!r} datasource is {datasource_uid(panel)!r}, "
            f"expected {DATASOURCE_VARIABLE!r}"
        )

    problems.extend(_check_field_config(name, label, panel))

    queries = list(targets(panel))
    if not queries:
        problems.append(f"{name}: panel {label!r} has no targets")
    for query in queries:
        problems.extend(_check_target(name, label, query))

    return problems


def _check_target(name: str, label: str, query: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []

    if datasource_uid(query) != DATASOURCE_VARIABLE:
        problems.append(
            f"{name}: panel {label!r} target datasource is {datasource_uid(query)!r}, "
            f"expected {DATASOURCE_VARIABLE!r}"
        )

    expr = query.get("expr")
    if not isinstance(expr, str) or not expr.strip():
        problems.append(f"{name}: panel {label!r} has a target without an expr")
        return problems

    found = metrics_in(expr)
    if not found:
        problems.append(f"{name}: panel {label!r} expr {expr!r} queries no dump1090_* series")
        return problems
    unknown = sorted(metric for metric in found if not is_known_metric(metric))
    if unknown:
        problems.append(f"{name}: panel {label!r} queries unknown metric(s): {', '.join(unknown)}")
    return problems


def _check_field_config(name: str, label: str, panel: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    defaults = _defaults(panel)
    if defaults is None:
        return [f"{name}: panel {label!r} has no fieldConfig.defaults"]

    unit = defaults.get("unit")
    if not isinstance(unit, str) or not unit:
        problems.append(f"{name}: panel {label!r} has no fieldConfig.defaults.unit")
    elif unit not in ALLOWED_UNITS:
        problems.append(
            f"{name}: panel {label!r} unit {unit!r} is not in the allowed set "
            f"{sorted(ALLOWED_UNITS)}"
        )

    steps = _threshold_steps(panel)
    if not steps:
        problems.append(f"{name}: panel {label!r} has no threshold steps")
    return problems


def _defaults(panel: Mapping[str, Any]) -> dict[str, Any] | None:
    field_config = panel.get("fieldConfig")
    if isinstance(field_config, dict):
        defaults = field_config.get("defaults")
        if isinstance(defaults, dict):
            return defaults
    return None


def _threshold_steps(panel: Mapping[str, Any]) -> list[object]:
    field_config = panel.get("fieldConfig")
    if not isinstance(field_config, dict):
        return []
    defaults = field_config.get("defaults")
    if not isinstance(defaults, dict):
        return []
    thresholds = defaults.get("thresholds")
    if not isinstance(thresholds, dict):
        return []
    steps = thresholds.get("steps")
    if not isinstance(steps, list):
        return []
    return steps


def _is_positive_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1
