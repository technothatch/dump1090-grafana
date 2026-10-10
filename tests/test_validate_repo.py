"""validate_repo and the CLI, exercised against deliberately broken checkouts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from dump1090_grafana.cli import main
from dump1090_grafana.dashboards import (
    DashboardError,
    dashboard_paths,
    read_document,
    validate_repo,
)

ROOT = Path(__file__).resolve().parents[1]
REAL_SCHEMA = (ROOT / "schema" / "dashboard.schema.json").read_text(encoding="utf-8")


def make_root(
    tmp_path: Path,
    dashboards: dict[str, str] | None = None,
    schema: str | None = REAL_SCHEMA,
) -> Path:
    """Build a miniature repository below *tmp_path*."""
    if schema is not None:
        (tmp_path / "schema").mkdir()
        (tmp_path / "schema" / "dashboard.schema.json").write_text(schema, encoding="utf-8")
    if dashboards is not None:
        folder = tmp_path / "dashboards"
        folder.mkdir()
        for name, text in dashboards.items():
            (folder / name).write_text(text, encoding="utf-8")
    return tmp_path


def overview_json(**changes: Any) -> str:
    """Return the shipped overview dashboard as JSON text with *changes* applied."""
    document = json.loads((ROOT / "dashboards" / "overview.json").read_text(encoding="utf-8"))
    document.update(changes)
    return json.dumps(document)


def test_missing_schema_file_is_reported(tmp_path: Path) -> None:
    root = make_root(tmp_path, schema=None)
    problems = validate_repo(root)
    assert len(problems) == 1
    assert "cannot read file" in problems[0]


def test_repository_without_dashboards_is_reported(tmp_path: Path) -> None:
    problems = validate_repo(make_root(tmp_path, dashboards={}))
    assert problems == [f"no dashboard JSON files found in {tmp_path / 'dashboards'}"]


def test_unparseable_dashboard_is_reported(tmp_path: Path) -> None:
    root = make_root(tmp_path, dashboards={"broken.json": '{"panels": ['})
    problems = validate_repo(root)
    assert len(problems) == 1
    assert "invalid JSON" in problems[0]


def test_non_object_dashboard_is_reported(tmp_path: Path) -> None:
    root = make_root(tmp_path, dashboards={"list.json": "[1, 2, 3]"})
    problems = validate_repo(root)
    assert len(problems) == 1
    assert "top level is not a JSON object" in problems[0]


def test_house_rule_violations_are_reported(tmp_path: Path) -> None:
    document = json.loads((ROOT / "dashboards" / "overview.json").read_text(encoding="utf-8"))
    document["panels"][0]["targets"][0]["expr"] = "dump1090_aircraft_flying"
    document["links"] = [{"title": "go", "url": "http://192.168.0.4:3000/"}]
    root = make_root(tmp_path, dashboards={"overview.json": json.dumps(document)})
    problems = validate_repo(root)
    assert any("unknown metric" in problem for problem in problems)
    assert any("hardcoded host" in problem for problem in problems)


def test_duplicate_dashboard_uids_are_reported(tmp_path: Path) -> None:
    text = overview_json()
    root = make_root(tmp_path, dashboards={"a.json": text, "b.json": text})
    problems = validate_repo(root)
    assert len(problems) == 1
    assert "is also used by a.json" in problems[0]


def test_a_clean_checkout_validates(tmp_path: Path) -> None:
    root = make_root(tmp_path, dashboards={"overview.json": overview_json()})
    assert validate_repo(root) == []
    assert dashboard_paths(root) == [root / "dashboards" / "overview.json"]


def test_cli_prints_a_summary_on_success(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--root", str(ROOT)]) == 0
    captured = capsys.readouterr()
    assert "OK: 4 dashboard(s), 26 panel(s) validated" in captured.out
    assert "dashboard.schema.json" in captured.out
    assert captured.err == ""


def test_cli_defaults_to_this_checkout(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "OK: 4 dashboard(s)" in capsys.readouterr().out


def test_python_dash_module_entry_point_runs() -> None:
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    result = subprocess.run(
        [sys.executable, "-m", "dump1090_grafana", "--root", str(ROOT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "OK: 4 dashboard(s)" in result.stdout


def test_cli_reports_failure_on_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_root(tmp_path, dashboards={"broken.json": "not json at all"})
    assert main(["--root", str(root)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "invalid JSON" in captured.err
    assert "1 problem(s) found" in captured.err


def test_cli_reports_every_problem_of_a_messy_dashboard(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = json.loads((ROOT / "dashboards" / "overview.json").read_text(encoding="utf-8"))
    document["templating"] = {"list": []}
    document["panels"][1]["id"] = document["panels"][0]["id"]
    root = make_root(tmp_path, dashboards={"overview.json": json.dumps(document)})
    assert main(["--root", str(root)]) == 1
    captured = capsys.readouterr()
    assert "DS_PROMETHEUS datasource template variable" in captured.err
    assert "used twice" in captured.err
    assert "problem(s) found" in captured.err


def test_read_document_reports_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(DashboardError, match="cannot read file"):
        read_document(tmp_path / "absent.json")


def test_read_document_reports_a_directory(tmp_path: Path) -> None:
    with pytest.raises(DashboardError, match="cannot read file"):
        read_document(tmp_path)


def test_read_document_reports_a_non_object(tmp_path: Path) -> None:
    path = tmp_path / "list.json"
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(DashboardError, match="top level is not a JSON object"):
        read_document(path)
