# SPDX-License-Identifier: Apache-2.0
"""Geographic quadtree, conservative visibility, and bounded local raster reads."""
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
import json
import math
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import Window

from ..geometry import surface_point

TILE_RADIUS=1.0001  # Visual separation above the coarse fallback sphere.
MAX_VISIBLE_TILES=32
CACHE_BYTES=96*1024**2
GPU_TILE_BYTES=64*1024**2


@dataclass(frozen=True)
class Tile:
    level: int
    x: int
    y: int

    @property
    def bounds(self):
        span=180/2**self.level
        w=-180+self.x*span
        n=90-self.y*span
        return w,n-span,w+span,n

    def children(self):
        return [Tile(self.level+1,2*self.x+x,2*self.y+y) for y in (0,1) for x in (0,1)]

    @property
    @lru_cache(maxsize=16384)
    def sphere(self):
        w,s,e,n=self.bounds
        lon,lat=(w+e)/2,(s+n)/2
        axis=surface_point(lon,lat)
        cosine=min(float(np.dot(axis,surface_point(edge,phi))) for edge in (w,e) for phi in (s,n))
        cosine=max(0,min(1,cosine))
        return axis*cosine*TILE_RADIUS, math.sqrt(max(0,1-cosine*cosine))*TILE_RADIUS


@dataclass
class TileSet:
    root: Path
    path: Path
    manifest: dict

    @property
    def tile_size(self): return self.manifest['tile_size']
    @property
    def max_level(self): return self.manifest['max_level']

    @classmethod
    def load(cls, root):
        root=Path(root).expanduser().resolve()
        path=root/'manifest.json'
        if path.stat().st_size>1024*1024:
            raise ValueError('Blue Marble manifest is too large')
        m=json.loads(path.read_text())
        if m.get('format')!='stratascry-blue-marble' or m.get('version')!=1:
            raise ValueError('Unsupported Blue Marble tile set')
        size,level=m['tile_size'],m['max_level']
        if type(size) is not int or not 8<=size<=1024 or type(level) is not int or not 0<=level<=8:
            raise ValueError('Unsupported tile size or detail level')
        if (m['width'],m['height'])!=(size*2**(level+1),size*2**level):
            raise ValueError('Tile grid dimensions are inconsistent')
        if type(m.get('fallback_width',0)) is not int or not 0<=m.get('fallback_width',0)<=m['width']:
            raise ValueError('Invalid fallback resolution')
        if m['bounds']!=[-180,-90,180,90] or m['crs']!='EPSG:4326':
            raise ValueError('Expected global WGS84 imagery')
        raster=(root/m['file']).resolve()
        if not raster.is_relative_to(root) or not raster.is_file() or raster.suffix.lower() not in ('.tif','.tiff'):
            raise ValueError('Missing or unsafe local tile raster')
        return cls(root,raster,m)

    def validate_raster(self, source):
        if source.driver!='GTiff' or any(max(shape)>1024 for shape in source.block_shapes):
            raise ValueError('Expected a GeoTIFF with storage blocks no larger than 1024 pixels')
        if (source.width,source.height,source.count)!=(self.manifest['width'],self.manifest['height'],3):
            raise ValueError('Tile raster dimensions do not match its manifest')
        if source.dtypes!=('uint8',)*3 or source.crs!=rasterio.crs.CRS.from_epsg(4326):
            raise ValueError('Expected RGB byte imagery in EPSG:4326')
        if not np.allclose(source.bounds,(-180,-90,180,90),rtol=0,atol=1e-7):
            raise ValueError('Unexpected geographic extent')
        if source.transform.b or source.transform.d or source.transform.a<=0 or source.transform.e>=0:
            raise ValueError('Unsupported raster orientation')
        if self.max_level and (not source.profile.get("tiled",False) or not source.overviews(1) or max(source.overviews(1))<2**self.max_level):
            raise ValueError('A tiled raster with reduced-resolution overviews is required')


