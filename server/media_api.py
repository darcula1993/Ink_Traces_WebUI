"""HTTP routes for the global media library (LIBRARY-GLOBAL-20261116 S1a).

Coexists with the old ``/api/canvas/library/*`` routes; application-wide auth guards it.
Errors: ``{success:false, error, code}``; codes are listed in the task log contract.
"""
import io

from flask import Blueprint, jsonify, request, send_file
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

import canvas_store as store
import media_library as media
from canvas_api import body
from local_delete import require_same_origin

media_api = Blueprint('media_api', __name__)
PREFIX = '/api/canvas/media'


@media_api.errorhandler(store.CanvasError)
def media_error(error):
    payload = {'success': False, 'error': str(error), 'code': getattr(error, 'code', None) or
               {404: 'media_not_found', 403: 'cross_site', 413: 'file_too_large', 415: 'invalid_request'}.get(error.status, 'invalid_request')}
    if getattr(error, 'media', None):
        payload['media'] = error.media
    return jsonify(payload), error.status


@media_api.errorhandler(BadRequest)
def invalid_body(error):
    return jsonify(success=False, error='请求数据格式无效', code='invalid_request'), 400


@media_api.errorhandler(RequestEntityTooLarge)
def too_large(error):
    return jsonify(success=False, error='请求数据超过大小限制', code='file_too_large'), 413


def _filters(args):
    folder = args.get('folder_id') or None
    page, limit = args.get('page', '1'), args.get('limit', '50')
    if not page.isdigit() or not limit.isdigit():
        raise media.MediaError('分页参数无效')
    finalized_raw = (args.get('finalized_only') or '').strip().lower()
    if finalized_raw not in ('', '0', '1', 'false', 'true'):
        raise media.MediaError('finalized_only 参数无效')
    return int(page), int(limit), {
        'folder_id': folder,
        'include_subfolders': args.get('include_subfolders') == '1',
        'kind': args.get('kind') or None,
        'q': args.get('q') or None,
        'origin': args.get('origin') or None,
        'sort': args.get('sort') or 'newest',
        'project_id': args.get('project_id') or None,
        'workflow_id': args.get('workflow_id') or None,
        'finalized_only': finalized_raw in ('1', 'true'),
    }


@media_api.route(PREFIX, methods=['GET', 'POST'])
def collection():
    if request.method == 'GET':
        page, limit, filters = _filters(request.args)
        return jsonify(success=True, **media.list_media(page=page, limit=limit, **filters))
    upload = request.files.get('file')
    if upload is None:
        raise media.MediaError('请选择素材文件')
    item, deduplicated = media.save_upload(upload.stream, upload.filename, folder_id=request.form.get('folder_id') or None,
                                           origin=request.form.get('origin') or 'upload')
    return jsonify(success=True, media=item, deduplicated=deduplicated), 200 if deduplicated else 201


@media_api.get(PREFIX + '/ids')
def ids():
    _, _, filters = _filters(request.args)
    return jsonify(success=True, **media.select_ids(**filters))


@media_api.get(PREFIX + '/history-filters')
def history_filters():
    return jsonify(success=True, **media.history_filter_options())


@media_api.get(PREFIX + '/<media_id>')
def read_file(media_id):
    row = media.get_media(media_id)
    try:
        response = send_file(media.media_path(row), mimetype=row['mime_type'], download_name=row['name'],
                             as_attachment=request.args.get('download') == '1', conditional=True)
    except FileNotFoundError:
        media.get_media(media_id)  # recheck for a tombstone if delete won the file-open race
        raise media.MediaError('素材文件不可读取', 409, 'file_missing') from None
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cache-Control'] = 'private, no-cache'
    return response


@media_api.patch(PREFIX + '/<media_id>')
def rename(media_id):
    data = body()
    if set(data) != {'name'}:
        raise media.MediaError('只支持修改素材名称 name', 400, 'invalid_request')
    return jsonify(success=True, media=media.rename_media(media_id, data['name']))


@media_api.get(PREFIX + '/<media_id>/info')
def info(media_id):
    return jsonify(success=True, media=media.public(media.get_media(media_id)))


@media_api.get(PREFIX + '/<media_id>/references')
def references(media_id):
    return jsonify(success=True, **media.media_references(media_id))


@media_api.get(PREFIX + '/<media_id>/thumbnail')
def thumbnail(media_id):
    from PIL import Image, ImageOps
    row = media.get_media(media_id)
    if row['kind'] == 'video':
        thumb = media.ensure_video_thumbnail(row)
        if thumb is None:
            raise media.MediaError('此视频暂无可用封面缩略图', 404, 'no_thumbnail')
        try:
            response = send_file(thumb, mimetype='image/webp', conditional=True)
        except FileNotFoundError:
            media.get_media(media_id)
            raise media.MediaError('缩略图不可用', 409, 'file_missing') from None
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'private, max-age=60'
        return response
    if row['kind'] != 'image':
        raise media.MediaError('此素材没有缩略图', 404, 'no_thumbnail')
    output = io.BytesIO()
    try:
        with Image.open(media.media_path(row)) as original:
            original.draft('RGB', (320, 320))
            picture = ImageOps.exif_transpose(original)
            picture.thumbnail((320, 320))
            picture.convert('RGB').save(output, format='WEBP', quality=75)
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        if isinstance(error, FileNotFoundError):
            media.get_media(media_id)
        raise media.MediaError('缩略图不可用', 409, 'file_missing') from error
    output.seek(0)
    response = send_file(output, mimetype='image/webp')
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cache-Control'] = 'private, max-age=60'
    return response


@media_api.post(PREFIX + '/lookup')
def lookup():
    return jsonify(success=True, **media.lookup(body().get('refs')))


@media_api.post(PREFIX + '/move')
def move():
    data = body()
    if 'folder_id' not in data:
        raise media.MediaError('缺少目标文件夹 folder_id（根目录传 null）')
    return jsonify(success=True, **media.move_media(data.get('ids'), data['folder_id']))


@media_api.route(PREFIX + '/folders', methods=['GET', 'POST'])
def folders():
    if request.method == 'GET':
        return jsonify(success=True, folders=media.list_folders())
    return jsonify(success=True, folder=media.create_folder(body())), 201


@media_api.route(PREFIX + '/folders/<folder_id>', methods=['PATCH', 'DELETE'])
def folder_detail(folder_id):
    if request.method == 'PATCH':
        return jsonify(success=True, folder=media.update_folder(folder_id, body()))
    media.delete_folder(folder_id)
    return jsonify(success=True)


@media_api.post(PREFIX + '/delete-preview')
def delete_preview():
    require_same_origin(request)
    return jsonify(success=True, **media.delete_preview(body().get('ids')))


@media_api.post(PREFIX + '/delete')
def delete():
    require_same_origin(request)
    return jsonify(success=True, **media.delete_media(body().get('ids')))


@media_api.route(PREFIX + '/groups', methods=['GET', 'POST'])
def groups():
    if request.method == 'GET':
        return jsonify(success=True, groups=media.list_groups())
    data = body()
    return jsonify(success=True, group=media.create_group(data.get('title'), data.get('media_ids'))), 201


@media_api.route(PREFIX + '/groups/<group_id>', methods=['GET', 'PATCH', 'DELETE'])
def group_detail(group_id):
    if request.method == 'GET':
        return jsonify(success=True, **media.expand_group(group_id, include_deleted=request.args.get('include_deleted') != '0'))
    if request.method == 'PATCH':
        return jsonify(success=True, group=media.update_group(group_id, body()))
    media.delete_group(group_id)
    return jsonify(success=True)
