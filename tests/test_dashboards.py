"""Repository-level checks for the four shipped Grafana dashboards."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from dump1090_grafana.dashboards import (
    ALLOWED_UNITS,
    DATASOURCE_VARIABLE,
    EXPORTER_METRICS,
    METRIC_LABELS,
    MIN_PANELS,
    check_dashboard,
    dashboard_paths,
    datasource_uid,
    has_datasource_variable,
    is_known_metric,
    metrics_in,
    panels,
    read_document,
    targets,
    units,
    url_violations,
    validate_repo,
)
from dump1090_grafana.schema import validate_document

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = read_document(ROOT / "schema" / "dashboard.schema.json")

#: Exactly the dashboards REPOS.md section 18 asks for.
DASHBOARDS = ("overview.json", "coverage.json", "receiver-health.json", "traffic.json")


def load(name: str) -> dict[str, Any]:
    return read_document(ROOT / "dashboards" / name)


@pytest.mark.parametrize("name", DASHBOARDS)
def test_dashboard_parses(name: str) -> None:
    document = load(name)
    assert isinstance(document, dict)
    assert document["schemaVersion"] >= 38


def test_all_expected_dashboard_files_exist() -> None:
    assert [path.name for path in dashboard_paths(ROOT)] == sorted(DASHBOARDS)


@pytest.mark.parametrize("name", DASHBOARDS)
def test_every_dashboard_has_at_least_four_panels(name: str) -> None:
    assert len(list(panels(load(name)))) >= MIN_PANELS


@pytest.mark.parametrize("name", DASHBOARDS)
def test_every_panel_and_target_uses_the_prometheus_variable(name: str) -> None:
    for panel in panels(load(name)):
        assert datasource_uid(panel) == DATASOURCE_VARIABLE
        panel_targets = list(targets(panel))
        assert panel_targets, panel["title"]
        for query in panel_targets:
            assert datasource_uid(query) == DATASOURCE_VARIABLE


@pytest.mark.parametrize("name", DASHBOARDS)
def test_datasource_template_variable_is_declared(name: str) -> None:
    document = load(name)
    assert has_datasource_variable(document)
    assert document["templating"]["list"][0]["query"] == "prometheus"


@pytest.mark.parametrize("name", DASHBOARDS)
def test_import_input_matches_the_datasource_variable(name: str) -> None:
    inputs = load(name)["__inputs"]
    assert inputs[0]["name"] == "DS_PROMETHEUS"
    assert inputs[0]["type"] == "datasource"
    assert inputs[0]["pluginId"] == "prometheus"


def test_dashboard_uids_are_unique() -> None:
    uids = [load(name)["uid"] for name in DASHBOARDS]
    assert len(set(uids)) == len(DASHBOARDS)


@pytest.mark.parametrize("name", DASHBOARDS)
def test_uid_is_stable_and_derived_from_the_filename(name: str) -> None:
    assert load(name)["uid"] == f"dump1090-grafana-{Path(name).stem}"


def test_titles_are_unique_and_descriptive() -> None:
    titles = [load(name)["title"] for name in DASHBOARDS]
    assert len(set(titles)) == len(titles)
    assert all("dump1090" in load(name)["description"] for name in DASHBOARDS)


@pytest.mark.parametrize("name", DASHBOARDS)
def test_panel_ids_are_unique_and_positive(name: str) -> None:
    ids = [panel["id"] for panel in panels(load(name))]
    assert len(set(ids)) == len(ids)
    assert all(isinstance(panel_id, int) and panel_id > 0 for panel_id in ids)


@pytest.mark.parametrize("name", DASHBOARDS)
def test_schema_validation_passes(name: str) -> None:
    assert validate_document(load(name), SCHEMA) == []


@pytest.mark.parametrize("name", DASHBOARDS)
def test_panels_declare_supported_units_and_thresholds(name: str) -> None:
    document = load(name)
    assert units(document) <= ALLOWED_UNITS
    for panel in panels(document):
        defaults = panel["fieldConfig"]["defaults"]
        assert defaults["unit"] in ALLOWED_UNITS
        assert defaults["thresholds"]["mode"] in {"absolute", "absolute-from"}
        assert len(defaults["thresholds"]["steps"]) >= 1


def test_required_units_are_actually_used() -> None:
    used: set[str] = set()
    for name in DASHBOARDS:
        used |= units(load(name))
    assert {"ops", "dBFS", "ft", "percent"} <= used
    assert "kn" in ALLOWED_UNITS


@pytest.mark.parametrize("name", DASHBOARDS)
def test_queries_only_reference_known_exporter_metrics(name: str) -> None:
    for panel in panels(load(name)):
        for query in targets(panel):
            found = metrics_in(query["expr"])
            assert found, query["expr"]
            assert {metric for metric in found if not is_known_metric(metric)} == set()


@pytest.mark.parametrize("name", DASHBOARDS)
def test_no_hardcoded_instance_urls(name: str) -> None:
    assert url_violations(load(name)) == []


@pytest.mark.parametrize("name", DASHBOARDS)
def test_grid_positions_fit_the_24_column_grid(name: str) -> None:
    for panel in panels(load(name)):
        grid = panel["gridPos"]
        assert grid["x"] + grid["w"] <= 24
        assert grid["w"] >= 1 and grid["h"] >= 1


def test_validate_repo_is_clean() -> None:
    assert validate_repo(ROOT) == []


# --- the rules must actually catch things ------------------------------------


def test_url_rule_flags_instance_urls_anywhere() -> None:
    assert url_violations({"title": "http://192.168.1.10:9100/metrics"}) != []
    assert url_violations({"title": "talk to localhost:3000"}) != []
    assert url_violations({"title": "receiver at 10.0.0.7"}) != []
    assert url_violations([{"title": "http://[::1]:9100"}]) != []


def test_url_rule_flags_absolute_urls_outside_allowed_keys() -> None:
    problems = url_violations({"description": "see https://grafana.com/docs/"})
    assert problems and "hardcoded instance URL" in problems[0]


def test_url_rule_allows_documentation_links_under_allowed_keys() -> None:
    assert url_violations({"url": "https://grafana.com/docs/grafana/latest/"}) == []
    assert url_violations({"links": [{"url": "/d/abc/overview"}]}) == []
    assert url_violations({"href": "#panel-1"}) == []
    assert url_violations({"content": "${__url_time_range}"}) == []


def test_url_rule_flags_forbidden_hosts_under_allowed_keys() -> None:
    assert url_violations({"url": "http://prometheus.local:9090"}) != []
    assert url_violations({"url": "https://example.com/grafana"}) != []


def test_url_rule_ignores_non_string_scalars() -> None:
    assert url_violations(42) == []
    assert url_violations(None) == []
    assert url_violations({"count": 3, "ratio": 0.5}) == []


def test_check_dashboard_flags_unknown_metrics_and_urls() -> None:
    document = copy.deepcopy(load("overview.json"))
    document["panels"][0]["targets"][0]["expr"] = "dump1090_aircraft_flying"
    document["panels"][1]["targets"][0]["expr"] = "up"
    document["links"] = [{"title": "metrics", "url": "http://10.1.2.3:9100/"}]
    problems = check_dashboard("overview.json", document, SCHEMA)
    assert any("unknown metric" in problem for problem in problems)
    assert any("queries no dump1090_* series" in problem for problem in problems)
    assert any("hardcoded host" in problem for problem in problems)


def test_check_dashboard_flags_duplicate_and_invalid_panel_ids() -> None:
    document = copy.deepcopy(load("overview.json"))
    document["panels"][1]["id"] = document["panels"][0]["id"]
    document["panels"][2]["id"] = 0
    document["panels"][3]["id"] = True
    problems = check_dashboard("overview.json", document, SCHEMA)
    assert sum("used twice" in problem for problem in problems) == 1
    assert sum("invalid id" in problem for problem in problems) == 2


def test_check_dashboard_flags_wrong_datasource_everywhere() -> None:
    document = copy.deepcopy(load("overview.json"))
    document["panels"][0]["datasource"]["uid"] = "prometheus"
    document["panels"][1]["targets"][0]["datasource"]["uid"] = "prometheus"
    problems = check_dashboard("overview.json", document, SCHEMA)
    assert any(
        problem.startswith("overview.json: panel 'Message rate' datasource is")
        for problem in problems
    )
    assert sum("target datasource is 'prometheus'" in problem for problem in problems) == 1


def test_check_dashboard_flags_missing_field_config_pieces() -> None:
    document = copy.deepcopy(load("overview.json"))
    del document["panels"][0]["fieldConfig"]["defaults"]["unit"]
    del document["panels"][1]["fieldConfig"]
    document["panels"][2]["fieldConfig"]["defaults"]["thresholds"]["steps"] = []
    problems = check_dashboard("overview.json", document, SCHEMA)
    assert any("missing required property 'unit'" in problem for problem in problems)
    assert any("has no fieldConfig.defaults" in problem for problem in problems)
    assert any("no threshold steps" in problem for problem in problems)


def test_check_dashboard_flags_too_few_panels_and_no_targets() -> None:
    document = copy.deepcopy(load("overview.json"))
    document["panels"] = document["panels"][:2]
    document["panels"][0]["targets"] = []
    problems = check_dashboard("overview.json", document, SCHEMA)
    assert any("expected at least 4 panels" in problem for problem in problems)
    assert any("has no targets" in problem for problem in problems)


def test_check_dashboard_flags_uid_and_template_variable() -> None:
    document = copy.deepcopy(load("overview.json"))
    document["uid"] = "Dump1090 Overview"
    document["templating"]["list"] = []
    problems = check_dashboard("overview.json", document, SCHEMA)
    assert any("not kebab-case" in problem for problem in problems)
    assert any("DS_PROMETHEUS datasource template variable" in problem for problem in problems)

    document["uid"] = ""
    problems = check_dashboard("overview.json", document, SCHEMA)
    assert any("missing or empty dashboard uid" in problem for problem in problems)


def test_check_dashboard_flags_broken_targets() -> None:
    document = copy.deepcopy(load("overview.json"))
    document["panels"][0]["targets"][0]["expr"] = "   "
    document["panels"][1]["targets"][0]["expr"] = "sum(rate(x[5m]))"
    document["panels"][2]["targets"][0]["datasource"] = {"type": "prometheus"}
    problems = check_dashboard("overview.json", document, SCHEMA)
    assert any("target without an expr" in problem for problem in problems)
    assert any("queries no dump1090_* series" in problem for problem in problems)
    assert any("target datasource is None" in problem for problem in problems)


def test_schema_rejects_a_hand_mangled_dashboard() -> None:
    document = copy.deepcopy(load("overview.json"))
    document["panels"][0]["id"] = -1
    document["panels"][0]["datasource"]["uid"] = "hardcoded-uid"
    document["panels"] = document["panels"][:1]
    problems = validate_document(document, SCHEMA)
    assert any("expected at least 4 items" in problem for problem in problems)
    assert any("expected at least 1, got -1" in problem for problem in problems)
    assert any("expected constant" in problem for problem in problems)


def test_check_dashboard_flags_an_unsupported_unit() -> None:
    document = copy.deepcopy(load("overview.json"))
    document["panels"][0]["fieldConfig"]["defaults"]["unit"] = "furlongs"
    problems = check_dashboard("overview.json", document, SCHEMA)
    assert any("is not in the allowed set" in problem for problem in problems)
    assert "furlongs" not in ALLOWED_UNITS


def test_panels_walker_descends_into_rows() -> None:
    document = {"panels": [{"id": 1}, {"id": 2, "panels": [{"id": 3}]}]}
    assert [panel["id"] for panel in panels(document)] == [1, 2, 3]
    assert list(panels({})) == []
    assert list(panels({"panels": "not-a-list"})) == []


def test_targets_walker_ignores_malformed_shapes() -> None:
    assert list(targets({"targets": "nope"})) == []
    assert list(targets({"targets": [1, "x", {"refId": "A"}]})) == [{"refId": "A"}]
    assert list(targets({})) == []


def test_datasource_uid_requires_a_mapping_with_a_string_uid() -> None:
    assert datasource_uid({}) is None
    assert datasource_uid({"datasource": "prometheus"}) is None
    assert datasource_uid({"datasource": {"type": "prometheus"}}) is None
    assert datasource_uid({"datasource": {"uid": 7}}) is None
    assert datasource_uid({"datasource": {"uid": "prometheus"}}) == "prometheus"


def test_has_datasource_variable_covers_malformed_shapes() -> None:
    assert not has_datasource_variable({})
    assert not has_datasource_variable({"templating": {}})
    assert not has_datasource_variable({"templating": {"list": []}})
    assert not has_datasource_variable({"templating": {"list": ["x"]}})
    assert not has_datasource_variable({"templating": {"list": [{"name": "OTHER"}]}})
    variable = {"name": "DS_PROMETHEUS", "type": "datasource"}
    assert has_datasource_variable({"templating": {"list": [variable]}})


def test_metrics_helper_understands_histogram_series() -> None:
    assert metrics_in("rate(dump1090_messages_total[5m])") == {"dump1090_messages_total"}
    assert metrics_in("sum by (stage) (dump1090_cpu_milliseconds)") == {"dump1090_cpu_milliseconds"}
    assert metrics_in("up == 0") == set()
    assert is_known_metric("dump1090_aircraft_altitude_bucket")
    assert is_known_metric("dump1090_aircraft_altitude_sum")
    assert is_known_metric("dump1090_aircraft_altitude_count")
    assert is_known_metric("dump1090_aircraft_altitude")
    assert not is_known_metric("dump1090_aircraft_altitude_histogram")
    assert not is_known_metric("dump1090_does_not_exist")


def test_labelled_metrics_are_a_subset_of_the_exporter_metrics() -> None:
    assert set(METRIC_LABELS) <= EXPORTER_METRICS
    assert METRIC_LABELS["dump1090_signal_dbfs"] == ("quantile",)
    assert {"dump1090_up", "dump1090_messages_per_second"} <= EXPORTER_METRICS
