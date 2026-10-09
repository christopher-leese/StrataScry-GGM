# SPDX-License-Identifier: Apache-2.0
"""Plain Python document, validated records and a bounded chronological delta history."""
from dataclasses import dataclass, field, replace, asdict
from collections import defaultdict
import copy
import json
import math
import uuid
from .geometry import coordinate, length, EARTH_RADIUS_M


def uid(): return str(uuid.uuid4())


@dataclass
class Layer:
    id: str
    name: str
    visible: bool = True
    color: str = '#62cde5'
    node_next: int = 0
    edge_next: int = 0


@dataclass
class Node:
    id: str
    layer: str
    lon: float
    lat: float
    seq: int
    name: str = ''
    kind: str = 'generic'
    attributes: dict = field(default_factory=dict)
    template: str | None = None


@dataclass
class Waypoint:
    id: str
    lon: float
    lat: float


@dataclass
class Edge:
    id: str
    layer: str
    source: str
    target: str
    seq: int
    name: str = ''
    directed: bool = False
    waypoints: list = field(default_factory=list)
    attributes: dict = field(default_factory=dict)
    weight_mode: str = 'unassigned'
    weight_value: float = 0.0
    weight_scale: float = 1.0
    weight_unit: str = 'm'


@dataclass
class Change:
    label: str
    before: dict
    after: dict
    size: int
    start_token: str
    end_token: str


