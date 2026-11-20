"""LIBRARY-GLOBAL-20261116 S1b: migration of every old library source into the global media library,
and validate_document accepting media ids / deleted placeholders."""
import copy
import hashlib
import importlib.util
import io
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import app as application
import canvas_store as store
import media_library as media
import media_migrate as migrate
import storage
import tasks
from test_canvas_library_folders import image_bytes
from test_canvas_asset_nodes import media as media_files  # noqa: F401  (fixture)

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'migrate-library-global.py'
NOW = '2026-11-10T00:00:00+00:00'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def hexid(label):
    return hashlib.md5(label.encode()).hexdigest()


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class World:
    """Fixture database covering every source type and skip category."""

    def __init__(self, files):
        self.db = db = tasks.get_db()
        self.root = store.asset_root()
        self.out = Path(storage.OUTPUT_DIR)
        self.files = files
        self.ids = {}
        db.execute('INSERT INTO canvas_projects VALUES (?,?,?,?)', ('p1', '项目一', NOW, NOW))
        db.execute('INSERT INTO canvas_projects VALUES (?,?,?,?)', ('p2', '归档项目', NOW, NOW))
        db.execute("INSERT INTO canvas_deletions VALUES ('project','p2','{\"cleanup_assets\": false}',1)")
        self.color = {c: image_bytes(c) for c in ('red', 'green', 'blue', 'yellow', 'purple', 'cyan', 'gray', 'white', 'black', 'orange')}
        # 1 local pure upload (character), 2 local joined from a task result
        self.local('L1', 'red')
        self.local('L2', 'green')
        t1, ta1 = self.task('image', 'green')
        db.execute('INSERT INTO canvas_local_sources VALUES (?,?,?)', (f'task:{ta1}', self.ids['L2'], NOW))
        db.execute("INSERT INTO characters (id, name, name_key, description, created_at, updated_at) VALUES ('c' || ?, '阿青', 'aqing', '', ?, ?)", ('0' * 31, NOW, NOW))
        db.execute("INSERT INTO character_media VALUES (?,?, 'image', 0, 20, 20, NULL, ?)", ('c' + '0' * 31, self.ids['L1'], NOW))
        # 3 project library asset in a folder and a project group; hidden library asset
        self.library('B1', 'blue')
        self.library('B2', 'white', hidden=True)
        db.execute("INSERT INTO canvas_library_folders VALUES ('f1','p1','角色',NULL,?,?)", (NOW, NOW))
        db.execute("INSERT INTO canvas_library_folder_icons VALUES ('f1','character')")
        db.execute('INSERT INTO canvas_library_asset_locations VALUES (?,?,?)', (self.ids['B1'], 'p1', 'f1'))
        self.ids['G1'] = hexid('G1')
        db.execute('INSERT INTO canvas_asset_groups VALUES (?,?,?,?,?,?)', (self.ids['G1'], 'p1', '主角组', json.dumps([self.ids['B1']]), NOW, NOW))
        # tags
        db.execute("INSERT INTO canvas_catalog_tags VALUES ('t1','标签')")
        db.execute("INSERT INTO canvas_catalog_item_tags VALUES (?, 't1')", ('local:' + self.ids['L1'],))
        # canvas
        db.execute('INSERT INTO canvas_workflows VALUES (?,?,?,?,1,?,?)', ('w1', 'p1', '画布一', json.dumps(store.default_document()), NOW, NOW))
        db.execute('INSERT INTO canvas_workflows VALUES (?,?,?,?,1,?,?)', ('w2', 'p2', '归档画布', json.dumps(store.default_document()), NOW, NOW))
        self.canvas('A1', 'w1', 'blue', copy='library:' + self.ids['B1'])          # copy of library -> library id
        self.canvas('A2', 'w1', 'yellow', origin='uploaded')                      # direct upload == task output (Q6)
        self.task('image', 'yellow')
        t3, ta3 = self.task('image', 'purple')
        self.canvas('A3', 'w1', 'purple')                                         # write-back of t3 (doc evidence)
        self.canvas('A4', 'w1', 'cyan')                                           # paste: unknown origin -> root
        self.canvas('A5', 'w1', 'orange', missing=True)                           # file gone, referenced -> tombstone
        self.canvas('A6', 'w2', 'gray')                                           # archived only -> skipped
        self.ta3, self.t3 = ta3, t3
        name, data = files['video']
        tv, self.tav = self.task('video', data=data, name='video.mp4', deleted=True)   # trash (Q5)
        name, data = files['audio']
        self.task('audio', data=data, name='audio.wav')
        self.task('image', 'black', status='failed')
        self.task('image', 'black', status='cancelled')
        self.task('image', 'black', status='failed', result={'result_unknown': True})
        self.task('layer', 'black')
        self.task('image', status='succeeded', no_output=True)
        self.task('image', 'black', missing=True)
        ref = lambda key: self.asset_ref(key)  # noqa: E731
        nodes = [
            {'id': 'gen', 'type': 'image', 'title': '', 'text': '', 'x': 0, 'y': 0, 'params': {},
             'asset': ref('A3'), 'candidates': [ref('A3')], 'selectedCandidateId': self.ids['A3'], 'task': {'id': t3, 'status': 'succeeded'},
             'referenceAssets': [ref('A1'), ref('A2'), ref('A5')], 'referenceOrder': [self.ids['A1'], self.ids['A2'], self.ids['A5']],
             'referenceMentions': {'@图片1': self.ids['A1'], '@图片3': self.ids['A5']},
             'referenceGroups': [{'id': self.ids['G1'], 'title': '主角组', 'asset_ids': [self.ids['A1']]}]},
            {'id': 'paste', 'type': 'asset', 'title': '', 'text': '', 'x': 0, 'y': 0, 'params': {}, 'asset': ref('A4'),
             'candidates': [ref('A4')], 'selectedCandidateId': self.ids['A4'], 'task': None},
            {'id': 'gone', 'type': 'asset', 'title': '', 'text': '', 'x': 0, 'y': 0, 'params': {}, 'asset': ref('A5'),
             'candidates': [ref('A5')], 'selectedCandidateId': self.ids['A5'], 'task': None},
        ]
        document = {**store.default_document(), 'nodes': nodes}
        db.execute('UPDATE canvas_workflows SET document=? WHERE id=?', (json.dumps(document), 'w1'))
        archived_doc = {**store.default_document(), 'nodes': [{**nodes[1], 'asset': ref('A6'), 'candidates': [ref('A6')], 'selectedCandidateId': self.ids['A6']}]}
        db.execute('UPDATE canvas_workflows SET document=? WHERE id=?', (json.dumps(archived_doc), 'w2'))
        db.execute("INSERT INTO canvas_group_runs VALUES ('run1','w1','g1','finished',1,NULL,?,?,?)", (NOW, NOW, NOW))
        db.execute('''INSERT INTO canvas_group_run_nodes VALUES ('run1','gen','image',0,0,'[]','succeeded',?,'{}',NULL,'fp',?,?,NULL,NULL,?)''',
                   (t3, json.dumps([self.ids['A1']]), self.ids['A1'], NOW))
        db.commit()

    def asset_ref(self, key):
        row = dict(self.db.execute('SELECT * FROM canvas_assets WHERE id=?', (self.ids[key],)).fetchone())
        return store.asset_public(row)

    def local(self, key, color):
        ident = self.ids[key] = hexid(key)
        data = self.color[color]
        put(self.root / 'local_uploads' / (ident + '.png'), data)
        self.db.execute('INSERT INTO canvas_local_uploads VALUES (?,?,?,?,?,?,?,?)',
                        (ident, key + '.png', 'image/png', 'image', sha(data), len(data), ident + '.png', NOW))

    def library(self, key, color, hidden=False):
        ident = self.ids[key] = hexid(key)
        data = self.color[color]
        put(self.root / 'library' / 'p1' / (ident + '.png'), data)
        self.db.execute('INSERT INTO canvas_library_assets VALUES (?,?,?,?,?,?,?,?,?)',
                        (ident, 'p1', key + '.png', 'image/png', 'image', sha(data), len(data), ident + '.png', NOW))
        if hidden:
            self.db.execute('INSERT INTO canvas_catalog_hidden VALUES (?)', ('library:' + ident,))

    def canvas(self, key, workflow, color, copy=None, origin=None, missing=False):
        ident = self.ids[key] = hexid(key)
        data = self.color[color]
        if not missing:
            put(self.root / workflow / (ident + '.png'), data)
        self.db.execute('INSERT INTO canvas_assets VALUES (?,?,?,?,?,?,?,?,?)',
                        (ident, workflow, key + '.png', 'image/png', 'image', sha(data), len(data), ident + '.png', NOW))
        if copy:
            self.db.execute('INSERT INTO canvas_asset_copies VALUES (?,?,?)', (ident, copy, NOW))
        if origin:
            self.db.execute('INSERT INTO canvas_catalog_origins VALUES (?,?,?)', ('workflow:' + ident, origin, NOW))

    def task(self, kind, color=None, data=None, name='image_0.png', status='succeeded', result=None, no_output=False, missing=False, deleted=False):
        tid = tasks.create_task(kind, 'p', {}, status=status)
        if result is not None or deleted:
            self.db.execute('UPDATE tasks SET result=?, deleted_at=? WHERE id=?', (json.dumps(result or {}), NOW if deleted else None, tid))
        if no_output:
            return tid, None
        path = self.out / kind / str(tid) / name
        put(path, data if data is not None else self.color[color])
        output_kind = 'output_' + (kind if kind in ('image', 'video', 'audio') else 'image')
        tasks.register_asset(tid, output_kind, str(path), 'image/png')
        if missing:
            path.unlink()
        self.db.commit()
        return tid, self.db.execute('SELECT id FROM task_assets WHERE path=?', (str(path),)).fetchone()[0]


