# Initial globe viewer verification

Executed September 18, 2026, on macOS 14.5 / Apple Silicon (arm64), using
Homebrew Python 3.14.2. This records observed results, not a certification of
other platforms or future graph-modeling capabilities.

## Environment

| Dependency | Installed version |
|---|---|
| PySide6 | 6.11.2 |
| PyVista | 0.48.4 |
| pyvistaqt | 0.11.4 |
| VTK | 9.6.2 |
| NumPy | 2.5.3 |
| pytest | 9.1.1 |

The project declares compatible dependency ranges in `pyproject.toml`. This
is the tested environment, not a cross-platform dependency lock.

## Executed checks

- `STRATASCRY_GUI_TESTS=1 .venv/bin/python -m pytest -q`: **18 passed** after the
  macOS menu correction. Geometry/UV tests cover cardinal coordinates, sphere
  radius, duplicated antimeridian, texture orientation, outward face winding,
  zoom bounds, north-up camera orthogonality, and reset fit for four aspect ratios.
- Qt integration tests dispatch left drag, wheel, Command-equals, Command-0,
  arrow-key, right-click, and macOS Control-click events to the live widget.
  They verify the resulting state, reset behavior, graticule state, native
  menu flag, and shared action identity between View and the context menu.
- A VTK render readback contains varied texture pixels rather than a blank
  framebuffer. The rendered North American view was also inspected visually:
  north is up, continents are correctly oriented, and coastlines are visible.
- Desktop inspection confirmed an actual macOS **View** menu with navigation,
  grid, context menu, help, and credits. Enabling the grid through that menu
  visibly overlays the globe. macOS's native Enter / Exit Full Screen commands entered and exited
  full screen. A fresh launch confirmed that the final View menu contains
  only one fullscreen command; the duplicate application item was removed.
- NASA JPEG SHA-256 and dimensions match the bundled provenance JSON.
- `.venv/bin/python -m pip check`: **No broken requirements found**.
- `.venv/bin/python -m build`: source archive and wheel build successfully.
  Wheel contents include application modules, the JPEG, provenance, attribution,
  Apache LICENSE, and NOTICE.
- `git diff --check`: passed. Existing README prose and `design/features.md`
  were retained; run instructions were appended to the README.

## Known limits / unverified items

- The test run emits 19 upstream VTK/NumPy deprecation warnings about assigning
  array shape. They did not cause test failures. No dependency warning is
  suppressed by the application or test configuration.
- Desktop capture initially failed to connect by app name; connecting by the
  Python application path subsequently succeeded. Qt widget-only screenshots
  omit the native OpenGL surface, so visual checks used VTK render readback
  and an actual desktop window capture.
- The macOS application menu is labeled **Python** when run from the interpreter.
  The window is labeled **StrataScry GGM — Globe**, with View in the system menu
  bar. A signed, distributable `.app` bundle is outside this initial iteration.
- Fullscreen entry and exit were verified through native menus. The application
  does not assign a fullscreen keyboard shortcut on macOS; use View or the
  green window control. F11 is assigned on other platforms but was not tested.
- Scroll and key events were tested through Qt. Trackpad hardware sensitivity,
  pinch gestures, multi-monitor behavior, and performance across other GPUs
  were not benchmarked. Pinch zoom is not implemented.
- Windows/Linux and older Python versions were not executed. The declared
  minimum Python version does not imply that every dependency wheel is
  available for every operating system / architecture.
- Imagery is a fixed-resolution August 2004 map on a sphere. No live tiles,
  terrain elevations, graph editor, hazard scoring, or route analysis is
  included in this viewer.
