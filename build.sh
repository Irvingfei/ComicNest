#!/bin/bash
# Build ComicNest for TOS 7.
#
# Usage:
#   ./build.sh                 # x86_64
#   ./build.sh aarch64         # aarch64
#   ./build.sh x86_64 --no-deb # assemble the package tree only

set -euo pipefail

PLATFORM="${1:-x86_64}"
shift || true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON=python
else
    echo "error: python 3.10 or newer is required" >&2
    exit 1
fi

case "$PLATFORM" in
    x86_64|aarch64) ;;
    *)
        echo "error: unsupported platform '$PLATFORM' (expected x86_64 or aarch64)" >&2
        exit 1
        ;;
esac

exec "$PYTHON" tools/build.py --platform "$PLATFORM" "$@"
