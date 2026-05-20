"""Task management with SQLite — tracks all image and video generation tasks."""

import sqlite3
import json
import os
import threading
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'tasks.db')
_local = threading.local()


def get_db():
    """Get thread-local database connection."""
    if not hasattr(_local, 'conn'):
        _local.conn = sqlite3.connect(DB_PATH)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute('PRAGMA journal_mode=WAL')
    return _local.conn


def init_db():
    """Create tasks table if not exists."""
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
            completed_at TEXT
        )
    ''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(type)')
    db.commit()


def create_task(task_type, prompt, params, provider=None, external_task_id=None):
    """Insert a new task, return its id."""
    db = get_db()
    cur = db.execute(
        'INSERT INTO tasks (type, status, prompt, params, provider, external_task_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (task_type, 'pending', prompt, json.dumps(params, ensure_ascii=False), provider, external_task_id, datetime.now().isoformat())
    )
    db.commit()
    return cur.lastrowid


def update_task(task_id, **kwargs):
    """Update task fields."""
    db = get_db()
    allowed = {'status', 'result', 'error', 'external_task_id', 'output_dir', 'completed_at'}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    # Serialize result if dict/list
    if 'result' in fields and not isinstance(fields['result'], str):
        fields['result'] = json.dumps(fields['result'], ensure_ascii=False)
    sets = ', '.join(f'{k} = ?' for k in fields)
    vals = list(fields.values()) + [task_id]
    db.execute(f'UPDATE tasks SET {sets} WHERE id = ?', vals)
    db.commit()


def get_task(task_id):
    """Get a single task by id."""
    db = get_db()
    row = db.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_tasks(task_type=None, status=None, limit=50, offset=0):
    """List tasks with optional filters."""
    db = get_db()
    query = 'SELECT * FROM tasks WHERE 1=1'
    params = []
    if task_type:
        query += ' AND type = ?'
        params.append(task_type)
    if status:
        query += ' AND status = ?'
        params.append(status)
    query += ' ORDER BY id DESC LIMIT ? OFFSET ?'
    params.extend([limit, offset])
    rows = db.execute(query, params).fetchall()

    count = db.execute(
        'SELECT COUNT(*) FROM tasks WHERE 1=1' +
        (' AND type = ?' if task_type else '') +
        (' AND status = ?' if status else ''),
        ([task_type] if task_type else []) + ([status] if status else [])
    ).fetchone()[0]

    return [_row_to_dict(r) for r in rows], count


def delete_task(task_id):
    """Delete a task."""
    db = get_db()
    db.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
    db.commit()


def _row_to_dict(row):
    d = dict(row)
    for key in ('params', 'result'):
        if d.get(key):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


# Initialize on import
init_db()
