# Copyright 2026 Christopher Leese
# SPDX-License-Identifier: Apache-2.0
"""The textured globe and explicit, bounded map navigation."""
from importlib.resources import files
import math
import os
import sys

# QtPy and VTK must use the same binding as the application's widgets.
os.environ["QT_API"] = "pyside6"

import numpy as np
import pyvista as pv
from PySide6.QtCore import Qt, Signal
from pyvistaqt import QtInteractor
from PySide6.QtWidgets import QApplication

from .geometry import GlobeCamera, globe_mesh_data, surface_point


class GlobeView(QtInteractor):
    camera_changed = Signal()
    context_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent=parent, auto_update=False, multi_samples=4)
        self.navigation = GlobeCamera()
        self._drag_position = None
        self._right_press = None
        self._right_dragged = False
        self.graph_controller = None
        self.setMouseTracking(True)
        self.setAcceptDrops(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.set_background("#080f1c")

        points, faces, uv = globe_mesh_data()
        mesh = pv.PolyData(points, faces)
        mesh.active_texture_coordinates = uv
        texture_path = files("stratascry").joinpath("assets/blue-marble-200408.jpg")
        self.texture = pv.read_texture(str(texture_path))
        self.texture.interpolate = True
        self.texture.repeat = False
        self.earth_actor = self.add_mesh(mesh, texture=self.texture, lighting=False,
                      smooth_shading=False, name="earth", pickable=True)
        self.graticule_actor = self.add_mesh(
            self._graticule(), color="#b5cadb", opacity=0.27,
            line_width=1, lighting=False, name="graticule", pickable=False)
        self.graticule_actor.SetVisibility(False)
        self.reset_view()

    @staticmethod
    def _graticule():
        curves = []
        for latitude in range(-60, 61, 30):
            curves.append(pv.lines_from_points(np.array([
                surface_point(lon, latitude, 1.00012)
                for lon in np.linspace(-180, 180, 361)])))
        for longitude in range(-180, 180, 30):
            curves.append(pv.lines_from_points(np.array([
                surface_point(longitude, lat, 1.00012)
                for lat in np.linspace(-90, 90, 181)])))
        return pv.MultiBlock(curves).combine()

    def apply_camera(self):
        self.camera.position = self.navigation.position
        self.camera.focal_point = (0, 0, 0)
        self.camera.up = self.navigation.view_up
        self.camera.view_angle = self.navigation.VIEW_ANGLE
        # Keep the camera outside the globe and avoid near-surface clipping.
        self.camera.clipping_range = (
            max(0.000001, (self.navigation.distance - 1) * 0.25),
            self.navigation.distance + 2.0)
        self.render()
        self.camera_changed.emit()

    def reset_view(self):
        self.navigation.reset(max(1, self.width()) / max(1, self.height()))
        self.apply_camera()

    def zoom(self, steps: float):
        self.navigation.zoom(steps)
        self.apply_camera()

    def orbit(self, east: float = 0, north: float = 0):
        self.navigation.orbit(east, north)
        self.apply_camera()

    def set_graticule(self, visible: bool):
        self.graticule_actor.SetVisibility(visible)
        self.render()

    def mousePressEvent(self, event):
        self.setFocus()
        if event.button() == Qt.MouseButton.LeftButton:
            if sys.platform == "darwin" and event.modifiers() & Qt.KeyboardModifier.MetaModifier:
                if self.graph_controller: self.graph_controller.cancel_drag()
                self.context_requested.emit(event.globalPosition().toPoint())
            elif self._right_press is None and self.graph_controller:
                self.graph_controller.pointer_press(event.position())
        elif event.button() == Qt.MouseButton.RightButton:
            if self.graph_controller: self.graph_controller.cancel_drag()
            self._right_press = event.position()
            self._drag_position = event.position()
            self._right_dragged = False
        event.accept()

    def mouseMoveEvent(self, event):
        if self._right_press is not None:
            if (event.position()-self._right_press).manhattanLength() >= QApplication.startDragDistance():
                self._right_dragged = True
            if self._right_dragged:
                delta = event.position() - self._drag_position
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                degrees_per_pixel = math.degrees(
                    2 * (self.navigation.distance - 1)
                    * math.tan(math.radians(self.navigation.VIEW_ANGLE / 2))
                    / max(1, self.height()))
                self.orbit(-delta.x() * degrees_per_pixel, delta.y() * degrees_per_pixel)
            self._drag_position = event.position()
        elif self.graph_controller:
            self.graph_controller.pointer_move(event.position())
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            popup = self._right_press is not None and not self._right_dragged and (event.position()-self._right_press).manhattanLength() < QApplication.startDragDistance()
            self._right_press = self._drag_position = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            if popup: self.context_requested.emit(event.globalPosition().toPoint())
        elif event.button() == Qt.MouseButton.LeftButton and self.graph_controller:
            self.graph_controller.pointer_release(event.position())
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "graph_controller", None): self.graph_controller.camera_changed()

    def leaveEvent(self, event):
        if self.graph_controller:
            self.graph_controller.ghost = None
            self.graph_controller.overlay.update()
        super().leaveEvent(event)

    def wheelEvent(self, event):
        delta = event.angleDelta().y() / 120
        if not delta and not event.pixelDelta().isNull():
            delta = event.pixelDelta().y() / 60
        if delta:
            self.zoom(delta)
        event.accept()

    def keyPressEvent(self, event):
        # Do not forward VTK's hidden shortcuts (wireframe, picking, quit, etc.).
        # All commands are Qt actions in the native View menu.
        event.ignore()

    def keyReleaseEvent(self, event):
        event.ignore()

    def mouseDoubleClickEvent(self, event):
        event.accept()

    def contextMenuEvent(self, event):
        # Secondary click is handled above so Cocoa cannot open a second popup.
        event.accept()

    def focusOutEvent(self, event):
        self._drag_position = self._right_press = None
        self._right_dragged = False
        if self.graph_controller: self.graph_controller.focus_lost()
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().focusOutEvent(event)
