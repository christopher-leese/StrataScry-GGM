# SPDX-License-Identifier: Apache-2.0
"""Main-thread tile actors with one bounded, cancellable raster worker."""
from collections import deque
from pathlib import Path
from threading import Condition
import time

import pyvista as pv
import rasterio
from PySide6.QtCore import QObject,QThread,QTimer,QEvent,QStandardPaths,Signal,Slot
from PySide6.QtWidgets import QFileDialog,QMessageBox

from .tiles import TileSet,TileCache,visible_tiles,read_tile,mesh_data,MAX_VISIBLE_TILES,GPU_TILE_BYTES


class TileWorker(QThread):
    tile_ready=Signal(object,object,float)
    failed=Signal(str)

    def __init__(self,tileset,parent=None):
        super().__init__(parent)
        self.tileset=tileset
        self.condition=Condition()
        self.pending=deque()
        self.reading=None
        self.awaiting_ack=False
        self.stopping=False
        self.read_count=0

    def request(self,tiles):
        with self.condition:
            self.pending=deque(tile for tile in dict.fromkeys(tiles) if tile!=self.reading)
            self.condition.notify_all()

    def acknowledge(self):
        with self.condition:
            self.awaiting_ack=False
            self.reading=None
            self.condition.notify_all()

    def stop(self):
        with self.condition:
            self.stopping=True
            self.pending.clear()
            self.condition.notify_all()

    def run(self):
        try:
            # No network rasters are accepted. This handle stays on this worker.
            with rasterio.Env(GDAL_CACHEMAX=32*1024**2,GDAL_NUM_THREADS='1'):
                with rasterio.open(self.tileset.path,driver="GTiff") as source:
                    self.tileset.validate_raster(source)
                    while True:
                        with self.condition:
                            self.condition.wait_for(lambda:self.stopping or (self.pending and not self.awaiting_ack))
                            if self.stopping: return
                            tile=self.reading=self.pending.popleft()
                        start=time.perf_counter()
                        pixels=read_tile(source,self.tileset,tile)
                        elapsed=(time.perf_counter()-start)*1000
                        with self.condition:
                            if self.stopping: return
                            self.awaiting_ack=True
                        self.read_count+=1
                        self.tile_ready.emit(tile,pixels,elapsed)
                        # At most one decoded tile can be waiting in Qt's event queue.
        except Exception as error:
            self.failed.emit(str(error))


