"""SQLite persistence for generation tasks, assets, prompts, and workers."""

import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
DB_PATH = os.environ.get('NANOBANANA_DB_PATH', os.path.join(PROJECT_ROOT, 'tasks.db'))
_local = threading.local()
ACTIVE_TASK_STATUSES = ('submitting', 'preparing', 'pending', 'processing', 'cancel_requested')
TERMINAL_TASK_STATUSES = ('succeeded', 'failed', 'cancelled')
TASK_SORTS = {
    'newest': 't.id DESC',
    'oldest': 't.id ASC',
    'updated': 't.updated_at DESC, t.id DESC',
}


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def _future(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def close_db():
    conn = getattr(_local, 'conn', None)
    if conn is not None:
        conn.close()
        del _local.conn


def configure(db_path):
    """Point this module at another database, primarily for tests and tooling."""
    global DB_PATH
    close_db()
    DB_PATH = str(db_path)
    init_db()


def get_db():
    """Return a thread-local connection configured for concurrent local workers."""
    conn = getattr(_local, 'conn', None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=5000')
        conn.execute('PRAGMA wal_autocheckpoint=256')
        conn.execute('PRAGMA journal_size_limit=1048576')
        _local.conn = conn
    return conn


def _ensure_columns(db, table, columns):
    existing = {row['name'] for row in db.execute(f'PRAGMA table_info({table})')}
    for name, definition in columns.items():
        if name not in existing:
            db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')


def init_db():
    """Create the current schema and migrate older databases in place."""
    db = get_db()
    db.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            prompt TEXT,
            params TEXT,
            provider TEXT,
            external_task_id TEXT,
            result TEXT,
            error TEXT,
            output_dir TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            updated_at TEXT,
            progress INTEGER NOT NULL DEFAULT 0,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            next_run_at TEXT,
            lease_owner TEXT,
            lease_until TEXT,
            favorite INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT,
            retry_of INTEGER
        )
    ''')
    _ensure_columns(db, 'tasks', {
        'updated_at': 'TEXT',
        'progress': 'INTEGER NOT NULL DEFAULT 0',
        'attempt_count': 'INTEGER NOT NULL DEFAULT 0',
        'next_run_at': 'TEXT',
        'lease_owner': 'TEXT',
        'lease_until': 'TEXT',
        'favorite': 'INTEGER NOT NULL DEFAULT 0',
        'deleted_at': 'TEXT',
        'retry_of': 'INTEGER',
    })
    db.execute('''
        CREATE TABLE IF NOT EXISTS task_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            kind TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE,
            mime_type TEXT,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE SET NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS worker_heartbeats (
            worker_id TEXT PRIMARY KEY,
            pid INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS prompts (
            id INTEGER PRIMARY KEY,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS workspace_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS favorite_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            color TEXT NOT NULL DEFAULT 'green',
            position INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS task_favorite_groups (
            task_id INTEGER NOT NULL,
            group_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(task_id, group_id),
            FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
            FOREIGN KEY(group_id) REFERENCES favorite_groups(id) ON DELETE CASCADE
        )
    ''')
    search_exists = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'task_search'"
    ).fetchone()
    db.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS task_search USING fts5(
            prompt,
            provider,
            content='tasks',
            content_rowid='id',
            tokenize='unicode61'
        )
    ''')
    db.execute('''
        CREATE TRIGGER IF NOT EXISTS tasks_search_insert AFTER INSERT ON tasks BEGIN
            INSERT INTO task_search(rowid, prompt, provider)
            VALUES (new.id, COALESCE(new.prompt, ''), COALESCE(new.provider, ''));
        END
    ''')
    db.execute('''
        CREATE TRIGGER IF NOT EXISTS tasks_search_delete AFTER DELETE ON tasks BEGIN
            INSERT INTO task_search(task_search, rowid, prompt, provider)
            VALUES ('delete', old.id, COALESCE(old.prompt, ''), COALESCE(old.provider, ''));
        END
    ''')
    db.execute('''
        CREATE TRIGGER IF NOT EXISTS tasks_search_update AFTER UPDATE OF prompt, provider ON tasks BEGIN
            INSERT INTO task_search(task_search, rowid, prompt, provider)
            VALUES ('delete', old.id, COALESCE(old.prompt, ''), COALESCE(old.provider, ''));
            INSERT INTO task_search(rowid, prompt, provider)
            VALUES (new.id, COALESCE(new.prompt, ''), COALESCE(new.provider, ''));
        END
    ''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(type)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_tasks_queue ON tasks(status, next_run_at, lease_until)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_tasks_type_status_id ON tasks(type, status, id DESC)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_tasks_favorite ON tasks(favorite, id DESC)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_tasks_deleted ON tasks(deleted_at, id DESC)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_tasks_deleted_updated ON tasks(deleted_at, updated_at DESC, id DESC)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_tasks_type_deleted_id ON tasks(type, deleted_at, id DESC)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_tasks_type_deleted_updated ON tasks(type, deleted_at, updated_at DESC, id DESC)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_tasks_type_deleted_favorite ON tasks(type, deleted_at, favorite, id DESC)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_assets_task ON task_assets(task_id)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_assets_expiry ON task_assets(expires_at)')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_external ON tasks(provider, external_task_id) WHERE external_task_id IS NOT NULL')
    db.execute('CREATE INDEX IF NOT EXISTS idx_task_favorite_groups_group ON task_favorite_groups(group_id, task_id)')
    now = utcnow()
    db.execute('UPDATE tasks SET updated_at = COALESCE(updated_at, created_at, ?)', (now,))
    if not search_exists:
        db.execute("INSERT INTO task_search(task_search) VALUES ('rebuild')")
    db.commit()


def create_task(task_type, prompt, params, provider=None, external_task_id=None, status='pending', retry_of=None):
    now = utcnow()
    db = get_db()
    cur = db.execute(
        '''INSERT INTO tasks
           (type, status, prompt, params, provider, external_task_id, created_at, updated_at, next_run_at, retry_of)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (task_type, status, prompt, _json(params), provider, external_task_id, now, now, now, retry_of)
    )
    db.commit()
    return cur.lastrowid


def update_task(task_id, **kwargs):
    allowed = {
        'status', 'params', 'result', 'error', 'provider', 'external_task_id',
        'output_dir', 'completed_at', 'updated_at', 'progress', 'attempt_count',
        'next_run_at', 'lease_owner', 'lease_until', 'favorite', 'deleted_at',
        'retry_of',
    }
    fields = {key: value for key, value in kwargs.items() if key in allowed}
    if not fields:
        return False
    for key in ('params', 'result'):
        if key in fields and fields[key] is not None and not isinstance(fields[key], str):
            fields[key] = _json(fields[key])
    fields.setdefault('updated_at', utcnow())
    sets = ', '.join(f'{key} = ?' for key in fields)
    values = list(fields.values()) + [task_id]
    cur = get_db().execute(f'UPDATE tasks SET {sets} WHERE id = ?', values)
    get_db().commit()
    return cur.rowcount > 0


def complete_task(task_id, result, output_dir=None):
    now = utcnow()
    cursor = get_db().execute(
        '''UPDATE tasks
           SET status = 'succeeded', result = ?, error = NULL, output_dir = ?,
               progress = 100, completed_at = ?, updated_at = ?, next_run_at = NULL,
               lease_owner = NULL, lease_until = NULL
           WHERE id = ? AND deleted_at IS NULL
             AND status NOT IN ('cancel_requested', 'cancelled', 'failed', 'succeeded')''',
        (_json(result), output_dir, now, now, task_id),
    )
    get_db().commit()
    return cursor.rowcount > 0


def fail_task(task_id, error, result=None):
    now = utcnow()
    cursor = get_db().execute(
        '''UPDATE tasks
           SET status = 'failed', error = ?,
               result = CASE WHEN ? IS NULL THEN result ELSE ? END,
               completed_at = ?, updated_at = ?, next_run_at = NULL,
               lease_owner = NULL, lease_until = NULL
           WHERE id = ? AND deleted_at IS NULL
             AND status NOT IN ('cancel_requested', 'cancelled', 'failed', 'succeeded')''',
        (str(error), None if result is None else 1, None if result is None else _json(result), now, now, task_id),
    )
    get_db().commit()
    return cursor.rowcount > 0


def reschedule_task(task_id, delay_seconds, status='processing', error=None, progress=None):
    now = utcnow()
    cursor = get_db().execute(
        '''UPDATE tasks
           SET status = ?, completed_at = NULL, next_run_at = ?, updated_at = ?,
               lease_owner = NULL, lease_until = NULL,
               error = CASE WHEN ? IS NULL THEN error ELSE ? END,
               progress = CASE WHEN ? IS NULL THEN progress ELSE ? END
           WHERE id = ? AND deleted_at IS NULL
             AND status NOT IN ('cancel_requested', 'cancelled', 'failed', 'succeeded')''',
        (
            status, _future(delay_seconds), now,
            error, None if error is None else str(error),
            progress, None if progress is None else int(progress), task_id,
        ),
    )
    get_db().commit()
    return cursor.rowcount > 0


def get_task(task_id):
    row = get_db().execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    if not row:
        return None
    task = _row_to_dict(row)
    _attach_favorite_groups([task])
    return task


def get_task_statuses(task_ids):
    """Fetch polling fields for multiple tasks without params or favorite joins."""
    task_ids = list(dict.fromkeys(int(task_id) for task_id in task_ids))
    if not task_ids:
        return []
    placeholders = ','.join('?' for _ in task_ids)
    rows = get_db().execute(
        f'''SELECT id, type, status, result, error, progress, provider,
                   external_task_id, updated_at, deleted_at
            FROM tasks WHERE id IN ({placeholders})''',
        task_ids,
    ).fetchall()
    statuses = [_row_to_dict(row) for row in rows]
    order = {task_id: index for index, task_id in enumerate(task_ids)}
    statuses.sort(key=lambda task: order.get(int(task['id']), len(order)))
    return statuses


def get_task_by_external(provider, external_task_id):
    row = get_db().execute(
        '''SELECT * FROM tasks
           WHERE provider = ? AND external_task_id = ? AND deleted_at IS NULL
           ORDER BY id DESC LIMIT 1''',
        (provider, external_task_id),
    ).fetchone()
    if not row:
        return None
    task = _row_to_dict(row)
    _attach_favorite_groups([task])
    return task


def _fts_search_query(value):
    tokens = re.findall(r'[\w]+', str(value).lower(), flags=re.UNICODE)
    return ' AND '.join(f'"{token}"*' for token in tokens[:12])


def _task_filters(task_type=None, status=None, favorite=None, active=False, search=None,
                  deleted=False, favorite_group=None, ungrouped=False):
    clauses = []
    params = []
    if deleted is True:
        clauses.append('t.deleted_at IS NOT NULL')
    elif deleted is False:
        clauses.append('t.deleted_at IS NULL')
    if task_type:
        clauses.append('t.type = ?')
        params.append(task_type)
    if status:
        clauses.append('t.status = ?')
        params.append(status)
    if favorite is not None:
        clauses.append('t.favorite = ?')
        params.append(1 if favorite else 0)
    if active:
        placeholders = ','.join('?' for _ in ACTIVE_TASK_STATUSES)
        clauses.append(f't.status IN ({placeholders})')
        params.extend(ACTIVE_TASK_STATUSES)
    if favorite_group is not None:
        clauses.append('''EXISTS (
            SELECT 1 FROM task_favorite_groups tfg
            WHERE tfg.task_id = t.id AND tfg.group_id = ?
        )''')
        params.append(int(favorite_group))
    if ungrouped:
        clauses.append('t.favorite = 1')
        clauses.append('NOT EXISTS (SELECT 1 FROM task_favorite_groups tfg WHERE tfg.task_id = t.id)')
    if search:
        pattern = f'%{search.lower()}%'
        fts_query = _fts_search_query(search)
        if fts_query:
            candidate_queries = [
                'SELECT rowid FROM task_search WHERE task_search MATCH ?',
                '''SELECT search_tfg.task_id
                   FROM task_favorite_groups search_tfg
                   JOIN favorite_groups search_fg ON search_fg.id = search_tfg.group_id
                   WHERE LOWER(search_fg.name) LIKE ?''',
            ]
            params.extend([fts_query, pattern])
            if str(search).strip().isdigit():
                candidate_queries.append('SELECT id FROM tasks WHERE id = ?')
                params.append(int(str(search).strip()))
            clauses.append(f't.id IN ({" UNION ".join(candidate_queries)})')
        else:
            clauses.append('''(
                CAST(t.id AS TEXT) LIKE ?
                OR LOWER(COALESCE(t.prompt, '')) LIKE ?
                OR LOWER(COALESCE(t.provider, '')) LIKE ?
            )''')
            params.extend([pattern, pattern, pattern])
    return clauses, params


def _task_order(sort):
    return TASK_SORTS.get(sort, TASK_SORTS['newest'])


def _attach_favorite_groups(tasks):
    if not tasks:
        return tasks
    task_map = {int(task['id']): task for task in tasks}
    for task in tasks:
        task['favorite_groups'] = []
    placeholders = ','.join('?' for _ in task_map)
    rows = get_db().execute(
        f'''SELECT tfg.task_id, fg.id, fg.name, fg.color, fg.position
            FROM task_favorite_groups tfg
            JOIN favorite_groups fg ON fg.id = tfg.group_id
            WHERE tfg.task_id IN ({placeholders})
            ORDER BY fg.position ASC, fg.name COLLATE NOCASE ASC, fg.id ASC''',
        list(task_map),
    ).fetchall()
    for row in rows:
        task = task_map.get(int(row['task_id']))
        if task is not None:
            task['favorite_groups'].append({
                'id': row['id'], 'name': row['name'], 'color': row['color'],
                'position': row['position'],
            })
    return tasks


def list_tasks(task_type=None, status=None, limit=50, offset=0, summary=False,
               favorite=None, active=False, search=None, deleted=False,
               favorite_group=None, ungrouped=False, sort='newest'):
    if summary:
        result_summary = '''
            CASE WHEN json_valid(t.result) THEN json_object(
                'local_images', json_extract(t.result, '$.local_images'),
                'local_thumbnails', json_extract(t.result, '$.local_thumbnails'),
                'local_refs', json_extract(t.result, '$.local_refs'),
                'local_video', json_extract(t.result, '$.local_video'),
                'local_last_frame', json_extract(t.result, '$.local_last_frame'),
                'local_thumbnail', json_extract(t.result, '$.local_thumbnail'),
                'thinking', substr(COALESCE(json_extract(t.result, '$.thinking'), ''), 1, 100)
            ) ELSE NULL END AS result
        '''
        columns = (
            't.id, t.type, t.status, t.prompt, t.params, t.provider, t.external_task_id, '
            f'{result_summary}, error, output_dir, created_at, completed_at, '
            't.updated_at, t.progress, t.attempt_count, t.favorite, t.deleted_at, t.retry_of'
        )
    else:
        columns = 't.*'
    clauses, filter_params = _task_filters(
        task_type, status, favorite, active, search, deleted, favorite_group, ungrouped,
    )
    where = f' WHERE {" AND ".join(clauses)}' if clauses else ''
    query = f'SELECT {columns} FROM tasks t{where} ORDER BY {_task_order(sort)}'
    query_params = list(filter_params)
    if limit is not None:
        query += ' LIMIT ? OFFSET ?'
        query_params.extend([int(limit), int(offset)])
    rows = get_db().execute(query, query_params).fetchall()
    tasks = [_row_to_dict(row) for row in rows]
    _attach_favorite_groups(tasks)
    count = get_db().execute(
        f'SELECT COUNT(*) FROM tasks t{where}', filter_params,
    ).fetchone()[0]
    return tasks, count


def list_task_ids(task_type=None, favorite=None, active=False, search=None,
                  deleted=False, favorite_group=None, ungrouped=False, sort='newest'):
    clauses, params = _task_filters(
        task_type, None, favorite, active, search, deleted, favorite_group, ungrouped,
    )
    where = f' WHERE {" AND ".join(clauses)}' if clauses else ''
    query = f'SELECT t.id FROM tasks t{where} ORDER BY {_task_order(sort)}'
    return [row['id'] for row in get_db().execute(query, params).fetchall()]


def get_task_navigation(task_id=None, task_type=None, favorite=None, active=False,
                        search=None, deleted=False, favorite_group=None,
                        ungrouped=False, sort='newest'):
    clauses, params = _task_filters(
        task_type, None, favorite, active, search, deleted, favorite_group, ungrouped,
    )
    where = f' WHERE {" AND ".join(clauses)}' if clauses else ''
    order = _task_order(sort)
    query = f'''
        WITH ranked AS (
            SELECT
                t.id,
                ROW_NUMBER() OVER (ORDER BY {order}) AS position,
                COUNT(*) OVER () AS total,
                LAG(t.id) OVER (ORDER BY {order}) AS previous_id,
                LEAD(t.id) OVER (ORDER BY {order}) AS next_id,
                FIRST_VALUE(t.id) OVER (ORDER BY {order}) AS first_id,
                LAST_VALUE(t.id) OVER (
                    ORDER BY {order}
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                ) AS last_id
            FROM tasks t{where}
        )
        SELECT * FROM ranked
    '''
    query_params = list(params)
    if task_id is not None:
        query += ' WHERE id = ?'
        query_params.append(int(task_id))
    query += ' LIMIT 1'
    row = get_db().execute(query, query_params).fetchone()
    if not row:
        return {
            'position': 0,
            'total': 0,
            'previous_id': None,
            'next_id': None,
            'first_id': None,
            'last_id': None,
        }
    return {key: row[key] for key in row.keys() if key != 'id'}


def claim_next_task(worker_id, lease_seconds=900):
    """Atomically lease one due image execution or video polling task."""
    db = get_db()
    now = utcnow()
    try:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute(
            '''
            SELECT * FROM tasks
            WHERE completed_at IS NULL AND deleted_at IS NULL
              AND (next_run_at IS NULL OR next_run_at <= ?)
              AND (lease_until IS NULL OR lease_until < ?)
              AND (
                    (type = 'image' AND status = 'pending')
                 OR (type = 'video' AND status IN ('pending', 'processing') AND external_task_id IS NOT NULL)
              )
            ORDER BY CASE type WHEN 'video' THEN 0 ELSE 1 END, id ASC
            LIMIT 1
            ''',
            (now, now),
        ).fetchone()
        if row is None:
            db.commit()
            return None
        lease_until = _future(lease_seconds)
        cur = db.execute(
            '''UPDATE tasks
               SET status = 'processing', lease_owner = ?, lease_until = ?,
                   attempt_count = attempt_count + 1, updated_at = ?
               WHERE id = ? AND (lease_until IS NULL OR lease_until < ?)''',
            (worker_id, lease_until, now, row['id'], now),
        )
        if cur.rowcount != 1:
            db.rollback()
            return None
        db.commit()
        return get_task(row['id'])
    except Exception:
        db.rollback()
        raise


def release_worker_leases(worker_id):
    db = get_db()
    db.execute(
        '''UPDATE tasks
           SET status = CASE WHEN status = 'cancel_requested' THEN 'cancelled' ELSE status END,
               completed_at = CASE WHEN status = 'cancel_requested' THEN ? ELSE completed_at END,
               next_run_at = CASE WHEN status = 'cancel_requested' THEN NULL ELSE next_run_at END,
               lease_owner = NULL, lease_until = NULL, updated_at = ?
           WHERE lease_owner = ?''',
        (utcnow(), utcnow(), worker_id),
    )
    db.commit()


def delete_task(task_id):
    db = get_db()
    db.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
    db.commit()


def delete_all_tasks():
    db = get_db()
    count = db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
    db.execute('DELETE FROM tasks')
    db.commit()
    return count


def set_task_favorite(task_id, favorite):
    db = get_db()
    try:
        db.execute('BEGIN IMMEDIATE')
        cursor = db.execute(
            'UPDATE tasks SET favorite = ?, updated_at = ? WHERE id = ?',
            (1 if favorite else 0, utcnow(), task_id),
        )
        if not favorite:
            db.execute('DELETE FROM task_favorite_groups WHERE task_id = ?', (task_id,))
        db.commit()
        return cursor.rowcount > 0
    except Exception:
        db.rollback()
        raise


def request_task_cancel(task_id):
    """Request cancellation without allowing a worker to overwrite the terminal state."""
    db = get_db()
    now = utcnow()
    try:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT type, status, lease_owner FROM tasks WHERE id = ?', (task_id,)).fetchone()
        if not row:
            db.rollback()
            return None
        if row['status'] in TERMINAL_TASK_STATUSES:
            db.commit()
            return row['status']
        if row['status'] == 'cancel_requested':
            db.commit()
            return 'cancel_requested'
        waiting_for_executor = bool(row['lease_owner']) or (
            row['type'] == 'image' and row['status'] == 'processing'
        )
        next_status = 'cancel_requested' if waiting_for_executor else 'cancelled'
        db.execute(
            '''UPDATE tasks SET status = ?, completed_at = ?, updated_at = ?,
                   next_run_at = NULL, lease_owner = CASE WHEN ? THEN lease_owner ELSE NULL END,
                   lease_until = CASE WHEN ? THEN lease_until ELSE NULL END
               WHERE id = ?''',
            (
                next_status, None if waiting_for_executor else now, now,
                1 if row['lease_owner'] else 0, 1 if row['lease_owner'] else 0, task_id,
            ),
        )
        db.commit()
        return next_status
    except Exception:
        db.rollback()
        raise


def cancellation_requested(task_id):
    row = get_db().execute('SELECT status FROM tasks WHERE id = ?', (task_id,)).fetchone()
    return bool(row and row['status'] in ('cancel_requested', 'cancelled'))


def finalize_task_cancel(task_id):
    now = utcnow()
    cursor = get_db().execute(
        '''UPDATE tasks SET status = 'cancelled', completed_at = ?, updated_at = ?,
               next_run_at = NULL, lease_owner = NULL, lease_until = NULL
           WHERE id = ? AND status = 'cancel_requested' ''',
        (now, now, task_id),
    )
    get_db().commit()
    return cursor.rowcount > 0


def activate_video_task(task_id, external_task_id):
    now = utcnow()
    cursor = get_db().execute(
        '''UPDATE tasks SET status = 'processing', external_task_id = ?, progress = 0,
               next_run_at = ?, updated_at = ?
           WHERE id = ? AND deleted_at IS NULL
             AND status NOT IN ('cancel_requested', 'cancelled')''',
        (external_task_id, now, now, task_id),
    )
    get_db().commit()
    return cursor.rowcount > 0


def move_tasks_to_trash(task_ids):
    db = get_db()
    now = utcnow()
    moved = []
    try:
        db.execute('BEGIN IMMEDIATE')
        for task_id in task_ids:
            row = db.execute(
                'SELECT type, status, lease_owner, deleted_at FROM tasks WHERE id = ?',
                (task_id,),
            ).fetchone()
            if not row or row['deleted_at'] is not None:
                continue
            status = row['status']
            completed_at = None
            if status not in TERMINAL_TASK_STATUSES:
                waiting_for_executor = bool(row['lease_owner']) or (
                    row['type'] == 'image' and status == 'processing'
                )
                status = 'cancel_requested' if waiting_for_executor else 'cancelled'
                if status == 'cancelled':
                    completed_at = now
            db.execute(
                '''UPDATE tasks SET deleted_at = ?, status = ?,
                       completed_at = COALESCE(?, completed_at), updated_at = ?, next_run_at = NULL,
                       lease_owner = CASE WHEN ? = 'cancel_requested' THEN lease_owner ELSE NULL END,
                       lease_until = CASE WHEN ? = 'cancel_requested' THEN lease_until ELSE NULL END
                   WHERE id = ?''',
                (now, status, completed_at, now, status, status, task_id),
            )
            moved.append(task_id)
        db.commit()
        return moved
    except Exception:
        db.rollback()
        raise


def restore_tasks(task_ids):
    db = get_db()
    now = utcnow()
    restored = []
    try:
        db.execute('BEGIN IMMEDIATE')
        for task_id in task_ids:
            row = db.execute(
                'SELECT status, lease_owner, deleted_at FROM tasks WHERE id = ?',
                (task_id,),
            ).fetchone()
            if not row or row['deleted_at'] is None or row['status'] == 'cancel_requested' or row['lease_owner']:
                continue
            db.execute(
                'UPDATE tasks SET deleted_at = NULL, updated_at = ? WHERE id = ?',
                (now, task_id),
            )
            restored.append(task_id)
        db.commit()
        return restored
    except Exception:
        db.rollback()
        raise


def create_favorite_group(name, color='green'):
    now = utcnow()
    db = get_db()
    position = db.execute('SELECT COALESCE(MAX(position), -1) + 1 FROM favorite_groups').fetchone()[0]
    cursor = db.execute(
        '''INSERT INTO favorite_groups (name, color, position, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?)''',
        (name, color, position, now, now),
    )
    db.commit()
    return get_favorite_group(cursor.lastrowid)


def get_favorite_group(group_id):
    row = get_db().execute('SELECT * FROM favorite_groups WHERE id = ?', (group_id,)).fetchone()
    return dict(row) if row else None


def list_favorite_groups(task_type=None):
    type_clause = 'AND t.type = ?' if task_type else ''
    params = [task_type] if task_type else []
    rows = get_db().execute(
        f'''SELECT fg.*, COUNT(DISTINCT t.id) AS task_count
            FROM favorite_groups fg
            LEFT JOIN task_favorite_groups tfg ON tfg.group_id = fg.id
            LEFT JOIN tasks t ON t.id = tfg.task_id AND t.favorite = 1
                AND t.deleted_at IS NULL {type_clause}
            GROUP BY fg.id
            ORDER BY fg.position ASC, fg.name COLLATE NOCASE ASC, fg.id ASC''',
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def update_favorite_group(group_id, name=None, color=None):
    updates = []
    params = []
    if name is not None:
        updates.append('name = ?')
        params.append(name)
    if color is not None:
        updates.append('color = ?')
        params.append(color)
    if not updates:
        return get_favorite_group(group_id)
    updates.append('updated_at = ?')
    params.extend([utcnow(), group_id])
    cursor = get_db().execute(
        f'UPDATE favorite_groups SET {", ".join(updates)} WHERE id = ?', params,
    )
    get_db().commit()
    return get_favorite_group(group_id) if cursor.rowcount else None


def delete_favorite_group(group_id):
    cursor = get_db().execute('DELETE FROM favorite_groups WHERE id = ?', (group_id,))
    get_db().commit()
    return cursor.rowcount > 0


def replace_task_favorite_groups(task_id, group_ids):
    group_ids = list(dict.fromkeys(int(group_id) for group_id in group_ids))
    db = get_db()
    now = utcnow()
    try:
        db.execute('BEGIN IMMEDIATE')
        task = db.execute('SELECT id FROM tasks WHERE id = ?', (task_id,)).fetchone()
        if not task:
            db.rollback()
            return False
        if group_ids:
            placeholders = ','.join('?' for _ in group_ids)
            count = db.execute(
                f'SELECT COUNT(*) FROM favorite_groups WHERE id IN ({placeholders})', group_ids,
            ).fetchone()[0]
            if count != len(group_ids):
                raise ValueError('收藏分组不存在')
        db.execute('DELETE FROM task_favorite_groups WHERE task_id = ?', (task_id,))
        for group_id in group_ids:
            db.execute(
                '''INSERT INTO task_favorite_groups (task_id, group_id, created_at)
                   VALUES (?, ?, ?)''',
                (task_id, group_id, now),
            )
        db.execute(
            'UPDATE tasks SET favorite = 1, updated_at = ? WHERE id = ?',
            (now, task_id),
        )
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def update_tasks_favorite_groups(task_ids, group_ids, mode='add'):
    task_ids = list(dict.fromkeys(int(task_id) for task_id in task_ids))
    group_ids = list(dict.fromkeys(int(group_id) for group_id in group_ids))
    if not task_ids:
        return []
    db = get_db()
    now = utcnow()
    try:
        db.execute('BEGIN IMMEDIATE')
        if group_ids:
            group_placeholders = ','.join('?' for _ in group_ids)
            count = db.execute(
                f'SELECT COUNT(*) FROM favorite_groups WHERE id IN ({group_placeholders})',
                group_ids,
            ).fetchone()[0]
            if count != len(group_ids):
                raise ValueError('收藏分组不存在')
        task_placeholders = ','.join('?' for _ in task_ids)
        existing = [
            row['id'] for row in db.execute(
                f'SELECT id FROM tasks WHERE id IN ({task_placeholders})', task_ids,
            ).fetchall()
        ]
        for task_id in existing:
            if mode == 'replace':
                db.execute('DELETE FROM task_favorite_groups WHERE task_id = ?', (task_id,))
            if mode in ('add', 'replace'):
                for group_id in group_ids:
                    db.execute(
                        '''INSERT OR IGNORE INTO task_favorite_groups (task_id, group_id, created_at)
                           VALUES (?, ?, ?)''',
                        (task_id, group_id, now),
                    )
            elif mode == 'remove':
                for group_id in group_ids:
                    db.execute(
                        'DELETE FROM task_favorite_groups WHERE task_id = ? AND group_id = ?',
                        (task_id, group_id),
                    )
            db.execute(
                'UPDATE tasks SET favorite = 1, updated_at = ? WHERE id = ?',
                (now, task_id),
            )
        db.commit()
        return existing
    except Exception:
        db.rollback()
        raise


def get_workspace_state(key):
    row = get_db().execute(
        'SELECT key, value, revision, updated_at FROM workspace_state WHERE key = ?',
        (key,),
    ).fetchone()
    if not row:
        return None
    data = dict(row)
    try:
        data['value'] = json.loads(data['value'])
    except (json.JSONDecodeError, TypeError):
        data['value'] = None
    return data


def set_workspace_state(key, value):
    now = utcnow()
    encoded = _json(value)
    get_db().execute(
        '''INSERT INTO workspace_state (key, value, revision, updated_at)
           VALUES (?, ?, 1, ?)
           ON CONFLICT(key) DO UPDATE SET
             value = excluded.value,
             revision = workspace_state.revision + 1,
             updated_at = excluded.updated_at''',
        (key, encoded, now),
    )
    get_db().commit()
    return get_workspace_state(key)


def delete_workspace_state(key):
    cursor = get_db().execute('DELETE FROM workspace_state WHERE key = ?', (key,))
    get_db().commit()
    return cursor.rowcount > 0


def register_asset(task_id, kind, path, mime_type=None, expires_at=None):
    path = os.path.abspath(path)
    size_bytes = os.path.getsize(path) if os.path.isfile(path) else 0
    db = get_db()
    db.execute(
        '''INSERT INTO task_assets (task_id, kind, path, mime_type, size_bytes, created_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(path) DO UPDATE SET
             task_id = excluded.task_id, kind = excluded.kind,
             mime_type = excluded.mime_type, size_bytes = excluded.size_bytes,
             expires_at = excluded.expires_at''',
        (task_id, kind, path, mime_type, size_bytes, utcnow(), expires_at),
    )
    db.commit()


def link_asset(path, task_id, expires_at=None):
    db = get_db()
    db.execute(
        'UPDATE task_assets SET task_id = ?, expires_at = ? WHERE path = ?',
        (task_id, expires_at, os.path.abspath(path)),
    )
    db.commit()


def list_assets(task_id=None, expired_before=None):
    query = 'SELECT * FROM task_assets WHERE 1=1'
    params = []
    if task_id is not None:
        query += ' AND task_id = ?'
        params.append(task_id)
    if expired_before is not None:
        query += ' AND expires_at IS NOT NULL AND expires_at <= ?'
        params.append(expired_before)
    return [dict(row) for row in get_db().execute(query, params).fetchall()]


def list_assets_for_tasks(task_ids, kinds=None):
    """Load assets for many tasks without issuing one query per task."""
    normalized_ids = list(dict.fromkeys(int(task_id) for task_id in task_ids))
    if not normalized_ids:
        return []
    normalized_kinds = list(dict.fromkeys(kinds or []))
    rows = []
    # Keep below SQLite's default variable limit, including kind parameters.
    chunk_size = max(1, 900 - len(normalized_kinds))
    for start in range(0, len(normalized_ids), chunk_size):
        chunk = normalized_ids[start:start + chunk_size]
        placeholders = ','.join('?' for _ in chunk)
        query = f'''SELECT a.*, t.type AS task_type
                    FROM task_assets a
                    JOIN tasks t ON t.id = a.task_id
                    WHERE a.task_id IN ({placeholders})'''
        params = list(chunk)
        if normalized_kinds:
            kind_placeholders = ','.join('?' for _ in normalized_kinds)
            query += f' AND a.kind IN ({kind_placeholders})'
            params.extend(normalized_kinds)
        query += ' ORDER BY a.task_id, a.id'
        rows.extend(dict(row) for row in get_db().execute(query, params).fetchall())
    return rows


def delete_asset(path):
    db = get_db()
    db.execute('DELETE FROM task_assets WHERE path = ?', (os.path.abspath(path),))
    db.commit()


def delete_assets(paths):
    normalized = list(dict.fromkeys(os.path.abspath(path) for path in paths))
    if not normalized:
        return 0
    db = get_db()
    before = db.total_changes
    db.executemany('DELETE FROM task_assets WHERE path = ?', ((path,) for path in normalized))
    db.commit()
    return db.total_changes - before


def upsert_worker_heartbeat(worker_id, pid, started_at):
    now = utcnow()
    db = get_db()
    db.execute(
        '''INSERT INTO worker_heartbeats (worker_id, pid, started_at, last_seen_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(worker_id) DO UPDATE SET pid = excluded.pid, last_seen_at = excluded.last_seen_at''',
        (worker_id, int(pid), started_at, now),
    )
    db.commit()


def remove_worker_heartbeat(worker_id):
    db = get_db()
    db.execute('DELETE FROM worker_heartbeats WHERE worker_id = ?', (worker_id,))
    db.commit()


def latest_worker_heartbeat():
    row = get_db().execute(
        'SELECT * FROM worker_heartbeats ORDER BY last_seen_at DESC LIMIT 1'
    ).fetchone()
    return dict(row) if row else None


def recover_dead_worker_leases(stale_seconds=30):
    """Release leases held by workers whose process exited or heartbeat expired."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)
    db = get_db()
    recovered = 0
    for row in db.execute('SELECT * FROM worker_heartbeats').fetchall():
        try:
            last_seen = datetime.fromisoformat(row['last_seen_at'])
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            last_seen = datetime.min.replace(tzinfo=timezone.utc)
        try:
            os.kill(int(row['pid']), 0)
            process_alive = True
        except (OSError, ValueError):
            process_alive = False
        if process_alive and last_seen >= cutoff:
            continue
        cursor = db.execute(
            '''UPDATE tasks
               SET status = CASE
                   WHEN status = 'cancel_requested' THEN 'cancelled'
                   WHEN type = 'image' AND completed_at IS NULL THEN 'pending'
                   ELSE status
               END,
               completed_at = CASE
                   WHEN status = 'cancel_requested' THEN ?
                   ELSE completed_at
               END,
               lease_owner = NULL,
               lease_until = NULL,
               next_run_at = CASE
                   WHEN status = 'cancel_requested' THEN NULL
                   ELSE COALESCE(next_run_at, ?)
               END
               WHERE lease_owner = ?''',
            (utcnow(), utcnow(), row['worker_id']),
        )
        recovered += cursor.rowcount
        db.execute('DELETE FROM worker_heartbeats WHERE worker_id = ?', (row['worker_id'],))
    db.commit()
    return recovered


def list_prompts():
    rows = get_db().execute(
        'SELECT id, text, created_at, updated_at FROM prompts ORDER BY created_at DESC, id DESC'
    ).fetchall()
    return [
        {'id': row['id'], 'text': row['text'], 'createdAt': row['created_at'], 'updatedAt': row['updated_at']}
        for row in rows
    ]


def create_prompt(text, prompt_id=None, created_at=None):
    created_at = created_at or utcnow()
    if prompt_id is None:
        cursor = get_db().execute(
            'INSERT INTO prompts (text, created_at) VALUES (?, ?)',
            (text, created_at),
        )
        prompt_id = cursor.lastrowid
    else:
        get_db().execute(
            'INSERT INTO prompts (id, text, created_at) VALUES (?, ?, ?)',
            (prompt_id, text, created_at),
        )
    get_db().commit()
    return {'id': prompt_id, 'text': text, 'createdAt': created_at}


def import_prompts(prompts):
    db = get_db()
    for prompt in prompts:
        text = str(prompt.get('text') or '').strip()
        if not text:
            continue
        prompt_id = prompt.get('id') or int(datetime.now(timezone.utc).timestamp() * 1000)
        created_at = prompt.get('createdAt') or utcnow()
        db.execute(
            'INSERT OR IGNORE INTO prompts (id, text, created_at) VALUES (?, ?, ?)',
            (prompt_id, text, created_at),
        )
    db.commit()


def update_prompt(prompt_id, text):
    cur = get_db().execute(
        'UPDATE prompts SET text = ?, updated_at = ? WHERE id = ?',
        (text, utcnow(), prompt_id),
    )
    get_db().commit()
    return cur.rowcount > 0


def delete_prompt(prompt_id):
    cur = get_db().execute('DELETE FROM prompts WHERE id = ?', (prompt_id,))
    get_db().commit()
    return cur.rowcount > 0


def db_stats():
    db = get_db()
    page_size = db.execute('PRAGMA page_size').fetchone()[0]
    page_count = db.execute('PRAGMA page_count').fetchone()[0]
    free_pages = db.execute('PRAGMA freelist_count').fetchone()[0]
    task_count = db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
    return {
        'path': DB_PATH,
        'task_count': task_count,
        'page_size': page_size,
        'page_count': page_count,
        'free_pages': free_pages,
        'size_bytes': page_size * page_count,
    }


def checkpoint(truncate=False):
    mode = 'TRUNCATE' if truncate else 'PASSIVE'
    return tuple(get_db().execute(f'PRAGMA wal_checkpoint({mode})').fetchone())


def vacuum():
    db = get_db()
    db.execute('VACUUM')


def ping():
    return get_db().execute('SELECT 1').fetchone()[0] == 1


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _row_to_dict(row):
    data = dict(row)
    for key in ('params', 'result'):
        if data.get(key):
            try:
                data[key] = json.loads(data[key])
            except (json.JSONDecodeError, TypeError):
                pass
    if 'favorite' in data:
        data['favorite'] = bool(data['favorite'])
    return data


init_db()
