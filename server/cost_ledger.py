"""Project cost ledger built from task estimates (never actual charges), plus per-project budget soft-warning thresholds.

GET /api/cost-ledger?project_id=&workflow_id=&from=YYYY-MM-DD&to=YYYY-MM-DD&tz_offset_minutes=
GET /api/cost-ledger/budget?project_id=<id>[&workflow_id=<id>]
PUT /api/cost-ledger/budget  {"project_id": "<id>", "budget_usd": 5.0 | null}
Never calls a Provider; historical tasks without a stored snapshot are derived from
their params on the fly (basis=derived, 推算). Budget thresholds live in their own
idempotent table ``canvas_project_budgets`` without altering any legacy table.
"""
from datetime import date, datetime, timedelta, timezone
import json
import math
import re
import sqlite3

from flask import jsonify, request

import canvas_store as store
import cost_estimate
from local_delete import require_same_origin
import task_public
import tasks as task_db

UNASSIGNED = '__unassigned__'
MISSING = '__missing__'
DISCLAIMER = '估算，非实际扣费'
BUDGET_MAX_USD = 100000.0
_BUDGET_TABLE_SQL = '''
CREATE TABLE IF NOT EXISTS canvas_project_budgets (
    project_id TEXT PRIMARY KEY,
    budget_usd REAL,
    updated_at TEXT NOT NULL
)
'''
ADAPTER_LABELS = {
    'ark': 'BytePlus Ark',
    'cupsy': 'Cupsy',
    'google': 'Google',
}
VIDEO_MODEL_LABELS = {
    'seedance-2.0': 'Seedance 2.0',
    'seedance-2.5': 'Seedance 2.5',
    'seedance-2.5-moderated': 'Seedance 2.5 · 加强审核',
    'dreamina-seedance-2.5': 'Seedance 2.5',
}
AUDIO_MODEL_LABELS = {
    'seed-audio-1.0': 'Seed Audio 1.0',
}
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


def _profile_index(db):
    """Map profile_id / (profile_id, revision) -> human-readable name (including deleted profiles)."""
    by_rev = {}
    by_id = {}
    try:
        rows = db.execute(
            'SELECT profile_id, revision, private_document FROM provider_profile_revisions ORDER BY revision ASC'
        ).fetchall()
    except Exception:
        rows = []
    for row in rows:
        try:
            doc = json.loads(row['private_document'] or '{}')
        except (TypeError, ValueError):
            continue
        name = doc.get('name')
        if isinstance(name, str) and name.strip() and not name.startswith('__deleted__:'):
            cleaned = task_public.mask_endpoint_ids(name.strip())
            by_rev[(row['profile_id'], row['revision'])] = cleaned
            by_id[row['profile_id']] = cleaned
    try:
        heads = db.execute('SELECT id, name FROM provider_profiles').fetchall()
    except Exception:
        heads = []
    for row in heads:
        name = row['name']
        if row['id'] not in by_id and isinstance(name, str) and name.strip() and not name.startswith('__deleted__:'):
            by_id[row['id']] = task_public.mask_endpoint_ids(name.strip())
    return by_rev, by_id


def _safe_ledger_model(raw_model):
    if not isinstance(raw_model, str):
        return None
    cleaned = raw_model.strip()
    if not cleaned:
        return None
    if cleaned.lower().startswith('ep-'):
        return task_public.ENDPOINT_MASK
    return task_public.mask_endpoint_ids(cleaned)


def _model_label(task, params, estimate, db):
    task_type = task.get('type')
    provider = task.get('provider')
    raw_model = str(params.get('model') or '').strip()
    est_model = estimate.get('model') if isinstance(estimate, dict) else None
    if task_type in ('image', 'layer'):
        if est_model == cost_estimate.SEEDREAM_55:
            return 'Seedream 5.5'
        if est_model == cost_estimate.SEEDREAM_50_PRO:
            return 'Seedream 5.0 Pro'
        if provider in ('ark', 'cupsy') or task_type == 'layer':
            family = cost_estimate._image_family(task, params, db)
            return 'Seedream 5.5' if family == cost_estimate.SEEDREAM_55 else 'Seedream 5.0 Pro'
        safe = _safe_ledger_model(raw_model)
        return None if safe == task_public.ENDPOINT_MASK else safe
    if task_type == 'video':
        if raw_model == 'seedance-2.0' and params.get('fast'):
            return 'Seedance 2.0 Fast'
        if raw_model in VIDEO_MODEL_LABELS:
            return VIDEO_MODEL_LABELS[raw_model]
        if est_model == 'seedance-2.5':
            return 'Seedance 2.5'
        if est_model == 'seedance-2.0':
            return 'Seedance 2.0 Fast' if params.get('fast') else 'Seedance 2.0'
        safe = _safe_ledger_model(raw_model)
        return None if safe == task_public.ENDPOINT_MASK else safe
    if task_type == 'audio':
        if raw_model in AUDIO_MODEL_LABELS:
            return AUDIO_MODEL_LABELS[raw_model]
        if provider == 'cupsy':
            return 'Seed Audio 1.0'
        safe = _safe_ledger_model(raw_model)
        return None if safe == task_public.ENDPOINT_MASK else safe
    safe = _safe_ledger_model(raw_model)
    return None if safe == task_public.ENDPOINT_MASK else safe


