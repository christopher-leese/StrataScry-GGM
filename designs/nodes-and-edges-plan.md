# Basic nodes and edges — implementation plan

Date: September 20, 2026; revised September 28, 2026
Status: proposed implementation; this document does not implement graph editing.  
Baseline: version 0.3 tiled Blue Marble viewer.

Implementation update (September 28, 2026): see [version 0.4 implementation](graph-editor-implementation.md)
and [executed verification](graph-editor-verification.md). This plan retains its
requirements and proposed targets; the verification record states measured limits.

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
9. Viewing mode is read-only for graphs/objects and persisted layer display
   preferences. Inspection and later non-mutating analysis remain available.
10. Layer deletion removes its contents after confirmation and supports undo.
    Hidden layers cannot be directly edited; no active layer is required.
11. Persisted layer display edits mark the document unsaved and support undo.
12. Placement shows a cursor-following ghost without holding a mouse button;
    click to place, then use the move tool for subsequent dragging.
13. Parallel edges are supported. Geographic route shape is independent of
    readability treatments; cosmetic edge separation is deferred.
14. Edge properties expose whether weight depends on route length. Length changes
    must not change an independent manually assigned weight.
15. Select/Move is one combined tool. At overlapping viewport hits, select only
    an object from the topmost visible layer containing a hit, using the layer
    stack order. Do not cycle or click through to objects in lower layers.

Proposals below are implementation choices, not additional user-approved
requirements. In particular, layer ownership, waypoint semantics, degree
ranking, and numeric performance targets should remain identifiable as choices.

## Requirements → functions → logical allocation → verification

| ID | Requirement / proposed scope | Function | Logical allocation | Acceptance evidence |
|---|---|---|---|---|
| GE-01 | Place and move geographic nodes | Surface picking; coordinate edit | Geometry + editor controller | Cardinal/seam/pole checks; GUI placement and drag |
| GE-02 | Stable connected edges, including cycles and parallel edges | Maintain endpoint references and adjacency | Graph model + commands | Moving/deleting/undo preserves referential integrity |
| GE-03 | Custom/default names | Allocate labels independently of identity | Model + inspector | Counters, rename, save/load and undo cases |
| GE-04 | Curved edge paths | Edit ordered shape waypoints | Geometry + interaction state | Endpoint motion, seam crossing, waypoint edits |
| GE-05 | Basic extensible layers and attributes | Select scope; validate data | Document + layer/attribute UI | Multiple layers, typed values, visibility invariance |
| GE-06 | Inspectable, reversible editing | Select, inspect, undo/redo | Commands + inspector | One undo per completed gesture; cancel is non-mutating |
| GE-07 | Save and reopen work (proposed scope) | Versioned serialization and atomic save | Persistence | Round trip, invalid input, interrupted-write behavior |
| GE-08 | Legible, selectable display at changing zoom | Cull, prioritize and reveal | Renderer + display policy | Dense/sparse scenes; hidden connectivity and hit tests |
| GE-09 | Mandatory optimization | Batch drawing; incremental updates; bounded derived state | Renderer + scheduler/indexes | Profiled scenes; budget and responsiveness checks |
| GE-10 | Native View access; B toggle, right-drag and arrows | Shared actions; explicit tool modes | Window + input router | Menu/context parity; focus and shortcut regression |
| GE-11 | Preserve future analytical meaning | Separate topology, shape, display and hazards | Model boundaries | Display operations leave document topology unchanged |
| GE-12 | Explicit length-dependent edge weights | Measure geographic route; configure weight source | Geometry + edge properties + model | Geometry changes update length-derived weight only; view changes update neither |
| GE-13 | Top-layer selection with combined Select/Move | Resolve visible hits by stack order; enforce edit permissions | Hit testing + layer display + controller | No lower-layer click-through, including when upper hit is read-only |

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
| Edge | ID, owning layer ID, endpoint IDs, directed flag, name mode/sequence/custom name, ordered shape waypoints, weight specification, attribute values |
| Shape waypoint | ID scoped to edge, longitude/latitude; editable handle rather than traversable vertex |
| Attribute definition | stable key, display label, value type, applicable object kind, optional unit/description |
| Persisted display state | ordered layer IDs (top to bottom), layer visibility/style, pins, dimming and decluttering preferences; separate from analytical data but part of the editable document |
| Session state | nullable active layer, selection, camera, current tool, temporary reveal and placement ghost; not serialized or part of document undo |

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
- Longitude is east-positive and latitude north-positive. Proposed numeric-entry
  acceptance: finite longitude in `[-180, 180]` and latitude in `[-90, 90]`;
  reject values outside those ranges rather than silently wrapping likely input
  mistakes such as `540`. Store longitude canonically in `[-180, 180)`, mapping
  accepted `180` to `-180`. Internal camera arithmetic may wrap longitude before
  producing an object coordinate. Serialized coordinates use the canonical
  convention. Store geographic coordinates, not altitude inferred from a render
  offset. This input-range choice is a proposed default, not an additional
  user requirement.
