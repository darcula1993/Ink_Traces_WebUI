"""SQLite persistence for generation tasks, assets, prompts, and workers."""

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
DB_PATH = os.environ.get('NANOBANANA_DB_PATH', os.path.join(PROJECT_ROOT, 'tasks.db'))
_local = threading.local()


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
        conn.execute('PRAGMA wal_autocheckpoint=1000')
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
            lease_until TEXT
        )
    ''')
    _ensure_columns(db, 'tasks', {
        'updated_at': 'TEXT',
        'progress': 'INTEGER NOT NULL DEFAULT 0',
        'attempt_count': 'INTEGER NOT NULL DEFAULT 0',
        'next_run_at': 'TEXT',
        'lease_owner': 'TEXT',
        'lease_until': 'TEXT',
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
    db.execute('CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(type)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_tasks_queue ON tasks(status, next_run_at, lease_until)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_tasks_type_status_id ON tasks(type, status, id DESC)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_assets_task ON task_assets(task_id)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_assets_expiry ON task_assets(expires_at)')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_external ON tasks(provider, external_task_id) WHERE external_task_id IS NOT NULL')
    now = utcnow()
    db.execute('UPDATE tasks SET updated_at = COALESCE(updated_at, created_at, ?)', (now,))
    db.commit()


def create_task(task_type, prompt, params, provider=None, external_task_id=None, status='pending'):
    now = utcnow()
    db = get_db()
    cur = db.execute(
        '''INSERT INTO tasks
           (type, status, prompt, params, provider, external_task_id, created_at, updated_at, next_run_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (task_type, status, prompt, _json(params), provider, external_task_id, now, now, now)
    )
    db.commit()
    return cur.lastrowid


def update_task(task_id, **kwargs):
    allowed = {
        'status', 'params', 'result', 'error', 'provider', 'external_task_id',
        'output_dir', 'completed_at', 'updated_at', 'progress', 'attempt_count',
        'next_run_at', 'lease_owner', 'lease_until',
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
    return update_task(
        task_id,
        status='succeeded',
        result=result,
        error=None,
        output_dir=output_dir,
        progress=100,
        completed_at=utcnow(),
        next_run_at=None,
        lease_owner=None,
        lease_until=None,
    )


def fail_task(task_id, error, result=None):
    values = {
        'status': 'failed',
        'error': str(error),
        'completed_at': utcnow(),
        'next_run_at': None,
        'lease_owner': None,
        'lease_until': None,
    }
    if result is not None:
        values['result'] = result
    return update_task(task_id, **values)


def reschedule_task(task_id, delay_seconds, status='processing', error=None, progress=None):
    values = {
        'status': status,
        'completed_at': None,
        'next_run_at': _future(delay_seconds),
        'lease_owner': None,
        'lease_until': None,
    }
    if error is not None:
        values['error'] = str(error)
    if progress is not None:
        values['progress'] = int(progress)
    return update_task(task_id, **values)


def get_task(task_id):
    row = get_db().execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    return _row_to_dict(row) if row else None


def get_task_by_external(provider, external_task_id):
    row = get_db().execute(
        'SELECT * FROM tasks WHERE provider = ? AND external_task_id = ? ORDER BY id DESC LIMIT 1',
        (provider, external_task_id),
    ).fetchone()
    return _row_to_dict(row) if row else None


def list_tasks(task_type=None, status=None, limit=50, offset=0, summary=False):
    if summary:
        result_summary = '''
            CASE WHEN json_valid(result) THEN json_object(
                'local_images', json_extract(result, '$.local_images'),
                'local_refs', json_extract(result, '$.local_refs'),
                'local_video', json_extract(result, '$.local_video'),
                'local_last_frame', json_extract(result, '$.local_last_frame'),
                'thinking', substr(COALESCE(json_extract(result, '$.thinking'), ''), 1, 100)
            ) ELSE NULL END AS result
        '''
        columns = (
            'id, type, status, prompt, params, provider, external_task_id, '
            f'{result_summary}, error, output_dir, created_at, completed_at, '
            'updated_at, progress, attempt_count'
        )
    else:
        columns = '*'
    query = f'SELECT {columns} FROM tasks WHERE 1=1'
    params = []
    if task_type:
        query += ' AND type = ?'
        params.append(task_type)
    if status:
        query += ' AND status = ?'
        params.append(status)
    query += ' ORDER BY id DESC'
    if limit is not None:
        query += ' LIMIT ? OFFSET ?'
        params.extend([int(limit), int(offset)])
    rows = get_db().execute(query, params).fetchall()

    count_query = 'SELECT COUNT(*) FROM tasks WHERE 1=1'
    count_params = []
    if task_type:
        count_query += ' AND type = ?'
        count_params.append(task_type)
    if status:
        count_query += ' AND status = ?'
        count_params.append(status)
    count = get_db().execute(count_query, count_params).fetchone()[0]
    return [_row_to_dict(row) for row in rows], count


def claim_next_task(worker_id, lease_seconds=900):
    """Atomically lease one due image execution or video polling task."""
    db = get_db()
    now = utcnow()
    try:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute(
            '''
            SELECT * FROM tasks
            WHERE completed_at IS NULL
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
        'UPDATE tasks SET lease_owner = NULL, lease_until = NULL WHERE lease_owner = ?',
        (worker_id,),
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


def delete_asset(path):
    db = get_db()
    db.execute('DELETE FROM task_assets WHERE path = ?', (os.path.abspath(path),))
    db.commit()


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
                   WHEN type = 'image' AND completed_at IS NULL THEN 'pending'
                   ELSE status
               END,
               lease_owner = NULL,
               lease_until = NULL,
               next_run_at = COALESCE(next_run_at, ?)
               WHERE lease_owner = ?''',
            (utcnow(), row['worker_id']),
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
    return data


init_db()
