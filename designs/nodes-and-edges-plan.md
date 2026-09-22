# Basic nodes and edges — implementation plan

Date: September 20, 2026  
Status: proposed implementation; this document does not implement graph editing.  
Baseline: version 0.3 tiled Blue Marble viewer.

## Objective and scope

Deliver an editable, persistent geographical graph over the existing globe:
place named nodes, connect them, shape edges with waypoints, move nodes while
preserving connectivity, and inspect/edit the resulting objects. The basemap is
context for analyst-authored geometry; neither road extraction nor building
imagery is required. Optimization is a requirement of this increment.

This plan preserves the longer-term direction: user-defined graph layers and
attributes, reusable node templates, separate hazard objects, pathfinding, and
sensitivity analysis. Those capabilities must not be implied by a working
editor before their semantics and algorithms exist.

The first usable milestone edits one layer. The completed increment includes
basic layer creation/selection/visibility, save/open, undo/redo, and a measured
visibility policy. General template authoring, hazard evaluation, routing,
analytical layer combination, graph summaries, collaboration, and terrain
models are later increments. Cycles are allowed; the editor does not restrict
the graph to a tree or DAG.

## Evidence and inherited constraints

Repository sources reviewed for this plan:

- [Current Blue Marble implementation](blue-marble-prototype.md): local tiled
  imagery, bounded caches, asynchronous reads, spherical display, and existing
  performance evidence. This is the current map baseline.
- [Globe design](globe-viewer.md), [GlobeView](../src/stratascry/globe.py), and
  [geometry](../src/stratascry/geometry.py): geographical coordinate convention,
  camera state, existing left-drag navigation to be replaced by right-drag,
  and already implemented arrow-key navigation.
- [Window/action registry](../src/stratascry/window.py): shared Qt actions and
  native macOS View/context menus.
- [Graph visibility discussion](graph-display-lod-notes.md): connectivity-based
  visibility, selected/pinned overrides, hidden-adjacency indicators, and the
  distinction between filtering and summarizing a graph.
- [Project description](../README.md): configurable layers, attributes, and
  analyst-defined additive and multiplicative hazard scoring.

User requirements carried forward:

1. Nodes and edges have optional custom names; defaults follow
   `<layer_name>-node 0` and `<layer_name>-edge 0`, with separate sequences.
2. Moving a node keeps its incident edges attached. Edge shapes can include
   geographical waypoints.
3. Layers and object information types are user-defined; a fixed layer-count
   limit is not a design objective. Actual capacity remains finite and measured.
4. At wider views, prioritize the most-connected nodes within an area whose
   definition remains subject to testing. Symbol size policy is still unsettled.
5. Provide contrasting outlines, optional basemap dimming, generous selection
   targets, and geographic storage of graph positions.
6. Interaction commands remain accessible through the native **View** menu.
7. Hazards are **hazard objects**, separate from graph vertices. Scores obtain
   their meaning from the analyst, not from assumptions built into the map.
8. **B toggles graph-building mode**. **Right-button drag navigates** in both
   viewing and building modes; retain the existing arrow-key navigation. A
   stationary right click retains context-menu access.

Proposals below are implementation choices, not additional user-approved
requirements. In particular, layer ownership, waypoint semantics, degree
ranking, and numeric performance targets should remain identifiable as choices.

## Requirements → functions → logical allocation → verification

