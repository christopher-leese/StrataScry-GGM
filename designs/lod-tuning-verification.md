# Display LOD tuning — verification record

Related: [plan](lod-tuning-plan.md), [graph editor verification](graph-editor-verification.md).
Development host: Apple M3, 8 GiB RAM, macOS 14.5, Python 3.14.2. Window viewport
1180 × 599 logical pixels for the display metrics. This record grows phase by
phase; each section states what was executed.

## Phase 0 baseline (October 8, 2026, version 0.4.0 behavior)

### Executed checks

- `STRATASCRY_GUI_TESTS=1 .venv/bin/python -m pytest -q`: **134 passed**, including
  41 new checks in `src/tests/test_lod_scenes.py` (scene structure and seeding for
  all five scenes; badge exactness and 24-pixel spacing, selection/reveal visibility
  at global, regional and close views; analytical fingerprint unchanged across
  pan, zoom, declutter, dim and reveal).
- Display metrics: `src/tests/lod_baseline.py` at ×1 and ×10 (no timing; fixed
  10-pixel pan steps).
- Timing: `src/tests/graph_benchmark.py --scene <name>` for the original benchmark
  scene and the five LOD scenes, 60 s at ×1 and 20 s at ×10, local full-resolution
  Blue Marble enabled. The renderer now records per-stage rebuild timings; this
  instrumentation does not change display behavior.

### What the declutter shows (×1)

These figures used scene IDs that were still random per run; IDs are the final
ranking tie-breaker, so a few counts vary slightly between runs. Phase 1 seeds the
IDs and records reproducible figures.

| Scene | View | On screen | Shown nodes | Shown edges | Notes |
|---|---|---:|---:|---:|---|
| Dense hub | regional | 671 | 470 | 946 | Hub retained |
| Sparse chain | regional | 260 | 43 | 1 | Path edges drawn 0 / 259 |
| Sparse chain | close | 24 | 26 | 27 | Path edges drawn 23 / 23 |
| Low-degree bridge | global | 1,000 | 2 | 0 | Bridge nodes shown 0 / 6 |
| Low-degree bridge | regional | 1,000 | 120 | 21 | Bridge nodes 6 / 6; path edges 5 / 7 |
| Overlapping layers | regional | 1,200 | 177 | 101 | |
| Mixed directions | regional | 500 | 169 | 243 | |

At global view every scene collapses to one or two nodes, as expected for scenes a
few degrees across. At ×10 density the sparse chain draws **no edges at any view**,
including close (28 of 244 on-screen nodes shown), because an edge is drawn only
when both endpoints survive suppression.

Churn per 10-pixel pan step is already low: median 0 in every scene and view; the
maximum is 5.6% (bridge ×10 regional) apart from views with only one or two shown
nodes, where a single swap reads as 100%.

### Timing (p95 unless noted)

| Scene | Size | Overlay rebuild | Heartbeat | Max pause | First geometry | Rank stage | Edge stage | Geometry stage | Paint |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Original benchmark | ×1 | 15.2 ms | 33.7 ms | 224 ms | 240 ms | 6.3 | 6.6 | 0.1 | 8.1 |
| Dense hub | ×1 | 11.6 | 28.6 | 93 | 58 | 4.4 | 3.7 | 0.1 | 8.0 |
| Sparse chain | ×1 | 2.0 | 19.1 | 76 | 12 | 0.9 | 0.5 | 0.1 | 1.9 |
| Low-degree bridge | ×1 | 6.7 | 20.1 | 124 | 127 | 3.2 | 2.2 | 0.1 | 1.3 |
| Overlapping layers | ×1 | 10.7 | 26.5 | 79 | 78 | 6.8 | 1.4 | 0.1 | 3.4 |
| Mixed directions | ×1 | 7.4 | 30.4 | 81 | 49 | 2.7 | 1.5 | 0.1 | 9.3 |
| Original benchmark | ×10 | 91.8 | 104.8 | 1,964 | 1,936 | 69.0 | 15.9 | 34.8 | 12.3 |
| Dense hub | ×10 | 62.9 | 75.3 | 565 | 556 | 45.8 | 10.7 | 3.7 | 12.8 |
| Sparse chain | ×10 | 10.7 | 23.3 | 108 | 101 | 7.8 | 1.7 | 0.1 | 1.7 |
| Low-degree bridge | ×10 | 66.9 | 61.8 | 1,277 | 1,215 | 36.0 | 19.1 | 50.5 | 2.7 |
| Overlapping layers | ×10 | 101.2 | 108.5 | 749 | 750 | 82.7 | 12.8 | 19.8 | 8.0 |
| Mixed directions | ×10 | 47.7 | 58.8 | 474 | 463 | 33.9 | 12.3 | 10.8 | 12.3 |

