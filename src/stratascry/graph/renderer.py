# SPDX-License-Identifier: Apache-2.0
"""Batched Qt overlay; analytical sphere clipping and a logical-pixel hit index.

One transparent widget, a small path set per layer, no per-object actors/widgets.
The overlay provides explicit layer order without changing geographic anchors.
"""
from collections import OrderedDict, defaultdict
import math
import time
import numpy as np
from PySide6.QtCore import Qt, QPointF, QRectF, QTimer, QLineF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget
from .geometry import Projection, unit, tessellate

NODE_BUDGET=1200
EDGE_BUDGET=1200
VERTEX_BUDGET=120_000
GEOMETRY_BYTES=32*1024**2
CELL=48


def clip_viewport(segments,width,height):
    """Vector Liang–Barsky clipping, preserving owner indices."""
    if not len(segments): return segments, np.empty(0,dtype=int)
    a,b=segments[:,0],segments[:,1]
    delta=b-a
    lo=np.zeros(len(a)); hi=np.ones(len(a)); ok=np.ones(len(a),dtype=bool)
    for axis,lower,upper in ((0,-10,width+10),(1,-10,height+10)):
        d=delta[:,axis]
        parallel=np.abs(d)<1e-12
        ok &= ~parallel | ((a[:,axis]>=lower)&(a[:,axis]<=upper))
        safe=np.where(parallel,1,d)
        t1=(lower-a[:,axis])/safe; t2=(upper-a[:,axis])/safe
        lo=np.maximum(lo,np.where(parallel,0,np.minimum(t1,t2)))
        hi=np.minimum(hi,np.where(parallel,1,np.maximum(t1,t2)))
    ok &= hi>=lo
    ids=np.flatnonzero(ok)
    return np.stack((a[ok]+lo[ok,None]*delta[ok],a[ok]+hi[ok,None]*delta[ok]),axis=1),ids