def _entry(task, db, projects, workflows, node_by_task, profile_by_rev, profile_by_id, offset):
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
    provider = task.get('provider')
    profile_id = params.get('profile_id') if isinstance(params.get('profile_id'), str) and params.get('profile_id') else None
    profile_revision = params.get('profile_revision')
    profile_name = None
    if profile_id:
        profile_name = profile_by_id.get(profile_id) or profile_by_rev.get((profile_id, profile_revision))
    if not profile_name:
        profile_name = ADAPTER_LABELS.get(provider) or (task_public.mask_endpoint_ids(str(provider)) if provider else None)
    model_label = _model_label(task, params, estimate, db)
    return {
        'id': task['id'], 'type': task.get('type'), 'provider': provider,
        'profile_id': profile_id, 'profile_name': profile_name,
        'model': _safe_ledger_model(params.get('model')), 'model_label': model_label,
        'status': task.get('status'), 'bucket': _bucket(task),
        'created_at': task.get('created_at'), 'date': (_local_date(task.get('created_at'), offset) or date.min).isoformat(),
        'deleted': bool(task.get('deleted_at')),
        'project_id': project_id, 'workflow_id': workflow_id, 'node_id': node_id,
        'estimate_usd': {'min': estimate['minimum_cost'], 'max': estimate['maximum_cost']} if known else None,
        'unknown_reason': reason,
        'unknown_reason_label': cost_estimate.UNKNOWN_REASONS.get(reason) if reason else None,
        'basis': estimate.get('basis'),
        'assumption': estimate.get('assumption') if known else None,
        'assumptions': {
            'ratio_assumed': estimate.get('ratio_assumed'),
            'input_duration_assumed': estimate.get('input_duration_assumed'),
            'input_video_seconds': estimate.get('input_video_seconds'),
            'output_seconds': [estimate.get('minimum_output_seconds'), estimate.get('maximum_output_seconds')],
            'promotion_active': estimate.get('promotion_active'),
            'image_size': [estimate.get('width'), estimate.get('height')] if task.get('type') == 'image' else None,
            'size_assumed': estimate.get('size_assumed'),
            'reference_image_count': estimate.get('reference_count'),
            'output_count': estimate.get('output_count'),
            'below_floor_layers': estimate.get('below_floor_layers'),
        } if known else None,
    }


def _ensure_budget_table(db):
    db.execute(_BUDGET_TABLE_SQL)


def _has_budget_table(db):
    row = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='canvas_project_budgets'"
    ).fetchone()
    return row is not None


def _valid_project_id(value):
    if not isinstance(value, str):
        raise LedgerError('project_id 须为非空字符串')
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 120 or cleaned in (UNASSIGNED, MISSING):
        raise LedgerError('project_id 无效')
    return cleaned


