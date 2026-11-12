"""Local, project-scoped folder archives, completed before any response is sent."""
import re
import shutil
import tempfile
import zipfile
from pathlib import PurePosixPath

from flask import send_file

import canvas_store as store
import canvas_library_folders as folders


def safe_name(value):
    name = re.sub(r'[\\/\\\\:*?"<>|\x00-\x1f\x7f]', '_', value).strip(' .')[:180]
    return name or 'untitled'


def unique_name(name, used):
    candidate, number = name, 1
    while candidate.casefold() in used:
        number += 1
        path = PurePosixPath(name)
        candidate = f'{path.stem} ({number}){path.suffix}'
    used.add(candidate.casefold())
    return candidate


def folder_archive(project_id, folder_id):
    archive = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode='w+b')
    try:
        # Snapshot metadata under a short lock; never hold a DB write lock for media I/O.
        plan = []
        with store.write_transaction():
            root = folders.folder(project_id, folder_id)
            children = {}
            for item in folders.list_folders(project_id):
                children.setdefault(item['parent_id'], []).append(item)
            assets_by_folder = {}
            for asset_id, parent in folders.placements(project_id).items():
                assets_by_folder.setdefault(parent, []).append(asset_id)
            queue, seen = [(root, safe_name(root['title']))], set()
            while queue:
                item, prefix = queue.pop()
                if item['id'] in seen:
                    raise store.CanvasError('文件夹层级无效', 409)
                seen.add(item['id'])
                plan.append((prefix + '/', None))
                used = set()
                for child in children.get(item['id'], []):
                    name = unique_name(safe_name(child['title']), used)
                    queue.append((child, prefix + '/' + name))
                for asset_id in sorted(assets_by_folder.get(item['id'], [])):
                    asset = store.get_asset(project_id, asset_id, library=True)
                    name = unique_name(safe_name(asset['name']), used)
                    plan.append((prefix + '/' + name, asset))
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as output:
            for name, asset in plan:
                if asset is None:
                    output.writestr(name, b'')
                    continue
                try:
                    # Unlink before open fails the whole request; unlink after open leaves
                    # the POSIX descriptor readable, so the captured snapshot stays complete.
                    path = store.asset_path(asset)
                    with path.open('rb') as source, output.open(name, 'w', force_zip64=True) as target:
                        shutil.copyfileobj(source, target, length=1024 * 1024)
                except (OSError, store.CanvasError) as exc:
                    raise store.CanvasError('素材文件缺失或不可读，无法下载完整文件夹', 409) from exc
        store.get_project(project_id)
        archive.seek(0)
        response = send_file(archive, mimetype='application/zip', as_attachment=True,
                             download_name=safe_name(root['title']) + '.zip', conditional=False)
        response.call_on_close(archive.close)
        return response
    except BaseException:
        archive.close()
        raise
