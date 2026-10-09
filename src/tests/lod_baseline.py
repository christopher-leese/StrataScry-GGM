# SPDX-License-Identifier: Apache-2.0
"""Deterministic display metrics for the LOD scenes (lod-tuning-plan.md, phase 0).

Unlike graph_benchmark.py this does not time anything: it steps the camera in
fixed increments and reports what the declutter shows. Requires a desktop session.
python src/tests/lod_baseline.py --output /tmp/lod-baseline.json [--scale 10]
"""
import argparse
import json
import numpy as np
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PySide6.QtTest import QTest
from stratascry.app import create_application
from stratascry.window import MainWindow
from stratascry.graph.geometry import unit
import lod_scenes

VIEWS = {'global': 3.2, 'regional': 1.06, 'close': 1.01}
PAN_STEP_PX = 10
PAN_STEPS = 30


def interior(o, key, margin=24):
    p = o.node_xy.get(key)
    return p is not None and margin <= p[0] <= o.width() - margin and margin <= p[1] <= o.height() - margin


def measure(window, scene, view):
    c = window.graph; o = c.overlay; nav = window.globe.navigation
    c.install_document(scene.document); d = c.document
    nav.longitude, nav.latitude = lod_scenes.CENTER; nav.distance = VIEWS[view]
    window.globe.apply_camera(); o.rebuild()
    onscreen = [k for k in d.nodes if interior(o, k, 0)]
    result = {'onscreen_nodes': len(onscreen), 'shown_nodes': len(o.surviving), 'shown_edges': len(set(o.edge_hit_keys)),
              'badged_nodes': len(o.badges), 'capacity_notice': bool(o.capacity)}
    meta = scene.meta
    if 'bridge_nodes' in meta:
        visible = [k for k in meta['bridge_nodes'] if interior(o, k, 0)]
        result['bridge_nodes_shown'] = f"{sum(k in o.surviving for k in visible)}/{len(visible)}"
    if 'path' in meta:
        drawn = set(o.edge_hit_keys)
        candidates = [e for e in meta['path'] if all(interior(o, k, 0) for k in (d.edges[e].source, d.edges[e].target))]
        result['path_edges_drawn'] = f"{sum(e in drawn for e in candidates)}/{len(candidates)}"
    # Churn: pan east in fixed screen-sized steps; count interior nodes that change state.
    lon, lat = nav.longitude, nav.latitude
    a, b = o.projection.project(unit([(lon, lat), (lon + 0.01, lat)]))
    degrees_per_px = 0.01 / max(1e-9, float(np.hypot(*(b - a))))
    churn = []; previous = set(o.surviving)
    for _ in range(PAN_STEPS):
        nav.longitude += PAN_STEP_PX * degrees_per_px; window.globe.apply_camera(); o.rebuild()
        shown = set(o.surviving)
        if shown: churn.append(sum(1 for k in previous ^ shown if interior(o, k)) / len(shown))
        previous = shown
    churn.sort()
    result['churn_median'] = churn[len(churn) // 2] if churn else 0.0
    result['churn_max'] = churn[-1] if churn else 0.0
    return result


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path, required=True); parser.add_argument('--scale', type=int, default=1)
    args = parser.parse_args()
    app = create_application([]); window = MainWindow(); window.show(); window.raise_(); window.activateWindow(); QTest.qWait(250)
    report = {'viewport_logical': [window.globe.width(), window.globe.height()], 'scale': args.scale, 'pan_step_px': PAN_STEP_PX, 'scenes': {}}
    for name, build in lod_scenes.SHORT.items():
        scene = build(args.scale)
        report['scenes'][name] = {view: measure(window, scene, view) for view in VIEWS}
        window.graph.document.mark_saved()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n'); print(json.dumps(report, indent=2))
    window.close(); QTest.qWait(200)


if __name__ == '__main__': main()
