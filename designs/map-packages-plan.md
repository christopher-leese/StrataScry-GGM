# Regional map packages — preliminary implementation plan

Current prototype direction: [tiled Blue Marble](blue-marble-prototype.md). Regional terrain tools remain an opt-in experiment via `--map-packages`.

Date: September 20, 2026  
Status: stages 0–2 implemented September 20, 2026; stage 3 remains planned.
See the [implementation record](map-packages-implementation.md) and
[executed verification](map-packages-verification.md) for final choices, evidence
and deviations. The proposal below is retained as the design baseline.  
Related: [existing globe design](globe-viewer.md), [graph display discussion](graph-display-lod-notes.md).

## Purpose and confirmed scope

Improve close-up geographic context for manually authored facility nodes and
road-like edges. The Earth is a reference geometry for multilayer graphs,
pathfinding, and sensitivity analysis. Accurate road tracing, building imagery,
and automatic extraction of a real-world road network are not required.

User direction: prepare packages from NASADEM and USGS The National Map; make
package coverage visible; exclude OSM from this scope. Keep map controls in
the native macOS View menu. Continue placing code under `src` and designs here.

Map packages are visual background resources. Loading, hiding, dimming, or
switching them must not alter graph topology, coordinates, weights, layer
membership, hazard effects, pathfinding inputs, or sensitivity-analysis results.
Any future use of elevation in analysis would require its own explicit design.

## Proposed first release

- Retain Blue Marble as the global fallback.
- Add locally prepared, bounded regional terrain packages derived from either
  NASADEM or USGS 3DEP elevation rasters.
- Render subdued shaded relief as a georeferenced texture on the existing
  spherical surface. True 3D terrain displacement is outside this release.
- Allow a catalog of installed packages, with one active regional background at
  a time initially. This is a proposed simplification, not a user requirement.
- Provide coverage outlines, package details, opacity/dimming, and Zoom to Package.
- Use manually downloaded source files initially. Viewing prepared packages must
  work offline. Automated source discovery/download and credentials are deferred.
- Natural Earth may be a later global overlay; it is not a dependency of this plan.

The National Map is a collection of products, not one interchangeable basemap.
The first USGS adapter targets **3DEP DEMs**, initially the 1/3 arc-second
GeoTIFF product where available. Roads, hydrography, topographic map PDFs,
lidar point clouds, and imagery are not automatically included. Additional
National Map reference layers would be separate extensions.

## Data sources and scope of evidence

| Source | Initial input | Role and constraints |
|---|---|---|
| NASADEM HGT V001 | Official elevation HGT files and their metadata, commonly distributed in source archives | Approximately 1 arc-second / 30 m sampling; land coverage 56°S–60°N. Use the elevation band/product, not similarly named quality or image-mosaic products. |
| USGS 3DEP via The National Map | Georeferenced elevation GeoTIFF plus supplied metadata | U.S. regional alternative; initially support 1/3 arc-second products where available. Coverage and native CRS must be read from each product. Other resolutions are later candidates. |

Sampling interval is not guaranteed accuracy. Package details must distinguish
acquisition dates, release/update dates, source sampling, and the resolution
of the prepared display texture. Preserve horizontal CRS, elevation units,
and vertical reference from the source; do not guess them from a filename.
HGT georeferencing does depend on the geographic tile naming convention, so
preserve the original filename and validate it with a geospatial reader.

NASA's dataset record reports its coverage and sampling and says it is openly
shared without restriction [S1]. The National Map's terms identify downloaded
data and map services as public domain and request acknowledgment [S3]. Keep
product provenance and attribution in each package; code licensing and data
provenance are separate. No source tiles or credentials are acquired by this
planning task. NASA download access may require an Earthdata login; source
retrieval remains external to the application in the first release.

## Requirements and design allocation

| ID | Requirement | Proposed component | Acceptance evidence |
|---|---|---|---|
| MP-01 | Prepare a local package from each selected source | Source adapters + builder | One representative NASADEM and one 3DEP import succeed |
| MP-02 | Align regional backgrounds to geographic coordinates | Raster preparation + globe patch renderer | Synthetic corner/orientation tests and reference-point checks |
| MP-03 | Clearly identify where regional data is available | Coverage geometry + catalog + View actions | Outline, no-data gaps, active state, and fallback inspected |
| MP-04 | Display a prepared package offline | Local package loader | Open and navigate with network unavailable |
| MP-05 | Bound resource use and keep navigation responsive | Preparation limits; background loading; later tile cache | Measure frame times, memory, and cancellation on target Mac |
| MP-06 | Keep map appearance independent of graph analysis | Separate map and graph models | When analysis exists, changing map settings leaves its input fingerprint and results unchanged |
| MP-07 | Preserve source identity and processing choices | Versioned manifest and provenance files | Source IDs, checksums, CRS, dates, and build settings survive relocation |
| MP-08 | Keep all map interactions under View | Shared QAction registry | Native menu and context-menu parity checks |

