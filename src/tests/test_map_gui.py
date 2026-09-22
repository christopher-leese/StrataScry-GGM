"""Desktop package integration: asynchronous jobs, menu state and rendered pixels."""
import os
import time
from threading import Event

import numpy as np
import pytest

from test_map_packages import elevation, prepared

pytestmark = pytest.mark.skipif(os.environ.get('STRATASCRY_GUI_TESTS') != '1', reason='Desktop GUI opt-in')


def wait_for(predicate, timeout=10000):
    from PySide6.QtTest import QTest
    deadline = time.monotonic() + timeout/1000
    while not predicate():
        assert time.monotonic() < deadline, 'Timed out waiting for Qt background job'
        QTest.qWait(10)


def screenshot(view):
    # QtInteractor dispatches render signals asynchronously on macOS.
    from PySide6.QtTest import QTest
    QTest.qWait(100)
    return view.globe.screenshot(return_img=True)


@pytest.fixture
def view(tmp_path):
    from stratascry.app import create_application
    from stratascry.window import MainWindow
    from PySide6.QtTest import QTest
    app = create_application([])
    window = MainWindow(catalog_path=tmp_path/'catalog.json', enable_map_packages=True)
    window.show()
    QTest.qWait(100)
    yield window
    window.close()
    wait_for(lambda: window.maps.job is None)
    app.processEvents()


def test_async_load_coverage_switch_and_render(view, prepared):
    view.maps.open_path(str(prepared))
    wait_for(lambda: view.maps.job is None)
    renderer = view.maps.renderer
    assert renderer.package.root == prepared
    view.actions['map_zoom'].trigger()
    assert 'within coverage' in view.map_status.text()
    assert renderer.borders
    assert all(a.GetMapper().GetInput().GetNumberOfVerts() == 0 for a in renderer.borders)
    view.actions['map_coverage'].trigger()
    assert all(not a.GetVisibility() for a in renderer.borders)
    normal = screenshot(view)
    view.maps.set_brightness(25)
    dim = screenshot(view)
    assert dim[:,:,:3].mean() < normal[:,:,:3].mean() * .65
    view.maps.set_brightness(100)
    view.maps.set_opacity(0)
    fallback = screenshot(view)
    assert np.abs(normal.astype(float)-fallback).mean() > 10
    assert 'hidden' in view.map_status.text()
    view.maps.open_path(None)
    assert renderer.actor is None
    assert not view.actions['map_zoom'].isEnabled()
    assert len(view.maps.catalog.entries) == 1
    assert (prepared/'manifest.json').exists()


def test_texture_orientation_and_transparent_hole(view, prepared):
    from stratascry.geometry import surface_point
    from stratascry.maps.model import load_package
    from stratascry.maps.renderer import PATCH_RADIUS
    package = load_package(prepared)
    h,w = package.rgba.shape[:2]
    package.rgba[:h//2,:w//2] = [255,0,0,255]     # Northwest
    package.rgba[:h//2,w//2:] = [0,255,0,255]     # Northeast
    package.rgba[h//2:,:w//2] = [0,0,255,255]     # Southwest
    package.rgba[h//2:,w//2:] = [255,255,0,255]   # Southeast
    package.rgba[h//3:2*h//3,w//3:2*w//3,3] = 0 # Transparent center
    renderer = view.maps.renderer
    view.maps.activate(package)
    renderer.zoom_to_package()
    renderer.set_coverage_visible(False)
    pixels = screenshot(view)
    vtk_renderer = view.globe.renderer
    west,south,east,north = package.bounds
    def pixel(lon,lat):
        vtk_renderer.SetWorldPoint(*surface_point(lon,lat,PATCH_RADIUS),1)
        vtk_renderer.WorldToDisplay()
        x,y,_=vtk_renderer.GetDisplayPoint()
        return pixels[pixels.shape[0]-1-round(y),round(x),:3].astype(int)
    for u,v,expected in [(.2,.8,[255,0,0]),(.8,.8,[0,255,0]),(.2,.2,[0,0,255]),(.8,.2,[255,255,0])]:
        assert np.max(np.abs(pixel(west+(east-west)*u,south+(north-south)*v)-expected)) < 5
    center = pixel((west+east)/2,(south+north)/2)
    renderer.actor.SetVisibility(False)
    view.globe.render()
    background = screenshot(view)
    original = pixels
    pixels = background
    assert np.max(np.abs(center-pixel((west+east)/2,(south+north)/2))) < 3
    # Corners fit inside the viewport, including a margin.
    for lon,lat in [(west,south),(west,north),(east,south),(east,north)]:
        vtk_renderer.SetWorldPoint(*surface_point(lon,lat,PATCH_RADIUS),1)
        vtk_renderer.WorldToDisplay()
        x,y,z=vtk_renderer.GetDisplayPoint()
        assert 0 < x < original.shape[1] and 0 < y < original.shape[0] and 0 < z < 1


def test_prepare_dialog_job_and_gui_thread(view, elevation, tmp_path, monkeypatch):
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QFileDialog, QDialogButtonBox
    from stratascry.maps.ui import PrepareDialog
    dialog = PrepareDialog(view.maps)
    dialog.product.setCurrentIndex(1)
    dialog.paths = [str(elevation)]
    dialog.show()
    dialog.inspect_sources()
    assert view.maps.progress_dialog.parent() == dialog
    wait_for(lambda: view.maps.job is None)
    assert dialog.buttons.button(QDialogButtonBox.StandardButton.Save).isEnabled()
    dialog.max_side.setValue(128)
    dialog.name.setText('GUI terrain')
    monkeypatch.setattr(QFileDialog,'getExistingDirectory',lambda *args: str(tmp_path))
    observed=[]
    original = view.maps.activate
    def activate(package):
        observed.append(QThread.currentThread() == view.thread())
        original(package)
    monkeypatch.setattr(view.maps,'activate',activate)
    dialog.prepare()
    wait_for(lambda: view.maps.job is None)
    assert observed == [True]
    assert view.maps.renderer.package.name == 'GUI terrain'
    assert not dialog.isVisible()
    dialog.deleteLater()


def test_close_waits_for_background_cancel(view):
    started = Event()
    def operation(job):
        started.set()
        while not job.isInterruptionRequested():
            started.wait(.002) if not started.is_set() else time.sleep(.002)
        job.check_cancel()
    view.maps.run_job(operation,lambda result: pytest.fail('Cancelled job activated'), 'Test cancellation')
    wait_for(started.is_set)
    view.close()
    wait_for(lambda: view.maps.job is None)
    assert not view.isVisible()


def test_minimum_altitude_does_not_clip_terrain(view, prepared):
    from stratascry.maps.model import load_package
    package = load_package(prepared)
    package.rgba[:,:,:] = [255,0,0,255]
    view.maps.activate(package)
    view.maps.renderer.zoom_to_package()
    view.globe.navigation.distance = view.globe.navigation.MIN_DISTANCE
    view.globe.apply_camera()
    image = screenshot(view)
    h,w = image.shape[:2]
    assert np.max(np.abs(image[h//2,w//2,:3].astype(int)-[255,0,0])) < 3
