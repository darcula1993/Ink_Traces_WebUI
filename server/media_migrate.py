"""LIBRARY-GLOBAL-20261116 S1b: migrate every old library source into the global media library.

Sources (old identity -> ``media_aliases`` scope): local uploads and joined results
(``canvas_local_uploads`` -> local), project library (``canvas_library_assets`` -> library),
canvas copies (``canvas_assets`` -> workflow) and every succeeded image/video/audio task
output, trash included (``task_assets`` -> task). Content is grouped by sha256; one media
row per content. Placement (user decisions 2026-11-16, Q6): content with any upload
evidence (pure local upload, project library, canvas direct upload) goes to the root and
keeps that identity; content that is only a generation result goes to 生成历史/<kind>;
everything else (paste/frame/role card copies of unknown origin) goes to the root.

``build_plan`` is read-only and works on any sqlite connection (the dry run opens the
database read-only). ``apply`` is idempotent and resumable: each content group commits in
its own transaction, aliases make document rewriting a pure id mapping, and every later
step re-derives its work from the database. Contract and steps:
(see the migration section of the technical notes).
"""
import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATE_KEY = 'library_global_migration'
OUTPUT_KINDS = {'output_image': 'image', 'output_video': 'video', 'output_audio': 'audio'}
GENERATION_TYPES = ('image', 'video', 'audio')
ACTIVE_TASK_STATUSES = ('submitting', 'preparing', 'pending', 'processing', 'cancel_requested')
ACTIVE_RUN_STATUSES = ('running', 'awaiting_confirm')
HEARTBEAT_SECONDS = 120
BACKUP_MAX_AGE = timedelta(hours=24)
# Keeper priority inside one content group: its id becomes the media id (step 5 "保留其 id").
PRIORITY = {'local': 0, 'local_joined': 1, 'library': 2, 'canvas_upload': 3, 'workflow': 4, 'task': 5}
ORIGIN = {'local': 'legacy_local', 'local_joined': 'legacy_local', 'library': 'legacy_library',
          'canvas_upload': 'canvas_upload', 'workflow': 'legacy_workflow', 'task': 'generated'}
NAME_BAD = set('/\\')


class MigrationError(RuntimeError):
    pass


def deterministic_id(sha256):
    return hashlib.sha256(('media:' + sha256).encode()).hexdigest()[:32]


def _has(db, table):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _rows(db, table, sql=None, args=()):
    if not _has(db, table):
        return []
    return [dict(r) for r in db.execute(sql or f'SELECT * FROM {table}', args)]


def _json(text, default):
    try:
        value = json.loads(text) if isinstance(text, str) else default
    except ValueError:
        return default
    return value if isinstance(value, type(default)) else default


def _file_ok(path):
    try:
        path = Path(path)
        return path.is_absolute() and path.resolve() == path and path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def digest(path):
    value, size = hashlib.sha256(), 0
    with open(path, 'rb') as handle:
        while chunk := handle.read(1024 * 1024):
            value.update(chunk)
            size += len(chunk)
    return value.hexdigest(), size


def clean_name(name, fallback):
    text = ''.join(' ' if (c in NAME_BAD or ord(c) < 32) else c for c in (name or '')).strip()[:240]
    if not text:
        text = ''.join(' ' if (c in NAME_BAD or ord(c) < 32) else c for c in fallback).strip()[:240] or 'media'
    return text


# ---------------------------------------------------------------- references

def _asset_objects(node):
    if isinstance(node.get('asset'), dict):
        yield 'asset', node['asset']
    for key in ('candidates', 'referenceAssets'):
        for item in node.get(key) or []:
            if isinstance(item, dict):
                yield key, item


def document_ids(document):
    """Every asset id a canvas document references (objects and id lists)."""
    ids = set()
    for node in document.get('nodes', []) if isinstance(document, dict) else []:
        if not isinstance(node, dict):
            continue
        ids |= {a.get('id') for _, a in _asset_objects(node)}
        ids |= set(node.get('referenceOrder') or [])
        ids |= set((node.get('referenceMentions') or {}).values())
        for group in node.get('referenceGroups') or []:
            ids |= set(group.get('asset_ids') or []) if isinstance(group, dict) else set()
        for ref in (node.get('characterRefs') or {}).values():
            ids |= set(ref.get('assetIds') or []) if isinstance(ref, dict) else set()
    return {i for i in ids if isinstance(i, str)}


def _generated_ids(document):
    """Canvas asset ids that are results of generation nodes (write-back evidence)."""
    ids = set()
    for node in document.get('nodes', []) if isinstance(document, dict) else []:
        if isinstance(node, dict) and node.get('type') in GENERATION_TYPES:
            ids |= {a.get('id') for key, a in _asset_objects(node) if key != 'referenceAssets'}
    return ids


# ---------------------------------------------------------------- plan

