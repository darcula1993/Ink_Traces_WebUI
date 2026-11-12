import copy
import pytest
import app as application
import canvas_store as store


def setup():
    project = store.create_project('groups')
    wf = store.create_workflow(project['id'], 'groups')
    document = copy.deepcopy(wf['document'])
    document['nodes'] = [{'id':n,'type':'image','x':i*100,'y':0,'params':{}} for i,n in enumerate(('a','b'))]
    document['edges'] = [{'id':'edge','source':'a','target':'b'}]
    return wf, document


@pytest.mark.parametrize('groups', [None, [], [{'id':'g','title':'组','nodeIds':['b','a']}], [{'id':'a','title':'A','nodeIds':['a']},{'id':'b','title':'B','nodeIds':['b']}]])
def test_groups_round_trip_and_ungroup_preserves_document(groups):
    wf, document = setup()
    if groups is not None:
        document['groups'] = groups
    original = copy.deepcopy(document)
    client = application.app.test_client()
    url = '/api/canvas/workflows/'+wf['id']
    assert client.put(url,json={'title':'groups','revision':1,'document':document}).status_code == 200
    assert client.get(url).json['workflow']['document'] == original
    document['groups'] = []
    assert client.put(url,json={'title':'groups','revision':2,'document':document}).status_code == 200
    assert client.get(url).json['workflow']['document'] == document


@pytest.mark.parametrize('groups', [None, {}, [None], [{'id':'g','title':'x','nodeIds':[]}],
    [{'id':'bad/id','title':'x','nodeIds':['a']}], [{'id':'g','title':' ','nodeIds':['a']}],
    [{'id':'g','title':'x'*101,'nodeIds':['a']}], [{'id':'g','title':1,'nodeIds':['a']}],
    [{'id':'g','title':'x','nodeIds':['a','a']}], [{'id':'g','title':'x','nodeIds':['missing']}],
    [{'id':'g','title':'x','nodeIds':[{}]}], [{'id':'g','title':'x','nodeIds':'a'}],
    [{'id':'g','title':'x','nodeIds':['a'],'extra':1}],
    [{'id':'g','title':'x','nodeIds':['a']},{'id':'g','title':'y','nodeIds':['b']}],
    [{'id':'g','title':'x','nodeIds':['a']},{'id':'h','title':'y','nodeIds':['a']}],
    [{'id':str(i),'title':'x','nodeIds':['a']} for i in range(501)],
])
def test_invalid_groups_rejected_without_revision_change(groups):
    wf, document = setup()
    document['groups'] = groups
    with pytest.raises(store.CanvasError):
        store.update_workflow(wf['id'],'groups',document,1)
    assert store.workflow(wf['id']) == wf


def test_delete_node_must_remove_group_membership():
    wf, document = setup()
    document.update(groups=[{'id':'g','title':'group','nodeIds':['a','b']}])
    store.update_workflow(wf['id'],'groups',document,1)
    document['nodes'].pop()
    document['edges'] = []
    with pytest.raises(store.CanvasError):
        store.update_workflow(wf['id'],'groups',document,2)
    document['groups'][0]['nodeIds'] = ['a']
    store.update_workflow(wf['id'],'groups',document,2)
    assert store.workflow(wf['id'])['document'] == document


def test_maximum_node_group_capacity():
    wf, document = setup()
    document['nodes'] = [{'id':str(i),'type':'image','x':0,'y':0} for i in range(500)]
    document['edges'] = []
    document['groups'] = [{'id':str(i),'title':'x'*100,'nodeIds':[str(i)]} for i in range(500)]
    store.update_workflow(wf['id'],'groups',document,1)
    assert store.workflow(wf['id'])['document'] == document


@pytest.mark.parametrize('frames', [0,1,2])
def test_keyframe_group_roundtrip_and_switch_to_plain(frames):
    wf, document = setup()
    document['nodes'] = [{'id':'video','type':'video','x':0,'y':0,'params':{'video_mode':'keyframe'}}] + document['nodes'][:frames]
    document['edges'] = [{'id':'e'+n['id'],'source':n['id'],'target':'video'} for n in document['nodes'][1:]]
    document['groups'] = [{'id':'g','title':'首尾帧','nodeIds':[n['id'] for n in document['nodes']], 'keyframeNodeId':'video'}]
    store.update_workflow(wf['id'],'groups',document,1)
    assert store.workflow(wf['id'])['document'] == document
    document['nodes'][0]['params']['video_mode'] = 'reference'
    del document['groups'][0]['keyframeNodeId']
    store.update_workflow(wf['id'],'groups',document,2)
    assert store.workflow(wf['id'])['document'] == document


@pytest.mark.parametrize('case', ['missing','notmember','notvideo','wrongmode','null','object','multipleowner'])
def test_keyframe_group_invalid_owner(case):
    wf, document = setup()
    document['nodes'].append({'id':'video','type':'video','x':0,'y':0,'params':{'video_mode':'keyframe'}})
    group = {'id':'g','title':'keyframe','nodeIds':['a','video'],'keyframeNodeId':'video'}
    document['groups'] = [group]
    if case == 'missing': group['keyframeNodeId'] = 'absent'
    if case == 'notmember': group['nodeIds'] = ['a']
    if case == 'notvideo': group['keyframeNodeId'] = 'a'
    if case == 'wrongmode': document['nodes'][-1]['params']['video_mode'] = 'reference'
    if case == 'null': group['keyframeNodeId'] = None
    if case == 'object': group['keyframeNodeId'] = {}
    if case == 'multipleowner': document['groups'].append({'id':'other','title':'other','nodeIds':['video'],'keyframeNodeId':'video'})
    with pytest.raises(store.CanvasError):
        store.update_workflow(wf['id'],'groups',document,1)


@pytest.mark.parametrize('color', ['green','cyan','blue','purple','amber','rose'])
def test_group_color_round_trip(color):
    wf, document = setup()
    document['groups'] = [{'id':'g','title':'colored','nodeIds':['a','b'],'color':color}]
    client = application.app.test_client()
    url = '/api/canvas/workflows/'+wf['id']
    assert client.put(url,json={'title':'groups','revision':1,'document':document}).status_code == 200
    assert client.get(url).json['workflow']['document'] == document


@pytest.mark.parametrize('color', [None, True, 1, [], {}, '', 'GREEN', '#00ff00', 'rgba(0,255,0,0.2)', 'red'])
def test_invalid_group_color_rejected(color):
    wf, document = setup()
    document['groups'] = [{'id':'g','title':'colored','nodeIds':['a'],'color':color}]
    with pytest.raises(store.CanvasError, match='颜色'):
        store.update_workflow(wf['id'],'groups',document,1)
    assert store.workflow(wf['id']) == wf
