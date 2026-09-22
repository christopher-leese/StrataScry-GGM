# Node visibility and summarized edges — preliminary design discussion

Date: September 20, 2026  
Status: candidate display rules; not an implementation plan approved for coding.  
Related: [map packages](map-packages-plan.md).

## User direction and scope

At wider zoom, prioritize the most-connected nodes in an area. The definition
of area, final symbol sizes, and edge behavior remain subject to testing.
Selected/pinned node overrides, contrasting outlines, optional background
dimming, generous selection targets, and geographical graph coordinates have
been accepted in principle. The graph's main purpose remains multilayer
modeling, pathfinding, and sensitivity analysis; the map provides context.

The proposals below concern the display. They do not delete nodes, rewire the
analytical graph, change weights, or approximate computations. A future
algorithmic graph reduction would be a different feature with different tests.

## 1. What “area in screen space” means

Geographic space measures positions on Earth; screen space measures where
those positions appear in the viewport, in Qt logical pixels. A large region
fits into a small part of the screen when zoomed out; a smaller region fills
that same screen area when zoomed in.

Illustrative prototype: divide the viewport into 100 × 100 logical-pixel cells
and rank nodes whose projected symbols fall inside each cell. At a wide view,
12 nodes may occupy one cell: retain a high-connectivity node and indicate
that additional nodes are hidden. When zooming spreads those nodes into
separate cells, more can appear. The value 100, cell capacity, and the cell
method are examples, not selected requirements or performance claims.

The grid is internal and need not be visible. It defines display competition,
not an administrative boundary, geographic model layer, or graph component.
Showing a retained node does not automatically make it a representative of
all other nodes nearby. Hiding node labels is also distinct from hiding nodes.

Alternatives to test:

| Method | Benefit | Limitation |
|---|---|---|
| Fixed screen grid | Simple prototype and density budget | Nearby symbols across cell boundaries can still overlap; panning can change winners |
| Screen-distance / symbol-overlap suppression | Directly addresses visible collisions | Variable symbol sizes and efficient neighbor queries require more work |
| Stable geographic cells with zoom-dependent levels | Group membership is stable while panning | Projected density varies with latitude and view direction |

Start by testing the first two on the same graph. Use stable tie-breaking,
retain previous visibility until a change is meaningful (hysteresis), and
always preserve selected/pinned objects. Do not turn an illustrative grid
size into a production constant without evaluating dense and sparse scenes.

Candidate priority: user pin / current selection, then connectivity in the
active layer scope, then a stable tie-breaker. Define “connectivity” explicitly:
unique neighbors, in/out degree, and cross-layer links are different measures.
Road bend/shape control points should not increase a facility's importance.
Degree does not capture all analyst importance; a one-link facility or a
low-degree bridge between two graph regions can still be important.

## 2. What happens to edges when nodes are hidden

Two distinct behaviors must not be conflated:

1. **Visibility filtering:** draw fewer objects. No new apparent connection is
   created. This is the proposed first experiment.
2. **Explicit summarization:** a display object represents a known chain or an
   explicit group of original edges. This requires rules beyond node ranking.

For the first experiment, draw a normal edge when both endpoints are visible;
otherwise omit it and give the visible endpoint a badge indicating hidden
adjacency. Selection or a reveal action can temporarily restore the incident
nodes and edges. This may understate connectivity at a glance, so compare it
with the later summary display in usability tests. Do not silently substitute
an edge to the nearest retained/high-degree node.

An isolated selected edge must reveal its true endpoints. When a pathfinding
result is selected, reveal the actual path or clearly render a path summary;
node suppression must not make the reported result appear disconnected.
Hidden-adjacency badges are counts of defined incident objects, not counts of
all possible paths.

## 3. Visual treatment for an explicit summary

Use redundant cues so color is not the only distinction. Proposed legend:

| Display object | Candidate appearance | Interaction / meaning |
|---|---|---|
| Ordinary graph edge | Solid stroke with contrasting halo | Inspect/edit the actual edge ID, endpoints, direction, and attributes |
| Selected ordinary edge | Stronger halo or emphasis while retaining solid stroke | Same edge; selection does not change semantics |
| Known chain summarized through hidden nodes | Broken stroke plus a small summary badge | Inspect its ordered member edges/nodes; expand to the actual chain |
| Explicit cluster-to-cluster edge bundle (later) | Broken stroke plus count badge | Count original crossing edges with defined membership, not possible routes |
| Map-package boundary | Thin closed footprint, package label, and map-coverage legend | Map metadata; excluded from graph selection and analysis |

If dash patterns are later needed for graph attributes, reserve another
summary-specific badge or pattern. Palette and stroke weights remain to be
prototyped. Summary style is separate from future risk-score coloring.

Example of a **single known chain**:

```text
Detailed graph:       A ── b ── c ── D
Simplified display:   A ┄┄ [via 2 hidden nodes · 3 edges] ┄┄ D
```

The second line does not add an A–D edge to the graph. Retain the projected
path shape where practical; drawing a straight shortcut could misstate the
underlying geography. Chain summaries are only unambiguous when the member
path is explicitly known. An arbitrary hidden subgraph may contain branches,
cycles, mixed directions, and alternative routes; it must not be displayed as
one equivalent weighted edge without a separate aggregation definition.

Directed summaries require an established direction through the represented
chain. Mixed-direction bundles should not get a single misleading arrow.
Do not automatically sum, average, minimize, or otherwise assign hazard scores
or weights to summary strokes. The application's analyst-defined weighting,
filter multipliers, layer combinations, and sensitivity measures may require
different aggregation rules. Initially show membership/counts, with original
attributes available on inspection.

Cluster summaries require explicit cluster objects with member IDs. Keeping
one high-degree node visible does not by itself establish cluster membership,
and a bundle must not imply that its representative facility has connections
belonging only to other nearby facilities.

## Proposed evaluation before implementation

Use a dense hub, a sparse chain, two regions connected by a low-degree bridge,
overlapping layers, and mixed directed edges. Compare whether users can select
an intended object, recover hidden neighbors, follow a selected path, and tell
actual edges from summaries. Check panning/zooming stability, reveal behavior,
selection overrides, symbol overlap, and color-independent recognition.

When graph analysis exists, verify that display changes leave a fingerprint of
the underlying graph and analytical results unchanged. The map-package work
can proceed independently of these display decisions. No graph reduction or
edge-summary algorithm has been chosen or executed in this planning task.
