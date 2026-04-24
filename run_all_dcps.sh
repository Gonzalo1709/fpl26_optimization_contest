#!/usr/bin/env bash

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Default benchmark path prefers sibling folder, then in-repo folder.
DEFAULT_BENCH_DIR="${SCRIPT_DIR}/../fpl26_contest_benchmarks"
if [[ ! -d "${DEFAULT_BENCH_DIR}" ]]; then
  DEFAULT_BENCH_DIR="${SCRIPT_DIR}/fpl26_contest_benchmarks"
fi

BENCH_DIR="${DEFAULT_BENCH_DIR}"
MODE="test"
MAX_NETS="5"
PYTHON_BIN="python3"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_ROOT="${SCRIPT_DIR}/batch_logs"
LOG_DIR="${LOG_ROOT}/run-${TIMESTAMP}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Run dcp_optimizer.py on every .dcp file in a benchmark directory and save logs.

Options:
  --bench-dir <path>   Benchmark directory containing .dcp files
                       (default: ${DEFAULT_BENCH_DIR})
  --logs-dir <path>    Directory where run logs should be written
                       (default: ${LOG_DIR})
  --mode <mode>        Execution mode: test | optimizer (default: test)
  --max-nets <n>       Max nets for --test mode (default: 5)
  --python <bin>       Python executable to use (default: python3)
  -h, --help           Show this help

Examples:
  $(basename "$0")
  $(basename "$0") --bench-dir "${SCRIPT_DIR}/../fpl26_contest_benchmarks" --mode test
  $(basename "$0") --mode optimizer --logs-dir "${SCRIPT_DIR}/batch_logs/full_run"
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bench-dir)
      BENCH_DIR="$2"
      shift 2
      ;;
    --logs-dir)
      LOG_DIR="$2"
      shift 2
      ;;
    --mode)
      MODE="$2"
      shift 2
      ;;
    --max-nets)
      MAX_NETS="$2"
      shift 2
      ;;
    --python)
      PYTHON_BIN="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ "${MODE}" != "test" && "${MODE}" != "optimizer" ]]; then
  echo "Error: --mode must be either 'test' or 'optimizer'" >&2
  exit 2
fi

if [[ ! -d "${BENCH_DIR}" ]]; then
  echo "Error: benchmark directory not found: ${BENCH_DIR}" >&2
  exit 1
fi

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "Error: Python executable not found: ${PYTHON_BIN}" >&2
  exit 1
fi

if [[ "${MODE}" == "optimizer" && -z "${OPENROUTER_API_KEY:-}" ]]; then
  echo "Error: OPENROUTER_API_KEY is required in optimizer mode" >&2
  exit 1
fi

mkdir -p "${LOG_DIR}"

mapfile -t DCP_FILES < <(find "${BENCH_DIR}" -maxdepth 1 -type f -name "*.dcp" | sort)

if [[ ${#DCP_FILES[@]} -eq 0 ]]; then
  echo "Error: no .dcp files found in ${BENCH_DIR}" >&2
  exit 1
fi

SUMMARY_CSV="${LOG_DIR}/summary.csv"
echo "dcp,status,exit_code,log_file,start_time,end_time" > "${SUMMARY_CSV}"

echo "Batch run started"
echo "  Mode:           ${MODE}"
echo "  Benchmark dir:  ${BENCH_DIR}"
echo "  Log directory:  ${LOG_DIR}"
echo "  DCP count:      ${#DCP_FILES[@]}"
echo

total=${#DCP_FILES[@]}
ok=0
failed=0
index=0

for dcp in "${DCP_FILES[@]}"; do
  index=$((index + 1))
  dcp_name="$(basename "${dcp}")"
  stem="${dcp_name%.dcp}"
  log_file="${LOG_DIR}/${stem}.log"
  start_time="$(date '+%Y-%m-%d %H:%M:%S')"

  if [[ "${MODE}" == "test" ]]; then
    cmd=("${PYTHON_BIN}" "${SCRIPT_DIR}/dcp_optimizer.py" "${dcp}" "--test" "--max-nets" "${MAX_NETS}")
  else
    cmd=("${PYTHON_BIN}" "${SCRIPT_DIR}/dcp_optimizer.py" "${dcp}")
  fi

  echo "[${index}/${total}] Running ${dcp_name}"
  echo "Command: ${cmd[*]}" > "${log_file}"
  echo "Started: ${start_time}" >> "${log_file}"
  echo "------------------------------------------------------------" >> "${log_file}"

  "${cmd[@]}" 2>&1 | tee -a "${log_file}"
  exit_code=${PIPESTATUS[0]}

  end_time="$(date '+%Y-%m-%d %H:%M:%S')"

  if [[ ${exit_code} -eq 0 ]]; then
    status="PASS"
    ok=$((ok + 1))
  else
    status="FAIL"
    failed=$((failed + 1))
  fi

  echo "------------------------------------------------------------" >> "${log_file}"
  echo "Ended: ${end_time}" >> "${log_file}"
  echo "Exit code: ${exit_code}" >> "${log_file}"
  echo "Status: ${status}" >> "${log_file}"

  printf '"%s",%s,%d,"%s","%s","%s"\n' \
    "${dcp}" "${status}" "${exit_code}" "${log_file}" "${start_time}" "${end_time}" >> "${SUMMARY_CSV}"

  echo "[${index}/${total}] ${status} - log: ${log_file}"
  echo
done

echo "Batch run complete"
echo "  Passed:   ${ok}"
echo "  Failed:   ${failed}"
echo "  Summary:  ${SUMMARY_CSV}"

if [[ ${failed} -gt 0 ]]; then
  exit 1
fi

exit 0