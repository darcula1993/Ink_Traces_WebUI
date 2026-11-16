#!/usr/bin/env python3
"""LIBRARY-GLOBAL-20261116: migrate old library sources into the global media library.

Default is a dry run: the database is opened read-only and only the reviewable list is
printed (counts/bytes per target, skips, dedup groups, affected documents). Nothing is
written. Steps for a real migration (方案 v2 §3; production needs separate approval):

  1. stop Web + Worker after checking there is no active task / group run;
  2. --make-backup DIR   sqlite .backup + hard-link snapshot of canvas_assets and output
                         + sha256sums.txt + manifest.json (keep 7 days, delete only after
                         the user confirms);
  3. dry run (default), review the list;
  4. --apply --backup-dir DIR   refuses on active tasks/runs, a live Worker heartbeat, or a
                         missing/stale backup; idempotent and resumable (rerun after any
                         interruption with the same backup);
  5. --verify            re-check hashes and that every active document validates.

Rollback: stop services; run --new-since <finished_at> --export-dir NEW_DIR to export what
changed after the migration (new media files copied to NEW_DIR/files, plus moves, renames,
deletions, new/changed folders and groups in NEW_DIR/changes.json); restore tasks.db from DIR/tasks.db and canvas_assets/output from the snapshot
(hard links: copy back with `cp -al` or rsync); roll back code. Old tables are kept, only
tags, project folders and canvas_local_sources rows are deleted (they are in the backup).

Copies held only by deleted (archived) canvases/projects are not imported (user decision
2026-11-16): the list shows them as "清理"; --apply deletes those files and their old rows
(rows whose file is already missing are just removed). The backup snapshot keeps them for
rollback. --include-archived imports them instead and nothing is purged.
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / 'server'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--db', required=True, help='tasks.db path')
    parser.add_argument('--asset-root', help='canvas_assets directory (default: <db dir>/canvas_assets)')
    parser.add_argument('--output-dir', help='task output directory for the backup (default: <db dir>/output)')
    parser.add_argument('--include-archived', action='store_true', help='import content only held by archived canvases/projects instead of purging it')
    parser.add_argument('--verify-hashes', action='store_true', help='dry run: re-hash every registered file')
    parser.add_argument('--json', help='write the full plan/summary as JSON to this path')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--make-backup', metavar='DIR', help='create a backup into a new directory and exit')
    mode.add_argument('--apply', action='store_true', help='execute the migration (needs --backup-dir)')
    mode.add_argument('--verify', action='store_true', help='post-migration checks')
    mode.add_argument('--new-since', metavar='ISO_TIME', help='rollback export: library changes after the migration finished at this time')
    parser.add_argument('--export-dir', help='with --new-since: new or empty directory outside the asset root for new media files and changes.json')
    parser.add_argument('--backup-dir', help='backup made by --make-backup')
    args = parser.parse_args(argv)
    if args.export_dir and not args.new_since:
        parser.error('--export-dir 只能与 --new-since 一起使用')

    db_path = Path(args.db).absolute()
    if not db_path.is_file():
        parser.error(f'数据库不存在：{db_path}')
    asset_root = Path(args.asset_root).absolute() if args.asset_root else db_path.parent / 'canvas_assets'
    output_dir = Path(args.output_dir).absolute() if args.output_dir else db_path.parent / 'output'
    # Point the server modules at this database before they are imported.
    os.environ['NANOBANANA_DB_PATH'] = str(db_path)
    os.environ['NANOBANANA_CANVAS_ASSET_DIR'] = str(asset_root)
    sys.path.insert(0, str(SERVER))
    import media_migrate as migrate

    if args.make_backup:
        manifest = migrate.make_backup(db_path, asset_root, output_dir, args.make_backup)
        print(json.dumps(manifest, ensure_ascii=False, indent=1))
        return 0
    if args.apply or args.verify or args.new_since:
        import tasks
        tasks.init_db()
        db = tasks.get_db()
        if args.new_since:
            try:
                report = migrate.changes_since(db, args.new_since, args.export_dir, asset_root)
            except migrate.MigrationError as error:
                print('拒绝执行：' + str(error), file=sys.stderr)
                return 2
            print(json.dumps(report, ensure_ascii=False, indent=1))
            return 0
        if args.verify:
            problems = migrate.verify(db)
            print('\n'.join(problems) or '校验通过')
            return 1 if problems else 0
        try:
            report = migrate.apply(db_path, args.backup_dir, include_archived=args.include_archived)
        except migrate.MigrationError as error:
            print('拒绝执行：' + str(error), file=sys.stderr)
            return 2
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0 if not report['problems'] and not report['documents_failed'] else 1

    db = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    plan = migrate.build_plan(db, asset_root, include_archived=args.include_archived, verify_hashes=args.verify_hashes)
    summary = migrate.summarize(plan)
    print(migrate.format_summary(summary))
    blockers, warnings, _ = migrate.preflight(db, db_path, args.backup_dir)
    for line in warnings:
        print('警告：' + line)
    for line in blockers:
        print('执行前需处理：' + line)
    if args.json:
        Path(args.json).write_text(json.dumps({'summary': summary, 'plan': plan}, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
