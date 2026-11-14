"""Read-only project cost ledger built from task estimates (never actual charges).

GET /api/cost-ledger?project_id=&workflow_id=&from=YYYY-MM-DD&to=YYYY-MM-DD&tz_offset_minutes=
Never calls a Provider and never writes; historical tasks without a stored
snapshot are derived from their params on the fly (basis=derived, 推算).
"""
from datetime import date, datetime, timedelta, timezone
import json
import re

from flask import jsonify, request

import cost_estimate
import tasks as task_db

UNASSIGNED = '__unassigned__'
MISSING = '__missing__'
DISCLAIMER = '估算，非实际扣费'
BUCKETS = ('billable', 'result_unknown', 'failed', 'cancelled', 'active')
BUCKET_LABELS = {
    'billable': '已完成（估算计入）',
    'result_unknown': '结果未知（可能已计费）',
    'failed': '失败（通常不计费）',
    'cancelled': '已取消（通常不计费）',
    'active': '进行中（尚未结束）',
}
TASK_LIMIT = 500
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


class LedgerError(ValueError):
    pass


def _bucket(task):
    status = task.get('status')
    if status == 'succeeded':
        return 'billable'
    if status == 'failed':
        result = task.get('result')
        return 'result_unknown' if isinstance(result, dict) and result.get('result_unknown') else 'failed'
    if status == 'cancelled':
        return 'cancelled'
    return 'active'


def _empty_totals():
    return {bucket: {'count': 0, 'known_count': 0, 'unknown_count': 0,
                     'known_usd_min': 0.0, 'known_usd_max': 0.0, 'unknown_reasons': {}}
            for bucket in BUCKETS}


def _add(totals, entry):
    item = totals[entry['bucket']]
    item['count'] += 1
    if entry['estimate_usd'] is None:
        item['unknown_count'] += 1
        reason = entry['unknown_reason']
        item['unknown_reasons'][reason] = item['unknown_reasons'].get(reason, 0) + 1
    else:
        item['known_count'] += 1
        item['known_usd_min'] += entry['estimate_usd']['min']
        item['known_usd_max'] += entry['estimate_usd']['max']


def _parse_date(value, name):
    if value in (None, ''):
        return None
    if not isinstance(value, str) or not DATE.fullmatch(value):
        raise LedgerError(f'{name} 必须是 YYYY-MM-DD')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise LedgerError(f'{name} 不是有效日期')


def _local_date(created_at, offset):
    try:
        moment = datetime.fromisoformat(str(created_at))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (moment.astimezone(timezone.utc) + offset).date()


def _canvas_index(db):
    from canvas_cleanup import is_deleted
    projects = {row['id']: dict(row) for row in db.execute('SELECT id, title FROM canvas_projects')}
    workflows, node_by_task = {}, {}
    for row in db.execute('SELECT id, project_id, title, document FROM canvas_workflows'):
        try:
            document = json.loads(row['document'] or '{}')
        except ValueError:
            document = {}
        nodes = {}
        for node in document.get('nodes', []) if isinstance(document, dict) else []:
            if not isinstance(node, dict) or not node.get('id'):
                continue
            nodes[node['id']] = {'title': node.get('title') or None, 'type': node.get('type')}
            task = node.get('task')
            if isinstance(task, dict) and isinstance(task.get('id'), int):
                node_by_task[(row['id'], task['id'])] = node['id']
        workflows[row['id']] = {'id': row['id'], 'project_id': row['project_id'], 'title': row['title'],
                                'deleted': is_deleted('workflow', row['id']), 'nodes': nodes}
    for project in projects.values():
        project['deleted'] = is_deleted('project', project['id'])
    return projects, workflows, node_by_task


def _entry(task, db, projects, workflows, node_by_task, offset):
    params = task.get('params') or {}
    workflow_id = params.get('canvas_workflow_id')
    workflow = workflows.get(workflow_id) if workflow_id else None
    if not workflow_id:
        project_id = UNASSIGNED
    elif workflow is None:
        project_id = MISSING
    else:
        project_id = workflow['project_id']
    node_id = params.get('canvas_node_id') if isinstance(params.get('canvas_node_id'), str) else None
    if workflow_id and not node_id:
        node_id = node_by_task.get((workflow_id, task['id']))
    estimate = cost_estimate.task_estimate(task, db)
    known = estimate.get('status') == 'estimate'
    reason = None if known else (estimate.get('reason') or 'no_estimate_snapshot')
    return {
        'id': task['id'], 'type': task.get('type'), 'provider': task.get('provider'),
        'model': params.get('model'), 'status': task.get('status'), 'bucket': _bucket(task),
        'created_at': task.get('created_at'), 'date': (_local_date(task.get('created_at'), offset) or date.min).isoformat(),
        'deleted': bool(task.get('deleted_at')),
        'project_id': project_id, 'workflow_id': workflow_id, 'node_id': node_id,
        'estimate_usd': {'min': estimate['minimum_cost'], 'max': estimate['maximum_cost']} if known else None,
        'unknown_reason': reason,
        'unknown_reason_label': cost_estimate.UNKNOWN_REASONS.get(reason) if reason else None,
        'basis': estimate.get('basis'),
        'assumptions': {
            'ratio_assumed': estimate.get('ratio_assumed'),
            'input_duration_assumed': estimate.get('input_duration_assumed'),
            'input_video_seconds': estimate.get('input_video_seconds'),
            'output_seconds': [estimate.get('minimum_output_seconds'), estimate.get('maximum_output_seconds')],
            'promotion_active': estimate.get('promotion_active'),
        } if known else None,
    }


