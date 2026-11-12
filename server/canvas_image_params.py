"""Single-shot image options, saved-node request guards, and bounded image metadata."""
from functools import lru_cache
from PIL import Image

import canvas_store as store
import storage
import seedream55 as seedream55_capabilities

BOOL_FIELDS = {'watermark', 'lock_aspect_ratio'}
ENUM_FIELDS = {'output_format': {'png','jpeg'}, 'background': {'default','auto','transparent','opaque'}}
IMAGE_FIELDS = BOOL_FIELDS | set(ENUM_FIELDS) | {'custom_width','custom_height'}


def validate_field(kind, key, value):
    if kind != 'image':
        raise store.CanvasError('此参数仅适用于图像生成节点')
    if key in BOOL_FIELDS and type(value) is not bool:
        raise store.CanvasError('图像开关参数必须为布尔值')
    if key in ENUM_FIELDS and (not isinstance(value,str) or value not in ENUM_FIELDS[key]):
        raise store.CanvasError('图像参数选项无效')
    if key in ('custom_width','custom_height') and (type(value) is not int or not 1 <= value <= 2147483647):
        raise store.CanvasError('自定义宽高必须为正整数')


def capabilities():
    import app
    providers={}
    for provider in ('ark','cupsy'):
        modern=provider=='ark' and seedream55_capabilities.enabled()
        size_map=app.ARK_SEEDREAM_PRO_SIZE_MAP if provider=='ark' else app.CUPSY_SEEDREAM_SIZE_MAP
        if modern: size_map={**size_map, '1.5K':seedream55_capabilities.SIZES}
        providers[provider]={'ratios': list(size_map['1K'])+(['auto','custom'] if provider=='ark' else ['custom']),
            'resolutions':['1K','1.5K','2K'] if modern else ['1K','2K'], 'formats':['png','jpeg'],
            'backgrounds':['default','auto','transparent','opaque'] if modern else ['default','transparent','opaque'] if provider=='ark' else ['default'],
            'watermark':True,
            'max_references':10,'max_reference_bytes':None,
            'size_map':size_map, 'custom':{'multiple':16,'min_pixels':921600,'max_pixels':4624220,'min_ratio':1/16,'max_ratio':16},
            'defaults':{'ratio':'1:1','resolution':'1K','output_format':'png','background':'default','watermark':False}}
    return providers


def normalized_saved(params, provider):
    import app
    spec=capabilities()[provider]
    values={key:params.get(key,default) for key,default in spec['defaults'].items()}
    # Old empty generic ratio/resolution fields used the previous canvas fallbacks.
    values['ratio']=values['ratio'] or '1:1'
    values['resolution']=values['resolution'] or '1K'
    if values['ratio'] not in spec['ratios'] or (values['ratio']!='custom' and values['resolution'] not in spec['resolutions']):
        raise store.CanvasError('已保存图像画幅或分辨率不适用于当前接口')
    if values['output_format'] not in spec['formats'] or values['background'] not in spec['backgrounds']:
        raise store.CanvasError('已保存图像格式或背景不适用于当前接口')
    if values['ratio']=='custom':
        width,height=params.get('custom_width'),params.get('custom_height')
        try: app.resolve_seedream_pro_size('custom',values['resolution'],width,height)
        except ValueError as error: raise store.CanvasError(str(error)) from error
        values.update(custom_width=width,custom_height=height)
        values.pop('resolution')
    return values


def _boolean(data,key,default):
    value=data.get(key,default)
    if type(value) is bool: return value
    if isinstance(value,str) and value.lower() in ('true','false'): return value.lower()=='true'
    raise store.CanvasError('图像开关参数必须为布尔值')


def validate_submission(data, provider, effective_model):
    if not data.get('canvas_node_id'):
        return
    saved=store.workflow(data['canvas_workflow_id'])
    # Recheck revision here as well as the early provider guard.
    if str(data.get('canvas_workflow_revision'))!=str(saved['revision']):
        raise store.CanvasError('画布已改变，请保存或刷新后重新生成',409)
    node=next((n for n in saved['document']['nodes'] if n['id']==data['canvas_node_id']),None)
    if not node or node['type']!='image': raise store.CanvasError('图像节点不存在',404)
    params=node.get('params',{})
    expected=normalized_saved(params,provider)
    actual={
        'ratio':str(data.get('aspect_ratio','1:1')).strip().lower(),
        'resolution':str(data.get('resolution','1K')).upper(),
        'output_format':str(data.get('output_format','png')).lower(),
        'background':str(data.get('background','default')).lower(),
        'watermark':_boolean(data,'watermark',False)}
    if expected['ratio']=='custom':
        actual.pop('resolution')
        for key in ('custom_width','custom_height'):
            value=data.get(key)
            if isinstance(value,str) and value.isdecimal(): value=int(value)
            if type(value) is not int: raise store.CanvasError('自定义宽高必须为整数')
            actual[key]=value
    if data.get('model') not in (None,'',effective_model):
        raise store.CanvasError('模型与当前接口配置不匹配，请刷新配置',409)
    if provider=='ark' and seedream55_capabilities.enabled(effective_model):
        for values in (actual,expected):
            if values['background']=='default': values['background']='auto'
    if actual!=expected:
        raise store.CanvasError('图像参数与已保存节点不一致，请保存或刷新后重新生成',409)


@lru_cache(maxsize=128)
def _metadata(path, mtime_ns, ctime_ns, size):
    with Image.open(path) as picture:
        return {'width':int(picture.width),'height':int(picture.height),'pixels':int(picture.width*picture.height),
                'has_alpha':bool(storage.image_has_alpha(picture))}


def register_routes(bp):
    from flask import jsonify
    @bp.get('/api/canvas/image-capabilities')
    def image_capabilities():
        return jsonify(success=True,providers=capabilities())

    @bp.get('/api/canvas/workflows/<workflow_id>/assets/<asset_id>/metadata')
    def asset_metadata(workflow_id,asset_id):
        row=store.get_asset(workflow_id,asset_id)
        if row['kind']!='image': raise store.CanvasError('只能读取图像素材元数据')
        path=store.asset_path(row)
        try:
            stat=path.stat()
            data=_metadata(str(path),stat.st_mtime_ns,stat.st_ctime_ns,stat.st_size)
        except (OSError,ValueError,Image.DecompressionBombError) as error:
            raise store.CanvasError('图像元数据不可读取',409) from error
        return jsonify(success=True,metadata={**data,'mime_type':row['mime_type']})
