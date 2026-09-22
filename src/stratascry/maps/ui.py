# SPDX-License-Identifier: Apache-2.0
"""Native View-menu integration and background jobs for local map packages."""
from pathlib import Path
from shiboken6 import isValid

from PySide6.QtCore import QObject, QStandardPaths, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu,
    QMessageBox, QPlainTextEdit, QProgressDialog, QPushButton, QSlider,
    QSpinBox, QVBoxLayout,
)

from .catalog import Catalog
from .model import PackageError, load_package, validate_bounds
from .renderer import PackageRenderer


class Job(QThread):
    progress = Signal(int, str)
    succeeded = Signal(object)
    failed = Signal(str)
    stopped = Signal()

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation

    def check_cancel(self):
        if self.isInterruptionRequested():
            from .prepare import PreparationCancelled
            raise PreparationCancelled()

    def run(self):
        try:
            result = self.operation(self)
            self.check_cancel()
            self.succeeded.emit(result)
        except Exception as error:
            if self.isInterruptionRequested():
                self.stopped.emit()
            else:
                self.failed.emit(str(error))


class PrepareDialog(QDialog):
    def __init__(self, controller):
        super().__init__(controller.window)
        self.controller = controller
        self.paths = []
        self.setWindowTitle("Prepare Regional Terrain Package")
        self.resize(650, 610)
        layout = QVBoxLayout(self)
        intro = QLabel("Prepare an offline background from downloaded elevation files.\n"
                       "The output is shaded relief for display; graph data is unaffected.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.product = QComboBox()
        self.product.addItem("NASA NASADEM HGT V001 (.hgt or .zip)", "nasadem")
        self.product.addItem("USGS 3DEP elevation (.tif / .tiff)", "usgs")
        form.addRow("Source product", self.product)
        self.source_label = QLabel("No files selected")
        self.source_label.setWordWrap(True)
        source_row = QHBoxLayout()
        source_row.addWidget(self.source_label, 1)
        browse = QPushButton("Choose Files…")
        browse.clicked.connect(self.choose_sources)
        source_row.addWidget(browse)
        form.addRow("Elevation files", source_row)
        self.inspect = QPushButton("Inspect Sources and Set Bounds")
        self.inspect.clicked.connect(self.inspect_sources)
        form.addRow(self.inspect)
        self.name = QLineEdit("Regional terrain")
        form.addRow("Package name", self.name)
        self.bounds = []
        bounds_row = QHBoxLayout()
        for label in ("West", "South", "East", "North"):
            column = QVBoxLayout()
            column.addWidget(QLabel(label))
            spin = QDoubleSpinBox()
            spin.setRange(-180, 180)
            spin.setDecimals(6)
            spin.setSingleStep(.1)
            column.addWidget(spin)
            bounds_row.addLayout(column)
            self.bounds.append(spin)
        form.addRow("Bounds (degrees)", bounds_row)
        self.max_side = QSpinBox()
        self.max_side.setRange(128, 4096)
        self.max_side.setValue(2048)
        self.max_side.setSingleStep(256)
        self.max_side.setSuffix(" pixels")
        form.addRow("Maximum display side", self.max_side)
        self.units = QComboBox()
        for label, value in (("Read source/product metadata", "from_metadata"),
                             ("Metres — explicitly specified", "metres"),
                             ("International feet — explicitly specified", "feet"),
                             ("US survey feet — explicitly specified", "us_survey_feet")):
            self.units.addItem(label, value)
        form.addRow("Elevation units", self.units)
        self.vertical = QLineEdit()
        self.vertical.setPlaceholderText("Optional override, only when known from the source")
        form.addRow("Vertical reference", self.vertical)
        self.source_url = QLineEdit()
        self.source_url.setPlaceholderText("Optional original download URL")
        form.addRow("Source URL", self.source_url)
        self.date = QLineEdit()
        self.date.setPlaceholderText("Optional acquisition date; source metadata is also retained")
        form.addRow("Acquisition date", self.date)
        layout.addLayout(form)
        self.summary = QLabel("Choose elevation files, then inspect them. Display imagery is resampled\n"
                              "to the chosen limit; its effective sampling is recorded in the package.")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.estimate = QLabel()
        self.estimate.setWordWrap(True)
        layout.addWidget(self.estimate)
        self.max_side.valueChanged.connect(self.update_estimate)
        self.update_estimate()
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("Prepare Package…")
        self.buttons.accepted.connect(self.prepare)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.product.currentIndexChanged.connect(self.invalidate)

    def update_estimate(self):
        mib = self.max_side.value()**2 * 4 / 1024**2
        self.estimate.setText(f"At most {mib:.0f} MiB of decoded RGBA pixels. Preparation and GPU copies use additional memory.\n"
                              "Limit: 12° per side, within ±89° latitude; split dateline-crossing regions.")

    def invalidate(self):
        self.summary.setText("Source selection changed; inspect again before preparing.")
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)

    def choose_sources(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose Downloaded Elevation Files", "",
                                               "Elevation (*.hgt *.HGT *.zip *.tif *.tiff);;All files (*)")
        if paths:
            self.paths = paths
            self.source_label.setText("\n".join(Path(path).name for path in paths))
            self.invalidate()

    def inspect_sources(self):
        if not self.paths:
            self.summary.setText("Choose elevation files first.")
            return
        product, paths = self.product.currentData(), list(self.paths)
        def operation(job):
            from .sources import inspect_sources
            return inspect_sources(paths, product, job.check_cancel)
        def ready(report):
            for control, value in zip(self.bounds, report["bounds"]):
                control.setValue(value)
            units = ", ".join(sorted({entry["units"] for entry in report["sources"]}))
            self.summary.setText(f"{len(report['sources'])} elevation file(s). Source elevation units: {units}.\n"
                                 "Adjust bounds if needed, then choose where to save the new package.")
            self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(True)
        self.controller.run_job(operation, ready, "Inspecting elevation sources…", owner=self)

    def prepare(self):
        from .prepare import PrepareOptions, build_package
        try:
            bounds = validate_bounds([field.value() for field in self.bounds])
            if not self.paths or not self.name.text().strip():
                raise PackageError("Choose input files and enter a package name")
        except PackageError as error:
            self.summary.setText(str(error))
            return
        parent = QFileDialog.getExistingDirectory(self, "Choose Parent Folder for New Package")
        if not parent:
            return
        import re
        dirname = re.sub(r"[^\w.-]+", "-", self.name.text().strip()).strip("-.") or "terrain-package"
        destination = str(Path(parent) / dirname)
        if Path(destination).exists():
            self.summary.setText(f"{dirname} already exists in that folder. Change the package name or choose another folder.")
            return
        options = PrepareOptions(self.paths, self.product.currentData(), destination,
            self.name.text(), bounds, self.max_side.value(), self.units.currentData(),
            self.vertical.text(), self.source_url.text(), self.date.text())
        def operation(job):
            output = build_package(options, job.progress.emit, job.isInterruptionRequested)
            return load_package(output, job.check_cancel)
        def ready(package):
            self.controller.activate(package)
            self.controller.renderer.zoom_to_package()
            self.accept()
        self.controller.run_job(operation, ready, "Preparing regional terrain…", owner=self)

    def reject(self):
        if self.controller.job is not None:
            self.controller.job.requestInterruption()
            return
        super().reject()


