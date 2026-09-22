# SPDX-License-Identifier: Apache-2.0
"""Bounded offline elevation-to-display preparation; never creates graph weights."""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import tempfile
import uuid

import numpy as np
from PIL import Image
import rasterio
from rasterio.crs import CRS
from rasterio.features import shapes
from rasterio.transform import from_bounds
from rasterio.vrt import WarpedVRT
from rasterio.warp import Resampling, reproject, transform_bounds

from .model import FORMAT_VERSION, MAX_SIDE, PackageError, sha256, validate_bounds
from .sources import PRODUCTS, inspect_sources, local_raster


class PreparationCancelled(Exception):
    pass


@dataclass
class PrepareOptions:
    paths: list[str]
    product: str
    destination: str
    name: str
    bounds: tuple | None = None
    max_side: int = 2048
    units: str = "from_metadata"
    vertical_reference: str = ""
    source_url: str = ""
    acquisition_date: str = ""


def unit_factor(units):
    normalized = units.lower().replace(" ", "_")
    if normalized in ("m", "metre", "metres", "meter", "meters"):
        return 1.0
    if normalized in ("ft", "foot", "feet", "international_foot"):
        return 0.3048
    if normalized in ("us_survey_feet", "us_survey_foot", "foot_us"):
        return 1200 / 3937
    raise PackageError("Elevation units are unspecified or unsupported. Select metres, feet, or US survey feet from the source metadata.")


def shade_elevations(elevation, pixel_m):
    """Multidirectional Lambert shading. Row direction is south, +Y is north."""
    dz_south, dz_east = np.gradient(elevation, pixel_m, pixel_m)
    nx, ny = -dz_east, dz_south
    normal_length = np.sqrt(nx * nx + ny * ny + 1)
    shade = np.zeros(elevation.shape, dtype=np.float32)
    for azimuth in (225, 270, 315, 360):
        azimuth = math.radians(azimuth)
        altitude = math.radians(45)
        illumination = (nx * math.sin(azimuth) * math.cos(altitude)
                        + ny * math.cos(azimuth) * math.cos(altitude)
                        + math.sin(altitude)) / normal_length
        shade += np.maximum(illumination, 0) / 4
    valid = np.isfinite(shade) & np.isfinite(elevation)
    # Restrained blue-grey relief keeps eventual graph overlays legible.
    brightness = np.nan_to_num(0.28 + 0.72 * shade, nan=0)
    rgb = np.stack([brightness * value for value in (170, 184, 191)], axis=0)
    return rgb.astype(np.uint8), valid


