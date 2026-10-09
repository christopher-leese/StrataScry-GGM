# Graph editor — version 0.4 implementation

September 28, 2026. Implements the basic editor described in
[nodes-and-edges-plan.md](nodes-and-edges-plan.md), including the subsequent
read-only, ghost placement, layer-order and length/weight decisions.

## Document and analysis boundaries

Projects have globally unique object IDs, independent per-layer topology, stable
zero-based node/edge naming sequences, and a top-to-bottom layer order. Custom
names do not replace IDs. Changing a layer name updates automatic labels only.
Parallel edges and cycles are supported; self-loop editing and cross-layer links
remain deferred. Shape waypoints belong to edges and do not change adjacency.

`graph/model.py` owns records, adjacency, unique-neighbor degree, mutations and
one chronological delta history. History is capped at 200 commands / 32 MiB;
a single operation beyond that payload limit is rejected rather than silently
becoming irreversible. Allocation high-water counters never go backwards, including
on branched undo history. Retained counter changes can keep a document unsaved
after undoing an addition; saving preserves the non-reuse rule across restarts.

`graph/persistence.py` validates version-1 UTF-8 JSON, rejects unknown fields and
invalid references, and saves using a temporary file and same-directory atomic
replacement. Project reading/validation runs on a worker thread. Files are limited
to 64 MiB; the prototype accepts up to 200,000 nodes plus edges, 10,000 layers,
and 1,024 shape controls per edge. These input limits are not performance claims.
A failed load leaves the current document intact; a failed save preserves the
previous file and leaves the document unsaved. Imagery is never embedded.

Node kinds and typed attributes are generic. Attribute values support text,
finite numbers, booleans and string lists. The properties editor currently uses
JSON with validation; optional project-wide definitions add types, labels, units
and descriptions. Template authoring, hazard evaluation, route algorithms and
analytical layer combination remain future work.

## Geometry and weights

`graph/geometry.py` uses geographic coordinates and short great-circle segments.
Its fixed logical display radius is 1.0001, shared by pointer picking, ghosts and
projected anchors even when image detail is absent. Screen calculations use Qt
logical pixels; Qt handles the overlay's device-pixel scaling. Imagery retains
its independent VTK rendering. Sphere-horizon clipping prevents overlay geometry
from appearing through the planet, including when only the middle of an edge is
visible. Node dragging retains the pointer's grab offset.

Distances use the declared spherical approximation with radius **6,371,008.8 m**,
recorded in the project. They sum arc lengths between stored controls, independent
of tessellation, display offsets and camera state. This is not an ellipsoidal
survey-distance claim. Within 1e-7 radians of an antipodal segment, the editor
requires another waypoint to establish the intended path.

Edge Properties exposes Unassigned, Manual, or Route length weights. The latter
is `scale × length in metres`; output units are analyst metadata. Geometry changes
recompute a length-derived weight but leave manual values unchanged. Unassigned
is distinct from zero. Inputs/results must remain finite; no positivity/routing
assumption is imposed. Combining length and hazard contributions is deferred.

## Interaction and permissions

- **B** toggles building mode, scoped to the globe so typing B in a field is safe.
- **Right drag** navigates in either mode. A stationary right click opens the
  context menu. Arrow keys, scroll and Command +/- remain available.
- **Add Node** shows a hover ghost without a held button. An ordinary click
  commits on release after drag discrimination. Add Edge uses the same convention
  for endpoints and optional controls; duplicate connections require an explicit
  continuation of the ordinary Add Edge workflow.
- **Select / Move** selects or drags a movable node/handle. The highest visible
  layer containing a hit wins before object-type priority. Same-layer overlaps
  appear in the inspector's candidate list. Edge bodies do not translate routes.
- Direct object edits require building mode and the visible active owning layer.
  View mode disables document edits, including undo/redo and persisted display
  controls. Inspection, temporary reveal and navigation remain available.
- Hiding/deleting the active layer clears it without selecting a replacement.
  Layer deletion confirms counts and removes owned objects in one undoable step.
  History replay and confirmed layer deletion can affect hidden/inactive layers.
- Layer stack order is persistent and undoable. Activating/selecting a layer
  never brings it to the front. Reorder/hide covering layers to pick below them.
- Escape and tool/mode changes cancel drafts; focus loss cancels transient drags.
  New/Open/Close handle unsaved work. Closing waits for raster/project workers.

All controls are exposed under native View submenus and shared in the context
menu. The [graph hotbar](graph-hotbar.md) above the globe adds icon shortcuts for
Select / Move, Add Node, and Add Edge; selected tools can expose variant menus.
The layer panel offers shortcut buttons to the same controller operations.
The initial active layer is empty; choose a visible layer explicitly to edit.

## Display and optimization

The geometry spike selected a **single transparent Qt overlay** over the existing
VTK globe. This permits deterministic screen-space order and hit testing without
placing graph layers on different spherical shells. There are no per-object Qt
widgets or VTK actors. Edge line segments are batched by layer/style; small node
glyphs are drawn individually in the same painter pass. A combined path containing
hundreds of ellipse strokes proved substantially slower on the development Mac
and was replaced after measurement.

Each overlay paint replaces the dirty region with transparent pixels using
`QPainter.CompositionMode_Source`, then draws the current graph and optional
map dimming with `SourceOver`. VTK renders the basemap outside Qt's backing store;
leaving the overlay's previous alpha/color contents intact produces graph trails
during drag navigation and accumulates dimming on repeated paints. The clear is
limited by the paint event's dirty region and Qt's system clip; it adds no stored
frames or per-object resources.

- Shared viewport limits: 1,200 node glyphs, 1,200 edges, 120,000 derived geometry
  vertices; a 32 MiB LRU edge-geometry cache. Source graph data stays intact.
- Decluttering favors pins/selection, then unique-neighbor degree within each
  layer, with retained winners and stable IDs breaking ties. Screen-distance
  suppression uses neighboring cells (24 logical pixels). Layer queues share
  the node allowance round-robin; there is no complete budget per layer.
- With decluttering enabled, total displayed edge stroke length also has a
  viewport-area budget (0.12 × logical-pixel area, measured in screen pixels).
  Priority edges consume the same hard resource limits; excess geometry is
  reported in the status. This is display filtering, not edge summarization.
- Hidden-adjacency badges count suppressed original incident edges. Temporary
  reveal survives pan/zoom while its source remains selected and ends on selection
  change, hiding, project change or Clear Reveal. Pin is a separate saved edit.
- Node hit candidates use screen cells; edge hits use vectorized segment bounds
  and distance tests. Geographic arrays are projected/clipped in batches. Rendering
  and picking use the same stack order and primitive identity mapping.
- Camera updates coalesce through a 16 ms single-shot timer. There is no idle graph
  animation. Edge tessellation refines by zoom in bounded power-of-two levels.
  Model changes invalidate only affected cached edge shapes; the display arrays
  are rebuilt for the next document revision.
- Basemap dimming is below the graph drawing within the overlay, so new image
  tiles are dimmed consistently without changing their cache or worker lifecycle.
  The existing 96 MiB tile cache and 32-detail-actor cap remain in place.

The first release uses real route geometry and selection highlighting. Cosmetic
separation, edge bundles and synthetic shortcuts are deliberately absent.
Performance and remaining limits are recorded in
[graph-editor-verification.md](graph-editor-verification.md).
