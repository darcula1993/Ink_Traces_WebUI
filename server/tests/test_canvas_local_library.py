import io
import wave
import canvas_store as store
import canvas_library_folders as folders
import tasks
from test_canvas_catalog import setup,upload,listing,task_outputs
from test_canvas_library_folders import image_bytes


def test_local_union_default_dedup_and_legacy_sources():
    client,p,w=setup()
    unknown=store.save_asset(p,io.BytesIO(image_bytes('green')),'legacy.png',library=True)
    uploaded=upload(client,p)
    direct=upload(client,w,'blue',workflow=True)
    result=client.post(f'/api/canvas/projects/{p}/library-items/save',json={'items':[{'source':'library','id':uploaded['id']}]})
    assert result.status_code==201
    task_outputs(w,count=1)
    response=client.get('/api/canvas/library/items',query_string={'project_id':p}).json
    assert response['total']==response['counts']['local']==3
    assert response['counts']['saved']==2 and response['counts']['uploaded']==2
    assert response['counts']['generated']==1
    assert len({i['key'] for i in response['items']})==3
    assert next(i for i in response['items'] if i['asset']['id']==unknown['id'])['origin_unknown']
    dual=next(i for i in response['items'] if i['asset']['id']==uploaded['id'])
    assert dual['origins']==['saved','uploaded']
    assert listing(client,p,'saved')['total']==2
    assert listing(client,p,'uploaded')['total']==2
    assert listing(client,p,'local')['items']==response['items']
    first=listing(client,p,'local',limit=2)
    second=listing(client,p,'local',limit=2,offset=2)
    assert first['total']==second['total']==3
    assert {i['key'] for i in first['items']}.isdisjoint({i['key'] for i in second['items']})


def test_local_filters_counts_scope_and_hidden_identity():
    client,p,w=setup(); a=upload(client,p)
    direct=upload(client,w,'blue',workflow=True)
    folder=folders.list_folders(p)[0]
    folders.edit_asset(p,a['id'],{'folder_id':folder['id'],'name':'target needle.png'})
    sound=io.BytesIO()
    with wave.open(sound,'wb') as handle:
        handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(8000); handle.writeframes(b'\0\0'*800)
    sound.seek(0)
    audio=client.post(f'/api/canvas/projects/{p}/assets',data={'file':(sound,'voice.wav')})
    assert audio.status_code==201
    tag=client.post('/api/canvas/library/tags',json={'title':'chosen'}).json['tag']
    client.patch('/api/canvas/library/items/library:'+a['id']+'/tags',json={'tag_ids':[tag['id']]})
    assert listing(client,p,'local',q='needle',tag_id=tag['id'],folder_id=folder['id'])['total']==1
    root=listing(client,p,'local',folder_id='')
    assert root['total']==2
    images=listing(client,p,'local',kind='image')
    assert images['total']==images['counts']['local']==2
    assert images['kind_counts']=={'image':2,'video':0,'audio':1}
    other=store.create_project('other')['id']; upload(client,other)
    assert listing(client,p,'local')['total']==3
    assert listing(client,p,'local',scope='all')['total']==4
    client.delete('/api/canvas/library/items/library:'+a['id'])
    assert listing(client,p,'local')['total']==2
    assert listing(client,other,'local')['total']==1
    assert client.get(a['url']).status_code==404
