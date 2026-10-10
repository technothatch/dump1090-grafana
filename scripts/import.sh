#!/usr/bin/env bash
#
# Import the dump1090-grafana dashboards into a running Grafana.
#
# Two modes:
#
#   api        (default) POST each dashboards/*.json to the Grafana HTTP API.
#   provision  copy dashboards/ and provisioning/ into a Grafana data directory
#              so a file provisioner picks them up.
#
# grafana-cli only manages plugins (it has no dashboard-import command), so the
# HTTP API is the supported non-interactive route; provisioning is the other.
# Every dashboard resolves ${DS_PROMETHEUS} through its own template variable,
# which defaults to the datasource uid `prometheus` created by
# provisioning/datasources/prometheus.yml.
set -euo pipefail

GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
GRAFANA_USER="${GRAFANA_USER:-admin}"
GRAFANA_PASSWORD="${GRAFANA_PASSWORD:-admin}"
GRAFANA_TOKEN="${GRAFANA_TOKEN:-}"
GRAFANA_FOLDER_UID="${GRAFANA_FOLDER_UID:-}"
GRAFANA_DATA_DIR="${GRAFANA_DATA_DIR:-/var/lib/grafana}"
MODE="${MODE:-api}"
PYTHON_BIN="${PYTHON:-python3}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DASHBOARDS_DIR="$ROOT/dashboards"

usage() {
  cat <<EOF
Usage: $(basename "$0") [--mode api|provision] [--help]

  --mode api        upload every dashboard through the Grafana HTTP API
                    (default)
  --mode provision  copy dashboards/ and provisioning/ into GRAFANA_DATA_DIR

Environment:
  GRAFANA_URL         base URL of Grafana          (default http://localhost:3000)
  GRAFANA_TOKEN       service-account token, preferred over user/password
  GRAFANA_USER        basic-auth user              (default admin)
  GRAFANA_PASSWORD    basic-auth password          (default admin)
  GRAFANA_FOLDER_UID  destination folder uid       (default: General)
  GRAFANA_DATA_DIR    provision target             (default /var/lib/grafana)
  PYTHON              python interpreter           (default python3)

Examples:
  GRAFANA_TOKEN=glsa_xxx ./scripts/import.sh
  GRAFANA_URL=https://grafana.example.internal ./scripts/import.sh
  ./scripts/import.sh --mode provision
EOF
}

die() {
  printf 'import.sh: %s\n' "$1" >&2
  exit 1
}

payload_for() {
  "$PYTHON_BIN" - "$1" "$GRAFANA_FOLDER_UID" <<'PY'
import json
import sys

path, folder = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as handle:
    dashboard = json.load(handle)
payload = {
    "dashboard": dashboard,
    "overwrite": True,
    "folderUid": folder,
    "message": "imported by dump1090-grafana/scripts/import.sh",
}
print(json.dumps(payload))
PY
}

upload() {
  local file="$1"
  local payload
  local response
  payload="$(payload_for "$file")"
  response="$("$CURL" "${CURL_ARGS[@]}" -X POST -d "$payload" \
    "$GRAFANA_URL/api/dashboards/db")"
  printf '%s -> %s\n' "$(basename "$file")" "$response"
}

import_via_api() {
  command -v curl >/dev/null 2>&1 || die "curl is required for --mode api"
  command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "$PYTHON_BIN is required"
  CURL_ARGS=(-sS -H "Content-Type: application/json")
  CURL="curl"
  if [ -n "$GRAFANA_TOKEN" ]; then
    CURL_ARGS+=(-H "Authorization: Bearer $GRAFANA_TOKEN")
  else
    CURL_ARGS+=(-u "$GRAFANA_USER:$GRAFANA_PASSWORD")
  fi
  local count=0
  local file
  for file in "$DASHBOARDS_DIR"/*.json; do
    upload "$file"
    count=$((count + 1))
  done
  printf 'imported %d dashboard(s) into %s\n' "$count" "$GRAFANA_URL"
}

import_via_provisioning() {
  command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "$PYTHON_BIN is required"
  local target="$GRAFANA_DATA_DIR"
  mkdir -p "$target/dashboards" \
    "$target/provisioning/dashboards" "$target/provisioning/datasources"
  cp "$DASHBOARDS_DIR"/*.json "$target/dashboards/"
  cp "$ROOT"/provisioning/dashboards/*.yml "$target/provisioning/dashboards/"
  cp "$ROOT"/provisioning/datasources/*.yml "$target/provisioning/datasources/"
  printf 'copied dashboards and provisioning files to %s\n' "$target"
  printf 'restart Grafana, or wait for updateIntervalSeconds to elapse\n'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --mode)
      [ $# -ge 2 ] || die "--mode needs an argument"
      MODE="$2"
      shift 2
      ;;
    --mode=*)
      MODE="${1#*=}"
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      die "unknown argument: $1"
      ;;
  esac
done

[ -d "$DASHBOARDS_DIR" ] || die "no dashboards/ directory in $ROOT"

for file in "$DASHBOARDS_DIR"/*.json; do
  [ -e "$file" ] || die "no dashboard JSON files in $DASHBOARDS_DIR"
  "$PYTHON_BIN" -c "import json, sys; json.load(open(sys.argv[1], encoding='utf-8'))" \
    "$file" || die "$file is not valid JSON"
done

case "$MODE" in
  api)
    import_via_api
    ;;
  provision)
    import_via_provisioning
    ;;
  *)
    die "unknown mode: $MODE (expected api or provision)"
    ;;
esac
