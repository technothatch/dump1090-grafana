# dump1090-grafana

[![CI](https://github.com/technothatch/dump1090-grafana/actions/workflows/ci.yml/badge.svg)](https://github.com/technothatch/dump1090-grafana/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/technothatch/dump1090-grafana/blob/main/LICENSE)
[![Latest Release](https://img.shields.io/github/v/release/technothatch/dump1090-grafana)](https://github.com/technothatch/dump1090-grafana/releases)
[![Issues](https://img.shields.io/github/issues/technothatch/dump1090-grafana)](https://github.com/technothatch/dump1090-grafana/issues)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/technothatch/dump1090-grafana/pulls)
[![Code size](https://img.shields.io/github/languages/code-size/technothatch/dump1090-grafana)](https://github.com/technothatch/dump1090-grafana)
[![Last commit](https://img.shields.io/github/last-commit/technothatch/dump1090-grafana)](https://github.com/technothatch/dump1090-grafana/commits/main)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Coverage](https://img.shields.io/badge/coverage-96%25-brightgreen.svg)](https://github.com/technothatch/dump1090-grafana/actions/workflows/ci.yml)

Four ready-to-import Grafana dashboards for watching a **dump1090** or **readsb**
ADS-B receiver: message rate, aircraft count, signal quality, decoder CPU, range
coverage and squawk mix, all sourced from the Prometheus metrics that
[dump1090-exporter](https://github.com/technothatch/dump1090-exporter) exposes
for your decoder. Every dashboard is a plain JSON file with no stack coupling —
drop it on any Grafana 10/11 that scrapes `dump1090_*` series and it works. The
repository ships with a JSON Schema, a zero-dependency validator, provisioning
examples and an import script so the dashboards can be reviewed, tested and
versioned like code instead of being edited only in the Grafana UI.

## Features

- **`dashboards/overview.json`** (8 panels) — message rate (ops), aircraft
  tracked, signal strength quantiles (dBFS), CPU by pipeline stage, plus
  decoder reachability, scrape duration, JSON refresh interval and decoder
  version stats.
- **`dashboards/coverage.json`** (5 panels) — altitude percentiles, altitude
  distribution over the last hour, unique tracks, aircraft with a position and
  local CPR decode success (how much of the sky your antenna actually hears).
- **`dashboards/receiver-health.json`** (7 panels) — `dump1090_up`, hour-long
  uptime, scrape duration, exporter staleness, dropped blocks and a
  decoder-availability timeline.
- **`dashboards/traffic.json`** (6 panels) — top-10 squawks, emergency-squawk
  alert stat, squawk coverage, altitude bands over time and per-squawk tracks.
- **`schema/dashboard.schema.json`** — JSON Schema (draft 2020-12) describing
  the house shape: kebab-case uid, `${DS_PROMETHEUS}` datasource, ≥4 panels,
  positive unique panel ids, thresholds, units and time range.
- **`src/dump1090_grafana/`** — a small Python package that validates the whole
  checkout (schema **and** house rules) with only the standard library; exposed
  as `dump1090-grafana` / `python -m dump1090_grafana` and wired to
  `make validate`.
- **`provisioning/`** — ready-to-paste Grafana datasource and dashboard
  provisioner configs (`uid: prometheus` matches the dashboards' variable).
- **`scripts/import.sh`** — imports every dashboard through the Grafana HTTP
  API, or copies dashboards plus provisioning files into a Grafana data
  directory (`--mode provision`).
- **108 tests** covering schema validation, every house rule and the whole
  repository, with branch coverage.

## Install

```bash
git clone https://github.com/technothatch/dump1090-grafana.git
cd dump1090-grafana
python -m pip install -e ".[dev]"     # ruff, mypy, pytest, pytest-cov
make help                             # list the available targets
```

Python ≥ 3.11 is the only runtime requirement; the validator itself uses the
standard library only, so `make validate` also works on a fresh checkout
without installing the package (`PYTHONPATH=src python -m dump1090_grafana`).

## Quickstart

Validate the shipped dashboards:

```console
$ PYTHONPATH=src python -m dump1090_grafana --root .
OK: 4 dashboard(s), 26 panel(s) validated against schema/dashboard.schema.json
```

Run the test suite (what CI runs, including the coverage floor):

```console
$ python -m pytest -q --cov --cov-report=term-missing --cov-fail-under=80
...
Required test coverage of 80% reached. Total coverage: 96.35%
108 passed in 1.52s
```

Then get the dashboards into Grafana — three supported ways.

**1. UI upload (fastest):** Grafana → **Dashboards → New → Import → Upload
JSON file**, pick a file from `dashboards/`, choose your Prometheus datasource
when asked for `DS_PROMETHEUS`, press **Import**.

**2. Provisioning (GitOps):** copy `dashboards/*.json` somewhere Grafana can
read them and point the bundled provider at that directory:

```yaml
# provisioning/dashboards/dump1090-grafana.yml (abridged)
providers:
  - name: dump1090-grafana
    folder: ADS-B
    type: file
    options:
      path: /var/lib/grafana/dashboards
```

Restart Grafana (or wait `updateIntervalSeconds`) and the four dashboards appear
under the **ADS-B** folder.

**3. Script (HTTP API):** `grafana-cli` only manages plugins — it has no
dashboard-import subcommand — so the supported non-interactive route is the HTTP
API, which `scripts/import.sh` wraps:

```console
$ GRAFANA_TOKEN=glsa_xxx GRAFANA_URL=https://grafana.internal ./scripts/import.sh
coverage.json -> {"id":12,"slug":"coverage","status":"success","uid":"dump1090-grafana-coverage","url":"/d/dump1090-grafana-coverage","version":1,"message":"Dashboard imported"}
overview.json -> {"id":13,"slug":"overview","status":"success","uid":"dump1090-grafana-overview","url":"/d/dump1090-grafana-overview","version":1,"message":"Dashboard imported"}
receiver-health.json -> {"id":14,"slug":"receiver-health","status":"success","uid":"dump1090-grafana-receiver-health","url":"/d/dump1090-grafana-receiver-health","version":1,"message":"Dashboard imported"}
traffic.json -> {"id":15,"slug":"traffic","status":"success","uid":"dump1090-grafana-traffic","url":"/d/dump1090-grafana-traffic","version":1,"message":"Dashboard imported"}
imported 4 dashboard(s) into https://grafana.internal
```

`./scripts/import.sh --mode provision` does the copy-into-a-data-directory
variant instead (set `GRAFANA_DATA_DIR`, default `/var/lib/grafana`).

## Configuration reference

| Setting | Type | Meaning | Default |
| --- | --- | --- | --- |
| `--root PATH` | CLI flag (`dump1090-grafana`) | Repository root to validate | this checkout |
| `PYTHONPATH=src` | env | Lets `python -m dump1090_grafana` run from a checkout without installing | unset |
| `GRAFANA_URL` | env (`import.sh`) | Base URL of the Grafana instance | `http://localhost:3000` |
| `GRAFANA_TOKEN` | env (`import.sh`) | Service-account token (preferred) | unset |
| `GRAFANA_USER` / `GRAFANA_PASSWORD` | env (`import.sh`) | Basic-auth credentials used when no token is set | `admin` / `admin` |
| `GRAFANA_FOLDER_UID` | env (`import.sh`) | Destination folder uid for API imports | empty (General) |
| `GRAFANA_DATA_DIR` | env (`import.sh --mode provision`) | Grafana data directory to copy into | `/var/lib/grafana` |
| `PYTHON` | env (`import.sh`) | Python interpreter used to build payloads | `python3` |
| `DS_PROMETHEUS` | Grafana template variable | Datasource every panel/target resolves through | uid `prometheus` |
| `provisioning/datasources/prometheus.yml` | file | Datasource definition with the `prometheus` uid | `http://prometheus:9090` |
| `provisioning/dashboards/dump1090-grafana.yml` | file | File provisioner: folder `ADS-B`, UI edits disabled | path `/var/lib/grafana/dashboards`, refresh `30s` |
| `dashboards/*.json` | file | The four importable dashboards | 4 files, 26 panels |
| `schema/dashboard.schema.json` | file | Schema every dashboard is validated against | draft 2020-12 |

## How it works

```
dump1090 / readsb  --HTTP JSON-->  dump1090-exporter  --/metrics-->  Prometheus
                                                                        |
                                             Grafana ${DS_PROMETHEUS} <-+
                                                            |
                                              dashboards/*.json (git)
                                                            |
                                        schema + house rules + 108 tests
```

- **Datasource indirection.** Each dashboard declares a `DS_PROMETHEUS`
  datasource template variable, and every panel and target references
  `${DS_PROMETHEUS}` instead of a uid. A dashboard therefore works both when
  imported through the UI (Grafana prompts for the datasource) and when
  provisioned from disk (the variable falls back to the template's current
  value, `prometheus`, which is exactly the uid created by
  `provisioning/datasources/prometheus.yml`).
- **Metric names are real.** `EXPORTER_METRICS` in
  `src/dump1090_grafana/dashboards.py` mirrors
  `dump1090-exporter/internal/exporter/exporter.go`; a panel that queries a
  typo (`dump1090_msg_total`) fails `make validate`. Histogram expansions
  (`_bucket`, `_sum`, `_count`) are accepted.
- **House rules** enforced on every checkout: dashboard uid is kebab-case and
  unique; ≥4 panels; panel ids positive and unique; every panel and target uses
  `${DS_PROMETHEUS}`; every panel declares a supported unit and threshold
  steps; and **no hardcoded instance URL** — any string containing an IPv4
  literal, `localhost`, `[::1]` or `host:port` is a violation, and any
  `http(s)://` URL is a violation unless it sits under a `url`/`links`/`href`
  key and starts with `/`, `${`, `#`, or a documentation host
  (`grafana.com`, `prometheus.io`, `github.com/technothatch/`).
- **Units.** Panels use `ops`, `dBFS`, `ft`, `percent`, `short`, `s` and
  `none`. `kn` is in the allowed set but unused: dump1090-exporter exposes no
  ground-speed metric, so a speed panel would have nothing honest to plot.
- **Grafana compatibility.** `schemaVersion: 39`, current `fieldConfig`,
  `thresholds` and `options` shapes — readable by Grafana 10 and 11.

## Development

```console
$ ruff check . && ruff format --check .
All checks passed!
13 files already formatted

$ mypy src
Success: no issues found in 5 source files

$ python -m pytest -q --cov --cov-report=term-missing --cov-fail-under=80
Required test coverage of 80% reached. Total coverage: 96.35%
108 passed in 1.52s
```

Or the same gate in one go:

```bash
make check        # lint + validate + test
make format       # apply ruff fixes and formatting
make validate     # schema + house rules for every dashboard
```

Layout: `dashboards/` (JSON), `schema/` (JSON Schema), `src/dump1090_grafana/`
(validator package), `tests/` (pytest), `provisioning/` (Grafana examples),
`scripts/import.sh` (API/provisioning import).

## Related projects

- [dump1090-fa](https://github.com/flightaware/dump1090) — FlightAware's
  dump1090, the reference Mode S decoder.
- [readsb](https://github.com/wiedehopf/readsb) — the decoder this ecosystem is
  usually deployed with.
- [tar1090](https://github.com/wiedehopf/tar1090) — web map for dump1090/readsb.
- [graphs1090](https://github.com/wiedehopf/graphs1090) — historical graphs for
  the same receivers.
- `technothatch/dump1090-exporter` — Prometheus exporter whose metrics these
  dashboards query.
- `technothatch/dump1090-stack` — compose stack that ships these dashboards
  under provisioning.
- `technothatch/dump1090-alerts` — alert rules for the same metrics.

## License

MIT — see [LICENSE](LICENSE).

---

## Related projects

Part of the [technothatch ADS-B toolkit](https://github.com/technothatch/technothatch#readme) - the full index with one-liners for every tool lives there.

- **Run & operate:** [dump1090-stack](https://github.com/technothatch/dump1090-stack) - full Compose stack; [dump1090-healthcheck](https://github.com/technothatch/dump1090-healthcheck) - decoder watchdog; [dump1090-alerts](https://github.com/technothatch/dump1090-alerts) - rule-based alerting
- **Metrics & data:** [dump1090-exporter](https://github.com/technothatch/dump1090-exporter) - Prometheus; [dump1090-influx](https://github.com/technothatch/dump1090-influx) - InfluxDB/Telegraf; [dump1090-grafana](https://github.com/technothatch/dump1090-grafana) - dashboards; [dump1090-recorder](https://github.com/technothatch/dump1090-recorder) - SQLite history; [dump1090-coverage](https://github.com/technothatch/dump1090-coverage) - heatmaps & reports
- **Feeds & networking:** [beast-relay](https://github.com/technothatch/beast-relay) - Beast fan-out; [dump1090-geofence](https://github.com/technothatch/dump1090-geofence) - region-filtered feeds; [dump1090-to-mqtt](https://github.com/technothatch/dump1090-to-mqtt) - MQTT/Home Assistant
- **Interfaces:** [dump1090-dashboard](https://github.com/technothatch/dump1090-dashboard) - web UI; [adsb-tui](https://github.com/technothatch/adsb-tui) - terminal radar; [dump1090-cli](https://github.com/technothatch/dump1090-cli) - aircraft.json CLI; [dump1090-sdk](https://github.com/technothatch/dump1090-sdk) - TypeScript client
- **Testing & decoding:** [dump1090-simulator](https://github.com/technothatch/dump1090-simulator) - synthetic traffic; [dump1090-replay](https://github.com/technothatch/dump1090-replay) - recorded history replay; [squawk-decoder](https://github.com/technothatch/squawk-decoder) - squawk/emitter/ICAO decoder