@pytest.fixture
def world(media_files):
    return World(media_files)


def plan(world, **kw):
    return migrate.build_plan(world.db, store.asset_root(), **kw)


def by_member(p, key):
    return next(g for g in p['groups'] if key in [m['key'] for m in g['members']])


def backup(tmp_path):
    return migrate.make_backup(tasks.DB_PATH, store.asset_root(), storage.OUTPUT_DIR, tmp_path / 'backup')


def run(tmp_path, **kw):
    manifest_dir = tmp_path / 'backup'
    if not manifest_dir.exists():
        backup(tmp_path)
    return migrate.apply(tasks.DB_PATH, manifest_dir, log=lambda _: None, **kw)


def test_dry_run_plan_covers_sources_and_is_read_only(world, tmp_path):
    before = sha(Path(tasks.DB_PATH).read_bytes())
    p = plan(world)
    ids = world.ids
    assert by_member(p, 'local:' + ids['L1'])['folder'] is None and by_member(p, 'local:' + ids['L1'])['media_id'] == ids['L1']
    joined = by_member(p, 'local:' + ids['L2'])
    assert joined['folder'] == 'generated_image' and joined['media_id'] == ids['L2'] and joined['origin'] == 'generated'
    blue = by_member(p, 'workflow:' + ids['A1'])
    assert blue['media_id'] == ids['B1'] and blue['folder'] is None and blue['origin'] == 'legacy_library'
    yellow = by_member(p, 'workflow:' + ids['A2'])  # Q6: upload + generation -> root, upload identity
    assert yellow['folder'] is None and yellow['media_id'] == ids['A2'] and yellow['origin'] == 'canvas_upload' and len(yellow['members']) == 2
    purple = by_member(p, 'workflow:' + ids['A3'])
    assert purple['folder'] == 'generated_image' and purple['media_id'] == ids['A3'] and purple['source_task_id'] == world.t3
    assert by_member(p, 'workflow:' + ids['A4'])['folder'] is None
    assert by_member(p, 'workflow:' + ids['A5'])['tombstone']
    video = by_member(p, f'task:{world.tav}')
    assert video['folder'] == 'generated_video' and video['media_id'] == migrate.deterministic_id(video['sha256'])
    skipped = p['skipped']
    for reason in ('task_failed', 'task_cancelled', 'task_result_unknown', 'task_layer', 'task_remote_only', 'task_file_missing',
                   'excluded_hidden'):
        assert skipped[reason]['count'] == 1, reason
    # S6b: archived-only copies are listed for purge instead of being skipped.
    assert 'excluded_archived' not in skipped and [m['key'] for m in p['archived_purge']] == ['workflow:' + ids['A6']]
    assert p['trash_outputs'] == 1
    assert p['tags'] == {'tags': 1, 'item_tags': 1} and p['project_folders']['folders'] == 1
    doc = next(d for d in p['documents'] if d['workflow_id'] == 'w1')
    assert doc['mapped'] == 5 and doc['id_changed'] == 1 and doc['tombstoned'] == 1 and not doc['unresolved']
    assert p['archived_documents'] == 0  # A6 is archived-only, not aliased
    assert p['run_nodes']['changed'] == 1 and p['asset_groups'][0]['media_ids'] == [ids['B1']]
    text = migrate.format_summary(migrate.summarize(p))
    assert '去重' in text and '清理 已删除画布/项目独有副本' in text and '1 项' in text
    with_archived = plan(world, include_archived=True)
    assert by_member(with_archived, 'workflow:' + ids['A6'])['folder'] is None and with_archived['archived_purge'] == []
    # The CLI dry run opens the database read-only and writes nothing.
    spec = importlib.util.spec_from_file_location('migrate_cli', SCRIPT)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    out = tmp_path / 'plan.json'
    keep = {k: os.environ.get(k) for k in ('NANOBANANA_DB_PATH', 'NANOBANANA_CANVAS_ASSET_DIR')}
    try:
        assert cli.main(['--db', tasks.DB_PATH, '--json', str(out), '--verify-hashes']) == 0
    finally:
        for k, v in keep.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    assert json.loads(out.read_text())['summary']['dedup_groups'] >= 3
    assert sha(Path(tasks.DB_PATH).read_bytes()) == before
    assert world.db.execute('SELECT COUNT(*) FROM media').fetchone()[0] == 0


