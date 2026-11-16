"""Server-queued "run whole node group" (GROUP-RUN-20261115, A2 state machine).

A run snapshots the generation nodes of one canvas node group, orders them by
in-group dependencies and submits each node once all of its in-group upstream
nodes succeeded.  User rules (task log GROUP-RUN-20261115, 用户决定):

1. independent nodes are submitted together; only downstream waits for upstream;
2. an ordinary failure / cancellation blocks only its downstream branch, a
   result_unknown stops the whole run;
3. a node whose re-estimate exceeds the confirmed estimate (or turns unknown)
   pauses the run (awaiting_confirm) until the user confirms;
4. every generation node of the group is rerun (old results stay candidates);
5. cancelling only stops nodes that were not submitted yet;
6. a node changed by hand during the run (prompt/params/references/inputs or
   the selected result of an in-group upstream) blocks its branch.

Submission and estimation are injected (``set_submitter``/``set_estimator``);
this module never calls a provider, never retries and never resubmits a node.
"""
import hashlib
import json
import logging
import math
import sqlite3
import uuid

import canvas_store as store
import tasks as task_db

LOG = logging.getLogger('nanobanana.canvas_group_run')

GENERATION_TYPES = ('image', 'video', 'audio')
# client canConnect (canvasReferences.js): target type -> accepted source media kinds; text feeds all.
ACCEPTS = {'image': ('image',), 'video': ('image', 'video', 'audio'), 'audio': ('image', 'audio')}
ACTIVE_RUN = ('running', 'awaiting_confirm')
RUN_STATUSES = ACTIVE_RUN + ('completed', 'stopped', 'cancelled')
LIVE_NODE = ('waiting', 'submitting', 'submitted')
NODE_STATUSES = LIVE_NODE + ('succeeded', 'failed', 'cancelled', 'unknown', 'blocked')
ACTIVE_TASK = ('pending', 'preparing', 'processing', 'cancel_requested')
TERMINAL_TASK = ('succeeded', 'failed', 'cancelled')
EPSILON = 1e-9


class GroupRunError(store.CanvasError):
    def __init__(self, message, code, status=400, **extra):
        super().__init__(message, status)
        self.code = code
        self.extra = extra


class SubmitRejected(Exception):
    """Raised by a submitter when the node was rejected before any provider call."""


def _default_estimator(workflow, node, ctx):
    return {'known': False, 'usd': None, 'reason': 'estimator_unavailable'}


_submitter = None
_estimator = _default_estimator


def set_submitter(fn):
    """fn(workflow_id, node_id, ctx) -> {'task_id': int, 'result_unknown': bool}; None disables."""
    global _submitter
    _submitter = fn


def set_estimator(fn):
    """fn(workflow, node, ctx) -> {'known', 'usd', 'reason'}; None restores the unknown default."""
    global _estimator
    _estimator = fn or _default_estimator


# ---------------------------------------------------------------- helpers

def _dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _digest(value):
    return hashlib.sha256(_dumps(value).encode('utf-8')).hexdigest()


def _asset_id(node):
    asset = node.get('asset') if isinstance(node, dict) else None
    return asset.get('id') if isinstance(asset, dict) else None


def _normalize_estimate(value):
    if isinstance(value, dict) and value.get('known') is True:
        usd = value.get('usd')
        if isinstance(usd, (int, float)) and not isinstance(usd, bool) and math.isfinite(usd) and usd >= 0:
            return {'known': True, 'usd': round(float(usd), 6), 'reason': None}
        return {'known': False, 'usd': None, 'reason': 'invalid_estimate'}
    reason = value.get('reason') if isinstance(value, dict) else None
    return {'known': False, 'usd': None, 'reason': reason if isinstance(reason, str) and reason else 'unknown'}


def _estimate(workflow, node, phase, upstream, document):
    try:
        return _normalize_estimate(_estimator(workflow, node, {'phase': phase, 'run_upstream': list(upstream), 'document': document}))
    except Exception:  # an estimator error is an unknown cost, never zero
        LOG.exception('group_run_estimate_failed node=%s', node.get('id'))
        return {'known': False, 'usd': None, 'reason': 'estimate_failed'}


def _exceeds(confirmed, current):
    if not current['known']:
        return confirmed['known']
    return confirmed['known'] and current['usd'] > confirmed['usd'] + EPSILON


def _total(estimates):
    known = [e for e in estimates if e['known']]
    return {'usd': round(sum(e['usd'] for e in known), 6), 'known_count': len(known),
            'unknown_count': len(estimates) - len(known)}


def _find_group(document, group_id):
    for group in document.get('groups') or []:
        if isinstance(group, dict) and group.get('id') == group_id:
            return group
    return None


def _source_kind(source):
    if source.get('type') == 'asset':
        asset = source.get('asset')
        return asset.get('kind') if isinstance(asset, dict) else None
    return source.get('type')


# ---------------------------------------------------------------- planning

