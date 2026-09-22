# Copyright 2026 Christopher Leese
# SPDX-License-Identifier: Apache-2.0
"""Desktop shell with one action registry for menus and keyboard shortcuts."""
import sys

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu,
    QMessageBox, QVBoxLayout, QWidget,
)

from .globe import GlobeView


class MainWindow(QMainWindow):
    def __init__(self, catalog_path=None, *, enable_map_packages=False, tile_path=None):
        super().__init__()
        self.setWindowTitle("StrataScry GGM — Globe")
        self.resize(1180, 820)
        self.setMinimumSize(640, 480)
        self.actions: dict[str, QAction] = {}

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QFrame()
        header.setObjectName("header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 17, 24, 17)
        brand = QLabel("StrataScry <span style='color:#87a2b8;font-weight:400'>GGM</span>")
        brand.setObjectName("brand")
        header_layout.addWidget(brand)
        header_layout.addStretch()
        label = QLabel("GLOBE WORKSPACE")
        label.setObjectName("workspaceLabel")
        header_layout.addWidget(label)
        layout.addWidget(header)
        self.map_status = QLabel("Blue Marble · Global overview")
        self.map_status.setTextFormat(Qt.TextFormat.PlainText)
        self.map_status.setStyleSheet("color: #aebfd0; background: #101c2b; padding: 7px 24px; font-size: 12px;")
        from PySide6.QtWidgets import QSizePolicy
        self.map_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.map_status)
        self.globe = GlobeView(body)
        layout.addWidget(self.globe, 1)

        footer = QFrame()
        footer.setObjectName("footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(24, 10, 24, 10)
        credit = self.credit = QLabel("NASA Blue Marble · August 2004")
        credit.setToolTip("Imagery: Reto Stöckli, NASA Earth Observatory. See View → Imagery Credits.")
        footer_layout.addWidget(credit)
        footer_layout.addStretch()
        self.coordinates = QLabel()
        self.coordinates.setAlignment(Qt.AlignmentFlag.AlignRight)
        footer_layout.addWidget(self.coordinates)
        layout.addWidget(footer)
        self.setCentralWidget(body)
        self.setStyleSheet("""
            QMainWindow { background: #080f1c; }
            QFrame#header { background: #101c2b; border-bottom: 1px solid #203145; }
            QFrame#footer { background: #101c2b; border-top: 1px solid #203145; }
            QFrame#header QLabel, QFrame#footer QLabel { color: #aebfd0; background: transparent; }
            QLabel#brand { color: #ecf2f8; font-size: 23px; font-weight: 600; }
            QLabel#workspaceLabel { color: #87a2b8; font-size: 11px; letter-spacing: 2px; }
            QFrame#footer QLabel { font-size: 12px; }
        """)
        self._build_menus()
        self.globe.camera_changed.connect(self._update_status)
        self.globe.context_requested.connect(self.show_context_menu)
        self._update_status()
        self.maps = None
        self.blue_marble = None
        if enable_map_packages:
            from .maps.ui import MapController
            self.maps = MapController(self, catalog_path)
        else:
            from .blue_marble.controller import BlueMarbleController
            self.blue_marble = BlueMarbleController(self, tile_path)
        # Reset after layout has established the actual viewport aspect ratio.
        QTimer.singleShot(0, self.globe.reset_view)

    def _action(self, key, title, callback, shortcuts=(), checkable=False):
        action = QAction(title, self)
        action.setObjectName(key)
        action.setMenuRole(QAction.MenuRole.NoRole)
        action.setCheckable(checkable)
        action.setShortcuts([QKeySequence(shortcut) for shortcut in shortcuts])
        if checkable:
            action.toggled.connect(callback)
        else:
            action.triggered.connect(lambda checked=False: callback())
        self.actions[key] = action
        self.addAction(action)
        return action

    def _build_menus(self):
        bar = self.menuBar()
        bar.setNativeMenuBar(True)
        file_menu = bar.addMenu("&File")
        quit_action = QAction("Quit StrataScry GGM", self)
        quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # Qt's portable Ctrl modifier is Command on macOS.
        self._action("zoom_in", "Zoom In", lambda: self.globe.zoom(1), ("Ctrl++", "Ctrl+=", "+", "="))
        self._action("zoom_out", "Zoom Out", lambda: self.globe.zoom(-1), ("Ctrl+-", "-"))
        self._action("reset", "Reset View", self.globe.reset_view, ("Ctrl+0",))
        self._action("west", "Rotate West", lambda: self.globe.orbit(east=-10), ("Left",))
        self._action("east", "Rotate East", lambda: self.globe.orbit(east=10), ("Right",))
        self._action("north", "Rotate North", lambda: self.globe.orbit(north=10), ("Up",))
        self._action("south", "Rotate South", lambda: self.globe.orbit(north=-10), ("Down",))
        self._action("graticule", "Show Latitude / Longitude Grid", self.globe.set_graticule, ("Ctrl+G",), True)
        # macOS inserts Enter / Exit Full Screen into the native View menu.
        # Adding our own would duplicate that system command and shortcut.
        if sys.platform != "darwin":
            self._action("fullscreen", "Full Screen", self._set_fullscreen, ("F11",), True)
        self._action("context", "Show Context Menu", self.show_context_menu, ("Shift+F10",))
        self._action("help", "Navigation Help…", self._show_navigation_help, ("?",))
        self._action("credits", "Imagery Credits…", self._show_credits)
        self.view_menu = bar.addMenu("&View")
        self._populate_view_menu(self.view_menu, include_context=True)
        self.context_menu = QMenu(self)
        self._populate_view_menu(self.context_menu, include_context=False)

    def _populate_view_menu(self, menu, include_context):
        for key in ("zoom_in", "zoom_out", "reset"):
            menu.addAction(self.actions[key])
        menu.addSeparator()
        navigation = menu.addMenu("Rotate")
        for key in ("west", "east", "north", "south"):
            navigation.addAction(self.actions[key])
        menu.addAction(self.actions["graticule"])
        if "fullscreen" in self.actions:
            menu.addAction(self.actions["fullscreen"])
        menu.addSeparator()
        if include_context:
            menu.addAction(self.actions["context"])
        menu.addAction(self.actions["help"])
        menu.addAction(self.actions["credits"])

    def show_context_menu(self, position=None):
        if position is None:
            position = self.globe.mapToGlobal(QPoint(self.globe.width() // 2, self.globe.height() // 2))
        self.context_menu.popup(position)

    def _set_fullscreen(self, enabled):
        if enabled:
            self.showFullScreen()
        else:
            self.showNormal()

    def changeEvent(self, event):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.WindowStateChange and "fullscreen" in self.actions:
            action = self.actions["fullscreen"]
            action.blockSignals(True)
            action.setChecked(self.isFullScreen())
            action.blockSignals(False)
        super().changeEvent(event)

    def _update_status(self):
        nav = self.globe.navigation
        latitude = f"{abs(nav.latitude):.1f}°{'N' if nav.latitude >= 0 else 'S'}"
        longitude = f"{abs(nav.longitude):.1f}°{'E' if nav.longitude >= 0 else 'W'}"
        self.coordinates.setText(f"View center  {latitude}  {longitude}")

    def _show_navigation_help(self):
        command = "⌘" if sys.platform == "darwin" else "Ctrl+"
        QMessageBox.information(self, "Globe Navigation",
            "Drag with the left mouse button to rotate the globe.\n"
            "Scroll vertically (mouse wheel or trackpad) to zoom.\n"
            "Right-click, or Control-click on macOS, for the context menu.\n\n"
            f"Zoom: {command}+ / {command}− (or + / −)\n"
            f"Reset view: {command}0\n"
            "Rotate: arrow keys\n"
            f"Latitude / longitude grid: {command}G\n"
            "Context menu: Shift+F10\n\n"
            "All navigation actions are available in the View menu.\n"
            "The globe stays north-up. Zoom stops above the surface.\n"
            "Blue Marble detail loads from local tiles as you zoom and pan.\n"
            "Zoom enlarges that image; the globe remains a sphere.")

    def _show_credits(self):
        box = QMessageBox(self)
        box.setWindowTitle("Imagery Credits")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(
            "<b>NASA Blue Marble: Next Generation</b><br>"
            "August 2004 · topography and bathymetry<br><br>"
            "Image credit: Reto Stöckli, NASA Earth Observatory.<br>"
            "Global overview: 5400 × 2700 pixels.<br>"
            "Optional full-resolution tiles: 86,400 × 43,200 source grid.<br>"
            "Only visible detail is loaded; see View → Blue Marble Detail Status.<br><br>"
            "<a href='https://science.nasa.gov/earth/earth-observatory/collections/blue-marble/'>NASA Blue Marble collection</a><br>"
            "<a href='https://www.nasa.gov/nasa-brand-center/images-and-media/'>NASA image use guidelines</a><br><br>"
            "Imagery credit does not imply NASA endorsement.<br>"
            "Terrain shading is part of the image; the globe surface is a sphere."
        )
        box.exec()

    def closeEvent(self, event):
        if self.maps is not None and not self.maps.request_close():
            event.ignore()
            return
        if self.blue_marble is not None and not self.blue_marble.request_close():
            event.ignore()
            return
        self.globe.close()
        event.accept()