def build_plan(db, asset_root, include_archived=False, verify_hashes=False):
    """Read-only migration plan. ``db`` rows must support mapping access (sqlite3.Row)."""
    asset_root = Path(asset_root).absolute()
    deletions = _rows(db, 'canvas_deletions')
    deleted = {(d['scope'], d['id']) for d in deletions}
    removed_library = set()
    for d in deletions:
        removed_library |= set(_json(d['manifest'], {}).get('removed_library_ids', []))
    hidden = {r['item_key'] for r in _rows(db, 'canvas_catalog_hidden')}
    projects = {r['id']: r for r in _rows(db, 'canvas_projects')}
    workflows = {r['id']: r for r in _rows(db, 'canvas_workflows')}
    archived_project = lambda pid: pid not in projects or ('project', pid) in deleted  # noqa: E731
    archived_workflow = lambda wid: wid not in workflows or ('workflow', wid) in deleted or archived_project(workflows[wid]['project_id'])  # noqa: E731
    active_docs, generated_ids = {}, {}
    for wid, row in workflows.items():
        document = _json(row['document'], {})
        if not archived_workflow(wid):
            active_docs[wid] = document
        generated_ids[wid] = _generated_ids(document)
    doc_refs = {wid: document_ids(doc) for wid, doc in active_docs.items()}
    character_rows = _rows(db, 'character_media')
    character_ids = {r['local_id'] for r in character_rows}
    group_rows = [g for g in _rows(db, 'canvas_asset_groups') if not archived_project(g['project_id'])]
    group_members = {i for g in group_rows for i in _json(g['asset_ids'], [])}
    run_nodes = _rows(db, 'canvas_group_run_nodes', '''SELECT n.*, r.workflow_id FROM canvas_group_run_nodes n
        JOIN canvas_group_runs r ON r.id=n.run_id''') if _has(db, 'canvas_group_runs') else []
    run_refs, active_run_refs = set(), set()
    for n in run_nodes:
        refs = {('workflow', i) for i in _json(n['base_assets'], []) + ([n['result_asset_id']] if n['result_asset_id'] else [])}
        run_refs |= refs
        if not archived_workflow(n['workflow_id']):
            active_run_refs |= refs
    base_refs = {('workflow', i) for refs in doc_refs.values() for i in refs} | {('local', i) for i in character_ids} | \
        {('library', i) for i in group_members}
    referenced = base_refs | run_refs
    # Anything still used by live data blocks the purge of archived-only copies (S6b).
    live_referenced = base_refs | active_run_refs

    local_sources = {}
    for r in _rows(db, 'canvas_local_sources'):
        local_sources.setdefault(r['local_id'], []).append(r['source_key'])
    copies = {}
    for r in _rows(db, 'canvas_asset_copies'):
        copies.setdefault(r['asset_id'], []).append(r['source_key'])
    uploaded = {r['item_key'] for r in _rows(db, 'canvas_catalog_origins') if r['origin'] == 'uploaded'}
    task_asset_task = {r['id']: r['task_id'] for r in _rows(db, 'task_assets', 'SELECT id, task_id FROM task_assets')}

    members, skipped, purge = [], {}, []

    def skip(reason, ident, size=0):
        entry = skipped.setdefault(reason, {'count': 0, 'bytes': 0, 'samples': []})
        entry['count'] += 1
        entry['bytes'] += size or 0
        if len(entry['samples']) < 20:
            entry['samples'].append(ident)

    def task_of(keys):
        found = [task_asset_task.get(int(k[5:])) for k in keys if k.startswith('task:') and k[5:].isdigit()]
        found = [t for t in found if t]
        return min(found) if found else None

    def add(scope, cls, row, path, kind, evidence, excluded=None, task_id=None, name=None, created_at=None, sha=None):
        members.append({
            'scope': scope, 'cls': cls, 'old_id': str(row['id']), 'key': f"{scope}:{row['id']}", 'kind': kind,
            'mime_type': row.get('mime_type'), 'name': name if name is not None else row.get('name'),
            'sha256': sha or row.get('sha256'), 'size': row.get('size_bytes') or 0,
            'created_at': created_at or row.get('created_at'), 'path': str(path), 'file_ok': _file_ok(path),
            'evidence': evidence, 'excluded': excluded, 'task_id': task_id})

    for row in _rows(db, 'canvas_local_uploads'):
        keys = local_sources.get(row['id'], [])
        joined = bool(keys)
        evidence = 'generated' if any(k.startswith('task:') for k in keys) else (None if joined else 'upload')
        excluded = 'hidden' if f"local:{row['id']}" in hidden and row['id'] not in character_ids else None
        add('local', 'local_joined' if joined else 'local', row, asset_root / 'local_uploads' / row['filename'],
            row['kind'], evidence, excluded, task_of(keys))
    for row in _rows(db, 'canvas_library_assets'):
        excluded = None
        if row['id'] in removed_library:
            excluded = 'removed'
        elif archived_project(row['project_id']):
            excluded = None if include_archived else 'archived'
        elif f"library:{row['id']}" in hidden and row['id'] not in group_members:
            excluded = 'hidden'
        add('library', 'library', row, asset_root / 'library' / row['project_id'] / row['filename'], row['kind'], 'upload', excluded)
    for row in _rows(db, 'canvas_assets'):
        wid = row['workflow_id']
        keys = copies.get(row['id'], [])
        if f"workflow:{row['id']}" in uploaded:
            cls, evidence = 'canvas_upload', 'upload'
        else:
            cls = 'workflow'
            evidence = 'generated' if any(k.startswith('task:') for k in keys) or row['id'] in generated_ids.get(wid, ()) else None
        excluded = None if include_archived or not archived_workflow(wid) else 'archived'
        add('workflow', cls, row, asset_root / wid / row['filename'], row['kind'], evidence, excluded, task_of(keys))

    # Task outputs: every succeeded image/video/audio task, trash included (Q5).
    tasks_by_id = {r['id']: r for r in _rows(db, 'tasks', 'SELECT id, type, status, params, result, deleted_at FROM tasks')}
    outputs = {}
    for row in _rows(db, 'task_assets', "SELECT * FROM task_assets WHERE kind IN ('output_image','output_video','output_audio')"):
        outputs.setdefault(row['task_id'], []).append(row)
    from result_names import result_display_name, task_result_name
    trash = 0
    for task in tasks_by_id.values():
        result = _json(task['result'], {})
        if task['status'] in ACTIVE_TASK_STATUSES:
            skip('task_active', task['id'])
            continue
        if task['status'] == 'failed':
            skip('task_result_unknown' if result.get('result_unknown') else 'task_failed', task['id'])
            continue
        if task['status'] == 'cancelled':
            skip('task_cancelled', task['id'])
            continue
        if task['status'] != 'succeeded':
            skip('task_other_status', task['id'])
            continue
        if task['type'] not in GENERATION_TYPES:
            skip('task_layer' if task['type'] == 'layer' else 'task_other_type', task['id'])
            continue
        rows = outputs.get(task['id'], [])
        if not rows:
            skip('task_remote_only', task['id'])
            continue
        params = _json(task['params'], {})
        for out in sorted(rows, key=lambda r: r['id']):
            path = Path(out['path'])
            if not _file_ok(path):
                skip('task_file_missing', f"task_asset:{out['id']}", out['size_bytes'])
                continue
            sha, size = digest(path)
            name = result_display_name(task_result_name(params), task['id'], path.name) or path.name
            add('task', 'task', {**out, 'size_bytes': size}, path, OUTPUT_KINDS[out['kind']], 'generated',
                task_id=task['id'], name=name, sha=sha)
            if task['deleted_at']:
                trash += 1
    for row in _rows(db, 'task_assets', "SELECT id FROM task_assets WHERE kind IN ('output_image','output_video','output_audio') AND task_id IS NULL"):
        skip('task_deleted', f"task_asset:{row['id']}")

    if verify_hashes:
        for m in members:
            if m['file_ok'] and m['scope'] != 'task' and digest(m['path'])[0] != m['sha256']:
                m['file_ok'] = False
                m['hash_mismatch'] = True

    existing = {r['sha256']: r for r in _rows(db, 'media')}
    prior = {(r['scope'], r['old_id']): r['media_id'] for r in _rows(db, 'media_aliases')}
    taken = {r['id'] for r in _rows(db, 'media')} | {r['id'] for r in _rows(db, 'media_tombstones')}
    by_sha = {}
    for m in members:
        by_sha.setdefault(m['sha256'], []).append(m)
    groups = []
    for sha, group in sorted(by_sha.items(), key=lambda item: min(m['created_at'] or '' for m in item[1])):
        live = [m for m in group if not m['excluded']]
        if not live:
            # User decision 2026-11-16 (S1b dry run): copies owned only by deleted (archived) canvases or
            # projects are not imported but removed together with their old rows; missing files only lose the row.
            if not include_archived and all(m['excluded'] == 'archived' for m in group) and \
                    not any((m['scope'], m['old_id']) in live_referenced for m in group):
                purge.extend({k: m[k] for k in ('scope', 'old_id', 'key', 'path', 'file_ok', 'size')} for m in group)
                continue
            for m in group:
                reason = 'archived_referenced' if m['excluded'] == 'archived' and not include_archived else m['excluded']
                skip(f"excluded_{reason}", m['key'], m['size'])
            continue
        live.sort(key=lambda m: (PRIORITY[m['cls']], m['created_at'] or '', m['key']))
        keeper = live[0]
        upload = [m for m in live if m['evidence'] == 'upload']
        generated = any(m['evidence'] == 'generated' for m in live)
        sources = [m for m in live if m['file_ok']] + [m for m in group if m['excluded'] and m['file_ok']]
        is_referenced = any((m['scope'], m['old_id']) in referenced for m in group)
        tombstone = not sources
        if tombstone and not is_referenced:
            for m in live:
                skip('file_missing', m['key'], m['size'])
            continue
        current = existing.get(sha)
        # Resume: an alias written by an interrupted run fixes the id (tombstones have no sha row).
        media_id = current['id'] if current else prior.get((keeper['scope'], keeper['old_id'])) or (
            keeper['old_id'] if keeper['scope'] != 'task' else deterministic_id(sha))
        if not current and (keeper['scope'], keeper['old_id']) not in prior and media_id in taken and keeper['scope'] != 'task':
            media_id = deterministic_id(sha)
        folder = ('generated_' + keeper['kind']) if generated and not upload else None
        origin = 'generated' if folder else (ORIGIN[upload[0]['cls']] if upload else
                                             ORIGIN[keeper['cls']] if keeper['cls'] != 'task' else 'legacy_workflow')
        task_ids = [m['task_id'] for m in group if m['task_id']]
        groups.append({
            'sha256': sha, 'media_id': media_id, 'existing': bool(current), 'tombstone': tombstone,
            'kind': keeper['kind'], 'mime_type': keeper['mime_type'], 'folder': folder, 'origin': origin,
            'name': clean_name(keeper['name'], Path(keeper['path']).name), 'size': keeper['size'],
            'created_at': min(m['created_at'] for m in live if m['created_at']),
            'source_task_id': min(task_ids) if task_ids else None, 'keeper': keeper['key'],
            'members': [{k: m[k] for k in ('scope', 'old_id', 'key', 'cls', 'excluded', 'file_ok', 'path')} for m in group],
            'sources': [m['path'] for m in sources], 'referenced': is_referenced})
        for m in group:
            if m.get('hash_mismatch'):
                skip('hash_mismatch', m['key'], m['size'])
            elif not m['file_ok'] and not tombstone:
                skip('member_file_missing_aliased', m['key'], m['size'])
    alias = {(m['scope'], m['old_id']): g['media_id'] for g in groups for m in g['members']}
    tombstoned = {g['media_id'] for g in groups if g['tombstone']}

    documents = []
    for wid, document in active_docs.items():
        refs = doc_refs[wid]
        mapped = {i for i in refs if ('workflow', i) in alias}
        changed = {i for i in mapped if alias[('workflow', i)] != i}
        unresolved = sorted(refs - mapped)
        if mapped or unresolved:
            documents.append({'workflow_id': wid, 'title': workflows[wid]['title'], 'project_id': workflows[wid]['project_id'],
                              'refs': len(refs), 'mapped': len(mapped), 'id_changed': len(changed),
                              'tombstoned': len({alias[('workflow', i)] for i in mapped} & tombstoned), 'unresolved': unresolved[:20],
                              'nodes': sum(1 for n in document.get('nodes', []) if isinstance(n, dict) and document_ids({'nodes': [n]}) & mapped)})
    archived_docs = [wid for wid in workflows if wid not in active_docs and any(
        ('workflow', i) in alias for i in document_ids(_json(workflows[wid]['document'], {})))]
    char_changes = [r for r in character_rows if alias.get(('local', r['local_id']), r['local_id']) != r['local_id']]
    char_unmapped = [r for r in character_rows if ('local', r['local_id']) not in alias]
    group_plan = []
    for g in group_rows:
        ids = _json(g['asset_ids'], [])
        kept = list(dict.fromkeys(alias[('library', i)] for i in ids if ('library', i) in alias and alias[('library', i)] not in tombstoned))
        group_plan.append({'id': g['id'], 'title': g['title'], 'project_id': g['project_id'], 'members': len(ids),
                           'kept': len(kept), 'media_ids': kept, 'created_at': g['created_at']})
    run_changes = 0
    for n in run_nodes:
        ids = _json(n['base_assets'], []) + ([n['result_asset_id']] if n['result_asset_id'] else [])
        run_changes += any(alias.get(('workflow', i), i) != i for i in ids)
    return {
        'asset_root': str(asset_root), 'include_archived': include_archived, 'groups': groups, 'skipped': skipped,
        'archived_purge': purge,
        'alias_count': len(alias), 'documents': documents, 'archived_documents': len(archived_docs),
        'characters': {'rows': len(character_rows), 'changed': len(char_changes), 'unmapped': len(char_unmapped)},
        'asset_groups': group_plan, 'run_nodes': {'rows': len(run_nodes), 'changed': run_changes},
        'trash_outputs': trash,
        'tags': {'tags': len(_rows(db, 'canvas_catalog_tags')), 'item_tags': len(_rows(db, 'canvas_catalog_item_tags'))},
        'project_folders': {'folders': len(_rows(db, 'canvas_library_folders')), 'locations': len(_rows(db, 'canvas_library_asset_locations'))},
        'local_sources': len(_rows(db, 'canvas_local_sources')),
    }


