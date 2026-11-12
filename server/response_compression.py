"""Bounded gzip for JSON and fingerprinted frontend assets, never media streams."""

import gzip
from functools import lru_cache

from flask import request


@lru_cache(maxsize=16)
def _compress_static(etag, data):
    return gzip.compress(data, compresslevel=5, mtime=0)


def install_compression(app):
    @app.after_request
    def compress_response(response):
        static_asset = request.path.startswith('/assets/')
        compressible = response.mimetype in {
            'application/json', 'application/javascript', 'text/javascript',
            'text/css', 'text/html', 'image/svg+xml',
        }
        if response.status_code == 304 and static_asset:
            response.vary.add('Accept-Encoding')
            return response
        if not compressible:
            return response
        response.vary.add('Accept-Encoding')
        if (request.method != 'GET' or response.status_code != 200
                or response.headers.get('Content-Encoding') or 'Range' in request.headers
                or response.cache_control.no_transform
                or request.accept_encodings['gzip'] <= 0):
            return response
        if response.direct_passthrough and not static_asset:
            return response
        length = response.content_length
        if length is None or not 1024 <= length <= 2 * 1024 * 1024:
            return response
        response.direct_passthrough = False
        raw = response.get_data()
        etag, _ = response.get_etag()
        encoded = _compress_static(etag, raw) if static_asset else gzip.compress(raw, compresslevel=5, mtime=0)
        if len(encoded) >= len(raw):
            return response
        response.set_data(encoded)
        response.headers['Content-Encoding'] = 'gzip'
        # Both encodings are semantically equivalent; weak validators permit 304
        # across the uncompressed send_file response and its compressed variant.
        if etag:
            response.set_etag(etag, weak=True)
        return response