def visible_tiles(nav, viewport, max_level, tile_size=675, budget=MAX_VISIBLE_TILES):
    """Select frustum/horizon-visible leaves, relaxing detail to respect actor budget."""
    width,height=viewport
    normal=surface_point(nav.longitude,nav.latitude)
    up=np.asarray(nav.view_up)
    right=np.cross(up,normal)
    tv=math.tan(math.radians(nav.VIEW_ANGLE/2))
    th=tv*max(1,width)/max(1,height)
    focal=max(1,height)/(2*tv)
    def visit(tile, threshold, output):
        center,radius=tile.sphere
        projection=float(np.dot(center,normal))
        if projection+radius<1/nav.distance:
            return
        depth=nav.distance-projection
        horizontal,vertical=abs(float(np.dot(center,right))),abs(float(np.dot(center,up)))
        if horizontal-depth*th>radius*math.sqrt(1+th*th) or vertical-depth*tv>radius*math.sqrt(1+tv*tv):
            return
        projected=2*radius*focal/max(depth-radius,nav.distance-TILE_RADIUS,1e-5)
        if tile.level<max_level and projected>threshold:
            for child in tile.children(): visit(child,threshold,output)
        else:
            output.append(tile)
    threshold=tile_size*1.15
    for _ in range(32):
        output=[]
        for x in (0,1): visit(Tile(0,x,0),threshold,output)
        if len(output)<=budget:
            return sorted(output,key=lambda t:-float(np.dot(t.sphere[0],normal)))
        threshold*=1.4
    return [Tile(0,0,0),Tile(0,1,0)]


def read_tile(source, tileset, tile):
    """Read one overview-backed tile, wrap longitude and clamp polar gutters."""
    n=tileset.tile_size
    if not 0<=tile.level<=tileset.max_level or not 0<=tile.x<2**(tile.level+1) or not 0<=tile.y<2**tile.level:
        raise ValueError('Tile address is out of range')
    factor=2**(tileset.max_level-tile.level)
    x0,y0=(tile.x*n-1)*factor,(tile.y*n-1)*factor
    x1,y1=x0+(n+2)*factor,y0+(n+2)*factor
    left,top=max(0,x0),max(0,y0)
    right,bottom=min(source.width,x1),min(source.height,y1)
    ox,oy=(left-x0)//factor,(top-y0)//factor
    width,height=(right-left)//factor,(bottom-top)//factor
    out=np.empty((3,n+2,n+2),dtype=np.uint8)
    out[:,oy:oy+height,ox:ox+width]=source.read((1,2,3),window=Window(left,top,right-left,bottom-top),
                        out_shape=(3,height,width),resampling=Resampling.bilinear)
    if ox:
        out[:,oy:oy+height,0:1]=source.read((1,2,3),window=Window(source.width-factor,top,factor,bottom-top),
                                  out_shape=(3,height,1),resampling=Resampling.bilinear)
    if ox+width<n+2:
        out[:,oy:oy+height,-1:]=source.read((1,2,3),window=Window(0,top,factor,bottom-top),
                                   out_shape=(3,height,1),resampling=Resampling.bilinear)
    if oy: out[:,0,:]=out[:,1,:]
    if oy+height<n+2: out[:,-1,:]=out[:,-2,:]
    return np.ascontiguousarray(np.moveaxis(out,0,-1))


class TileCache:
    def __init__(self, limit=CACHE_BYTES):
        self.limit=limit
        self.bytes=0
        self.items=OrderedDict()

    def get(self,key):
        value=self.items.get(key)
        if value is not None: self.items.move_to_end(key)
        return value

    def put(self,key,value):
        old=self.items.pop(key,None)
        if old is not None: self.bytes-=old.nbytes
        if value.nbytes>self.limit: return
        self.items[key]=value
        self.bytes+=value.nbytes
        while self.bytes>self.limit:
            _,removed=self.items.popitem(last=False)
            self.bytes-=removed.nbytes


def mesh_data(tile, size):
    w,s,e,n=tile.bounds
    step=2**(-tile.level/2)
    columns,rows=max(2,math.ceil((e-w)/step)),max(2,math.ceil((n-s)/step))
    lon,lat=np.meshgrid(np.linspace(w,e,columns+1),np.linspace(s,n,rows+1))
    l,p=np.radians(lon),np.radians(lat)
    points=TILE_RADIUS*np.column_stack(((np.cos(p)*np.cos(l)).ravel(),(np.cos(p)*np.sin(l)).ravel(),np.sin(p).ravel()))
    first=(np.arange(rows)[:,None]*(columns+1)+np.arange(columns)).ravel()
    faces=np.column_stack((np.full(first.size,4),first,first+1,first+columns+2,first+columns+1)).ravel()
    u=(((lon-w)/(e-w)*size+1)/(size+2)).ravel()
    v=(((lat-s)/(n-s)*size+1)/(size+2)).ravel()
    uv=np.column_stack((u,v))
    return points,faces,uv