def summarize(plan):
    """Compact, reviewable dry-run list (counts, bytes, skips, dedup groups, affected documents)."""
    by_target, by_member = {}, {}
    for g in plan['groups']:
        target = 'tombstone' if g['tombstone'] else (g['folder'] or 'root')
        entry = by_target.setdefault(target, {'count': 0, 'bytes': 0, 'existing': 0})
        entry['count'] += 1
        entry['bytes'] += 0 if g['tombstone'] else g['size']
        entry['existing'] += g['existing']
        for m in g['members']:
            by_member[m['cls']] = by_member.get(m['cls'], 0) + 1
    dedup = [{'sha256': g['sha256'][:12], 'media_id': g['media_id'], 'kind': g['kind'], 'target': g['folder'] or 'root',
              'keeper': g['keeper'], 'members': [m['key'] + ('(excluded:' + m['excluded'] + ')' if m['excluded'] else '') for m in g['members']]}
             for g in plan['groups'] if len(g['members']) > 1]
    id_changed = sum(1 for g in plan['groups'] for m in g['members'] if m['old_id'] != g['media_id'])
    purge = plan.get('archived_purge', [])
    present = [m for m in purge if m['file_ok']]
    archived_purge = {'count': len(purge), 'files': len(present), 'bytes': sum(m['size'] for m in present),
                      'missing_files': len(purge) - len(present),
                      'by_scope': {s: sum(1 for m in purge if m['scope'] == s) for s in sorted({m['scope'] for m in purge})},
                      'samples': [m['key'] for m in purge[:20]]}
    return {
        'media_to_create_or_reuse': by_target, 'members_by_source': by_member, 'trash_task_outputs': plan['trash_outputs'],
        'skipped': plan['skipped'], 'archived_purge': archived_purge, 'dedup_groups': len(dedup), 'dedup': dedup[:50],
        'aliases': plan['alias_count'], 'aliases_id_changed': id_changed,
        'documents': plan['documents'], 'archived_documents_not_rewritten': plan['archived_documents'],
        'characters': plan['characters'], 'asset_groups': [{k: g[k] for k in ('id', 'title', 'members', 'kept')} for g in plan['asset_groups']],
        'run_nodes': plan['run_nodes'], 'tags_to_delete': plan['tags'], 'project_folders_to_delete': plan['project_folders'],
        'local_sources_to_alias_and_delete': plan['local_sources'], 'include_archived': plan['include_archived'],
    }