MP-06 is an architectural invariant now; its end-to-end analysis test must wait
for an actual graph/analysis implementation.

## Package contents and storage

Proposed portable package: a directory containing `manifest.json`,
`coverage.geojson`, `preview.png`, `display/`, and `attribution.md`.
A zipped exchange format can follow after the directory format is stable.
Provider download archives are inputs, not the application's package format.

The versioned manifest should record:

- Stable package ID, display name, format version, and builder version.
- Source agency, product identifier/version, source URLs, source-file hashes,
  retrieval date, and known acquisition/release dates.
- Original CRS and vertical reference, original units and sampling, no-data
  conventions, and source filenames.
- Display CRS, geographic extent, valid-data footprint, display dimensions,
  effective sampling, resampling method, and processing/style parameters.
- Preview/display asset paths, checksums, sizes, and available resolution levels.
- Attribution and source-use reference links.

Use WGS84 longitude/latitude for the display footprint. Coordinate arrays are
explicitly **[longitude, latitude]**. Coverage can be a polygon or multipolygon
with holes; an extent rectangle is not necessarily the valid-data footprint.
Antimeridian-crossing regions must be split/represented explicitly, not treated
as nearly world-wide rectangles.

Prepared packages and raw downloads live outside the source tree by default,
in a user-selected data directory. Source rasters remain unchanged. The package
must render after relocation without the original downloads; provenance records
how to rebuild it. Keep only small synthetic fixtures in the repository.

## Preparation and rendering pipeline

1. **Read and validate source metadata.** Identify the supported elevation
   product, bounds, dimensions, no-data values, CRS, units, and datum. Reject
   unsupported/ambiguous inputs with a useful explanation. Read source archives
   safely and select only expected elevation/metadata files.
2. **Choose a bounded area.** Initially use an input tile's extent or explicit
   geographic bounds. Show the proposed area and estimated display size before
   preparation. Avoid loading an entire national or global mosaic.
3. **Prepare a coherent relief image.** Mosaic adjacent tiles from a compatible
   product with a small processing margin, handle no-data, and produce shaded
   relief. Perform derivatives in a suitable projected metric CRS with correct
   elevation units; do not treat degrees as meters. Warp the resulting display
   image to the globe's geographic texture coordinates. GDAL documents unit and
   high-latitude concerns for hillshade [S5].
4. **Preserve masks and consistency.** Keep missing-data regions transparent;
   zero elevation is not automatically missing data. Use consistent illumination
   and styling across tiles. Avoid inventing elevations across gaps. Do not
   merge NASADEM and 3DEP elevations into one surface without explicitly resolving
   differences in datums, units, and source characteristics.
5. **Write a self-contained package.** Store the derived display assets,
   geographic footprint, preview, manifest, and attribution. Complete the build
   in staging, then expose it as ready; failed/cancelled builds stay inactive.
6. **Display as a separate globe patch.** Use a subdivided geographic patch whose
   UVs match the prepared raster; render slightly above the base sphere to avoid
   depth conflict. Package coverage borders sit above that image. Check actual
   VTK alpha/depth behavior with two representative packages before choosing
   offset and subdivision parameters. Future graph symbols render above these
   backgrounds and remain independently selectable.

Candidate preparation tools are Rasterio/GDAL for raster access/reprojection
and GDAL hillshade processing. Verify an installable combination on the current
Apple Silicon / Python 3.14 environment before selecting exact dependencies.
If necessary, use a separate preparation environment while keeping the viewer's
runtime unchanged. This compatibility work has not been executed.

## Start bounded; introduce local tiling incrementally

The first rendering milestone uses a preview and a single bounded regional
image with an explicit texture/memory limit determined by a small platform
experiment. If an area exceeds that limit, offer a smaller area or an explicitly
lower display resolution. Never silently claim full source detail after
resampling. Original source sampling and actual display sampling remain visible.

The next milestone prepares local display tiles and lower-resolution overview
levels. Read only tiles needed for the current viewport and camera scale, use
a bounded memory cache, and retain the preview while a sharper tile loads.
Rasterio supports overview rasters for reduced-resolution reads [S6], but a
raster file's internal tiling/overviews do not by themselves implement the
VTK tile-selection, texture-upload, or eviction logic.

This sequence retains a route to optimized tiled rendering while limiting the
first milestone to local packages. Worldwide streaming, remote tile services,
and downloading while navigating are deferred. No claim about achieved frame
rate or memory usage is made before the platform experiment.

## Coverage presentation and controls

Proposed presentation:

- Available package: a thin neutral broken outline when Show Package Coverage is on.
- Selected package: brighter outlined footprint and a faint fill while previewing
  its area; label with name and source. Exact colors/patterns remain prototype choices.
- Active background: subdued footprint outline remains on by default; selection
  fill can disappear so it does not compete with future graph content.
- Missing source coverage: transparent areas reveal Blue Marble. Package details
  distinguish overall bounds from actual valid coverage; preview can hatch gaps.
