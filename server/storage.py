"""Filesystem storage helpers for task inputs, outputs, and maintenance."""

import base64
import hashlib
import mimetypes
import os
import re
import shutil
import time
import uuid
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


def ensure_storage_dirs():
    os.makedirs(os.path.join(OUTPUT_DIR, 'image'), exist_ok=True)
    os.makedirs(os.path.join(OUTPUT_DIR, 'video'), exist_ok=True)
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


def save_normalized_image(image, path, output_format='PNG'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = f'{path}.{uuid.uuid4().hex}.tmp'
    try:
        image.convert('RGB').save(temp_path, format=output_format)
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
    for filename in os.listdir(directory):
        path = os.path.join(directory, filename)
        if filename not in referenced and os.path.isfile(path):
            os.remove(path)
            removed += 1
    return removed


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
    inputs.sort(key=lambda asset: asset['path'])
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

    for task_type in ('image', 'video'):
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
