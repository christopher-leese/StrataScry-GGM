"""Streaming cancellation and renderer resource checks with a desktop event loop."""
import os
import time
import numpy as np
import pytest
from test_blue_marble import tile_set

pytestmark=pytest.mark.skipif(os.environ.get('STRATASCRY_GUI_TESTS')!='1',reason='Desktop GUI opt-in')


def wait_until(condition,seconds=10):
    from PySide6.QtTest import QTest
    deadline=time.monotonic()+seconds
    while not condition():
        assert time.monotonic()<deadline,'Tile operation timed out'
        QTest.qWait(10)


def test_worker_one_inflight_and_replaces_stale_queue(tile_set):
    from stratascry.app import create_application
    from stratascry.blue_marble.controller import TileWorker
    from stratascry.blue_marble.tiles import Tile
    from PySide6.QtTest import QTest
    app=create_application([])
    worker=TileWorker(tile_set)
    received=[]
    worker.tile_ready.connect(lambda key,pixels,elapsed:received.append(key))
    first=Tile(1,0,0)
    latest=Tile(1,3,1)
    worker.request([first,Tile(1,1,0),Tile(1,2,0)])
    worker.start()
    try:
        wait_until(lambda:len(received)==1)
        QTest.qWait(50)
        assert worker.read_count==1  # Back-pressure until main-thread acknowledgement.
        worker.request([latest])
        worker.acknowledge()
        wait_until(lambda:len(received)==2)
        assert received==[first,latest]
    finally:
        worker.stop()
        assert worker.wait(2000)


def test_tiled_view_load_pan_hide_and_close(tile_set,tmp_path):
    from PySide6.QtTest import QTest
    from stratascry.app import create_application
    from stratascry.window import MainWindow
    app=create_application([])
    window=MainWindow(tile_path=tile_set.root)
    window.show()
    controller=window.blue_marble
    try:
        wait_until(lambda:bool(controller.wanted) and len(controller.actors)==len(controller.wanted))
        assert not controller.error
        assert controller.cache.bytes<=controller.cache.limit
        assert len(controller.actors)<=32
        assert controller.worker.read_count>0
        reads=controller.worker.read_count
        controller.update_view()
        QTest.qWait(50)
        assert controller.worker.read_count==reads  # Cached redraw does no raster I/O.
        window.globe.orbit(east=180)
        wait_until(lambda:bool(controller.wanted) and len(controller.actors)==len(controller.wanted))
        assert controller.cache.bytes<=controller.cache.limit
        window.actions['bm_detail'].trigger()
        wait_until(lambda:not controller.actors)
        assert 'Global overview' in window.map_status.text()
        assert window.maps is None
    finally:
        window.close()
        wait_until(lambda:controller.worker is None)
        assert not window.isVisible()
        window.deleteLater()
        from PySide6.QtCore import QEvent
        app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()


def test_no_detail_io_when_overview_is_sufficient(tile_set,tmp_path):
    from PySide6.QtTest import QTest
    from stratascry.app import create_application
    from stratascry.window import MainWindow
    app=create_application([])
    window=MainWindow(tile_path=tile_set.root)
    controller=window.blue_marble
    # A matching overview supplies this fixture's entire resolution range.
    controller.tileset.manifest['fallback_width']=controller.tileset.manifest['width']
    window.show()
    try:
        QTest.qWait(200)
        assert not controller.error
        assert controller.wanted==[] and not controller.actors
        assert controller.worker.read_count==0 and controller.cache.bytes==0
        assert 'Global overview' in window.map_status.text()
    finally:
        window.close()
        wait_until(lambda:controller.worker is None)
        window.deleteLater()
        from PySide6.QtCore import QEvent
        app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()
