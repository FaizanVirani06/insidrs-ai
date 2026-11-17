#!/usr/bin/env bash
# Run one research step on the droplet, from the repo root:
#
#   research/run.sh research.analysis.study3 --stage dev
#
# - Refuses to start if any tracked file has uncommitted changes.
# - Passes the commit hash into the container (the analysis prints it and refuses without it).
# - Appends everything printed to one summary file you can paste:
#   $SUMMARY (default research/output/summary.txt).
# - Forwards HOLDOUT_CONFIRM only if you set it on the command line yourself.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ $# -lt 1 ]; then
  echo "usage: research/run.sh <python module> [args...]" >&2
  exit 2
fi
dirty="$(git status --porcelain --untracked-files=no)"
if [ -n "$dirty" ]; then
  echo "Refusing to run: uncommitted changes to tracked files:" >&2
  echo "$dirty" >&2
  exit 1
fi
commit="$(git rev-parse HEAD)"
SUMMARY="${SUMMARY:-research/output/summary.txt}"
mkdir -p "$(dirname "$SUMMARY")"

env_args=(-e "RESEARCH_GIT_COMMIT=$commit" -e "RESEARCH_TREE_CLEAN=1")
if [ -n "${HOLDOUT_CONFIRM:-}" ]; then
  env_args+=(-e "HOLDOUT_CONFIRM=$HOLDOUT_CONFIRM")
fi

{
  echo
  echo "################ $(date -u '+%Y-%m-%d %H:%M:%S UTC')  research/run.sh $*"
  echo "################ commit $commit"
} | tee -a "$SUMMARY"

set +e
docker compose -f docker-compose.prod.yml -f docker-compose.research.yml run --rm -T "${env_args[@]}" \
  research python -m research.runner "$@" < /dev/null 2>&1 \
  | grep --line-buffered -v -e "the attribute \`version\` is obsolete" -e "^\[+\]" -e "Container insidersproject-" -e "✔ Container" \
  | tee -a "$SUMMARY"
status=${PIPESTATUS[0]}
set -e
echo "################ exit status $status" | tee -a "$SUMMARY"
exit "$status"
