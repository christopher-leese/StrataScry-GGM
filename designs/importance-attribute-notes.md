# Importance attribute — preliminary notes (part B)

Date: October 8, 2026  
Status: notes only; not an implementation plan approved for coding.  
Related: [LOD notes](graph-display-lod-notes.md), [LOD tuning plan](lod-tuning-plan.md) (part A).

## User direction

Bridges and facilities matter in analysis even when they have few connections, so
degree alone is the wrong display priority for them. Add an analyst-set
**importance** value: an integer from 0 to 100, chosen for convenience and
intuition rather than any physical unit. How importance "collapses" for level of
detail still needs to be worked out. Part A goes first; nothing here is built yet.

## What the value means

- An ordinal display and analysis hint set by the analyst: higher means "keep this
  visible and treat it as significant". It is not a probability, a weight or a cost.
- 0–100 inclusive, integers only. The range is a convention; the code should treat
  it as ordered integers so the bounds can change later without rewriting rules.
- Applies to nodes first. Edges may get the same attribute later (a key bridge
  road), but that is a separate decision.
- It must not change topology, edge weights or future path costs unless a later
  scoring model explicitly reads it.

## Unset versus zero

Distinguish "not set" from 0, as edge weights already do (Unassigned vs zero).
Options for an unset node:

1. Treat as a neutral default (for example 50), so only deliberate choices move a
   node up or down.
2. Treat as 0, so only explicitly marked nodes get any boost.
3. Derive a suggestion from structure (see below) but display it as "suggested",
   never silently stored.

Option 1 is the least surprising for mixed projects; to be decided.

## Where it is stored

- **Built-in node field** (`importance: int | None`): simplest for ranking code
  and validation; needs a `.ssg.json` format version bump with a reader for
  version 1 files.
- **Typed attribute through project definitions:** reuses the existing attribute
  machinery and needs no format change, but ranking code would depend on an
  attribute name the analyst could rename or delete.

A built-in field looks cleaner for something the renderer depends on.

## How it combines with degree for LOD ("collapse")

Ranking today: pin/selection → degree → incumbent → ID. Candidate replacements:

| Approach | Rule | Behavior |
|---|---|---|
| Strict tier | importance, then degree | Any higher-importance node beats any lower one; simple and predictable, but a 51 always beats a busy 50 hub |
| Banded tier | importance bands (e.g. 0–24, 25–49, 50–74, 75–100), then degree within a band | Analysts control coarse priority; degree still orders similar nodes |
| Blended score | `importance + k × normalized degree` | Smooth, but `k` is a tuning constant that is hard to explain |
| Threshold by zoom | show only nodes with importance ≥ T(zoom) when zoomed out, then degree | Gives a clear "map scale" feel; needs a zoom-to-threshold table |

The banded tier is the leading candidate: it is explainable, keeps degree useful,
and the band edges can be tuned using the part A scenes. Pins and selection still
override everything.

"Collapse" questions to settle:

- When a high-importance node suppresses nearby nodes, its hidden-adjacency badge
  could show the highest importance among hidden neighbors (for example "+12 ▲80"),
  so a hidden important node is not invisible in effect.
- Future chain or cluster summaries should carry the **maximum** importance of
  their members for ranking, not an average, so one key facility keeps the summary
  visible. Summaries must still never imply new edges.
- Across layers, importance ranks within a layer; the round-robin allowance between
  layers stays as is unless layer priority is added separately.

## Structural suggestions (optional)

The renderer could offer suggestions without storing them:

- **Articulation points and bridges** (nodes or edges whose removal disconnects the
  layer) are exactly the low-degree but critical objects the user named. They can be
  found in linear time per layer.
- Betweenness centrality is a richer measure but too costly to recompute on every
  edit for large graphs; if used, run it on demand.

A suggestion would appear in the properties panel ("structural bridge — consider
importance ≥ 75"), never applied automatically.

## Editing

- Properties panel: integer field 0–100 with an "unset" state; batch-set for a
  selection later.
- Undoable like other attribute edits; marks the project unsaved.
- The part A "low-degree bridge" scene is the acceptance test: setting the bridge
  nodes to high importance must keep them visible at every zoom.

## Open questions

1. Unset default: neutral 50, zero, or structure-derived suggestion?
2. Nodes only, or nodes and edges from the start?
3. Built-in field (format version bump) or a typed attribute?
4. Banded tier, strict tier, blended score, or zoom thresholds?
5. Should future scoring or pathfinding ever read importance, or is it display-only?
