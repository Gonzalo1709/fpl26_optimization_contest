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

# ----------------------------------------------------------------------
# Upload settings
# ----------------------------------------------------------------------
# Set this to enable uploads by default, for example:
#   RCLONE_DEST="gdrive:fpl26-results"
#
# You can also override this from the command line with:
#   --upload-target gdrive:fpl26-results
#
# If empty, upload is disabled.
RCLONE_DEST=""

# Require the rclone destination folder to already exist.
# Recommended: true
#
# This prevents accidentally uploading to a typo path like:
#   gdrive:fpl26-resutls
#
# If you want rclone to create the destination automatically, set this to false.
REQUIRE_RCLONE_DEST_EXISTS="true"

# Extra rclone flags used during upload.
# --progress is nice interactively, mildly noisy in CI.
RCLONE_UPLOAD_FLAGS=(--progress)

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Run dcp_optimizer.py on every .dcp file in a benchmark directory and save logs.

Options:
  --bench-dir <path>        Benchmark directory containing .dcp files
                            (default: ${DEFAULT_BENCH_DIR})

  --logs-dir <path>         Directory where run logs should be written
                            (default: ${LOG_DIR})

  --mode <mode>             Execution mode: test | optimizer
                            (default: test)

  --max-nets <n>            Max nets for --test mode
                            (default: 5)

  --python <bin>            Python executable to use
                            (default: python3)

  --upload-target <target>  Optional rclone destination, e.g.
                            gdrive:fpl26-results

                            If provided, the script compresses the run logs
                            into a .tar.gz archive and uploads the archive.

  -h, --help                Show this help

Examples:
  $(basename "$0")
  $(basename "$0") --bench-dir "${SCRIPT_DIR}/../fpl26_contest_benchmarks" --mode test
  $(basename "$0") --mode optimizer --logs-dir "${SCRIPT_DIR}/batch_logs/full_run"
  $(basename "$0") --mode test --upload-target gdrive:fpl26-results
  $(basename "$0") --mode optimizer --upload-target gdrive:fpl26-results
EOF
}

error_exit() {
  echo "Error: $*" >&2
  exit 1
}

join_rclone_path() {
  local base="$1"
  local name="$2"

  base="${base%/}"

  if [[ "${base}" == *: ]]; then
    printf '%s%s\n' "${base}" "${name}"
  else
    printf '%s/%s\n' "${base}" "${name}"
  fi
}

validate_rclone_destination() {
  local destination="$1"
  local remote_name
  local remote_with_colon

  if [[ -z "${destination}" ]]; then
    return 0
  fi

  if ! command -v rclone >/dev/null 2>&1; then
    cat >&2 <<EOF
Error: upload target was provided, but rclone is not installed.

Install it with:
  sudo apt update
  sudo apt install rclone

Then configure your remote with:
  rclone config

Example upload target:
  gdrive:fpl26-results
EOF
    exit 1
  fi

  if [[ "${destination}" != *:* ]]; then
    cat >&2 <<EOF
Error: invalid rclone destination: ${destination}

Rclone destinations must look like:
  remote:path

Example:
  gdrive:fpl26-results
EOF
    exit 1
  fi

  remote_name="${destination%%:*}"
  remote_with_colon="${remote_name}:"

  if ! rclone listremotes | grep -Fxq "${remote_with_colon}"; then
    cat >&2 <<EOF
Error: rclone remote is not configured: ${remote_with_colon}

Configured remotes are:
$(rclone listremotes 2>/dev/null || true)

Create the remote with:
  rclone config

Example:
  remote name: gdrive
  upload target: gdrive:fpl26-results
EOF
    exit 1
  fi

  if [[ "${REQUIRE_RCLONE_DEST_EXISTS}" == "true" ]]; then
    if ! rclone lsf "${destination}" --max-depth 1 >/dev/null 2>&1; then
      cat >&2 <<EOF
Error: rclone destination does not exist or is not accessible: ${destination}

Check it with:
  rclone lsf "${destination}" --max-depth 1

If the folder does not exist, create it with:
  rclone mkdir "${destination}"

If you are using Google Drive with the restricted drive.file scope,
make sure the folder was created by rclone, not manually in the browser.
Because naturally, cloud permissions needed a philosophical subplot.
EOF
      exit 1
    fi
  fi
}

upload_results() {
  local archive_file
  local archive_name
  local remote_archive_path
  local upload_exit_code

  if [[ -z "${RCLONE_DEST}" ]]; then
    return 0
  fi

  archive_file="${LOG_DIR}.tar.gz"
  archive_name="$(basename "${archive_file}")"
  remote_archive_path="$(join_rclone_path "${RCLONE_DEST}" "${archive_name}")"

  echo "Compressing results"
  echo "  Source directory: ${LOG_DIR}"
  echo "  Archive:          ${archive_file}"

  if ! tar -czf "${archive_file}" -C "${LOG_ROOT}" "$(basename "${LOG_DIR}")"; then
    error_exit "failed to create archive: ${archive_file}"
  fi

  echo
  echo "Uploading compressed results"
  echo "  Source:      ${archive_file}"
  echo "  Destination: ${remote_archive_path}"

  rclone copyto "${archive_file}" "${remote_archive_path}" "${RCLONE_UPLOAD_FLAGS[@]}"
  upload_exit_code=$?

  if [[ ${upload_exit_code} -ne 0 ]]; then
    cat >&2 <<EOF
Error: rclone upload failed with exit code ${upload_exit_code}

Source:
  ${archive_file}

Destination:
  ${remote_archive_path}

Try manually:
  rclone copyto "${archive_file}" "${remote_archive_path}" --progress
EOF
    exit 1
  fi

  echo "Upload complete"
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
    --upload-target)
      RCLONE_DEST="$2"
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

# Validate upload setup before spending potentially hours running benchmarks.
# Humanity may be doomed, but at least we can fail early.
validate_rclone_destination "${RCLONE_DEST}"

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

if [[ -n "${RCLONE_DEST}" ]]; then
  echo "  Upload target:  ${RCLONE_DEST}"
  echo "  Upload format:  tar.gz archive"
else
  echo "  Upload target:  disabled"
fi

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
echo

upload_results

if [[ ${failed} -gt 0 ]]; then
  exit 1
fi

exit 0
