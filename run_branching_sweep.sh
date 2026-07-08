#!/usr/bin/env bash

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DEFAULT_BENCH_DIR="${SCRIPT_DIR}/../fpl26_contest_benchmarks"
if [[ ! -d "${DEFAULT_BENCH_DIR}" ]]; then
  DEFAULT_BENCH_DIR="${SCRIPT_DIR}/fpl26_contest_benchmarks"
fi

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_ROOT="${SCRIPT_DIR}/branching_sweep_logs"
LOG_DIR="${LOG_ROOT}/run-${TIMESTAMP}"

BENCH_DIR="${DEFAULT_BENCH_DIR}"
PYTHON_BIN="python3"
COMMON_OPT_ARGS=""
SEARCH_MODE="generations"

declare -a SETTING_LABELS=()
declare -a SETTING_ARGS=()

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Run the full optimizer on every .dcp file in a folder, sweeping multiple
branching/search configurations and saving per-run logs plus a CSV summary.

Options:
  --bench-dir <path>         Benchmark directory containing .dcp files
                             (default: ${DEFAULT_BENCH_DIR})

  --logs-dir <path>          Directory where sweep logs should be written
                             (default: ${LOG_DIR})

  --python <bin>             Python executable to use
                             (default: python3)

  --search-mode <mode>       Search mode passed to dcp_optimizer.py
                             (default: generations)

  --common-opt-args <text>   Extra optimizer args added to every run

  --setting <spec>           Add one sweep configuration
                             Format: <label>|<optimizer args>
                             Example:
                               --setting "b2_bw2_g3|--branches 2 --beam-width 2 --generations 3"

  -h, --help                 Show this help

Default settings used when no --setting options are provided:
  b1_bw1_g2    -> --branches 1 --beam-width 1 --generations 2
  b2_bw2_g3    -> --branches 2 --beam-width 2 --generations 3
  b3_bw2_g4    -> --branches 3 --beam-width 2 --generations 4
  b3_bw3_g4    -> --branches 3 --beam-width 3 --generations 4

Examples:
  $(basename "$0")
  $(basename "$0") --bench-dir "${SCRIPT_DIR}/../fpl26_contest_benchmarks"
  $(basename "$0") --common-opt-args "--steps-per-branch 4 --max-llm-calls 80"
  $(basename "$0") \\
    --setting "small|--branches 1 --beam-width 1 --generations 2" \\
    --setting "wide|--branches 4 --beam-width 3 --generations 4"
EOF
}

error_exit() {
  echo "Error: $*" >&2
  exit 1
}

add_setting() {
  local spec="$1"
  local label
  local args

  if [[ "${spec}" != *"|"* ]]; then
    error_exit "invalid --setting '${spec}' (expected <label>|<optimizer args>)"
  fi

  label="${spec%%|*}"
  args="${spec#*|}"

  if [[ -z "${label}" ]]; then
    error_exit "invalid --setting '${spec}' (empty label)"
  fi
  if [[ -z "${args}" ]]; then
    error_exit "invalid --setting '${spec}' (empty optimizer args)"
  fi
  if [[ "${label}" == *"/"* ]]; then
    error_exit "invalid --setting label '${label}' (must not contain '/')"
  fi

  SETTING_LABELS+=("${label}")
  SETTING_ARGS+=("${args}")
}

load_default_settings() {

  add_setting "b3_bw2_g4|--branches 3 --beam-width 2 --generations 4"
  add_setting "b3_bw3_g4|--branches 3 --beam-width 3 --generations 4"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bench-dir)
      BENCH_DIR="$2"
      shift 2
      ;;
    --logs-dir)
      LOG_DIR="$2"
      LOG_ROOT="$(dirname "${LOG_DIR}")"
      shift 2
      ;;
    --python)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --search-mode)
      SEARCH_MODE="$2"
      shift 2
      ;;
    --common-opt-args)
      COMMON_OPT_ARGS="$2"
      shift 2
      ;;
    --setting)
      add_setting "$2"
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

if [[ ! -d "${BENCH_DIR}" ]]; then
  error_exit "benchmark directory not found: ${BENCH_DIR}"
fi

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  error_exit "Python executable not found: ${PYTHON_BIN}"
fi

if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
  error_exit "OPENROUTER_API_KEY is required for branching sweep runs"
fi

if [[ "${SEARCH_MODE}" != "generations" && "${SEARCH_MODE}" != "linear" ]]; then
  error_exit "--search-mode must be either 'generations' or 'linear'"
fi

