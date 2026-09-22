# Regional map packages — verification record

Date: September 20, 2026. Version: 0.2.0.
Scope: stages 0–2 of the [plan](map-packages-plan.md), with the limits recorded in
[the implementation guide](map-packages-implementation.md). This is development
verification, not evidence of cartographic accuracy or analytical suitability.

## Environment and regression checks

Executed on the current Apple Silicon Mac, macOS 14.5, Homebrew Python 3.14.2:
PySide6 6.11.2, PyVista 0.48.4, pyvistaqt 0.11.4, VTK 9.6.2, NumPy 2.5.3,
Rasterio 1.5.1 / GDAL 3.12.4, Pillow 12.3.0 and affine 3.0.1.
Other OS/Python combinations have not been tested.

```sh
STRATASCRY_GUI_TESTS=1 .venv/bin/python -m pytest -q
```

**45 passed in 12.52 seconds** against the installed project. The 208 warnings
come from upstream VTK/NumPy array-shape and Rasterio/affine multiplication
deprecations. The earlier image checks initially exposed stale asynchronous
render capture; tests now allow queued Qt rendering before reading pixels.
A close-up camera check also motivated reducing the near clipping minimum.

| Area | Executed evidence |
|---|---|
| Existing globe | Geometry/cardinal coordinates, UV seam, camera bounds, assets, native View/context actions, actual mouse/keyboard dispatch |
| NASADEM importer | Full-size synthetic 3601² big-endian HGT, coordinate filename/half-cell georeferencing, ZIP with elevation and ancillary `.num`; real derived terrain sample below |
| USGS importer | Synthetic and real GeoTIFF; native CRS; official FGDC sidecar encoding/DTD reference, units, vertical datum and separate date fields |
| Projection/units | UTM fixture transforms to expected geographic bounds; metre/foot versions produce matching display pixels within test tolerance |
| Mask and mosaic | No-data holes remain transparent; valid zero elevations stay valid; adjacent flat tiles have coverage across their shared seam; unknown common vertical reference rejected |
| Portability/validation | Relocated packages load; missing/unsafe assets, altered checksums, oversized images and invalid required metadata fail; corrupt catalog retained |
| Offline loading | Relocated package loads with Python socket connections forbidden; loader has no remote asset path; no operating-system-wide network cutoff performed |
| Extent limits | Degenerate, nonfinite, world-spanning, dateline-crossing and pole-crossing requests rejected; a synthetic 84°N region prepares successfully |
| VTK rendering | Four known geographic quadrants render expected colors; patch corners fit viewport; alpha-hole center matches Blue Marble pixels; minimum camera altitude still shows the patch |
| Interaction | Background load, prepare-dialog inspect/build, GUI-thread activation, package selection, coverage toggle, opacity/dimming, nondestructive catalog removal and close-during-cancel |

Native macOS UI inspection confirmed View → Map Packages, both catalog entries,
Zoom to Package, active coverage/fallback status, readable source details, and
all preparation fields. A form-growth adjustment gives text inputs the available
width. The regional overlay and border were inspected in real rendered output.
Both persistent examples also passed `python -m stratascry.maps validate`.

`pip install -e '.[dev]'` installed version 0.2.0 and `pip check` reported no
broken requirements. `python -m build` produced the 0.2.0 wheel and source distribution using the
declared isolated build environment. Archive inspection confirmed map modules,
bundled Blue Marble, LICENSE/NOTICE, and design/test files in the appropriate
artifacts; raw elevation downloads are excluded. The initial `--no-isolation`
attempt failed because setuptools is not installed in the runtime venv; the
standard isolated build succeeded without changing runtime dependencies.

## Representative data and provenance

The common display extent is [west, south, east, north] =
[-122.8, 37.7, -122.4, 38.05], in degrees. It deliberately extends north of the
source tile, demonstrating transparent missing coverage and global fallback.
The builder limit was 2048; both outputs are 1847 × 2047 RGBA pixels, approximately
19.0 × 19.0 m display sampling at the region center. That is resampled display
spacing; neither source accuracy nor added terrain detail is implied.