def test_apply_preflight_blocks(world, tmp_path):
    with pytest.raises(migrate.MigrationError, match='backup-dir'):
        migrate.apply(tasks.DB_PATH, None, log=lambda _: None)
    backup(tmp_path)
    tid = tasks.create_task('image', 'p', {}, status='processing')
    with pytest.raises(migrate.MigrationError, match='活动任务'):
        migrate.apply(tasks.DB_PATH, tmp_path / 'backup', log=lambda _: None)
    world.db.execute("UPDATE tasks SET status='succeeded' WHERE id=?", (tid,))
    world.db.execute("INSERT INTO canvas_group_runs VALUES ('run2','w1','g2','running',1,NULL,?,?,NULL)", (NOW, NOW))
    world.db.execute("INSERT INTO worker_heartbeats VALUES ('w', 1, ?, ?)", (NOW, datetime.now(timezone.utc).isoformat()))
    world.db.commit()
    blockers, _, _ = migrate.preflight(world.db, tasks.DB_PATH, tmp_path / 'backup')
    joined = '；'.join(blockers)
    assert '组运行' in joined and 'Worker' in joined and '备份后数据库已有变化' in joined
    stale = migrate.preflight(world.db, tasks.DB_PATH, tmp_path / 'backup', now=datetime.now(timezone.utc) + timedelta(days=2))[0]
    assert any('24小时' in b for b in stale)
    assert world.db.execute('SELECT COUNT(*) FROM media').fetchone()[0] == 0


