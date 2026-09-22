# Blue Marble prototype — tiled display

Version 0.3.0, September 20, 2026. Supersedes the regional terrain backgrounds as
the normal prototype view. User direction: use Blue Marble, maximize useful
resolution, and make tiling/optimization mandatory. The separate NASADEM/USGS
experiment is retained behind `--map-packages`; its actors, outlines and catalog
are not loaded by the normal prototype.

## Delivered behavior

The native macOS **View** menu retains navigation, reset, grid, context menu and
credits. It adds **Show Blue Marble Detail**, **Load Blue Marble Tiles…**, and
**Blue Marble Detail Status…**; the context menu shares those actions.

A bundled 5400 × 2700 overview appears immediately. Detail levels no sharper
than that matching overview require zero detail-tile reads, decoded cache bytes
or detail actors. Local detail replaces it as
needed while zooming and panning. The full installed source grid is
**86,400 × 43,200**, NASA's nominal 500 m Blue Marble product. Only visible detail
is read and rendered. No network service or credentials are used by the viewer.
The Earth is still spherical; topographic/bathymetric shading is image content.

Native sampling is finite: zooming beyond it enlarges existing pixels. This does
not provide building imagery, road tracing, contemporary observations or terrain
geometry. Source month remains August 2004.

## Storage and reproducible preparation

On this Mac the installed dataset is:

`~/Library/Application Support/StrataScry/StrataScry GGM/imagery/blue-marble-200408/`

It contains `earth.tif`, `manifest.json`, and `ATTRIBUTION.md`. The TIFF is about
410 MiB and stays outside the repository. Copy the whole folder to move it, then
use View → Load Blue Marble Tiles. Custom selections are session state; the
standard installation location is discovered automatically on startup.

To reproduce from NASA's eight August JPEGs (requires `curl` for downloading):

```sh
python -m stratascry.blue_marble.build --download \
  --output "$HOME/Library/Application Support/StrataScry/StrataScry GGM/imagery/blue-marble-200408"
```

The output must not exist. To rebuild an existing installation, choose a new
folder and load it after preparation. Alternatively use
`--source-dir /path/to/downloaded-nasa-jpegs` instead of `--download`.
The required names are `world.topo.bathy.200408.3x21600x21600.A1.jpg` through D1,
and A2 through D2. Download mode fetches at most two files concurrently into a
temporary directory; it is an explicit command, never a navigation side effect.

The builder validates the eight raster layouts, assembles their geographic
placements, and writes a tiled GeoTIFF using GDAL's COG driver. Native pixel
sampling is retained; JPEG quality 90 recompression is lossy. Reduced-resolution
overviews use averaging. The manifest records source URLs/checksums, the output
checksum, grid dimensions and processing choices. Preparation is staged and an
existing dataset is never overwritten. The offline builder uses two GDAL
threads and a 256 MiB GDAL cache; these differ from runtime limits below.

## Rendering and optimization contract

| Resource or behavior | Implemented limit/choice |
|---|---|
| On-disk blocks | 512 × 512, compressed; overviews from 2× through 256× reduction |
| Display tile grid | Geographic quadtree, levels 0–6; 675 × 675 content pixels per tile |
| Native level | 128 × 64 tiles, exactly matching 86,400 × 43,200 sampling |
| Edge filtering | One-pixel gutters; longitude wraps and polar edges clamp |
| Visibility | Conservative camera-frustum and horizon culling |
| Level selection | Projected tile size; detail relaxes if the visible actor budget would be exceeded |
| Visible detail | At most 32 actors; also capped by a 64 MiB RGBA texture estimate |
| Decoded CPU cache | 96 MiB, byte-counted least-recently-used eviction |
| GDAL runtime cache | 32 MiB; one raster reader and one decoding thread |
| Pending decoded output | One tile awaiting GUI acknowledgment |
| GPU uploads | One actor/texture upload per event-loop turn |
| Camera updates | At most one selection update per 50 ms; uses the latest camera state |
| Cached geometry bounds | At most 16,384 quadtree bounding spheres |

The unusual 675-pixel display tile size divides the native image exactly, avoiding
upsampling the highest level to a conventional power-of-two global raster. It is
independent of the TIFF's 512-pixel storage blocks. Overview-backed window reads
avoid reading native-resolution data for distant views.

The raster worker receives the latest required tile list, replacing queued work
for old viewpoints. An already executing local read can finish; its result may
enter the bounded cache but cannot create an actor unless that tile is still
wanted. Qt back-pressure prevents an unbounded queue of decoded arrays. VTK
actor creation and updates stay on the GUI thread. Closing waits for the current
read to finish instead of destroying a running worker.

The global overview remains underneath while detail loads. Obsolete detail
actors are removed before replacement tiles are uploaded; their pixels may stay
in the bounded CPU cache for reuse. No preview/parent textures are accumulated
outside the actor budget. Missing or invalid local detail falls back to the
bundled globe, with an explanation in the status tooltip/detail dialog.