def format_summary(summary):
    mib = lambda n: f'{n / 1048576:.2f}MiB'  # noqa: E731
    lines = ['== 全局素材库迁移清单 ==' + ('（含归档）' if summary['include_archived'] else '（不含归档画布/项目独有素材）')]
    for target, e in sorted(summary['media_to_create_or_reuse'].items()):
        lines.append(f"入库 {target}: {e['count']} 项 {mib(e['bytes'])}（已存在复用 {e['existing']}）")
    lines.append('来源成员: ' + '，'.join(f'{k}={v}' for k, v in sorted(summary['members_by_source'].items())) +
                 f"；其中回收站任务输出 {summary['trash_task_outputs']}")
    lines.append(f"去重组(>1来源): {summary['dedup_groups']}；别名 {summary['aliases']}（id 改变 {summary['aliases_id_changed']}）")
    for reason, e in sorted(summary['skipped'].items()):
        lines.append(f"跳过 {reason}: {e['count']} {mib(e['bytes'])} 例 {', '.join(map(str, e['samples'][:5]))}")
    purge = summary['archived_purge']
    lines.append(f"清理 已删除画布/项目独有副本（不入库，--apply 删除文件与旧记录）: {purge['count']} 项，"
                 f"文件 {purge['files']} 个 {mib(purge['bytes'])}，缺文件仅清记录 {purge['missing_files']}；"
                 + '，'.join(f'{k}={v}' for k, v in purge['by_scope'].items()))
    for d in summary['documents']:
        lines.append(f"画布文档 {d['title']}({d['workflow_id'][:8]}): 引用 {d['refs']} 映射 {d['mapped']} 改id {d['id_changed']} "
                     f"已删除占位 {d['tombstoned']} 节点 {d['nodes']} 未解析 {len(d['unresolved'])}")
    lines.append(f"归档画布文档（不改写，保存时规范化）: {summary['archived_documents_not_rewritten']}")
    lines.append(f"角色素材 {summary['characters']}；组运行节点 {summary['run_nodes']}")
    lines.append(f"项目素材组→全局组: {len(summary['asset_groups'])} " + '; '.join(f"{g['title']} {g['kept']}/{g['members']}" for g in summary['asset_groups']))
    lines.append(f"删除标签 {summary['tags_to_delete']}；取消项目文件夹 {summary['project_folders_to_delete']}；"
                 f"canvas_local_sources 转别名后删除 {summary['local_sources_to_alias_and_delete']}")
    for g in summary['dedup'][:20]:
        lines.append(f"  去重 {g['sha256']} {g['kind']} -> {g['target']} keep {g['keeper']} ← {', '.join(g['members'])}")
    return '\n'.join(lines)


# ---------------------------------------------------------------- backup / preflight

def fingerprint(db):
    def scalar(table, sql):
        return db.execute(sql).fetchone()[0] if _has(db, table) else 0
    return {
        'tasks': scalar('tasks', 'SELECT COUNT(*) || ":" || COALESCE(MAX(id),0) || ":" || COALESCE(MAX(updated_at),"") FROM tasks'),
        'task_assets': scalar('task_assets', 'SELECT COUNT(*) || ":" || COALESCE(MAX(id),0) FROM task_assets'),
        'canvas_assets': scalar('canvas_assets', 'SELECT COUNT(*) FROM canvas_assets'),
        'canvas_library_assets': scalar('canvas_library_assets', 'SELECT COUNT(*) FROM canvas_library_assets'),
        'canvas_local_uploads': scalar('canvas_local_uploads', 'SELECT COUNT(*) FROM canvas_local_uploads'),
        'canvas_workflows': scalar('canvas_workflows', 'SELECT COUNT(*) || ":" || COALESCE(SUM(revision),0) FROM canvas_workflows'),
        'media': scalar('media', 'SELECT COUNT(*) FROM media'),
    }


def _snapshot_tree(source, target, lines, label):
    source = Path(source)
    if not source.is_dir():
        return 0
    count = 0
    for directory, _, files in os.walk(source):
        for name in sorted(files):
            path = Path(directory) / name
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(source)
            destination = Path(target) / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(path, destination)
            except OSError:
                shutil.copy2(path, destination)
            lines.append(f'{digest(destination)[0]}  {label}/{relative.as_posix()}')
            count += 1
    return count