def build_package(options, progress=lambda percent, message: None, cancelled=lambda: False):
    """Build in staging and atomically expose a new directory; never overwrite."""
    def check():
        if cancelled():
            raise PreparationCancelled("Preparation cancelled")

    if not options.name.strip():
        raise PackageError("Enter a package name")
    if not 128 <= options.max_side <= MAX_SIDE:
        raise PackageError(f"Display limit must be between 128 and {MAX_SIDE} pixels")
    target = Path(options.destination).expanduser().resolve()
    if target.exists():
        raise PackageError("The output directory already exists. Choose a new package directory.")
    if not target.parent.is_dir():
        raise PackageError("The output parent directory does not exist")
    progress(2, "Inspecting local elevation data…")
    report = inspect_sources(options.paths, options.product, check)
    bounds = validate_bounds(list(options.bounds) if options.bounds is not None else report["bounds"])
    if len(report["sources"]) > 1 and not options.vertical_reference.strip():
        references = {source["vertical_reference"] for source in report["sources"]}
        if len(references) != 1 or any(value.startswith("not supplied") for value in references):
            raise PackageError("Multiple rasters require a known common vertical reference. Check metadata and specify it explicitly before mosaicking.")
    w, s, e, n = bounds
    lon, lat = (w + e) / 2, (s + n) / 2
    metric_crs = CRS.from_string(f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m +no_defs")
    left, bottom, right, top = transform_bounds("EPSG:4326", metric_crs, *bounds, densify_pts=41)
    pixel_m = max((right - left), (top - bottom)) / (options.max_side - 4)
    if not math.isfinite(pixel_m) or pixel_m < 0.1:
        raise PackageError("Choose a larger geographic area")
    # Two-pixel margin allows derivatives before clipping to requested bounds.
    width = math.ceil((right - left) / pixel_m) + 4
    height = math.ceil((top - bottom) / pixel_m) + 4
    from affine import Affine
    metric_transform = Affine(pixel_m, 0, left - 2 * pixel_m, 0, -pixel_m, top + 2 * pixel_m)
    mosaic = np.full((height, width), np.nan, dtype=np.float32)
    source_records = []
    with rasterio.Env(GDAL_CACHEMAX=64 * 1024 * 1024):
        for index, (path, info) in enumerate(zip(options.paths, report["sources"])):
            check()
            progress(8 + int(40 * index / len(options.paths)), f"Reading {Path(path).name}…")
            units = info["units"] if options.units == "from_metadata" else options.units
            if options.product == "nasadem":
                if options.units not in ("from_metadata", "metres"):
                    raise PackageError("NASADEM HGT elevations are defined in metres")
                units = "metres"
            factor = unit_factor(units)
            with local_raster(path, options.product) as raster, rasterio.open(raster) as source:
                with WarpedVRT(source, crs=metric_crs, transform=metric_transform,
                               width=width, height=height, dtype="float32", nodata=float("nan"),
                               resampling=Resampling.bilinear, warp_mem_limit=64) as warped:
                    values = warped.read(1, masked=True).filled(np.nan)
                values = (values * source.scales[0] + source.offsets[0]) * factor
                usable = np.isfinite(values) & ~np.isfinite(mosaic)
                mosaic[usable] = values[usable]
            info = dict(info)
            info.update(sha256=sha256(path, check), units_applied=units,
                        unit_selection="source/product metadata" if options.units == "from_metadata" else "user declaration")
            info["vertical_reference"] = options.vertical_reference.strip() or info["vertical_reference"]
            source_records.append(info)
        check()
        if not np.isfinite(mosaic).any():
            raise PackageError("No valid elevation data intersects the requested area")
        progress(53, "Preparing shaded relief…")
        rgb, valid = shade_elevations(mosaic, pixel_m)
        del mosaic
        # Geographic raster: rows north-to-south, columns west-to-east.
        east_m = (e - w) * 111195 * max(math.cos(math.radians(lat)), 0.01)
        north_m = (n - s) * 111195
        dw = max(2, min(options.max_side, math.ceil(east_m / pixel_m)))
        dh = max(2, min(options.max_side, math.ceil(north_m / pixel_m)))
        display_transform = from_bounds(*bounds, dw, dh)
        output = np.zeros((4, dh, dw), dtype=np.uint8)
        metric_rgba = np.concatenate((rgb, (valid.astype(np.uint8) * 255)[None]), axis=0)
        reproject(metric_rgba, output, src_transform=metric_transform, src_crs=metric_crs,
                  dst_transform=display_transform, dst_crs="EPSG:4326", src_alpha=4,
                  dst_alpha=4, resampling=Resampling.bilinear, warp_mem_limit=64)
    check()
    pixels = np.moveaxis(output, 0, -1)
    if not np.any(pixels[:, :, 3]):
        raise PackageError("No displayable terrain remains after preparation")
    progress(72, "Writing package and coverage…")
    with tempfile.TemporaryDirectory(prefix=".stratascry-build-", dir=target.parent) as temporary:
        staging = Path(temporary) / "package"
        (staging / "display").mkdir(parents=True)
        image = Image.fromarray(pixels)
        image.save(staging / "display/relief.png")
        preview = image.copy()
        preview.thumbnail((512, 512))
        preview.save(staging / "preview.png")
        # The outline is an explicit approximation; exact center coverage uses alpha.
        cw, ch = max(2, min(256, dw)), max(2, min(256, dh))
        mask = np.array(Image.fromarray(pixels[:, :, 3]).resize((cw, ch), Image.Resampling.NEAREST)) > 0
        coverage = {"type": "FeatureCollection", "features": []}
        for geometry, value in shapes(mask.astype(np.uint8), mask=mask,
                                       transform=from_bounds(*bounds, cw, ch)):
            coverage["features"].append({"type": "Feature", "properties": {
                "kind": "map_coverage", "approximation": "display-alpha mask sampled at at most 256 × 256 pixels"},
                "geometry": geometry})
        (staging / "coverage.geojson").write_text(json.dumps(coverage), encoding="utf-8")
        product = PRODUCTS[options.product]
        (staging / "attribution.md").write_text(
            f"# {options.name}\n\n{product['credit']}\n\nSource: {options.source_url or product['url']}\n\n"
            f"Use guidance: {product['terms']}\n\nShaded relief derived for visual context; no graph weights are computed.\n",
            encoding="utf-8")
        assets = {relative: sha256(staging / relative, check) for relative in
                  ("display/relief.png", "preview.png", "coverage.geojson", "attribution.md")}
        manifest = {
            "format": "stratascry-map", "version": FORMAT_VERSION, "id": str(uuid.uuid4()),
            "name": options.name.strip(), "created": datetime.now(timezone.utc).isoformat(),
            "builder": "stratascry-ggm/0.2", "source": {
                **product, "product": options.product, "source_url": options.source_url or product["url"],
                "acquisition_date": options.acquisition_date.strip() or "not supplied",
                "files": source_records, "identity": "provider/product declared by importer; layout checked"},
            "display": {"crs": "EPSG:4326", "bounds": list(bounds), "width": dw, "height": dh,
                        "image": "display/relief.png", "sampling_degrees": [(e-w)/dw, (n-s)/dh],
                        "approx_sampling_m_at_center": [east_m/dw, north_m/dh],
                        "source_sampling_preserved": False},
            "processing": {"metric_crs": metric_crs.to_wkt(), "metric_sampling_m": pixel_m,
                           "resampling": "bilinear", "max_side": options.max_side,
                           "style": "multidirectional relief; azimuths 225,270,315,360; altitude 45; no exaggeration",
                           "overlap": "first valid source in user-specified order",
                           "rasterio": rasterio.__version__, "gdal": rasterio.__gdal_version__},
            "assets": assets,
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")
        check()
        if target.exists():
            raise PackageError("Output appeared during preparation; existing files were not replaced")
        staging.rename(target)
    progress(100, "Package ready")
    return str(target)