- No edge may reference a missing endpoint. Validate mutations before commit.
  Edge crossings and coincident positions do not establish connectivity; only
  shared endpoint IDs do.

### Layer ownership: proposed first implementation

Create a default layer named `Network`. Each node/edge belongs to exactly one
layer, and edge endpoints must belong to that layer. Multiple layers may be
visible. Direct object editing requires building mode, a visible owning layer,
and that layer as the active editing target. Other layers remain inspectable
with read-only inspector fields. The active layer is nullable session state:
map-only viewing and a document with zero layers are valid.

Hiding the active layer cancels its pending gesture, hides its objects/handles,
and clears the active target; it must not activate another layer automatically.
Showing that layer again does not automatically reactivate it. Proposed default:
activate only a visible layer, keeping Show Layer and Set Active Layer separate.
Clear selections/reveals whose objects become hidden. Changing the active target
cancels uncommitted editing but does not itself dirty the document.

Layer visibility is a persisted, undoable display edit and is disabled in viewing
mode. To hide/show a layer, enable building mode; this does not require an active
layer. A selected row in the layer panel is distinct from an active editing target.

Delete Layer is available in building mode for the explicitly targeted layer,
including a hidden layer. Show an “Are you sure?” dialog with its name and counts
of contained nodes, edges and owned shape waypoints; cancel is non-mutating.
Confirmation performs one compound deletion of the layer, all its objects and
associated display records. Undo restores IDs, names, attributes, counters,
geometry, stack position and persisted display settings. Deleting the active layer clears the
active target. Deleting the last layer leaves an empty document; do not create a
replacement layer automatically.

Confirmed history rule: hidden/inactive-layer locks apply to **direct object
editing**, not replaying document undo/redo or confirmed Delete Layer. A unified
history must restore its recorded state even when the user has since changed
editing target. Undo/redo does not silently activate a layer; it may clear a
now-invalid active target. Display the affected layer in the history action label.
Document this exception in help and verify it in the history tests.

The layer panel stores one explicit top-to-bottom stack order for all layers,
including hidden ones; every layer ID appears exactly once. Rendering and hit
testing share this order. It is a display ordering, not altitude: do not put each
layer on a different sphere. Layer reordering is a saved, undoable display edit
requiring building mode. New layers are inserted at the top; deletion/undo
preserves their original stack position. Selecting or activating a layer never
implicitly reorders it. Hide or reorder a covering layer to reach objects below
through viewport picking; the layer panel itself remains accessible.

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
waypoint order. Parallel edges are distinct edges joining the same two node IDs,
for example two alternative roads connecting the same facilities. They may have
independent names, shapes, direction and attributes. An opposite directed edge
is a separate connection but is not a duplicate of the same ordered direction.

Use the ordinary **Add Edge** workflow for all edges; a separate Add Parallel Edge
tool is unnecessary. Proposed duplicate guard: if an undirected edge already
joins that pair, or a directed edge already has the same ordered endpoints and
direction, show the existing connection(s) and let the user choose “Create another
edge” or cancel. Shape/attribute differences do not merge identities. The guard
is an explicit continuation of Add Edge, not a different edge type. Clear the
completed source selection so a trailing click cannot immediately duplicate it.
Support cycles of distinct nodes. Defer self-loop editing and
reject a same-node connection with an explanation until a loop-shape interaction
exists; this restriction does not prevent ordinary cycles.

The original “special waypoint node” idea has two possible meanings:

- A **shape waypoint** bends one edge without adding a graph connection. Use
  this for road-like curves in the first implementation.
- A **junction node** connects edges and participates in graph traversal. Use a
  normal graph node, initially with kind `junction`.

