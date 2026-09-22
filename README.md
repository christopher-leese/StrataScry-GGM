# StrataScry GGM
StrataScry Geospatial Graph Modeler (GGM) is a geospatial graph modeling tool under development for constructing and analyzing multilayer networks over map imagery. Its planned capabilities include user-defined layers, configurable node and edge attributes, and hazard objects that influence edges through proximity or specific selection. Analysts define scoring models using additive contributions, net multipliers applied to an edge’s combined score, and tag-filtered multipliers applied to selected hazard contributions. The project aims to support geospatial network modeling and route analysis.

StrataScry GGM is a personal project of mine. Generative AI has been used for code.

# Attributions
- StrataScry GGM uses NASA Earth Observatory's Blue Marble: Next Generation's imagery from 2004 for the basemap.
- A personal thank you to Bobby Cupps for reminding me that if we have N layers, and for all layers, if every edge is weighted from 0 to 1, then we can bound the sum of a set of corresponding edges simply by dividing it by N. Simple in retrospect, but it never crossed my mind in our conversation.

# On Licensing
If StrataScry GGM contributes to your work, please (as a courtesy) acknowledge the project and link to this repository.

## Run the globe viewer

The current implementation is a Python desktop globe viewer with **tiled NASA
Blue Marble imagery**. It opens with Blue Marble alone, uses a lightweight global
overview while visible detail loads, and supports the full 86,400 × 43,200 source
grid when the local tile set is installed. Navigation and imagery controls are
under the native macOS **View** menu. Graph editing and analysis are not implemented yet.

Use Python 3.10 or newer with a working desktop graphics environment. On this
Mac, use the Homebrew Python (`/opt/homebrew/bin/python3`); the system Python
3.9 is too old. From the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m stratascry
```

After the environment is installed, launch directly with
`.venv/bin/python -m stratascry` or `.venv/bin/stratascry`.
The viewer works offline after installation; no API key or paid service is needed.

- **Rotate:** left drag or arrow keys.
- **Zoom:** scroll, Command + / −, or View → Zoom In / Out.
- **Reset:** Command 0 or View → Reset View.
- **Context menu:** right-click, Control-click, Shift F10, or View → Show Context Menu.
- **More:** View → Navigation Help.

The globe works offline. Detail uses overview-backed window reads, a 96 MiB
CPU tile cache and at most 32 visible detail tiles. This prototype retains
August 2004 imagery; zooming beyond its approximately 500 m native sampling
cannot reveal additional features. Terrain shading is part of the image.

A full local Blue Marble tile set is already installed on the development Mac,
outside the repository. On a fresh machine, the bundled overview works alone.
Prepare full detail with:

```sh
python -m stratascry.blue_marble.build --download --output /path/to/new-blue-marble-folder
```

Then select that folder through **View → Load Blue Marble Tiles…**. The explicit
preparation command downloads NASA's eight source JPEGs and needs temporary disk
space; the viewer never downloads while navigating. See the
[tiled Blue Marble design and setup guide](designs/blue-marble-prototype.md)
for the standard installation path, resource budgets, provenance and measured results.

The previous terrain-package implementation and examples are retained behind
`python -m stratascry --map-packages`. They are disabled in normal prototype
startup; the [package guide](designs/map-packages-implementation.md) documents
that separate experiment.

## Development and design

Application code and tests are under `src`. The initial design, coordinate
conventions, requirement traceability, and interaction contract are in
[designs/globe-viewer.md](designs/globe-viewer.md). Executed checks are recorded
in [designs/verification.md](designs/verification.md) for the initial globe and
[designs/map-packages-verification.md](designs/map-packages-verification.md) for
regional maps. NASA asset provenance
and usage references are in [the imagery attribution](src/stratascry/assets/ATTRIBUTION.md).

```sh
python -m pytest                                      # geometry, assets and raster packages
STRATASCRY_GUI_TESTS=1 python -m pytest                # include desktop GUI checks
python -m build                                      # source distribution and wheel
```

The GUI tests create a visible window and require an active desktop session.
