"""Reproducible desktop benchmark. Run from the repository with its venv Python.

python src/tests/graph_benchmark.py --seconds 60 --output /tmp/graph-benchmark
python src/tests/graph_benchmark.py --scene hub --scale 10 --seconds 20 --output /tmp/hub-x10
The stress option (or --scale 10) measures a larger scene without claiming supported
capacity. --scene picks one of the LOD evaluation scenes in lod_scenes.py.
"""
import argparse
import json
import math
from pathlib import Path
import resource
import time
import sys
import numpy as np
from PySide6.QtCore import QTimer,QPointF,QEventLoop
from PySide6.QtTest import QTest
from stratascry.app import create_application
from stratascry.window import MainWindow
from stratascry.graph.model import Document,Node,Edge,Waypoint
sys.path.insert(0,str(Path(__file__).resolve().parent))
import lod_scenes


def make_scene(n=1000,m=5000):
    d=Document(); layer=next(iter(d.layers)); rng=np.random.default_rng(4)
    for i in range(n):
        lon,lat=-90+rng.uniform(-1,1),25+rng.uniform(-1,1)
        d.nodes[f'n{i}']=Node(f'n{i}',layer,lon,lat,i)
    for i in range(m):
        a=f'n{i%n}'; b=f'n{(i%n+1+i//n)%n}'; u,v=d.nodes[a],d.nodes[b]
        d.edges[f'e{i}']=Edge(f'e{i}',layer,a,b,i,
            waypoints=[Waypoint('p0',u.lon*.67+v.lon*.33,u.lat*.67+v.lat*.33),Waypoint('p1',u.lon*.33+v.lon*.67,u.lat*.33+v.lat*.67)])
    d.layers[layer].node_next=n; d.layers[layer].edge_next=m
    d._index(set(d.nodes),set(d.edges),[]); d.mark_saved()
    return d,layer


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--seconds',type=float,default=60); parser.add_argument('--output',type=Path,required=True); parser.add_argument('--stress',action='store_true')
    parser.add_argument('--scene',choices=['default',*lod_scenes.SHORT],default='default'); parser.add_argument('--scale',type=int,default=1)
    args=parser.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    app=create_application([]); loop=QEventLoop(); window=MainWindow(); window.show(); window.raise_(); window.activateWindow(); QTest.qWait(250)
    c=window.graph
    if args.scene=='default':
        scale=10 if args.stress else args.scale
        d,layer=make_scene(1000*scale,5000*scale)
    else:
        d=lod_scenes.SHORT[args.scene](args.scale).document; layer=d.settings['order'][0]
    window.globe.navigation.longitude,window.globe.navigation.latitude=lod_scenes.CENTER
    start=time.perf_counter(); c.install_document(d); c.active=layer; c.overlay.rebuild(); first_ms=(time.perf_counter()-start)*1000
    QTest.qWait(1500)
    heartbeat=[]; samples=[]; start=time.perf_counter(); last=[start]; ticks=[0]; phase=[-1]
    phase_markers=[]
    churn=[]; last_shown=[None]
    def measure_churn():
        shown=c.overlay.surviving
        if shown is last_shown[0]: return
        previous=last_shown[0]; last_shown[0]=shown
        if previous is None or not shown: return
        w,h=c.overlay.width(),c.overlay.height()
        def interior(k):
            p=c.overlay.node_xy.get(k)
            return p is not None and 24<=p[0]<=w-24 and 24<=p[1]<=h-24
        changed=sum(1 for k in previous^shown if interior(k))
        churn.append(changed/len(shown))
    def beat():
        now=time.perf_counter(); heartbeat.append((now-last[0])*1000); last[0]=now
    def tick():
        elapsed=time.perf_counter()-start
        if elapsed>=args.seconds:
            timer.stop(); heart.stop(); loop.quit(); return
        section=min(2,int(elapsed/args.seconds*3))
        if section!=phase[0]:
            phase[0]=section; phase_markers.append({'phase':section,'elapsed':elapsed})
            window.globe.navigation.distance=(3.2,1.06,1.01)[section]
        measure_churn()
        t=time.perf_counter()
        window.globe.navigation.longitude=lod_scenes.CENTER[0]+0.2*math.sin(elapsed*0.5)
        window.globe.apply_camera()
        if ticks[0]%90==0:
            visible=list(c.overlay.surviving)
            if visible: c.select(visible[0])
        if ticks[0]%90==15 and c.selected in d.nodes:
            c.set_building(True); c.active=layer; c.tool='select'; c.overlay.rebuild()
            p=c.overlay.node_xy.get(c.selected)
            if p is not None:
                c.pointer_press(QPointF(*p)); c.pointer_move(QPointF(p[0]+12,p[1]+8)); c.pointer_release(QPointF(p[0]+12,p[1]+8))
        samples.append((time.perf_counter()-t)*1000); ticks[0]+=1
    heart=QTimer(); heart.timeout.connect(beat); heart.start(16)
    timer=QTimer(); timer.timeout.connect(tick); timer.start(16)
    loop.exec()
    def stats(values):
        return {'median_ms':float(np.median(values)),'p95_ms':float(np.percentile(values,95)),'max_ms':float(max(values))} if values else {}
    churn_stats={'median':float(np.median(churn)),'p95':float(np.percentile(churn,95)),'samples':len(churn)} if churn else {}
    stages={k:stats(v) for k,v in c.overlay.stage_times.items()}
    result={'scene_name':args.scene,'scale':args.scale if args.scene!='default' else (10 if args.stress else args.scale),'churn_fraction':churn_stats,'stages':stages,'scene':{'nodes':len(d.nodes),'edges':len(d.edges),'waypoints':sum(len(e.waypoints) for e in d.edges.values())},'viewport_logical':[window.globe.width(),window.globe.height()],'device_pixel_ratio':window.globe.devicePixelRatioF(),'duration_s':time.perf_counter()-start,'ticks':ticks[0], 'first_geometry_ms':first_ms,'input_work':stats(samples),'overlay_update':stats(c.overlay.times),'heartbeat':stats(heartbeat),'rss_mib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024**2,'display':c.overlay.stats,'phase_changes':phase_markers,'tile_cache_mib':window.blue_marble.cache.bytes/1024**2,'tile_actors':len(window.blue_marble.actors)}
    (args.output/'metrics.json').write_text(json.dumps(result,indent=2)+'\n')
    window.grab().save(str(args.output/'scene.png')); print(json.dumps(result))
    d.mark_saved(); window.close(); QTest.qWait(200)

if __name__=='__main__': main()