def test_preflight_blocks_missing_ffprobe(world, tmp_path, monkeypatch):
    """BACKLOG-LIBRARY-SIDEBAR: migration preflight reports a clear Chinese error when ffprobe is missing."""
    backup(tmp_path)
    monkeypatch.setattr(migrate.shutil, 'which', lambda cmd: None if cmd == 'ffprobe' else '/usr/bin/' + cmd)
    blockers, _, _ = migrate.preflight(world.db, tasks.DB_PATH, tmp_path / 'backup')
    assert any('ffprobe' in b and '外部依赖' in b for b in blockers), blockers
    with pytest.raises(migrate.MigrationError, match='ffprobe'):
        migrate.apply(tasks.DB_PATH, tmp_path / 'backup', log=lambda _: None)


def test_backup_snapshot_and_manifest(world, tmp_path):
    manifest = backup(tmp_path)
    dest = tmp_path / 'backup'
    assert manifest['complete'] and (dest / 'manifest.json').is_file()
    copy_db = sqlite3.connect(dest / 'tasks.db')
    assert copy_db.execute('SELECT COUNT(*) FROM canvas_assets').fetchone()[0] == 6
    lines = (dest / 'sha256sums.txt').read_text().splitlines()
    assert any(line.endswith('canvas_assets/w1/' + world.ids['A1'] + '.png') for line in lines)
    original = store.asset_root() / 'w1' / (world.ids['A1'] + '.png')
    assert os.stat(dest / 'canvas_assets' / 'w1' / original.name).st_ino == os.stat(original).st_ino
    with pytest.raises(FileExistsError):
        backup(tmp_path)


