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
from .geometry import Projection, unit, tessellate, tessellate_many

NODE_BUDGET=1200
EDGE_BUDGET=1200
VERTEX_BUDGET=120_000
GEOMETRY_BYTES=32*1024**2
# Ranking refresh interval during camera motion, and the settle delay after it stops.
RANK_REFRESH_S=0.1
SETTLE_MS=120
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
        # Per-stage rebuild timings (ms, last 1000) for the benchmark; see lod-tuning-plan.md.
        self.stage_times=defaultdict(list)
        self.projection=Projection(controller.globe.navigation,controller.globe.width(),controller.globe.height())
        self.timer=QTimer(self); self.timer.setSingleShot(True); self.timer.timeout.connect(lambda:self.rebuild(allow_stale=True))
        self.rank_signature=None; self.rank_time=0.0; self.geometry_builds=0
        self.ranked_winners=[]; self.ranked_shown=np.zeros(0,dtype=bool); self.ranked_edge_set=set()
        self.settle_timer=QTimer(self); self.settle_timer.setSingleShot(True); self.settle_timer.timeout.connect(self.settle)
        self.setGeometry(controller.globe.rect())
        self.show(); self.raise_()

    def settle(self): self.rebuild()

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
        self.node_index={k:i for i,k in enumerate(self.node_ids)}
        self.node_points=unit([(v.lon,v.lat) for v in d.nodes.values()]) if d.nodes else np.empty((0,3))
        self.node_layer=[d.nodes[k].layer for k in self.node_ids]
        self.node_degree=np.fromiter((d.degree.get(k,0) for k in self.node_ids),dtype=float,count=len(self.node_ids))
        # Rank of each ID in string order: the final, stable tie-breaker.
        self.node_idrank=np.empty(len(self.node_ids),dtype=int)
        self.node_idrank[np.argsort(np.array(self.node_ids,dtype=object))]=np.arange(len(self.node_ids))
        self.old_mask=np.fromiter((k in self.old_survivors for k in self.node_ids),dtype=bool,count=len(self.node_ids))
        # Priority objects are included before ordinary model order at capacity.
        priority=set(d.settings['pins'])|({self.controller.selected} if self.controller.selected else set())
        edges=[e for e in sorted(d.edges.values(),key=lambda e:(e.id not in priority,e.id)) if d.layers[e.layer].visible]
        # Tessellate uncached edges in one batch; a local map survives cache eviction.
        missing=[e for e in edges if (e.id,self.detail_level) not in self.cache]
        fresh={}
        if missing:
            step=math.radians(1)/(2**self.detail_level)
            for e,p in zip(missing,tessellate_many([d.route(e) for e in missing],step)):
                fresh[e.id]=p; self.store(e.id,p)
        self.edge_ids=[]; arrays=[]; sizes=[]; count=0
        self.geometry_capacity=False
        for e in edges:
            p=fresh.get(e.id)
            if p is None: p=self.edge_points(e)
            if count+len(p)*2>VERTEX_BUDGET:
                self.geometry_capacity=True
                continue
            self.edge_ids.append(e.id); arrays.append(p); sizes.append(len(p)); count+=len(p)*2
        if arrays:
            points=np.concatenate(arrays); sizes=np.asarray(sizes)
            boundary=np.ones(len(points)-1,dtype=bool); boundary[np.cumsum(sizes)[:-1]-1]=False
            self.segment_a,self.segment_b=points[:-1][boundary],points[1:][boundary]
            self.edge_owner=np.repeat(np.arange(len(sizes)),sizes-1)
        else:
            self.segment_a=self.segment_b=np.empty((0,3)); self.edge_owner=np.empty(0,dtype=int)
        self.edge_index={k:i for i,k in enumerate(self.edge_ids)}
        self.edge_src=np.fromiter((self.node_index[d.edges[k].source] for k in self.edge_ids),dtype=int,count=len(self.edge_ids))
        self.edge_dst=np.fromiter((self.node_index[d.edges[k].target] for k in self.edge_ids),dtype=int,count=len(self.edge_ids))
        self.edge_idrank=np.empty(len(self.edge_ids),dtype=int)
        self.edge_idrank[np.argsort(np.array(self.edge_ids,dtype=object))]=np.arange(len(self.edge_ids))
        self.geometry_revision=d.revision; self.geometry_builds+=1

    def store(self,key,p):
        key=(key,self.detail_level)
        while self.cache and self.cache_bytes+p.nbytes>GEOMETRY_BYTES:
            _,old=self.cache.popitem(last=False); self.cache_bytes-=old.nbytes
        if p.nbytes<=GEOMETRY_BYTES:
            self.cache[key]=p; self.cache_bytes+=p.nbytes

    def rebuild(self,allow_stale=False):
        """Explicit rebuilds always re-rank; scheduled camera updates may reuse a recent ranking."""
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
        clock=[start]
        def stage(name):
            now=time.perf_counter(); times=self.stage_times[name]
            times.append((now-clock[0])*1000); clock[0]=now
            if len(times)>1000: del times[:-1000]
        stage('geometry')
        pr=self.projection
        xy=pr.project(self.node_points)
        visible=pr.visible(self.node_points)
        inside=visible & (xy[:,0]>=-12)&(xy[:,0]<=self.width()+12)&(xy[:,1]>=-12)&(xy[:,1]<=self.height()+12)
        ids=self.node_ids
        self.node_xy={ids[i]:xy[i] for i in np.flatnonzero(visible)}
        order=[l for l in d.settings['order'] if d.layers[l].visible]
        layer_rank={l:i for i,l in enumerate(order)}
        node_rank=np.fromiter((layer_rank.get(l,-1) for l in self.node_layer),dtype=int,count=len(ids))
        candidate=inside & (node_rank>=0)
        stage('project')
        # Bounded-staleness ranking (lod-tuning-plan.md): while only the camera moves,
        # reproject the last ranked display and re-rank at most every RANK_REFRESH_S,
        # plus once motion settles. Any other input change re-ranks immediately.
        signature=(id(d),self.geometry_builds,d.revision,self.detail_level,c.selected,c.reveal,tuple(d.settings['pins']),d.settings['declutter'],tuple(order),self.width(),self.height())
        now=time.perf_counter()
        if allow_stale and signature==self.rank_signature and now-self.rank_time<RANK_REFRESH_S:
            winners=[k for k in self.ranked_winners if k in self.node_xy]
            shown=self.ranked_shown; edge_set=self.ranked_edge_set; queues={l:None for l in order}
            subset=np.flatnonzero(shown[self.edge_owner]) if len(self.edge_owner) else np.zeros(0,dtype=int)
            seg,idx=pr.clipped_pairs(self.segment_a[subset],self.segment_b[subset])
            owners=self.edge_owner[subset][idx]
            seg,idx=clip_viewport(seg,self.width(),self.height()); owners=owners[idx]
            self.settle_timer.start(SETTLE_MS)
            stage('reuse')
        else:
            priority=set(d.settings['pins'])
            if c.selected:
                priority.add(c.selected)
                if c.selected in d.edges:
                    e=d.edges[c.selected]; priority.update((e.source,e.target))
            if c.reveal and c.selected in d.nodes:
                for eid in d.adjacency[c.selected]:
                    e=d.edges[eid]; priority.update((e.source,e.target,eid))
            priority_nodes=np.zeros(len(ids),dtype=bool)
            for key in priority:
                i=self.node_index.get(key)
                if i is not None: priority_nodes[i]=True
            # Deterministic degree ranking, with retained winners as a tie-breaker,
            # then layers interleaved round-robin in stack order.
            cand=np.flatnonzero(candidate)
            ranked=cand[np.lexsort((self.node_idrank[cand],~self.old_mask[cand],-self.node_degree[cand],~priority_nodes[cand]))]
            lay=node_rank[ranked]
            by_layer=np.argsort(lay,kind='stable')
            group_start=np.searchsorted(lay[by_layer],lay[by_layer],side='left')
            position=np.empty(len(ranked),dtype=int); position[by_layer]=np.arange(len(ranked))-group_start
            ranked=ranked[np.lexsort((lay,position))]
            xs=xy[:,0].tolist(); ys=xy[:,1].tolist()
            declutter=d.settings['declutter']; cells=defaultdict(list); win=np.zeros(len(ids),dtype=bool); winners=[]
            def accept(i):
                x,y=xs[i],ys[i]; cx,cy=int(x//24),int(y//24)
                if declutter and not priority_nodes[i]:
                    for gx in (cx-1,cx,cx+1):
                        for gy in (cy-1,cy,cy+1):
                            for ox,oy in cells.get((gx,gy),()):
                                if (x-ox)*(x-ox)+(y-oy)*(y-oy)<576: return
                win[i]=True; winners.append(ids[i]); cells[(cx,cy)].append((x,y))
            for i in sorted(np.flatnonzero(candidate & priority_nodes),key=lambda i:ids[i]):
                if len(winners)>=NODE_BUDGET: break
                accept(i)
            for i in ranked.tolist():
                if len(winners)>=NODE_BUDGET: break
                if not win[i]: accept(i)
            self.surviving=set(winners)
            suppressed=candidate & ~win
            self.old_survivors=self.surviving; self.old_mask=win
            self.capacity=self.geometry_capacity or len(winners)>=NODE_BUDGET
            queues={l:None for l in order}
            stage('rank')
            seg,idx=pr.clipped_pairs(self.segment_a,self.segment_b)
            owners=self.edge_owner[idx]
            seg,idx=clip_viewport(seg,self.width(),self.height()); owners=owners[idx]
            eligible=~(suppressed[self.edge_src]|suppressed[self.edge_dst]) if len(self.edge_ids) else np.zeros(0,dtype=bool)
            edge_priority=np.zeros(len(self.edge_ids),dtype=bool)
            for key in priority:
                i=self.edge_index.get(key)
                if i is not None: edge_priority[i]=True
            lengths=np.bincount(owners,weights=np.linalg.norm(seg[:,1]-seg[:,0],axis=1),minlength=len(self.edge_ids))
            ink_limit=self.width()*self.height()*0.12 if declutter else float('inf')
            ink=0.0; shown=np.zeros(len(self.edge_ids),dtype=bool); shown_count=0
            present=np.unique(owners)
            present=present[np.lexsort((self.edge_idrank[present],~edge_priority[present]))]
            present=present[eligible[present]]
            for i,prio,size in zip(present.tolist(),edge_priority[present].tolist(),lengths[present].tolist()):
                if shown_count>=EDGE_BUDGET:
                    self.capacity=True
                    continue
                if not prio and ink+size>ink_limit: continue
                shown[i]=True; shown_count+=1; ink+=size
            edge_set={self.edge_ids[i] for i in np.flatnonzero(shown)}
            stage('edges')
            self.badges={}
            suppressed_ids={ids[i] for i in np.flatnonzero(suppressed)}
            for key in winners:
                hidden=0
                for e in d.adjacency[key]:
                    edge=d.edges[e]; i=self.edge_index.get(e)
                    if edge.source in suppressed_ids or edge.target in suppressed_ids or (i is not None and eligible[i] and not shown[i]): hidden+=1
                if hidden: self.badges[key]=hidden
            stage('badges')
            self.rank_signature=signature; self.rank_time=now; self.settle_timer.stop()
            self.ranked_winners=winners; self.ranked_shown=shown; self.ranked_edge_set=edge_set
        self.layer_draw={l:{'edges':[],'selected':[],'arrows':QPainterPath(),'nodes':[],'selected_nodes':[],'handles':[], 'labels':[]} for l in queues}
        self.primitives=[]; self.grid=defaultdict(list)
        drawn=shown[owners] if len(owners) else np.zeros(0,dtype=bool)
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
        stage('draw_lists')
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
        started=time.perf_counter()
        self._paint(event)
        times=self.stage_times['paint']; times.append((time.perf_counter()-started)*1000)
        if len(times)>1000: del times[:-1000]

    def _paint(self,event):
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
