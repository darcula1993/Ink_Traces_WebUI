"""Original user uploads: unowned durable copies, independent of tool/provider caches."""
from contextlib import contextmanager
import hashlib
import os
import mimetypes
from PIL import Image, UnidentifiedImageError
import uuid

import tasks
import canvas_store as store


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
def capture_user_upload(upload):
    """Stage raw bytes before tool normalization; publish only after upload succeeds.

    Tool/provider helpers have their own commits. They run before the independent
    catalog transaction; a failed helper never publishes a local catalog entry.
    """
    name=upload.filename
    if not isinstance(name,str) or not name or len(name)>240 or any(c in name for c in '/\\') or any(ord(c)<32 for c in name):
        raise store.CanvasError('无效素材文件名')
    ident=uuid.uuid4().hex
    staging=root()/(ident+'.tmp')
    digest=hashlib.sha256(); size=0
    operation_succeeded=False
    try:
        upload.stream.seek(0)
        with staging.open('xb') as output:
            while True:
                chunk=upload.stream.read(1024*1024)
                if not chunk: break
                size+=len(chunk)
                if size>store.MAX_ASSET_BYTES: raise store.CanvasError('素材不得超过100MiB',413)
                digest.update(chunk); output.write(chunk)
            output.flush(); os.fsync(output.fileno())
        if not size: raise store.CanvasError('素材不能为空')
        try:
            with Image.open(staging) as picture:
                image_format=picture.format
                picture.verify()
            mime=Image.MIME.get(image_format, 'image/'+image_format.lower())
            extension=mimetypes.guess_extension(mime) or '.'+image_format.lower()
        except UnidentifiedImageError:
            mime,extension=store._detect_media(staging)
        upload.stream.seek(0)
        yield
        operation_succeeded=True
        checksum=digest.hexdigest()
        with store.write_transaction() as db:
            existing=db.execute('SELECT * FROM canvas_local_uploads WHERE sha256=?',(checksum,)).fetchone()
            if existing:
                path_for(existing)
                saved_id=existing['id']
            else:
                target=root()/(ident+extension)
                os.replace(staging,target)
                journal=store._transaction_files.get()
                if journal is not None and journal[0] is db:
                    journal[1].append(('canvas_local_uploads',ident,target))
                db.execute('INSERT INTO canvas_local_uploads VALUES (?,?,?,?,?,?,?,?)',
                           (ident,name,mime,mime.split('/')[0],checksum,size,target.name,tasks.utcnow()))
                saved_id=ident
            db.execute('DELETE FROM canvas_catalog_hidden WHERE item_key=?',('local:'+saved_id,))
    except Exception as error:
        if operation_succeeded:
            raise UploadRegistrationError('工具文件可能已上传（Cupsy可能已排队），但本地素材登记失败；请检查后重试，相同内容会去重') from error
        raise
    finally:
        staging.unlink(missing_ok=True)
        upload.stream.seek(0)


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