if [[ ${#SETTING_LABELS[@]} -eq 0 ]]; then
  load_default_settings
fi

mkdir -p "${LOG_DIR}"

mapfile -t DCP_FILES < <(find "${BENCH_DIR}" -maxdepth 1 -type f -name "*.dcp" | sort)
if [[ ${#DCP_FILES[@]} -eq 0 ]]; then
  error_exit "no .dcp files found in ${BENCH_DIR}"
fi

SUMMARY_CSV="${LOG_DIR}/summary.csv"
echo "setting_label,dcp,status,exit_code,console_log,run_artifact_dir,optimizer_run_dir,token_usage_json,start_time,end_time,opt_args" > "${SUMMARY_CSV}"

echo "Branching sweep started"
echo "  Benchmark dir:   ${BENCH_DIR}"
echo "  Log directory:   ${LOG_DIR}"
echo "  DCP count:       ${#DCP_FILES[@]}"
echo "  Setting count:   ${#SETTING_LABELS[@]}"
echo "  Search mode:     ${SEARCH_MODE}"
if [[ -n "${COMMON_OPT_ARGS}" ]]; then
  echo "  Common OPT_ARGS: ${COMMON_OPT_ARGS}"
else
  echo "  Common OPT_ARGS: <none>"
fi
echo

for idx in "${!SETTING_LABELS[@]}"; do
  echo "  Setting[$((idx + 1))]: ${SETTING_LABELS[$idx]} -> ${SETTING_ARGS[$idx]}"
done
echo

total_runs=$(( ${#DCP_FILES[@]} * ${#SETTING_LABELS[@]} ))
run_index=0
ok=0
failed=0

for setting_idx in "${!SETTING_LABELS[@]}"; do
  setting_label="${SETTING_LABELS[$setting_idx]}"
  setting_args="${SETTING_ARGS[$setting_idx]}"
  setting_dir="${LOG_DIR}/${setting_label}"
  mkdir -p "${setting_dir}"

  echo "================================================================"
  echo "SETTING: ${setting_label}"
  echo "ARGS:    ${setting_args}"
  echo "================================================================"

  for dcp in "${DCP_FILES[@]}"; do
    run_index=$((run_index + 1))
    dcp_abs="$(realpath "${dcp}")"
    dcp_name="$(basename "${dcp_abs}")"
    stem="${dcp_name%.dcp}"
    run_artifact_dir="${setting_dir}/${stem}"
    log_file="${run_artifact_dir}/console.log"
    optimizer_run_dir=""
    token_usage_json=""
    start_time="$(date '+%Y-%m-%d %H:%M:%S')"

    mkdir -p "${run_artifact_dir}"

    opt_args="--search-mode ${SEARCH_MODE} ${setting_args}"
    if [[ -n "${COMMON_OPT_ARGS}" ]]; then
      opt_args="${opt_args} ${COMMON_OPT_ARGS}"
    fi

    cmd=("make" "-C" "${SCRIPT_DIR}" "run_optimizer" "DCP=${dcp_abs}" "RUN_CWD=${run_artifact_dir}" "PYTHON=${PYTHON_BIN}" "OPT_ARGS=${opt_args}")

    printf -v cmd_display '%q ' "${cmd[@]}"
    cmd_display="${cmd_display% }"

    echo "[${run_index}/${total_runs}] Running ${dcp_name} with ${setting_label}"
    echo "Command: ${cmd_display}" > "${log_file}"
    echo "Started: ${start_time}" >> "${log_file}"
    echo "------------------------------------------------------------" >> "${log_file}"

    "${cmd[@]}" 2>&1 | tee -a "${log_file}"
    exit_code=${PIPESTATUS[0]}

    end_time="$(date '+%Y-%m-%d %H:%M:%S')"

    mapfile -t optimizer_run_dirs < <(find "${run_artifact_dir}" -maxdepth 1 -mindepth 1 -type d -name "dcp_optimizer_run-*" | sort)
    if [[ ${#optimizer_run_dirs[@]} -gt 0 ]]; then
      optimizer_run_dir="${optimizer_run_dirs[-1]}"
      if [[ -f "${optimizer_run_dir}/token_usage.json" ]]; then
        token_usage_json="${optimizer_run_dir}/token_usage.json"
      fi
    fi

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
    echo "Setting label: ${setting_label}" >> "${log_file}"
    echo "OPT_ARGS: ${opt_args}" >> "${log_file}"
    if [[ -n "${optimizer_run_dir}" ]]; then
      echo "Optimizer run dir: ${optimizer_run_dir}" >> "${log_file}"
    fi
    if [[ -n "${token_usage_json}" ]]; then
      echo "Token usage JSON: ${token_usage_json}" >> "${log_file}"
    fi

    printf '"%s","%s",%s,%d,"%s","%s","%s","%s","%s","%s","%s"\n' \
      "${setting_label}" "${dcp_abs}" "${status}" "${exit_code}" "${log_file}" "${run_artifact_dir}" "${optimizer_run_dir}" "${token_usage_json}" "${start_time}" "${end_time}" "${opt_args}" >> "${SUMMARY_CSV}"

    echo "[${run_index}/${total_runs}] ${status} - ${setting_label} - ${dcp_name}"
    echo "  Console log: ${log_file}"
    if [[ -n "${token_usage_json}" ]]; then
      echo "  Token usage: ${token_usage_json}"
    fi
    echo
  done
done

echo "Branching sweep complete"
echo "  Passed:   ${ok}"
echo "  Failed:   ${failed}"
echo "  Summary:  ${SUMMARY_CSV}"

if [[ ${failed} -gt 0 ]]; then
  exit 1
fi

exit 0
