"""MIGRATE-RACE-20261115: API and Worker both run init_db at start-up.

The loser of the race must tolerate a column the winner has just added (v1.9.0 deploy:
Gunicorn failed to boot with "duplicate column name: stage").
"""
import sqlite3

import pytest

import tasks


class _StaleSchema:
    """A connection whose PRAGMA view predates another process adding the column."""

    def __init__(self, db):
        self.db = db

    def execute(self, sql, *args):
        if sql.startswith('PRAGMA table_info'):
            return [row for row in self.db.execute(sql, *args) if row[1] != 'stage']
        return self.db.execute(sql, *args)


def _db():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE tasks (id INTEGER PRIMARY KEY, stage TEXT)')
    return db


def test_column_added_by_the_other_process_is_tolerated():
    db = _db()
    tasks._ensure_columns(_StaleSchema(db), 'tasks', {'stage': 'TEXT'})
    assert [row[1] for row in db.execute('PRAGMA table_info(tasks)')].count('stage') == 1


def test_other_alter_errors_still_raise():
    db = _db()
    with pytest.raises(sqlite3.OperationalError):
        tasks._ensure_columns(db, 'missing_table', {'x': 'TEXT'})
