"""SQL filtering/counting/pagination; never materialize all task details in Python."""
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

import tasks
import storage
import canvas_store as store

BASE = '''WITH
active_projects AS (SELECT p.* FROM canvas_projects p WHERE NOT EXISTS
 (SELECT 1 FROM canvas_deletions d WHERE d.scope='project' AND d.id=p.id)),
active_workflows AS (SELECT w.id,w.project_id FROM canvas_workflows w JOIN active_projects p ON p.id=w.project_id
 WHERE NOT EXISTS (SELECT 1 FROM canvas_deletions d WHERE d.scope='workflow' AND d.id=w.id)),
removed_library AS (SELECT j.value AS id FROM canvas_deletions d,json_each(d.manifest,'$.removed_library_ids') j),
raw_task_owners AS (
 SELECT task_id,workflow_id FROM canvas_workflow_tasks UNION
 SELECT id,json_extract(params,'$.canvas_workflow_id') FROM tasks WHERE json_extract(params,'$.canvas_workflow_id') IS NOT NULL),
task_owners AS (SELECT DISTINCT r.task_id,w.project_id FROM raw_task_owners r JOIN active_workflows w ON w.id=r.workflow_id),
raw_items AS (
 SELECT 'local:'||a.id AS key,'local' AS source,a.id AS id,a.name,a.kind,a.mime_type,a.size_bytes,a.created_at,
 :local_root||a.filename AS path,'[]' AS project_ids,'["uploaded"]' AS origins,NULL AS folder_id,NULL AS task_id,'' AS prompt,NULL AS thumbnails
 FROM canvas_local_uploads a
 UNION ALL
 SELECT 'library:'||a.id AS key,'library' AS source,a.id AS id,a.name,a.kind,a.mime_type,a.size_bytes,a.created_at,
 :library_root||a.project_id||'/'||a.filename AS path,json_array(a.project_id) AS project_ids,
 coalesce((SELECT json_group_array(origin) FROM canvas_catalog_origins o WHERE o.item_key='library:'||a.id),'[]') AS origins,
 l.folder_id,NULL AS task_id,'' AS prompt,NULL AS thumbnails
 FROM canvas_library_assets a JOIN active_projects p ON p.id=a.project_id
 LEFT JOIN canvas_library_asset_locations l ON l.asset_id=a.id WHERE a.id NOT IN (SELECT id FROM removed_library)
 UNION ALL
 SELECT 'workflow:'||a.id,'workflow',a.id,a.name,a.kind,a.mime_type,a.size_bytes,a.created_at,
 :canvas_root||a.workflow_id||'/'||a.filename,json_array(w.project_id),
 (SELECT json_group_array(origin) FROM canvas_catalog_origins o WHERE o.item_key='workflow:'||a.id),
 NULL,NULL,'',NULL FROM canvas_assets a JOIN active_workflows w ON w.id=a.workflow_id
 WHERE EXISTS (SELECT 1 FROM canvas_catalog_origins o WHERE o.item_key='workflow:'||a.id)
 UNION ALL
 SELECT 'task:'||a.id,'task',cast(a.id AS TEXT),'',substr(a.kind,8),a.mime_type,a.size_bytes,a.created_at,a.path,
 (SELECT json_group_array(project_id) FROM task_owners o WHERE o.task_id=t.id),'["generated"]',NULL,t.id,t.prompt,
 NULL
 FROM task_assets a JOIN tasks t ON t.id=a.task_id
 WHERE a.kind IN ('output_image','output_video','output_audio') AND t.status='succeeded' AND t.deleted_at IS NULL
 AND (NOT EXISTS (SELECT 1 FROM raw_task_owners o WHERE o.task_id=t.id) OR EXISTS (SELECT 1 FROM task_owners o WHERE o.task_id=t.id))
 AND NOT EXISTS (SELECT 1 FROM canvas_deletions d WHERE d.completed=0 AND json_extract(d.manifest,'$.cleanup_assets')=1
 AND EXISTS (SELECT 1 FROM json_each(d.manifest,'$.candidates') c WHERE json_extract(c.value,'$.task_id')=t.id AND json_extract(c.value,'$.output')=1)
 AND NOT EXISTS (SELECT 1 FROM json_each(d.manifest,'$.shared_task_ids') j WHERE j.value=t.id))
), items AS (
 SELECT r.*,CASE WHEN source='library' AND origins='[]' THEN '["saved"]' ELSE origins END AS effective_origins,
 CASE WHEN source='library' AND origins='[]' THEN 1 ELSE 0 END AS origin_unknown,
 CASE WHEN source='task' THEN catalog_basename(path) ELSE name END AS display_name
 FROM raw_items r WHERE NOT EXISTS (SELECT 1 FROM canvas_catalog_hidden h WHERE h.item_key=r.key)
), filtered AS (SELECT * FROM items WHERE
 (:scope='all' OR EXISTS (SELECT 1 FROM json_each(project_ids) j WHERE j.value=:project_id))
 AND (:folder_filter=0 OR (source!='task' AND folder_id IS :folder_id))
 AND (:q='' OR instr(lower(display_name||' '||coalesce(prompt,'')),lower(:q))>0)
 AND (:tag_id IS NULL OR EXISTS (SELECT 1 FROM canvas_catalog_item_tags t WHERE t.item_key=key AND t.tag_id=:tag_id))
)
'''