Shape waypoints do not change graph connectivity or insert traversable vertices.
Changing edge geometry can still change future distance- or hazard-dependent
costs and consequently route results; topology invariance is not cost invariance.
The shape/junction distinction is a proposed interpretation of the original idea.
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
topology but needs an inspector indication and the same-layer overlap selection
mechanism below. Parallel routes can be geometrically coincident; they must not
be artificially bent simply to distinguish their identities.

### Route length, edge properties and weight

Keep three concepts distinct: stored geographic route geometry, the analyst's
weight definition, and rendering style. Two roads between the same nodes can
have different waypoint-defined routes and therefore different lengths. Two
edges may also intentionally share identical geometry while representing distinct
connections. Neither case requires automatic visual offsets.

Compute route length from the endpoints and ordered geographic shape waypoints:

`L_e = sum(distance(P_i, P_(i+1)))`.

For this spherical prototype, use the same short-arc segment definition as route
geometry, with a documented, versioned physical-radius parameter for conversion
to metres. The chosen parameter is model metadata, not the dimensionless display
radius `1.0001`. Record the chosen distance convention before implementation;
label resulting distances as spherical estimates. Do not derive length from
screen pixels, tessellated render vertices, stroke width or the display offset.
Changing camera, zoom, tile detail, layer order or highlighting cannot change it.

Add **Edge Properties…** under View → Graph Tools and the shared context menu,
opening the selected edge's inspector. Include endpoints, direction, route/shape,
read-only calculated length and units, and an explicit **Weight source** control.
Proposed initial choices:

| Weight source | Editable properties | Evaluation |
|---|---|---|
| Unassigned (default) | None | No analytical weight; do not silently substitute zero or one |
| Manual | Finite value, optional unit/description | Value remains unchanged when route length changes |
| Route length | Explicit scale and declared resulting units; default scale 1 gives metres | `weight = scale * L_e`; recalculates when geographic route changes |

Store the source selection and its parameters as the weight specification. Length
and a length-derived weight are computed outputs, not independently editable
values. A missing/manual-unassigned value remains distinguishable from a valid
zero. No positivity requirement or routing algorithm is introduced by this
editor; future analysis must validate its own weight assumptions. Finite inputs
that overflow a derived result produce a clear validation error, not an infinite
stored weight. General expressions, multiple cost channels and combining length
with hazards remain later analysis work; this increment establishes the explicit
dependency and basic modes without executing arbitrary expressions.

Moving an endpoint or changing waypoints invalidates route length and any
length-derived weight. A manual weight and unrelated attributes remain intact.
During a drag, show derived values as preview state; commit geometry once and
recompute consistently through undo/redo/load. Changing weight source or parameters
is one undoable edit, allowed only in building mode on the visible active layer.
Switching from Manual to Route length makes the source change explicit; never
silently infer it from an attribute name or the existence of a measured length.

For this increment, use true geographic paths, selected-edge highlighting and a
**same-layer** overlap list in the inspector. Defer cosmetic separation entirely.
If later introduced, screen-space offsets must remain a rendering-only operation
and must not affect length, hazard intersection, connectivity or weight. Edge
selection must still resolve to the original object ID.

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
instruction in the status area. Building-tool actions are disabled while viewing;
only the explicit Graph-Building Mode action or B enables editing. Escape cancels a pending operation without leaving the
mode; toggling B or switching tools cancels an uncommitted preview. Ignore key
repeat for the B toggle so holding B cannot repeatedly switch modes.

**Right-button drag rotates the globe in every mode**, replacing the existing
left-drag navigation. Arrow keys retain their existing 10° rotation steps and
View → Rotate actions; wheel/trackpad and Command +/− retain zoom. Left-button
input is reserved for selection and graph editing, with no navigation fallback.
In viewing mode it may select/inspect but cannot modify the graph or persisted
object/layer display settings. Inspector fields are read-only; disable mutating
commands at the controller/command boundary as well as their menu actions.

### Command-by-mode record