class MapController(QObject):
    def __init__(self, window, catalog_path=None):
        super().__init__(window)
        self.window = window
        self.renderer = PackageRenderer(window.globe)
        if catalog_path is None:
            catalog_path = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)) / "maps/catalog.json"
        self.catalog = Catalog(catalog_path)
        self.job = None
        self.closing = False
        self.progress_dialog = None
        self.menu = QMenu("Map Packages", window)
        self.group = QActionGroup(self)
        self.dynamic_actions = []
        self._action("map_add", "Add Local Package…", self.add_package)
        self._action("map_prepare", "Prepare Package from Local Data…", self.prepare_package)
        self.menu.addSeparator()
        self.active_menu = self.menu.addMenu("Active Package")
        self._action("map_zoom", "Zoom to Package", self.renderer.zoom_to_package)
        coverage = self._action("map_coverage", "Show Package Coverage", self.renderer.set_coverage_visible, checkable=True)
        coverage.setChecked(True)
        self._action("map_appearance", "Map Appearance…", self.appearance)
        self._action("map_details", "Package Details…", self.details)
        self._action("map_remove", "Remove from Catalog…", self.remove)
        window.view_menu.addSeparator()
        window.view_menu.addMenu(self.menu)
        window.context_menu.addSeparator()
        window.context_menu.addMenu(self.menu)
        window.globe.camera_changed.connect(self.update_status)
        self.refresh()
        if self.catalog.error:
            QTimer.singleShot(0, lambda: self.error(self.catalog.error))
        elif self.catalog.active_id:
            entry = next((entry for entry in self.catalog.entries if entry["id"] == self.catalog.active_id), None)
            if entry:
                QTimer.singleShot(0, lambda: self.open_path(entry["path"]))

    def _action(self, key, name, callback, checkable=False):
        action = self.window._action(key, name, callback, checkable=checkable)
        self.menu.addAction(action)
        return action

    def error(self, message):
        if not self.closing:
            QMessageBox.warning(self.window, "Map Packages", message)

    def save(self):
        try:
            self.catalog.save()
        except (OSError, PackageError) as error:
            self.error(f"The map is usable in this session, but its catalog could not be saved.\n{error}")

    def refresh(self):
        self.active_menu.clear()
        for action in self.dynamic_actions:
            self.group.removeAction(action)
            action.deleteLater()
        self.dynamic_actions = []
        entries = [{"id": None, "name": "None — Blue Marble", "path": None}] + self.catalog.entries
        for entry in entries:
            action = QAction(entry["name"], self)
            action.setMenuRole(QAction.MenuRole.NoRole)
            action.setCheckable(True)
            self.group.addAction(action)
            active = self.renderer.package.id if self.renderer.package else None
            action.setChecked(entry["id"] == active)
            path = entry["path"]
            action.triggered.connect(lambda checked, path=path: self.open_path(path))
            self.active_menu.addAction(action)
            self.dynamic_actions.append(action)
        self.renderer.set_coverage(self.catalog.entries)
        self.set_busy(self.job is not None)
        self.update_status()

    def set_busy(self, busy):
        self.active_menu.setEnabled(not busy)
        for key in ("map_add", "map_prepare", "map_remove"):
            self.window.actions[key].setEnabled(not busy and (key != "map_remove" or bool(self.catalog.entries)))
        for key in ("map_zoom", "map_details"):
            self.window.actions[key].setEnabled(self.renderer.package is not None and not busy)

    def run_job(self, operation, ready, title, owner=None):
        if self.job is not None:
            return
        self.job = Job(operation, self)
        job = self.job
        self.set_busy(True)
        progress = QProgressDialog(title, "Cancel", 0, 100, owner or self.window)
        progress.setWindowTitle("Map Packages")
        progress.setWindowModality(Qt.WindowModality.WindowModal if owner else Qt.WindowModality.NonModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)
        progress.canceled.connect(job.requestInterruption)
        if owner:
            # Cancel hides QProgressDialog before a GDAL operation can finish.
            # Keep the input form fixed until the worker acknowledges cancellation.
            progress.canceled.connect(lambda: owner.setEnabled(False) if isValid(owner) else None)
        job.progress.connect(lambda value, text: (progress.setLabelText(text), progress.setValue(value)))
        self.progress_dialog = progress
        def success(result):
            if not self.closing:
                try:
                    ready(result)
                except Exception as error:
                    self.error(str(error))
        job.succeeded.connect(success)
        job.failed.connect(self.error)
        def finished():
            progress.close()
            progress.deleteLater()
            self.progress_dialog = None
            self.job = None
            if owner and isValid(owner):
                owner.setEnabled(True)
            self.refresh()
            job.deleteLater()
            if self.closing:
                self.window.close()
        job.finished.connect(finished)
        job.start()

    def activate(self, package):
        self.catalog.add(package)
        self.renderer.set_package(package)
        self.catalog.active_id = package.id
        self.save()
        self.refresh()

    def open_path(self, path):
        if path is None:
            self.renderer.set_package(None)
            self.catalog.active_id = None
            self.save()
            self.refresh()
            return
        self.run_job(lambda job: load_package(path, job.check_cancel), self.activate, "Validating local map package…")

    def add_package(self):
        path = QFileDialog.getExistingDirectory(self.window, "Choose a StrataScry Map Package Folder")
        if path:
            self.open_path(path)

    def prepare_package(self):
        dialog = PrepareDialog(self)
        dialog.invalidate()
        dialog.exec()
        dialog.deleteLater()

    def update_status(self):
        package = self.renderer.package
        if package is None:
            self.window.map_status.setText("Blue Marble · Global background · Local terrain: View → Map Packages")
            self.window.map_status.setToolTip("")
            self.window.credit.setText("NASA Blue Marble · August 2004")
            self.window.credit.setToolTip("")
            return
        nav = self.window.globe.navigation
        inside = package.contains(nav.longitude, nav.latitude)
        state = "view center within coverage" if inside else "view center outside coverage · Blue Marble fallback"
        if self.renderer.opacity == 0:
            state = "regional image hidden (0% opacity)"
        self.window.map_status.setText(f"{package.name} · {state}")
        self.window.map_status.setToolTip("Package coverage is a visual map footprint, independent of graph layers.\n" + package.source_name)
        self.window.credit.setText("NASA JPL · NASADEM + Blue Marble" if package.manifest["source"]["product"] == "nasadem"
                                   else "USGS 3DEP · NASA Blue Marble")
        self.window.credit.setToolTip(package.manifest["source"]["credit"] + "\nSee View → Map Packages → Package Details.")

    def details(self):
        package = self.renderer.package
        if package is None:
            return
        dialog = QDialog(self.window)
        dialog.setWindowTitle("Package Details")
        dialog.resize(660, 520)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        display = package.manifest["display"]
        lines = [package.name, package.source_name, "", f"Folder: {package.root}",
                 f"Bounds [west, south, east, north]: {package.bounds}",
                 f"Display: {display['width']} × {display['height']} pixels (resampled)",
                 f"Approximate display spacing at center: {display['approx_sampling_m_at_center'][0]:.1f} × {display['approx_sampling_m_at_center'][1]:.1f} m",
                 "Sampling is not a statement of geographic accuracy.", "",
                 "Coverage outline: simplified valid-data footprint. Grey broken outlines show inactive package bounds.",
                 "Transparent gaps and areas outside the package show the global background.", "",
                 package.manifest["source"]["credit"], package.manifest["source"]["source_url"], ""]
        lines.extend([f"Importer-supplied acquisition date: {package.manifest['source'].get('acquisition_date', 'not supplied')}",
                      "Product identity is declared on import; compatible file layout alone does not certify the provider.", ""])
        for source in package.manifest["source"]["files"]:
            lines.extend([source["file"], f"  Native sampling: {source['sampling_native']} (source CRS units)",
                          f"  Elevation units: {source['units_applied']}", f"  Vertical reference: {source['vertical_reference']}",
                          f"  Acquisition: {source.get('sidecar_metadata',{}).get('acquisition_start') or 'not supplied'} – {source.get('sidecar_metadata',{}).get('acquisition_end') or 'not supplied'}",
                          f"  Source release: {source.get('sidecar_metadata',{}).get('publication_date') or 'not supplied'}"])
        text.setPlainText("\n".join(lines))
        layout.addWidget(text)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.exec()

    def appearance(self):
        dialog = QDialog(self.window)
        dialog.setWindowTitle("Map Appearance")
        layout = QFormLayout(dialog)
        for label, value, callback in (
            ("Regional map opacity", round(self.renderer.opacity*100), self.set_opacity),
            ("Background brightness", round(self.renderer.brightness*100), self.set_brightness)):
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0 if label.startswith("Regional") else 20, 100)
            slider.setValue(value)
            slider.valueChanged.connect(callback)
            layout.addRow(label, slider)
        layout.addRow(QLabel("Coverage outlines remain visible. These settings affect map appearance only."))
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject)
        layout.addRow(close)
        dialog.exec()

    def set_opacity(self, value):
        self.renderer.opacity = value / 100
        self.renderer.apply_appearance()
        self.update_status()

    def set_brightness(self, value):
        self.renderer.brightness = value / 100
        self.renderer.apply_appearance()

    def remove(self):
        entries = list(self.catalog.entries)
        labels = [f"{entry['name']} — {entry['id'][:8]}" for entry in entries]
        value, ok = QInputDialog.getItem(self.window, "Remove from Catalog", "Package files will remain on disk.", labels, 0, False)
        if ok:
            entry = entries[labels.index(value)]
            if self.renderer.package and self.renderer.package.id == entry["id"]:
                self.renderer.set_package(None)
            self.catalog.remove(entry["id"])
            self.save()
            self.refresh()

    def request_close(self):
        if self.job is None:
            return True
        self.closing = True
        self.job.requestInterruption()
        if self.progress_dialog:
            self.progress_dialog.setLabelText("Finishing the current raster operation before closing…")
        return False