def make_backup(db_path, asset_root, output_dir, dest):
    """sqlite .backup + hard-link snapshot (copy across file systems) + sha256 list; manifest last."""
    dest = Path(dest).absolute()
    dest.mkdir(parents=True, exist_ok=False)
    source = sqlite3.connect(f'file:{Path(db_path).absolute()}?mode=ro', uri=True)
    target = sqlite3.connect(dest / 'tasks.db')
    try:
        source.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise MigrationError('备份库完整性检查失败')
        target.row_factory = sqlite3.Row
        snapshot_fingerprint = fingerprint(target)
    finally:
        target.close()
        source.close()
    lines = []
    files = {'canvas_assets': _snapshot_tree(asset_root, dest / 'canvas_assets', lines, 'canvas_assets'),
             'output': _snapshot_tree(output_dir, dest / 'output', lines, 'output')}
    (dest / 'sha256sums.txt').write_text('\n'.join(lines) + ('\n' if lines else ''))
    manifest = {'id': uuid.uuid4().hex, 'db_path': str(Path(db_path).resolve()), 'asset_root': str(Path(asset_root).absolute()),
                'output_dir': str(Path(output_dir).absolute()), 'created_at': datetime.now(timezone.utc).isoformat(),
                'fingerprint': snapshot_fingerprint, 'files': files, 'complete': True}
    temporary = dest / 'manifest.json.tmp'
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    os.replace(temporary, dest / 'manifest.json')
    return manifest


def _state(db):
    if not _has(db, 'media_meta'):
        return {}
    row = db.execute('SELECT value FROM media_meta WHERE key=?', (STATE_KEY,)).fetchone()
    return _json(row[0], {}) if row else {}


def preflight(db, db_path, backup_dir, now=None):
    """Blockers for --apply: active work, running Worker, missing/stale backup."""
    blockers, warnings = [], []
    now = now or datetime.now(timezone.utc)
    active = db.execute(f"SELECT COUNT(*) FROM tasks WHERE status IN ({','.join('?' * len(ACTIVE_TASK_STATUSES))})",
                        ACTIVE_TASK_STATUSES).fetchone()[0]
    if active:
        blockers.append(f'存在 {active} 个活动任务')
    if _has(db, 'canvas_group_runs'):
        runs = db.execute(f"SELECT COUNT(*) FROM canvas_group_runs WHERE status IN ({','.join('?' * len(ACTIVE_RUN_STATUSES))})",
                          ACTIVE_RUN_STATUSES).fetchone()[0]
        if runs:
            blockers.append(f'存在 {runs} 个进行中的组运行')
        pending = db.execute("""SELECT COUNT(*) FROM canvas_group_run_nodes n JOIN canvas_group_runs r ON r.id=n.run_id
            WHERE r.finished_at IS NULL AND n.status IN ('submitting','submitted','unknown')""").fetchone()[0]
        if pending:
            blockers.append(f'存在 {pending} 个组运行节点待提交或结果未知待核')
    unknown = sum(1 for r in db.execute("SELECT result FROM tasks WHERE status='failed'") if _json(r[0], {}).get('result_unknown'))
    if unknown:
        warnings.append(f'{unknown} 个 result_unknown 任务不入库（核定成功后由正常流程入库），请确认已核对')
    if _has(db, 'worker_heartbeats'):
        for r in db.execute('SELECT worker_id, last_seen_at FROM worker_heartbeats'):
            try:
                seen = datetime.fromisoformat(r[1])
            except (TypeError, ValueError):
                continue
            if now - seen < timedelta(seconds=HEARTBEAT_SECONDS):
                blockers.append(f'Worker {r[0]} 心跳仍在更新（{r[1]}），请先停 Web 与 Worker')
    manifest = None
    if not backup_dir:
        blockers.append('缺少 --backup-dir（先用 --make-backup 生成备份）')
    else:
        path = Path(backup_dir) / 'manifest.json'
        manifest = _json(path.read_text(), {}) if path.is_file() else {}
        if not manifest.get('complete') or not (Path(backup_dir) / 'tasks.db').is_file():
            blockers.append(f'备份不完整或不存在：{backup_dir}')
        elif manifest.get('db_path') != str(Path(db_path).resolve()):
            blockers.append('备份不是本数据库的备份')
        else:
            state = _state(db)
            resuming = state.get('backup_id') == manifest.get('id')
            created = datetime.fromisoformat(manifest['created_at'])
            if not resuming and now - created > BACKUP_MAX_AGE:
                blockers.append('备份已超过24小时，请重新备份')
            if not resuming and manifest.get('fingerprint') != fingerprint(db):
                blockers.append('备份后数据库已有变化，请重新备份')
    return blockers, warnings, manifest


# ---------------------------------------------------------------- apply

def _detect(path):
    import canvas_store as store
    try:
        return store._detect_media(Path(path))
    except store.CanvasError as error:
        if error.status >= 500:
            raise MigrationError(str(error)) from error
        return None


def _choose_source(group):
    """First source whose bytes match the group hash and whose media type is supported."""
    for path in group['sources']:
        if not _file_ok(path):
            continue
        if digest(path)[0] != group['sha256']:
            continue
        detected = _detect(path)
        if detected:
            return Path(path), detected
    return None, None


def _link(source, target, sha256):
    if target.exists():
        if digest(target)[0] == sha256:
            return False  # left by an interrupted run; reuse it
        target.unlink()
    try:
        os.link(source, target)
    except OSError:
        temporary = target.with_name(target.name + '.tmp')
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return True


