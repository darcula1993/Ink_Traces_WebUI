"""HTTP routes for canvas group runs (GROUP-RUN-20261115; contract in the task log)."""
from flask import jsonify, request

import canvas_group_run as group_run

PREFIX = '/api/canvas/workflows/<workflow_id>'


def register_routes(blueprint, body):
    @blueprint.errorhandler(group_run.GroupRunError)
    def group_run_error(error):
        return jsonify(success=False, error=str(error), code=error.code, **error.extra), error.status

    @blueprint.route(PREFIX + '/groups/<group_id>/run-preview', methods=['POST'])
    def group_run_preview(workflow_id, group_id):
        return jsonify(success=True, preview=group_run.preview(workflow_id, group_id, body().get('revision')))

    @blueprint.route(PREFIX + '/group-runs', methods=['GET', 'POST'])
    def group_runs(workflow_id):
        if request.method == 'GET':
            return jsonify(success=True, runs=group_run.list_runs(
                workflow_id, active=request.args.get('active') in ('1', 'true'), group_id=request.args.get('group_id') or None))
        data = body()
        run = group_run.create_run(workflow_id, data.get('group_id'), data.get('revision'), data.get('preview_token'))
        return jsonify(success=True, run=run), 201

    @blueprint.route(PREFIX + '/group-runs/<run_id>', methods=['GET'])
    def group_run_detail(workflow_id, run_id):
        return jsonify(success=True, run=group_run.get_run(workflow_id, run_id))

    @blueprint.route(PREFIX + '/group-runs/<run_id>/cancel', methods=['POST'])
    def group_run_cancel(workflow_id, run_id):
        return jsonify(success=True, run=group_run.cancel(workflow_id, run_id))

    @blueprint.route(PREFIX + '/group-runs/<run_id>/confirm', methods=['POST'])
    def group_run_confirm(workflow_id, run_id):
        token = body().get('confirm_token')
        if not isinstance(token, str) or not token:
            raise group_run.GroupRunError('缺少费用确认凭据', 'invalid_request')
        return jsonify(success=True, run=group_run.confirm(workflow_id, run_id, token))
