# SPDX-License-Identifier: Apache-2.0
"""Portable, validated display packages. No source raster or network is needed."""
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

FORMAT_VERSION = 1
MAX_SIDE = 4096
MAX_JSON_BYTES = 8 * 1024 * 1024


class PackageError(ValueError):
    pass


def read_json(path):
    path = Path(path)
    if path.stat().st_size > MAX_JSON_BYTES:
        raise PackageError(f"Metadata is too large: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path, check_cancel=lambda: None):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            check_cancel()
            digest.update(chunk)
    return digest.hexdigest()


def asset_path(root, relative):
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise PackageError("Package asset paths must be relative")
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()) or not candidate.is_file():
        raise PackageError(f"Missing or unsafe package asset: {relative}")
    return candidate


def validate_bounds(bounds):
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
        raise PackageError("Bounds must be [west, south, east, north]")
    w, s, e, n = map(float, bounds)
    if not all(math.isfinite(x) for x in (w, s, e, n)):
        raise PackageError("Bounds must be finite")
    if not (-180 <= w < e <= 180 and -89 <= s < n <= 89):
        raise PackageError("Use bounds within ±89° latitude and one side of the antimeridian. Split crossing regions into separate packages.")
    if e - w > 12 or n - s > 12:
        raise PackageError("A regional package may span at most 12° in either direction; choose a smaller area.")
    return w, s, e, n


@dataclass
class MapPackage:
    root: Path
    manifest: dict
    rgba: np.ndarray
    coverage: dict

    @property
    def id(self):
        return self.manifest["id"]

    @property
    def name(self):
        return self.manifest["name"]

    @property
    def bounds(self):
        return tuple(self.manifest["display"]["bounds"])

    @property
    def source_name(self):
        return self.manifest["source"]["label"]

    def contains(self, longitude, latitude):
        w, s, e, n = self.bounds
        if not (w <= longitude <= e and s <= latitude <= n):
            return False
        height, width = self.rgba.shape[:2]
        x = min(width - 1, int((longitude - w) / (e - w) * width))
        y = min(height - 1, int((n - latitude) / (n - s) * height))
        return bool(self.rgba[y, x, 3])


def load_package(directory, check_cancel=lambda: None):
    """Validate metadata and assets before returning bounded, decoded pixels."""
    root = Path(directory).expanduser().resolve()
    try:
        manifest = read_json(root / "manifest.json")
        if not isinstance(manifest, dict) or manifest.get("format") != "stratascry-map" or manifest.get("version") != FORMAT_VERSION:
            raise PackageError("Unsupported StrataScry map-package format/version")
        for key in ("id", "name"):
            if not isinstance(manifest.get(key), str) or not manifest[key].strip() or len(manifest[key]) > 512:
                raise PackageError(f"Package {key} is missing")
        display = manifest["display"]
        w, s, e, n = validate_bounds(display["bounds"])
        width, height = display["width"], display["height"]
        if type(width) is not int or type(height) is not int or not (2 <= width <= MAX_SIDE and 2 <= height <= MAX_SIDE):
            raise PackageError("Package texture dimensions exceed the supported limit")
        if display.get("crs") != "EPSG:4326":
            raise PackageError("Display textures must use EPSG:4326")
        sampling = display["approx_sampling_m_at_center"]
        if len(sampling) != 2 or not all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in sampling):
            raise PackageError("Invalid display sampling")
        source = manifest["source"]
        if source["product"] not in ("nasadem", "usgs"):
            raise PackageError("Unsupported source product")
        for key in ("label", "credit", "source_url"):
            if not isinstance(source[key], str) or not source[key].strip():
                raise PackageError(f"Source {key} is missing")
        if not isinstance(source["files"], list) or not 1 <= len(source["files"]) <= 16:
            raise PackageError("Package must describe 1–16 source files")
        for record in source["files"]:
            for key in ("file", "units_applied", "vertical_reference"):
                if not isinstance(record[key], str):
                    raise PackageError(f"Invalid source {key}")
            if not isinstance(record["sampling_native"], list) or len(record["sampling_native"]) != 2:
                raise PackageError("Invalid native sampling")
            if not isinstance(record.get("sidecar_metadata", {}), dict):
                raise PackageError("Invalid source sidecar metadata")
        for relative in (display["image"], "preview.png", "coverage.geojson", "attribution.md"):
            check_cancel()
            path = asset_path(root, relative)
            if path.stat().st_size > 96 * 1024 * 1024:
                raise PackageError(f"Asset exceeds size limit: {relative}")
            expected = manifest["assets"][relative]
            if sha256(path, check_cancel) != expected:
                raise PackageError(f"Asset checksum mismatch: {relative}")
        with Image.open(asset_path(root, display["image"])) as picture:
            if picture.size != (width, height) or picture.mode != "RGBA":
                raise PackageError("Display image must be RGBA and match its manifest dimensions")
            rgba = np.array(picture)
        if not np.any(rgba[:, :, 3]):
            raise PackageError("Package has no visible data")
        coverage = read_json(root / "coverage.geojson")
        if not isinstance(coverage, dict) or coverage.get("type") != "FeatureCollection":
            raise PackageError("Coverage must be a GeoJSON FeatureCollection")
        if not isinstance(coverage["features"], list) or not coverage["features"]:
            raise PackageError("Coverage must include valid-data polygons")
        vertex_count = 0
        for feature in coverage["features"]:
            geometry = feature["geometry"]
            if geometry["type"] != "Polygon":
                raise PackageError("Coverage features must be polygons")
            if not geometry["coordinates"]:
                raise PackageError("Empty coverage polygon")
            for ring in geometry["coordinates"]:
                vertex_count += len(ring)
                if len(ring) < 4 or ring[0] != ring[-1]:
                    raise PackageError("Coverage rings must be closed")
                for point in ring:
                    if len(point) != 2 or not all(math.isfinite(float(v)) for v in point):
                        raise PackageError("Invalid coverage coordinate")
                    if not (-180 <= point[0] <= 180 and -90 <= point[1] <= 90):
                        raise PackageError("Coverage coordinate is out of range")
                    if not (w-1e-8 <= point[0] <= e+1e-8 and s-1e-8 <= point[1] <= n+1e-8):
                        raise PackageError("Coverage extends outside the package bounds")
        if vertex_count > 200000:
            raise PackageError("Coverage geometry exceeds the supported limit")
        return MapPackage(root, manifest, rgba, coverage)
    except PackageError:
        raise
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
        raise PackageError(f"Cannot read map package: {error}") from error