**USGS:** downloaded the actual 222,936,410-byte
[USGS 1/3 arc-second n38w123 GeoTIFF](https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/13/TIFF/current/n38w123/USGS_13_n38w123.tif)
and [its XML metadata](https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/13/TIFF/current/n38w123/USGS_13_n38w123.xml).
Rasterio reports 10812² pixels, EPSG:4269, and approximately 1/10800° sampling.
The sidecar reports metres, NAVD88, a dataset acquisition range of
1947-01-01 through 2023-12-11, and publication date 2025-08-27. That range describes
the source metadata; it does not date every location in the example.

**NASADEM:** read a one-degree window from the
[Stanford NatCap public NASADEM mosaic](https://data.naturalcapitalalliance.stanford.edu/download/global/nasa-hgt-v1-1s/nasa-hgt-v1-1s.tif)
using HTTP range reads, then resampled that window onto a named 3601² HGT posting
grid for importer testing. The entire global mosaic was not downloaded.
This is real terrain through an independent distribution, **not an original
NASA-distributed ZIP**. The package name and source URL retain that distinction.
Original NASA archive layout was tested synthetically. Direct Earthdata
retrieval/authentication and independent verification of the mosaic against
original NASA tiles remain untested. The
[NASA product record](https://doi.org/10.5067/MEaSUREs/NASADEM/NASADEM_HGT.001)
is the adapter's product reference.

Packages are saved outside the source tree in the application's local data
folder under `maps/examples/marin-usgs` and `maps/examples/marin-nasadem`. Their
manifests contain source checksums and processing metadata. Raw downloads and
benchmark scratch files were kept outside Git.

## Measured resource use

Single runs on this Mac; no statistical performance guarantee is inferred.
Preparation timings include package validation, exclude downloading and process
startup, and used separate Python processes. File size is the complete package
at creation. RSS is the macOS process high-water mark, not GPU memory.

| Measurement | NASADEM-derived example | USGS example |
|---|---:|---:|
| Prepare + validate | 0.879 s | 1.410 s |
| Package bytes | 1,643,541 | 1,889,630 |
| Preparation process peak RSS | 351.4 MiB | 351.5 MiB |
| Open to first explicit completed render call | 2.755 s | 2.599 s |
| Median VTK render-call wall time (40 samples) | 7.28 ms | 7.13 ms |
| 95th percentile render-call wall time | 9.83 ms | 9.68 ms |

The viewer rendered at 2360 × 1346 physical pixels. Render timing used explicit
VTK/PyVista render calls after tiny camera moves, with Qt events processed.
It does not measure complete pointer-to-display latency, guaranteed frame rate,
or worst-case shader/driver/GPU completion. The two-package viewer process
peaked at 428.3 MiB RSS. Actor counts were four with one catalog entry and five
with two, reflecting base, graticule, one active image and one outline per entry.
Long-duration memory/VRAM leak testing was not performed.

The default decoded regional image cap is 16 MiB (2048² RGBA); the selectable
4096 cap is 64 MiB. CPU work arrays, source caches, Qt/VTK, the global image and
GPU copies add memory. The measurements above validate the default-size sample,
not all allowable extents or the maximum-size workload.

## Requirement status and remaining evidence

MP-01 through MP-05 and MP-07/08 have the development evidence above, subject to
the sample provenance and platform limits. MP-06 (map changes never alter graph
analysis) is enforced by architectural separation now; an end-to-end analysis
invariance test must wait for graph/analysis functionality.

Automatic antimeridian splitting, polar rendering stress tests, GIS-based
independent absolute alignment checks, maximum-size stress tests, long-running
GPU memory measurements and local tile/cache benchmarks remain future checks.
Tile pyramids and viewport loading are stage 3, not part of this release.
No graph aggregation, routing, hazard scores or analysis results were changed.
