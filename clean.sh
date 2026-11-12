#!/usr/bin/env bash
# Remove regenerable development caches only, never runtime data or build output.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "${1:-}" in
    ''|--dry-run) ;;
    *) echo "Usage: $0 [--dry-run]" >&2; exit 2 ;;
esac
if [ "$#" -gt 1 ]; then
    echo "Usage: $0 [--dry-run]" >&2
    exit 2
fi

python3 - "$PROJECT_ROOT" "${1:-}" <<'PY'
import os
from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1]).resolve()
dry_run = sys.argv[2] == '--dry-run'
candidates = [root / name for name in (
    '.pytest_cache', 'client/test-results', 'client/playwright-report',
)]
# Search only first-party Python code. Never traverse assets or dependencies.
for name in ('server', 'deploy'):
    base = root / name
    if base.is_symlink() or not base.is_dir():
        continue
    for directory, dirs, _files in os.walk(base, followlinks=False):
        dirs[:] = [d for d in dirs if d not in {'node_modules', 'uploads', '.venv', 'venv'}
                   and not (Path(directory) / d).is_symlink()]
        if '__pycache__' in dirs:
            candidates.append(Path(directory) / '__pycache__')
            dirs.remove('__pycache__')

removed = 0
for path in candidates:
    # Also reject symlinked ancestors, such as a linked client directory.
    if path.resolve() != path or not path.is_dir():
        continue
    print(('Would remove: ' if dry_run else 'Removing: ') + str(path.relative_to(root)))
    if not dry_run:
        shutil.rmtree(path)
    removed += 1
print(f'{"Previewed" if dry_run else "Removed"} {removed} cache directories.')
print('Runtime data, configuration, logs, dependencies and client/dist are preserved.')
PY
