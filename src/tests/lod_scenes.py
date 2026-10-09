# SPDX-License-Identifier: Apache-2.0
"""Seeded display-LOD evaluation scenes (designs/lod-tuning-plan.md, LT-01).

Synthetic verification fixtures over open ocean near 90°W, 25°N. Each builder takes
a ``scale`` (1 for the acceptance size, 10 for the stress variant) and returns a
``Scene`` whose ``meta`` names the structurally interesting objects.

Export for hands-on review:
python src/tests/lod_scenes.py --output /tmp/lod-scenes [--scale 10]
"""
import argparse
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import numpy as np
import uuid
from stratascry.graph.model import Document, Layer, Node, Edge

CENTER = (-90.0, 25.0)
COLORS = ('#62cde5', '#f2a65a', '#9be38b')


@dataclass
class Scene:
    name: str
    document: Document
    meta: dict = field(default_factory=dict)


class _Builder:
    def __init__(self, seed):
        self.rng = np.random.default_rng(seed)
        # IDs are seeded too: they are the final ranking tie-breaker, so random IDs
        # would make display results differ between runs.
        self.ids = np.random.default_rng(seed + 1000)
        self.d = Document(empty=True); self.d.id = self.uid()
        self.layer = self.add_layer('Network')

    def uid(self):
        return str(uuid.UUID(bytes=self.ids.bytes(16), version=4))

    def add_layer(self, name):
        layer = Layer(self.uid(), name, color=COLORS[len(self.d.layers) % len(COLORS)])
        self.d.layers[layer.id] = layer; self.d.settings['order'].append(layer.id)
        return layer.id

    def node(self, lon, lat, layer=None, kind='generic'):
        layer = layer or self.layer; l = self.d.layers[layer]
        key = self.uid(); self.d.nodes[key] = Node(key, layer, float(lon), float(lat), l.node_next, kind=kind)
        l.node_next += 1
        return key

    def edge(self, a, b, directed=False):
        layer = self.d.nodes[a].layer; l = self.d.layers[layer]
        key = self.uid(); self.d.edges[key] = Edge(key, layer, a, b, l.edge_next, directed=directed)
        l.edge_next += 1
        return key

    def finish(self):
        self.d._index(set(self.d.nodes), set(self.d.edges), []); self.d.mark_saved()
        return self.d


def _local_edges(b, keys, count, k=10):
    """Connect random picks to one of their k nearest neighbors: local, road-like edges."""
    pts = np.array([(b.d.nodes[n].lon, b.d.nodes[n].lat) for n in keys])
    near = np.empty((len(keys), k), dtype=int)
    for start in range(0, len(keys), 512):
        block = np.hypot(*(pts[start:start + 512, None, :] - pts[None, :, :]).transpose(2, 0, 1))
        idx = np.argpartition(block, k, axis=1)[:, :k + 1]
        for row, cand in enumerate(idx):
            cand = cand[cand != start + row][:k]
            near[start + row] = cand
    seen = set(); out = []
    while len(out) < count:
        i = int(b.rng.integers(len(keys))); j = int(near[i, b.rng.integers(k)])
        pair = (min(i, j), max(i, j))
        if pair in seen: continue
        seen.add(pair); out.append(b.edge(keys[i], keys[j]))
    return out


def dense_hub(scale=1):
    """One hub linked to many nearby leaves, over a background grid."""
    b = _Builder(11); lon0, lat0 = CENTER
    hub = b.node(lon0, lat0, kind='junction'); leaves = []
    for _ in range(200 * scale):
        r = 0.3 * math.sqrt(b.rng.uniform()); t = b.rng.uniform(0, 2 * math.pi)
        leaf = b.node(lon0 + r * math.cos(t), lat0 + r * math.sin(t)); leaves.append(leaf); b.edge(hub, leaf)
    side = int(math.ceil(math.sqrt(800 * scale))); grid = {}
    for i in range(side):
        for j in range(side):
            if len(grid) >= 800 * scale: break
            grid[i, j] = b.node(lon0 - 2 + 4 * i / (side - 1), lat0 - 2 + 4 * j / (side - 1))
    for (i, j), key in grid.items():
        for n in ((i + 1, j), (i, j + 1)):
            if n in grid: b.edge(key, grid[n])
    return Scene('hub', b.finish(), {'hub': hub, 'leaves': leaves})


