#!/bin/bash
# Harbor verifier: runs acceptance tests from workspace (in-repo TDD contract).
set -euo pipefail

SOURCE_DIR="${SOURCE_DIR:-/app/source}"
PYTEST_ARGS="${PYTEST_ARGS:--rA}"

if [ ! -d "$SOURCE_DIR" ]; then
  echo "Error: SOURCE_DIR not found: $SOURCE_DIR" >&2
  exit 1
fi

mkdir -p /logs/verifier 2>/dev/null || true

export PYTHONPATH="${SOURCE_DIR}:${PYTHONPATH:-}"

set +e
python3 -m pytest "${SOURCE_DIR}/tests/acceptance/" ${PYTEST_ARGS} -p no:cacheprovider
PYTEST_EXIT=$?
set -e

if [ -d /logs/verifier ]; then
  if [ "$PYTEST_EXIT" -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
  else
    echo 0 > /logs/verifier/reward.txt
  fi
fi

exit "$PYTEST_EXIT"
