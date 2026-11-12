"""Storage and SQLite maintenance commands."""

import argparse
import json

import storage
import tasks as task_db


def compact_task_results():
    """Remove legacy inline Base64 images while preserving local/remote metadata."""
    tasks, _ = task_db.list_tasks(limit=None)
    changed = 0
    for task in tasks:
        result = task.get('result')
        if not isinstance(result, dict):
            continue
        images = result.get('images')
        if not isinstance(images, list) or not any(
            isinstance(item, str) and item.startswith('data:') for item in images
        ):
            continue
        result.pop('images', None)
        task_db.update_task(task['id'], result=result)
        changed += 1
    return changed


def run_cleanup(grace_hours):
    return {
        'expired_assets': storage.cleanup_expired_assets(),
        'orphans': storage.cleanup_orphans(grace_seconds=max(0, grace_hours) * 60 * 60),
    }


def run_vacuum():
    before = task_db.db_stats()
    checkpoint = task_db.checkpoint(truncate=True)
    task_db.vacuum()
    after = task_db.db_stats()
    return {'before': before, 'checkpoint': checkpoint, 'after': after}


def main():
    parser = argparse.ArgumentParser(description='Nanobanana backend maintenance')
    parser.add_argument('action', choices=('cleanup', 'compact', 'vacuum', 'all'))
    parser.add_argument('--grace-hours', type=int, default=24)
    args = parser.parse_args()

    result = {}
    if args.action in ('cleanup', 'all'):
        result['cleanup'] = run_cleanup(args.grace_hours)
    if args.action in ('compact', 'all'):
        result['compacted_results'] = compact_task_results()
    if args.action in ('vacuum', 'all'):
        result['vacuum'] = run_vacuum()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
