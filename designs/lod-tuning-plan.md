# Display LOD tuning and performance — implementation plan

Date: October 8, 2026  
Status: approved for implementation October 8, 2026 (see "Review decisions").
No code has been changed for this plan.  
Baseline: version 0.4.0 graph editor.  
Related: [LOD notes](graph-display-lod-notes.md),
[graph editor implementation](graph-editor-implementation.md#display-and-optimization),
[graph editor verification](graph-editor-verification.md),
[importance attribute notes](importance-attribute-notes.md) (part B, not in scope).

## Objective and scope

Turn the version 0.4 decluttering from a working default into measured, tuned
behavior. This increment:

1. builds the five evaluation scenes proposed in the LOD notes as reusable,
   seeded fixtures;
2. extends the benchmark so every scene is measured the same way, with per-stage
   timings, and investigates the reported "slight lag after panning";
3. adds real hysteresis so panning does not reshuffle which nodes are shown;
4. ranks edges for the display budget instead of keeping them by ID order;
5. settles node symbol size, edge width and suppression distance from a
   parameter sweep across the scenes.

Out of scope: edge or chain summaries, cluster bundles, the importance attribute
(part B), pathfinding, and any change to stored graph data. Display changes must
continue to leave topology, attributes and weights untouched.

## What exists today (version 0.4)

Measured facts are from [graph-editor-verification.md](graph-editor-verification.md);
code references are to `src/stratascry/graph/renderer.py`.

- Node ranking: pins and selection first, then unique-neighbor degree within the
  layer, then "was visible last frame", then ID. Layers share a 1,200-node
  allowance round-robin.
- Suppression: a node is hidden if a higher-ranked accepted node is within
  24 logical pixels; neighbor lookup uses 40-pixel cells.
- Edges: shown only when both endpoints survive; a 1,200-edge cap and, with
  decluttering on, an "ink" budget of 0.12 × viewport area. Within that budget,
  edges are taken in **ID order**, so which edges survive is arbitrary.
- Glyphs: 10-pixel nodes, 2-pixel edges with a 5-pixel halo. These sizes were
  chosen, not tuned.
- Performance: the 1,000-node / 5,000-edge acceptance scene met its steady-state
  targets except one 218 ms first-geometry pause. The 10,000 / 50,000 stress scene
  missed them (overlay rebuild p95 94 ms, ~2 s first geometry).
- Every rebuild loops in Python over all nodes (projection dictionary, candidate
  list, ranking sort) and all edges (eligibility set), and creates one `QLineF`
  per visible segment. These are the first profiling suspects for panning lag;
  this is an inference from reading the code, not yet a measurement.

## Requirements → functions → components → implementation

| ID | Requirement | Function | Component | Implementation / verification |
|---|---|---|---|---|
| LT-01 | Five reproducible evaluation scenes | Seeded scene generators with known structure | Test fixtures | New `src/tests/lod_scenes.py`; each scene also exportable as `.ssg.json` for hands-on review |
| LT-02 | Decluttering never hides what the analyst is working on | Check selection, reveal, path visibility per scene | Display-semantics tests | New `src/tests/test_lod_scenes.py`; GUI opt-in where a window is needed |
| LT-03 | Display operations never change the analytical graph | Fingerprint topology, attributes and weights before/after | Model + tests | Hash check across scripted pan/zoom/declutter/dim runs on every scene |
| LT-04 | Shown nodes stay stable while panning | Hysteresis for incumbents; churn metric | Renderer ranking | Churn measured per scripted pan step; target in "Proposed gates" |
| LT-05 | Important edges survive the edge budget | Rank edges by endpoint rank, then length, then ID | Renderer edge selection | Deterministic ranking; test that a bridge edge between two kept hubs is shown |
| LT-06 | Measure every scene the same way | Benchmark `--scene` option, per-stage timers | `graph_benchmark.py` | JSON metrics per scene and stage; results in the verification record |
| LT-07 | Reduce lag after panning | Profile, then remove per-frame Python loops and first-use spikes | Renderer + geometry cache | Before/after stage timings on the acceptance and stress scenes |
| LT-08 | Tuned glyph and suppression sizes | Parameter sweep across scenes | Renderer constants | Chosen values recorded with the sweep results; constants named in one place |
| LT-09 | Inspectable evidence | Verification record | Docs | New `designs/lod-tuning-verification.md` |

## The five evaluation scenes (LT-01)

All scenes are seeded, placed over open ocean near 90°W 25°N like the existing
benchmark, and built through the public model so they validate like real projects.
Sizes below are proposals; each scene also has a ×10 stress variant.

| Scene | Structure | Approx. size | What it tests |
|---|---|---|---|
| Dense hub | One node linked to 200 nearby leaves, plus a background grid | 1,000 nodes / 2,000 edges | Hub stays visible; leaves declutter; badge counts are exact; reveal restores all leaves |
| Sparse chain | A long path of degree-2 nodes crossing several hundred km | 300 nodes / 299 edges | Chain stays readable when zoomed out; no gaps that look like breaks; hidden-adjacency badges at chain cuts |
| Low-degree bridge | Two dense regions joined by a single degree-2 bridge path | 1,000 nodes / 4,000 edges | Documents today's failure (bridge hidden by degree ranking) as a baseline for part B; selection and reveal still reach it |
| Overlapping layers | Three layers sharing the same area with offset copies of a network | 3 × 400 nodes | Round-robin allowance fairness; top-layer picking; hidden layers excluded from competition |
| Mixed directions | Directed cycles, parallel edges with opposite directions, undirected edges | 500 nodes / 1,500 edges | Arrows remain correct and unambiguous; parallel edges stay selectable via the overlap list |

## Display-semantics checks (LT-02, LT-03)

Run on every scene at global, regional and close views:

- The selected node or edge, and both endpoints of a selected edge, are always drawn.
- Reveal on any node shows every incident edge and neighbor; clearing it restores
  the previous decluttered set.
- A scripted selected path (a list of edge IDs standing in for a future route
  result) is drawn completely; no suppressed node makes it look disconnected.
- A node's badge count equals the number of incident edges not drawn.
- No two drawn node glyphs overlap by more than the chosen tolerance, except
  pinned or selected ones.
- The analytical fingerprint (topology, attributes, weights) is identical before
  and after the run.

## Hysteresis (LT-04)

Today "was visible last frame" only breaks ties between equal degrees, so a small
pan can swap many winners. Proposed rule, to be tuned with the churn metric:

- **Incumbent advantage:** a node shown in the previous frame is ranked as if its
  degree were higher by a factor (candidate 1.25) when competing with a newcomer.
- **Asymmetric distance:** a newcomer is suppressed within 24 px of an accepted
  node, but an incumbent is only displaced within a smaller radius (candidate 18 px).
- **Reset on zoom-level change:** hysteresis applies to panning and small zooms;
  crossing a tessellation detail level re-ranks from scratch so the view does not
  stay stuck at a stale density.

Churn metric: for each scripted pan step, the fraction of shown nodes that change,
excluding nodes entering or leaving the viewport edge.

## Edge ranking (LT-05)

Replace ID order within the ink and count budgets with a deterministic order:
priority edges first, then the higher of the two endpoint ranks, then **longer**
on-screen length (long-haul connections win over short local edges when the
budget is tight; decided in review), then ID.

## Performance work (LT-06, LT-07)

1. **Measure first.** Add `--scene` and per-stage timers to the benchmark:
   projection, ranking/suppression, edge eligibility and budget, badges, draw-list
   build, and paint. Record baseline numbers for every scene before changing code.
2. **Candidate fixes, applied only where the profile shows cost:**
   - keep node positions and visibility in NumPy arrays instead of rebuilding a
     dictionary of all nodes every frame;
   - precompute per-edge endpoint indices so eligibility is a vector test;
   - cull candidates with a coarse geographic index before projecting;
   - build edge draw lists as arrays (`drawLines` accepts a batch) instead of one
     `QLineF` per segment;
   - during continuous drag-navigation, reuse the last ranking and only reproject,
     refreshing the full ranking on a tunable interval (about 100 ms) and when
     motion settles (bounded staleness; accepted in review);
   - prepare geometry for a new detail level in the background, showing the
     previous level until it is ready.
3. **Re-measure** each change against the baseline; keep only changes that help.

## Proposed gates

Same hardware and method as the 0.4 verification (M3 / 8 GiB, warmed 60 s run).

- Acceptance-size scenes: overlay rebuild p95 ≤ 16 ms; heartbeat p95 < 50 ms;
  no unexplained pause over 200 ms, including first use of a detail level.
- Stress variants: record results; target overlay rebuild p95 ≤ 50 ms and first
  geometry under 500 ms, but missing these does not block the increment as long
  as the limit is documented.
- Churn: at most 5% of shown nodes change per small pan step (candidate value).
- Process RSS for acceptance scenes stays below 1 GiB.

## Phases

0. Scenes, semantics checks and benchmark extensions; record the baseline.
1. Profile and fix panning lag; re-measure.
2. Hysteresis and edge ranking; measure churn and semantics.
3. Glyph size, edge width and suppression-distance sweep; pick defaults with you
   from screenshots of each scene. Node symbols scale with zoom through a single
   named, tunable size curve (minimum size, maximum size and zoom range); the
   suppression distance follows the current symbol size.
4. Write `lod-tuning-verification.md`, update the implementation doc and changelog.

## Review decisions (round 1, October 8, 2026)

1. Scenes are for verification, not validation: synthetic open-ocean scenes at the
   proposed sizes are fine.
2. Hysteresis: **accepted** as proposed (incumbent advantage, asymmetric displacement
   distance), including the full re-rank when crossing a detail level.
3. Edge ranking prefers **longer** on-screen edges when the budget is tight.
4. Bounded-staleness ranking: **accepted**. During drag-navigation, positions are
   reprojected every frame; the full ranking refreshes on a semi-regular interval
   (about 100 ms, tunable) and once motion settles, so the analyst keeps a steady
   reference while panning.
5. Proposed acceptance gates accepted; ×10 stress variants are measured and
   documented rather than gated.
6. Node symbols **scale with zoom**, controlled by one named, tunable size curve for
   UX fine-tuning.
7. **Draw real edges when endpoints are hidden** (decided after the phase 0
   baseline): an edge's true geometry is drawn, de-emphasized, even when its
   endpoint nodes are decluttered, within the edge budgets. No synthetic edges.
   Implemented in phase 2.

## Questions for review (original)

1. Scene sizes: are the proposed sizes and the open-ocean placement fine, or do
   you want scenes modeled on a real geography (still fictional data)?
2. Hysteresis numbers (1.25 rank factor, 18 px incumbent radius, 5% churn gate):
   accept as starting points to tune, or set different targets?
3. Edge ranking tie-break: prefer shorter on-screen edges (local detail) or longer
   ones (long-haul connections) when the budget is tight?
4. Is a bounded-staleness ranking during drag-navigation acceptable (positions stay
   exact; which nodes are shown may lag by about 100 ms)?
5. Performance gates: are the proposed acceptance and stress targets right, or
   should the stress scene become a supported size in this increment?
6. Sizing sweep: should symbol size scale with zoom, or stay fixed in screen pixels
   with only the suppression distance tuned?
