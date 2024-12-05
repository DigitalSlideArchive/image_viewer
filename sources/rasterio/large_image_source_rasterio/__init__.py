#############################################################################
#  Copyright Kitware Inc.
#
#  Licensed under the Apache License, Version 2.0 ( the "License" );
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#############################################################################

import math
import os
import pathlib
import tempfile
import threading
import warnings
from contextlib import suppress
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _importlib_version

import numpy as np
import PIL.Image

import large_image
from large_image.cache_util import LruCacheMetaclass, methodcache
from large_image.constants import (TILE_FORMAT_IMAGE, TILE_FORMAT_NUMPY,
                                   TILE_FORMAT_PIL, SourcePriority,
                                   TileInputUnits, TileOutputMimeTypes)
from large_image.exceptions import (TileSourceError,
                                    TileSourceFileNotFoundError,
                                    TileSourceInefficientError)
from large_image.tilesource.geo import (GDALBaseFileTileSource,
                                        ProjUnitsAcrossLevel0,
                                        ProjUnitsAcrossLevel0_MaxSize)
from large_image.tilesource.utilities import JSONDict

try:
    __version__ = _importlib_version(__name__)
except PackageNotFoundError:
    # package is not installed
    pass

rio = None
Affine = None


def _lazyImport():
    """
    Import the rasterio module.  This is done when needed rather than in the
    module initialization because it is slow.
    """
    global Affine, rio

    if rio is None:
        try:
            import affine
            import rasterio as rio
            import rasterio.warp

            Affine = affine.Affine

            warnings.filterwarnings(
                'ignore', category=rio.errors.NotGeoreferencedWarning, module='rasterio')
            rio._env.code_map.pop(1, None)
        except ImportError:
            msg = 'rasterio module not found.'
            raise TileSourceError(msg)


def make_crs(projection):
    _lazyImport()

    if isinstance(projection, str):
        return rio.CRS.from_string(projection)
    if isinstance(projection, dict):
        return rio.CRS.from_dict(projection)
    if isinstance(projection, int):
        return rio.CRS.from_string(f'EPSG:{projection}')
    return rio.CRS(projection)