class Document:
    FORMAT = 'stratascry-graph'
    VERSION = 1
    MAX_OBJECTS = 200_000
    MAX_WAYPOINTS = 1024
    HISTORY_BYTES = 32 * 1024**2
    HISTORY_COUNT = 200

    def __init__(self, empty=False):
        self.id = uid()
        self.layers, self.nodes, self.edges = {}, {}, {}
        self.settings = {'order': [], 'pins': [], 'dim': 0.0, 'declutter': True, 'definitions': {}}
        self.radius_m = EARTH_RADIUS_M
        self.adjacency = defaultdict(set)
        self.degree = {}
        self.history = []
        self.cursor = 0
        self.token = uid()
        self.saved_token = self.token
        self.saved_counters = {}
        self.revision = 0
        self.changed_nodes, self.changed_edges = set(), set()
        self.history_trimmed = False
        if not empty:
            layer = Layer(uid(), 'Network')
            self.layers[layer.id] = layer
            self.settings['order'] = [layer.id]
        self.saved_counters = self.counters()

    @property
    def dirty(self): return self.token != self.saved_token or self.counters() != self.saved_counters
    def counters(self): return {k:(l.node_next,l.edge_next) for k,l in self.layers.items()}
    def mark_saved(self):
        self.saved_token = self.token
        self.saved_counters = self.counters()
    def label(self, obj):
        return obj.name or f'{self.layers[obj.layer].name}-{"node" if isinstance(obj, Node) else "edge"} {obj.seq}'
    def route(self, edge):
        a,b = self.nodes[edge.source], self.nodes[edge.target]
        return [(a.lon,a.lat), *[(p.lon,p.lat) for p in edge.waypoints], (b.lon,b.lat)]
    def edge_length(self, edge): return length(self.route(edge), self.radius_m)
    def weight(self, edge):
        if edge.weight_mode == 'unassigned': return None
        value = edge.weight_value if edge.weight_mode == 'manual' else edge.weight_scale*self.edge_length(edge)
        if not math.isfinite(value): raise ValueError('Derived weight exceeds finite numeric range')
        return value

    def _index(self, changed_nodes, changed_edges, old_edges):
        affected = set(changed_nodes)
        for e in old_edges:
            if e:
                for node in (e.source,e.target):
                    self.adjacency[node].discard(e.id)
                    affected.add(node)
        for key in changed_edges:
            e = self.edges.get(key)
            if e:
                for node in (e.source,e.target):
                    self.adjacency[node].add(e.id)
                    affected.add(node)
        for key in affected:
            if key not in self.nodes:
                self.adjacency.pop(key,None)
                self.degree.pop(key,None)
            else:
                neighbors = set()
                for eid in self.adjacency[key]:
                    e = self.edges[eid]
                    neighbors.add(e.target if e.source == key else e.source)
                self.degree[key] = len(neighbors)

    def _apply(self, delta):
        changed_nodes = set(delta.get('nodes',{}))
        changed_edges = set(delta.get('edges',{}))
        old_edges = [self.edges.get(key) for key in changed_edges]
        for collection, updates in delta.items():
            target = getattr(self,collection)
            for key,value in updates.items():
                if value is None: target.pop(key,None)
                else: target[key] = copy.deepcopy(value)
        self._index(changed_nodes, changed_edges, old_edges)
        self.changed_nodes = changed_nodes
        self.changed_edges = changed_edges | {eid for n in changed_nodes for eid in self.adjacency.get(n,())}
        self.revision += 1

    def commit(self, label, delta):
        before = {coll: {key:copy.deepcopy(getattr(self,coll).get(key)) for key in updates} for coll,updates in delta.items()}
        if before == delta: return False
        # Controller routes all editing through validated operations below.
        size = len(repr(before).encode()) + len(repr(delta).encode())
        if size > self.HISTORY_BYTES:
            raise ValueError('This edit exceeds the 32 MiB undo budget; split it into smaller edits')
        change = Change(label, before, copy.deepcopy(delta), size, self.token, uid())
        self._apply(change.after)
        del self.history[self.cursor:]
        self.history.append(change)
        self.cursor += 1
        self.token = change.end_token
        while len(self.history)>self.HISTORY_COUNT or sum(c.size for c in self.history)>self.HISTORY_BYTES:
            self.history.pop(0)
            self.cursor -= 1
            self.history_trimmed = True
        return True

    def undo(self):
        if not self.cursor: return False
        self.cursor -= 1
        c = self.history[self.cursor]
        # Allocation high-water marks never go backwards, including branch edits.
        counters = {k:(v.node_next,v.edge_next) for k,v in self.layers.items()}
        self._apply(c.before)
        for k,(n,e) in counters.items():
            if k in self.layers:
                self.layers[k].node_next=max(n,self.layers[k].node_next)
                self.layers[k].edge_next=max(e,self.layers[k].edge_next)
        self.token = c.start_token
        return True

    def redo(self):
        if self.cursor == len(self.history): return False
        c = self.history[self.cursor]
        counters = {k:(v.node_next,v.edge_next) for k,v in self.layers.items()}
        self._apply(c.after)
        for k,(n,e) in counters.items():
            if k in self.layers:
                self.layers[k].node_next=max(n,self.layers[k].node_next)
                self.layers[k].edge_next=max(e,self.layers[k].edge_next)
        self.cursor += 1
        self.token = c.end_token
        return True

    def new_layer(self, name):
        name = name.strip()
        if not name or any(l.name==name for l in self.layers.values()): raise ValueError('Choose a unique, nonempty layer name')
        l = Layer(uid(),name)
        self.commit('Add layer '+name, {'layers':{l.id:l}, 'settings':{'order':[l.id,*self.settings['order']]}})
        return l.id

    def update_layer(self, key, **values):
        old = self.layers[key]
        if 'name' in values:
            values['name'] = values['name'].strip()
            if not values['name'] or any(k!=key and l.name==values['name'] for k,l in self.layers.items()):
                raise ValueError('Choose a unique, nonempty layer name')
        self.commit('Edit layer '+old.name, {'layers':{key:replace(old,**values)}})

    def delete_layer(self,key):
        nodes = {k:None for k,v in self.nodes.items() if v.layer==key}
        edges = {k:None for k,v in self.edges.items() if v.layer==key}
        self.commit('Delete layer '+self.layers[key].name, {'layers':{key:None}, 'nodes':nodes,'edges':edges,
            'settings':{'order':[k for k in self.settings['order'] if k!=key],
                        'pins':[k for k in self.settings['pins'] if k not in nodes and k not in edges]}})

    def add_node(self, layer, lon, lat, **values):
        if len(self.nodes)+len(self.edges)>=self.MAX_OBJECTS: raise ValueError('Project capacity reached')
        lon,lat = coordinate(lon,lat)
        l = self.layers[layer]
        node = Node(uid(),layer,lon,lat,l.node_next,**values)
        self.commit('Add node · '+l.name, {'nodes':{node.id:node},'layers':{layer:replace(l,node_next=l.node_next+1)}})
        return node.id

    def validate_edge(self, e, nodes=None):
        nodes = self.nodes if nodes is None else nodes
        if e.source == e.target: raise ValueError('Self-loop editing is not supported yet')
        if e.source not in nodes or e.target not in nodes: raise ValueError('Edge endpoint is missing')
        if nodes[e.source].layer!=e.layer or nodes[e.target].layer!=e.layer: raise ValueError('Both endpoints must belong to the edge layer')
        if len(e.waypoints)>self.MAX_WAYPOINTS: raise ValueError('At most 1024 shape waypoints per edge')
        if len({p.id for p in e.waypoints})!=len(e.waypoints): raise ValueError('Duplicate waypoint IDs')
        for p in e.waypoints: coordinate(p.lon,p.lat)
        a,b = nodes[e.source],nodes[e.target]
        distance = length([(a.lon,a.lat),*[(p.lon,p.lat) for p in e.waypoints],(b.lon,b.lat)],self.radius_m)
        if e.weight_mode not in ('unassigned','manual','length'): raise ValueError('Unknown weight source')
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in (e.weight_value,e.weight_scale)):
            raise ValueError('Weight inputs must be finite numbers')
        if e.weight_mode=='length' and not math.isfinite(distance*e.weight_scale): raise ValueError('Derived weight exceeds finite numeric range')

    def add_edge(self, source, target, waypoints=(), directed=False):
        if len(self.nodes)+len(self.edges)>=self.MAX_OBJECTS: raise ValueError('Project capacity reached')
        layer = self.nodes[source].layer
        l = self.layers[layer]
        e = Edge(uid(),layer,source,target,l.edge_next,directed=directed,
                 waypoints=[Waypoint(uid(),*coordinate(*p)) for p in waypoints])
        self.validate_edge(e)
        self.commit('Add edge · '+l.name, {'edges':{e.id:e},'layers':{layer:replace(l,edge_next=l.edge_next+1)}})
        return e.id

    def update_node(self, key, **values):
        old = self.nodes[key]
        obj = replace(old,**values)
        obj.lon,obj.lat=coordinate(obj.lon,obj.lat)
        if 'name' in values: obj.name=obj.name.strip()
        overlay = dict(self.nodes)
        overlay[key]=obj
        for eid in self.adjacency[key]: self.validate_edge(self.edges[eid],overlay)
        self.check_attributes(obj.attributes)
        self.commit('Edit '+self.label(old), {'nodes':{key:obj}})

    def update_edge(self,key,**values):
        old = self.edges[key]
        obj = replace(old,**values)
        if 'name' in values: obj.name=obj.name.strip()
        self.validate_edge(obj)
        self.check_attributes(obj.attributes)
        self.commit('Edit '+self.label(old),{'edges':{key:obj}})

    def delete_object(self,key):
        if key in self.nodes:
            edges = {eid:None for eid in self.adjacency[key]}
            nodes = {key:None}
        else: nodes,edges = {},{key:None}
        obj = self.nodes.get(key) or self.edges[key]
        self.commit('Delete '+self.label(obj), {'nodes':nodes,'edges':edges,
            'settings':{'pins':[k for k in self.settings['pins'] if k not in nodes and k not in edges]}})

    def setting(self,key,value,label):
        if key=='order' and (len(value)!=len(self.layers) or set(value)!=set(self.layers)): raise ValueError('Invalid layer order')
        self.commit(label, {'settings':{key:value}})

    @staticmethod
    def check_attributes(values):
        if not isinstance(values,dict) or len(values)>256: raise ValueError('Attributes must be an object with at most 256 fields')
        for key,value in values.items():
            if not isinstance(key,str) or not key.strip() or len(key)>128: raise ValueError('Attribute keys must be nonempty text, at most 128 characters')
            good = isinstance(value,(str,bool)) or (type(value) in (int,float) and math.isfinite(value)) or (isinstance(value,list) and len(value)<=1024 and all(isinstance(v,str) for v in value))
            if not good: raise ValueError('Attributes support text, finite numbers, booleans and string lists')
        if len(json.dumps(values))>65536: raise ValueError('Attributes exceed 64 KiB per object')

    def to_dict(self):
        return {'format':self.FORMAT,'version':self.VERSION,'id':self.id,'distance':{'kind':'sphere','radius_m':self.radius_m},
                'layers':[asdict(self.layers[k]) for k in sorted(self.layers)], 'nodes':[asdict(self.nodes[k]) for k in sorted(self.nodes)],
                'edges':[asdict(self.edges[k]) for k in sorted(self.edges)], 'display':copy.deepcopy(self.settings)}

    @classmethod
    def from_dict(cls,data):
        if not isinstance(data,dict) or set(data)!={'format','version','id','distance','layers','nodes','edges','display'}:
            raise ValueError('Invalid project fields')
        if data['format']!=cls.FORMAT or type(data['version']) is not int or data['version']!=cls.VERSION: raise ValueError('Unsupported project format/version')
        d = cls(empty=True)
        d.id = data['id']
        if not isinstance(d.id,str) or not d.id: raise ValueError('Invalid document ID')
        meta=data['distance']
        if not isinstance(meta,dict) or set(meta)!={'kind','radius_m'} or meta['kind']!='sphere' or meta['radius_m']!=EARTH_RADIUS_M:
            raise ValueError('Unsupported spherical distance convention')
        if any(not isinstance(data[k],list) for k in ('layers','nodes','edges')): raise ValueError('Object collections must be lists')
        if len(data['nodes'])+len(data['edges'])>cls.MAX_OBJECTS or len(data['layers'])>10000: raise ValueError('Project exceeds prototype capacity')
        seen=set()
        for coll,kind in (('layers',Layer),('nodes',Node),('edges',Edge)):
            for record in data[coll]:
                if not isinstance(record,dict): raise ValueError('Invalid object record')
                record=dict(record)
                if coll=='edges': record['waypoints']=[Waypoint(**v) for v in record.get('waypoints',[])]
                obj=kind(**record)
                if not isinstance(obj.id,str) or not obj.id or obj.id in seen: raise ValueError('Missing/duplicate object ID')
                seen.add(obj.id)
                getattr(d,coll)[obj.id]=obj
        if any(not isinstance(l.name,str) or not l.name.strip() for l in d.layers.values()) or len({l.name for l in d.layers.values()})!=len(d.layers): raise ValueError('Layer names must be unique and nonempty')
        for l in d.layers.values():
            if type(l.visible) is not bool or any(type(v) is not int or v<0 for v in (l.node_next,l.edge_next)): raise ValueError('Invalid layer flags/counters')
            if not isinstance(l.color,str) or len(l.color)!=7 or l.color[0]!='#' or any(c not in '0123456789abcdefABCDEF' for c in l.color[1:]): raise ValueError('Invalid layer color')
        sequences=set()
        for coll in ('nodes','edges'):
            for obj in getattr(d,coll).values():
                if obj.layer not in d.layers or type(obj.seq) is not int or obj.seq<0 or not isinstance(obj.name,str): raise ValueError('Invalid layer/name/sequence')
                seq=(coll,obj.layer,obj.seq)
                if seq in sequences: raise ValueError('Duplicate allocated sequence')
                sequences.add(seq)
                counter=d.layers[obj.layer].node_next if coll=='nodes' else d.layers[obj.layer].edge_next
                if counter<=obj.seq: raise ValueError('Allocation counter would reuse a name')
                d.check_attributes(obj.attributes)
                if coll=='nodes':
                    obj.lon,obj.lat=coordinate(obj.lon,obj.lat)
                    if not isinstance(obj.kind,str) or (obj.template is not None and not isinstance(obj.template,str)): raise ValueError('Invalid node kind/template')
                else:
                    if type(obj.directed) is not bool or not isinstance(obj.weight_unit,str): raise ValueError('Invalid edge direction/units')
                    d.validate_edge(obj)
        settings=data['display']
        if not isinstance(settings,dict) or set(settings)!=set(d.settings): raise ValueError('Unsupported display fields')
        order=settings['order']
        if not isinstance(order,list) or len(order)!=len(d.layers) or set(order)!=set(d.layers): raise ValueError('Invalid layer stack order')
        pins=settings['pins']
        if not isinstance(pins,list) or len(pins)!=len(set(pins)) or any(k not in d.nodes and k not in d.edges for k in pins): raise ValueError('Invalid pins')
        if type(settings['dim']) not in (int,float) or not 0<=settings['dim']<=0.8 or type(settings['declutter']) is not bool: raise ValueError('Invalid display settings')
        definitions=settings['definitions']
        if not isinstance(definitions,dict) or len(definitions)>256: raise ValueError('Invalid attribute definitions')
        for key,v in definitions.items():
            if not isinstance(key,str) or not isinstance(v,dict) or set(v)!={'type','label','unit','description'} or v['type'] not in ('text','number','boolean','list') or any(not isinstance(v[k],str) for k in ('label','unit','description')): raise ValueError('Invalid attribute definition')
        d.settings=copy.deepcopy(settings)
        for obj in [*d.nodes.values(),*d.edges.values()]:
            for key,value in obj.attributes.items():
                if key in definitions:
                    kind='boolean' if isinstance(value,bool) else 'text' if isinstance(value,str) else 'list' if isinstance(value,list) else 'number'
                    if definitions[key]['type']!=kind: raise ValueError('Attribute conflicts with definition: '+key)
        d._index(set(d.nodes),set(d.edges),[])
        d.mark_saved()
        return d
