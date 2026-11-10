#!/usr/bin/env bash
# One line saying what this script does.
#
# Usage: script.sh [-n] [-v] <input> [output]
#   -n   dry run: print what would be done
#   -v   verbose
#   -h   help
set -euo pipefail

readonly SCRIPT_NAME=$(basename "$0")
DRY_RUN=0
VERBOSE=0

usage() { sed -n '2,/^set /{/^set /d;s/^# \{0,1\}//;p}' "$0"; }
log()   { printf '%s\n' "$*" >&2; }
debug() { [ "$VERBOSE" -eq 1 ] && log "debug: $*" || true; }
die()   { log "$SCRIPT_NAME: error: $*"; exit 1; }
need()  { command -v "$1" >/dev/null 2>&1 || die "'$1' is required but not installed"; }

# Run a command, or only print it in dry-run mode.
run() {
  if [ "$DRY_RUN" -eq 1 ]; then log "would run: $*"; else debug "running: $*"; "$@"; fi
}

TMP_DIR=""
cleanup() { [ -n "$TMP_DIR" ] && rm -rf -- "$TMP_DIR"; }
trap cleanup EXIT
trap 'die "interrupted"' INT TERM

main() {
  while getopts ":nvh" opt; do
    case "$opt" in
      n) DRY_RUN=1 ;;
      v) VERBOSE=1 ;;
      h) usage; exit 0 ;;
      :) die "option -$OPTARG needs a value" ;;
      *) die "unknown option -$OPTARG (see -h)" ;;
    esac
  done
  shift $((OPTIND - 1))

  [ $# -ge 1 ] || { usage >&2; exit 2; }
  local input=$1
  local output=${2:-"$input.out"}
  [ -e "$input" ] || die "input not found: $input"

  TMP_DIR=$(mktemp -d)
  debug "temp dir: $TMP_DIR"

  # --- the actual work goes here ---
  run cp -- "$input" "$output"
  log "done: $output"
}

main "$@"