def build_ledger(project_id=None, workflow_id=None, date_from=None, date_to=None, tz_offset_minutes=0):
    offset = timedelta(minutes=tz_offset_minutes)
    db = task_db.get_db()
    projects, workflows, node_by_task = _canvas_index(db)
    rows = db.execute(
        'SELECT id, type, status, provider, params, result, created_at, deleted_at FROM tasks ORDER BY id DESC'
    ).fetchall()
    entries = []
    for row in rows:
        task = dict(row)
        task['params'] = task_db._from_json(task['params']) or {}
        task['result'] = task_db._from_json(task['result'])
        if not isinstance(task['params'], dict):
            task['params'] = {}
        entry = _entry(task, db, projects, workflows, node_by_task, offset)
        if project_id and entry['project_id'] != project_id:
            continue
        if workflow_id and entry['workflow_id'] != workflow_id:
            continue
        if date_from and entry['date'] < date_from.isoformat():
            continue
        if date_to and entry['date'] > date_to.isoformat():
            continue
        entries.append(entry)

    totals, by_type, by_date, by_project = _empty_totals(), {}, {}, {}
    for entry in entries:
        _add(totals, entry)
        _add(by_type.setdefault(entry['type'] or 'unknown', _empty_totals()), entry)
        _add(by_date.setdefault(entry['date'], _empty_totals()), entry)
        pid = entry['project_id']
        if pid not in by_project:
            meta = projects.get(pid, {})
            by_project[pid] = {
                'id': pid, 'kind': 'unassigned' if pid == UNASSIGNED else 'missing' if pid == MISSING else 'canvas',
                'title': '未归属项目（旧工具任务）' if pid == UNASSIGNED else '画布已删除' if pid == MISSING else meta.get('title') or pid,
                'deleted': bool(meta.get('deleted')), 'totals': _empty_totals(), 'workflows': {},
            }
        project = by_project[pid]
        _add(project['totals'], entry)
        if entry['workflow_id']:
            wf_meta = workflows.get(entry['workflow_id']) or {}
            wf = project['workflows'].setdefault(entry['workflow_id'], {
                'id': entry['workflow_id'], 'title': wf_meta.get('title') or '已删除画布',
                'deleted': bool(wf_meta.get('deleted')) or not wf_meta, 'totals': _empty_totals(), 'nodes': {},
            })
            _add(wf['totals'], entry)
            node_meta = (wf_meta.get('nodes') or {}).get(entry['node_id']) if entry['node_id'] else None
            node = wf['nodes'].setdefault(entry['node_id'] or '', {
                'node_id': entry['node_id'], 'title': (node_meta or {}).get('title'),
                'type': (node_meta or {}).get('type') or entry['type'],
                'missing': entry['node_id'] is not None and node_meta is None, 'totals': _empty_totals(),
            })
            _add(node['totals'], entry)

    def project_list():
        out = []
        for project in by_project.values():
            workflows_out = []
            for wf in project['workflows'].values():
                workflows_out.append({**wf, 'nodes': list(wf['nodes'].values())})
            out.append({**project, 'workflows': workflows_out})
        order = {UNASSIGNED: 2, MISSING: 1}
        return sorted(out, key=lambda item: (order.get(item['id'], 0), item['title']))

    return {
        'success': True, 'disclaimer': DISCLAIMER, 'currency': 'USD',
        'formula': 'byteplus-seedance-tokens-v%d' % cost_estimate.FORMULA_VERSION,
        'bucket_labels': BUCKET_LABELS, 'unknown_reason_labels': cost_estimate.UNKNOWN_REASONS,
        'filters': {'project_id': project_id, 'workflow_id': workflow_id,
                    'from': date_from.isoformat() if date_from else None,
                    'to': date_to.isoformat() if date_to else None,
                    'tz_offset_minutes': tz_offset_minutes},
        'totals': totals,
        'projects': project_list(),
        'types': [{'type': key, 'totals': value} for key, value in sorted(by_type.items())],
        'dates': [{'date': key, 'totals': value} for key, value in sorted(by_date.items(), reverse=True)],
        'tasks': entries[:TASK_LIMIT], 'tasks_total': len(entries), 'tasks_truncated': len(entries) > TASK_LIMIT,
    }


def register_routes(app):
    @app.route('/api/cost-ledger', methods=['GET'])
    def api_cost_ledger():
        args = request.args
        try:
            date_from = _parse_date(args.get('from'), 'from')
            date_to = _parse_date(args.get('to'), 'to')
            if date_from and date_to and date_from > date_to:
                raise LedgerError('from 不能晚于 to')
            raw_offset = args.get('tz_offset_minutes', '0') or '0'
            try:
                offset = int(raw_offset)
            except ValueError:
                raise LedgerError('tz_offset_minutes 必须是整数')
            if not -840 <= offset <= 840:
                raise LedgerError('tz_offset_minutes 超出范围')
        except LedgerError as error:
            return jsonify({'success': False, 'error': str(error)}), 400
        return jsonify(build_ledger(
            project_id=args.get('project_id') or None, workflow_id=args.get('workflow_id') or None,
            date_from=date_from, date_to=date_to, tz_offset_minutes=offset,
        ))
