# SPDX-License-Identifier: Apache-2.0
"""Display-semantics checks on the LOD evaluation scenes (lod-tuning-plan.md, LT-01 to LT-03)."""
import os
from collections import deque
import numpy as np
import pytest
from stratascry.graph.model import Document
import lod_scenes

gui = pytest.mark.skipif(os.environ.get('STRATASCRY_GUI_TESTS') != '1', reason='Requires a desktop display')
SCENES = list(lod_scenes.SHORT)
VIEWS = {'global': 3.2, 'regional': 1.06, 'close': 1.01}


# Structure (no display needed)

@pytest.mark.parametrize('name', SCENES)
def test_scene_is_seeded_and_valid(name):
    a, b = lod_scenes.SHORT[name](), lod_scenes.SHORT[name]()
    assert len(a.document.nodes) == len(b.document.nodes) and len(a.document.edges) == len(b.document.edges)
    coords = lambda d: sorted((n.lon, n.lat) for n in d.nodes.values())
    assert coords(a.document) == coords(b.document)
    reloaded = Document.from_dict(a.document.to_dict())
    assert lod_scenes.fingerprint(reloaded) == lod_scenes.fingerprint(a.document)


def test_scene_structures():
    hub = lod_scenes.dense_hub(); d = hub.document
    assert d.degree[hub.meta['hub']] == len(hub.meta['leaves']) == 200
    chain = lod_scenes.sparse_chain(); d = chain.document
    assert sorted(set(d.degree.values())) == [1, 2] and len(chain.meta['path']) == len(d.nodes) - 1
    bridge = lod_scenes.low_degree_bridge(); d = bridge.document
    assert all(d.degree[k] == 2 for k in bridge.meta['bridge_nodes'])
    # Removing one bridge node disconnects the two regions.
    cut = bridge.meta['bridge_nodes'][2]; start = bridge.meta['regions'][0][0]
    seen = {start}; queue = deque([start])
    while queue:
        n = queue.popleft()
        for eid in d.adjacency[n]:
            e = d.edges[eid]; m = e.target if e.source == n else e.source
            if m != cut and m not in seen: seen.add(m); queue.append(m)
    assert not seen & set(bridge.meta['regions'][1])
    layers = lod_scenes.overlapping_layers(); d = layers.document
    assert len(d.layers) == 3 and {len(v) for v in layers.meta['per_layer'].values()} == {400}
    mixed = lod_scenes.mixed_directions(); d = mixed.document
    for forward, backward in mixed.meta['pairs']:
        f, b = d.edges[forward], d.edges[backward]
        assert (f.source, f.target) == (b.target, b.source) and f.directed and b.directed


# Display semantics (desktop opt-in)

@pytest.fixture
def window(tmp_path):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtTest import QTest
    from stratascry.app import create_application
    from stratascry.window import MainWindow
    app = create_application([])
    w = MainWindow(tile_path=tmp_path); w.show(); w.raise_(); w.activateWindow()
    QTest.qWaitForWindowActive(w, 3000); QTest.qWait(100)
    yield w
    w.graph.document.mark_saved(); w.close(); w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete); app.processEvents()


def show(window, scene, view):
    c = window.graph; nav = window.globe.navigation
    c.install_document(scene.document)
    nav.longitude, nav.latitude = lod_scenes.CENTER; nav.distance = VIEWS[view]
    window.globe.apply_camera(); c.overlay.rebuild()
    return c


def inside(overlay, key, margin=0):
    p = overlay.node_xy.get(key)
    return p is not None and margin <= p[0] <= overlay.width() - margin and margin <= p[1] <= overlay.height() - margin


def drawn_edges(overlay): return set(overlay.edge_hit_keys)


@gui
@pytest.mark.parametrize('view', list(VIEWS))
@pytest.mark.parametrize('name', SCENES)
def test_badges_and_spacing(window, name, view):
    scene = lod_scenes.SHORT[name](); c = show(window, scene, view); o = c.overlay; d = c.document
    drawn = drawn_edges(o)
    for key in o.surviving:
        assert o.badges.get(key, 0) == sum(1 for e in d.adjacency[key] if e not in drawn)
    pts = np.array([o.node_xy[k] for k in o.surviving])
    if len(pts) > 1:
        gaps = np.hypot(*(pts[:, None, :] - pts[None, :, :]).transpose(2, 0, 1))
        np.fill_diagonal(gaps, np.inf)
        assert gaps.min() >= 24 - 1e-6


@gui
@pytest.mark.parametrize('view', list(VIEWS))
@pytest.mark.parametrize('name', SCENES)
def test_selection_and_reveal_are_never_hidden(window, name, view):
    scene = lod_scenes.SHORT[name](); c = show(window, scene, view); o = c.overlay; d = c.document
    onscreen = [k for k in d.nodes if inside(o, k)]
    suppressed = [k for k in onscreen if k not in o.surviving]
    target = (suppressed or onscreen)[0]
    c.select(target); o.rebuild()
    assert target in o.surviving
    # A selected edge shows its on-screen endpoints.
    edge = next(iter(d.adjacency[target]))
    c.select(edge); o.rebuild()
    e = d.edges[edge]
    assert all(k in o.surviving for k in (e.source, e.target) if inside(o, k, 12))
    # Reveal on the busiest on-screen node restores every on-screen neighbor and edge.
    busiest = max(onscreen, key=lambda k: d.degree.get(k, 0))
    c.select(busiest); c.reveal_neighbors(); o.rebuild()
    drawn = drawn_edges(o)
    for eid in d.adjacency[busiest]:
        e = d.edges[eid]; other = e.target if e.source == busiest else e.source
        if inside(o, other, 12):
            assert other in o.surviving
            assert eid in drawn
    c.clear_reveal(); o.rebuild()


@gui
@pytest.mark.parametrize('name', SCENES)
def test_display_operations_leave_fingerprint_unchanged(window, name):
    scene = lod_scenes.SHORT[name](); before = lod_scenes.fingerprint(scene.document)
    c = show(window, scene, 'regional'); nav = window.globe.navigation
    for distance in VIEWS.values():
        nav.distance = distance
        for step in range(5):
            nav.longitude = lod_scenes.CENTER[0] + 0.05 * step; window.globe.apply_camera(); c.overlay.rebuild()
    c.set_building(True); c.toggle_declutter(False); c.overlay.rebuild(); c.toggle_declutter(True)
    c.document.setting('dim', 0.4, 'Dim'); c.overlay.rebuild()
    key = next(iter(c.document.nodes)); c.select(key); c.reveal_neighbors(); c.overlay.rebuild()
    assert lod_scenes.fingerprint(c.document) == before
