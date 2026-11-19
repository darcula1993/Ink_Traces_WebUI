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
            id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, relpath TEXT NOT NULL UNIQUE,
            folder_id TEXT REFERENCES media_folders(id) ON DELETE RESTRICT,
            name TEXT NOT NULL, mime_type TEXT NOT NULL, kind TEXT NOT NULL, size_bytes INTEGER NOT NULL,
            origin TEXT NOT NULL, source_task_id INTEGER, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_media_sha256 ON media(sha256);
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
    _drop_sha256_unique(db)
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


def _drop_sha256_unique(db):
    """GEN-RESULT-LIFECYCLE-20261119: a copy out of 生成历史 is an independent item sharing the
    original's file (hard link), so the same content may have several rows. Older databases
    created ``sha256 ... UNIQUE``; rebuild the table once without it (idempotent, one
    transaction, rows/ids unchanged; nothing references ``media`` by foreign key).
    """
    def unique_sha(connection):
        for index in connection.execute("PRAGMA index_list('media')").fetchall():
            if index[2] and index[3] == 'u':
                columns = [r[2] for r in connection.execute(f"PRAGMA index_info('{index[1]}')")]
                if columns == ['sha256']:
                    return True
        return False
    if not unique_sha(db):
        return
    db.commit()
    db.execute('BEGIN IMMEDIATE')
    try:
        if unique_sha(db):  # another process may have rebuilt it meanwhile
            db.execute('''CREATE TABLE media_rebuild (
                id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, relpath TEXT NOT NULL UNIQUE,
                folder_id TEXT REFERENCES media_folders(id) ON DELETE RESTRICT,
                name TEXT NOT NULL, mime_type TEXT NOT NULL, kind TEXT NOT NULL, size_bytes INTEGER NOT NULL,
                origin TEXT NOT NULL, source_task_id INTEGER, created_at TEXT NOT NULL)''')
            db.execute('''INSERT INTO media_rebuild (id, sha256, relpath, folder_id, name, mime_type, kind, size_bytes,
                origin, source_task_id, created_at) SELECT id, sha256, relpath, folder_id, name, mime_type, kind,
                size_bytes, origin, source_task_id, created_at FROM media''')
            db.execute('DROP TABLE media')
            db.execute('ALTER TABLE media_rebuild RENAME TO media')
            db.execute('CREATE INDEX IF NOT EXISTS idx_media_sha256 ON media(sha256)')
            db.execute('CREATE INDEX IF NOT EXISTS idx_media_folder_created ON media(folder_id, created_at DESC, id)')
            db.execute('CREATE INDEX IF NOT EXISTS idx_media_created ON media(created_at DESC, id)')
            db.execute('CREATE INDEX IF NOT EXISTS idx_media_source_task ON media(source_task_id)')
        db.commit()
    except Exception:
        db.rollback()
        raise