| Command family | Viewing mode | Building mode | Document history / unsaved state |
|---|---|---|---|
| Navigate, zoom, reset camera, select, inspect, open/close panels | Allowed | Allowed | Session only; no document change |
| Non-mutating analysis (later) | Allowed when implemented | Allowed when implemented | Transient result only; writing results to objects is an edit |
| Set/clear active editing target | Allowed for visible layers | Allowed for visible layers | Session only; never bypasses build/visibility checks |
| Create/move/delete/rename objects; edit attributes/direction/shape/weight source | Disabled | Allowed only in visible active layer | Undoable; marks unsaved |
| Create/rename/delete a layer | Disabled | Allowed; no active layer required | Undoable; deletion confirmed and cascading |
| Layer show/hide/style/order, persistent pins, dimming/decluttering preferences | Disabled | Allowed; target layer need not be active | Undoable; marks unsaved |
| Temporary selection/neighbor reveal | Allowed | Allowed | Session only; never unhides an explicitly hidden layer |
| Document Undo/Redo | Disabled | Allowed if history exists, including the stated hidden-layer exception | Same chronological history for graph and persisted display edits |
| Save / Save As | Allowed | Allowed | Saves existing document; marks saved only on success |
| New / Open / Close | Allowed with unsaved-work handling | Allowed with unsaved-work handling | Explicit document lifecycle; cancels drafts; does not edit the old graph |
| Toggle Graph-Building Mode (B) | Enables building | Returns to viewing | Session only; cancels uncommitted previews |

New/Open creates or selects another document; it is an explicit lifecycle action,
not a permission to edit the existing document while viewing. Text-field undo
remains local to an editable input until Apply commits its document command.

| Mode/action | Pointer behavior | Completion/cancellation |
|---|---|---|
| Viewing | Right drag rotates; left click selects/inspects | No creation or geometry mutation |
| Add Node | With no button held, a ghost follows the cursor over valid globe positions | A normal left click commits one node; mode stays active with a fresh ghost |
| Select/Move | Left click selects the top-layer hit; left drag on that hit moves it only if it is a movable node/handle in the active visible layer; blank-space left drag does nothing | Release commits one move; a read-only hit blocks lower-layer dragging; Escape/focus loss cancels preview |
| Add Edge | Left click source node, optional globe positions for shape waypoints, then target node | Target commits; Escape cancels; draft remains separate from model |
| Edit Edge Shape | Selected edge exposes handles; actions insert/remove waypoints, handles drag like nodes | One command per completed change; endpoints remain ID-linked |
| Inspect | Selection opens a reusable inspector for identity, layer, name, coordinates/shape, direction and attributes | Read-only unless edit conditions hold; Apply validates and commits one reversible edit |
| Delete Selection | Reports incident edges that will also be removed when deleting a node | One reversible compound command; undo restores full connectivity |

Placement requires **no press-and-hold gesture**: pointer motion previews the
object, an ordinary press/release click commits it, and Select/Move handles later
repositioning. Commit on release only if the gesture remained below the drag
threshold, using the valid ghost anchor at that click. A drag commits nothing.
The ghost is not a document object, does not allocate a persistent ID/sequence,
and does not enter undo/history. Hide or mark it invalid over sky, UI panels or
an unavailable editing layer; never place at a stale last-valid position when
clicking outside the valid area. Recompute after camera movement even if the
pointer has not moved. Clear it on leaving placement mode or losing focus and
re-establish it on valid pointer input. Edge and waypoint creation use the same
hover-preview/click-to-commit convention for each control point.

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
use. Define **top layer** as the highest visible layer in the stack that has an
eligible rendered object within the pointer's hit tolerance. A top layer with no
hit there does not block empty space over lower layers. Exclude hidden layers,
clipped/backside geometry, density-suppressed objects and imagery/grid actors.

Resolve layer precedence **before** object type or distance: a higher-layer edge
wins over a lower-layer node at the same location. Within the winning layer,
prioritize handles, nodes, then edges; use projected distance followed by a stable
ID tie-breaker. The inspector may list overlapping candidates from that layer
only. Do not automatically cycle through lower layers. Explicit rendering order
must agree with these priorities, including outlines and selection highlights;
a selected lower-layer object must not be visually raised above a covering layer.

Select/Move selects on click and, once the drag threshold is crossed, moves the
same selected node/handle if editing is permitted. An inactive-layer object can
be inspected but not moved; it still blocks click-through to an active object
underneath. Explain its read-only status and allow an explicit Set Active Layer
action. Do not activate it automatically. Dragging an edge body does not translate
its route; use its shape handles to edit it. Selecting a different object or
reordering layers does not start a move until a new deliberate gesture.

