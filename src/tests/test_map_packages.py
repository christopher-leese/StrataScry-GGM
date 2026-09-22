"""Meaningful package, projection, masking, and source-format regression checks."""
import json
from pathlib import Path
import shutil
import zipfile

import numpy as np
from PIL import Image
import pytest
import rasterio
from rasterio.transform import from_bounds, from_origin

from stratascry.maps.catalog import Catalog
from stratascry.maps.model import PackageError, load_package, validate_bounds
from stratascry.maps.prepare import PrepareOptions, PreparationCancelled, build_package, shade_elevations
from stratascry.maps.sources import inspect_sources


@pytest.fixture
def elevation(tmp_path):
    path = tmp_path / 'USGS_synthetic.tif'
    rows, cols = np.mgrid[:160, :180]
    values = (cols*2 + 100*np.sin(rows/20)).astype('float32')
    values[45:65, 65:95] = -9999
    values[110:140, 20:50] = 0  # Zero elevation is valid, not a missing-data marker.
    with rasterio.open(path, 'w', driver='GTiff', width=180, height=160,
                       count=1, dtype='float32', crs='EPSG:4326', nodata=-9999,
                       transform=from_bounds(-123, 37, -122.8, 37.2, 180, 160)) as dataset:
        dataset.write(values, 1)
    path.with_suffix('.xml').write_text('<?xml version="1.0" encoding="ISO-8859-1"?><!DOCTYPE metadata SYSTEM "https://example.invalid/unused.dtd"><metadata><spref><vertdef><altsys><altunits>meters</altunits><altdatum>NAVD88</altdatum></altsys></vertdef></spref><timeperd><timeinfo><rngdates><begdate>20200101</begdate><enddate>20201231</enddate></rngdates></timeinfo></timeperd><idinfo><citation><citeinfo><pubdate>20210101</pubdate></citeinfo></citation></idinfo></metadata>')
    return path


@pytest.fixture
def prepared(tmp_path, elevation):
    target = tmp_path / 'package'
    options = PrepareOptions([str(elevation)], 'usgs', str(target), 'Synthetic terrain', max_side=256)
    build_package(options)
    return target


def test_portable_package_metadata_mask_and_corruption(tmp_path, prepared):
    moved = tmp_path / 'relocated'
    shutil.copytree(prepared, moved)
    package = load_package(moved)
    assert package.name == 'Synthetic terrain'
    assert package.manifest['source']['files'][0]['vertical_reference'] == 'NAVD88'
    assert package.manifest['source']['files'][0]['sidecar_metadata']['publication_date'] == '20210101'
    assert not package.contains(-122.91, 37.131)  # No-data hole.
    assert package.contains(-122.96, 37.045)  # Zero-metre patch remains valid.
    assert not package.contains(-120, 35)
    assert (package.rgba[:, :, 3] == 0).any()
    assert package.rgba[:, :, 3].max() == 255
    assert max(package.rgba.shape[:2]) <= 256
    with (moved / 'display/relief.png').open('ab') as stream:
        stream.write(b'corruption')
    with pytest.raises(PackageError, match='checksum'):
        load_package(moved)


def test_unsafe_asset_and_oversized_texture_rejected(prepared):
    manifest_file = prepared / 'manifest.json'
    original = json.loads(manifest_file.read_text())
    modified = json.loads(manifest_file.read_text())
    modified['display']['image'] = '../outside.png'
    manifest_file.write_text(json.dumps(modified))
    with pytest.raises(PackageError, match='unsafe|Missing'):
        load_package(prepared)
    original['display']['width'] = 1000000
    manifest_file.write_text(json.dumps(original))
    with pytest.raises(PackageError, match='dimensions'):
        load_package(prepared)