| ID | Requirement / proposed scope | Function | Logical allocation | Acceptance evidence |
|---|---|---|---|---|
| GE-01 | Place and move geographic nodes | Surface picking; coordinate edit | Geometry + editor controller | Cardinal/seam/pole checks; GUI placement and drag |
| GE-02 | Stable connected edges, including cycles | Maintain endpoint references and adjacency | Graph model + commands | Moving/deleting/undo preserves referential integrity |
| GE-03 | Custom/default names | Allocate labels independently of identity | Model + inspector | Counters, rename, save/load and undo cases |
| GE-04 | Curved edge paths | Edit ordered shape waypoints | Geometry + interaction state | Endpoint motion, seam crossing, waypoint edits |
| GE-05 | Basic extensible layers and attributes | Select scope; validate data | Document + layer/attribute UI | Multiple layers, typed values, visibility invariance |
| GE-06 | Inspectable, reversible editing | Select, inspect, undo/redo | Commands + inspector | One undo per completed gesture; cancel is non-mutating |
| GE-07 | Save and reopen work (proposed scope) | Versioned serialization and atomic save | Persistence | Round trip, invalid input, interrupted-write behavior |
| GE-08 | Legible, selectable display at changing zoom | Cull, prioritize and reveal | Renderer + display policy | Dense/sparse scenes; hidden connectivity and hit tests |
| GE-09 | Mandatory optimization | Batch drawing; incremental updates; bounded derived state | Renderer + scheduler/indexes | Profiled scenes; budget and responsiveness checks |
| GE-10 | Native View access; B toggle, right-drag and arrows | Shared actions; explicit tool modes | Window + input router | Menu/context parity; focus and shortcut regression |
| GE-11 | Preserve future analytical meaning | Separate topology, shape, display and hazards | Model boundaries | Display operations leave document topology unchanged |

Physical/runtime allocation remains one local Python desktop process with Qt
and VTK, a local project document, and independently stored imagery. No backend,
account, network map dependency, or new rendering engine is proposed.

## Data model and invariants

Use renderer-independent records with stable IDs. Names are labels; changing a
name must never change references. Qt widgets, VTK actor handles, screen
coordinates, and tile identifiers must not enter the persistent graph model.

| Record | Proposed minimum fields |
|---|---|
| Document | schema version, document ID, layer/node/edge maps, attribute definitions |
| Layer | ID, unique nonempty name, node/edge sequence counters, display defaults |
| Node | ID, owning layer ID, longitude/latitude in degrees, name mode, allocated sequence, custom name, kind, optional template ID, attribute values |
| Edge | ID, owning layer ID, endpoint IDs, directed flag, name mode/sequence/custom name, ordered shape waypoints, attribute values |
| Shape waypoint | ID scoped to edge, longitude/latitude; editable handle rather than traversable vertex |
| Attribute definition | stable key, display label, value type, applicable object kind, optional unit/description |
| Display state | visible/active layers, pins, dimming preference; separate from analytical data |

### Identity, labels and coordinates

- Allocate UUIDs for persistent objects. Maintain adjacency maps keyed by node
  ID; moving a node updates only its incident geometry.
- Allocate each node/edge sequence from its layer's own zero-based counter,
  even when a custom name is supplied. Do not renumber on deletion or reuse a
  deleted object's label during normal creation. Persist counters; undo restores
  original IDs and sequences without introducing collisions.
- Proposed naming rule: store automatic/custom mode explicitly. An automatic
  label uses the layer's **current** name and the allocated sequence, so renaming
  a layer updates automatic labels. Custom labels are unchanged. Blank/whitespace
  input restores automatic mode. Duplicate custom labels are allowed; show IDs
  and layer names when disambiguation is necessary.
- Longitude is east-positive, normalized to `[-180, 180)`; latitude is
  north-positive in `[-90, 90]`. Reject nonfinite and out-of-domain values. Store
  geographic coordinates, not a fictitious altitude inferred from a render offset.
- No edge may reference a missing endpoint. Validate mutations before commit.
  Edge crossings and coincident positions do not establish connectivity; only
  shared endpoint IDs do.

### Layer ownership: proposed first implementation

Create a default layer named `Network`. Each node/edge belongs to exactly one
layer, and edge endpoints must belong to that layer. Multiple layers may be
visible, but editing targets one active layer; other layers are inspectable
without silently moving the active scope. Making a layer active also shows it.
Cancel an unfinished gesture before changing the active layer.

This is a deliberately limited first representation. Earlier discussions use
“layers” both for networks and for dimensions such as climate and hazards.
Whether several layers share one canonical facility/road, contain independent
topologies, or store per-layer attributes on shared objects remains open.
Before implementing corresponding-edge calculations or multilayer routing,
resolve that distinction and version the schema accordingly. Stable IDs permit
explicit correspondence later; matching names or coordinates must not create it
automatically. No cross-layer link editing is included in this increment.

