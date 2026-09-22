# NASA Blue Marble imagery

`blue-marble-200408.jpg` is an unmodified copy of NASA's 5400 × 2700 JPEG:
**August, Blue Marble: Next Generation, with topography and bathymetry**.

Credit: **Reto Stöckli, NASA Earth Observatory**. Data: Terra / MODIS,
August 1–31, 2004. The file is bundled for offline viewing.

- [Original image record](https://visibleearth.nasa.gov/images/73776/august-blue-marble-next-generation-w-topography-and-bathymetry/73778l) (NASA has migrated parts of this site; the record may redirect).
- [Original JPEG](https://eoimages.gsfc.nasa.gov/images/imagerecords/73000/73776/world.topo.bathy.200408.3x5400x2700.jpg).
- [NASA Blue Marble collection](https://science.nasa.gov/earth/earth-observatory/collections/blue-marble/).
- [NASA images and media use guidelines](https://www.nasa.gov/nasa-brand-center/images-and-media/), consulted September 18, 2026.

NASA's guidelines permit use of NASA content for educational and informational
purposes and request acknowledgment. NASA content is generally not subject to
copyright in the United States, subject to the exceptions in those guidelines.
This image is credited to NASA; the source record does not identify a separate
third-party copyright restriction. NASA's names, insignia, and identifiers have
separate restrictions. No NASA logo is bundled and no endorsement is implied.
The project's Apache-2.0 software license does not relicense the NASA imagery.

SHA-256: `f76d7b94445e8975a755c849ddaa93ed07b7e01118fb0b7e6bc5546a68c18d5c`.

This is historical, fixed-resolution imagery, not a live map. Topographic and
bathymetric shading are image content, not elevation geometry. The downsampled
bundled image does not have the resolution of the full Blue Marble dataset.

For version 0.3, this bundled image is the lightweight fallback. An optional
local dataset contains the eight full-resolution NASA August 2004 tiles,
recompressed into a tiled GeoTIFF with overviews. Its own manifest and
ATTRIBUTION.md record the sources and processing; it is not bundled in Git.
See `designs/blue-marble-prototype.md` for setup and the separate rendering budget.