- A visible status indicator names the active background and reports when the
  view center is outside its valid coverage. Crossing a boundary never unloads
  the graph or clips objects/edges.

Coverage is geographic **map metadata**, not a graph edge, hazard boundary, or
analytical region. Include a legend/tooltip and keep it outside graph selection
and pathfinding. Packages that overlap are explicitly selected in the first
release; do not silently change sources according to nominal resolution.

All controls are proposed under **View → Map Packages**:

- Add Local Package…
- Prepare Package from Local Data…
- Active Package → None / package names
- Zoom to Package
- Show Package Coverage
- Map Appearance… (opacity/dimming)
- Package Details… (source, dates, coverage, sampling, attribution)
- Remove from Catalog… (does not delete the package's files)

These commands reuse shared actions where applicable in the right-click menu.
Heavy reading/preparation runs outside the GUI thread with progress/cancel;
VTK actor creation and texture updates stay on the GUI/render thread. Zoom to
Package preserves a north-up view and fits its extent; test dateline and polar
cases explicitly.

## Implementation sequence and stopping points

| Stage | Work | Completion criterion |
|---|---|---|
| 0 — Feasibility sample | Obtain a small sample from each provider; verify raster tooling, CRS handling, a rendered geographic patch, and memory behavior | Two aligned sample backgrounds; documented dependency and size limits |
| 1 — Builder and format | Source adapters, bounded cropping, relief preparation, footprint/mask, versioned manifest and validation | A reproducible portable package from each source |
| 2 — Viewer integration | Catalog, View controls, background patch, footprint highlight, opacity, details, fallback, cancellation | Useful offline close-up context on the current globe |
| 3 — Local resolution management | Precomputed levels/tiles, viewport selection, background reads, bounded cache | Measured improvement on larger regional packages without UI stalls |
| Later — Optional reference content | Specific National Map water/contour/road overlays and source-download integration | Separate scope agreed after first packages are usable |

Stages 0–2 define the proposed first usable increment. Stage 3 is planned
optimization, not a prerequisite for proving the map-package workflow. Graph
visibility/aggregation remains a separate proposal, described in the linked note.

Suggested code allocation under `src/stratascry/maps/`: manifest/model,
source adapters, preparation, catalog, and renderer modules. `window.py` owns
View actions; `globe.py` integrates map actors without owning provider logic.
New tests belong under `src/tests`. File names are preliminary, not created here.

## Validation plan and unresolved choices

Planned checks: synthetic labeled-raster orientation and known geographic
corners; pixel-center vs pixel-area alignment; projection/unit handling;
no-data holes and adjacent seams; antimeridian split; near-pole patch behavior;
missing/corrupt assets; cancellation and cache limits; offline relocation;
coverage visibility and menu parity; Blue Marble fallback; CPU/GPU texture
release when switching packages. Independently compare prepared georeferencing
against metadata or a trusted GIS view. Screen appearance alone is insufficient.

Benchmark one bounded region from each source at overview and close-up scale.
Record preparation time, peak memory, file size, input-to-render latency, and
navigation frame times. Choose numerical budgets after measurement rather than
assuming larger textures or tiled rendering will be fast on this laptop.

Open decisions: final package size cap; relief palette; optional contour display;
one-active-package restriction; dependency packaging; and automatic switching
thresholds if later desired. These do not block the two-source feasibility sample.
No implementation tests or data downloads were performed for this document.

## Primary references

Sources consulted September 19–20, 2026. NASA/USGS pages occasionally failed direct
fetch; official indexed content and product records supplied the cited facts.

- [S1 — NASADEM HGT V001 product record](https://doi.org/10.5067/MEaSUREs/NASADEM/NASADEM_HGT.001): coverage, sampling, data identity, and use/citation statement.
- [S2 — USGS 3DEP products](https://www.usgs.gov/3d-elevation-program/about-3dep-products-services): available elevation products and restrictions.
- [S3 — National Map usage terms](https://www.usgs.gov/faqs/what-are-terms-uselicensing-map-services-and-data-national-map?page=1): public-domain status and acknowledgment.
- [S4 — National Map downloads](https://www.usgs.gov/the-national-map-data-delivery/gis-data-download): product categories and access methods.
- [S5 — GDAL hillshade/DEM processing](https://gdal.org/en/stable/programs/gdaldem.html): rendering derivatives and coordinate-unit handling.
- [S6 — Rasterio overviews](https://rasterio.readthedocs.io/en/stable/topics/overviews.html): reduced-resolution raster reads.
- [S7 — GDAL HGT reader](https://gdal.org/en/stable/drivers/raster/srtmhgt.html): HGT layout and naming requirements.
- [S8 — USGS DEM naming](https://www.usgs.gov/faqs/why-are-two-different-file-naming-conventions-used-distribution-3d-elevation-program-3dep-dem): 1/3 arc-second GeoTIFF example.