### Edges, waypoints and direction

Propose an undirected default with an explicit directed option. Preserve stored
endpoint order in either case; reversing a directed edge also reverses its shape
waypoint order. Parallel edges are valid and retain separate IDs. The creation
workflow must make a second edge an explicit action rather than an accidental
repeat click. Support cycles of distinct nodes. Defer self-loop editing and
reject a same-node connection with an explanation until a loop-shape interaction
exists; this restriction does not prevent ordinary cycles.

The original “special waypoint node” idea has two possible meanings:

- A **shape waypoint** bends one edge without adding a graph connection. Use
  this for road-like curves in the first implementation.
- A **junction node** connects edges and participates in graph traversal. Use a
  normal graph node, initially with kind `junction`.

This distinction prevents adding bends from increasing graph degree or changing
future route results. It is a proposed interpretation of the original idea.
Reusable/named waypoint vertices can be added later if they need independent
attributes or traversal semantics. Do not silently convert shape handles into
junctions. Splitting an edge at a junction is a later explicit command unless
it can be included without delaying the basic editor.

An edge's displayed path is its start node, ordered waypoints, and end node,
with surface-following segments. Moving an endpoint retains the waypoints'
absolute geographical positions; the user can then reshape the path. Whole-edge
translation/rubber-banding is not implied. Use short great-circle arcs between
controls, with adaptive tessellation for the current view; do not linearly
interpolate longitude across the antimeridian. Require an intermediate waypoint
for exactly/near-antipodal segments where a unique arc is unstable. Define and
test the numerical tolerance. A coincident pair of distinct nodes remains valid
topology but needs an inspector indication and an overlap-selection mechanism.

### Attributes and templates

Provide a generic node and junction appearance first, with editable kind and
basic typed attributes: text, finite number, boolean, and string list. Attribute
keys are stable and definitions make types inspectable. Treat lists usable as
tags as metadata only; tag filtering and routing constraints are not active yet.
Do not execute strings as expressions or infer units from a field name.

Reserve an optional template reference without shipping a full template editor.
A later template may supply symbol, kind, field definitions and defaults for
facilities or other structures. Define instance overrides and template update
behavior in that later plan. No fixed catalogue of military/civilian facilities
is required for the generic editor.

## Interaction contract

Use a checkable **Graph-Building Mode** action with shortcut **B**, off at
startup. Pressing B enables the last graph tool (initially Select/Move); pressing
it again returns to viewing mode. Building mode offers an exclusive action group
for Select/Move, Add Node and Add Edge. Show the mode, active tool and a short
instruction in the status area. Selecting a building tool through View also
enables building mode. Escape cancels a pending operation without leaving the
mode; toggling B or switching tools cancels an uncommitted preview. Ignore key
repeat for the B toggle so holding B cannot repeatedly switch modes.

**Right-button drag rotates the globe in every mode**, replacing the existing
left-drag navigation. Arrow keys retain their existing 10° rotation steps and
View → Rotate actions; wheel/trackpad and Command +/− retain zoom. Left-button
input is reserved for selection and graph editing, with no navigation fallback.
In viewing mode it may select/inspect but cannot modify the graph.

| Mode/action | Pointer behavior | Completion/cancellation |
|---|---|---|
| Viewing | Right drag rotates; left click selects/inspects | No creation or geometry mutation |
| Add Node | Left click valid globe position previews/places a node in active layer | One click commits one node; mode stays active |
| Select/Move | Left click selects; left drag on a node past Qt's drag threshold previews geographic motion; blank-space left drag does nothing initially | Release commits one move; Escape/focus loss cancels preview |
| Add Edge | Left click source node, optional globe positions for shape waypoints, then target node | Target commits; Escape cancels; draft remains separate from model |
| Edit Edge Shape | Selected edge exposes handles; actions insert/remove waypoints, handles drag like nodes | One command per completed change; endpoints remain ID-linked |
| Inspect | Selection opens a reusable inspector for identity, layer, name, coordinates/shape, direction and attributes | Apply validates and commits a reversible edit |
| Delete Selection | Reports incident edges that will also be removed when deleting a node | One reversible compound command; undo restores full connectivity |

