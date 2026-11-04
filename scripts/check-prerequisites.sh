#!/usr/bin/env bash
# Read-only prerequisites. No downloads, installs, account access or secret output.
set -uo pipefail
failures=0
probe() {
  local label="$1"
  shift
  printf '\n%s\n' "$label"
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'MISSING: %s\n' "$1"
    failures=$((failures + 1))
    return
  fi
  if ! "$@"; then
    printf 'FAILED: %s\n' "$label"
    failures=$((failures + 1))
  fi
}
printf 'Retail Analytics Automation: read-only prerequisite check\n'
printf 'UTC: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
printf 'OS/kernel: %s\n' "$(uname -sr)"
printf 'Architecture: %s\n' "$(uname -m)"
if [[ -r /proc/meminfo ]]; then
  awk '/MemTotal:|MemAvailable:/ {print $1, $2, $3}' /proc/meminfo
elif command -v sysctl >/dev/null 2>&1; then
  sysctl hw.memsize 2>/dev/null || true
fi
df -Pk . | awk 'NR == 2 {print "Filesystem free KiB:", $4}'
probe 'Git' git --version
probe 'Docker client' docker --version
probe 'Docker Compose' docker compose version
if command -v docker >/dev/null 2>&1; then
  printf '\nDocker daemon and container OS\n'
  if docker_os=$(docker info --format '{{.OSType}}' 2>/dev/null); then
    printf 'Container OS: %s\n' "$docker_os"
    if [[ "$docker_os" != 'linux' ]]; then
      printf 'FAILED: use Linux containers for this project.\n'
      failures=$((failures + 1))
    fi
  else
    printf 'FAILED: Docker daemon unavailable or inaccessible.\n'
    failures=$((failures + 1))
  fi
fi
printf '\nBlocking prerequisite findings: %s\n' "$failures"
printf 'This does not verify G0 data, model, deployment, or resource adequacy.\n'
if [[ "$failures" -gt 0 ]]; then exit 1; fi
