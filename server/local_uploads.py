"""Original user uploads: unowned durable copies, independent of tool/provider caches.

``capture_user_upload`` registers into the global media library (S6c); the old
``canvas_local_uploads`` helpers below remain for legacy readers until it is retired.
"""
from contextlib import contextmanager
import hashlib
import os
from PIL import Image
import logging
import uuid

import tasks
import canvas_store as store

LOG=logging.getLogger('nanobanana.local_uploads')


class UploadRegistrationError(ValueError):
    pass


def init_local_uploads_db():
    tasks.get_db().execute('''CREATE TABLE IF NOT EXISTS canvas_local_uploads (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, mime_type TEXT NOT NULL,
        kind TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE, size_bytes INTEGER NOT NULL,
        filename TEXT NOT NULL, created_at TEXT NOT NULL)''')
    tasks.get_db().commit()


def root():
    path=store.asset_root()/'local_uploads'
    if path.resolve()!=path:
        raise store.CanvasError('本地上传目录不安全')
    path.mkdir(parents=True,exist_ok=True)
    return path


def path_for(row):
    directory=root(); path=directory/row['filename']
    if path.resolve()!=path or not path.is_relative_to(directory) or not path.is_file():
        raise store.CanvasError('本地上传原文件不可读取',409)
    return path


@contextmanager
def capture_user_upload(upload, normalize_image=False):
    """Stage raw bytes before tool normalization; register the original only after the tool succeeds.

    LIBRARY-GLOBAL-20261116 S6c: the original is registered in the global media library
    (``media``, library root, origin ``upload``, dedup by content; content already in the
    library, 生成历史 included, is returned unchanged: S9, user decision 2026-11-17), not in
    the old ``canvas_local_uploads``.
    Tool/provider helpers have their own commits and run before the library transaction;
    a failed helper never registers anything. Image formats the library does not accept
    (e.g. BMP/TIFF): when the tool normalizes images (``normalize_image``, the old image tool)
    the same PNG conversion is registered under the original name with a ``.png`` extension
    (S7, user decision 2026-11-17; dedup by content); otherwise they are not registered.
    """
    import media_library
    name=upload.filename
    if not isinstance(name,str) or not name or len(name)>240 or any(c in name for c in '/\\') or any(ord(c)<32 for c in name):
        raise store.CanvasError('无效素材文件名')
    staging=media_library.root()/(uuid.uuid4().hex+'.capture.tmp')
    size=0
    operation_succeeded=False
    try:
        upload.stream.seek(0)
        with staging.open('xb') as output:
            while True:
                chunk=upload.stream.read(1024*1024)
                if not chunk: break
                size+=len(chunk)
                if size>store.MAX_ASSET_BYTES: raise store.CanvasError('素材不得超过100MiB',413)
                output.write(chunk)
            output.flush(); os.fsync(output.fileno())
        if not size: raise store.CanvasError('素材不能为空')
        registrable=True
        try:
            store._detect_media(staging)
        except store.CanvasError as unsupported:
            # Other PIL images the tool may still accept (and normalize) are not library formats.
            try:
                with Image.open(staging) as picture:
                    picture.verify()
            except (OSError, SyntaxError, Image.DecompressionBombError):
                raise unsupported from None
            registrable=False
        upload.stream.seek(0)
        yield
        operation_succeeded=True
        if registrable:
            with staging.open('rb') as handle:
                media_library.save_upload(handle,name,origin='upload')
        elif normalize_image:
            _register_converted_png(staging,name)
        else:
            LOG.info('original upload %r not registered: format not accepted by the media library',name)
    except Exception as error:
        if operation_succeeded:
            raise UploadRegistrationError('工具文件可能已上传（Cupsy可能已排队），但本地素材登记失败；请检查后重试，相同内容会去重') from error
        raise
    finally:
        staging.unlink(missing_ok=True)
        upload.stream.seek(0)


def _converted_name(name):
    stem=os.path.splitext(name)[0]
    return (stem or name)+'.png'


def _register_converted_png(staging,name):
    """Register the PNG the image tool produces (same ``storage.save_normalized_image``)."""
    import media_library
    import storage
    converted=staging.with_name(staging.name+'.png')
    try:
        with Image.open(staging) as picture:
            picture.load()
            storage.save_normalized_image(picture,str(converted))
        with converted.open('rb') as handle:
            media_library.save_upload(handle,_converted_name(name),origin='upload')
    finally:
        converted.unlink(missing_ok=True)


def stage_stream(stream, name):
    """Stage and content-check bytes for registration (no database lock held).

    Used by sources that register an original or a copy directly as 本地素材
    (character library upload, copies of non-local selections). Returns a dict for
    ``publish_staged``; the caller must unlink ``staged['path']`` on failure.
    """
    if not isinstance(name,str) or not name or len(name)>240 or any(c in name for c in '/\\') or any(ord(c)<32 for c in name):
        raise store.CanvasError('无效素材文件名')
    ident=uuid.uuid4().hex
    staging=root()/(ident+'.tmp')
    digest=hashlib.sha256(); size=0
    try:
        with staging.open('xb') as output:
            while True:
                chunk=stream.read(1024*1024)
                if not chunk: break
                size+=len(chunk)
                if size>store.MAX_ASSET_BYTES: raise store.CanvasError('素材不得超过100MiB',413)
                digest.update(chunk); output.write(chunk)
            output.flush(); os.fsync(output.fileno())
        if not size: raise store.CanvasError('素材不能为空')
        mime,extension=store._detect_media(staging)
    except BaseException:
        staging.unlink(missing_ok=True)
        raise
    return {'id':ident,'path':staging,'name':name,'mime_type':mime,'extension':extension,'sha256':digest.hexdigest(),'size_bytes':size}


def publish_staged(db, staged):
    """Register a staged file inside the caller's write transaction (dedup by content)."""
    existing=db.execute('SELECT * FROM canvas_local_uploads WHERE sha256=?',(staged['sha256'],)).fetchone()
    if existing:
        path_for(existing)
        staged['path'].unlink(missing_ok=True)
        row=dict(existing)
    else:
        target=root()/(staged['id']+staged['extension'])
        os.replace(staged['path'],target)
        journal=store._transaction_files.get()
        if journal is not None and journal[0] is db:
            journal[1].append(('canvas_local_uploads',staged['id'],target))
        mime=staged['mime_type']
        db.execute('INSERT INTO canvas_local_uploads VALUES (?,?,?,?,?,?,?,?)',
                   (staged['id'],staged['name'],mime,mime.split('/')[0],staged['sha256'],staged['size_bytes'],target.name,tasks.utcnow()))
        row=dict(db.execute('SELECT * FROM canvas_local_uploads WHERE id=?',(staged['id'],)).fetchone())
    db.execute('DELETE FROM canvas_catalog_hidden WHERE item_key=?',('local:'+row['id'],))
    return row