Distinguish a right click from a right drag using Qt's drag-distance threshold.
Do not open the context menu on right-button press: begin navigation after the
threshold, and open the context menu on release only if no drag occurred. A
completed right drag must not produce a context menu. Keep Control-click on
macOS, Shift F10 and View → Show Context Menu as secondary menu access paths.
Control-click must never place a node or begin an edit.

Right-drag navigation during an Add Edge draft preserves its committed draft
control points and refreshes its preview from the new camera. Do not allow
simultaneous edit and navigation drags: if another button is pressed during a
node/handle drag, cancel that transient edit before beginning navigation. In
placement modes a drag must not emit a click. A ray missing the sphere creates
nothing; during an edit drag retain the last valid preview and explain why the
pointer is invalid. Cancel transient drags on focus loss to avoid stuck gestures.

For selection, use a screen-space hit radius larger than the visible marker or
edge stroke. Prototype an 8-logical-pixel minimum tolerance, adjustable after
use. Nodes/handles take priority over edges; overlapping candidates are listed
or cycled deterministically. Parallel edges must all remain selectable through
the inspector/candidate list even if their geometry coincides. Selection of an
edge reveals its true endpoints. Picking ignores imagery actors and the grid.

All commands are available through **View**, using submenus to contain growth:

- **View → Graph Tools:** Graph-Building Mode (B), tool selection, cancel,
  inspect, delete, undo/redo,
  edge direction and shape commands.
- **View → Graph Display:** show graph, pin/unpin, reveal hidden neighbors,
  decluttering, basemap dimming, layer list and inspector visibility.
- **View → Graph Project:** new/open/save/save as, plus layer management.

The context menu reuses the same QAction instances and enabled states. Existing
navigation stays in View; Quit remains the standard application lifecycle item.
File/Edit aliases may be considered later, but View remains a complete route to
these operations as requested. Commands requiring a location must have a
menu-accessible numeric coordinate dialog or enter an explicit placement mode.

Scope B and bare arrow/plus/minus/Delete shortcuts to the globe so editing text,
coordinates or attributes cannot toggle modes or rotate/zoom/delete behind the
inspector. Typing the letter B in a name/attribute field inserts text normally. Native
text-field undo takes precedence while text is being edited; graph undo applies
to committed graph commands. Stationary right-click/Control-click must not begin an edit or
commit a pending edge. Reset View resets the camera, not the document or selection.

## Rendering, picking and optimization

Keep graph rendering independent of the Blue Marble tile grid. A tile arriving,
evicting or changing detail cannot move or remove an analytical graph object.
The graph itself remains resident for this prototype; out-of-core graph storage
is a separate capacity decision, not a consequence of imagery tiling.

1. **Coordinate picking.** Unproject the pointer to a camera ray and intersect
   an analytical radius-1 sphere. Select the nearest forward intersection and
   convert to geographic coordinates. Explicitly handle Qt logical pixels,
   render-window physical pixels and VTK's vertical origin convention. This
   avoids node placements changing when image tile meshes are replaced.
2. **Surface visibility.** Share a display-surface convention with the globe:
   current detail radius is `1.0001`, graticule `1.00012`, minimum camera distance
   `1.0002`. Choose and test a graph depth bias/offset compatible with those
   values and near clipping, rather than repeatedly inflating sphere radii.
   Glyph footprints should be screen-aligned; their anchors stay geographical.
   Hide rear-hemisphere nodes and clip edge segments at the horizon, including
   edges with both endpoints outside the visible region but a visible middle.
3. **Batch primitives.** Batch node markers and edge polylines by a small style
   palette and spatial chunks; do not allocate one Qt widget or VTK actor per
   graph object. Maintain explicit primitive-to-object-ID mappings for picking.
   Selected objects/handles can use a small separate batch. Prototype halo strokes
   and marker outlines on this Mac before choosing a wide-line implementation.