def _valid_budget_usd(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LedgerError('budget_usd 须为正数或 null')
    amount = float(value)
    if not math.isfinite(amount) or amount <= 0 or amount > BUDGET_MAX_USD:
        raise LedgerError(f'budget_usd 须大于 0 且不超过 {int(BUDGET_MAX_USD)}')
    return amount


def _all_project_budgets(db):
    if not _has_budget_table(db):
        return {}
    try:
        rows = db.execute('SELECT project_id, budget_usd, updated_at FROM canvas_project_budgets').fetchall()
    except sqlite3.OperationalError:
        return {}
    return {row['project_id']: {'budget_usd': row['budget_usd'], 'updated_at': row['updated_at']} for row in rows}


def _get_project_budget_row(db, project_id):
    if not project_id or project_id in (UNASSIGNED, MISSING) or not _has_budget_table(db):
        return None
    try:
        row = db.execute(
            'SELECT project_id, budget_usd, updated_at FROM canvas_project_budgets WHERE project_id=?',
            (project_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return dict(row) if row is not None else None


def resolve_budget_project_id(db, project_id=None, workflow_id=None):
    if project_id:
        return _valid_project_id(project_id)
    if workflow_id:
        if not isinstance(workflow_id, str) or not workflow_id.strip() or len(workflow_id.strip()) > 120:
            raise LedgerError('workflow_id 无效')
        row = db.execute('SELECT project_id FROM canvas_workflows WHERE id=?', (workflow_id.strip(),)).fetchone()
        if row is None or not row['project_id']:
            raise LedgerError('画布不存在')
        return row['project_id']
    raise LedgerError('缺少 project_id')


def get_project_budget(project_id=None, workflow_id=None):
    db = task_db.get_db()
    resolved_id = resolve_budget_project_id(db, project_id=project_id, workflow_id=workflow_id)
    row = _get_project_budget_row(db, resolved_id)
    ledger = build_ledger(project_id=resolved_id)
    return {
        'success': True,
        'project_id': resolved_id,
        'budget_usd': row['budget_usd'] if row else None,
        'updated_at': row['updated_at'] if row else None,
        'disclaimer': DISCLAIMER,
        'currency': 'USD',
        'billable': ledger['totals']['billable'],
        'totals': ledger['totals'],
    }


def set_project_budget(project_id, budget_usd):
    resolved_id = _valid_project_id(project_id)
    amount = _valid_budget_usd(budget_usd)
    with store.write_transaction() as db:
        _ensure_budget_table(db)
        exists = db.execute('SELECT 1 FROM canvas_projects WHERE id=?', (resolved_id,)).fetchone()
        if exists is None:
            raise store.CanvasError('项目不存在', 404)
        if amount is None:
            db.execute('DELETE FROM canvas_project_budgets WHERE project_id=?', (resolved_id,))
            return {
                'success': True,
                'project_id': resolved_id,
                'budget_usd': None,
                'updated_at': None,
                'disclaimer': DISCLAIMER,
            }
        now = task_db.utcnow()
        db.execute(
            'INSERT OR REPLACE INTO canvas_project_budgets (project_id, budget_usd, updated_at) VALUES (?, ?, ?)',
            (resolved_id, amount, now),
        )
        return {
            'success': True,
            'project_id': resolved_id,
            'budget_usd': amount,
            'updated_at': now,
            'disclaimer': DISCLAIMER,
        }


def build_ledger(project_id=None, workflow_id=None, date_from=None, date_to=None, tz_offset_minutes=0):
    offset = timedelta(minutes=tz_offset_minutes)
    db = task_db.get_db()
    projects, workflows, node_by_task = _canvas_index(db)
    profile_by_rev, profile_by_id = _profile_index(db)
    budgets = _all_project_budgets(db)
    budget_project_id = None
    if project_id and project_id not in (UNASSIGNED, MISSING):
        budget_project_id = project_id
    elif workflow_id and workflow_id in workflows:
        budget_project_id = workflows[workflow_id]['project_id']
    rows = db.execute(
        'SELECT id, type, status, provider, params, result, created_at, deleted_at FROM tasks ORDER BY id DESC'
    ).fetchall()
    entries = []
    project_totals_all = _empty_totals() if budget_project_id else None
    for row in rows:
        task = dict(row)
        task['params'] = task_db._from_json(task['params']) or {}
        task['result'] = task_db._from_json(task['result'])
        if not isinstance(task['params'], dict):
            task['params'] = {}
        entry = _entry(task, db, projects, workflows, node_by_task, profile_by_rev, profile_by_id, offset)
        if project_totals_all is not None and entry['project_id'] == budget_project_id:
            _add(project_totals_all, entry)
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
            budget_meta = budgets.get(pid) if pid not in (UNASSIGNED, MISSING) else None
            by_project[pid] = {
                'id': pid, 'kind': 'unassigned' if pid == UNASSIGNED else 'missing' if pid == MISSING else 'canvas',
                'title': '未归属项目（旧工具任务）' if pid == UNASSIGNED else '画布已删除' if pid == MISSING else meta.get('title') or pid,
                'deleted': bool(meta.get('deleted')),
                'budget_usd': budget_meta['budget_usd'] if budget_meta else None,
                'totals': _empty_totals(), 'workflows': {},
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

    budget_row = budgets.get(budget_project_id) if budget_project_id else None
    return {
        'success': True, 'disclaimer': DISCLAIMER, 'currency': 'USD',
        'formula': 'byteplus-seedance-tokens-v%d+byteplus-image-v%d' % (
            cost_estimate.FORMULA_VERSION, cost_estimate.IMAGE_FORMULA_VERSION),
        'bucket_labels': BUCKET_LABELS, 'unknown_reason_labels': cost_estimate.UNKNOWN_REASONS,
        'filters': {'project_id': project_id, 'workflow_id': workflow_id,
                    'from': date_from.isoformat() if date_from else None,
                    'to': date_to.isoformat() if date_to else None,
                    'tz_offset_minutes': tz_offset_minutes},
        'budget_usd': budget_row['budget_usd'] if budget_row else None,
        'budget_project_id': budget_project_id,
        'project_billable': project_totals_all['billable'] if project_totals_all is not None else None,
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

    @app.route('/api/cost-ledger/budget', methods=['GET', 'PUT'])
    def api_cost_ledger_budget():
        if request.method == 'GET':
            try:
                return jsonify(get_project_budget(
                    project_id=request.args.get('project_id') or None,
                    workflow_id=request.args.get('workflow_id') or None,
                ))
            except LedgerError as error:
                return jsonify({'success': False, 'error': str(error)}), 400
        try:
            require_same_origin(request)
            data = request.get_json(silent=True)
            if not isinstance(data, dict) or 'budget_usd' not in data:
                raise LedgerError('请求须包含 project_id 与 budget_usd')
            return jsonify(set_project_budget(data.get('project_id'), data.get('budget_usd')))
        except store.CanvasError as error:
            return jsonify({'success': False, 'error': str(error)}), error.status
        except LedgerError as error:
            return jsonify({'success': False, 'error': str(error)}), 400
