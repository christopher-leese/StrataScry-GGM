# Changelog

Notable changes to StrataScry GGM. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow the
`version` in `pyproject.toml`; while the project is a 0.x prototype, any release
may change behavior or file formats. Dates are when the version was built; entries
before 0.4.0 were reconstructed from the design and verification records in
`designs/`.

## [Unreleased]

### Added
- Five seeded LOD evaluation scenes (`src/tests/lod_scenes.py`, ×1 and ×10) with
  display-semantics and fingerprint tests (`src/tests/test_lod_scenes.py`).
- Benchmark `--scene` / `--scale` options, churn and per-stage timings; deterministic
  display metrics in `src/tests/lod_baseline.py`.
- Per-stage rebuild timing in the graph renderer (no display change).
- Phase 0 baseline in `designs/lod-tuning-verification.md`.
- `designs/lod-tuning-plan.md` (proposed) and `designs/importance-attribute-notes.md`.
- GUI test that project file commands live under File, ahead of Quit.
- This changelog, included in source distributions.

### Changed
- Faster graph display: batch edge tessellation, vectorized ranking and edge budget,
  and ranking refreshed about every 100 ms (and on settle) while the camera moves.
  What is shown is unchanged. On the 10,000-node stress scene, first geometry
  dropped from about 1.8 s to 0.17 s and redraw p95 from 91 ms to 30 ms.
- LOD evaluation scenes use seeded IDs for reproducible display results.
- Graph Project New / Open / Save / Save As moved from View to the **File** menu.
  The remaining layer commands are under **View → Graph Layers** (formerly Graph
  Project) and the context menu.
- Project description unified as "Designed for geospatial network modeling and
  route analysis" across the README, package metadata and command-line help.
- README links the graph-editor design, plan, verification and hotbar documents.
- `designs/globe-viewer.md` records right-drag rotation (GV-02), the 0.4 graph
  editor, and that 0.3 tiling superseded the single-texture imagery note.
- Design docs note why map packages were demoted, that the 0.4 editor implemented
  the decluttering candidates, the reason OSM is excluded, and the motivation for
  the hotbar and hover placement.

### Removed
- `src/.DS_Store` (macOS folder metadata) from version control; `.DS_Store` is now ignored.

## [0.4.0] - 2026-09-28

Graph editor. See [implementation](designs/graph-editor-implementation.md),
[plan](designs/nodes-and-edges-plan.md),
[verification](designs/graph-editor-verification.md) and
[hotbar](designs/graph-hotbar.md).

### Added
- `stratascry.graph` package: document model with per-layer topology, globally
  unique IDs, parallel edges, shape waypoints and a single undo/redo history
  (capped at 200 commands / 32 MiB).
- Graph-building mode (**B**) with Select / Move, Add Node (by click or by
  coordinates) and Add Edge tools; hover ghosts, drag discrimination and Escape
  to cancel drafts.
- Icon hotbar above the globe, with an overflow menu on narrow windows.
- Layer panel: activate, hide, reorder, color, pin, dim and declutter; layer
  deletion confirms and is undoable.
- Object / Edge Properties: names, coordinates, direction, typed attributes
  (validated JSON) and edge weights (Unassigned, Manual, or Route length on a
  6,371,008.8 m sphere).
- Local `.ssg.json` graph projects (format version 1) with validation, a 64 MiB
  limit, background loading and atomic saves; imagery is never embedded.
- Single transparent Qt overlay for graph drawing with viewport display budgets,
  decluttering by unique-neighbor degree, hidden-adjacency badges and temporary
  neighbor reveal.
- Example project `assets/example-graph.ssg.json` and toolbar icons.
- Graph model and GUI tests, and `src/tests/graph_benchmark.py`.

### Changed
- Globe rotation moved from left drag to **right drag**; a stationary right
  click still opens the context menu. The left button is reserved for graph tools.
- Package description now reads "A geographic graph editor on a tiled Blue Marble globe".

### Not included
- Hazard scoring, pathfinding, template authoring, cross-layer links and
  self-loop editing remain future work.

## [0.3.0] - 2026-09-20

Tiled Blue Marble. See [blue-marble-prototype.md](designs/blue-marble-prototype.md).

### Added
- Tiled NASA Blue Marble (August 2004) display: a bundled 5400 × 2700 overview
  plus on-demand local detail up to the full 86,400 × 43,200 source grid.
- View → Show Blue Marble Detail, Load Blue Marble Tiles… and Blue Marble Detail Status….
- Reproducible tile-set preparation from NASA's source JPEGs (`blue_marble/build.py`).

### Changed
- Blue Marble became the default view. The regional terrain packages from 0.2
  moved behind the `--map-packages` command-line option.

## [0.2.0] - 2026-09-20

Regional map packages (stages 0–2). See the
[plan](designs/map-packages-plan.md),
[implementation](designs/map-packages-implementation.md) and
[verification](designs/map-packages-verification.md).

### Added
- View → Map Packages: prepare packages from local NASADEM or USGS 3DEP
  elevation files, add existing packages, and fit the view to their bounds.
- Package catalog, source inspection and explicit vertical-reference declarations.

### Not included
- Stage 3 (viewport-driven local tiles and a bounded tile cache).

## [0.1.0] - 2026-09-18

Initial globe viewer. See [globe-viewer.md](designs/globe-viewer.md) and
[verification.md](designs/verification.md).

### Added
- Offline 3D globe textured with NASA Blue Marble imagery (PySide6, PyVista, VTK).
- Left-drag rotation, wheel and Command +/− zoom, Command 0 reset, arrow-key rotation.
- Native macOS View menu with a context menu that shares the same actions.
- Optional latitude / longitude grid and an Imagery Credits dialog.