4. **Incremental work.** Cache adjacency, degree and geographical bounds. A node
   drag rebuilds that node and incident edges only. Coalesce camera notifications
   and input previews to the latest state; update VTK on the GUI thread. Use a
   conservative spatial index for candidate nodes/edge segments, then precise
   screen hit tests. Index long segments by their bounds, not endpoints alone.
5. **Bound derived work.** Cap projected-geometry/label caches, tessellation per
   segment and total displayed vertices. Bound undo history by command count and
   estimated payload bytes; evict old commands with an honest available-history
   indication. Keep the saved/dirty state correct if a saved undo position expires.
   Record the chosen numeric limits after the rendering spike; do not conceal
   oversized workloads by deleting model data.
6. **Idle behavior.** Render on changes and coalesce requests; do not introduce
   an always-running graph animation loop. Preserve the current Blue Marble
   96 MiB decoded cache and 32-tile limits. Measure combined behavior while tiles
   are loading, not only the graph on a static background.

### Zoom-dependent visibility

Follow [the existing display notes](graph-display-lod-notes.md). For the first
policy, compare a screen-cell method with screen-distance suppression. The
previous 100 × 100 logical-pixel cell example is a trial parameter, not a fixed
requirement. Use stable ID tie-breaking and hysteresis to reduce churn when
panning; maintain a coarse geographic candidate index so ranking does not require
projecting every node on every pointer event.

Proposed ranking: selected/pinned objects first, then **unique adjacent nodes in
the active layer**, then stable ID. Parallel edges count once for this proposed
measure; direction is ignored for display ranking. Shape waypoints never count.
This chooses one precise meaning of “most-connected”; directed in/out degree and
multilayer scope can be later configurable alternatives. Rank other visible
layers within their own scope. A selected edge reveals both of its endpoints.

Ordinary edges are solid with a contrasting halo and direction arrows where
applicable. Initially show them only when their endpoints survive density
filtering. This differs from viewport clipping: endpoints outside the viewport
need not be drawn for a connecting edge segment inside it to remain visible.
Keep edge candidate culling independent of the list of on-screen node glyphs. A retained
node gets a badge counting omitted incident edge IDs, with a reveal command;
that count is not a route count. Hiding a layer remains explicit and distinct
from automatic decluttering. Reveal overrides density suppression, not the
user's layer visibility without an explicit action.

Do not draw artificial shortcuts through hidden nodes or make a high-degree
node represent its neighborhood. Broken strokes/count badges are reserved for a
later explicit summary mode with inspectable member IDs. Color alone must never
be the distinction between a real and summarized edge. Defer numerical edge
weight aggregation entirely.

Use a provisional bounded range of marker/stroke sizes in logical pixels and
labels for selected/hovered objects first; final sizing remains open as discussed.
Pins/selections may exceed a normal display-density target. Report that situation
and retain inspectability; use chunked work or a visible capacity message rather
than dropping selected objects silently. Optional basemap dimming affects imagery
only, including newly arriving tiles; graph halos, selection and legend remain
legible. Hidden/display state must not mutate adjacency, attributes or future
analysis results.

## Persistence and undo

Use a versioned UTF-8 JSON document for this increment. Store the graph,
attribute definitions, naming counters and user display preferences, with an
optional camera bookmark. Do not embed imagery, tile caches, transient selection,
VTK objects or live tool drafts. A project must open with the bundled overview
when optional local tiles are absent.

Validate schema, IDs, references, finite coordinates, field types and size limits
before replacing the current document. Unknown schema versions fail clearly;
never partially load and silently discard unsupported analytical fields. Parse
large documents away from interactive rendering where needed, then commit the
validated result on the GUI thread.

Save through a temporary file in the destination directory followed by atomic
replacement. A failed save leaves the previous file intact and the document dirty.
New/Open/Close prompts about unsaved work; canceled dialogs preserve everything.
Project commands are local, with no cloud upload or collaboration behavior.

