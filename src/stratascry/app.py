# Copyright 2026 Christopher Leese
# SPDX-License-Identifier: Apache-2.0
"""Application entry point. Launch with `python -m stratascry`."""
import argparse
import sys
import traceback

from PySide6.QtCore import Qt
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication, QMessageBox


def create_application(argv=None):
    existing = QApplication.instance()
    if existing is not None:
        return existing
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    surface_format = QSurfaceFormat()
    surface_format.setSamples(4)
    QSurfaceFormat.setDefaultFormat(surface_format)
    application = QApplication(sys.argv if argv is None else argv)
    application.setApplicationName("StrataScry GGM")
    application.setApplicationDisplayName("StrataScry GGM")
    application.setOrganizationName("StrataScry")
    return application


def main():
    parser = argparse.ArgumentParser(description="StrataScry Blue Marble globe prototype")
    parser.add_argument("--map-packages", action="store_true",
                        help="Enable the experimental regional terrain tools")
    args, qt_args = parser.parse_known_args()
    application = create_application([sys.argv[0], *qt_args])
    try:
        from .window import MainWindow
        window = MainWindow(enable_map_packages=args.map_packages)
    except Exception:
        details = traceback.format_exc()
        print(details, file=sys.stderr)
        box = QMessageBox(QMessageBox.Icon.Critical, "StrataScry GGM",
            "The globe viewer could not start. Check that the package, its bundled "
            "imagery, and graphics dependencies are installed. See Details for the error.")
        box.setDetailedText(details)
        box.exec()
        return 1
    window.show()
    window.raise_()
    window.activateWindow()
    return application.exec()