class RasterioFileTileSource(GDALBaseFileTileSource, metaclass=LruCacheMetaclass):
    """Provides tile access to geospatial files."""

    cacheName = 'tilesource'
    name = 'rasterio'

    def __init__(self, path, projection=None, unitsPerPixel=None, **kwargs):
        """Initialize the tile class.

        See the base class for other available parameters.

        :param path: a filesystem path for the tile source.
        :param projection: None to use pixel space, otherwise a crs compatible with rasterio's CRS.
        :param unitsPerPixel: The size of a pixel at the 0 tile size.
            Ignored if the projection is None.  For projections, None uses the default,
            which is the distance between (-180,0) and (180,0) in EPSG:4326 converted to the
            projection divided by the tile size. crs projections that are not latlong
            (is_geographic is False) must specify unitsPerPixel.

        """
        # init the object
        super().__init__(path, **kwargs)
        _lazyImport()
        self.addKnownExtensions()

        # create a thread lock
        self._getDatasetLock = threading.RLock()

        if isinstance(path, rio.io.MemoryFile):
            path = path.open(mode='r')

        if isinstance(path, rio.io.DatasetReaderBase):
            self.dataset = path
            self._largeImagePath = self.dataset.name
        else:
            # set the large_image path
            self._largeImagePath = self._getLargeImagePath()

            # open the file with rasterio and display potential warning/errors
            with self._getDatasetLock:
                if not self._largeImagePath.startswith(
                        '/vsi') and not os.path.isfile(self._largeImagePath):
                    raise TileSourceFileNotFoundError(self._largeImagePath) from None
                try:
                    self.dataset = rio.open(self._largeImagePath)
                except rio.errors.RasterioIOError:
                    msg = 'File cannot be opened via rasterio.'
                    raise TileSourceError(msg)
                if self.dataset.driver == 'netCDF':
                    msg = 'netCDF file will not be read via rasterio source.'
                    raise TileSourceError(msg)

        # extract default parameters from the image
        self.tileSize = 256
        self._bounds = {}
        self.tileWidth = self.tileSize
        self.tileHeight = self.tileSize
        self.projection = make_crs(projection) if projection else None

        # get width and height parameters
        with self._getDatasetLock:
            self.sourceSizeX = self.sizeX = self.dataset.width
            self.sourceSizeY = self.sizeY = self.dataset.height

        # netCDF is blacklisted from rasterio so it won't be used.
        # use the mapnik source if needed. This variable is always ignored
        # is_netcdf = False

        try:
            # get the different scales and projections from the image
            scale = self.getPixelSizeInMeters()

            # raise an error if we are missing some information about the projection
            # i.e. we don't know where to place it on a map
            isProjected = self.projection or self.dataset.driver.lower() in {'png'}
            if isProjected and not scale:
                msg = ('File does not have a projected scale, so will not be '
                       'opened via rasterio with a projection.')
                raise TileSourceError(msg)

            # set the levels of the tiles
            logX = math.log(float(self.sizeX) / self.tileWidth)
            logY = math.log(float(self.sizeY) / self.tileHeight)
            computedLevel = math.ceil(max(logX, logY) / math.log(2))
            self.sourceLevels = self.levels = int(max(0, computedLevel) + 1)

            self._unitsPerPixel = unitsPerPixel
            self.projection is None or self._initWithProjection(unitsPerPixel)
            self._getPopulatedLevels()
            self._getTileLock = threading.Lock()
            self._setDefaultStyle()
        except Exception as exc:
            msg = f'File cannot be opened via rasterio {exc}.'
            raise TileSourceError(msg)

    def _getPopulatedLevels(self):
        try:
            with self._getDatasetLock:
                self._populatedLevels = 1 + len(self.dataset.overviews(1))
        except Exception:
            pass

    def _scanForMinMax(self, dtype, frame=0, analysisSize=1024, onlyMinMax=True):
        """Update the band range of the data type to the end of the range list.

        This will change autocalling behavior, and for non-integer data types,
        this adds the range [0, 1].

        :param dtype: the dtype of the bands
        :param frame: optional default to 0
        :param analysisSize: optional default to 1024
        :param onlyMinMax: optional default to True
        """
        # default frame to 0 in case it is set to None from outside
        frame = frame or 0

        # read band information
        bandInfo = self.getBandInformation()

        # get the minmax value from the band
        hasMin = all(b.get('min') is not None for b in bandInfo.values())
        hasMax = all(b.get('max') is not None for b in bandInfo.values())
        if not frame and onlyMinMax and hasMax and hasMin:
            with self._getDatasetLock:
                dtype = self.dataset.profile['dtype']
            self._bandRanges[0] = {
                'min': np.array([b['min'] for b in bandInfo.values()], dtype=dtype),
                'max': np.array([b['max'] for b in bandInfo.values()], dtype=dtype),
            }
        else:
            kwargs = {}
            if self.projection:
                bounds = self.getBounds(self.projection)
                kwargs = {
                    'region': {
                        'left': bounds['xmin'],
                        'top': bounds['ymax'],
                        'right': bounds['xmax'],
                        'bottom': bounds['ymin'],
                        'units': 'projection',
                    },
                }
            super(RasterioFileTileSource, RasterioFileTileSource)._scanForMinMax(
                self,
                dtype=dtype,
                frame=frame,
                analysisSize=analysisSize,
                onlyMinMax=onlyMinMax,
                **kwargs,
            )

        # Add the maximum range of the data type to the end of the band
        # range list.  This changes autoscaling behavior.  For non-integer
        # data types, this adds the range [0, 1].
        band_frame = self._bandRanges[frame]
        try:
            # only valid for integer dtypes
            range_max = np.iinfo(band_frame['max'].dtype).max
        except ValueError:
            range_max = 1
        band_frame['min'] = np.append(band_frame['min'], 0)
        band_frame['max'] = np.append(band_frame['max'], range_max)

    def _initWithProjection(self, unitsPerPixel=None):
        """Initialize aspects of the class when a projection is set.

        :param unitsPerPixel: optional default to None
        """
        srcCrs = make_crs(4326)
        # Since we already converted to bytes decoding is safe here
        dstCrs = self.projection
        if dstCrs.is_geographic:
            msg = ('Projection must not be geographic (it needs to use linear '
                   'units, not longitude/latitude).')
            raise TileSourceError(msg)

        if unitsPerPixel is not None:
            self.unitsAcrossLevel0 = float(unitsPerPixel) * self.tileSize
        else:
            self.unitsAcrossLevel0 = ProjUnitsAcrossLevel0.get(
                self.projection.to_string(),
            )
            if self.unitsAcrossLevel0 is None:
                # If unitsPerPixel is not specified, the horizontal distance
                # between -180,0 and +180,0 is used.  Some projections (such as
                # stereographic) will fail in this case; they must have a unitsPerPixel specified.
                east, _ = rio.warp.transform(srcCrs, dstCrs, [-180], [0])
                west, _ = rio.warp.transform(srcCrs, dstCrs, [180], [0])
                self.unitsAcrossLevel0 = abs(east[0] - west[0])
                if not self.unitsAcrossLevel0:
                    msg = 'unitsPerPixel must be specified for this projection'
                    raise TileSourceError(msg)
                if len(ProjUnitsAcrossLevel0) >= ProjUnitsAcrossLevel0_MaxSize:
                    ProjUnitsAcrossLevel0.clear()

                ProjUnitsAcrossLevel0[
                    self.projection.to_string()
                ] = self.unitsAcrossLevel0

        # for consistency, it should probably always be (0, 0).  Whatever
        # renders the map would need the same offset as used here.
        self.projectionOrigin = (0, 0)

        # Calculate values for this projection
        width = self.getPixelSizeInMeters() * self.tileWidth
        tile0 = self.unitsAcrossLevel0 / width
        base2 = math.ceil(math.log(tile0) / math.log(2))
        self.levels = int(max(int(base2) + 1, 1))

        # Report sizeX and sizeY as the whole world
        self.sizeX = 2 ** (self.levels - 1) * self.tileWidth
        self.sizeY = 2 ** (self.levels - 1) * self.tileHeight

    @staticmethod
    def getLRUHash(*args, **kwargs):
        projection = kwargs.get('projection', args[1] if len(args) >= 2 else None)
        unitsPerPixel = kwargs.get('unitsPerPixel', args[3] if len(args) >= 4 else None)

        source = super(RasterioFileTileSource, RasterioFileTileSource)
        lru = source.getLRUHash(*args, **kwargs)
        info = f',{projection},{unitsPerPixel}'

        return lru + info

    def getState(self):
        proj = self.projection.to_string() if self.projection else None
        unit = self._unitsPerPixel

        return super().getState() + f',{proj},{unit}'

    def getCrs(self):
        """Returns crs object for the given dataset

        :returns: The crs or None.
        """
        with self._getDatasetLock:

            # use gcp if available
            if len(self.dataset.gcps[0]) != 0 and self.dataset.gcps[1]:
                crs = self.dataset.gcps[1]
            else:
                crs = self.dataset.crs

            # if no crs but the file is a NITF or has a valid affine transform then
            # consider it as 4326
            hasTransform = self.dataset.transform != Affine.identity()
            isNitf = self.dataset.driver.lower() in {'NITF'}
            if not crs and (hasTransform or isNitf):
                crs = make_crs(4326)

            return crs

    def _getAffine(self):
        """Get the Affine transformation.

        If GCPs are used, get the appropriate Affine for those. Be careful,
        Rasterio have deprecated GDAL styled transform in favor
        of ``Affine`` objects. See their documentation for more information:
        shorturl.at/bcdGL

        :returns: a six-component array with the transform
        """
        with self._getDatasetLock:
            affine = self.dataset.transform
            if len(self.dataset.gcps[0]) != 0 and self.dataset.gcps[1]:
                affine = rio.transform.from_gcps(self.dataset.gcps[0])

        return affine

    def getBounds(self, crs=None, **kwargs):
        """Returns bounds of the image.

        :param crs: the projection for the bounds.  None for the default.

        :returns: an object with the four corners and the projection that was used.
            None if we don't know the original projection.
        """
        if crs is None and 'srs' in kwargs:
            crs = kwargs.get('srs')

        # read the crs as a crs if needed
        dstCrs = make_crs(crs) if crs else None
        strDstCrs = 'none' if dstCrs is None else dstCrs.to_string()

        # exit if it's already set
        if strDstCrs in self._bounds:
            return self._bounds[strDstCrs]

        # extract the projection information
        af = self._getAffine()
        srcCrs = self.getCrs()

        # set bounds to none and exit if no crs is set for the dataset
        if not srcCrs:
            self._bounds[strDstCrs] = None
            return

        # compute the corner coordinates using the affine transformation as
        # longitudes and latitudes. Cannot only rely on bounds because of
        # rotated coordinate systems
        bounds = {
            'll': {
                'x': af[2] + self.sourceSizeY * af[1],
                'y': af[5] + self.sourceSizeY * af[4],
            },
            'ul': {
                'x': af[2],
                'y': af[5],
            },
            'lr': {
                'x': af[2] + self.sourceSizeX * af[0] + self.sourceSizeY * af[1],
                'y': af[5] + self.sourceSizeX * af[3] + self.sourceSizeY * af[4],
            },
            'ur': {
                'x': af[2] + self.sourceSizeX * af[0],
                'y': af[5] + self.sourceSizeX * af[3],
            },
        }

        # ensure that the coordinates are within the projection limits
        if srcCrs.is_geographic and dstCrs:

            # set the vertical bounds
            # some projection system don't cover the poles so we need to adapt
            # the values of ybounds accordingly
            has_poles = rio.warp.transform(4326, dstCrs, [0], [90])[1][0] != float('inf')
            yBounds = 90 if has_poles else 89.999999

            # for each corner fix the latitude within -yBounds yBounds
            for k in bounds:
                bounds[k]['y'] = max(min(bounds[k]['y'], yBounds), -yBounds)

            # rotate longitude so the western-most corner is within [-180, 180)
            dx = min(v['x'] for v in bounds.values())
            if dx < -180 or dx >= 180:
                dx = ((dx + 180) % 360 - 180) - dx
                for k in bounds:
                    bounds[k]['x'] += dx

            # if one of the corner is >= 180 set all the corners to world width
            if any(v['x'] >= 180 for v in bounds.values()):
                bounds['ul']['x'] = bounds['ll']['x'] = -180
                bounds['ur']['x'] = bounds['lr']['x'] = 180

        # reproject the pts in the destination coordinate system if necessary
        needProjection = dstCrs and dstCrs != srcCrs
        if needProjection:
            for pt in bounds.values():
                [pt['x']], [pt['y']] = rio.warp.transform(srcCrs, dstCrs, [pt['x']], [pt['y']])

        # extract min max coordinates from the corners
        ll = bounds['ll']['x'], bounds['ll']['y']
        ul = bounds['ul']['x'], bounds['ul']['y']
        lr = bounds['lr']['x'], bounds['lr']['y']
        ur = bounds['ur']['x'], bounds['ur']['y']
        bounds['xmin'] = min(ll[0], ul[0], lr[0], ur[0])
        bounds['xmax'] = max(ll[0], ul[0], lr[0], ur[0])
        bounds['ymin'] = min(ll[1], ul[1], lr[1], ur[1])
        bounds['ymax'] = max(ll[1], ul[1], lr[1], ur[1])

        # set the srs in the bounds
        bounds['srs'] = dstCrs.to_string() if needProjection else srcCrs.to_string()

        # write the bounds in memory
        self._bounds[strDstCrs] = bounds

        return bounds

    def getBandInformation(self, statistics=True, dataset=None, **kwargs):
        """Get information about each band in the image.

        :param statistics: if True, compute statistics if they don't already exist.
            Ignored: always treated as True.
        :param dataset: the dataset.  If None, use the main dataset.

        :returns: a list of one dictionary per band.  Each dictionary contains
            known values such as interpretation, min, max, mean, stdev, nodata,
            scale, offset, units, categories, colortable, maskband.
        """
        # exit if the value is already set
        if getattr(self, '_bandInfo', None) and not dataset:
            return self._bandInfo

        # check if the dataset is cached
        cache = not dataset

        # do everything inside the dataset lock to avoid multiple read
        with self._getDatasetLock:

            # setup the dataset (use the one store in self.dataset if not cached)
            dataset = dataset or self.dataset

            # loop in the bands to get the indicidative stats (bands are 1 indexed)
            infoSet = JSONDict({})
            for i in dataset.indexes:  # 1 indexed

                # get the stats
                if hasattr(dataset, 'stats'):
                    stats = dataset.stats(indexes=[i], approx=True)[0]
                else:
                    stats = dataset.statistics(i, approx=True, clear_cache=True)

                # rasterio doesn't provide support for maskband as for RCF 15
                # instead the whole mask numpy array is rendered. We don't want to save it
                # in the metadata
                info = {
                    'min': stats.min,
                    'max': stats.max,
                    'mean': stats.mean,
                    'stdev': stats.std,
                    'nodata': dataset.nodatavals[i - 1],
                    'scale': dataset.scales[i - 1],
                    'offset': dataset.offsets[i - 1],
                    'units': dataset.units[i - 1],
                    'categories': dataset.descriptions[i - 1],
                    'interpretation': dataset.colorinterp[i - 1].name.lower(),
                }
                if info['interpretation'] == 'palette':
                    info['colortable'] = list(dataset.colormap(i).values())
                # if dataset.mask_flag_enums[i - 1][0] != MaskFlags.all_valid:
                #     # TODO: find band number - this is incorrect
                #     info["maskband"] = dataset.mask_flag_enums[i - 1][1].value

                # Only keep values that aren't None or the empty string
                infoSet[i] = {
                    k: v for k, v in info.items()
                    if v not in (None, '') and not (
                        isinstance(v, float) and
                        math.isnan(v)
                    )
                }

        # set the value to cache if needed
        if cache:
            self._bandInfo = infoSet

        return infoSet

    def getMetadata(self):
        metadata = super().getMetadata()
        with self._getDatasetLock:
            # check if the file is geospatial
            has_projection = self.dataset.crs
            has_gcps = len(self.dataset.gcps[0]) != 0 and self.dataset.gcps[1]
            has_affine = self.dataset.transform

            metadata.update({
                'geospatial': bool(has_projection or has_gcps or has_affine),
                'sourceLevels': self.sourceLevels,
                'sourceSizeX': self.sourceSizeX,
                'sourceSizeY': self.sourceSizeY,
                'bounds': self.getBounds(self.projection),
                'projection': self.projection.decode() if isinstance(
                    self.projection, bytes) else self.projection,
                'sourceBounds': self.getBounds(),
                'bands': self.getBandInformation(),
            })
        return metadata

    def getInternalMetadata(self, **kwargs):
        """Return additional known metadata about the tile source.

        Data returned from this method is not guaranteed to be in
        any particular format or have specific values.

        :returns: a dictionary of data or None.
        """
        result = JSONDict({})
        with self._getDatasetLock:
            result['driverShortName'] = self.dataset.driver
            result['driverLongName'] = self.dataset.driver
            # result['fileList'] = self.dataset.GetFileList()
            result['RasterXSize'] = self.dataset.width
            result['RasterYSize'] = self.dataset.height
            result['Affine'] = self._getAffine()
            result['Projection'] = (
                self.dataset.crs.to_string() if self.dataset.crs else None
            )
            result['GCPProjection'] = self.dataset.gcps[1]

            meta = self.dataset.meta
            meta['crs'] = (
                meta['crs'].to_string()
                if ('crs' in meta and meta['crs'] is not None)
                else None
            )
            meta['transform'] = (
                meta['transform'].to_gdal() if 'transform' in meta else None
            )
            result['Metadata'] = meta

            # add gcp of available
            if len(self.dataset.gcps[0]) != 0:
                result['GCPs'] = [gcp.asdict() for gcp in self.dataset.gcps[0]]

        return result

    @methodcache()
    def getTile(self, x, y, z, pilImageAllowed=False, numpyAllowed=False, **kwargs):
        if not self.projection:
            self._xyzInRange(x, y, z)
            factor = int(2 ** (self.levels - 1 - z))
            xmin = int(x * factor * self.tileWidth)
            ymin = int(y * factor * self.tileHeight)
            xmax = int(min(xmin + factor * self.tileWidth, self.sourceSizeX))
            ymax = int(min(ymin + factor * self.tileHeight, self.sourceSizeY))
            w = int(max(1, round((xmax - xmin) / factor)))
            h = int(max(1, round((ymax - ymin) / factor)))

            with self._getDatasetLock:
                window = rio.windows.Window(xmin, ymin, xmax - xmin, ymax - ymin)
                count = self.dataset.count
                tile = self.dataset.read(
                    window=window,
                    out_shape=(count, h, w),
                    resampling=rio.enums.Resampling.nearest,
                )

        else:
            xmin, ymin, xmax, ymax = self.getTileCorners(z, x, y)
            bounds = self.getBounds(self.projection)

            # return empty image when I'm out of bounds
            if (
                xmin >= bounds['xmax'] or
                xmax <= bounds['xmin'] or
                ymin >= bounds['ymax'] or
                ymax <= bounds['ymin']
            ):
                pilimg = PIL.Image.new('RGBA', (self.tileWidth, self.tileHeight))
                return self._outputTile(
                    pilimg, TILE_FORMAT_PIL, x, y, z, applyStyle=False, **kwargs,
                )

            xres = (xmax - xmin) / self.tileWidth
            yres = (ymax - ymin) / self.tileHeight
            dst_transform = Affine(xres, 0.0, xmin, 0.0, -yres, ymax)

            # Adding an alpha band when the source has one is trouble.
            # It will result in surprisingly unmasked data.
            src_alpha_band = 0
            for i, interp in enumerate(self.dataset.colorinterp):
                if interp == rio.enums.ColorInterp.alpha:
                    src_alpha_band = i
            add_alpha = not src_alpha_band

            # read the image as a warp vrt
            with self._getDatasetLock:
                with rio.vrt.WarpedVRT(
                    self.dataset,
                    resampling=rio.enums.Resampling.nearest,
                    crs=self.projection,
                    transform=dst_transform,
                    height=self.tileHeight,
                    width=self.tileWidth,
                    add_alpha=add_alpha,
                ) as vrt:
                    tile = vrt.read(resampling=rio.enums.Resampling.nearest)

        # necessary for multispectral images:
        # set the coordinates first and the bands at the end
        if len(tile.shape) == 3:
            tile = np.moveaxis(tile, 0, 2)

        return self._outputTile(
            tile, TILE_FORMAT_NUMPY, x, y, z, pilImageAllowed, numpyAllowed, **kwargs,
        )

    def _convertProjectionUnits(
        self, left, top, right, bottom, width=None, height=None, units='base_pixels', **kwargs,
    ):
        """Convert projection units.

        Given bound information and a units that consists of a projection (srs or crs),
        convert the bounds to either pixel or the class projection coordinates.

        :param left: the left edge (inclusive) of the region to process.
        :param top: the top edge (inclusive) of the region to process.
        :param right: the right edge (exclusive) of the region to process.
        :param bottom: the bottom edge (exclusive) of the region to process.
        :param width: the width of the region to process.  Ignored if both left and
            right are specified.
        :param height: the height of the region to process.  Ignores if both top and
            bottom are specified.
        :param units: either 'projection', a string starting with 'proj4:','epsg:',
            or '+proj=' or a enumerated value like 'wgs84', or one of the super's values.
        :param kwargs: optional parameters.

        :returns: left, top, right, bottom, units.  The new bounds in the either
            pixel or class projection units.
        """
        # build the different corner from the parameters
        if not kwargs.get('unitsWH') or kwargs.get('unitsWH') == units:
            if left is None and right is not None and width is not None:
                left = right - width
            if right is None and left is not None and width is not None:
                right = left + width
            if top is None and bottom is not None and height is not None:
                top = bottom - height
            if bottom is None and top is not None and height is not None:
                bottom = top + height

        # raise error if we didn't build one of the coordinates
        if (left is None and right is None) or (top is None and bottom is None):
            msg = ('Cannot convert from projection unless at least one of '
                   'left and right and at least one of top and bottom is '
                   'specified.')
            raise TileSourceError(msg)

        # compute the pixel coordinates of the corners if no projection is set
        if not self.projection:
            pleft, ptop = self.toNativePixelCoordinates(
                right if left is None else left, bottom if top is None else top, units,
            )
            pright, pbottom = self.toNativePixelCoordinates(
                left if right is None else right,
                top if bottom is None else bottom,
                units,
            )
            units = 'base_pixels'

        # compute the coordinates if the projection exist
        else:
            if units.startswith('proj4:'):
                # HACK to avoid `proj4:` prefixes with `WGS84`, etc.
                units = units.split(':', 1)[1]
            srcCrs = make_crs(units)
            dstCrs = self.projection  # instance projection -- do not use the CRS native to the file
            [pleft], [ptop] = rio.warp.transform(
                srcCrs, dstCrs,
                [right if left is None else left],
                [bottom if top is None else top])
            [pright], [pbottom] = rio.warp.transform(
                srcCrs, dstCrs,
                [left if right is None else right],
                [top if bottom is None else bottom])
            units = 'projection'

        # set the corner value in pixel coordinates if the coordinate was initially
        # set else leave it to None
        left = pleft if left is not None else None
        top = ptop if top is not None else None
        right = pright if right is not None else None
        bottom = pbottom if bottom is not None else None

        return left, top, right, bottom, units

    def _getRegionBounds(
        self,
        metadata,
        left=None,
        top=None,
        right=None,
        bottom=None,
        width=None,
        height=None,
        units=None,
        **kwargs,
    ):
        """Get region bounds.

        Given a set of arguments that can include left, right, top, bottom, width,
        height, and units, generate actual pixel values for left, top, right, and bottom.
        If units is `'projection'`, use the source's projection.  If units is a
        proj string, use that projection.  Otherwise, just use the super function.

        :param metadata: the metadata associated with this source.
        :param left: the left edge (inclusive) of the region to process.
        :param top: the top edge (inclusive) of the region to process.
        :param right: the right edge (exclusive) of the region to process.
        :param bottom: the bottom edge (exclusive) of the region to process.
        :param width: the width of the region to process.  Ignored if both left and
            right are specified.
        :param height: the height of the region to process.  Ignores if both top and
            bottom are specified.
        :param units: either 'projection', a string starting with 'proj4:', 'epsg:'
            or a enumarted value like 'wgs84', or one of the super's values.
        :param kwargs: optional parameters from _convertProjectionUnits.  See above.

        :returns: left, top, right, bottom bounds in pixels.
        """
        isUnits = units is not None
        units = TileInputUnits.get(units.lower() if isUnits else None, units)

        # check if the units is a string or projection material
        isProj = False
        with suppress(rio.errors.CRSError):
            isProj = make_crs(units) is not None

        # convert the coordinates if a projection exist
        if isUnits and isProj:
            left, top, right, bottom, units = self._convertProjectionUnits(
                left, top, right, bottom, width, height, units, **kwargs,
            )

        if units == 'projection' and self.projection:
            bounds = self.getBounds(self.projection)

            # Fill in missing values
            if left is None:
                left = bounds['xmin'] if right is None or width is None else right - \
                    width  # fmt: skip
            if right is None:
                right = bounds['xmax'] if width is None else left + width
            if top is None:
                top = bounds['ymax'] if bottom is None or height is None else bottom - \
                    height  # fmt: skip
            if bottom is None:
                bottom = bounds['ymin'] if height is None else top + height

            # remove width and height if necessary
            if not kwargs.get('unitsWH') or kwargs.get('unitsWH') == units:
                width = height = None

            # Convert to [-0.5, 0.5], [-0.5, 0.5] coordinate range
            left = (left - self.projectionOrigin[0]) / self.unitsAcrossLevel0
            right = (right - self.projectionOrigin[0]) / self.unitsAcrossLevel0
            top = (top - self.projectionOrigin[1]) / self.unitsAcrossLevel0
            bottom = (bottom - self.projectionOrigin[1]) / self.unitsAcrossLevel0

            # Convert to worldwide 'base pixels' and crop to the world
            xScale = 2 ** (self.levels - 1) * self.tileWidth
            yScale = 2 ** (self.levels - 1) * self.tileHeight
            left = max(0, min(xScale, (0.5 + left) * xScale))
            right = max(0, min(xScale, (0.5 + right) * xScale))
            top = max(0, min(yScale, (0.5 - top) * yScale))
            bottom = max(0, min(yScale, (0.5 - bottom) * yScale))

            # Ensure correct ordering
            left, right = min(left, right), max(left, right)
            top, bottom = min(top, bottom), max(top, bottom)
            units = 'base_pixels'

        return super()._getRegionBounds(
            metadata, left, top, right, bottom, width, height, units, **kwargs,
        )

    def pixelToProjection(self, x, y, level=None):
        """Convert from pixels back to projection coordinates.

        :param x, y: base pixel coordinates.
        :param level: the level of the pixel.  None for maximum level.

        :returns: px, py in projection coordinates.
        """
        if level is None:
            level = self.levels - 1

        # if no projection is set build the pixel values using the geotransform
        if not self.projection:
            af = self._getAffine()
            x *= 2 ** (self.levels - 1 - level)
            y *= 2 ** (self.levels - 1 - level)
            x = af[2] + af[0] * x + af[1] * y
            y = af[5] + af[3] * x + af[4] * y

        # else we used the projection set in __init__
        else:
            xScale = 2**level * self.tileWidth
            yScale = 2**level * self.tileHeight
            x = x / xScale - 0.5
            y = 0.5 - y / yScale
            x = x * self.unitsAcrossLevel0 + self.projectionOrigin[0]
            y = y * self.unitsAcrossLevel0 + self.projectionOrigin[1]

        return x, y

    def toNativePixelCoordinates(self, x, y, crs=None, roundResults=True):
        """Convert a coordinate in the native projection to pixel coordinates.

        :param x: the x coordinate it the native projection.
        :param y: the y coordinate it the native projection.
        :param crs: input projection.  None to use the sources's projection.
        :param roundResults: if True, round the results to the nearest pixel.

        :return: (x, y) the pixel coordinate.
        """
        srcCrs = self.projection if crs is None else make_crs(crs)

        # convert to the native projection
        dstCrs = make_crs(self.getCrs())
        [px], [py] = rio.warp.transform(srcCrs, dstCrs, [x], [y])

        # convert to native pixel coordinates
        af = self._getAffine()
        d = af[1] * af[3] - af[0] * af[4]
        x = (af[2] * af[4] - af[1] * af[5] - af[4] * px + af[1] * py) / d
        y = (af[0] * af[5] - af[2] * af[3] + af[3] * px - af[0] * py) / d

        # convert to integer if requested
        if roundResults:
            x, y = int(round(x)), int(round(y))

        return x, y

    def getPixel(self, **kwargs):
        """Get a single pixel from the current tile source.

        :param kwargs: optional arguments.  Some options are region, output, encoding,
            jpegQuality, jpegSubsampling, tiffCompression, fill.  See tileIterator.

        :returns: a dictionary with the value of the pixel for each channel on a
            scale of [0-255], including alpha, if available.  This may contain
            additional information.
        """
        pixel = super().getPixel(includeTileRecord=True, **kwargs)
        tile = pixel.pop('tile', None)

        if tile:
            # Coordinates in the max level tile
            x, y = tile['gx'], tile['gy']

            if self.projection:
                # convert to a scale of [-0.5, 0.5]
                x = 0.5 + x / 2 ** (self.levels - 1) / self.tileWidth
                y = 0.5 - y / 2 ** (self.levels - 1) / self.tileHeight
                # convert to projection coordinates
                x = self.projectionOrigin[0] + x * self.unitsAcrossLevel0
                y = self.projectionOrigin[1] + y * self.unitsAcrossLevel0
                # convert to native pixel coordinates
                x, y = self.toNativePixelCoordinates(x, y)

            if 0 <= int(x) < self.sizeX and 0 <= int(y) < self.sizeY:
                with self._getDatasetLock:
                    for i in self.dataset.indexes:
                        window = rio.windows.Window(int(x), int(y), 1, 1)
                        try:
                            value = self.dataset.read(
                                i, window=window, resampling=rio.enums.Resampling.nearest,
                            )
                            value = value[0][0]  # there should be 1 single pixel
                            pixel.setdefault('bands', {})[i] = value.item()
                        except RuntimeError:
                            pass
        return pixel

    def _encodeTiledImageFromVips(self, vimg, iterInfo, image, **kwargs):
        raise NotImplementedError

    def getRegion(self, format=(TILE_FORMAT_IMAGE,), **kwargs):
        """Get region.

        Get a rectangular region from the current tile source.  Aspect ratio is preserved.
        If neither width nor height is given, the original size of the highest
        resolution level is used.  If both are given, the returned image will be
        no larger than either size.

        :param format: the desired format or a tuple of allowed formats. Formats
            are members of (TILE_FORMAT_PIL, TILE_FORMAT_NUMPY, TILE_FORMAT_IMAGE).
            If TILE_FORMAT_IMAGE, encoding may be specified.
        :param kwargs: optional arguments.  Some options are region, output, encoding,
            jpegQuality, jpegSubsampling, tiffCompression, fill.  See tileIterator.

        :returns: regionData, formatOrRegionMime: the image data and either the
            mime type, if the format is TILE_FORMAT_IMAGE, or the format.
        """
        # cast format as a tuple if needed
        format = format if isinstance(format, (tuple, set, list)) else (format,)

        if self.projection is None:
            if kwargs.get('encoding') == 'TILED':
                msg = 'getRegion() with TILED output can only be used with a projection.'
                raise NotImplementedError(msg)
            return super().getRegion(format, **kwargs)

        # The tile iterator handles determining the output region
        iterInfo = self.tileIterator(format=TILE_FORMAT_NUMPY, resample=None, **kwargs).info

        if not (
            iterInfo and
            not self._jsonstyle and
            TILE_FORMAT_IMAGE in format and
            kwargs.get('encoding') == 'TILED'
        ):
            return super().getRegion(format, **kwargs)

        left, top = self.pixelToProjection(
            iterInfo['region']['left'], iterInfo['region']['top'], iterInfo['level'])
        right, bottom = self.pixelToProjection(
            iterInfo['region']['right'], iterInfo['region']['bottom'], iterInfo['level'])
        # Be sure to use set output size
        width = iterInfo['output']['width']
        height = iterInfo['output']['height']

        with self._getDatasetLock, tempfile.NamedTemporaryFile(
            suffix='.tiff', prefix='tiledGeoRegion_', delete=False,
        ) as output:

            xres = (right - left) / width
            yres = (top - bottom) / height
            dst_transform = Affine(xres, 0.0, left, 0.0, -yres, top)

            with rio.vrt.WarpedVRT(
                self.dataset,
                resampling=rio.enums.Resampling.nearest,
                crs=self.projection,
                transform=dst_transform,
                height=height,
                width=width,
            ) as vrt:
                data = vrt.read(resampling=rio.enums.Resampling.nearest)

            profile = self.dataset.meta.copy()
            profile.update(
                large_image.tilesource.utilities._rasterioParameters(
                    defaultCompression='lzw', **kwargs,
                ),
            )
            profile.update({
                'crs': self.projection,
                'height': height,
                'width': width,
                'transform': dst_transform,
            })
            with rio.open(output.name, 'w', **profile) as dst:
                dst.write(data)
                # Write colormaps if available
                for i in range(data.shape[0]):
                    if self.dataset.colorinterp[i].name.lower() == 'palette':
                        dst.write_colormap(i + 1, self.dataset.colormap(i + 1))

            return pathlib.Path(output.name), TileOutputMimeTypes['TILED']

    def validateCOG(self, strict=True, warn=True):
        """Check if this image is a valid Cloud Optimized GeoTiff.

        This will raise a :class:`large_image.exceptions.TileSourceInefficientError`
        if not a valid Cloud Optimized GeoTiff. Otherwise, returns True. Requires
        the ``rio-cogeo`` lib.


        :param strict: Enforce warnings as exceptions. Set to False to only warn
            and not raise exceptions.
        :param warn: Log any warnings

        :returns: the validity of the cogtiff
        """
        try:
            from rio_cogeo.cogeo import cog_validate
        except ImportError:
            msg = 'Please install `rio-cogeo` to check COG validity.'
            raise ImportError(msg)

        isValid, errors, warnings = cog_validate(self._largeImagePath, strict=strict)

        if errors:
            raise TileSourceInefficientError(errors)
        if strict and warnings:
            raise TileSourceInefficientError(warnings)
        if warn:
            for warning in warnings:
                self.logger.warning(warning)

        return isValid

    @staticmethod
    def isGeospatial(path):
        """
        Check if a path is likely to be a geospatial file.

        :param path: The path to the file
        :returns: True if geospatial.
        """
        _lazyImport()

        if isinstance(path, rio.io.DatasetReaderBase):
            ds = path
        else:
            try:
                ds = rio.open(path)
            except Exception:
                return False
        if ds.crs or (ds.transform and ds.transform != rio.Affine(1, 0, 0, 0, 1, 0)):
            return True
        if len(ds.gcps[0]) and ds.gcps[1]:
            return True
        return False

    @classmethod
    def addKnownExtensions(cls):
        import rasterio.drivers

        if not hasattr(cls, '_addedExtensions'):
            cls._addedExtensions = True
            cls.extensions = cls.extensions.copy()
            for ext in rasterio.drivers.raster_driver_extensions():
                if ext not in cls.extensions:
                    cls.extensions[ext] = SourcePriority.IMPLICIT


def open(*args, **kwargs):
    """Create an instance of the module class."""
    return RasterioFileTileSource(*args, **kwargs)


def canRead(*args, **kwargs):
    """Check if an input can be read by the module class."""
    return RasterioFileTileSource.canRead(*args, **kwargs)