def _plan(document, group_id):
    """Members, in-group dependencies and levels of a group; raises on invalid graphs."""
    group = _find_group(document, group_id)
    if group is None:
        raise GroupRunError('节点组不存在', 'group_not_found', 404)
    by_id = {node.get('id'): node for node in document.get('nodes') or [] if isinstance(node, dict)}
    members = [node_id for node_id in group.get('nodeIds') or [] if node_id in by_id]
    run_ids = [node_id for node_id in members if by_id[node_id].get('type') in GENERATION_TYPES]
    skipped = [{'node_id': node_id, 'type': by_id[node_id].get('type'), 'reason': 'not_generation'}
               for node_id in members if node_id not in run_ids]
    if not run_ids:
        raise GroupRunError('节点组内没有可生成的图像、视频或音频节点', 'group_empty')
    run_set = set(run_ids)
    upstream = {node_id: [] for node_id in run_ids}
    for edge in document.get('edges') or []:
        if not isinstance(edge, dict) or edge.get('target') not in run_set:
            continue
        target, source = by_id[edge['target']], by_id.get(edge.get('source'))
        if not isinstance(source, dict) or source.get('id') == target['id']:
            continue
        kind = _source_kind(source)
        if kind == 'text' or kind not in ACCEPTS[target['type']]:
            continue
        if source['id'] in run_set:
            if source['id'] not in upstream[target['id']]:
                upstream[target['id']].append(source['id'])
        elif not _asset_id(source):
            # Only the group is chained; an outside (or non-run) upstream must already have a result.
            raise GroupRunError('节点“%s”的上游“%s”不在本组运行范围内且还没有结果，请先生成或移除连线'
                                % (target.get('title') or target['id'], source.get('title') or source['id']),
                                'upstream_missing', node_id=target['id'], source_id=source['id'])
    position = {node_id: index for index, node_id in enumerate(run_ids)}
    for node_id in upstream:
        upstream[node_id].sort(key=position.get)
    level, remaining = {}, list(run_ids)
    while remaining:
        ready = [n for n in remaining if all(u in level for u in upstream[n])]
        if not ready:
            raise GroupRunError('节点组内连线存在循环，无法确定运行顺序', 'cycle', node_ids=remaining)
        for node_id in ready:
            level[node_id] = 1 + max((level[u] for u in upstream[node_id]), default=-1)
        remaining = [n for n in remaining if n not in level]
    ordered = sorted(run_ids, key=lambda n: (level[n], position[n]))
    return {'by_id': by_id, 'run_ids': ordered, 'upstream': upstream, 'level': level,
            'position': position, 'skipped': skipped}


def _semantic_text(document, node, alias, run_set=()):
    """The node's own prompt with every @图片N/@视频N/@音频N token replaced by the asset it
    points at (bound referenceMentions first, else the browser's positional numbering).

    A token that points at nothing yet is resolved once more with a placeholder asset
    ``@up:<node>`` (kind = node type) for every in-group run upstream that has no result,
    so "参考 @图片1" written against a not-yet-generated upstream already means
    ``{{@up:a}}`` and stays equal after the write-back binds it to the new result.
    """
    import canvas_submit
    text = node.get('text')
    if not isinstance(text, str) or not text:
        return text
    nodes, edges = document.get('nodes') or [], document.get('edges') or []
    mentions = node.get('referenceMentions') if isinstance(node.get('referenceMentions'), dict) else {}

    def resolver(node_list):
        try:
            assets = canvas_submit.resolve_node_inputs(node, node_list, edges)['assets']
            current = {item['token']: item['assetId'] for item in canvas_submit.canvas_mention_items(node, assets)}
        except Exception:  # an unreadable reference set is not an edit by itself; fall back to the raw tokens
            assets, current = [], {}
        ids = {a.get('id') for a in assets}

        def resolve(token):
            bound = mentions.get(token)
            return bound if bound and bound in ids else current.get(token)
        return resolve

    real = resolver(nodes)
    sources = {e.get('source') for e in edges if isinstance(e, dict) and e.get('target') == node.get('id')}
    missing = {n.get('id') for n in nodes if isinstance(n, dict) and n.get('id') in run_set
               and n.get('id') in sources and not _asset_id(n)}
    placeholder = resolver([{**n, 'asset': {'id': '@up:' + n['id'], 'kind': n.get('type')}}
                            if isinstance(n, dict) and n.get('id') in missing else n
                            for n in nodes]) if missing else (lambda token: None)

    def target(match):
        token = match.group(0)
        resolved = real(token) or placeholder(token)
        return '{{%s}}' % alias(resolved) if resolved else token
    return canvas_submit.REFERENCE_TOKEN.sub(target, text)


