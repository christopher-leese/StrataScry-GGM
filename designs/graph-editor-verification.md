# Graph editor verification — version 0.4

September 28, 2026. Development host: Apple M3, 8 GiB RAM, macOS 14.5,
Python 3.14.2; existing project PySide6/PyVista/VTK/Rasterio environment.
Related: [implementation](graph-editor-implementation.md),
[requirements and plan](nodes-and-edges-plan.md).

## Executed checks

`STRATASCRY_GUI_TESTS=1 .venv/bin/python -m pytest -q` completed with
**89 passed in 18.66 seconds**. The 440 warnings originate from upstream
Rasterio/affine and VTK/NumPy deprecations. This includes the previous 61 checks
and 28 new model/geometry/persistence/GUI cases.

New evidence covers:

- Auto/custom names, layer rename and allocation after branched undo; cycles and
  distinct parallel edges; adjacency independent of shape controls; cascade
  deletion/restoration of nodes and entire layers, including the final layer.
- Manual versus length-derived weights after geographic edits and undo; invalid
  endpoints, cross-layer connections, self-loops and numerical overflow rejected.
- Versioned round trips and failure injection into atomic replacement: the old
  file survives and the edited document stays unsaved. Invalid versions, duplicate
  object IDs, references, counters, order and nonfinite coordinates are rejected.
- Coordinate projection/picking round trips at global/near-surface scales,
  antimeridian and polar viewpoints, and multiple logical viewport sizes; sky
  misses; horizon clipping when both endpoints are hidden but an arc middle is
  visible; geographic distance across the dateline.
- Qt event dispatch for hover ghosts, click-versus-drag placement, attached-edge
  node movement and one-command undo; read-only action gates and inspector fields;
  typing B in a name without toggling modes; B on the globe toggles building.
- Upper-layer edges block lower-layer nodes, same-layer parallel edges remain
  selectable in the candidate list, hidden layers stop blocking, and inactive
  objects cannot move. Layer hide/undo leaves an optional active target.
- Actual property edits, local project save and asynchronous open; dimming,
  decluttering, zoom and camera updates leave analytical weights and edge records
  unchanged. The original native View/context parity and globe/raster tests pass.

Cocoa's `QTest.mouseMove` cursor warp did not reliably deliver a no-button hover
in this environment. The hover regression dispatches a real Qt mouse-move event
to the widget; this verifies handler behavior, while native interaction is checked
separately. No test result is claimed to establish arbitrary-hardware performance,
long-duration stability, ellipsoidal accuracy or analytical routing correctness.

## Performance method

The reproducible harness is `src/tests/graph_benchmark.py`. It uses a seeded
1,000-node / 5,000-edge / 10,000-waypoint scene around 90°W, 25°N, with graph
endpoints intentionally spread through a dense area rather than an ideal road
layout. It exercises global, regional and close views, keeps navigation centered
on the graph, periodically selects nodes and performs committed drag edits, and
runs a separate 16 ms event-loop heartbeat for 60 seconds. Local full-resolution
Blue Marble imagery is enabled. System file caches are warm; geometry detail
levels may be generated for the first time during view transitions.

Reproduce from the repository:

```sh
.venv/bin/python src/tests/graph_benchmark.py --seconds 60 --output /tmp/stratascry-graph-benchmark
```

The timer callback reports input/edit work; overlay rebuild time is measured
separately. Neither is input-to-photon latency or a guaranteed frame rate.
Resident memory includes Qt, VTK, image caches and the harness; GPU memory is not
independently measured. The 10,000-node / 50,000-edge stress option identifies
limits rather than promising that size as an interactive supported capacity.

During optimization, the first dense run painted a compound ellipse path in
roughly 115 ms per overlay frame. Independent glyph drawing in the same painter
pass reduced that measurement to about 18 ms. Vectorized edge hit testing and
screen-density filtering reduced the corresponding overlay rebuild from roughly
64 ms to 12 ms in those diagnostic views. These are development observations;
the final reproducible run below is the acceptance evidence.

## Measured results

