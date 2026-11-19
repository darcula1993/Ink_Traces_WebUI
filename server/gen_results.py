"""Generation tasks and their 生成历史 results share one life cycle (GEN-RESULT-LIFECYCLE-20261119).

User decisions 2026-11-19: a task in the trash hides its 生成历史 results (``media_library``
filters them by query; restoring the task brings them back), and permanently deleting a
task or emptying the trash deletes those results from the library exactly like a library
deletion (tombstones, "已删除" placeholders on canvases, references/mentions removed,
character images unlinked, group members kept as placeholders, old routes 410). Copies out
of 生成历史 are independent items and are never touched; task cards do not change otherwise.

A library item belongs to the tasks linked to it (``media.source_task_id`` plus every
``task_assets.media_id``) only while it is in 生成历史/<kind>; it is deleted when every linked
task still existing is part of the batch being deleted.
"""
import uuid

import canvas_store as store
import media_library as ml
import tasks as task_db

PREVIEW_ITEMS = 50


def _marks(values):
    return ','.join('?' for _ in values)


def owned_media(db, task_ids):
    """Ids of 生成历史 items that go away with ``task_ids`` (no other linked task remains)."""
    task_ids = sorted(set(task_ids))
    if not task_ids:
        return []
    found = []
    gen = ml.GENERATED_FOLDERS
    for start in range(0, len(task_ids), 400):
        chunk = task_ids[start:start + 400]
        rows = db.execute(
            f'''SELECT id FROM media WHERE folder_id IN ({_marks(gen)}) AND (source_task_id IN ({_marks(chunk)})
                OR id IN (SELECT media_id FROM task_assets WHERE media_id IS NOT NULL AND task_id IN ({_marks(chunk)})))''',
            (*gen, *chunk, *chunk)).fetchall()
        found += [r[0] for r in rows]
    batch, owned = set(task_ids), []
    for media_id in dict.fromkeys(found):
        linked = {r[0] for r in db.execute(
            '''SELECT t.id FROM tasks t WHERE t.id IN (SELECT source_task_id FROM media WHERE id=? UNION
               SELECT task_id FROM task_assets WHERE media_id=?)''', (media_id, media_id))}
        if linked <= batch:
            owned.append(media_id)
    return owned


def _eligible(db, task_ids, task_type=None):
    """(eligible rows, skipped {id: reason}, missing ids): the permanent-deletion rules."""
    eligible, skipped, missing = [], {}, []
    for task_id in task_ids:
        row = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not row or (task_type and row['type'] != task_type):
            missing.append(task_id)
        elif row['deleted_at'] is None:
            skipped[task_id] = 'not_in_trash'
        elif row['status'] == 'cancel_requested':
            skipped[task_id] = 'cancel_requested'
        elif row['lease_owner']:
            skipped[task_id] = 'leased'
        else:
            eligible.append(row)
    return eligible, skipped, missing


def _copies_kept(db, media_ids):
    if not media_ids:
        return 0
    gen = ml.GENERATED_FOLDERS
    total = 0
    for start in range(0, len(media_ids), 400):
        chunk = media_ids[start:start + 400]
        total += db.execute(
            f'''SELECT COUNT(*) FROM media WHERE (folder_id IS NULL OR folder_id NOT IN ({_marks(gen)}))
                AND sha256 IN (SELECT sha256 FROM media WHERE id IN ({_marks(chunk)}))''', (*gen, *chunk)).fetchone()[0]
    return total


def _media_summary(summary, copies):
    items = summary['items']
    return {'count': len(items), 'items': items[:PREVIEW_ITEMS],
            'kinds': {kind: sum(1 for i in items if i['kind'] == kind) for kind in ml.KINDS},
            'affected_workflows': summary['affected_workflows'], 'media_groups': summary['media_groups'],
            'characters': summary['characters'], 'asset_groups': summary['asset_groups'], 'copies_kept': copies}


EMPTY_MEDIA = {'count': 0, 'items': [], 'kinds': {k: 0 for k in ml.KINDS}, 'affected_workflows': [], 'media_groups': [],
               'characters': [], 'asset_groups': 0, 'copies_kept': 0}


def trashed_ids(task_type):
    ids, after = [], 0
    while True:
        batch = task_db.list_trashed_task_ids(task_type, after, 500)
        if not batch:
            return ids
        ids += batch
        after = batch[-1]


def preview(task_ids, task_type=None):
    """What a permanent deletion of ``task_ids`` would remove from the library (read only)."""
    db = task_db.get_db()
    owns = not db.in_transaction
    if owns:
        db.execute('BEGIN')
    try:
        eligible, skipped, missing = _eligible(db, task_ids, task_type)
        ids = [r['id'] for r in eligible]
        media_ids = owned_media(db, ids)
        media = _media_summary(ml._plan(db, media_ids)['summary'], _copies_kept(db, media_ids)) if media_ids else EMPTY_MEDIA
        return {'task_ids': ids, 'tasks': len(ids), 'skipped_ids': list(skipped), 'skipped': skipped,
                'missing_ids': missing, 'media': media}
    finally:
        if owns:
            db.rollback()


def purge(task_ids, task_type=None):
    """Permanently delete eligible trashed tasks and their 生成历史 results in one transaction.

    Eligibility is re-checked under BEGIN IMMEDIATE (a concurrent restore, cancel or lease
    wins: the task is skipped). Library files are staged inside the transaction and removed
    after commit; task files (outside the library) are removed last, as before.
    """
    staged, token = [], uuid.uuid4().hex
    purged = []
    try:
        with store.write_transaction() as db:
            eligible, skipped, missing = _eligible(db, task_ids, task_type)
            ids = [r['id'] for r in eligible]
            media_ids = owned_media(db, ids)
            plan = ml._plan(db, media_ids) if media_ids else None
            if plan:
                ml.apply_delete(db, plan, staged, token)
            for row in eligible:
                assets = [dict(a) for a in db.execute('SELECT * FROM task_assets WHERE task_id=?', (row['id'],)).fetchall()]
                db.execute('DELETE FROM tasks WHERE id=?', (row['id'],))
                purged.append((task_db._row_to_dict(row), assets))
    except BaseException:
        ml.undo_delete(staged)
        raise
    files = ml.finish_delete(staged)
    from task_media import remove_task_files
    for task, assets in purged:
        remove_task_files(task, assets)
    return {'deleted_ids': [task['id'] for task, _ in purged], 'skipped': skipped, 'missing_ids': missing,
            'media_deleted_ids': [r['id'] for r in plan['rows']] if plan else [], 'media_files_removed': files,
            'affected_workflows': plan['summary']['affected_workflows'] if plan else []}
