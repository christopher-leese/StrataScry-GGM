# SPDX-License-Identifier: Apache-2.0
"""Local source adapters. Provider identity is declared by the importer."""
from contextlib import contextmanager
from pathlib import Path
import re
import shutil
import tempfile
import zipfile
from xml.etree import ElementTree

import rasterio
from rasterio.warp import transform_bounds

from .model import PackageError, sha256

PRODUCTS = {
    "nasadem": {
        "label": "NASA NASADEM HGT V001",
        "url": "https://doi.org/10.5067/MEaSUREs/NASADEM/NASADEM_HGT.001",
        "credit": "NASA JPL (2020), NASADEM Merged DEM Global 1 arc second V001. NASA Earthdata. No endorsement implied.",
        "terms": "https://www.earthdata.nasa.gov/engage/open-data-services-software/data-use-policy",
    },
    "usgs": {
        "label": "USGS 3DEP / The National Map",
        "url": "https://www.usgs.gov/3d-elevation-program/about-3dep-products-services",
        "credit": "Map services and data available from U.S. Geological Survey, National Geospatial Program. No endorsement implied.",
        "terms": "https://www.usgs.gov/faqs/what-are-terms-uselicensing-map-services-and-data-national-map",
    },
}
HGT_NAME = re.compile(r"[ns]\d{2}[ew]\d{3}\.hgt", re.IGNORECASE)


@contextmanager
def local_raster(path, product):
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise PackageError(f"Source does not exist: {path}")
    if product not in PRODUCTS:
        raise PackageError("Select NASADEM or USGS 3DEP")
    if product == "nasadem" and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory(prefix="stratascry-hgt-") as temporary:
            entries = [entry for entry in archive.infolist()
                       if HGT_NAME.fullmatch(Path(entry.filename).name)]
            if len(entries) != 1:
                raise PackageError("A NASADEM archive must contain exactly one named elevation .hgt file")
            entry = entries[0]
            if entry.file_size != 3601 * 3601 * 2:
                raise PackageError("NASADEM HGT V001 requires a 3601 × 3601 signed-int16 elevation tile")
            # Copy just the validated basename; never extract arbitrary archive paths.
            raster = Path(temporary) / Path(entry.filename).name
            with archive.open(entry) as source, raster.open("wb") as target:
                shutil.copyfileobj(source, target, 1024 * 1024)
            yield raster
    else:
        expected = (".hgt",) if product == "nasadem" else (".tif", ".tiff")
        if path.suffix.lower() not in expected:
            raise PackageError("NASADEM accepts .hgt/.zip; USGS accepts elevation .tif/.tiff files")
        yield path


def metadata_for(path, raster, product):
    with rasterio.open(raster) as source:
        if source.crs is None or source.count != 1:
            raise PackageError("Elevation input must have a CRS and exactly one band")
        if product == "nasadem":
            if not HGT_NAME.fullmatch(raster.name) or source.shape != (3601, 3601) or source.dtypes[0] != "int16":
                raise PackageError("Input does not match NASADEM's named 1-arc-second HGT elevation layout")
            units, datum = "metres", "EGM96 geoid (NASADEM HGT V001 product specification)"
        else:
            units = source.units[0] or "unspecified"
            datum = source.tags().get("VERTICAL_DATUM", "not supplied; preserved in source CRS/metadata if present")
        sidecar = Path(path).with_suffix(".xml")
        extra = {}
        if sidecar.is_file() and sidecar.stat().st_size < 1024 * 1024:
            xml = sidecar.read_bytes()
            if b"<!ENTITY" in xml.upper():
                raise PackageError(f"Entity declarations are unsupported in source metadata: {sidecar.name}")
            try:
                # ElementTree reads declared text encodings and does not retrieve
                # external DTDs (official FGDC sidecars often name one).
                root = ElementTree.fromstring(xml)
                def field(tag):
                    return next((element.text.strip() for element in root.iter(tag) if element.text), None)
                extra = {"xml": ElementTree.tostring(root, encoding="unicode"), "file": sidecar.name,
                         "sha256": sha256(sidecar),
                         "acquisition_start": field("begdate"), "acquisition_end": field("enddate"),
                         "publication_date": field("pubdate")}
                units = field("altunits") or units
                datum = field("altdatum") or datum
            except (ElementTree.ParseError, LookupError, ValueError) as error:
                raise PackageError(f"Invalid elevation metadata XML: {sidecar.name}") from error
        bounds = list(transform_bounds(source.crs, "EPSG:4326", *source.bounds, densify_pts=41))
        return {
            "file": Path(path).name, "raster_file": raster.name,
            "width": source.width, "height": source.height,
            "crs_wkt": source.crs.to_wkt(), "bounds": bounds,
            "sampling_native": list(source.res), "units": units,
            "vertical_reference": datum,
            "nodata": float(source.nodata) if source.nodata is not None and abs(source.nodata) < 1e38 else None,
            "tags": source.tags(), "band_tags": source.tags(1), "sidecar_metadata": extra,
        }


def inspect_sources(paths, product, check_cancel=lambda: None):
    if not paths or len(paths) > 16:
        raise PackageError("Choose between 1 and 16 local elevation files")
    metadata = []
    for path in paths:
        check_cancel()
        with local_raster(path, product) as raster:
            metadata.append(metadata_for(path, raster, product))
    # Clip the half-pixel HGT padding at the geographic domain boundary.
    bounds = [max(-180, min(item["bounds"][0] for item in metadata)),
              max(-89, min(item["bounds"][1] for item in metadata)),
              min(180, max(item["bounds"][2] for item in metadata)),
              min(89, max(item["bounds"][3] for item in metadata))]
    return {"sources": metadata, "bounds": bounds}