| Measure | Acceptance scene, 60 s | Stress scene, 12 s |
|---|---:|---:|
| Nodes / edges / shape controls | 1,000 / 5,000 / 10,000 | 10,000 / 50,000 / 100,000 |
| Input/edit callback p95 | 0.55 ms | 0.59 ms |
| Overlay rebuild p95 | 15.78 ms | 93.87 ms |
| Heartbeat p95 | 32.14 ms | 109.06 ms |
| Maximum heartbeat interval | 218.33 ms | 1989.25 ms |
| First geometry preparation | 208.26 ms | 1953.17 ms |
| Peak process RSS | 461.2 MiB | 542.0 MiB |
| Final edge geometry cache | 1.23 MiB | 12.03 MiB |
| Final tile cache | 5.25 MiB | 5.25 MiB |

The editing viewport was **811 × 662 logical pixels at 2× device scale** after
opening the layer panel. This is smaller than the earlier map-only benchmark;
it is not an equal-viewport performance comparison. The final acceptance frame
retained 56 node glyphs and 137 edges; final stress retained 285 and 130, with its
geometry-capacity notice active. Counts change by view and filtering. No graph
objects were removed to attain those display counts.

The acceptance run's steady update/heartbeat percentiles and process-memory target
were met at this viewport. Maximum heartbeat was 218 ms, above the nominal 200 ms
threshold, during first generation of geometry at a new detail level; the roughly
205 ms maximum overlay rebuild identifies that remaining source of latency.
This release does not claim every interaction remains below 200 ms.

The stress scene **does not meet the responsiveness target**: first geometry work
and a detail-level change took approximately two seconds, and heartbeat p95 was
109 ms. The supported performance evidence is therefore the 1,000-node/5,000-edge
acceptance scene, not the larger input capacity. A future larger-scene increment
needs incremental/background geometry preparation and more selective geographic
candidate indexing. Input/geometry budgets remain enforced, and graph data stays
intact when the display reports capacity limits.

## Remaining limitations

- Initial geometry and zoom-detail changes can pause the UI; long-duration leak
  behavior and performance on other machines or much larger viewports are unverified.
- No out-of-core graph database, routing engine, hazard evaluation, template editor,
  shared topology across layers, self-loop editor or cosmetic parallel-edge offsets.
- Attribute and definition editing uses validated JSON; a dedicated field-form
  authoring UI is not part of this iteration.
- Edge display budgets can omit edges; hidden-adjacency indicators and selection
  overrides aid inspection, but the display is not a complete analytical view at
  every zoom. There are no aggregate substitute edges or weights.

## Native UI and packaging

The running macOS app was checked through its native View menu and actual
keyboard/pointer input: read-only properties, Command +/- zoom, B mode switching,
explicit layer activation, Add Node, click placement (3 → 4 nodes), Command Z
(4 → 3), Command S, and B returning to read-only controls. Two distinct waypoint
routes between the same endpoints and the directed-edge arrow were visually
inspected. Edge Properties showed the selected route's spherical length and its
length-derived weight. A checkable-action callback mismatch found during this
check was fixed and covered by the new shared-action regression.

Version 0.4 builds as a source distribution and wheel. Artifact inspection checks
the graph modules, bundled overview and source-distribution docs/tests; the large
local Blue Marble TIFF is excluded. Runtime dependencies are unchanged. A small
fictional example project is bundled as `assets/example-graph.ssg.json`; it makes
no claim about real facilities or roads.

## Drag redraw regression fix

The reported duplicate graph images were retained overlay pixels: geometry lists
are rebuilt per frame, but the transparent widget previously painted over its old
contents. A retained-QImage regression failed before the fix for both no dimming
and 30% dimming, then passed after explicit transparent replacement at the start
of `GraphOverlay.paintEvent`.

The project regression dispatches right-button drag events through `GlobeView`,
repeatedly renders the overlay into the same device-scaled image, and compares
all color/alpha bytes with a freshly rendered frame. It also checks the requested
dimming alpha, an idle repaint, hiding the layer, a changed camera longitude, and
an unchanged document after navigation. A fresh `QWidget.grab()` alone would not
exercise retained pixels and therefore would miss this failure mode. Both dimming
cases pass as part of the 89-test suite above. A separate sample-window harness
also completed 20 synthetic drag frames with 3 nodes and 4 edges unchanged.

The automated checks validate Qt event handling and retained-surface painting;
they do not constitute a physical mouse-drag or GPU compositor capture. The
already-running user window must be restarted to load the changed paint handler.

## Hotbar follow-up

The [hotbar design and verification](graph-hotbar.md) records three additional
GUI regressions, icon/menu rendering and overflow inspection, and packaged SVG
checks. The complete suite after this addition passed **92 tests in 17.47 seconds**.