Stage columns are milliseconds. Peak process RSS stayed between 522 and 617 MiB.

### Baseline conclusions

- All ×1 scenes meet the steady-state gates (rebuild p95 ≤ 16 ms, heartbeat p95
  < 50 ms). The original benchmark scene still has one first-geometry pause above
  200 ms (224 ms), so the "no unexplained pause over 200 ms" gate is not yet met.
- At ×10, the **ranking stage dominates** (34–83 ms p95): the per-node Python sort
  and spacing loop. Bounded-staleness ranking during drag-navigation and a
  vectorized spacing pass target this directly.
- **First geometry** for a new detail level is the cause of the long pauses
  (0.5–1.9 s at ×10). Background preparation targets this.
- Painting is not the bottleneck (≤ 13 ms p95).
- Display issue for review: chains of low-degree nodes lose their edges entirely
  once neighbors are suppressed (see the sparse chain rows).

## Phase 1: performance (October 9, 2026)

### Changes

- **Batch tessellation** (`graph/geometry.py: tessellate_many`): all uncached edges
  for a detail level are sampled in one vectorized pass. Output is identical to the
  per-edge `tessellate` (checked at all seven detail levels on 2,000 random routes,
  including zero-length and near-dateline routes). On the ×10 bridge scene, edge
  sampling dropped from about 1,060 ms to 46 ms per detail level.
- **Vectorized ranking and edge budget** (`graph/renderer.py`): node ordering uses
  NumPy sorts over precomputed degree, ID-rank and layer arrays; the 24-pixel
  spacing test uses plain float arithmetic in a 24-pixel grid; edge eligibility
  and the drawn-segment mask are array operations.
- **Bounded-staleness ranking**: scheduled camera updates reproject the last ranked
  display and re-rank at most every `RANK_REFRESH_S` (0.1 s), and again 120 ms
  (`SETTLE_MS`) after motion stops. Any change to the document, selection, reveal,
  pins, decluttering, layer order or viewport size re-ranks immediately. Explicit
  `rebuild()` calls always re-rank, so tests and tools stay exact.
- **Seeded scene IDs** in `lod_scenes.py` so display results are reproducible.

### Executed checks

- Display equivalence: `lod_baseline.py` on all five scenes, three views and 30 pan
  steps gives **identical** results with the phase 0 renderer and the phase 1
  renderer (same seeded scenes, same session). The optimization does not change
  what is shown.
- Tests: graph, geometry and LOD-scene tests **84 passed, 1 failed**. The failure,
  `test_viewing_blocks_commands_and_text_b_does_not_toggle`, and
  `test_gui.py::test_keyboard_shortcuts_and_mouse_navigation` both depend on the test
  window receiving keyboard focus. Both fail identically on the unchanged phase 0
  code in the same session (the Mac was idle with another app in front), so they are
  environmental here; they passed in the phase 0 session.

### Timing, same-session comparison

Measured back to back on the same machine state. The desktop was idle during this
session, which slowed painting for every run (old and new alike), so absolute ×1
numbers are not comparable with the phase 0 table; the old/new pair is.