def test_apply_migrates_everything_and_is_idempotent(world, tmp_path):
    ids = world.ids
    report = run(tmp_path)
    assert not report['problems'] and not report['documents_failed'], report
    db = world.db
    rows = {r['id']: dict(r) for r in db.execute('SELECT * FROM media')}
    gen = {k: media.system_folder_id(k) for k in ('generated_image', 'generated_video', 'generated_audio')}
    assert rows[ids['L1']]['folder_id'] is None and rows[ids['L1']]['origin'] == 'legacy_local'
    assert rows[ids['L2']]['folder_id'] == gen['generated_image']
    assert rows[ids['B1']]['folder_id'] is None and rows[ids['A2']]['folder_id'] is None and rows[ids['A2']]['origin'] == 'canvas_upload'
    assert rows[ids['A3']]['folder_id'] == gen['generated_image'] and rows[ids['A4']]['origin'] == 'legacy_workflow'
    assert {r['folder_id'] for r in rows.values()} >= {gen['generated_video'], gen['generated_audio']}
    assert ids['A6'] not in rows and ids['B2'] not in rows and ids['A1'] not in rows
    assert db.execute('SELECT 1 FROM media_tombstones WHERE id=?', (ids['A5'],)).fetchone()
    # Hard links: same inode as the old file; hashes verified.
    old = store.asset_root() / 'library' / 'p1' / (ids['B1'] + '.png')
    assert os.stat(media.media_path(rows[ids['B1']])).st_ino == os.stat(old).st_ino
    # Aliases and task links.
    assert media.resolve('workflow:' + ids['A1']) == ids['B1'] and media.resolve(f"/api/canvas/workflows/w1/assets/{ids['A1']}") == ids['B1']
    assert media.resolve(f'task:{world.ta3}') == ids['A3']
    assert db.execute('SELECT media_id FROM task_assets WHERE id=?', (world.ta3,)).fetchone()[0] == ids['A3']
    assert db.execute('SELECT media_id FROM task_assets WHERE id=?', (world.tav,)).fetchone()[0]
    # Document: ids mapped, snapshots point to the library, deleted reference stripped, placeholder kept.
    wf = store.workflow('w1')
    assert wf['revision'] == 2
    gen_node, paste, gone = wf['document']['nodes']
    assert [a['id'] for a in gen_node['referenceAssets']] == [ids['B1'], ids['A2']]
    assert all(a['url'] == '/api/canvas/media/' + a['id'] for a in gen_node['referenceAssets'] + [gen_node['asset']])
    assert gen_node['referenceOrder'] == [ids['B1'], ids['A2']] and gen_node['referenceMentions'] == {'@图片1': ids['B1']}
    assert gen_node['referenceGroups'][0]['asset_ids'] == [ids['B1']] and gen_node['referenceGroups'][0]['id'] == ids['G1']
    assert gone['asset']['id'] == ids['A5'] and gone['asset']['url'] == '/api/canvas/media/' + ids['A5'] and 'size_bytes' not in gone['asset']
    assert paste['asset']['id'] == ids['A4']
    archived = json.loads(db.execute("SELECT document FROM canvas_workflows WHERE id='w2'").fetchone()[0])
    assert archived['nodes'][0]['asset']['id'] == ids['A6'] and '/workflows/w2/' in archived['nodes'][0]['asset']['url']  # untouched
    # Characters, groups, runs, tables.
    assert db.execute('SELECT local_id FROM character_media').fetchone()[0] == ids['L1']
    group = media.get_group(ids['G1'])
    assert group['media_ids'] == [ids['B1']] and group['title'] == '主角组'
    run_row = db.execute('SELECT base_assets, result_asset_id FROM canvas_group_run_nodes').fetchone()
    assert json.loads(run_row[0]) == [ids['B1']] and run_row[1] == ids['B1']
    for table in ('canvas_catalog_tags', 'canvas_catalog_item_tags', 'canvas_library_folders', 'canvas_library_asset_locations', 'canvas_local_sources'):
        assert db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0, table
    # Old tables kept for rollback, except the archived-only copy A6 (purged with its file, S6b).
    assert db.execute('SELECT COUNT(*) FROM canvas_assets').fetchone()[0] == 5
    assert not db.execute('SELECT 1 FROM canvas_assets WHERE id=?', (ids['A6'],)).fetchone()
    assert not (store.asset_root() / 'w2' / (ids['A6'] + '.png')).exists()
    assert (tmp_path / 'backup' / 'canvas_assets' / 'w2' / (ids['A6'] + '.png')).read_bytes() == world.color['gray']
    assert report['archived_files_removed'] == 1 and report['archived_rows_removed'] == 1
    state = json.loads(db.execute("SELECT value FROM media_meta WHERE key=?", (migrate.STATE_KEY,)).fetchone()[0])
    assert state['state'] == 'done'
    # Rerun: no new rows, no new revision.
    count = len(rows)
    again = run(tmp_path)
    assert again['created'] == 0 and again['documents_rewritten'] == 0 and not again['problems']
    assert again['archived_rows_removed'] == 0 and again['archived_files_removed'] == 0
    assert db.execute('SELECT COUNT(*) FROM media').fetchone()[0] == count and store.workflow('w1')['revision'] == 2
    assert migrate.verify(db) == []
    # The library API serves migrated items.
    client = application.app.test_client()
    assert client.get('/api/canvas/media/' + ids['B1']).data == world.color['blue']
    assert client.get('/api/canvas/media/' + ids['A5'] + '/info').status_code == 410