def _fingerprint(document, node, run_set, aliases):
    """Hashes of the user-editable inputs of a node (rule 6), ``r:<raw>;s:<semantic>``.

    Server-written fields (task/candidates/asset/selection/upstreamStale) and
    layout are excluded; ids of in-group upstream results are replaced by
    ``@up:<node>`` so the write-back reference rename (F11) is not an edit.
    The raw hash keeps the prompt and referenceMentions as stored; the semantic
    hash replaces each @token in the prompt by the asset it points at and drops
    referenceMentions, so the browser renumbering tokens after an upstream
    result arrives (reconcileReferenceMentions / positionalMentionRebinds) is
    not an edit either. A node is unchanged when either hash matches
    (``_same_fingerprint``); a real prompt, parameter or binding edit changes both.
    """
    def alias(value):
        return aliases.get(value, value) if isinstance(value, str) else value

    by_id = {n.get('id'): n for n in document.get('nodes') or [] if isinstance(n, dict)}
    inputs = []
    for edge in document.get('edges') or []:
        if not isinstance(edge, dict) or edge.get('target') != node.get('id'):
            continue
        source = by_id.get(edge.get('source'))
        if not isinstance(source, dict):
            continue
        if source['id'] in run_set:
            inputs.append(['run', source['id']])
        else:
            inputs.append(['ext', source['id'], source.get('type'),
                           source.get('text') if source.get('type') == 'text' else None, alias(_asset_id(source))])
    payload = {
        'type': node.get('type'), 'text': node.get('text'), 'params': node.get('params') or {},
        'providerSelection': node.get('providerSelection'), 'characterRefs': node.get('characterRefs'),
        'referenceGroups': node.get('referenceGroups') or [],
        'referenceAssets': [alias(a.get('id')) for a in node.get('referenceAssets') or [] if isinstance(a, dict)],
        'referenceOrder': [alias(i) for i in node.get('referenceOrder') or []],
        'referenceMentions': {k: alias(v) for k, v in (node.get('referenceMentions') or {}).items()},
        'inputs': sorted(inputs, key=_dumps),
    }
    raw = _digest(payload)
    payload.pop('referenceMentions')
    payload['text'] = _semantic_text(document, node, alias, run_set)
    return 'r:%s;s:%s' % (raw, _digest(payload))


def _same_fingerprint(stored, current):
    def parts(value):
        return dict(part.split(':', 1) for part in (value or '').split(';') if ':' in part)
    old, new = parts(stored), parts(current)
    return any(old.get(key) and old.get(key) == new.get(key) for key in ('r', 's'))


def _preview(workflow, group_id):
    document = workflow['document']
    plan = _plan(document, group_id)
    nodes = []
    for node_id in plan['run_ids']:
        node = plan['by_id'][node_id]
        nodes.append({'node_id': node_id, 'type': node['type'], 'title': node.get('title') or '',
                      'level': plan['level'][node_id], 'upstream': plan['upstream'][node_id],
                      'has_result': bool(_asset_id(node)),
                      'estimate': _estimate(workflow, node, 'preview', plan['upstream'][node_id], document)})
    token = _digest({'v': 1, 'workflow_id': workflow['id'], 'group_id': group_id, 'revision': workflow['revision'],
                     'nodes': [[n['node_id'], n['level'], n['upstream'], n['estimate']] for n in nodes]})
    total = _total([n['estimate'] for n in nodes])
    total['node_count'] = len(nodes)
    return {'workflow_id': workflow['id'], 'group_id': group_id, 'revision': workflow['revision'],
            'preview_token': token, 'nodes': nodes, 'skipped': plan['skipped'], 'total': total}, plan


def _revision(value):
    if type(value) is not int or value < 1:
        raise GroupRunError('revision 必须为正整数', 'invalid_request')
    return value


def preview(workflow_id, group_id, revision):
    workflow = store.workflow(workflow_id)
    if workflow['revision'] != _revision(revision):
        raise GroupRunError('画布已更新，请保存或重新载入后再运行', 'revision_mismatch', 409, revision=workflow['revision'])
    return _preview(workflow, group_id)[0]


# ---------------------------------------------------------------- persistence

def _now():
    return task_db.utcnow()


def _run_row(run_id):
    return task_db.get_db().execute('SELECT * FROM canvas_group_runs WHERE id=?', (run_id,)).fetchone()


def _node_rows(run_id):
    return [dict(row) for row in task_db.get_db().execute(
        'SELECT * FROM canvas_group_run_nodes WHERE run_id=? ORDER BY level, position', (run_id,))]


def _set_node(db, run_id, node_id, status, expect=None, **fields):
    fields.update(status=status, updated_at=_now())
    sql = 'UPDATE canvas_group_run_nodes SET ' + ','.join(f'{k}=?' for k in fields) + ' WHERE run_id=? AND node_id=?'
    args = list(fields.values()) + [run_id, node_id]
    if expect:
        sql += ' AND status IN (%s)' % ','.join('?' * len(expect))
        args += list(expect)
    return db.execute(sql, args).rowcount


def _touch(db, run_id):
    db.execute('UPDATE canvas_group_runs SET updated_at=? WHERE id=?', (_now(), run_id))


def _block_descendants(db, run_id, node_id, reason):
    """Block waiting downstream nodes of ``node_id``; direct ones get ``reason``."""
    rows = {r['node_id']: json.loads(r['upstream']) for r in db.execute(
        'SELECT node_id, upstream FROM canvas_group_run_nodes WHERE run_id=?', (run_id,))}
    frontier, seen = [(node_id, reason)], {node_id}
    while frontier:
        parent, why = frontier.pop()
        for child, ups in rows.items():
            if parent in ups and child not in seen:
                seen.add(child)
                _set_node(db, run_id, child, 'blocked', ('waiting',), reason=why, pending_estimate=None)
                frontier.append((child, 'upstream_blocked'))