class GraphOverlay(QWidget):
    def __init__(self,controller):
        self.controller=controller
        super().__init__(controller.globe)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.cache=OrderedDict(); self.cache_bytes=0
        self.geometry_revision=-1
        self.detail_level=0
        self.node_ids=[]; self.node_points=np.empty((0,3))
        self.edge_ids=[]; self.edge_owner=np.empty(0,dtype=int)
        self.segment_a=np.empty((0,3)); self.segment_b=np.empty((0,3))
        self.layer_draw={}; self.grid=defaultdict(list); self.primitives=[]
        self.node_xy={}; self.surviving=set(); self.badges={}
        self.old_survivors=set(); self.capacity=False; self.stats={}; self.times=[]
        self.projection=Projection(controller.globe.navigation,controller.globe.width(),controller.globe.height())
        self.timer=QTimer(self); self.timer.setSingleShot(True); self.timer.timeout.connect(self.rebuild)
        self.setGeometry(controller.globe.rect())
        self.show(); self.raise_()

    def schedule(self):
        self.setGeometry(self.controller.globe.rect())
        if not self.timer.isActive(): self.timer.start(16)

    def invalidate(self,full=False):
        doc=self.controller.document
        keys=list(self.cache) if full else [key for key in self.cache if key[0] in doc.changed_edges]
        for key in keys:
            item=self.cache.pop(key,None)
            if item is not None: self.cache_bytes-=item.nbytes
        self.geometry_revision=-1
        self.schedule()

    def edge_points(self,e):
        key=(e.id,self.detail_level)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        p=tessellate(self.controller.document.route(e),step=math.radians(1)/(2**self.detail_level))
        while self.cache and self.cache_bytes+p.nbytes>GEOMETRY_BYTES:
            _,old=self.cache.popitem(last=False); self.cache_bytes-=old.nbytes
        if p.nbytes<=GEOMETRY_BYTES:
            self.cache[key]=p; self.cache_bytes+=p.nbytes
        return p

    def build_geometry(self):
        d=self.controller.document
        self.node_ids=list(d.nodes)
        self.node_points=unit([(v.lon,v.lat) for v in d.nodes.values()]) if d.nodes else np.empty((0,3))
        self.edge_ids=[]; a=[]; b=[]; owners=[]; count=0
        # Priority objects are included before ordinary model order at capacity.
        priority=set(d.settings['pins'])|({self.controller.selected} if self.controller.selected else set())
        edges=sorted(d.edges.values(),key=lambda e:(e.id not in priority,e.id))
        self.geometry_capacity=False
        for e in edges:
            if not d.layers[e.layer].visible: continue
            p=self.edge_points(e)
            if count+len(p)*2>VERTEX_BUDGET:
                self.geometry_capacity=True
                continue
            index=len(self.edge_ids); self.edge_ids.append(e.id)
            a.append(p[:-1]); b.append(p[1:]); owners.extend([index]*(len(p)-1))
            count+=len(p)*2
        self.segment_a=np.concatenate(a) if a else np.empty((0,3))
        self.segment_b=np.concatenate(b) if b else np.empty((0,3))
        self.edge_owner=np.asarray(owners,dtype=int)
        self.geometry_revision=d.revision

    def rebuild(self):
        start=time.perf_counter()
        c=self.controller; d=c.document
        if c.closing: return
        self.setGeometry(c.globe.rect())
        self.projection=Projection(c.globe.navigation,self.width(),self.height())
        step=math.sqrt(8*0.7*max(self.projection.distance-1.0001,1e-6)/self.projection.focal)
        level=max(0,min(6,math.ceil(math.log2(math.radians(1)/step))))
        if level!=self.detail_level:
            self.detail_level=level; self.geometry_revision=-1
        if self.geometry_revision!=d.revision: self.build_geometry()
        pr=self.projection
        xy=pr.project(self.node_points)
        visible=pr.visible(self.node_points)
        inside=visible & (xy[:,0]>=-12)&(xy[:,0]<=self.width()+12)&(xy[:,1]>=-12)&(xy[:,1]<=self.height()+12)
        self.node_xy={key:xy[i] for i,key in enumerate(self.node_ids) if visible[i]}
        candidates=[key for i,key in enumerate(self.node_ids) if inside[i] and d.layers[d.nodes[key].layer].visible]
        priority=set(d.settings['pins'])
        if c.selected:
            priority.add(c.selected)
            if c.selected in d.edges:
                e=d.edges[c.selected]; priority.update((e.source,e.target))
        if c.reveal and c.selected in d.nodes:
            for eid in d.adjacency[c.selected]:
                e=d.edges[eid]; priority.update((e.source,e.target,eid))
        # Deterministic degree ranking, with retained winners as a tie-breaker.
        queues={l:[] for l in d.settings['order'] if d.layers[l].visible}
        for key in candidates: queues[d.nodes[key].layer].append(key)
        for q in queues.values(): q.sort(key=lambda k:(k not in priority,-d.degree.get(k,0),k not in self.old_survivors,k))
        winners=[]; cells=defaultdict(list)
        def accept(key):
            p=self.node_xy[key]; cell=(int(p[0]//40),int(p[1]//40))
            if d.settings['declutter'] and key not in priority:
                if any(np.linalg.norm(p-self.node_xy[o])<24 for x in range(cell[0]-1,cell[0]+2) for y in range(cell[1]-1,cell[1]+2) for o in cells[(x,y)]): return
            if len(winners)>=NODE_BUDGET: return
            winners.append(key); cells[cell].append(key)
        for key in sorted(set(candidates)&priority): accept(key)
        priority_visible=set(winners)
        from itertools import zip_longest
        for row in zip_longest(*(q for q in queues.values()),fillvalue=None):
            for key in row:
                if key and key not in priority_visible: accept(key)
        self.surviving=set(winners)
        suppressed=set(candidates)-self.surviving
        self.old_survivors=self.surviving
        self.capacity=self.geometry_capacity or len(winners)>=NODE_BUDGET
        seg,idx=pr.clipped_pairs(self.segment_a,self.segment_b)
        owners=self.edge_owner[idx]
        seg,idx=clip_viewport(seg,self.width(),self.height()); owners=owners[idx]
        eligible={k for k in self.edge_ids if d.edges[k].source not in suppressed and d.edges[k].target not in suppressed}
        shown_edges=[]
        lengths=np.bincount(owners,weights=np.linalg.norm(seg[:,1]-seg[:,0],axis=1),minlength=len(self.edge_ids))
        ink_limit=self.width()*self.height()*0.12 if d.settings['declutter'] else float('inf')
        ink=0.0
        for index in sorted(set(owners),key=lambda i:(self.edge_ids[i] not in priority,self.edge_ids[i])):
            e=self.edge_ids[index]
            if e not in eligible: continue
            if len(shown_edges)>=EDGE_BUDGET:
                self.capacity=True
                continue
            if e not in priority and ink+lengths[index]>ink_limit: continue
            shown_edges.append(e); ink+=lengths[index]
        edge_set=set(shown_edges)
        self.badges={}
        for key in winners:
            hidden=sum(1 for e in d.adjacency[key] if d.edges[e].source in suppressed or d.edges[e].target in suppressed or (e in eligible and e not in edge_set))
            if hidden: self.badges[key]=hidden
        self.layer_draw={l:{'edges':[],'selected':[],'arrows':QPainterPath(),'nodes':[],'selected_nodes':[],'handles':[], 'labels':[]} for l in queues}
        self.primitives=[]; self.grid=defaultdict(list)
        drawn=(np.isin(owners,[i for i,k in enumerate(self.edge_ids) if k in edge_set]))
        seg,owners=seg[drawn],owners[drawn]
        self.edge_hit_segments=seg
        self.edge_hit_keys=[self.edge_ids[i] for i in owners]
        for endpoints,owner in zip(seg,owners):
            key=self.edge_ids[owner]
            if key not in edge_set: continue
            e=d.edges[key]; draw=self.layer_draw[e.layer]
            target=draw['selected'] if key==c.selected else draw['edges']
            a,b=endpoints
            target.append(QLineF(float(a[0]),float(a[1]),float(b[0]),float(b[1])))
            # Edge picking uses a vectorized segment test, not an expansive grid.

        # One directional marker on a visible segment per directed edge.
        arrow_done=set()
        for endpoints,owner in zip(seg,owners):
            key=self.edge_ids[owner]
            if key not in edge_set or key in arrow_done or not d.edges[key].directed: continue
            a,b=endpoints; v=b-a; n=np.linalg.norm(v)
            if n<16: continue
            arrow_done.add(key); v/=n; mid=(a+b)/2; side=np.array([-v[1],v[0]])
            path=self.layer_draw[d.edges[key].layer]['arrows']
            p=mid+v*4; q=mid-v*4+side*3; r=mid-v*4-side*3
            path.moveTo(*map(float,p)); path.lineTo(*map(float,q)); path.lineTo(*map(float,r)); path.closeSubpath()
        for key in winners:
            node=d.nodes[key]; p=self.node_xy[key]; draw=self.layer_draw[node.layer]
            target=draw['selected_nodes'] if key==c.selected else draw['nodes']
            rect=QRectF(float(p[0]-5),float(p[1]-5),10,10)
            target.append((rect,node.kind=='junction'))
            self.add_hit(node.layer,1,key,np.asarray([p,p]))
            if key==c.selected or key in self.badges:
                label=d.label(node) if key==c.selected else ''
                if key in self.badges: label+=f'  +{self.badges[key]} edges'
                draw['labels'].append((p,label if key==c.selected else f'+{self.badges[key]}'))
        if c.selected in d.edges and c.can_edit(c.selected):
            edge=d.edges[c.selected]
            if edge.layer in self.layer_draw:
                for w in edge.waypoints:
                    point=unit([(w.lon,w.lat)])
                    if pr.visible(point)[0]:
                        p=pr.project(point)[0]
                        self.layer_draw[edge.layer]['handles'].append(p)
                        self.add_hit(edge.layer,0,(edge.id,w.id),np.asarray([p,p]))
        self.stats={'nodes':len(winners),'edges':len(edge_set),'segments':len(seg),'cache_mib':self.cache_bytes/1024**2,'capacity':self.capacity}
        self.times.append((time.perf_counter()-start)*1000); self.times=self.times[-1000:]
        self.update(); c.update_status_only()

    def add_hit(self,layer,kind,key,endpoints):
        index=len(self.primitives); self.primitives.append((layer,kind,key,endpoints))
        lo=np.floor((np.minimum(*endpoints)-8)/CELL).astype(int)
        hi=np.floor((np.maximum(*endpoints)+8)/CELL).astype(int)
        for x in range(max(-1,lo[0]),min(self.width()//CELL+1,hi[0])+1):
            for y in range(max(-1,lo[1]),min(self.height()//CELL+1,hi[1])+1):
                self.grid[(x,y)].append(index)

    def hits(self,x,y):
        point=np.array([x,y]); candidates=[]; order=self.controller.document.settings['order']
        for i in self.grid.get((int(x//CELL),int(y//CELL)),()):
            layer,kind,key,(a,b)=self.primitives[i]
            v=b-a; denom=float(v@v)
            nearest=a if denom<1e-12 else a+np.clip(float((point-a)@v)/denom,0,1)*v
            distance=float(np.linalg.norm(point-nearest))
            if distance<=8: candidates.append((order.index(layer),kind,distance,str(key),key))
        segments=getattr(self,'edge_hit_segments',np.empty((0,2,2)))
        if len(segments):
            a,b=segments[:,0],segments[:,1]
            near=((np.minimum(a,b)-8<=point)&(np.maximum(a,b)+8>=point)).all(axis=1)
            ids=np.flatnonzero(near)
            a,b=a[near],b[near]; v=b-a
            denom=np.einsum('ij,ij->i',v,v)
            t=np.clip(np.einsum('ij,ij->i',point-a,v)/np.maximum(denom,1e-15),0,1)
            distances=np.linalg.norm(point-(a+t[:,None]*v),axis=1)
            for index,distance in zip(ids,distances):
                if distance<=8:
                    key=self.edge_hit_keys[index]; layer=self.controller.document.edges[key].layer
                    candidates.append((order.index(layer),2,float(distance),key,key))
        if not candidates: return []
        candidates.sort(); top=candidates[0][0]
        return list(dict.fromkeys(c[-1] for c in candidates if c[0]==top))

    def paintEvent(self,event):
        painter=QPainter(self)
        # VTK paints the map outside Qt's backing store. Replace the overlay's
        # dirty pixels (including alpha) before drawing; SourceOver with a
        # transparent brush would leave old graph positions and dimming intact.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(event.rect(),Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        d=self.controller.document
        dim=d.settings['dim']
        if dim: painter.fillRect(self.rect(),QColor(0,0,0,round(dim*255)))
        for layer in reversed(d.settings['order']):
            draw=self.layer_draw.get(layer)
            if draw is None: continue
            color=QColor(d.layers[layer].color)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for name,width,ink in (('edges',5,QColor('#071321')),('edges',2,color),('selected',7,QColor('#071321')),('selected',3,QColor('#ffe080'))):
                painter.setPen(QPen(ink,width)); painter.drawLines(draw[name])
            painter.setPen(QPen(QColor('#071321'),1)); painter.setBrush(color); painter.drawPath(draw['arrows'])
            for name,fill in (('nodes',color),('selected_nodes',QColor('#ffe080'))):
                painter.setPen(QPen(QColor('#071321'),2)); painter.setBrush(fill)
                for rect,square in draw[name]:
                    if square: painter.drawRect(rect)
                    else: painter.drawEllipse(rect)
            painter.setBrush(QColor('#ffe080'))
            for point in draw['handles']: painter.drawRect(QRectF(point[0]-4,point[1]-4,8,8))
            for point,label in draw['labels']:
                painter.setPen(QColor('#071321')); painter.drawText(QPointF(point[0]+10,point[1]-7),label)
                painter.setPen(QColor('#ffffff')); painter.drawText(QPointF(point[0]+9,point[1]-8),label)
        c=self.controller
        if c.ghost is not None:
            p=self.projection.project(unit([c.ghost]))[0]
            painter.setPen(QPen(QColor('#ffffff'),2,Qt.PenStyle.DashLine)); painter.setBrush(QColor(120,220,245,90))
            painter.drawEllipse(QPointF(*p),7,7)
        if c.draft_source and c.draft_source in d.nodes:
            n=d.nodes[c.draft_source]; coords=[(n.lon,n.lat),*c.draft_points]
            if c.ghost is not None: coords.append(c.ghost)
            if len(coords)>1:
                try:
                    lines=self.projection.clipped_segments(tessellate(coords))
                    painter.setPen(QPen(QColor('#ffffff'),2,Qt.PenStyle.DashLine))
                    for a,b in lines: painter.drawLine(QPointF(*a),QPointF(*b))
                except ValueError: pass
        if c.move_preview:
            for coords in c.preview_routes():
                try:
                    lines=self.projection.clipped_segments(tessellate(coords))
                    painter.setPen(QPen(QColor('#ffe080'),2,Qt.PenStyle.DashLine))
                    for a,b in lines: painter.drawLine(QPointF(*a),QPointF(*b))
                except ValueError: pass
            pos=self.projection.project(unit([c.move_preview]))[0]
            painter.setPen(QPen(QColor('#ffe080'),2)); painter.setBrush(QColor('#ffe080')); painter.drawEllipse(QPointF(*pos),6,6)
        painter.end()
