# Globe graph-tool hotbar

September 28, 2026. Extends the [graph editor](graph-editor-implementation.md).

## Interaction contract

A fixed icon hotbar sits between the imagery status and globe viewport, within
the central viewer area. It provides Select / Move, Add Node, and Add Edge.
The highlighted icon reflects the controller's selected tool. Tooltips and
accessible names describe the icons; keyboard focus and Space activation work.
The native View and right-click commands remain available.

- Clicking an unselected tool invokes its default action. Add Node defaults to
  placement by clicking the globe, with the existing hover ghost.
- Clicking an already selected tool with choices opens its menu without
  deselecting it. Add Node offers **Add node by clicking** and
  **Add node by coordinates…**. Its separate arrow also opens these choices.
- Coordinate placement invokes the existing longitude/latitude dialog and creates
  one undoable node. It does not change the default tool or remember a new
  placement preference. Cancelling the dialog does not edit the graph.
- A selected tool with no choices stays selected when clicked again.
- Permissions are shared with the existing commands: tools are disabled in view
  mode or while loading; coordinate placement additionally requires a visible
  active layer. Selecting a creation tool does not enable editing by itself.
- Closing a menu or completing a command returns focus to the globe, retaining
  the B and navigation shortcuts. Tool selection creates no document edit.

## Structure and extension

`src/stratascry/graph/hotbar.py` defines `ToolSpec`, `ToolChoice`, `GRAPH_TOOLS`,
and `GraphHotbar`. Each specification supplies the existing command key, label,
SVG icon, tooltip description, and optional labeled command choices. New tools
need a controller action and one specification; any tool may have choices using
the same repeat-click handling. There is no node-specific menu implementation.
Commands that introduce new editing modes must still implement their own model,
permission, and controller behavior.

The hotbar uses ordinary `QAction` entries in an embedded `QToolBar`; Qt's
extension menu keeps entries accessible when they no longer fit. Choices also
remain available as submenus in overflow. Presentation actions provide distinct
labels without changing the shared View/context actions. They forward execution
to the controller and mirror checked/enabled state. The controller explicitly
resynchronizes the hotbar after its signal-blocked checked-state updates.

SVG assets are bundled under `src/stratascry/assets/icons` and included in package
data. Qt renders them at the requested size/device scale; no raster icon cache,
external icon service, or new dependency is introduced. The bar is outside the
VTK widget, so it does not intercept globe picking or require overlay reprojection.

## Verification

GUI regressions exercise first-click selection, second-click menu opening,
coordinate creation and undo, returning to click placement, dialog cancellation,
View/controller-to-hotbar synchronization, disabled view/hidden-layer controls,
keyboard activation, and adding choices to a different tool using the same
specification mechanism. Widget renders were inspected for icon spacing and the
two menu labels. A 90-logical-pixel toolbar showed an overflow menu containing
Add Node (with its submenu) and Add Edge.

`STRATASCRY_GUI_TESTS=1 .venv/bin/python -m pytest -q` completed with **92 passed
in 17.47 seconds**, including the drag-trail regressions. The 494 warnings are
existing upstream Rasterio/affine and VTK/NumPy deprecations. Both source
and wheel builds succeeded; archive inspection confirmed the hotbar module and
three SVGs match source, and the source distribution contains this design and
the GUI tests. Qt widget renders were inspected; no claim is made about physical
mouse input on every supported desktop platform.