SELECT_ALL_LIMIT = 1000


def query(args, max_limit=100):
    db = tasks.get_db()
    owns_snapshot = not db.in_transaction
    if owns_snapshot:
        db.execute('BEGIN')
    try:
        return _query(args, max_limit)
    finally:
        if owns_snapshot:
            db.rollback()  # Read-only snapshot: counts and page observe the same state.


def task_thumbnail(row, db):
    if row['source'] != 'task':
        return None
    metadata = db.execute("SELECT output_dir,json_extract(result,'$.local_thumbnails') AS thumbs,json_extract(result,'$.local_thumbnail') AS thumb FROM tasks WHERE id=?", (row['task_id'],)).fetchone()
    thumbs = json.loads(metadata['thumbs']) if metadata['thumbs'] else []
    index = db.execute("SELECT count(*) FROM task_assets WHERE task_id=? AND kind=? AND id<?", (row['task_id'],'output_'+row['kind'],int(row['id']))).fetchone()[0]
    url = thumbs[index] if isinstance(thumbs,list) and index < len(thumbs) else metadata['thumb'] if index == 0 else None
    prefix = f"/api/tasks/{row['task_id']}/file/"
    if not isinstance(url,str) or not url.startswith(prefix) or not metadata['output_dir']:
        return None
    path = Path(metadata['output_dir']).absolute() / unquote(urlsplit(url).path[len(prefix):])
    root = Path(storage.OUTPUT_DIR).absolute()
    if path.resolve()!=path or not path.is_relative_to(root) or not path.is_file():
        return None
    if not db.execute("SELECT 1 FROM task_assets WHERE task_id=? AND path=? AND kind='output_thumbnail'", (row['task_id'],str(path))).fetchone():
        return None
    return url


def select_all(args):
    """Every item matching the current server filters (not just the loaded page)."""
    params = {k: v for k, v in args.items() if k not in ('limit', 'offset')}
    result = query({**params, 'limit': SELECT_ALL_LIMIT, 'offset': 0}, SELECT_ALL_LIMIT)
    if result['total'] > SELECT_ALL_LIMIT:
        raise store.CanvasError(f'当前筛选共 {result["total"]} 项，超过单次全选上限 {SELECT_ALL_LIMIT}，请缩小筛选', 409)
    return {'success': True, 'items': result['items'], 'total': result['total']}