def test_archived_only_copies_are_purged_and_live_references_protect(world, tmp_path):
    db, root, ids = world.db, store.asset_root(), world.ids
    # Archived project library item with a file, archived canvas copy whose file is already gone,
    # archived copy still used by an active group run (kept), and archived copy of live content (aliased).
    lib = ids['P1'] = hexid('P1')
    data = image_bytes('navy')
    put(root / 'library' / 'p2' / (lib + '.png'), data)
    db.execute('INSERT INTO canvas_library_assets VALUES (?,?,?,?,?,?,?,?,?)', (lib, 'p2', 'old.png', 'image/png', 'image', sha(data), len(data), lib + '.png', NOW))
    db.execute("INSERT INTO canvas_library_folders VALUES ('f2','p2','旧',NULL,?,?)", (NOW, NOW))
    db.execute("INSERT INTO canvas_library_asset_locations VALUES (?,?, 'f2')", (lib, 'p2'))
    db.execute('INSERT INTO canvas_catalog_origins VALUES (?,?,?)', ('library:' + lib, 'uploaded', NOW))
    world.color['olive'] = image_bytes('olive')
    world.canvas('A7', 'w2', 'olive', missing=True)
    world.color['teal'] = image_bytes('teal')
    world.canvas('A8', 'w2', 'teal')
    db.execute("INSERT INTO canvas_group_runs VALUES ('run3','w1','g3','finished',1,NULL,?,?,?)", (NOW, NOW, NOW))
    db.execute('''INSERT INTO canvas_group_run_nodes VALUES ('run3','paste','image',0,0,'[]','succeeded',NULL,'{}',NULL,'fp',?,NULL,NULL,NULL,?)''',
               (json.dumps([ids['A8']]), NOW))
    world.canvas('A9', 'w2', 'blue', copy='library:' + ids['B1'])  # same content as live B1
    db.commit()
    p = plan(world)
    keys = sorted(m['key'] for m in p['archived_purge'])
    assert keys == sorted(['workflow:' + ids['A6'], 'workflow:' + ids['A7'], 'library:' + lib])
    summary = migrate.summarize(p)['archived_purge']
    assert summary['count'] == 3 and summary['files'] == 2 and summary['missing_files'] == 1
    assert summary['bytes'] == len(data) + len(world.color['gray'])
    assert p['skipped']['excluded_archived_referenced']['samples'] == ['workflow:' + ids['A8']]
    assert 'workflow:' + ids['A9'] in [m['key'] for m in by_member(p, 'library:' + ids['B1'])['members']]
    report = run(tmp_path)
    assert not report['problems'] and report['archived_rows_removed'] == 3 and report['archived_files_removed'] == 2
    assert not (root / 'library' / 'p2' / (lib + '.png')).exists()
    for table, key in (('canvas_library_assets', lib), ('canvas_assets', ids['A6']), ('canvas_assets', ids['A7'])):
        assert not db.execute(f'SELECT 1 FROM {table} WHERE id=?', (key,)).fetchone(), (table, key)
    assert not db.execute("SELECT 1 FROM canvas_catalog_origins WHERE item_key=?", ('library:' + lib,)).fetchone()
    # Kept: the referenced archived copy and the archived duplicate of live content (its alias resolves).
    assert (root / 'w2' / (ids['A8'] + '.png')).is_file() and db.execute('SELECT 1 FROM canvas_assets WHERE id=?', (ids['A8'],)).fetchone()
    assert (root / 'w2' / (ids['A9'] + '.png')).is_file() and media.resolve('workflow:' + ids['A9']) == ids['B1']
    # Backup snapshot still holds the purged file for rollback; a rerun purges nothing.
    assert (tmp_path / 'backup' / 'canvas_assets' / 'library' / 'p2' / (lib + '.png')).read_bytes() == data
    again = run(tmp_path)
    assert again['archived_rows_removed'] == 0 and plan(world)['archived_purge'] == []


