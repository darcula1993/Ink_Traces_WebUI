"""Filesystem storage helpers for task inputs, outputs, and maintenance."""

import base64
import ctypes
import gc
import hashlib
import mimetypes
import os
import re
import shutil
import struct
import time
import uuid
import zlib
from datetime import datetime, timedelta, timezone

from PIL import Image

import tasks as task_db


PROJECT_ROOT = os.environ.get(
    'NANOBANANA_DATA_ROOT',
    os.path.dirname(os.path.dirname(__file__)),
)
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'output')
UPLOAD_VIDEO_DIR = os.path.join(PROJECT_ROOT, 'upload_video')
WORKSPACE_ASSET_DIR = os.path.join(PROJECT_ROOT, 'workspace_assets')
DATA_URL_PATTERN = re.compile(r'^data:([^;,]+)?;base64,(.+)$', re.DOTALL)
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
REFERENCE_ASSET_PATTERN = re.compile(r'^ref_(\d+)(?:\D|$)', re.IGNORECASE)

try:
    _MALLOC_TRIM = ctypes.CDLL(None).malloc_trim
    _MALLOC_TRIM.argtypes = [ctypes.c_size_t]
    _MALLOC_TRIM.restype = ctypes.c_int
except (AttributeError, OSError):
    _MALLOC_TRIM = None


def release_process_memory():
    gc.collect()
    if _MALLOC_TRIM is not None:
        _MALLOC_TRIM(0)


def iter_png_with_text(path, text_entries, chunk_size=1024 * 1024):
    """Yield a PNG with selected iTXt chunks replaced, preserving image bytes."""
    replacements = {str(keyword) for keyword in text_entries}
    with open(path, 'rb') as handle:
        signature = handle.read(len(PNG_SIGNATURE))
        if signature != PNG_SIGNATURE:
            yield signature
            for chunk in iter(lambda: handle.read(chunk_size), b''):
                yield chunk
            return

        yield signature
        while True:
            length_bytes = handle.read(4)
            if not length_bytes:
                return
            if len(length_bytes) != 4:
                yield length_bytes
                return
            length = struct.unpack('>I', length_bytes)[0]
            chunk_type = handle.read(4)
            if len(chunk_type) != 4:
                yield length_bytes + chunk_type
                return
            if chunk_type in (b'tEXt', b'zTXt', b'iTXt', b'IEND'):
                data = handle.read(length)
                checksum = handle.read(4)
                if len(data) != length or len(checksum) != 4:
                    yield length_bytes + chunk_type + data + checksum
                    return
                keyword = _png_text_keyword(chunk_type, data)
                if keyword in replacements:
                    continue
                if chunk_type == b'IEND':
                    for name, value in text_entries.items():
                        yield _png_itxt_chunk(name, value)
                yield length_bytes + chunk_type + data + checksum
                continue

            yield length_bytes + chunk_type
            remaining = length + 4
            while remaining:
                chunk = handle.read(min(chunk_size, remaining))
                if not chunk:
                    return
                yield chunk
                remaining -= len(chunk)


def _png_text_keyword(chunk_type, data):
    if chunk_type not in (b'tEXt', b'zTXt', b'iTXt') or b'\x00' not in data:
        return None
    return data.split(b'\x00', 1)[0].decode('latin-1', errors='ignore')


def _png_itxt_chunk(keyword, value):
    encoded_keyword = str(keyword).encode('latin-1')[:79]
    encoded_value = str(value).encode('utf-8')
    data = encoded_keyword + b'\x00\x00\x00\x00\x00' + encoded_value
    chunk_type = b'iTXt'
    checksum = zlib.crc32(chunk_type + data) & 0xffffffff
    return struct.pack('>I', len(data)) + chunk_type + data + struct.pack('>I', checksum)