def _query(args, max_limit=100):
    from canvas_catalog import SOURCES, KINDS
    source,scope,kind=args.get('source','local'),args.get('scope','project'),args.get('kind') or None
    pid=args.get('project_id')
    if source not in SOURCES or scope not in ('project','all') or (kind and kind not in KINDS):
        raise store.CanvasError('素材筛选无效')
    if scope=='project': store.get_project(pid)
    folder=args.get('folder_id')
    if folder is not None:
        if scope!='project' or source=='generated': raise store.CanvasError('文件夹筛选须选择项目内本地素材')
        from canvas_library_folders import validate_parent
        validate_parent(pid,folder or None)
    try: limit,offset=int(args.get('limit',50)),int(args.get('offset',0))
    except (TypeError,ValueError): raise store.CanvasError('分页参数无效')
    if not 1<=limit<=max_limit or not 0<=offset<=2147483647: raise store.CanvasError('分页参数超出范围')
    db=tasks.get_db()
    roots={'task':Path(storage.OUTPUT_DIR).absolute(),'library':store.asset_root(),'workflow':store.asset_root(),'local':store.asset_root()/'local_uploads'}
    def available(raw,source):
        path=Path(raw).absolute(); root=roots[source]
        return int(path.resolve()==path and root.resolve()==root and path.is_relative_to(root) and path.is_file())
    db.create_function('catalog_basename',1,lambda raw:Path(raw).name)
    params={'source':source,'scope':scope,'kind':kind,'project_id':pid,'folder_filter':int(folder is not None),
            'folder_id':folder or None,'q':args.get('q','').strip(),'tag_id':args.get('tag_id') or None,
            'local_root':str(roots['local'])+'/', 'canvas_root':str(roots['library'])+'/', 'library_root':str(roots['library'])+'/library/', 'limit':limit,'offset':offset}
    local_pred="EXISTS (SELECT 1 FROM json_each(effective_origins) j WHERE j.value IN ('saved','uploaded'))"
    source_pred=local_pred if source=='local' else "EXISTS (SELECT 1 FROM json_each(effective_origins) j WHERE j.value=:source)"
    kind_pred='(:kind IS NULL OR kind=:kind)'
    counts={s:0 for s in sorted(SOURCES)}
    for row in db.execute(BASE+f'SELECT j.value,count(*) AS total FROM filtered,json_each(effective_origins) j WHERE {kind_pred} GROUP BY j.value',params):
        if row['value'] in counts: counts[row['value']]=row['total']
    counts['local']=db.execute(BASE+f'SELECT count(*) FROM filtered WHERE {local_pred} AND {kind_pred}',params).fetchone()[0]
    kind_counts={k:0 for k in sorted(KINDS)}
    for row in db.execute(BASE+f'SELECT kind,count(*) AS total FROM filtered WHERE {source_pred} GROUP BY kind',params):
        kind_counts[row['kind']]=row['total']
    rows=db.execute(BASE+f'SELECT * FROM filtered WHERE {source_pred} AND {kind_pred} ORDER BY created_at DESC,key DESC LIMIT :limit OFFSET :offset',params).fetchall()
    page=[]
    from canvas_catalog import tags_for
    for row in rows:
        projects=json.loads(row['project_ids']); project=projects[0] if projects else None
        if row['source'] in ('task','local'): url=f"/api/canvas/library/items/{row['key']}/download?inline=1"
        elif row['source']=='library': url=f"/api/canvas/projects/{project}/assets/{row['id']}"
        else:
            wid=db.execute('SELECT workflow_id FROM canvas_assets WHERE id=?',(row['id'],)).fetchone()['workflow_id']
            url=f"/api/canvas/workflows/{wid}/assets/{row['id']}"
        asset={'id':row['id'],'name':row['display_name'],'kind':row['kind'],'mime_type':row['mime_type'],'size_bytes':row['size_bytes'],'url':url}
        page.append({'key':row['key'],'selection':{'source':row['source'],'id':row['id']},'asset':asset,
                     'project_id':project,'project_ids':projects,'project_title':store.get_project(project)['title'] if project else None,
                     'created_at':row['created_at'],'origins':json.loads(row['effective_origins']),'origin_unknown':bool(row['origin_unknown']),
                     'folder_id':row['folder_id'],'tags':tags_for(row['key']),'task_id':row['task_id'],
                     'available':bool(available(row['path'],row['source'])),
                     'thumbnail_url':task_thumbnail(row,db) or (f"/api/canvas/library/items/{row['key']}/thumbnail" if row['kind']=='image' else None)})
    return {'success':True,'items':page,'total':counts[source],'counts':counts,'source_counts':counts,'kind_counts':kind_counts,'limit':limit,'offset':offset}
