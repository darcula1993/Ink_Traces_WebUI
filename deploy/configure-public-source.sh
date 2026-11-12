#!/bin/sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON=${PYTHON:-python3}

case " ${*:-} " in
    *" --check "*|*" --dry-run "*)
        exec "$PYTHON" "$PROJECT_ROOT/deploy/configure_public_source.py" "$@"
        ;;
esac

if [ "$(id -u)" -eq 0 ]; then
    exec "$PYTHON" "$PROJECT_ROOT/deploy/configure_public_source.py" "$@"
fi

if command -v sudo >/dev/null 2>&1; then
    exec sudo "$PYTHON" "$PROJECT_ROOT/deploy/configure_public_source.py" "$@"
fi

echo "Public source deployment requires root privileges (sudo was not found)." >&2
exit 1
