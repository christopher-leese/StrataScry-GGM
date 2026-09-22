"""Tile-grid, visibility, storage, seam and explicit resource-budget checks."""
import json
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from stratascry.geometry import GlobeCamera
from stratascry.blue_marble.build import write_pyramid
from stratascry.blue_marble.tiles import Tile,TileSet,TileCache,read_tile,visible_tiles,mesh_data,TILE_RADIUS


@pytest.fixture(scope='module')
def tile_set(tmp_path_factory):
    root=tmp_path_factory.mktemp('blue-marble')
    source=root/'source.tif'
    rows,cols=np.mgrid[:1024,:2048]
    pixels=np.stack((cols//8,rows//4,np.full(cols.shape,50))).astype('uint8')
    with rasterio.open(source,'w',driver='GTiff',count=3,width=2048,height=1024,
                       dtype='uint8',crs='EPSG:4326',transform=from_bounds(-180,-90,180,90,2048,1024)) as dst:
        dst.write(pixels)
    target=write_pyramid(source,root/'tiles',tile_size=512,max_level=1,provenance=[])
    return TileSet.load(target)


def test_overviews_and_geographic_validation(tile_set):
    with rasterio.open(tile_set.path) as raster:
        tile_set.validate_raster(raster)
        assert raster.profile.get("tiled") and raster.overviews(1)
    assert tile_set.manifest['width']==2048


def test_wrapped_and_polar_gutters_match_neighbors(tile_set):
    with rasterio.open(tile_set.path) as raster:
        tile_set.validate_raster(raster)
        west=read_tile(raster,tile_set,Tile(1,0,0))
        east=read_tile(raster,tile_set,Tile(1,1,0))
        last=read_tile(raster,tile_set,Tile(1,3,0))
        assert west.shape==(514,514,3)
        np.testing.assert_array_equal(west[:,0],last[:,-2])
        np.testing.assert_array_equal(west[:,-1],east[:,1])
        np.testing.assert_array_equal(east[:,0],west[:,-2])
        np.testing.assert_array_equal(west[0],west[1])
        south=read_tile(raster,tile_set,Tile(1,0,1))
        np.testing.assert_array_equal(south[-1],south[-2])
        coarse=read_tile(raster,tile_set,Tile(0,0,0))
        assert coarse.shape==west.shape
        assert coarse.nbytes==514*514*3


def test_cache_enforces_byte_limit_and_lru():
    cache=TileCache(30)
    cache.put('a',np.zeros(10,dtype='uint8'))
    cache.put('b',np.zeros(10,dtype='uint8'))
    cache.put('c',np.zeros(10,dtype='uint8'))
    cache.get('a')
    cache.put('d',np.zeros(10,dtype='uint8'))
    assert cache.get('b') is None and cache.get('a') is not None
    cache.put('oversized',np.zeros(31,dtype='uint8'))
    assert cache.bytes==30 and cache.get('oversized') is None


@pytest.mark.parametrize('lon,lat,distance,viewport',[
    (-90,25,3.6,(2360,1350)),(-100,40,1.5,(2360,1350)),
    (-122.6,37.9,1.03,(2360,1350)),(179.99,30,1.01,(2360,1350)),
    (-179.99,-30,1.01,(2360,1350)),(10,89,1.005,(2360,1350)),
    (10,-89,1.005,(1350,2360)),(0,0,3.6,(10000,10000)),
])
def test_selection_covers_center_and_respects_budget(lon,lat,distance,viewport):
    nav=GlobeCamera(lon,lat,distance)
    tiles=visible_tiles(nav,viewport,6)
    assert 0<len(tiles)<=32
    assert len(set(tiles))==len(tiles)
    assert any(t.bounds[0]<=lon<=t.bounds[2] and t.bounds[1]<=lat<=t.bounds[3] for t in tiles)
    assert all(0<=t.level<=6 for t in tiles)
    if distance<1.04 and abs(lat)<75: assert max(t.level for t in tiles)>=5
    # Polar convergence can intentionally reduce detail to stay inside the budget.


def test_mesh_uv_orientation_and_radius():
    tile=Tile(6,20,10)
    points,faces,uv=mesh_data(tile,675)
    assert np.allclose(np.linalg.norm(points,axis=1),TILE_RADIUS)
    assert uv.min()==pytest.approx(1/677)
    assert uv.max()==pytest.approx(676/677)
    assert uv[0,1]<uv[-1,1]  # South-to-north VTK mesh convention.
    assert np.all(faces.reshape(-1,5)[:,0]==4)


def test_manifest_path_escape_and_invalid_grid(tile_set,tmp_path):
    data=dict(tile_set.manifest)
    data['file']='../escape.tif'
    (tmp_path/'manifest.json').write_text(json.dumps(data))
    with pytest.raises(ValueError,match='unsafe|Missing'):
        TileSet.load(tmp_path)
    data['width']+=1
    (tmp_path/'manifest.json').write_text(json.dumps(data))
    with pytest.raises(ValueError,match='dimensions'):
        TileSet.load(tmp_path)
