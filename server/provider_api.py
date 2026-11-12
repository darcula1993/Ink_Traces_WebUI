"""Same-origin credential configuration API, guarded by application authentication."""
import json
import sqlite3
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

import provider_profiles as profiles

provider_api = Blueprint('provider_api', __name__)


@provider_api.errorhandler(profiles.ProfileError)
def profile_error(error):
    return jsonify(success=False, error=str(error)), error.status


@provider_api.errorhandler(sqlite3.Error)
def storage_error(error):
    return jsonify(success=False, error='接口配置存储暂不可用'), 503


@provider_api.errorhandler(RequestEntityTooLarge)
def large_request(error):
    return jsonify(success=False, error='接口配置请求过大'), 413


@provider_api.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@provider_api.before_request
def protect_writes():
    if request.method not in ('POST', 'PATCH', 'DELETE'):
        return
    if request.headers.get('Sec-Fetch-Site') not in (None, 'same-origin', 'none'):
        raise profiles.ProfileError('接口配置只允许同源修改', 403)
    origin = request.headers.get('Origin')
    if origin:
        expected_scheme = request.headers.get('X-Forwarded-Proto', request.scheme)
        try:
            parsed = urlsplit(origin)
            valid = parsed.scheme == expected_scheme and parsed.netloc == request.host and parsed.path in ('', '/') and not parsed.query and not parsed.fragment
        except ValueError:
            valid = False
        if not valid:
            raise profiles.ProfileError('接口配置只允许同源修改', 403)
    if not request.is_json:
        raise profiles.ProfileError('接口配置写入必须使用JSON', 415)


def body():
    raw = request.stream.read(32769)
    if len(raw) > 32768:
        raise profiles.ProfileError('接口配置请求过大', 413)
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        raise profiles.ProfileError('接口配置请求格式无效')
    if not isinstance(data, dict):
        raise profiles.ProfileError('接口配置请求必须为对象')
    return data


@provider_api.route('/api/provider-profiles', methods=['GET', 'POST'])
def collection():
    if request.method == 'GET':
        return jsonify(success=True, profiles=profiles.list_profiles(request.args.get('kind')))
    return jsonify(success=True, profile=profiles.save_profile(body())), 201


@provider_api.route('/api/provider-profiles/<profile_id>', methods=['GET', 'PATCH', 'DELETE'])
def item(profile_id):
    if request.method == 'GET':
        return jsonify(success=True, profile=profiles.public_profile(profiles.load_profile(profile_id)))
    data = body()
    if request.method == 'DELETE':
        if set(data) != {'revision'}:
            raise profiles.ProfileError('停用配置需要当前revision')
        data['enabled'] = False
    return jsonify(success=True, profile=profiles.save_profile(data, profile_id))