def _import_group(group, report):
    import canvas_store as store
    import media_library as library
    source, detected = (None, None) if group['tombstone'] else _choose_source(group)
    with store.write_transaction() as db:
        current = db.execute('SELECT * FROM media WHERE sha256=?', (group['sha256'],)).fetchone()
        if current is not None:
            media_id = current['id']
            in_system = current['folder_id'] and db.execute('SELECT system_key FROM media_folders WHERE id=?', (current['folder_id'],)).fetchone()['system_key']
            if in_system and group['folder'] is None:
                # Q6: content that is also an upload leaves 生成历史 and keeps the upload identity.
                db.execute('UPDATE media SET folder_id=NULL, origin=? WHERE id=?', (group['origin'], media_id))
                report['moved_to_root'] += 1
            report['reused'] += 1
        else:
            media_id = group['media_id']
            if db.execute('SELECT 1 FROM media WHERE id=? UNION SELECT 1 FROM media_tombstones WHERE id=?', (media_id, media_id)).fetchone() \
                    and not (group['tombstone'] and db.execute('SELECT 1 FROM media_tombstones WHERE id=?', (media_id,)).fetchone()):
                media_id = deterministic_id(group['sha256'])
                if db.execute('SELECT 1 FROM media WHERE id=? UNION SELECT 1 FROM media_tombstones WHERE id=?', (media_id, media_id)).fetchone():
                    media_id = uuid.uuid4().hex
            if group['tombstone'] or source is None:
                if not group['referenced']:
                    report['skipped_unreadable'].append(group['keeper'])
                    return None
                # Referenced content without any readable file becomes a "已删除" placeholder.
                db.execute('INSERT OR IGNORE INTO media_tombstones VALUES (?,?,?,?,?,?,?)',
                           (media_id, group['name'], group['kind'], group['mime_type'] or 'application/octet-stream',
                            group['origin'], group['source_task_id'], tasks_now()))
                report['tombstones'] += 1
            else:
                mime, extension = detected
                kind = mime.split('/')[0]
                folder = library.system_folder_id('generated_' + kind) if group['folder'] else None
                target = library.root() / (media_id + extension)
                if _link(source, target, group['sha256']):
                    library._journal(db, media_id, target)
                db.execute('INSERT INTO media VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                           (media_id, group['sha256'], target.name, folder, group['name'], mime, kind,
                            target.stat().st_size, group['origin'], group['source_task_id'], group['created_at'] or tasks_now()))
                report['created'] += 1
        for member in group['members']:
            db.execute('INSERT OR IGNORE INTO media_aliases VALUES (?,?,?,?)', (member['scope'], member['old_id'], media_id, tasks_now()))
            if member['scope'] == 'task':
                db.execute('UPDATE task_assets SET media_id=? WHERE id=? AND media_id IS NOT ?', (media_id, int(member['old_id']), media_id))
    return media_id


def tasks_now():
    import tasks
    return tasks.utcnow()


def _rewrite_documents(report):
    """Map old canvas asset ids to media ids in active documents (rev+1 only when changed)."""
    import canvas_store as store
    import tasks
    db = tasks.get_db()
    ids = [r['id'] for r in db.execute('''SELECT id FROM canvas_workflows w WHERE
        NOT EXISTS (SELECT 1 FROM canvas_deletions d WHERE d.scope='workflow' AND d.id=w.id) AND
        NOT EXISTS (SELECT 1 FROM canvas_deletions d WHERE d.scope='project' AND d.id=w.project_id)''')]
    for workflow_id in ids:
        try:
            with store.write_transaction() as db:
                row = db.execute('SELECT document FROM canvas_workflows WHERE id=?', (workflow_id,)).fetchone()
                encoded = store.validate_document(json.loads(row['document']), workflow_id)
                if json.loads(encoded) != json.loads(row['document']):
                    now = tasks.utcnow()
                    db.execute('UPDATE canvas_workflows SET document=?, revision=revision+1, updated_at=? WHERE id=?', (encoded, now, workflow_id))
                    report['documents_rewritten'] += 1
        except store.CanvasError as error:
            report['documents_failed'].append({'workflow_id': workflow_id, 'error': str(error)})


def _rewrite_references(plan, report):
    import canvas_store as store
    import media_library as library

    def alias(db, scope, old):
        row = db.execute('SELECT media_id FROM media_aliases WHERE scope=? AND old_id=?', (scope, old)).fetchone()
        return row[0] if row else None

    with store.write_transaction() as db:
        for row in db.execute('SELECT * FROM character_media').fetchall():
            new = alias(db, 'local', row['local_id'])
            if new and new != row['local_id']:
                if db.execute('SELECT 1 FROM character_media WHERE character_id=? AND local_id=?', (row['character_id'], new)).fetchone():
                    db.execute('DELETE FROM character_media WHERE character_id=? AND local_id=?', (row['character_id'], row['local_id']))
                else:
                    db.execute('UPDATE character_media SET local_id=? WHERE character_id=? AND local_id=?', (new, row['character_id'], row['local_id']))
                report['characters_rewritten'] += 1
        for row in db.execute('SELECT n.*, r.workflow_id FROM canvas_group_run_nodes n JOIN canvas_group_runs r ON r.id=n.run_id').fetchall():
            base = _json(row['base_assets'], [])
            mapped = [alias(db, 'workflow', i) or i for i in base]
            result = alias(db, 'workflow', row['result_asset_id']) or row['result_asset_id'] if row['result_asset_id'] else None
            if mapped != base or result != row['result_asset_id']:
                db.execute('UPDATE canvas_group_run_nodes SET base_assets=?, result_asset_id=? WHERE run_id=? AND node_id=?',
                           (json.dumps(mapped), result, row['run_id'], row['node_id']))
                report['run_nodes_rewritten'] += 1
    for group in plan['asset_groups']:
        with store.write_transaction() as db:
            if db.execute('SELECT 1 FROM media_groups WHERE id=?', (group['id'],)).fetchone():
                continue
            live = [m for m in group['media_ids'] if db.execute('SELECT 1 FROM media WHERE id=?', (m,)).fetchone()]
            if not live:
                report['asset_groups_empty'].append(group['id'])
                continue
            title = (group['title'] or '素材组').strip()[:120] or '素材组'
            library.create_group(title, live[:library.MAX_GROUP], group_id=group['id'] if library.MEDIA_ID.fullmatch(group['id']) else None,
                                 created_at=group['created_at'])
            report['asset_groups_created'] += 1


def _finalize_tables(report):
    import canvas_store as store
    with store.write_transaction() as db:
        if _has(db, 'canvas_local_sources'):
            for row in db.execute('SELECT * FROM canvas_local_sources').fetchall():
                media_id = db.execute("SELECT media_id FROM media_aliases WHERE scope='local' AND old_id=?", (row['local_id'],)).fetchone()
                scope, _, old = row['source_key'].partition(':')
                if media_id and scope in ('task', 'workflow', 'local', 'library') and old:
                    db.execute('INSERT OR IGNORE INTO media_aliases VALUES (?,?,?,?)', (scope, old, media_id[0], tasks_now()))
            report['local_sources_deleted'] = db.execute('DELETE FROM canvas_local_sources').rowcount
        for table in ('canvas_catalog_item_tags', 'canvas_catalog_tags'):
            if _has(db, table):
                report['tags_deleted'] += db.execute(f'DELETE FROM {table}').rowcount
        for table in ('canvas_library_asset_locations', 'canvas_library_folder_icons', 'canvas_library_folders'):
            if _has(db, table):
                report['project_folders_deleted'] += db.execute(f'DELETE FROM {table}').rowcount