Apply the same top-layer object-hit rule when Add Edge chooses endpoints. An
ineligible upper-layer hit must not silently pick an obscured lower endpoint or
be reinterpreted as an empty-surface waypoint click. Selecting an edge reveals
its true endpoints subject to layer visibility, viewport clipping and stack
occlusion. Same-layer parallel/coincident edges remain individually inspectable
through the overlap list; cosmetic separation remains deferred.

All commands are available through **View**, using submenus to contain growth:

- **View → Graph Tools:** Graph-Building Mode (B), tool selection, cancel,
  inspect, delete, undo/redo,
  Edge Properties…, edge direction and shape commands.
- **View → Graph Display:** show graph, pin/unpin, reveal hidden neighbors,
  decluttering, basemap dimming, layer list and inspector visibility.
- **File:** New / Open / Save / Save As Graph Project (moved from View on 2026-10-08).
- **View → Graph Layers:** layer management (formerly View → Graph Project).

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

1. **Coordinate picking and projection.** Accepted convention: one fixed logical
   display sphere with radius `R_display = 1.0001`, matching the current detail
   surface. Intersect the pointer ray with this analytical sphere, choose the
   nearest forward hit, normalize its direction, and derive geographic coordinates.
   Render node anchors, edge controls and placement ghosts by mapping those same
   coordinates back onto the same sphere. Use it even when detail imagery is
   absent; never pick the replaceable tile triangles. Geographic storage remains
   longitude/latitude with no implied elevation. Share one transform adapter for
   Qt logical pixels, render-window physical pixels and VTK's vertical origin.
   Verify click → geographic coordinate → displayed anchor within one logical
   pixel at valid surface hits, including near the horizon and closest zoom.
2. **Surface visibility.** Current graticule radius is `1.00012` and minimum camera
   distance `1.0002`. Keep graph anchors on `R_display`; test depth bias or explicit
   overlay draw ordering for graph/grid/imagery rather than moving anchors to a
   different radius to resolve depth conflicts. Screen-aligned glyph footprints
   do not change their geographic anchors. Any overlay rendering still needs
   explicit sphere-horizon culling/clipping, including visible middles of edges
   whose endpoints are off-screen. Use the same reference sphere for geometric
   visibility; a missed/tangent ray does not fabricate an off-surface location.
   The coarse fallback and reference sphere may differ slightly at the silhouette;
   test this and adapt fallback rendering if visible, keeping the logical sphere
   independent of tile availability. Phase 0 must validate the rendering method.
   For movement, apply the same picker and preserve the pointer-to-anchor grab
   offset so clicking a generous hit target does not make the node jump. A newly
   placed ghost is centered on the hit; dragging is a separate deliberate edit.
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
the owning layer**, then stable ID. Parallel edges count once for this proposed
measure; direction is ignored for display ranking. Shape waypoints never count.
This chooses one precise meaning of “most-connected”; directed in/out degree and
multilayer scope can be later configurable alternatives. Rank visible layers
within their own scope, then allocate from **one shared viewport budget**, never
one full budget per layer. Proposed allocation for experiments: reserve priority
slots for selection/pins, then share remaining slots round-robin across nonempty
visible-layer candidate lists per screen region, ordered by stable layer ID;
redistribute unused slots. Active-layer status alone does not grant a separate
budget. This fairness rule is a candidate for testing, not an approved user rule.
A selected edge reveals its actual endpoints within the visible viewport; it
never draws through the globe or moves the camera implicitly.

Ordinary edges are solid with a contrasting halo and direction arrows where
applicable. Initially show them only when their endpoints survive density
filtering. This differs from viewport clipping: endpoints outside the viewport
need not be drawn for a connecting edge segment inside it to remain visible.
Keep edge candidate culling independent of the list of on-screen node glyphs. A retained
node gets a badge counting incident edge IDs omitted specifically by density
suppression, with a reveal command. Off-screen/horizon clipping and explicit
layer hiding do not contribute to that badge; it is not a route count.
Hiding a layer remains explicit and distinct
from automatic decluttering. Reveal overrides density suppression, not the
user's layer visibility without an explicit action.