Use command objects for add/move/edit/delete and layer changes. A drag previews
without changing persistent state, then creates one command on release. Cascaded
node/edge deletion is one command. Undo/redo restores the original IDs, names,
attributes, shape and layer references. Camera movement, hover and imagery tile
updates do not enter the graph undo stack.

## Compatibility with later hazards and analysis

Do not implement hazard scoring in this increment. Leave a separate future
`HazardObject` collection with layer applicability and either radius-based edge
influence or explicit edge-ID references. Hazard geometry is not an edge endpoint
and does not contribute to connectivity ranking. Radius intersection semantics
(distance to a point, any segment, or an affected fraction of length) still need
a separate specification.

Preserve the user's intended composition without storing risk as an unexplained
mutable total. A later candidate expression for an edge is:

\[
R_e = \left(\prod_{m\in G_e}m\right)
      \sum_{h\in A_e}\left[a_{h,e}
      \prod_{f\in F_e:\,\mathrm{matches}(f,\mathrm{tags}(h))}f\right].
\]

Here `A_e` contains additive hazard contributions, `G_e` net multipliers, and
`F_e` tag-filter multipliers. Empty multiplier products equal one. The formula
reproduces `M(A+B+C)` and `N(D)+E` when only D has the matching tag. It proposes
multiplying multiple matching filter factors once each; multiple matches, tag
matching logic, default/base contributions, missing values, allowed score domains
and cross-layer composition still require decisions before a scoring engine.
The selector examines **hazard contribution tags**, not automatically edge tags.

A net multiplier remains outside the sum when later contributions arrive; do not
apply it destructively to an accumulated stored total. Neither score represents
probability, expected loss, or physical units unless an analyst defines that
meaning. No normalization, layer averaging, positivity constraint or choice of
pathfinding algorithm is introduced by this editor plan. Any future algorithm
must validate its own assumptions against the chosen weights and graph direction.

## Implementation sequence and exit gates

| Phase | Work and proposed files under `src/stratascry/graph/` | Exit gate |
|---|---|---|
| 0. Geometry/rendering spike | `geometry.py`, renderer prototype; ray picking, halos, depth/horizon handling and batched markers/lines | Demonstrate selectable geometry at global/regional/closest zoom, seam and poles; record chosen primitives and derived-data budgets |
| 1. Document foundation | `model.py`, `commands.py`, `persistence.py`; IDs, layer ownership, naming, adjacency and versioned serialization | Model/round-trip/undo invariants pass without Qt; simple cyclic fixture reloads exactly |
| 2. First editable graph | `controller.py`, `interaction.py`, `renderer.py`, `inspector.py`; place/move/connect/delete in default layer; integrate existing window and globe | Place three nodes, connect a triangle, drag one, rename, undo/redo, save/reopen; navigation remains usable |
| 3. Shapes and layers | Waypoint insertion/motion/removal, direction/parallel-edge inspection, layer management and typed attributes | Bent edges retain endpoint links; multiple layers stay isolated and inspectable; all actions in View |
| 4. Visibility and scale | `display_policy.py`, spatial indexes, label/halo/dimming treatment; compare density policies | Degree preference, pins, hidden-adjacency reveal and model invariance pass; performance gate below met or capacity explicitly reduced |
| 5. Release verification | Regression tests, packaging, design/verification record and navigation help | Packaged app saves/reopens real edits, contains updated help, and retains tiled imagery behavior |

Each phase should leave a usable increment. Basic batching and incremental
updates start in phases 0–2; optimization is not deferred until phase 4.
No NetworkX/other analysis dependency is required merely to store/edit this graph.
Evaluate such a dependency when actual algorithms are specified.

`GlobeView` needs an explicit input-routing boundary: right-button gestures
belong to navigation/context handling, while left-button gestures are dispatched
according to the graph-building state. Replace its current right-press popup
with release/drag discrimination. Retain existing arrow-key actions and update
navigation help and mouse-input regression tests to the new contract. `MainWindow` owns shared actions
and inspector/layer-panel placement. The graph controller must not reach into
Blue Marble's worker queue or own its caches. Prefer a small shared display API
for dimming and surface conventions instead of circular controller imports.