def _stop(db, run_id, reason='result_unknown'):
    db.execute("UPDATE canvas_group_runs SET status='stopped', stop_reason=?, updated_at=? WHERE id=? AND status IN ('running','awaiting_confirm')",
               (reason, _now(), run_id))
    db.execute("UPDATE canvas_group_run_nodes SET status='blocked', reason='run_stopped', pending_estimate=NULL, updated_at=? WHERE run_id=? AND status='waiting'",
               (_now(), run_id))


def _finalize(run_id):
    with store.write_transaction() as db:
        run = _run_row(run_id)
        if run is None or run['finished_at']:
            return
        live = db.execute("SELECT COUNT(*) FROM canvas_group_run_nodes WHERE run_id=? AND status IN ('waiting','submitting','submitted')",
                          (run_id,)).fetchone()[0]
        if live:
            if run['status'] == 'awaiting_confirm' and not db.execute(
                    "SELECT 1 FROM canvas_group_run_nodes WHERE run_id=? AND status='waiting' AND pending_estimate IS NOT NULL",
                    (run_id,)).fetchone():
                db.execute("UPDATE canvas_group_runs SET status='running', updated_at=? WHERE id=?", (_now(), run_id))
            return
        status = 'completed' if run['status'] in ACTIVE_RUN else run['status']
        db.execute('UPDATE canvas_group_runs SET status=?, finished_at=?, updated_at=? WHERE id=?',
                   (status, _now(), _now(), run_id))


# ---------------------------------------------------------------- create / query

def _public_estimate(raw):
    return json.loads(raw) if raw else None


def _confirm_token(run_id, pending):
    return _digest({'v': 1, 'run_id': run_id, 'pending': pending})


def public_run(run_id):
    run = _run_row(run_id)
    if run is None:
        raise GroupRunError('组运行不存在', 'run_not_found', 404)
    run = dict(run)
    nodes, counts = [], {}
    for row in _node_rows(run_id):
        counts[row['status']] = counts.get(row['status'], 0) + 1
        nodes.append({'node_id': row['node_id'], 'type': row['node_type'], 'level': row['level'],
                      'upstream': json.loads(row['upstream']), 'status': row['status'], 'task_id': row['task_id'],
                      'estimate': json.loads(row['estimate']), 'pending_estimate': _public_estimate(row['pending_estimate']),
                      'reason': row['reason'], 'message': row['message']})
    pending = [{'node_id': n['node_id'], 'confirmed': n['estimate'], 'estimate': n['pending_estimate']}
               for n in nodes if n['status'] == 'waiting' and n['pending_estimate']]
    confirm = None
    if run['status'] == 'awaiting_confirm' and pending:
        confirm = {'confirm_token': _confirm_token(run_id, pending), 'nodes': pending}
    done = sum(v for k, v in counts.items() if k not in LIVE_NODE)
    return {'id': run['id'], 'workflow_id': run['workflow_id'], 'group_id': run['group_id'], 'status': run['status'],
            'base_revision': run['base_revision'], 'stop_reason': run['stop_reason'], 'created_at': run['created_at'],
            'updated_at': run['updated_at'], 'finished_at': run['finished_at'],
            'total': _total([n['estimate'] for n in nodes]), 'counts': counts,
            'progress': {'done': done, 'total': len(nodes)}, 'confirm': confirm, 'nodes': nodes}


def get_run(workflow_id, run_id):
    store.workflow(workflow_id)
    run = _run_row(run_id)
    if run is None or run['workflow_id'] != workflow_id:
        raise GroupRunError('组运行不存在', 'run_not_found', 404)
    return public_run(run_id)


def list_runs(workflow_id, active=False, group_id=None):
    store.workflow(workflow_id)
    sql, args = 'SELECT id FROM canvas_group_runs WHERE workflow_id=?', [workflow_id]
    if active:
        sql += " AND status IN ('running','awaiting_confirm')"
    if group_id:
        sql += ' AND group_id=?'
        args.append(group_id)
    sql += ' ORDER BY created_at DESC, rowid DESC LIMIT 50'
    return [public_run(row['id']) for row in task_db.get_db().execute(sql, args)]


def active_run_for_node(workflow_id, node_id):
    """Id of the active run that owns ``node_id`` (B4 manual-generation guard), else None."""
    row = task_db.get_db().execute(
        """SELECT r.id FROM canvas_group_runs r JOIN canvas_group_run_nodes n ON n.run_id=r.id
           WHERE r.workflow_id=? AND n.node_id=? AND r.status IN ('running','awaiting_confirm')
             AND n.status IN ('waiting','submitting','submitted') LIMIT 1""", (workflow_id, node_id)).fetchone()
    return row['id'] if row else None