def _purge_archived(plan, report):
    """Delete archived-only copies (file first, then the old rows) so an interrupted run simply repeats.

    The backup snapshot keeps hard links of every file, so rollback still restores them.
    """
    import canvas_store as store
    import tasks
    purge = plan.get('archived_purge', [])
    if not purge:
        return
    root = store.asset_root().absolute()
    db = tasks.get_db()
    keep = {m['path'] for g in plan['groups'] for m in g['members']}
    keep |= {r[0] for r in db.execute('SELECT path FROM task_assets WHERE path IS NOT NULL')}
    removable = []
    for m in purge:
        path = Path(m['path'])
        safe = path.is_absolute() and path.resolve() == path and path.is_relative_to(root) and \
            not path.is_relative_to(root / 'media') and m['path'] not in keep
        if m['file_ok'] and not safe:
            report['archived_purge_retained'].append(m['key'])
            continue
        removable.append(m)
    for m in removable:
        if m['file_ok']:
            try:
                Path(m['path']).unlink(missing_ok=True)
            except OSError as error:
                raise MigrationError(f"清理归档副本文件失败：{m['key']}（{error}）") from error
            report['archived_files_removed'] += 1
            report['archived_bytes_removed'] += m['size'] or 0
    with store.write_transaction() as db:
        for m in removable:
            key = m['key']
            if m['scope'] == 'workflow':
                db.execute('DELETE FROM canvas_asset_copies WHERE asset_id=?', (m['old_id'],))
                deleted = db.execute('DELETE FROM canvas_assets WHERE id=?', (m['old_id'],)).rowcount
            elif m['scope'] == 'library':
                if _has(db, 'canvas_library_asset_locations'):
                    db.execute('DELETE FROM canvas_library_asset_locations WHERE asset_id=?', (m['old_id'],))
                deleted = db.execute('DELETE FROM canvas_library_assets WHERE id=?', (m['old_id'],)).rowcount
            else:
                continue
            for table in ('canvas_catalog_origins', 'canvas_catalog_hidden', 'canvas_catalog_item_tags'):
                if _has(db, table):
                    db.execute(f'DELETE FROM {table} WHERE item_key=?', (key,))
            if _has(db, 'canvas_asset_copies'):
                db.execute('DELETE FROM canvas_asset_copies WHERE source_key=?', (key,))
            report['archived_rows_removed'] += deleted


def verify(db, plan=None):
    """Post-migration checks: media files and hashes, active documents valid, task outputs linked."""
    import canvas_store as store
    import media_library as library
    problems = []
    for row in db.execute('SELECT * FROM media').fetchall():
        path = library.root() / row['relpath']
        if not path.is_file():
            problems.append(f"media {row['id']} 文件缺失")
        elif digest(path)[0] != row['sha256']:
            problems.append(f"media {row['id']} 哈希不符")
    for row in db.execute('''SELECT id, document FROM canvas_workflows w WHERE
            NOT EXISTS (SELECT 1 FROM canvas_deletions d WHERE d.scope='workflow' AND d.id=w.id) AND
            NOT EXISTS (SELECT 1 FROM canvas_deletions d WHERE d.scope='project' AND d.id=w.project_id)''').fetchall():
        try:
            encoded = store.validate_document(json.loads(row['document']), row['id'])
        except store.CanvasError as error:
            problems.append(f"画布 {row['id']} 文档校验失败：{error}")
            continue
        if json.loads(encoded) != json.loads(row['document']):
            problems.append(f"画布 {row['id']} 仍含未规范化的旧素材编号")
    if plan:
        for group in plan['groups']:
            for m in group['members']:
                if m['scope'] == 'task' and not db.execute('SELECT media_id FROM task_assets WHERE id=?', (int(m['old_id']),)).fetchone()[0]:
                    problems.append(f"task_asset {m['old_id']} 未关联 media")
    return problems


def apply(db_path, backup_dir, include_archived=False, log=print, fail_after=None):
    """Execute the migration. ``fail_after`` (tests) aborts after N content groups to exercise resume."""
    import canvas_store as store
    import tasks
    tasks.init_db()
    db = tasks.get_db()
    blockers, warnings, manifest = preflight(db, db_path, backup_dir)
    for warning in warnings:
        log('警告：' + warning)
    if blockers:
        raise MigrationError('；'.join(blockers))
    state = _state(db)
    db.execute('INSERT OR REPLACE INTO media_meta VALUES (?,?)', (STATE_KEY, json.dumps({
        'state': 'running', 'backup_id': manifest['id'], 'backup_dir': str(Path(backup_dir).absolute()),
        'started_at': state.get('started_at') or tasks.utcnow(), 'resumed': bool(state)}, ensure_ascii=False)))
    db.commit()
    plan = build_plan(db, store.asset_root(), include_archived=include_archived)
    report = {'created': 0, 'reused': 0, 'moved_to_root': 0, 'tombstones': 0, 'skipped_unreadable': [],
              'documents_rewritten': 0, 'documents_failed': [], 'characters_rewritten': 0, 'run_nodes_rewritten': 0,
              'asset_groups_created': 0, 'asset_groups_empty': [], 'local_sources_deleted': 0, 'tags_deleted': 0,
              'project_folders_deleted': 0, 'archived_files_removed': 0, 'archived_bytes_removed': 0,
              'archived_rows_removed': 0, 'archived_purge_retained': []}
    # Upload-class content first, then generation results (contract note 4).
    ordered = sorted(plan['groups'], key=lambda g: (g['folder'] is not None, g['created_at'] or ''))
    for index, group in enumerate(ordered):
        if fail_after is not None and index >= fail_after:
            raise MigrationError('测试中断')
        _import_group(group, report)
    _rewrite_documents(report)
    _rewrite_references(plan, report)
    _finalize_tables(report)
    _purge_archived(plan, report)
    problems = verify(db, plan)
    report['problems'] = problems
    _record_baseline(db)
    state = 'done' if not problems and not report['documents_failed'] else 'needs_review'
    db.execute('INSERT OR REPLACE INTO media_meta VALUES (?,?)', (STATE_KEY, json.dumps({
        'state': state, 'backup_id': manifest['id'], 'backup_dir': str(Path(backup_dir).absolute()),
        'finished_at': tasks.utcnow(), 'report': {k: v if not isinstance(v, list) else len(v) for k, v in report.items()}}, ensure_ascii=False)))
    db.commit()
    return report