def test_cancel_and_existing_destination_leave_files_intact(tmp_path, elevation):
    target = tmp_path / 'cancelled'
    opts = PrepareOptions([str(elevation)], 'usgs', str(target), 'Cancelled', max_side=128)
    with pytest.raises(PreparationCancelled):
        build_package(opts, cancelled=lambda: True)
    assert not target.exists()
    assert not list(tmp_path.glob('.stratascry-build-*'))
    target.mkdir()
    (target / 'keep').write_text('user file')
    with pytest.raises(PackageError, match='already exists'):
        build_package(opts)
    assert (target / 'keep').read_text() == 'user file'


def test_unknown_units_require_explicit_selection(tmp_path, elevation):
    elevation.with_suffix('.xml').unlink()
    options = PrepareOptions([str(elevation)], 'usgs', str(tmp_path/'output'), 'No units', max_side=128)
    with pytest.raises(PackageError, match='units'):
        build_package(options)
    options.units = 'metres'
    package = load_package(build_package(options))
    assert package.manifest['source']['files'][0]['unit_selection'] == 'user declaration'


def test_synthetic_hgt_and_nasa_archive_layout(tmp_path):
    path = tmp_path / 'n37w123.hgt'
    # Original HGT posting count, endian convention, and coordinate filename.
    np.broadcast_to(np.arange(3601, dtype='>i2'), (3601, 3601)).astype('>i2').tofile(path)
    archive_path = tmp_path/'NASADEM_HGT_n37w123.zip'
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.write(path, arcname='n37w123.hgt')
        archive.writestr('n37w123.num', b'not elevation')
    report = inspect_sources([str(archive_path)], 'nasadem')
    assert report['sources'][0]['units'] == 'metres'
    assert report['sources'][0]['vertical_reference'].startswith('EGM96')
    assert report['bounds'] == pytest.approx([-123-1/7200,37-1/7200,-122+1/7200,38+1/7200])
    options = PrepareOptions([str(archive_path)], 'nasadem', str(tmp_path/'nasa-package'),
                             'Synthetic NASADEM layout', (-122.9,37.2,-122.7,37.4), 128)
    package = load_package(build_package(options))
    assert package.contains(-122.8,37.3)
    assert package.manifest['source']['product'] == 'nasadem'


def test_projected_source_and_feet_conversion(tmp_path):
    def write(name, data, units):
        path = tmp_path/name
        with rasterio.open(path,'w',driver='GTiff',width=80,height=80,count=1,dtype='float32',
                           crs='EPSG:32610',transform=from_origin(540000,4180000,30,30)) as dst:
            dst.write(data.astype('float32'),1)
            dst.set_band_unit(1,units)
        return path
    rows, cols = np.mgrid[:80,:80]
    metres = (cols*10+np.sin(rows/8)*100).astype('float32')
    m = write('meters.tif',metres,'m')
    ft = write('feet.tif',metres/.3048,'ft')
    outputs = []
    for index,path in enumerate((m,ft)):
        package = load_package(build_package(PrepareOptions([str(path)],'usgs',str(tmp_path/f'p{index}'),'Projection test',max_side=128)))
        outputs.append(package.rgba.astype(float))
        w,s,e,n = package.bounds
        assert -123 < w < e < -122 and 37 < s < n < 38
    assert np.abs(outputs[0]-outputs[1]).mean() < .2


def test_catalog_persistence_and_removal_never_delete_package(tmp_path, prepared):
    catalog_path = tmp_path/'settings/catalog.json'
    catalog = Catalog(catalog_path)
    package = load_package(prepared)
    catalog.add(package)
    catalog.active_id = package.id
    catalog.save()
    restored = Catalog(catalog_path)
    assert restored.active_id == package.id
    restored.remove(package.id)
    restored.save()
    assert not Catalog(catalog_path).entries
    assert (prepared/'display/relief.png').exists()


@pytest.mark.parametrize('bounds', [(179,0,-179,1),(-180,0,180,1),(0,88,1,90),(1,0,1,1),(0,float('nan'),1,2)])
def test_unsupported_extents_fail_explicitly(bounds):
    with pytest.raises(PackageError):
        validate_bounds(bounds)