def create_run(workflow_id, group_id, revision, preview_token):
    if not isinstance(group_id, str) or not group_id:
        raise GroupRunError('group_id 无效', 'invalid_request')
    if not isinstance(preview_token, str) or not preview_token:
        raise GroupRunError('缺少费用确认凭据，请先预估', 'invalid_request')
    revision = _revision(revision)
    workflow = store.workflow(workflow_id)
    if workflow['revision'] != revision:
        raise GroupRunError('画布已更新，请保存或重新载入后再运行', 'revision_mismatch', 409, revision=workflow['revision'])
    fresh, plan = _preview(workflow, group_id)
    if fresh['preview_token'] != preview_token:
        raise GroupRunError('预估已变化，请重新确认费用', 'preview_stale', 409, preview=fresh)
    if _submitter is None:
        raise GroupRunError('服务端组运行提交尚未接入', 'submit_unavailable', 503)
    document, run_set = workflow['document'], set(plan['run_ids'])
    busy = [n for n in plan['run_ids']
            if isinstance(plan['by_id'][n].get('task'), dict) and plan['by_id'][n]['task'].get('status') in ACTIVE_TASK]
    aliases = {_asset_id(plan['by_id'][n]): '@up:' + n for n in plan['run_ids'] if _asset_id(plan['by_id'][n])}
    run_id, now = uuid.uuid4().hex, _now()
    estimates = {n['node_id']: n['estimate'] for n in fresh['nodes']}
    try:
        with store.write_transaction() as db:
            current = store.workflow(workflow_id)['revision']
            if current != revision:
                raise GroupRunError('画布已更新，请保存或重新载入后再运行', 'revision_mismatch', 409, revision=current)
            marks = ','.join('?' * len(plan['run_ids']))
            busy += [row['node_id'] for row in db.execute(
                f"""SELECT DISTINCT n.node_id FROM canvas_group_run_nodes n JOIN canvas_group_runs r ON r.id=n.run_id
                    WHERE r.workflow_id=? AND n.status IN ('submitting','submitted') AND n.node_id IN ({marks})""",
                [workflow_id] + plan['run_ids']) if row['node_id'] not in busy]
            if busy:
                raise GroupRunError('组内有节点正在生成，请等待完成或取消后再运行', 'node_busy', 409, node_ids=busy)
            db.execute('INSERT INTO canvas_group_runs (id, workflow_id, group_id, status, base_revision, created_at, updated_at) VALUES (?,?,?,?,?,?,?)',
                       (run_id, workflow_id, group_id, 'running', revision, now, now))
            for node_id in plan['run_ids']:
                node = plan['by_id'][node_id]
                own = _asset_id(node)
                db.execute('''INSERT INTO canvas_group_run_nodes
                              (run_id, node_id, node_type, position, level, upstream, status, estimate, fingerprint, base_assets, updated_at)
                              VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                           (run_id, node_id, node['type'], plan['position'][node_id], plan['level'][node_id],
                            json.dumps(plan['upstream'][node_id]), 'waiting', _dumps(estimates[node_id]),
                            _fingerprint(document, node, run_set, aliases), json.dumps([own] if own else []), now))
    except sqlite3.IntegrityError:
        existing = task_db.get_db().execute(
            "SELECT id FROM canvas_group_runs WHERE workflow_id=? AND group_id=? AND status IN ('running','awaiting_confirm')",
            (workflow_id, group_id)).fetchone()
        raise GroupRunError('该节点组已有运行中的组运行', 'run_active', 409, run_id=existing['id'] if existing else None)
    advance(run_id)
    return public_run(run_id)


# ---------------------------------------------------------------- state machine

def _aliases(rows):
    aliases = {}
    for row in rows:
        for asset_id in json.loads(row['base_assets']) + ([row['result_asset_id']] if row['result_asset_id'] else []):
            aliases[asset_id] = '@up:' + row['node_id']
    return aliases


def _branch_check(document, group, row, rows_by_id, run_set, aliases):
    """None when the node may be submitted, else the blocking reason (rule 6)."""
    by_id = {n.get('id'): n for n in document.get('nodes') or [] if isinstance(n, dict)}
    members = set(group.get('nodeIds') or []) if group else set()
    node = by_id.get(row['node_id'])
    if node is None or row['node_id'] not in members:
        return 'node_removed'
    if not _same_fingerprint(row['fingerprint'], _fingerprint(document, node, run_set, aliases)):
        return 'node_modified'
    for up_id in json.loads(row['upstream']):
        up, up_row = by_id.get(up_id), rows_by_id[up_id]
        if up is None or up_id not in members or not _same_fingerprint(up_row['fingerprint'], _fingerprint(document, up, run_set, aliases)):
            return 'upstream_modified'
        if not up_row['result_asset_id']:
            return 'upstream_no_result'
        if _asset_id(up) != up_row['result_asset_id']:
            return 'upstream_modified'
    return None


OUTPUT_KINDS = ('output_image', 'output_video', 'output_audio')


def _task_output_hashes(task_id):
    """sha256 of the task's own local outputs (the content its write-back imports)."""
    hashes = set()
    for asset in task_db.list_assets(task_id):
        if asset['kind'] not in OUTPUT_KINDS:
            continue
        if asset.get('media_id'):
            # LIBRARY-GLOBAL-20261116 S2: the library item's hash, even after the output file is gone.
            import canvas_media_refs
            hashes.update(canvas_media_refs.media_hashes([asset['media_id']]).values())
        digest = hashlib.sha256()
        try:
            with open(asset['path'], 'rb') as handle:
                for chunk in iter(lambda: handle.read(1 << 20), b''):
                    digest.update(chunk)
        except OSError:
            continue
        hashes.add(digest.hexdigest())
    return hashes


def _node_task_asset(workflow_id, node_id, task_id, hashes):
    """(asset id from this task or None, write-back still pending) for the node."""
    try:
        document = store.workflow(workflow_id)['document']
    except store.CanvasError:
        return None, False
    node = next((n for n in document.get('nodes') or [] if isinstance(n, dict) and n.get('id') == node_id), None)
    task = node.get('task') if node else None
    if not isinstance(task, dict) or task.get('id') != task_id:
        return None, False   # relinked / deleted: the write-back will never land on this node
    ids = [_asset_id(node)] + [c.get('id') for c in node.get('candidates') or [] if isinstance(c, dict)]
    ids = [i for i in dict.fromkeys(ids) if isinstance(i, str)]
    if ids and hashes:
        marks = ','.join('?' * len(ids))
        found = {row['id']: row['sha256'] for row in task_db.get_db().execute(
            f'SELECT id, sha256 FROM canvas_assets WHERE workflow_id=? AND id IN ({marks})', [workflow_id] + ids)}
        # LIBRARY-GLOBAL-20261116 S2: written-back results reference library media items.
        import canvas_media_refs
        found.update(canvas_media_refs.media_hashes(ids))
        for asset_id in ids:   # the selected one first; else a candidate from this task (user switched)
            if found.get(asset_id) in hashes:
                return asset_id, False
    return None, task.get('status') in ACTIVE_TASK


def _result_asset(workflow_id, node_id, task_id):
    """Canvas asset of ``node_id`` that provably comes from ``task_id`` (GROUP-RUN D1).

    Only an asset whose content hash equals one of the task's own outputs counts:
    an older ``node.asset`` left by a write-back that never landed (it raised, or
    the worker died in between) is never taken for the new result. When the
    write-back is still pending it is attempted once more through the existing
    canvas_writeback import (its merge rules unchanged). None when still missing.
    """
    hashes = _task_output_hashes(task_id)
    asset_id, pending = _node_task_asset(workflow_id, node_id, task_id, hashes)
    if asset_id is None and pending:
        try:
            import canvas_writeback
            canvas_writeback.apply_task_result(task_id, workflow_id)
        except Exception:
            LOG.exception('group_run_writeback_retry_failed workflow=%s node=%s task=%s', workflow_id, node_id, task_id)
            return None
        asset_id, _pending = _node_task_asset(workflow_id, node_id, task_id, hashes)
    return asset_id


def _apply_task(run_id, workflow_id, node_id, task, final=False):
    """Record a terminal task on its submitted node. True when something changed.

    A succeeded task whose result is not (yet) on the canvas is left ``submitted``
    so nothing downstream runs on a stale result; the patrol calls with
    ``final=True`` and then records it without a result (downstream blocked as
    ``upstream_no_result``).
    """
    status = task['status']
    if status not in TERMINAL_TASK:
        return False
    result = task.get('result') if isinstance(task.get('result'), dict) else {}
    asset_id = _result_asset(workflow_id, node_id, task['id']) if status == 'succeeded' else None
    if status == 'succeeded' and asset_id is None and not final:
        LOG.warning('group_run_result_missing run=%s node=%s task=%s', run_id, node_id, task['id'])
        return False
    with store.write_transaction() as db:
        if status == 'succeeded':
            changed = _set_node(db, run_id, node_id, 'succeeded', ('submitted',), result_asset_id=asset_id, reason=None)
        elif status == 'failed' and result.get('result_unknown'):
            changed = _set_node(db, run_id, node_id, 'unknown', ('submitted',), reason='result_unknown', message='任务结果未知，可能已计费')
            if changed:
                _stop(db, run_id)
        elif status == 'failed':
            changed = _set_node(db, run_id, node_id, 'failed', ('submitted',), reason='task_failed', message=None)
            if changed:
                _block_descendants(db, run_id, node_id, 'upstream_failed')
        else:
            changed = _set_node(db, run_id, node_id, 'cancelled', ('submitted',), reason='task_cancelled')
            if changed:
                _block_descendants(db, run_id, node_id, 'upstream_cancelled')
        if changed:
            _touch(db, run_id)
    return bool(changed)


def on_task_terminal(task_id):
    """Worker hook (B4): call after the task's canvas write-back. Returns the run or None."""
    row = task_db.get_db().execute(
        """SELECT n.run_id, n.node_id, r.workflow_id FROM canvas_group_run_nodes n
           JOIN canvas_group_runs r ON r.id=n.run_id WHERE n.task_id=? AND n.status='submitted'""", (task_id,)).fetchone()
    if row is None:
        return None
    task = task_db.get_task(task_id)
    if task and _apply_task(row['run_id'], row['workflow_id'], row['node_id'], task):
        advance(row['run_id'])
    return public_run(row['run_id'])


def _submit(run, row, document, revision):
    run_id, node_id = run['id'], row['node_id']
    with store.write_transaction() as db:
        state = db.execute('SELECT status FROM canvas_group_runs WHERE id=?', (run_id,)).fetchone()
        if state['status'] != 'running' or not _set_node(db, run_id, node_id, 'submitting', ('waiting',), pending_estimate=None):
            return False
    try:
        outcome = _submitter(run['workflow_id'], node_id, {'run_id': run_id, 'document': document, 'revision': revision})
    except SubmitRejected as error:
        with store.write_transaction() as db:
            _set_node(db, run_id, node_id, 'failed', ('submitting',), reason='submit_rejected', message=str(error)[:500] or '提交被拒绝')
            _block_descendants(db, run_id, node_id, 'upstream_failed')
            _touch(db, run_id)
        return True
    except Exception:
        LOG.exception('group_run_submit_unknown run=%s node=%s', run_id, node_id)
        outcome = {'result_unknown': True}
    task_id = outcome.get('task_id') if isinstance(outcome, dict) else None
    if type(task_id) is not int or task_id < 1:
        task_id = None
    with store.write_transaction() as db:
        if task_id is None or outcome.get('result_unknown'):
            _set_node(db, run_id, node_id, 'unknown', ('submitting',), task_id=task_id, reason='result_unknown',
                      message='提交结果未知，可能已计费；整组已停止，不会自动重试')
            _stop(db, run_id)
        else:
            _set_node(db, run_id, node_id, 'submitted', ('submitting',), task_id=task_id)
        _touch(db, run_id)
    if task_id is not None and not outcome.get('result_unknown'):
        task = task_db.get_task(task_id)
        if task:  # the task may already be terminal before the worker hook could find it
            _apply_task(run_id, run['workflow_id'], node_id, task)
    return True


def advance(run_id):
    """Idempotent: submit every ready node of a running run (rules 1-3, 6)."""
    for _ in range(1000):
        run = _run_row(run_id)
        if run is None:
            return None
        if run['status'] != 'running':
            break
        rows = _node_rows(run_id)
        rows_by_id = {r['node_id']: r for r in rows}
        ready = [r for r in rows if r['status'] == 'waiting'
                 and all(rows_by_id[u]['status'] == 'succeeded' for u in json.loads(r['upstream']))]
        if not ready:
            break
        try:
            workflow = store.workflow(run['workflow_id'])
        except store.CanvasError:
            workflow = None
        document = workflow['document'] if workflow else {'nodes': [], 'edges': []}
        group = _find_group(document, run['group_id'])
        run_set, aliases = set(rows_by_id), _aliases(rows)
        progressed, passed = False, []
        for row in ready:
            reason = _branch_check(document, group, row, rows_by_id, run_set, aliases) if workflow else 'node_removed'
            if reason is None:
                passed.append(row)
                continue
            with store.write_transaction() as db:
                if _set_node(db, run_id, row['node_id'], 'blocked', ('waiting',), reason=reason, pending_estimate=None):
                    _block_descendants(db, run_id, row['node_id'], 'upstream_blocked')
                    _touch(db, run_id)
                    progressed = True
        by_id = {n.get('id'): n for n in document.get('nodes') or [] if isinstance(n, dict)}
        exceeded, submit = [], []
        for row in passed:
            current = _estimate(workflow, by_id[row['node_id']], 'submit', json.loads(row['upstream']), document)
            (exceeded if _exceeds(json.loads(row['estimate']), current) else submit).append((row, current))
        if exceeded:
            # Rule 3: pause the whole run; nothing new is submitted until the user confirms.
            with store.write_transaction() as db:
                if db.execute("UPDATE canvas_group_runs SET status='awaiting_confirm', updated_at=? WHERE id=? AND status='running'",
                              (_now(), run_id)).rowcount:
                    for row, current in exceeded:
                        _set_node(db, run_id, row['node_id'], 'waiting', ('waiting',), pending_estimate=_dumps(current))
            break
        for row, _current in submit:
            progressed = _submit(run, row, document, workflow['revision']) or progressed
        if not progressed:
            break
    _finalize(run_id)
    return public_run(run_id)


# ---------------------------------------------------------------- B4: worker recovery and manual guard

# A node left in ``submitting`` is only declared unknown after this many seconds without a
# task row: a submission may still be in flight in another thread or process.
SUBMIT_GRACE_SECONDS = 300


def is_run_submission(run_id, node_id, request_run_id):
    """True when ``request_run_id`` (from the server-internal submission context, never from the
    request body) is this active run and ``node_id`` is claimed as submitting."""
    if not run_id or request_run_id != run_id:
        return False
    row = task_db.get_db().execute(
        "SELECT 1 FROM canvas_group_run_nodes WHERE run_id=? AND node_id=? AND status='submitting'",
        (run_id, node_id)).fetchone()
    return row is not None


def _task_for_node(run, node_id):
    """Id of the task the run created for ``node_id`` (params.group_run_id + canvas_node_id), else None."""
    rows = task_db.get_db().execute(
        'SELECT id, params FROM tasks WHERE created_at >= ? AND params LIKE ? ORDER BY id',
        (run['created_at'][:19], '%' + run['id'] + '%'))
    for row in rows:
        try:
            params = json.loads(row['params'] or '{}')
        except (TypeError, ValueError):
            continue
        if isinstance(params, dict) and params.get('group_run_id') == run['id'] and params.get('canvas_node_id') == node_id:
            return row['id']
    return None


def _age_seconds(stamp):
    from datetime import datetime, timezone
    try:
        then = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return float('inf')
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds()


def _recover_submitting(run, row, grace):
    """Restore a node interrupted while submitting; never resubmits it."""
    run_id, node_id = run['id'], row['node_id']
    task_id = _task_for_node(run, node_id)
    if task_id is not None:
        with store.write_transaction() as db:
            changed = _set_node(db, run_id, node_id, 'submitted', ('submitting',), task_id=task_id)
            if changed:
                _touch(db, run_id)
        if changed:
            LOG.warning('group_run_recovered_submission run=%s node=%s task=%s', run_id, node_id, task_id)
            task = task_db.get_task(task_id)
            if task:
                _apply_task(run_id, run['workflow_id'], node_id, task)
        return bool(changed)
    if _age_seconds(row['updated_at']) < grace:
        return False
    with store.write_transaction() as db:
        changed = _set_node(db, run_id, node_id, 'unknown', ('submitting',), reason='result_unknown',
                            message='提交过程中断且未找到任务记录，结果未知，可能已计费；整组已停止，不会自动重试')
        if changed:
            _stop(db, run_id)
            _touch(db, run_id)
    if changed:
        LOG.warning('group_run_submission_unknown run=%s node=%s', run_id, node_id)
    return bool(changed)


def _recover_submitted(run, row):
    """Apply a terminal task whose worker hook was missed (crash between finalize and hook)."""
    task = task_db.get_task(row['task_id'])
    if task is None:
        with store.write_transaction() as db:
            changed = _set_node(db, run['id'], row['node_id'], 'unknown', ('submitted',), reason='result_unknown',
                                message='任务记录不存在，结果未知；整组已停止，不会自动重试')
            if changed:
                _stop(db, run['id'])
                _touch(db, run['id'])
        return bool(changed)
    return _apply_task(run['id'], run['workflow_id'], row['node_id'], task, final=True)


def sweep(grace=None):
    """Worker patrol (startup recovery + missed-advance fallback). Returns the runs touched.

    For every unfinished run: an interrupted ``submitting`` node is bound to the
    task found by params.group_run_id + canvas_node_id, or after ``grace``
    seconds without one recorded as unknown (whole run stopped); a ``submitted``
    node whose task is already terminal is applied; then the run is advanced.
    Nothing is ever resubmitted or retried.
    """
    grace = SUBMIT_GRACE_SECONDS if grace is None else grace
    touched = []
    run_ids = [r['id'] for r in task_db.get_db().execute(
        'SELECT id FROM canvas_group_runs WHERE finished_at IS NULL ORDER BY created_at')]
    for run_id in run_ids:
        try:
            run = _run_row(run_id)
            if run is None:
                continue
            changed = False
            for row in _node_rows(run_id):
                if row['status'] == 'submitting':
                    changed = _recover_submitting(run, row, grace) or changed
                elif row['status'] == 'submitted' and row['task_id']:
                    changed = _recover_submitted(run, row) or changed
            before = _run_row(run_id)
            after = advance(run_id)
            if changed or (after and (after['status'] != before['status'] or after['updated_at'] != before['updated_at'])):
                touched.append(run_id)
        except Exception:
            LOG.exception('group_run_sweep_failed run=%s', run_id)
    return touched


def confirm(workflow_id, run_id, token):
    run = get_run(workflow_id, run_id)
    if run['status'] != 'awaiting_confirm' or not run['confirm']:
        raise GroupRunError('该组运行当前不需要确认费用', 'not_awaiting_confirm', 409)
    if token != run['confirm']['confirm_token']:
        raise GroupRunError('费用预估已变化，请重新确认', 'confirm_stale', 409, run=run)
    with store.write_transaction() as db:
        if not db.execute("UPDATE canvas_group_runs SET status='running', updated_at=? WHERE id=? AND status='awaiting_confirm'",
                          (_now(), run_id)).rowcount:
            raise GroupRunError('该组运行当前不需要确认费用', 'not_awaiting_confirm', 409)
        db.execute("""UPDATE canvas_group_run_nodes SET estimate=pending_estimate, pending_estimate=NULL, updated_at=?
                      WHERE run_id=? AND status='waiting' AND pending_estimate IS NOT NULL""", (_now(), run_id))
    return advance(run_id)


def cancel(workflow_id, run_id):
    """Rule 5: stop unsubmitted nodes; submitted tasks finish and write back normally."""
    run = get_run(workflow_id, run_id)
    if run['status'] == 'cancelled':
        return run
    if run['status'] not in ACTIVE_RUN:
        raise GroupRunError('该组运行已结束', 'run_finished', 409)
    with store.write_transaction() as db:
        if db.execute("UPDATE canvas_group_runs SET status='cancelled', stop_reason='user_cancelled', updated_at=? WHERE id=? AND status IN ('running','awaiting_confirm')",
                      (_now(), run_id)).rowcount:
            db.execute("UPDATE canvas_group_run_nodes SET status='cancelled', reason='user_cancelled', pending_estimate=NULL, updated_at=? WHERE run_id=? AND status='waiting'",
                       (_now(), run_id))
    _finalize(run_id)
    return public_run(run_id)
