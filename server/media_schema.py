"""Global media library schema (LIBRARY-GLOBAL-20261116 S1a).

Called from ``tasks.init_db`` so the API and the Worker both create it; every
statement is idempotent and safe when both processes start together. Old library
tables are untouched: the new library coexists with them until migration (S1b).
"""
import hashlib
from datetime import datetime, timezone

SYSTEM_FOLDERS = (
    # (system_key, title, parent system_key)
    ('generated', '生成历史', None),
    ('generated_image', '图片', 'generated'),
    ('generated_video', '视频', 'generated'),
    ('generated_audio', '音频', 'generated'),
)
DEFAULT_FOLDERS = (('音效', 'music'), ('角色', 'character'), ('场景', 'scene'), ('物品', 'prop'), ('风格', 'style'))


def stable_id(namespace, key):
    """Deterministic folder id: concurrent initializers insert the same row."""
    return hashlib.sha256(f'media-folder:{namespace}:{key}'.encode()).hexdigest()[:32]


def create(db, ensure_columns):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS media_folders (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, parent_id TEXT REFERENCES media_folders(id) ON DELETE RESTRICT,
            system_key TEXT UNIQUE, icon TEXT NOT NULL DEFAULT 'folder',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_media_folders_parent ON media_folders(parent_id);
        CREATE TABLE IF NOT EXISTS media (
            id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, relpath TEXT NOT NULL UNIQUE,
            folder_id TEXT REFERENCES media_folders(id) ON DELETE RESTRICT,
            name TEXT NOT NULL, mime_type TEXT NOT NULL, kind TEXT NOT NULL, size_bytes INTEGER NOT NULL,
            origin TEXT NOT NULL, source_task_id INTEGER, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_media_folder_created ON media(folder_id, created_at DESC, id);
        CREATE INDEX IF NOT EXISTS idx_media_created ON media(created_at DESC, id);
        CREATE INDEX IF NOT EXISTS idx_media_source_task ON media(source_task_id);
        CREATE TABLE IF NOT EXISTS media_aliases (
            scope TEXT NOT NULL, old_id TEXT NOT NULL, media_id TEXT NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY(scope, old_id)
        );
        CREATE INDEX IF NOT EXISTS idx_media_aliases_media ON media_aliases(media_id);
        CREATE TABLE IF NOT EXISTS media_tombstones (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, mime_type TEXT NOT NULL,
            origin TEXT NOT NULL, source_task_id INTEGER, deleted_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS media_groups (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS media_group_members (
            group_id TEXT NOT NULL REFERENCES media_groups(id) ON DELETE CASCADE,
            media_id TEXT NOT NULL, position INTEGER NOT NULL, PRIMARY KEY(group_id, media_id)
        );
        CREATE INDEX IF NOT EXISTS idx_media_group_members_media ON media_group_members(media_id);
        CREATE TABLE IF NOT EXISTS media_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    ''')
    ensure_columns(db, 'task_assets', {'media_id': 'TEXT'})
    db.execute('CREATE INDEX IF NOT EXISTS idx_task_assets_media ON task_assets(media_id)')
    now = datetime.now(timezone.utc).isoformat()
    for key, title, parent in SYSTEM_FOLDERS:
        db.execute('INSERT OR IGNORE INTO media_folders VALUES (?,?,?,?,?,?,?)',
                   (stable_id('system', key), title, stable_id('system', parent) if parent else None, key, 'folder', now, now))
    # Defaults are seeded once; a user who deletes one never sees it recreated.
    if db.execute("INSERT OR IGNORE INTO media_meta VALUES ('defaults_seeded', ?)", (now,)).rowcount:
        for title, icon in DEFAULT_FOLDERS:
            db.execute('INSERT OR IGNORE INTO media_folders VALUES (?,?,?,?,?,?,?)',
                       (stable_id('default', title), title, None, None, icon, now, now))
    db.commit()
