import copy
import math
from dataclasses import replace
import numpy as np
import pytest
from stratascry.graph.model import Document, Waypoint, uid
from stratascry.graph.geometry import Projection, unit, length, coordinate, EARTH_RADIUS_M
from stratascry.geometry import GlobeCamera
from stratascry.graph import persistence


def scene():
    d=Document(); l=next(iter(d.layers)); a=d.add_node(l,-90,25); b=d.add_node(l,-89,25)
    e=d.add_edge(a,b)
    return d,l,a,b,e


def test_names_counter_branch_undo_and_rename():
    d,l,a,b,e=scene()
    assert d.label(d.nodes[a])=='Network-node 0'
    d.update_node(a,name='FOB')
    d.update_layer(l,name='Roads')
    assert d.label(d.nodes[a])=='FOB'
    assert d.label(d.nodes[b])=='Roads-node 1'
    c=d.add_node(l,0,0); d.undo()
    new=d.add_node(l,1,1)
    assert d.nodes[new].seq>d.layers[l].node_next-2
    assert d.nodes[new].seq>2
    assert c not in d.nodes
    assert d.cursor==len(d.history)


def test_topology_geometry_and_weight_independence():
    d,l,a,b,e=scene()
    other=d.add_edge(a,b,[(0,20)])
    assert d.degree[a]==1
    d.update_edge(e,weight_mode='manual',weight_value=7)
    d.update_edge(other,weight_mode='length',weight_scale=.001,weight_unit='km')
    first=d.edge_length(d.edges[e]); old=d.weight(d.edges[other])
    d.update_node(b,lon=-88)
    assert d.edge_length(d.edges[e])!=first
    assert d.weight(d.edges[e])==7
    assert d.weight(d.edges[other])!=old
    d.undo()
    assert d.edge_length(d.edges[e])==pytest.approx(first)
    assert d.weight(d.edges[other])==pytest.approx(old)


def test_cycles_parallel_delete_undo():
    d,l,a,b,e=scene(); c=d.add_node(l,-88,26)
    d.add_edge(b,c); d.add_edge(c,a); d.add_edge(a,b)
    before=d.to_dict()
    d.delete_object(a)
    assert a not in d.nodes and len(d.edges)==1
    d.undo(); assert d.to_dict()==before
    d.delete_layer(l); assert not d.layers and not d.nodes and not d.edges
    d.undo(); assert d.to_dict()==before
    d.redo(); assert not d.layers


def test_display_and_graph_share_history():
    d,l,a,b,e=scene(); d.mark_saved()
    d.update_node(a,lon=-91)
    d.update_layer(l,visible=False)
    assert d.dirty
    d.undo(); assert d.layers[l].visible and d.nodes[a].lon==-91
    d.undo(); assert d.nodes[a].lon==-90 and not d.dirty
    d.redo(); assert d.dirty


def test_model_rejects_cross_layer_self_and_overflow():
    d,l,a,b,e=scene(); l2=d.new_layer('Other'); c=d.add_node(l2,0,0)
    for x,y in ((a,a),(a,c)):
        with pytest.raises(ValueError): d.add_edge(x,y)
    with pytest.raises(ValueError): d.update_edge(e,weight_mode='length',weight_scale=1e308)
    with pytest.raises(ValueError): d.update_edge(e,attributes={'bad':float('nan')})
    assert d.edges[e].weight_mode=='unassigned'


def test_persistence_round_trip_and_atomic_failure(tmp_path,monkeypatch):
    d,l,a,b,e=scene(); p=tmp_path/'project.ssg.json'
    persistence.save(d,p); assert not d.dirty
    loaded=persistence.load(p); assert loaded.to_dict()==d.to_dict()
    old=p.read_bytes(); d.update_node(a,lon=-91)
    def fail(*args): raise OSError('simulated replacement failure')
    monkeypatch.setattr(persistence.os,'replace',fail)
    with pytest.raises(OSError): persistence.save(d,p)
    assert p.read_bytes()==old and d.dirty
    assert list(tmp_path.iterdir())==[p]


@pytest.mark.parametrize('fault',['reference','duplicate','version','counter','order','nonfinite','unknown'])
def test_invalid_documents(fault):
    d,l,a,b,e=scene(); data=d.to_dict()
    if fault=='reference': data['edges'][0]['target']='missing'
    if fault=='duplicate': data['nodes'][1]['id']=data['nodes'][0]['id']
    if fault=='version': data['version']=99
    if fault=='counter': data['layers'][0]['node_next']=0
    if fault=='order': data['display']['order']=[]
    if fault=='nonfinite': data['nodes'][0]['lon']=float('nan')
    if fault=='unknown': data['future']=True
    with pytest.raises((ValueError,TypeError)): Document.from_dict(data)


def test_length_dateline_and_antipodal():
    assert length([(179,0),(-179,0)])==pytest.approx(math.radians(2)*EARTH_RADIUS_M)
    assert length([(0,0),(0,0)])==0
    with pytest.raises(ValueError): length([(0,0),(180,0)])
    assert coordinate(180,90)==(-180,90)
    with pytest.raises(ValueError): coordinate(540,0)


@pytest.mark.parametrize('lon,lat,distance',[(-90,25,3),(179,0,1.01),(0,89,1.001),(0,0,1.0002)])
def test_projection_round_trip(lon,lat,distance):
    nav=GlobeCamera(lon,lat,distance)
    for width,height in ((1180,690),(590,345),(2360,1380)):
        pr=Projection(nav,width,height)
        for x,y in ((width/2,height/2),(width*.45,height*.55),(width*.55,height*.45)):
            coords=pr.pick(x,y)
            assert coords is not None
            screen=pr.project(unit([coords]))[0]
            assert np.linalg.norm(screen-[x,y])<1
    assert Projection(GlobeCamera(0,0,4),1000,1000).pick(0,0) is None


def test_horizon_middle_visible_with_both_endpoints_hidden():
    pr=Projection(GlobeCamera(0,0,1.01),1000,1000)
    p=unit([(-10,0),(10,0)])
    assert not pr.visible(p).any()
    segments=pr.clipped_segments(p)
    assert len(segments)==1
    assert segments[0,0,0]<500<segments[0,1,0]