def sparse_chain(scale=1):
    """A long path of degree-2 nodes spanning several hundred kilometres."""
    b = _Builder(12); lon0, lat0 = CENTER; n = 300 * scale; chain = []
    for i in range(n):
        f = i / (n - 1)
        chain.append(b.node(lon0 - 3 + 6 * f, lat0 + 0.4 * math.sin(f * 4 * math.pi)))
    edges = [b.edge(a, c) for a, c in zip(chain, chain[1:])]
    return Scene('chain', b.finish(), {'chain': chain, 'path': edges})


def low_degree_bridge(scale=1):
    """Two dense regions joined only by a degree-2 bridge path."""
    b = _Builder(13); lon0, lat0 = CENTER; regions = []
    per = 497 * scale
    for dx in (-1.75, 1.75):
        keys = [b.node(lon0 + dx + b.rng.uniform(-0.5, 0.5), lat0 + b.rng.uniform(-0.5, 0.5)) for _ in range(per)]
        _local_edges(b, keys, 2000 * scale - 4); regions.append(keys)
    def nearest(keys, lon):
        return min(keys, key=lambda k: abs(b.d.nodes[k].lon - lon) + abs(b.d.nodes[k].lat - lat0))
    a, z = nearest(regions[0], lon0 - 1.25), nearest(regions[1], lon0 + 1.25)
    bridge = [b.node(lon0 - 1.0 + 2.0 * i / 5, lat0) for i in range(6)]
    path = [b.edge(x, y) for x, y in zip([a, *bridge], [*bridge, z])]
    return Scene('bridge', b.finish(), {'bridge_nodes': bridge, 'path': path, 'regions': regions})


def overlapping_layers(scale=1):
    """Three layers sharing an area, each an offset copy of one network."""
    b = _Builder(14); lon0, lat0 = CENTER
    b.d.layers[b.layer].name = 'Layer A'
    layers = [b.layer, b.add_layer('Layer B'), b.add_layer('Layer C')]
    base = [(lon0 + b.rng.uniform(-1, 1), lat0 + b.rng.uniform(-1, 1)) for _ in range(400 * scale)]
    per_layer = {}
    for li, layer in enumerate(layers):
        keys = [b.node(lon + 0.01 * li, lat + 0.01 * li, layer) for lon, lat in base]
        _local_edges(b, keys, 2 * len(keys)); per_layer[layer] = keys
    return Scene('layers', b.finish(), {'layers': layers, 'per_layer': per_layer})


def mixed_directions(scale=1):
    """Directed cycles, opposite-direction parallel pairs and undirected edges."""
    b = _Builder(15); lon0, lat0 = CENTER
    keys = [b.node(lon0 + b.rng.uniform(-1, 1), lat0 + b.rng.uniform(-1, 1)) for _ in range(500 * scale)]
    cycles = []
    for c in range(100 * scale):
        ring = keys[5 * c:5 * c + 5]
        cycles.append([b.edge(x, y, True) for x, y in zip(ring, ring[1:] + ring[:1])])
    pairs = []
    for _ in range(250 * scale):
        i, j = b.rng.choice(len(keys), 2, replace=False)
        pairs.append((b.edge(keys[i], keys[j], True), b.edge(keys[j], keys[i], True)))
    _local_edges(b, keys, 500 * scale)
    return Scene('directions', b.finish(), {'cycles': cycles, 'pairs': pairs})


SCENES = {f.__name__: f for f in (dense_hub, sparse_chain, low_degree_bridge, overlapping_layers, mixed_directions)}
SHORT = {'hub': dense_hub, 'chain': sparse_chain, 'bridge': low_degree_bridge, 'layers': overlapping_layers, 'directions': mixed_directions}


def fingerprint(document):
    """Hash of analytical content: layers' topology, coordinates, attributes and weights."""
    data = document.to_dict()
    payload = {k: data[k] for k in ('layers', 'nodes', 'edges', 'distance')}
    payload['weights'] = {k: document.weight(e) for k, e in sorted(document.edges.items())}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def main():
    from stratascry.graph import persistence
    parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path, required=True); parser.add_argument('--scale', type=int, default=1)
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    for name, build in SHORT.items():
        scene = build(args.scale); path = args.output / f'lod-{name}-x{args.scale}.ssg.json'
        persistence.save(scene.document, path)
        print(f'{path}  nodes={len(scene.document.nodes)} edges={len(scene.document.edges)}')


if __name__ == '__main__': main()