def test_include_archived_imports_instead_of_purging(world, tmp_path):
    report = run(tmp_path, include_archived=True)
    assert report['archived_rows_removed'] == 0 and media.get_media(world.ids['A6'])['folder_id'] is None
    assert (store.asset_root() / 'w2' / (world.ids['A6'] + '.png')).is_file()


def test_apply_resumes_after_interruption(world, tmp_path):
    with pytest.raises(migrate.MigrationError, match='测试中断'):
        run(tmp_path, fail_after=3)
    db = world.db
    assert db.execute('SELECT COUNT(*) FROM media').fetchone()[0] == 3
    assert json.loads(db.execute("SELECT value FROM media_meta WHERE key=?", (migrate.STATE_KEY,)).fetchone()[0])['state'] == 'running'
    # The same backup is accepted although the database has changed since.
    report = run(tmp_path)
    assert not report['problems'] and report['reused'] == 3
    full = len(plan(world)['groups'])
    assert db.execute('SELECT COUNT(*) FROM media').fetchone()[0] + db.execute('SELECT COUNT(*) FROM media_tombstones').fetchone()[0] == full
    assert not [p for p in media.root().iterdir() if p.name.endswith('.tmp')]


def test_existing_generated_media_moves_to_root_when_also_uploaded(world, tmp_path):
    # S2 already registered the yellow output in 生成历史 before migration: Q6 moves it to the root.
    yellow_task = world.db.execute("SELECT task_id, path FROM task_assets WHERE path LIKE '%/image/%' ORDER BY id").fetchall()[1]
    existing = media.register_generated(yellow_task[0], yellow_task[1], 'image')
    world.db.commit()
    report = run(tmp_path)
    row = media.get_media(existing)
    assert row['folder_id'] is None and row['origin'] == 'canvas_upload' and report['moved_to_root'] == 1
    assert media.resolve('workflow:' + world.ids['A2']) == existing


# ---------------------------------------------------------------- validate_document