## Verification and performance gate

All checks in this section are **planned**, not executed graph-editor results.
Add tests under `src/tests/`; retain the existing globe, tiled imagery and optional
map-package regressions. Avoid tests that merely restate implementation details.

- **Model:** auto/custom labels across layer rename and save/load; counters after
  delete/undo/new edit; directed/parallel edges and cycles; endpoint/layer integrity;
  node move affects only incident geometry; shape points do not change adjacency.
- **Geometry:** pick/project round trips at cardinal locations, both sides of the
  dateline, near poles, viewport edges and multiple device-pixel ratios; sky miss,
  tangent ray, coincident endpoints and antipodal guard; horizon clipping and
  near-surface visibility with/without detail tiles.
- **Interaction:** B toggle/held-key behavior and View check-state parity; B in
  text fields; right click versus right drag; arrows in both modes; no left-drag
  navigation; edge draft preservation during right-drag navigation and cancellation
  on mode switch; focus loss, inspector shortcut isolation, context-menu parity, overlap
  selection, deletion cascade/undo, and selected-edge endpoint reveal.
- **Persistence:** valid round trips; malformed/oversized documents; duplicate IDs,
  dangling references and unsupported versions; failed-save preservation; missing
  optional imagery; unsaved-change cancellation. Include a schema fixture so later
  changes cannot silently alter project meaning.
- **Display semantics:** dense hub, sparse chain, low-degree bridge, overlapping
  layers, coincident/parallel edges and directed cycles. Hash analytical data before
  and after zoom/pan/dimming/decluttering; the hash must remain unchanged.

Proposed initial performance acceptance target on the existing M3/8 GiB Mac:
**1,000 nodes, 5,000 edges and 10,000 shape waypoints**, with tiled imagery enabled,
at global, regional and local views. Also profile a **10,000-node/50,000-edge**
stress scene to identify limits; the stress size is not initially a supported
capacity claim. Include dense visible clusters and long horizon-crossing paths,
not only uniformly distributed nodes that are easy to cull.

For a warmed 60-second pan/zoom/selection/drag run at the same viewport used for
the Blue Marble baseline, propose these gates:

- 95th-percentile input-handler plus graph-update work at or below 33 ms; record
  render submission separately and do not call this input-to-photon latency.
- A 16 ms event-loop heartbeat with 95th-percentile interval below 50 ms and no
  unexplained pause over 200 ms; also record tile-loading and first-use spikes.
- Existing tile/cache caps respected; chosen graph cache, tessellation and undo
  budgets enforced, with actor counts and rendered vertices reported.
- Proposed combined process RSS target below 1 GiB for the acceptance scene;
  inspect repeated edit/delete/open/close cycles for accumulating retained memory.
  Process RSS is not a measurement of GPU memory.

These are design targets to validate, not inferred performance from the previous
61 passing viewer tests. If the acceptance scene misses a target, profile and
resolve the bottleneck or document a reduced supported capacity before declaring
this increment complete. Record hardware, viewport/DPI, graph distribution,
visible counts, cold/warm conditions, method and measured results in a new
`designs/graph-editor-verification.md` during implementation.

## Decisions that remain open

Proceed with the explicit prototype defaults above without treating them as final
analytical semantics. The consequential open decisions are:

1. Shared physical objects across layers versus independent per-layer topology;
   resolve before corresponding-edge calculations or multilayer routing.
2. Whether some waypoints should be named, reusable topological vertices rather
   than private shape controls; resolve before routing relies on waypoint meaning.
3. Final screen-space area, symbol sizes, connectivity measure and reveal policy;
   choose from the display experiments, preserving analyst access to low-degree nodes.
4. Score domains, tag matching, multiplier overlap and spatial hazard influence;
   resolve in a separate hazard-model plan before evaluation/pathfinding.

The completion criterion for this plan's implementation is a responsive, reversible,
persistent basic graph editor on the tiled globe, with inspectable topology and
clear boundaries around analytical features still to come.