class BlueMarbleController(QObject):
    def __init__(self,window,tile_path=None):
        super().__init__(window)
        self.window=window
        self.globe=window.globe
        self.cache=TileCache()
        self.actors={}
        self.wanted=[]
        self.uploads=deque()
        self.worker=None
        self.tileset=None
        self.error=None
        self.closing=False
        self.enabled=True
        self.actor_limit=MAX_VISIBLE_TILES
        self.pending_path=None
        self.read_times=[]
        self.update_times=[]
        self.update_timer=QTimer(self)
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self.update_view)
        self.upload_timer=QTimer(self)
        self.upload_timer.setSingleShot(True)
        self.upload_timer.timeout.connect(self.upload_one)
        self.globe.camera_changed.connect(self.schedule_update)
        self.globe.installEventFilter(self)
        for key,title,callback,checkable in (
            ('bm_detail','Show Blue Marble Detail',self.set_enabled,True),
            ('bm_load','Load Blue Marble Tiles…',self.choose,False),
            ('bm_status','Blue Marble Detail Status…',self.details,False)):
            action=window._action(key,title,callback,checkable=checkable)
            window.view_menu.addAction(action)
            window.context_menu.addAction(action)
            if checkable: action.setChecked(True)
        if tile_path is None:
            tile_path=Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))/'imagery/blue-marble-200408'
        if (Path(tile_path)/'manifest.json').is_file():
            self.load_path(tile_path)
        else:
            self.update_status()

    def eventFilter(self,watched,event):
        if event.type() in (QEvent.Type.Resize,QEvent.Type.Show): self.schedule_update()
        return False

    def schedule_update(self):
        if not self.closing and not self.update_timer.isActive():
            self.update_timer.start(50)

    def set_enabled(self,enabled):
        self.enabled=enabled
        self.schedule_update()

    def clear_actors(self):
        for actor in self.actors.values():
            self.globe.remove_actor(actor,reset_camera=False,render=False)
        self.actors.clear()
        self.uploads.clear()
        self.wanted=[]
        self.globe.render()

    def load_path(self,path):
        try:
            candidate=TileSet.load(path)
        except Exception as error:
            self.error=str(error)
            self.update_status()
            return
        if self.worker is not None:
            self.pending_path=path
            self.worker.stop()
            return
        self.clear_actors()
        self.cache=TileCache()
        self.tileset=candidate
        self.actor_limit=min(MAX_VISIBLE_TILES,GPU_TILE_BYTES//((candidate.tile_size+2)**2*4))
        self.error=None
        worker=self.worker=TileWorker(candidate,self)
        worker.tile_ready.connect(self.receive_tile)
        worker.failed.connect(self.report_failure)
        worker.finished.connect(self.worker_finished)
        worker.start()
        self.schedule_update()

    @Slot(str)
    def report_failure(self,message):
        self.error=message
        self.clear_actors()
        self.update_status()

    @Slot()
    def worker_finished(self):
        worker=self.worker
        self.worker=None
        if worker: worker.deleteLater()
        if self.closing:
            self.window.close()
        elif self.pending_path is not None:
            path,self.pending_path=self.pending_path,None
            self.load_path(path)
        else:
            self.update_status()

    @Slot()
    def update_view(self):
        start=time.perf_counter()
        if self.closing: return
        if not self.enabled or self.tileset is None or self.error:
            self.clear_actors()
            if self.worker: self.worker.request([])
            self.update_status()
            return
        ratio=self.globe.devicePixelRatioF()
        size=(self.globe.width()*ratio,self.globe.height()*ratio)
        self.wanted=visible_tiles(self.globe.navigation,size,self.tileset.max_level,self.tileset.tile_size,self.actor_limit)
        # The packaged overview already supplies these coarse levels. Avoid
        # redundant I/O, actors and textures until the chosen detail is sharper.
        self.wanted=[tile for tile in self.wanted if self.tileset.tile_size*2**(tile.level+1)>self.tileset.manifest.get('fallback_width',0)]
        wanted=set(self.wanted)
        for tile in list(self.actors):
            if tile not in wanted:
                self.globe.remove_actor(self.actors.pop(tile),reset_camera=False,render=False)
        self.uploads=deque(tile for tile in self.wanted if tile not in self.actors and self.cache.get(tile) is not None)
        missing=[tile for tile in self.wanted if tile not in self.actors and self.cache.get(tile) is None]
        if self.worker: self.worker.request(missing)
        if self.uploads and not self.upload_timer.isActive(): self.upload_timer.start(0)
        self.globe.render()
        self.update_status()
        self.update_times.append((time.perf_counter()-start)*1000)
        self.update_times=self.update_times[-100:]

    @Slot(object,object,float)
    def receive_tile(self,tile,pixels,elapsed):
        try:
            if self.closing: return
            self.cache.put(tile,pixels)
            self.read_times.append(elapsed)
            self.read_times=self.read_times[-100:]
            if self.enabled and tile in self.wanted and tile not in self.actors and tile not in self.uploads:
                self.uploads.append(tile)
                if not self.upload_timer.isActive(): self.upload_timer.start(0)
        finally:
            if self.worker: self.worker.acknowledge()

    @Slot()
    def upload_one(self):
        if self.closing or not self.enabled or self.tileset is None: return
        if self.uploads:
            tile=self.uploads.popleft()
            pixels=self.cache.get(tile)
            if tile in self.wanted and tile not in self.actors and pixels is not None and len(self.actors)<self.actor_limit:
                points,faces,uv=mesh_data(tile,self.tileset.tile_size)
                mesh=pv.PolyData(points,faces)
                mesh.active_texture_coordinates=uv
                texture=pv.numpy_to_texture(pixels)
                texture.interpolate=True
                texture.repeat=False
                self.actors[tile]=self.globe.add_mesh(mesh,texture=texture,lighting=False,pickable=False,
                                                     reset_camera=False,render=False)
                self.globe.render()
        self.update_status()
        # One actor/texture upload per event-loop turn, leaving input dispatch free.
        if self.uploads: self.upload_timer.start(0)

    def update_status(self):
        if self.error:
            text='Blue Marble · Global overview · Local detail unavailable'
        elif not self.enabled or self.tileset is None or not self.wanted:
            text='Blue Marble · Global overview'
        elif len(self.actors)<len(self.wanted):
            text='Blue Marble · Loading local detail…'
        else:
            text='Blue Marble · Local detail ready'
        self.window.map_status.setText(text)
        self.window.map_status.setToolTip(self.error or 'NASA Blue Marble, August 2004. Detail loads from local tiles as needed.')

    def choose(self):
        path=QFileDialog.getExistingDirectory(self.window,'Choose a Blue Marble Tile Set')
        if path: self.load_path(path)

    def details(self):
        source=str(self.tileset.path) if self.tileset else 'No local high-resolution tile set is loaded.'
        native=f"{self.tileset.manifest['width']:,} × {self.tileset.manifest['height']:,}" if self.tileset else 'not installed'
        QMessageBox.information(self.window,'Blue Marble Detail',
            f'Native image grid: {native}\nVisible detail tiles: {len(self.actors)} / {self.actor_limit}\n'
            f'Decoded cache: {self.cache.bytes/1024**2:.1f} / {self.cache.limit/1024**2:.0f} MiB\n\n'
            'A 5400 × 2700 global overview remains visible while local detail loads.\n'
            'The finest installed imagery is approximately 500 m sampling.\n'
            'This is historical imagery, not building-level mapping.\n\n'+source+
            ('\n\n'+self.error if self.error else ''))

    def request_close(self):
        self.closing=True
        self.update_timer.stop()
        self.upload_timer.stop()
        if self.worker is not None:
            self.worker.stop()
            return False
        return True