def ensure_storage_dirs():
    os.makedirs(os.path.join(OUTPUT_DIR, 'image'), exist_ok=True)
    os.makedirs(os.path.join(OUTPUT_DIR, 'video'), exist_ok=True)
    os.makedirs(os.path.join(OUTPUT_DIR, 'audio'), exist_ok=True)
    os.makedirs(UPLOAD_VIDEO_DIR, exist_ok=True)
    os.makedirs(WORKSPACE_ASSET_DIR, exist_ok=True)


def task_output_dir(task_type, task_id):
    path = os.path.join(OUTPUT_DIR, task_type, str(task_id))
    os.makedirs(path, exist_ok=True)
    return path


def atomic_write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = f'{path}.{uuid.uuid4().hex}.tmp'
    try:
        with open(temp_path, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def image_has_alpha(image):
    """Return whether the source image carries an alpha/transparency channel."""
    return 'A' in image.getbands() or 'transparency' in image.info


def inspect_image(source):
    """Return provider-relevant image metadata without changing the source."""
    with Image.open(source) as image:
        image.load()
        return {
            'format': str(image.format or '').lower(),
            'width': int(image.width),
            'height': int(image.height),
            'pixels': int(image.width * image.height),
            'has_alpha': bool(image_has_alpha(image)),
        }


def inspect_uploaded_image(file_storage):
    file_storage.stream.seek(0)
    try:
        return inspect_image(file_storage.stream)
    finally:
        file_storage.stream.seek(0)


def save_normalized_image(image, path, output_format='PNG'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = f'{path}.{uuid.uuid4().hex}.tmp'
    normalized_format = str(output_format or 'PNG').upper()
    try:
        supports_alpha = normalized_format in {'PNG', 'WEBP', 'TIFF'}
        target_mode = 'RGBA' if supports_alpha and image_has_alpha(image) else 'RGB'
        image.convert(target_mode).save(temp_path, format=normalized_format)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def save_uploaded_image(file_storage, path):
    file_storage.seek(0)
    with Image.open(file_storage.stream) as image:
        image.load()
        save_normalized_image(image, path)
    return path


def save_data_url(data_url, path):
    _, encoded = data_url.split(',', 1)
    atomic_write(path, base64.b64decode(encoded))
    return path


def create_image_thumbnail(source_path, target_path, max_size=512):
    """Create a compact WebP preview without changing the original output."""
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    temp_path = f'{target_path}.{uuid.uuid4().hex}.tmp'
    try:
        with Image.open(source_path) as image:
            image.load()
            image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            if image.mode not in ('RGB', 'RGBA'):
                image = image.convert('RGBA' if 'transparency' in image.info else 'RGB')
            image.save(temp_path, format='WEBP', quality=82, method=4)
        os.replace(temp_path, target_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    return target_path


def _workspace_asset_extension(mime_type):
    extension = mimetypes.guess_extension(mime_type or '') or '.bin'
    return '.jpg' if extension in ('.jpe', '.jpeg') else extension


def persist_workspace_upload(key, file_storage, chunk_size=1024 * 1024, normalize_image=False):
    """Stream one browser asset to content-addressed workspace storage."""
    directory = os.path.join(WORKSPACE_ASSET_DIR, key)
    os.makedirs(directory, exist_ok=True)
    temp_path = os.path.join(directory, f'.{uuid.uuid4().hex}.tmp')
    digest = hashlib.sha256()
    size_bytes = 0
    mime_type = file_storage.mimetype or mimetypes.guess_type(file_storage.filename or '')[0] or 'application/octet-stream'
    stream = file_storage.stream
    stream.seek(0)
    try:
        with open(temp_path, 'wb') as handle:
            while True:
                chunk = stream.read(chunk_size)
                if not chunk:
                    break
                digest.update(chunk)
                size_bytes += len(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if normalize_image:
            normalized_path = os.path.join(directory, f'.{uuid.uuid4().hex}.normalized')
            try:
                with Image.open(temp_path) as image:
                    image.load()
                    save_normalized_image(image, normalized_path)
                os.remove(temp_path)
                temp_path = normalized_path
                mime_type = 'image/png'
                size_bytes = os.path.getsize(temp_path)
                digest = hashlib.sha256()
                with open(temp_path, 'rb') as handle:
                    for chunk in iter(lambda: handle.read(chunk_size), b''):
                        digest.update(chunk)
            finally:
                if os.path.exists(normalized_path) and normalized_path != temp_path:
                    os.remove(normalized_path)
        filename = f'{digest.hexdigest()}{_workspace_asset_extension(mime_type)}'
        path = os.path.join(directory, filename)
        if os.path.isfile(path):
            os.remove(temp_path)
        else:
            os.replace(temp_path, path)
        asset = {
            'url': f'/api/workspace/assets/{key}/{filename}',
            'name': file_storage.filename or filename,
            'mime_type': mime_type,
            'size_bytes': size_bytes,
        }
        if mime_type.startswith('image/'):
            asset.update(inspect_image(path))
        return asset
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def resolve_workspace_asset_url(key, url):
    prefix = f'/api/workspace/assets/{key}/'
    if not isinstance(url, str) or not url.startswith(prefix):
        return None
    filename = url[len(prefix):]
    if not filename or filename != os.path.basename(filename):
        return None
    directory = os.path.abspath(os.path.join(WORKSPACE_ASSET_DIR, key))
    path = os.path.abspath(os.path.join(directory, filename))
    if os.path.commonpath((directory, path)) != directory or not os.path.isfile(path):
        return None
    return path


def persist_workspace_value(key, value):
    """Write embedded data URLs to disk and return JSON-safe state with local URLs."""
    directory = os.path.join(WORKSPACE_ASSET_DIR, key)

    def persist(item):
        if isinstance(item, list):
            return [persist(child) for child in item]
        if isinstance(item, dict):
            return {name: persist(child) for name, child in item.items()}
        if not isinstance(item, str) or not item.startswith('data:'):
            return item

        match = DATA_URL_PATTERN.match(item)
        if not match:
            return item
        mime_type = match.group(1) or 'application/octet-stream'
        try:
            payload = base64.b64decode(match.group(2), validate=True)
        except (ValueError, TypeError):
            return item
        digest = hashlib.sha256(payload).hexdigest()
        filename = f'{digest}{_workspace_asset_extension(mime_type)}'
        path = os.path.join(directory, filename)
        if not os.path.isfile(path):
            atomic_write(path, payload)
        return f'/api/workspace/assets/{key}/{filename}'

    return persist(value)


def cleanup_workspace_assets(key, value):
    directory = os.path.join(WORKSPACE_ASSET_DIR, key)
    if not os.path.isdir(directory):
        return 0
    prefix = f'/api/workspace/assets/{key}/'
    referenced = set()

    def collect(item):
        if isinstance(item, list):
            for child in item:
                collect(child)
        elif isinstance(item, dict):
            for child in item.values():
                collect(child)
        elif isinstance(item, str) and item.startswith(prefix):
            referenced.add(item.rsplit('/', 1)[-1])

    collect(value)
    removed = 0
    now = time.time()
    for filename in os.listdir(directory):
        path = os.path.join(directory, filename)
        if filename not in referenced and os.path.isfile(path) and now - os.path.getmtime(path) >= 300:
            os.remove(path)
            removed += 1
    return removed


def save_image_file(source_path, target_path):
    with Image.open(source_path) as image:
        image.load()
        save_normalized_image(image, target_path)
    return target_path


def clone_workspace_image(source_path, target_path):
    if os.path.splitext(source_path)[1].lower() != '.png':
        return save_image_file(source_path, target_path)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    try:
        os.link(source_path, target_path)
    except OSError:
        shutil.copy2(source_path, target_path)
    return target_path


def stream_response_to_file(response, path, chunk_size=1024 * 1024):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = f'{path}.{uuid.uuid4().hex}.tmp'
    try:
        with open(temp_path, 'wb') as handle:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    return path


def register_file(task_id, kind, path, mime_type=None, expires_at=None):
    mime_type = mime_type or mimetypes.guess_type(path)[0]
    task_db.register_asset(task_id, kind, path, mime_type, expires_at)


def reference_asset_sort_key(asset):
    """Sort ref_2 before ref_10 while remaining compatible with legacy names."""
    path = asset.get('path', '') if isinstance(asset, dict) else str(asset)
    match = REFERENCE_ASSET_PATTERN.match(os.path.basename(path))
    if match:
        return 0, int(match.group(1)), path
    return 1, 0, path


def upload_expiry(hours=24):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def remove_task_files(task):
    paths = {asset['path'] for asset in task_db.list_assets(task['id'])}
    params = task.get('params') or {}
    paths.update(params.get('ref_video_paths') or [])
    for path in paths:
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass
    task_db.delete_assets(paths)

    output_dir = task.get('output_dir')
    if output_dir and os.path.isdir(output_dir):
        shutil.rmtree(output_dir, ignore_errors=True)


def remove_task_output_files(task_id):
    """Remove generated files while preserving references needed for retry."""
    removed = 0
    deleted_assets = []
    for asset in task_db.list_assets(task_id):
        if not asset['kind'].startswith('output_'):
            continue
        if os.path.isfile(asset['path']):
            try:
                os.remove(asset['path'])
                removed += 1
            except OSError:
                continue
        deleted_assets.append(asset['path'])
    task_db.delete_assets(deleted_assets)
    return removed


def clone_image_inputs(source_task_id, target_task_id):
    """Copy persisted image references into a new retry task directory."""
    target_dir = task_output_dir('image', target_task_id)
    copied = 0
    inputs = [asset for asset in task_db.list_assets(source_task_id) if asset['kind'] == 'input_image']
    inputs.sort(key=reference_asset_sort_key)
    for index, asset in enumerate(inputs):
        if not os.path.isfile(asset['path']):
            continue
        extension = os.path.splitext(asset['path'])[1].lower() or '.png'
        path = os.path.join(target_dir, f'ref_{index}{extension}')
        shutil.copy2(asset['path'], path)
        register_file(target_task_id, 'input_image', path, asset.get('mime_type'))
        copied += 1
    return target_dir, copied


def cleanup_expired_assets(now=None):
    now = now or datetime.now(timezone.utc).isoformat()
    removed = 0
    deleted_assets = []
    for asset in task_db.list_assets(expired_before=now):
        if os.path.isfile(asset['path']):
            try:
                os.remove(asset['path'])
                removed += 1
            except OSError:
                continue
        deleted_assets.append(asset['path'])
    task_db.delete_assets(deleted_assets)
    return removed


def cleanup_orphans(grace_seconds=24 * 60 * 60):
    """Remove old files that are not represented by a task or asset row."""
    ensure_storage_dirs()
    cutoff = time.time() - grace_seconds
    known_assets = {os.path.abspath(asset['path']) for asset in task_db.list_assets()}
    known_task_ids = set(task_db.list_task_ids(deleted=None))
    removed_files = 0
    removed_dirs = 0

    for root, _, files in os.walk(UPLOAD_VIDEO_DIR):
        for name in files:
            path = os.path.abspath(os.path.join(root, name))
            if path not in known_assets and os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed_files += 1

    for task_type in ('image', 'video', 'audio'):
        root = os.path.join(OUTPUT_DIR, task_type)
        if not os.path.isdir(root):
            continue
        for name in os.listdir(root):
            path = os.path.join(root, name)
            if not os.path.isdir(path) or not name.isdigit():
                continue
            if int(name) not in known_task_ids and os.path.getmtime(path) < cutoff:
                removed_files += sum(len(files) for _, _, files in os.walk(path))
                shutil.rmtree(path, ignore_errors=True)
                removed_dirs += 1

    return {'files': removed_files, 'directories': removed_dirs}


def storage_usage():
    ensure_storage_dirs()
    usage = shutil.disk_usage(PROJECT_ROOT)
    return {'total': usage.total, 'used': usage.used, 'free': usage.free}


ensure_storage_dirs()