def new_media_since(db, finished_at):
    """For rollback: media created after the migration (export before restoring the backup)."""
    return [dict(r) for r in db.execute('SELECT id, name, relpath, origin, folder_id, created_at FROM media WHERE created_at > ? ORDER BY created_at', (finished_at,))]


# ---------------------------------------------------------------- rollback export (S9 O2)
# ``apply`` records the library state it finished with; ``changes_since`` diffs the current
# state against it so a rollback can carry over what users did afterwards (new media files,
# moves, renames, deletions, folders and groups). The backup itself predates the migration.

BASELINE_TABLE = 'media_migration_baseline'


def _library_state(db):
    media_rows = {r['id']: {'name': r['name'], 'folder_id': r['folder_id'], 'kind': r['kind'], 'relpath': r['relpath'],
                            'sha256': r['sha256'], 'origin': r['origin'], 'created_at': r['created_at']}
                  for r in db.execute('SELECT * FROM media')}
    folders = {r['id']: {'title': r['title'], 'parent_id': r['parent_id'], 'icon': r['icon'], 'system_key': r['system_key']}
               for r in db.execute('SELECT * FROM media_folders')}
    groups = {}
    for r in db.execute('SELECT * FROM media_groups'):
        members = [m[0] for m in db.execute('SELECT media_id FROM media_group_members WHERE group_id=? ORDER BY position', (r['id'],))]
        groups[r['id']] = {'title': r['title'], 'media_ids': members}
    return {'media': media_rows, 'folder': folders, 'group': groups}


def _record_baseline(db):
    db.execute(f'CREATE TABLE IF NOT EXISTS {BASELINE_TABLE} (kind TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(kind, id))')
    db.execute(f'DELETE FROM {BASELINE_TABLE}')
    for kind, rows in _library_state(db).items():
        db.executemany(f'INSERT INTO {BASELINE_TABLE} VALUES (?,?,?)',
                       [(kind, ident, json.dumps(data, ensure_ascii=False, sort_keys=True)) for ident, data in rows.items()])


def _baseline(db):
    if not _has(db, BASELINE_TABLE):
        return None
    state = {'media': {}, 'folder': {}, 'group': {}}
    for r in db.execute(f'SELECT kind, id, data FROM {BASELINE_TABLE}'):
        state.setdefault(r['kind'], {})[r['id']] = json.loads(r['data'])
    return state


def _diff(before, after, fields):
    created = [{'id': i, **after[i]} for i in after if i not in before]
    deleted = [{'id': i, **before[i]} for i in before if i not in after]
    changed = []
    for ident in after:
        if ident in before:
            delta = {f: {'from': before[ident].get(f), 'to': after[ident].get(f)} for f in fields if before[ident].get(f) != after[ident].get(f)}
            if delta:
                changed.append({'id': ident, 'title': after[ident].get('title', after[ident].get('name')), **delta})
    return created, deleted, changed


def _export_target(export_dir, asset_root):
    target = Path(export_dir).absolute()
    if target.is_relative_to(Path(asset_root).absolute()):
        raise MigrationError('导出目录不能位于素材目录内（回退会还原该目录）')
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise MigrationError(f'导出目录须为新目录或空目录：{target}')
    return target


def changes_since(db, finished_at, export_dir=None, asset_root=None):
    """Rollback export: what changed in the library after the migration finished.

    With a recorded baseline (``apply`` of this version) every difference is listed; without
    one only media created after ``finished_at`` are known (``baseline: false``). When
    ``export_dir`` is given, new media files are copied to ``<export_dir>/files/`` and the
    report is written to ``<export_dir>/changes.json``. Nothing in the library is modified.
    """
    import media_library
    target = _export_target(export_dir, asset_root) if export_dir else None
    current = _library_state(db)
    base = _baseline(db)
    tombstones = {r['id']: r['deleted_at'] for r in db.execute('SELECT id, deleted_at FROM media_tombstones')}
    titles = {i: f['title'] for i, f in current['folder'].items()}
    if base is not None:
        base_titles = {i: f['title'] for i, f in base['folder'].items()}
        new_ids = [i for i in current['media'] if i not in base['media']]
        _, deleted, changed = _diff(base['media'], current['media'], ('name', 'folder_id'))
        moved = [{'id': c['id'], 'name': c['title'], 'from': c['folder_id']['from'], 'from_title': base_titles.get(c['folder_id']['from'], titles.get(c['folder_id']['from'])),
                  'to': c['folder_id']['to'], 'to_title': titles.get(c['folder_id']['to'])} for c in changed if 'folder_id' in c]
        renamed = [{'id': c['id'], 'from': c['name']['from'], 'to': c['name']['to']} for c in changed if 'name' in c]
        deleted = [{'id': d['id'], 'name': d['name'], 'kind': d['kind'], 'deleted_at': tombstones.get(d['id'])} for d in deleted]
        folders = dict(zip(('created', 'deleted', 'changed'), _diff(base['folder'], current['folder'], ('title', 'parent_id', 'icon'))))
        groups = dict(zip(('created', 'deleted', 'changed'), _diff(base['group'], current['group'], ('title', 'media_ids'))))
    else:
        new_ids = [i for i, m in current['media'].items() if m['created_at'] > finished_at]
        moved, renamed, deleted, folders, groups = [], [], [], None, None
    new_media = sorted(({'id': i, **{k: current['media'][i][k] for k in ('name', 'kind', 'folder_id', 'origin', 'relpath', 'created_at')},
                         'folder_title': titles.get(current['media'][i]['folder_id'])} for i in new_ids), key=lambda m: (m['created_at'], m['id']))
    report = {'since': finished_at, 'baseline': base is not None, 'new_media': new_media, 'moved': moved, 'renamed': renamed,
              'deleted_media': deleted, 'folders': folders, 'groups': groups, 'export_dir': str(target) if target else None,
              'exported_files': 0}
    if target is not None:
        files = target / 'files'
        files.mkdir(parents=True, exist_ok=True)
        source_root = media_library.root()
        for item in new_media:
            source = source_root / item['relpath']
            if source.resolve() != source or not source.is_relative_to(source_root) or not source.is_file():
                item['export_error'] = '文件不可读取'
                continue
            shutil.copy2(source, files / item['relpath'])
            report['exported_files'] += 1
        (target / 'changes.json').write_text(json.dumps(report, ensure_ascii=False, indent=1))
    return report