def migrated(world, tmp_path):
    run(tmp_path)
    return store.workflow('w1')


def test_validate_accepts_media_and_placeholders_and_rejects_bad_refs(world, tmp_path):
    wf = migrated(world, tmp_path)
    ids = world.ids
    doc = wf['document']
    store.validate_document(copy.deepcopy(doc), 'w1')
    # An item from another project's library can be referenced directly (global library).
    item = media.get_media(ids['L1'])
    ref = store.media_reference(item)
    doc2 = copy.deepcopy(doc)
    doc2['nodes'][0]['referenceAssets'].append(ref)
    store.validate_document(doc2, 'w1')
    for broken, message in (({**ref, 'url': '/api/canvas/media/' + ids['B1']}, '不一致'),
                            ({**ref, 'kind': 'video'}, '不一致'),
                            ({**ref, 'size_bytes': 1}, '字段无效'),
                            ({**ref, 'extra': 1}, '字段无效'),
                            ({**ref, 'id': hexid('nothing'), 'url': '/api/canvas/media/' + hexid('nothing')}, '素材库素材')):
        bad = copy.deepcopy(doc)
        bad['nodes'][0]['referenceAssets'].append(broken)
        with pytest.raises(store.CanvasError, match=message):
            store.validate_document(bad, 'w1')
    # A deleted media id is a valid output placeholder but is stripped from inputs on save.
    media.delete_media([ids['A2']])
    current = store.workflow('w1')['document']
    assert ids['A2'] not in [a['id'] for a in current['nodes'][0]['referenceAssets']]
    stale = copy.deepcopy(doc)
    encoded = json.loads(store.validate_document(stale, 'w1'))
    assert ids['A2'] not in [a['id'] for a in encoded['nodes'][0]['referenceAssets']]
    placeholder = copy.deepcopy(current)
    tomb = store.media_reference(dict(world.db.execute('SELECT * FROM media_tombstones WHERE id=?', (ids['A2'],)).fetchone()))
    placeholder['nodes'][1] = {**placeholder['nodes'][1], 'asset': tomb, 'candidates': [tomb], 'selectedCandidateId': ids['A2']}
    store.validate_document(placeholder, 'w1')


def test_validate_normalizes_old_ids_on_save(world, tmp_path):
    ids = world.ids
    old_doc = json.loads(world.db.execute("SELECT document FROM canvas_workflows WHERE id='w1'").fetchone()[0])
    wf = migrated(world, tmp_path)
    saved = store.update_workflow('w1', '画布一', old_doc, wf['revision'])
    gen_node = saved['document']['nodes'][0]
    assert gen_node['referenceOrder'] == [ids['B1'], ids['A2']] and saved['document']['nodes'][1]['asset']['url'].startswith('/api/canvas/media/')
    assert gen_node['selectedCandidateId'] == ids['A3']
    # Before migration (no aliases) old canvas assets stay valid and untouched.
    world2 = store.create_project('新项目')
    w = store.create_workflow(world2['id'], '画布')
    asset = store.save_asset(w['id'], io.BytesIO(image_bytes('pink')), 'pink.png')
    node = {'id': 'n', 'type': 'asset', 'title': '', 'text': '', 'x': 0, 'y': 0, 'params': {}, 'asset': asset, 'candidates': [asset], 'selectedCandidateId': asset['id'], 'task': None}
    document = {**store.default_document(), 'nodes': [node]}
    assert json.loads(store.validate_document(copy.deepcopy(document), w['id'])) == document
    assert store.MEDIA_REFERENCES is True


def test_image_metadata_route_accepts_media_ids(world, tmp_path):
    migrated(world, tmp_path)
    client = application.app.test_client()
    ids = world.ids
    r = client.get(f"/api/canvas/workflows/w1/assets/{ids['L1']}/metadata")
    assert r.status_code == 200 and r.json['metadata']['width'] == 20
    old = client.get(f"/api/canvas/workflows/w1/assets/{ids['A1']}/metadata")  # old canvas row still served
    assert old.status_code == 200
    assert client.get(f"/api/canvas/workflows/w1/assets/{hexid('zz')}/metadata").status_code == 404