def test_northern_region_supported(tmp_path):
    path = tmp_path/'north.tif'
    with rasterio.open(path,'w',driver='GTiff',width=100,height=100,count=1,dtype='float32',
                       crs='EPSG:4326',transform=from_bounds(20,84,20.1,84.1,100,100)) as dst:
        dst.write(np.ones((100,100),dtype='float32')*20,1)
        dst.set_band_unit(1,'m')
    package=load_package(build_package(PrepareOptions([str(path)],'usgs',str(tmp_path/'north'),'Polar fixture',max_side=128)))
    assert package.contains(20.05,84.05)


def test_hillshade_normal_and_vertical_units():
    # Flat plane has the same illumination regardless of elevation offset.
    rgb, valid = shade_elevations(np.zeros((8,8),dtype='float32'), 30)
    expected = (0.28 + .72*np.sin(np.pi/4))*170
    assert rgb[0,3,3] == int(expected)
    assert valid.all()
    rows,cols=np.mgrid[:8,:8]
    # A plane rising east has a west-facing normal, brighter under western lights.
    west_facing,_=shade_elevations(cols.astype('float32')*30,30)
    east_facing,_=shade_elevations(-cols.astype('float32')*30,30)
    assert west_facing.mean() > east_facing.mean()


@pytest.mark.parametrize('mutation', [
    lambda m: m['source'].pop('product'),
    lambda m: m['source'].__setitem__('files',[]),
    lambda m: m['display'].__setitem__('approx_sampling_m_at_center',[float('nan'),1]),
    lambda m: m['source']['files'][0].__setitem__('sidecar_metadata','bad'),
])
def test_invalid_required_metadata_rejected(prepared, mutation):
    path = prepared/'manifest.json'
    manifest = json.loads(path.read_text())
    mutation(manifest)
    path.write_text(json.dumps(manifest))
    with pytest.raises(PackageError):
        load_package(prepared)


def test_adjacent_sources_mosaic_and_vertical_reference(tmp_path):
    paths=[]
    for i in range(2):
        path=tmp_path/f'part{i}.tif'
        with rasterio.open(path,'w',driver='GTiff',width=80,height=80,count=1,dtype='float32',
                           nodata=-9999,crs='EPSG:4326',transform=from_bounds(-123+i*.1,37,-122.9+i*.1,37.1,80,80)) as dst:
            dst.write(np.full((80,80),100,dtype='float32'),1)
            dst.set_band_unit(1,'m')
        paths.append(str(path))
    options=PrepareOptions(paths,'usgs',str(tmp_path/'joined'),'Adjacent tiles',max_side=128)
    with pytest.raises(PackageError,match='vertical reference'):
        build_package(options)
    options.vertical_reference='Common synthetic reference'
    package=load_package(build_package(options))
    for lon in (-122.95,-122.9001,-122.9,-122.8999,-122.85):
        assert package.contains(lon,37.05)
    assert len(package.manifest['source']['files']) == 2


def test_no_intersection_leaves_no_output(tmp_path, elevation):
    target=tmp_path/'empty'
    with pytest.raises(PackageError,match='No valid elevation'):
        build_package(PrepareOptions([str(elevation)],'usgs',str(target),'Outside',(0,1,.1,1.1),128))
    assert not target.exists()


def test_loader_offline_after_relocation(tmp_path, prepared, monkeypatch):
    import socket
    def no_network(*args, **kwargs):
        raise AssertionError('Package loading attempted network access')
    monkeypatch.setattr(socket.socket,'connect',no_network)
    monkeypatch.setattr(socket,'create_connection',no_network)
    moved=tmp_path/'offline-copy'
    shutil.copytree(prepared,moved)
    shutil.rmtree(prepared)
    assert load_package(moved).name == 'Synthetic terrain'


def test_corrupt_catalog_preserved(tmp_path):
    path=tmp_path/'catalog.json'
    path.write_text('[]')
    catalog=Catalog(path)
    assert catalog.error
    with pytest.raises(PackageError):
        catalog.save()
    assert path.read_text() == '[]'
