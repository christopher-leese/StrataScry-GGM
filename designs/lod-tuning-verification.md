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