**Temporary reveal** means inspecting information hidden only by automatic
zoom/density filtering. Example: a retained hub shows “3 hidden edges”; Reveal
Hidden Neighbors exposes those original incident edges and their real neighbor
nodes without changing topology or saved visibility settings. Accepted lifetime:
keep this override while its source remains selected, including during pan/zoom;
clear it on selection change, source-layer hiding, project change, or Clear Reveal.
It is session-only and available while viewing, like a selection highlight.
Persistent Pin is different: it is a saved, undoable display edit requiring build
mode. A large reveal still obeys resource limits; list all members in the inspector
and visibly indicate any rendering capacity limit instead of claiming every member
is drawn. Selection priority does not override explicit hidden-layer state.

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
attribute definitions, naming counters and user display preferences. Defer camera
bookmarks; navigation is session state. Do not embed imagery, tile caches, active
editing target, transient selection/reveal, VTK objects or live tool drafts.
A project must open with the bundled overview
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

Use **one chronological document undo/redo history** for graph/object edits and
persisted display edits, including layer visibility/styles/order and pins. There are
not separate user-facing graph and display undo stacks. The analytical/display
split is a data-model distinction, not an exception to saving or undo support.
For example, move node → hide layer → undo shows the layer; the next undo restores
the node position. Layer display changes mark the document unsaved just like
geometry changes. A successful save establishes the saved history position;
undo/redo back to that document state clears the unsaved indication. If history
truncation removes that position, remain conservatively dirty until another save
unless equality with saved persisted content is independently established.

A drag previews without changing persistent state, then creates one command on
release. Cascaded node/edge deletion and confirmed whole-layer deletion each form
one command. Undo/redo restores original IDs, names, attributes, shape, references
and persisted display state. Enforce building mode for history replay. Camera
movement, active-target changes, hover, temporary reveal and imagery tile updates
are session operations: neither dirty the document nor enter its undo stack.

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
| 3. Shapes, properties and layers | Waypoint editing, direction/parallel-edge inspection, length/weight properties, layer stack management and typed attributes | Bent edges retain endpoint links; length dependencies are explicit; top-layer selection and layer isolation verified; all actions in View |
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
  node move affects only incident geometry; shape points do not change adjacency;
  layer deletion/undo restores all owned objects and display records, including
  last-layer deletion and hidden-layer history replay; ordered layer IDs survive
  save/load/reorder/undo with no duplicates or omissions; parallel edges retain
  distinct identity even with identical endpoints and shape.
- **Geometry:** pick/project round trips at cardinal locations, both sides of the
  dateline, near poles, viewport edges and multiple device-pixel ratios; sky miss,
  tangent ray, coincident endpoints and antipodal guard; horizon clipping and
  near-surface visibility with/without detail tiles; length depends on stored
  short-arc paths, not rendering tessellation or the display-sphere offset.
- **Interaction:** B toggle/held-key behavior and View check-state parity; B in
  text fields; right click versus right drag; arrows in both modes; no left-drag
  navigation; hover ghosts without held buttons, release-only placement and
  invalid-position rejection; all mutation paths disabled while viewing; nullable
  active target and hide-active cancellation; edge draft preservation and cancellation
  on mode switch; focus loss, inspector shortcut isolation, context-menu parity, overlap
  selection, deletion cascade/undo, and selected-edge endpoint reveal; top-layer
  precedence before object type; inactive top-layer objects block direct edits
  and click-through; no hit in an upper layer allows a lower-layer hit; same-layer
  parallel-edge overlap selection; rendering and hit order agree after reordering.
- **Weight properties:** Unassigned/Manual/Route length modes; changing geometry
  updates only dependent length/weight; camera, decluttering, highlights and tile
  changes affect neither; zero versus unassigned, explicit units/scale, numeric
  overflow, mode switching and undo/save/load consistency. General routing and
  hazard evaluation remain unimplemented.
- **Persistence:** valid round trips; malformed/oversized documents; duplicate IDs,
  dangling references and unsupported versions; failed-save preservation; missing
  optional imagery; unsaved-change cancellation; mixed graph/display command
  ordering and saved-state tracking. Include a schema fixture so later
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
3. Final screen-space area, symbol sizes, connectivity measure and viewport-budget
   allocation; choose from display experiments. Reveal lifetime is settled: until
   selection changes or an explicit clearing event. Preserve access to low-degree
   nodes without overriding hidden-layer or top-layer picking rules.
4. Score domains, tag matching, multiplier overlap and spatial hazard influence;
   resolve in a separate hazard-model plan before evaluation/pathfinding.

The completion criterion for this plan's implementation is a responsive, reversible,
persistent basic graph editor on the tiled globe, with inspectable topology and
clear boundaries around analytical features still to come.
