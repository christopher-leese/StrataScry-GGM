"""Opt-in tests with a real Qt/VTK window; require a desktop display.

Run: STRATASCRY_GUI_TESTS=1 python -m pytest
"""
import os
import sys

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("STRATASCRY_GUI_TESTS") != "1",
    reason="Set STRATASCRY_GUI_TESTS=1 in a desktop session to run GUI tests",
)


@pytest.fixture(scope="module")
def window(tmp_path_factory):
    from PySide6.QtTest import QTest
    from stratascry.app import create_application
    from stratascry.window import MainWindow
    app = create_application([])
    view = MainWindow(catalog_path=tmp_path_factory.mktemp("gui") / "catalog.json",
                      tile_path=tmp_path_factory.mktemp("no-tiles"))
    view.show()
    view.raise_()
    view.activateWindow()
    view.globe.setFocus()
    QTest.qWait(250)
    app.processEvents()
    yield view
    view.close()
    app.processEvents()


def menu_actions(menu):
    result = []
    for action in menu.actions():
        if action.menu():
            result.extend(menu_actions(action.menu()))
        elif not action.isSeparator():
            result.append(action)
    return result


def test_native_view_contains_all_context_actions(window):
    assert window.maps is None
    assert "map_add" not in window.actions
    assert window.blue_marble is not None
    assert "Global overview" in window.map_status.text()
    if sys.platform == "darwin":
        assert window.menuBar().isNativeMenuBar()
    assert set(menu_actions(window.context_menu)) <= set(menu_actions(window.view_menu))
    assert set(window.actions.values()) <= set(menu_actions(window.view_menu))


def test_menu_zoom_reset_and_grid(window):
    nav = window.globe.navigation
    window.actions["reset"].trigger()
    initial = nav.distance
    window.actions["zoom_in"].trigger()
    assert nav.distance < initial
    window.actions["zoom_out"].trigger()
    assert nav.distance == pytest.approx(initial)
    window.actions["east"].trigger()
    assert nav.longitude == -80
    window.actions["reset"].trigger()
    assert (nav.longitude, nav.latitude) == (-90, 25)
    window.actions["graticule"].trigger()
    assert window.globe.graticule_actor.GetVisibility()
    assert window.actions["graticule"].isChecked()
    window.actions["graticule"].trigger()
    assert not window.globe.graticule_actor.GetVisibility()


def test_keyboard_shortcuts_and_mouse_navigation(window):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    globe = window.globe
    nav = globe.navigation
    globe.reset_view()
    initial = nav.distance
    window.raise_()
    window.activateWindow()
    assert QTest.qWaitForWindowActive(window, 3000), "GUI test window must be active for native shortcuts"
    globe.setFocus()
    QTest.qWait(100)
    QTest.keyClick(globe, Qt.Key.Key_Equal, Qt.KeyboardModifier.ControlModifier)
    assert nav.distance < initial
    QTest.keyClick(globe, Qt.Key.Key_0, Qt.KeyboardModifier.ControlModifier)
    assert nav.distance == pytest.approx(initial)
    QTest.keyClick(globe, Qt.Key.Key_Right)
    assert nav.longitude == -80
    QTest.mousePress(globe, Qt.MouseButton.LeftButton, pos=QPoint(300, 250))
    QTest.mouseMove(globe, QPoint(350, 270))
    QTest.mouseRelease(globe, Qt.MouseButton.LeftButton, pos=QPoint(350, 270))
    assert nav.longitude < -80
    assert nav.latitude > 25
    position = QPointF(350, 270)
    wheel = QWheelEvent(position, QPointF(globe.mapToGlobal(position.toPoint())),
        QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(globe, wheel)
    assert nav.distance < initial
    QTest.mouseClick(globe, Qt.MouseButton.RightButton, pos=QPoint(400, 300))
    QApplication.processEvents()
    assert window.context_menu.isVisible()
    window.context_menu.hide()
    window.actions["context"].trigger()
    assert window.context_menu.isVisible()
    window.context_menu.hide()
    if sys.platform == "darwin":
        QTest.mouseClick(globe, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.MetaModifier, pos=QPoint(400, 300))
        assert window.context_menu.isVisible()
        window.context_menu.hide()
    globe.reset_view()


def test_renderer_produces_textured_globe(window):
    from PySide6.QtWidgets import QApplication
    window.globe.reset_view()
    QApplication.processEvents()
    pixels = window.globe.screenshot(return_img=True)
    h, w = pixels.shape[:2]
    # A blank render can pass widget tests. Require distinct visible image content.
    center = pixels[h//3:2*h//3, w//3:2*w//3, :3]
    assert np.std(center.astype(float)) > 15
    assert np.unique(center.reshape(-1, 3), axis=0).shape[0] > 1000
