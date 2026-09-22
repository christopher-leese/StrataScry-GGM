# SPDX-License-Identifier: Apache-2.0
"""Build a portable tiled Blue Marble GeoTIFF with reduced-resolution overviews.

python -m stratascry.blue_marble.build --source-dir DOWNLOADS --output NEW_FOLDER
Use --download instead of --source-dir to fetch the eight NASA source JPEGs.
Only this explicit preparation command accesses the network; the viewer is offline.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import subprocess
from concurrent.futures import ThreadPoolExecutor
from xml.sax.saxutils import escape

import rasterio
from rasterio.shutil import copy as raster_copy

PAGE = 'https://science.nasa.gov/earth/earth-observatory/blue-marble-next-generation/base-topography-bathymetry/'
BASE = 'https://assets.science.nasa.gov/content/dam/science/esd/eo/images/bmng/bmng-topography-bathymetry/august/'


def sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as source:
        while block:=source.read(1024*1024):
            digest.update(block)
    return digest.hexdigest()


def write_pyramid(source, target, *, tile_size, max_level, provenance, fallback_width=0):
    """Stream into a tiled COG; GDAL constructs on-disk overviews with bounded cache."""
    target=Path(target).expanduser().resolve()
    if target.exists() or not target.parent.is_dir():
        raise ValueError('Choose a new output folder inside an existing directory')
    with tempfile.TemporaryDirectory(prefix='.blue-marble-',dir=target.parent) as temporary:
        staging=Path(temporary)/'package'
        staging.mkdir()
        with rasterio.Env(GDAL_CACHEMAX=256*1024**2, GDAL_NUM_THREADS='2'):
            raster_copy(str(source),str(staging/'earth.tif'),driver='COG',
                        COMPRESS='JPEG',QUALITY='90',BLOCKSIZE='512',
                        OVERVIEWS='AUTO',RESAMPLING='AVERAGE',NUM_THREADS='2',BIGTIFF='IF_SAFER')
        with rasterio.open(staging/'earth.tif') as raster:
            if (raster.width,raster.height)!=(tile_size*2**(max_level+1),tile_size*2**max_level):
                raise ValueError('Raster dimensions do not match the tile grid')
            overviews=raster.overviews(1)
            if max_level and (not overviews or max(overviews)<2**max_level):
                raise ValueError('Output lacks the required reduced-resolution overviews')
        manifest={'format':'stratascry-blue-marble','version':1,'file':'earth.tif',
                  'name':'Blue Marble · August 2004','width':raster.width,'height':raster.height,
                  'tile_size':tile_size,'max_level':max_level,'overviews':overviews,'fallback_width':fallback_width,
                  'bounds':[-180,-90,180,90],'crs':'EPSG:4326',
                  'credit':'Reto Stöckli, NASA Earth Observatory',
                  'source_page':PAGE,'sources':provenance,
                  'processing':'Native sampling retained; JPEG quality 90; average overviews; 512-pixel storage blocks',
                  'sha256':sha256(staging/'earth.tif')}
        (staging/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        (staging/'ATTRIBUTION.md').write_text(
            '# Blue Marble: Next Generation\n\nReto Stöckli, NASA Earth Observatory. August 2004.\n\n'
            +PAGE+'\n\nNative spatial sampling retained; JPEG recompression is lossy. '
            'Shading is image content, not terrain geometry. No NASA endorsement implied.\n')
        if target.exists():
            raise ValueError('Output appeared during preparation; existing files were not replaced')
        staging.rename(target)
    return target


def build(source_dir, output):
    source_dir=Path(source_dir).expanduser().resolve()
    records=[]
    sources=[]
    for row in range(2):
        for col,letter in enumerate('ABCD'):
            name=f'world.topo.bathy.200408.3x21600x21600.{letter}{row+1}.jpg'
            path=source_dir/name
            with rasterio.open(path) as source:
                if (source.width,source.height,source.count)!=(21600,21600,3) or source.dtypes!=('uint8',)*3:
                    raise ValueError(f'Unexpected NASA source dimensions: {name}')
            records.append({'file':name,'source':BASE+name,'sha256':sha256(path)})
            sources.append((col,row,path))
    with tempfile.TemporaryDirectory(prefix='blue-marble-vrt-') as temporary:
        vrt=Path(temporary)/'world.vrt'
        lines=['<VRTDataset rasterXSize="86400" rasterYSize="43200">',
               '<SRS>EPSG:4326</SRS><GeoTransform>-180,0.004166666666666667,0,90,0,-0.004166666666666667</GeoTransform>']
        for band,color in enumerate(('Red','Green','Blue'),1):
            lines.append(f'<VRTRasterBand dataType="Byte" band="{band}"><ColorInterp>{color}</ColorInterp>')
            for col,row,path in sources:
                lines.append(f'<SimpleSource><SourceFilename relativeToVRT="0">{escape(str(path))}</SourceFilename>'
                             f'<SourceBand>{band}</SourceBand><SrcRect xOff="0" yOff="0" xSize="21600" ySize="21600"/>'
                             f'<DstRect xOff="{col*21600}" yOff="{row*21600}" xSize="21600" ySize="21600"/></SimpleSource>')
            lines.append('</VRTRasterBand>')
        lines.append('</VRTDataset>')
        vrt.write_text('\n'.join(lines))
        print('Building tiled raster and overviews (native 86400 × 43200)…',flush=True)
        result=write_pyramid(vrt,output,tile_size=675,max_level=6,provenance=records,fallback_width=5400)
    print(result,flush=True)
    return result


def download_sources(directory):
    """Explicit CLI opt-in; the running viewer never makes these requests."""
    directory=Path(directory)
    def fetch(tile):
        name=f'world.topo.bathy.200408.3x21600x21600.{tile}.jpg'
        target=directory/name
        partial=target.with_suffix('.part')
        subprocess.run(['curl','--fail','--location','--silent','--show-error',
                        '--retry','2','--connect-timeout','20','--max-time','300',
                        '--output',str(partial),BASE+name],check=True)
        partial.replace(target)
        print('Downloaded '+tile,flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(fetch,[c+r for r in '12' for c in 'ABCD']))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    inputs=parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--source-dir')
    inputs.add_argument('--download',action='store_true',help='Download eight official NASA JPEGs using curl')
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    target=Path(args.output).expanduser().resolve()
    if target.exists(): parser.error('Output already exists; choose a new folder')
    target.parent.mkdir(parents=True,exist_ok=True)
    if args.download:
        with tempfile.TemporaryDirectory(prefix='blue-marble-download-') as temporary:
            download_sources(temporary)
            build(temporary,target)
    else:
        build(args.source_dir,target)


if __name__=='__main__':
    main()