The 64 MiB number is a conservative RGBA estimate for detail texture pixels,
not a whole-process or measured VRAM bound. The fallback texture, VTK copies,
mesh data, Qt/GDAL overhead and framebuffer memory are additional. Measured
process memory is recorded in the verification section. A very large viewport
or polar convergence may reduce selected detail to honor the tile budget.

## Geometry and module allocation

`src/stratascry/blue_marble/tiles.py` owns the tile grid, selection, bounded cache,
window reads and mesh data. `controller.py` owns the worker, scheduler, View
actions and actors. `build.py` prepares the portable local raster. The normal
`MainWindow` initializes this controller; the experimental map-package controller
is initialized only with its explicit launch flag.

Tile geometry follows the existing equirectangular coordinate convention:
longitude eastward, latitude northward, VTK texture V south-to-north. Image rows
are north-to-south. Gutters lie outside the mapped core UV interval. The meshes
get finer with detail level and share a radius of 1.0001, above the coarse radius-1
fallback sphere. This approximately 637 m display offset prevents depth conflicts;
it does not represent elevation. The grid radius is 1.00012, and minimum camera
distance is now 1.0002 so the camera remains above these surfaces. Future graph
rendering must account for the display surface while retaining geographic model
coordinates independently.

## Sources

NASA's [Blue Marble topography and bathymetry page](https://science.nasa.gov/earth/earth-observatory/blue-marble-next-generation/base-topography-bathymetry/)
lists the global overviews and eight full-resolution tiles for each month.
The installed dataset uses August 2004. Credit: Reto Stöckli, NASA Earth
Observatory. Exact source URLs and SHA-256 values accompany the local dataset.
The bundled overview retains its existing attribution file. The software license
does not relicense the imagery; no NASA endorsement is implied.

## Verification

Executed on the development Mac (Apple M3, 8 GiB RAM, macOS 14.5, Python
3.14.2). Dependencies include PySide6 6.11.2, PyVista 0.48.4, VTK 9.6.2,
Rasterio 1.5.1 / GDAL 3.12.4 and NumPy 2.5.3.

The complete suite exercises the original globe and optional regional tools,
plus tile-grid validation, coarse overviews, cross-tile gutters, longitude wrap,
polar clamping, mesh UV orientation, bounded LRU eviction, frustum selection,
zero detail I/O when the fallback suffices, cache reuse, replacement of stale
requests, one-result back-pressure, visibility toggling and worker shutdown.
Native shortcut checks now explicitly raise/wait for their test window, and
streaming tests dispose of closed native windows to isolate menu ownership.
Upstream Rasterio/affine and VTK/NumPy deprecation warnings remain.

A separate real-data run tested a 2360 × 1378 physical-pixel viewport. After each
camera change it waited for the selected tiles, then measured 20 explicit VTK
render calls and inspected a screenshot. File-system cache was warm; these are
single-run observations, not cold-start or hardware-independent guarantees.


| View | Active detail tiles | Levels | Detail ready | Median render call | 95th percentile |
|---|---:|---|---:|---:|---:|
| Global | 0 | overview | 0.000 s | 10.01 ms | 16.66 ms |
| Continent | 31 | 4 | 0.665 s | 4.37 ms | 7.59 ms |
| Regional | 3 | 6 | 0.081 s | 3.43 ms | 5.90 ms |
| Dateline | 12 | 6 | 0.139 s | 4.16 ms | 6.78 ms |
| Polar | 26 | 4 | 0.242 s | 3.33 ms | 5.29 ms |

A subsequent ten-second scripted pan used a 16 ms Qt timer to change the camera,
with an independent event-loop heartbeat. Median heartbeat interval was
14.85 ms, 95th percentile
24.96 ms, and maximum
28.14 ms in that run. This measures scheduling
responsiveness, not input-to-photon latency or a guaranteed frame rate.

Peak process RSS was 537.9 MiB, including the screenshots
and test harness. The decoded cache ended at 95.72
MiB, within its 96 MiB limit. Median recent tile read time was
6.34 ms and selection time
0.62 ms. GPU memory was not independently measured.
The source grid would occupy about 10.43 GiB as one decoded RGB image; the running
viewer never materializes that global array.

The real-data continental and regional screenshots were visually inspected;
the dateline and polar views were rendered and exercised by the measurement harness.
The finest native level was selected in the regional and dateline cases. Polar
convergence selected a coarser level to keep the actor budget. No claim of
building-level resolution, independent geodetic accuracy, arbitrary-hardware
performance, or long-duration leak testing follows from these checks.

Final regression suite: `STRATASCRY_GUI_TESTS=1 .venv/bin/python -m pytest -q`
completed with **61 passed** in 13.80 seconds. Upstream Rasterio/affine and VTK/NumPy
warnings remain; no test failed.
