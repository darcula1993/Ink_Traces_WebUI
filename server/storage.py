"""Filesystem storage helpers for task inputs, outputs, and maintenance."""

import base64
import mimetypes
import os
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


def ensure_storage_dirs():
    os.makedirs(os.path.join(OUTPUT_DIR, 'image'), exist_ok=True)
    os.makedirs(os.path.join(OUTPUT_DIR, 'video'), exist_ok=True)
    os.makedirs(UPLOAD_VIDEO_DIR, exist_ok=True)


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
        task_db.delete_asset(path)

    output_dir = task.get('output_dir')
    if output_dir and os.path.isdir(output_dir):
        shutil.rmtree(output_dir, ignore_errors=True)


def cleanup_expired_assets(now=None):
    now = now or datetime.now(timezone.utc).isoformat()
    removed = 0
    for asset in task_db.list_assets(expired_before=now):
        if os.path.isfile(asset['path']):
            try:
                os.remove(asset['path'])
                removed += 1
            except OSError:
                continue
        task_db.delete_asset(asset['path'])
    return removed


def cleanup_orphans(grace_seconds=24 * 60 * 60):
    """Remove old files that are not represented by a task or asset row."""
    ensure_storage_dirs()
    cutoff = time.time() - grace_seconds
    known_assets = {os.path.abspath(asset['path']) for asset in task_db.list_assets()}
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
            if task_db.get_task(int(name)) is None and os.path.getmtime(path) < cutoff:
                removed_files += sum(len(files) for _, _, files in os.walk(path))
                shutil.rmtree(path, ignore_errors=True)
                removed_dirs += 1

    return {'files': removed_files, 'directories': removed_dirs}


def storage_usage():
    ensure_storage_dirs()
    usage = shutil.disk_usage(PROJECT_ROOT)
    return {'total': usage.total, 'used': usage.used, 'free': usage.free}


ensure_storage_dirs()