| Original benchmark scene | Size | Overlay rebuild p95 | Heartbeat p95 | Max pause | First geometry | Rank stage p95 |
|---|---|---:|---:|---:|---:|---:|
| Phase 0 code | ×10 | 91.3 ms | 102.9 ms | 1,930 ms | 1,775 ms | 68.2 |
| Phase 1 code | ×10 | 30.4 | 40.5 | 214 | 174 | 7.7 |
| Phase 0 code | ×1 | 73.5 | 116.9 | 1,369 | 198 | 18.7 |
| Phase 1 code | ×1 | 49.6 | 107.3 | 760 | 23 | 5.8 |

Phase 1, ×10 stress variants of the LOD scenes (20 s):

| Scene | Overlay rebuild p95 | Heartbeat p95 | Max pause | First geometry |
|---|---:|---:|---:|---:|
| Dense hub | 39.2 ms | 33.9 ms | 158 ms | 73 ms |
| Sparse chain | 7.6 | 17.6 | 75 | 16 |
| Low-degree bridge | 26.6 | 26.3 | 182 | 154 |
| Overlapping layers | 28.7 | 37.1 | 129 | 105 |
| Mixed directions | 19.4 | 33.2 | 101 | 60 |

### Phase 1 conclusions

- Stress scenes now stay under the 50 ms heartbeat target and mostly under the
  200 ms pause limit (original benchmark ×10: 214 ms worst case, down from 1.9 s).
  They were documented-only targets; these results exceed them.
- Ranking is no longer the bottleneck (rank stage p95 ≤ 11 ms at ×10).
- The ×1 runs in the idle session were dominated by slow painting in both old and
  new code; they were re-measured with an active desktop below.

### Acceptance re-measurement, active desktop (October 9, 2026)

`STRATASCRY_GUI_TESTS=1 .venv/bin/python -m pytest -q`: **134 passed**, including both
keyboard-focus tests. Timing at ×1, 60 s per scene, old and new code back to back:

| Scene | Code | Overlay rebuild p95 | Heartbeat p95 | Max pause | First geometry | Rank stage p95 |
|---|---|---:|---:|---:|---:|---:|
| Original benchmark | Phase 0 | 14.8 ms | 33.1 ms | 209 ms | 215 ms | 6.1 |
| Original benchmark | Phase 1 | 8.8 | 27.5 | 108 | 43 | 1.0 |
| Dense hub | Phase 1 | 6.6 | 25.7 | 88 | 8 | 1.2 |
| Sparse chain | Phase 1 | 1.5 | 18.7 | 67 | 16 | 0.4 |
| Low-degree bridge | Phase 1 | 4.1 | 19.8 | 93 | 14 | 1.2 |
| Overlapping layers | Phase 1 | 4.6 | 19.5 | 92 | 24 | 1.5 |
| Mixed directions | Phase 1 | 5.1 | 29.8 | 91 | 12 | 0.7 |

**All acceptance gates are now met**: rebuild p95 ≤ 16 ms, heartbeat p95 < 50 ms, and
no pause over 200 ms in any scene (the phase 0 code still pauses 209 ms on the
original scene). Peak RSS 522–537 MiB.

### Seeded display figures (×1, identical for phase 0 and phase 1 renderers)

| Scene | View | On screen | Shown nodes | Shown edges | Notes |
|---|---|---:|---:|---:|---|
| Dense hub | regional | 671 | 470 | 946 | Hub retained |
| Sparse chain | regional | 260 | 43 | 0 | Path edges drawn 0 / 259 |
| Sparse chain | close | 24 | 26 | 27 | Path edges drawn 23 / 23 |
| Low-degree bridge | global | 1,000 | 2 | 0 | Bridge nodes shown 0 / 6 |
| Low-degree bridge | regional | 1,000 | 119 | 28 | Bridge nodes 6 / 6; path edges 5 / 7 |
| Overlapping layers | regional | 1,200 | 178 | 105 | |
| Mixed directions | regional | 500 | 172 | 255 | |
