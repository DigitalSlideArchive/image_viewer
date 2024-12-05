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
import struct
import tempfile
import threading
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _importlib_version

import numpy as np
import PIL.Image

from large_image.cache_util import LruCacheMetaclass, methodcache
from large_image.constants import (TILE_FORMAT_IMAGE, TILE_FORMAT_NUMPY,
                                   TILE_FORMAT_PIL, SourcePriority,
                                   TileOutputMimeTypes)
from large_image.exceptions import (TileSourceError,
                                    TileSourceFileNotFoundError,
                                    TileSourceInefficientError)
from large_image.tilesource.geo import (GDALBaseFileTileSource,
                                        ProjUnitsAcrossLevel0,
                                        ProjUnitsAcrossLevel0_MaxSize)
from large_image.tilesource.utilities import JSONDict, _gdalParameters, _vipsCast, _vipsParameters

try:
    __version__ = _importlib_version(__name__)
except PackageNotFoundError:
    # package is not installed
    pass

gdal = None
gdal_array = None
gdalconst = None
osr = None
pyproj = None


def _lazyImport():
    """
    Import the gdal module.  This is done when needed rather than in the
    module initialization because it is slow.
    """
    global gdal, gdal_array, gdalconst, osr, pyproj

    if gdal is None:
        try:
            from osgeo import gdal, gdal_array, gdalconst, osr

            try:
                gdal.UseExceptions()
            except Exception:
                pass

            # isort: off

            # pyproj stopped supporting older pythons, so on those versions its
            # database is aging; as such, if on those older versions of python
            # if it is imported before gdal, there can be a database version
            # conflict; importing after gdal avoids this.
            import pyproj

            # isort: on
        except ImportError:
            msg = 'gdal module not found.'
            raise TileSourceError(msg)


class GDALFileTileSource(GDALBaseFileTileSource, metaclass=LruCacheMetaclass):
    """
    Provides tile access to geospatial files.
    """

    cacheName = 'tilesource'
    name = 'gdal'

    def __init__(self, path, projection=None, unitsPerPixel=None, **kwargs):
        """
        Initialize the tile class.  See the base class for other available
        parameters.

        :param path: a filesystem path for the tile source.
        :param projection: None to use pixel space, otherwise a proj4
            projection string or a case-insensitive string of the form
            'EPSG:<epsg number>'.  If a string and case-insensitively prefixed
            with 'proj4:', that prefix is removed.  For instance,
            'proj4:EPSG:3857', 'PROJ4:+init=epsg:3857', and '+init=epsg:3857',
            and 'EPSG:3857' are all equivalent.
        :param unitsPerPixel: The size of a pixel at the 0 tile size.  Ignored
            if the projection is None.  For projections, None uses the default,
            which is the distance between (-180,0) and (180,0) in EPSG:4326
            converted to the projection divided by the tile size.  Proj4
            projections that are not latlong (is_geographic is False) must
            specify unitsPerPixel.
        """
        super().__init__(path, **kwargs)
        _lazyImport()

        self.addKnownExtensions()
        self._bounds = {}
        self._largeImagePath = self._getLargeImagePath()
        try:
            self.dataset = gdal.Open(self._largeImagePath, gdalconst.GA_ReadOnly)
        except (RuntimeError, UnicodeDecodeError):
            if not os.path.isfile(self._largeImagePath):
                raise TileSourceFileNotFoundError(self._largeImagePath) from None
            msg = 'File cannot be opened via GDAL'
            raise TileSourceError(msg)
        self._getDatasetLock = threading.RLock()
        self.tileSize = 256
        self.tileWidth = self.tileSize
        self.tileHeight = self.tileSize
        if projection and projection.lower().startswith('epsg:'):
            projection = projection.lower()
        if projection and not isinstance(projection, bytes):
            projection = projection.encode()
        self.projection = projection
        try:
            with self._getDatasetLock:
                self.sourceSizeX = self.sizeX = self.dataset.RasterXSize
                self.sourceSizeY = self.sizeY = self.dataset.RasterYSize
        except AttributeError as exc:
            if not os.path.isfile(self._largeImagePath):
                raise TileSourceFileNotFoundError(self._largeImagePath) from None
            raise TileSourceError('File cannot be opened via GDAL: %r' % exc)
        is_netcdf = self._checkNetCDF()
        try:
            scale = self.getPixelSizeInMeters()
        except RuntimeError as exc:
            raise TileSourceError('File cannot be opened via GDAL: %r' % exc)
        if not self.sizeX or not self.sizeY:
            msg = 'File cannot be opened via GDAL (no size)'
            raise TileSourceError(msg)
        if (self.projection or self._getDriver() in {
            'PNG',
        }) and not scale and not is_netcdf:
            msg = ('File does not have a projected scale, so will not be '
                   'opened via GDAL with a projection.')
            raise TileSourceError(msg)
        self.sourceLevels = self.levels = int(max(0, math.ceil(max(
            math.log(float(self.sizeX) / self.tileWidth),
            math.log(float(self.sizeY) / self.tileHeight)) / math.log(2))) + 1)
        self._unitsPerPixel = unitsPerPixel
        if self.projection:
            self._initWithProjection(unitsPerPixel)
        self._getPopulatedLevels()
        self._getTileLock = threading.Lock()
        self._setDefaultStyle()

    def _getDriver(self):
        """
        Get the GDAL driver used to read this dataset.

        :returns: The name of the driver.
        """
        if not hasattr(self, '_driver'):
            with self._getDatasetLock:
                if not self.dataset or not self.dataset.GetDriver():
                    self._driver = None
                else:
                    self._driver = self.dataset.GetDriver().ShortName
        return self._driver

    def _checkNetCDF(self):
        if self._getDriver() == 'netCDF':
            msg = 'netCDF file will not be read via GDAL source'
            raise TileSourceError(msg)
        return False

    def _getPopulatedLevels(self):
        try:
            with self._getDatasetLock:
                self._populatedLevels = 1 + self.dataset.GetRasterBand(1).GetOverviewCount()
        except Exception:
            pass

    def _scanForMinMax(self, dtype, frame=None, analysisSize=1024, onlyMinMax=True):
        frame = frame or 0
        bandInfo = self.getBandInformation()
        if (not frame and onlyMinMax and all(
                band.get('min') is not None and band.get('max') is not None
                for band in bandInfo.values())):
            with self._getDatasetLock:
                dtype = gdal_array.GDALTypeCodeToNumericTypeCode(
                    self.dataset.GetRasterBand(1).DataType)
            self._bandRanges[0] = {
                'min': np.array([band['min'] for band in bandInfo.values()], dtype=dtype),
                'max': np.array([band['max'] for band in bandInfo.values()], dtype=dtype),
            }
        else:
            kwargs = {}
            if self.projection:
                bounds = self.getBounds(self.projection)
                kwargs = {'region': {
                    'left': bounds['xmin'],
                    'top': bounds['ymax'],
                    'right': bounds['xmax'],
                    'bottom': bounds['ymin'],
                    'units': 'projection',
                }}
            super(GDALFileTileSource, GDALFileTileSource)._scanForMinMax(
                self, dtype=dtype, frame=frame, analysisSize=analysisSize,
                onlyMinMax=onlyMinMax, **kwargs)
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
        """
        Initialize aspects of the class when a projection is set.
        """
        inProj = self._proj4Proj('epsg:4326')
        # Since we already converted to bytes decoding is safe here
        outProj = self._proj4Proj(self.projection)
        if outProj.crs.is_geographic:
            msg = ('Projection must not be geographic (it needs to use linear '
                   'units, not longitude/latitude).')
            raise TileSourceError(msg)
        if unitsPerPixel:
            self.unitsAcrossLevel0 = float(unitsPerPixel) * self.tileSize
        else:
            self.unitsAcrossLevel0 = ProjUnitsAcrossLevel0.get(self.projection)
            if self.unitsAcrossLevel0 is None:
                # If unitsPerPixel is not specified, the horizontal distance
                # between -180,0 and +180,0 is used.  Some projections (such as
                # stereographic) will fail in this case; they must have a
                # unitsPerPixel specified.
                equator = pyproj.Transformer.from_proj(inProj, outProj, always_xy=True).transform(
                    [-180, 180], [0, 0])
                self.unitsAcrossLevel0 = abs(equator[0][1] - equator[0][0])
                if not self.unitsAcrossLevel0:
                    msg = 'unitsPerPixel must be specified for this projection'
                    raise TileSourceError(msg)
                if len(ProjUnitsAcrossLevel0) >= ProjUnitsAcrossLevel0_MaxSize:
                    ProjUnitsAcrossLevel0.clear()
                ProjUnitsAcrossLevel0[self.projection] = self.unitsAcrossLevel0
        # This was
        #   self.projectionOrigin = pyproj.transform(inProj, outProj, 0, 0)
        # but for consistency, it should probably always be (0, 0).  Whatever
        # renders the map would need the same offset as used here.
        self.projectionOrigin = (0, 0)
        # Calculate values for this projection
        self.levels = int(max(int(math.ceil(
            math.log(self.unitsAcrossLevel0 / self.getPixelSizeInMeters() / self.tileWidth) /
            math.log(2))) + 1, 1))
        # Report sizeX and sizeY as the whole world
        self.sizeX = 2 ** (self.levels - 1) * self.tileWidth
        self.sizeY = 2 ** (self.levels - 1) * self.tileHeight

    @staticmethod
    def getLRUHash(*args, **kwargs):
        return super(GDALFileTileSource, GDALFileTileSource).getLRUHash(
            *args, **kwargs) + ',%s,%s' % (
                kwargs.get('projection', args[1] if len(args) >= 2 else None),
                kwargs.get('unitsPerPixel', args[3] if len(args) >= 4 else None))

    def getState(self):
        return super().getState() + ',%s,%s' % (
            self.projection, self._unitsPerPixel)

    def getProj4String(self):
        """
        Returns proj4 string for the given dataset

        :returns: The proj4 string or None.
        """
        with self._getDatasetLock:
            if self.dataset.GetGCPs() and self.dataset.GetGCPProjection():
                wkt = self.dataset.GetGCPProjection()
            else:
                wkt = self.dataset.GetProjection()
        if not wkt:
            if (self.dataset.GetGeoTransform(can_return_null=True) or
                    hasattr(self, '_netcdf') or self._getDriver() in {'NITF'}):
                return 'epsg:4326'
            return
        proj = osr.SpatialReference()
        proj.ImportFromWkt(wkt)
        return proj.ExportToProj4()

    def _getGeoTransform(self):
        """
        Get the GeoTransform.  If GCPs are used, get the appropriate transform
        for those.

        :returns: a six-component array with the transform
        """
        with self._getDatasetLock:
            gt = self.dataset.GetGeoTransform()
            if (self.dataset.GetGCPProjection() and self.dataset.GetGCPs()):
                gt = gdal.GCPsToGeoTransform(self.dataset.GetGCPs())
        return gt

    @staticmethod
    def _proj4Proj(proj):
        """
        Return a pyproj.Proj based on either a binary or unicode string.

        :param proj: a binary or unicode projection string.
        :returns: a proj4 projection object.  None if the specified projection
            cannot be created.
        """
        _lazyImport()

        if isinstance(proj, bytes):
            proj = proj.decode()
        if not isinstance(proj, str):
            return
        if proj.lower().startswith('proj4:'):
            proj = proj.split(':', 1)[1]
        if proj.lower().startswith('epsg:'):
            proj = proj.lower()
        return pyproj.Proj(proj)

    def toNativePixelCoordinates(self, x, y, proj=None, roundResults=True):
        """
        Convert a coordinate in the native projection (self.getProj4String) to
        pixel coordinates.

        :param x: the x coordinate it the native projection.
        :param y: the y coordinate it the native projection.
        :param proj: input projection.  None to use the source's projection.
        :param roundResults: if True, round the results to the nearest pixel.
        :return: (x, y) the pixel coordinate.
        """
        if proj is None:
            proj = self.projection
        # convert to the native projection
        inProj = self._proj4Proj(proj)
        outProj = self._proj4Proj(self.getProj4String())
        px, py = pyproj.Transformer.from_proj(inProj, outProj, always_xy=True).transform(x, y)
        # convert to native pixel coordinates
        gt = self._getGeoTransform()
        d = gt[2] * gt[4] - gt[1] * gt[5]
        x = (gt[0] * gt[5] - gt[2] * gt[3] - gt[5] * px + gt[2] * py) / d
        y = (gt[1] * gt[3] - gt[0] * gt[4] + gt[4] * px - gt[1] * py) / d
        if roundResults:
            x = int(round(x))
            y = int(round(y))
        return x, y

    def _convertProjectionUnits(self, left, top, right, bottom, width, height,
                                units, **kwargs):
        """
        Given bound information and a units string that consists of a proj4
        projection (starts with `'proj4:'`, `'epsg:'`, `'+proj='` or is an
        enumerated value like `'wgs84'`), convert the bounds to either pixel or
        the class projection coordinates.

        :param left: the left edge (inclusive) of the region to process.
        :param top: the top edge (inclusive) of the region to process.
        :param right: the right edge (exclusive) of the region to process.
        :param bottom: the bottom edge (exclusive) of the region to process.
        :param width: the width of the region to process.  Ignored if both
            left and right are specified.
        :param height: the height of the region to process.  Ignores if both
            top and bottom are specified.
        :param units: either 'projection', a string starting with 'proj4:',
            'epsg:', or '+proj=' or a enumerated value like 'wgs84', or one of
            the super's values.
        :param kwargs: optional parameters.
        :returns: left, top, right, bottom, units.  The new bounds in the
            either pixel or class projection units.
        """
        if not kwargs.get('unitsWH') or kwargs.get('unitsWH') == units:
            if left is None and right is not None and width is not None:
                left = right - width
            if right is None and left is not None and width is not None:
                right = left + width
            if top is None and bottom is not None and height is not None:
                top = bottom - height
            if bottom is None and top is not None and height is not None:
                bottom = top + height
        if (left is None and right is None) or (top is None and bottom is None):
            msg = ('Cannot convert from projection unless at least one of '
                   'left and right and at least one of top and bottom is '
                   'specified.')
            raise TileSourceError(msg)
        if not self.projection:
            pleft, ptop = self.toNativePixelCoordinates(
                right if left is None else left,
                bottom if top is None else top,
                units)
            pright, pbottom = self.toNativePixelCoordinates(
                left if right is None else right,
                top if bottom is None else bottom,
                units)
            units = 'base_pixels'
        else:
            inProj = self._proj4Proj(units)
            outProj = self._proj4Proj(self.projection)
            transformer = pyproj.Transformer.from_proj(inProj, outProj, always_xy=True)
            pleft, ptop = transformer.transform(
                right if left is None else left,
                bottom if top is None else top)
            pright, pbottom = transformer.transform(
                left if right is None else right,
                top if bottom is None else bottom)
            units = 'projection'
        left = pleft if left is not None else None
        top = ptop if top is not None else None
        right = pright if right is not None else None
        bottom = pbottom if bottom is not None else None
        return left, top, right, bottom, units

    def pixelToProjection(self, x, y, level=None):
        """
        Convert from pixels back to projection coordinates.

        :param x, y: base pixel coordinates.
        :param level: the level of the pixel.  None for maximum level.
        :returns: x, y in projection coordinates.
        """
        if level is None:
            level = self.levels - 1
        if not self.projection:
            x *= 2 ** (self.levels - 1 - level)
            y *= 2 ** (self.levels - 1 - level)
            gt = self._getGeoTransform()
            px = gt[0] + gt[1] * x + gt[2] * y
            py = gt[3] + gt[4] * x + gt[5] * y
            return px, py
        xScale = 2 ** level * self.tileWidth
        yScale = 2 ** level * self.tileHeight
        x = x / xScale - 0.5
        y = 0.5 - y / yScale
        x = x * self.unitsAcrossLevel0 + self.projectionOrigin[0]
        y = y * self.unitsAcrossLevel0 + self.projectionOrigin[1]
        return x, y

    def getBounds(self, srs=None):
        """
        Returns bounds of the image.

        :param srs: the projection for the bounds.  None for the default 4326.
        :returns: an object with the four corners and the projection that was
            used.  None if we don't know the original projection.
        """
        if srs not in self._bounds:
            gt = self._getGeoTransform()
            nativeSrs = self.getProj4String()
            if not nativeSrs or not gt:
                self._bounds[srs] = None
                return
            bounds = {
                'll': {
                    'x': gt[0] + self.sourceSizeY * gt[2],
                    'y': gt[3] + self.sourceSizeY * gt[5],
                },
                'ul': {
                    'x': gt[0],
                    'y': gt[3],
                },
                'lr': {
                    'x': gt[0] + self.sourceSizeX * gt[1] + self.sourceSizeY * gt[2],
                    'y': gt[3] + self.sourceSizeX * gt[4] + self.sourceSizeY * gt[5],
                },
                'ur': {
                    'x': gt[0] + self.sourceSizeX * gt[1],
                    'y': gt[3] + self.sourceSizeX * gt[4],
                },
                'srs': nativeSrs,
            }
            # Make sure geographic coordinates do not exceed their limits
            if self._proj4Proj(nativeSrs).crs.is_geographic and srs:
                try:
                    self._proj4Proj(srs)(0, 90, errcheck=True)
                    yBound = 90.0
                except RuntimeError:
                    yBound = 89.999999
                keys = ('ll', 'ul', 'lr', 'ur')
                for key in keys:
                    bounds[key]['y'] = max(min(bounds[key]['y'], yBound), -yBound)
                dx = min(bounds[key]['x'] for key in keys)
                if dx < -180 or dx >= 180:
                    dx = ((dx + 180) % 360 - 180) - dx
                    for key in keys:
                        bounds[key]['x'] += dx
                if any(bounds[key]['x'] >= 180 for key in keys):
                    bounds['ul']['x'] = bounds['ll']['x'] = -180
                    bounds['ur']['x'] = bounds['lr']['x'] = 180
            if srs and srs != nativeSrs:
                inProj = self._proj4Proj(nativeSrs)
                outProj = self._proj4Proj(srs)
                keys = ('ll', 'ul', 'lr', 'ur')
                pts = pyproj.Transformer.from_proj(inProj, outProj, always_xy=True).itransform([
                    (bounds[key]['x'], bounds[key]['y']) for key in keys])
                for idx, pt in enumerate(pts):
                    key = keys[idx]
                    bounds[key]['x'] = pt[0]
                    bounds[key]['y'] = pt[1]
                bounds['srs'] = srs.decode() if isinstance(srs, bytes) else srs
            bounds['xmin'] = min(bounds['ll']['x'], bounds['ul']['x'],
                                 bounds['lr']['x'], bounds['ur']['x'])
            bounds['xmax'] = max(bounds['ll']['x'], bounds['ul']['x'],
                                 bounds['lr']['x'], bounds['ur']['x'])
            bounds['ymin'] = min(bounds['ll']['y'], bounds['ul']['y'],
                                 bounds['lr']['y'], bounds['ur']['y'])
            bounds['ymax'] = max(bounds['ll']['y'], bounds['ul']['y'],
                                 bounds['lr']['y'], bounds['ur']['y'])
            self._bounds[srs] = bounds
        return self._bounds[srs]

    def getBandInformation(self, statistics=True, dataset=None, **kwargs):
        """
        Get information about each band in the image.

        :param statistics: if True, compute statistics if they don't already
            exist.  Ignored: always treated as True.
        :param dataset: the dataset.  If None, use the main dataset.
        :returns: a list of one dictionary per band.  Each dictionary contains
            known values such as interpretation, min, max, mean, stdev, nodata,
            scale, offset, units, categories, colortable, maskband.
        """
        if not getattr(self, '_bandInfo', None) or dataset:
            with self._getDatasetLock:
                cache = not dataset
                if not dataset:
                    dataset = self.dataset
                infoSet = JSONDict({})
                for i in range(dataset.RasterCount):
                    band = dataset.GetRasterBand(i + 1)
                    info = {}
                    try:
                        stats = band.GetStatistics(True, True)
                        # The statistics provide a min and max, so we don't
                        # fetch those separately
                        info.update(dict(zip(('min', 'max', 'mean', 'stdev'), stats)))
                    except (RuntimeError, TypeError):
                        self.logger.info('Failed to get statistics for band %d', i + 1)
                    info['nodata'] = band.GetNoDataValue()
                    info['scale'] = band.GetScale()
                    info['offset'] = band.GetOffset()
                    info['units'] = band.GetUnitType()
                    info['categories'] = band.GetCategoryNames()
                    interp = band.GetColorInterpretation()
                    info['interpretation'] = {
                        gdalconst.GCI_GrayIndex: 'gray',
                        gdalconst.GCI_PaletteIndex: 'palette',
                        gdalconst.GCI_RedBand: 'red',
                        gdalconst.GCI_GreenBand: 'green',
                        gdalconst.GCI_BlueBand: 'blue',
                        gdalconst.GCI_AlphaBand: 'alpha',
                        gdalconst.GCI_HueBand: 'hue',
                        gdalconst.GCI_SaturationBand: 'saturation',
                        gdalconst.GCI_LightnessBand: 'lightness',
                        gdalconst.GCI_CyanBand: 'cyan',
                        gdalconst.GCI_MagentaBand: 'magenta',
                        gdalconst.GCI_YellowBand: 'yellow',
                        gdalconst.GCI_BlackBand: 'black',
                        gdalconst.GCI_YCbCr_YBand: 'Y',
                        gdalconst.GCI_YCbCr_CbBand: 'Cb',
                        gdalconst.GCI_YCbCr_CrBand: 'Cr',
                    }.get(interp, interp)
                    if band.GetColorTable():
                        info['colortable'] = [band.GetColorTable().GetColorEntry(pos)
                                              for pos in range(band.GetColorTable().GetCount())]
                    if band.GetMaskBand():
                        info['maskband'] = band.GetMaskBand().GetBand() or None
                    # Only keep values that aren't None or the empty string
                    infoSet[i + 1] = {
                        k: v for k, v in info.items()
                        if v not in (None, '') and not (
                            isinstance(v, float) and
                            math.isnan(v)
                        )
                    }
            if not cache:
                return infoSet
            self._bandInfo = infoSet
        return self._bandInfo

    @property
    def geospatial(self):
        """
        This is true if the source has geospatial information.
        """
        return bool(
            self.dataset.GetProjection() or
            (self.dataset.GetGCPProjection() and self.dataset.GetGCPs()) or
            self.dataset.GetGeoTransform(can_return_null=True) or
            hasattr(self, '_netcdf'))

    def getMetadata(self):
        metadata = super().getMetadata()
        with self._getDatasetLock:
            metadata.update({
                'geospatial': self.geospatial,
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
        """
        Return additional known metadata about the tile source.  Data returned
        from this method is not guaranteed to be in any particular format or
        have specific values.

        :returns: a dictionary of data or None.
        """
        result = JSONDict({})
        with self._getDatasetLock:
            result['driverShortName'] = self.dataset.GetDriver().ShortName
            result['driverLongName'] = self.dataset.GetDriver().LongName
            result['fileList'] = self.dataset.GetFileList()
            result['RasterXSize'] = self.dataset.RasterXSize
            result['RasterYSize'] = self.dataset.RasterYSize
            result['GeoTransform'] = self._getGeoTransform()
            result['Projection'] = self.dataset.GetProjection()
            result['proj4Projection'] = self.getProj4String()
            result['GCPProjection'] = self.dataset.GetGCPProjection()
            if self.dataset.GetGCPs():
                result['GCPs'] = [{
                    'id': gcp.Id, 'line': gcp.GCPLine, 'pixel': gcp.GCPPixel,
                    'x': gcp.GCPX, 'y': gcp.GCPY, 'z': gcp.GCPZ}
                    for gcp in self.dataset.GetGCPs()]
            result['Metadata'] = self.dataset.GetMetadata_List()
            for key in ['IMAGE_STRUCTURE', 'SUBDATASETS', 'GEOLOCATION', 'RPC']:
                metadatalist = self.dataset.GetMetadata_List(key)
                if metadatalist:
                    result['Metadata_' + key] = metadatalist
        if hasattr(self, '_netcdf'):
            # To ensure all band information from all subdatasets in netcdf,
            # we could do the following:
            # for key in self._netcdf['datasets']:
            #     dataset = self._netcdf['datasets'][key]
            #     if 'bands' not in dataset:
            #         gdaldataset = gdal.Open(dataset['name'], gdalconst.GA_ReadOnly)
            #         dataset['bands'] = self.getBandInformation(gdaldataset)
            #         dataset['sizeX'] = gdaldataset.RasterXSize
            #         dataset['sizeY'] = gdaldataset.RasterYSize
            result['netcdf'] = self._netcdf
        return result

    def _bandNumber(self, band, exc=True):  # TODO: use super method?
        """
        Given a band number or interpretation name, return a validated band
        number.

        :param band: either -1, a positive integer, or the name of a band
            interpretation that is present in the tile source.
        :param exc: if True, raise an exception if no band matches.
        :returns: a validated band, either 1 or a positive integer, or None if
            no matching band and exceptions are not enabled.
        """
        if hasattr(self, '_netcdf') and (':' in str(band) or str(band).isdigit()):
            key = None
            if ':' in str(band):
                key, band = band.split(':', 1)
            if str(band).isdigit():
                band = int(band)
            else:
                band = 1
            if not key or key == 'default':
                key = self._netcdf.get('default', None)
                if key is None:
                    return band
            if key in self._netcdf['datasets']:
                return (key, band)
        bands = self.getBandInformation()
        if not isinstance(band, int):
            try:
                band = next(bandIdx for bandIdx in sorted(bands)
                            if band == bands[bandIdx]['interpretation'])
            except StopIteration:
                pass
        if hasattr(band, 'isdigit') and band.isdigit():
            band = int(band)
        if band != -1 and band not in bands:
            if exc:
                msg = ('Band has to be a positive integer, -1, or a band '
                       'interpretation found in the source.')
                raise TileSourceError(msg)
            return None
        return int(band)

    @methodcache()
    def getTile(self, x, y, z, pilImageAllowed=False, numpyAllowed=False, **kwargs):
        if not self.projection:
            self._xyzInRange(x, y, z)
            factor = int(2 ** (self.levels - 1 - z))
            x0 = int(x * factor * self.tileWidth)
            y0 = int(y * factor * self.tileHeight)
            x1 = int(min(x0 + factor * self.tileWidth, self.sourceSizeX))
            y1 = int(min(y0 + factor * self.tileHeight, self.sourceSizeY))
            w = int(max(1, round((x1 - x0) / factor)))
            h = int(max(1, round((y1 - y0) / factor)))
            with self._getDatasetLock:
                try:
                    tile = self.dataset.ReadAsArray(
                        xoff=x0, yoff=y0, xsize=x1 - x0, ysize=y1 - y0, buf_xsize=w, buf_ysize=h)
                except Exception:
                    self.logger.exception('Failed to getTile')
                    tile = np.zeros((1, 1))
        else:
            xmin, ymin, xmax, ymax = self.getTileCorners(z, x, y)
            bounds = self.getBounds(self.projection)
            if (xmin >= bounds['xmax'] or xmax <= bounds['xmin'] or
                    ymin >= bounds['ymax'] or ymax <= bounds['ymin']):
                pilimg = PIL.Image.new('RGBA', (self.tileWidth, self.tileHeight))
                return self._outputTile(
                    pilimg, TILE_FORMAT_PIL, x, y, z, applyStyle=False, **kwargs)
            res = (self.unitsAcrossLevel0 / self.tileSize) * (2 ** -z)
            if not hasattr(self, '_warpSRS'):
                self._warpSRS = (self.getProj4String(),
                                 self.projection.decode())
            with self._getDatasetLock:
                ds = gdal.Warp(
                    '', self.dataset, format='VRT',
                    srcSRS=self._warpSRS[0], dstSRS=self._warpSRS[1],
                    dstAlpha=True,
                    # Valid options are GRA_NearestNeighbour, GRA_Bilinear,
                    # GRA_Cubic, GRA_CubicSpline, GRA_Lanczos, GRA_Med,
                    # GRA_Mode, perhaps others; because we have some indexed
                    # datasets, generically, this should probably either be
                    # GRA_NearestNeighbour or GRA_Mode.
                    resampleAlg=gdal.GRA_NearestNeighbour,
                    multithread=True,
                    # We might get a speed-up with acceptable distortion if we
                    # set the polynomialOrder or ask for an optimal transform
                    # around the outputBounds.
                    polynomialOrder=1,
                    xRes=res, yRes=res, outputBounds=[xmin, ymin, xmax, ymax])
                try:
                    tile = ds.ReadAsArray()
                except Exception:
                    self.logger.exception('Failed to getTile')
                    tile = np.zeros((1, 1))
        if len(tile.shape) == 3:
            tile = np.rollaxis(tile, 0, 3)
        return self._outputTile(tile, TILE_FORMAT_NUMPY, x, y, z,
                                pilImageAllowed, numpyAllowed, **kwargs)

    def getPixel(self, **kwargs):
        """
        Get a single pixel from the current tile source.

        :param kwargs: optional arguments.  Some options are region, output,
            encoding, jpegQuality, jpegSubsampling, tiffCompression, fill.  See
            tileIterator.
        :returns: a dictionary with the value of the pixel for each channel on
            a scale of [0-255], including alpha, if available.  This may
            contain additional information.
        """
        # TODO: netCDF - currently this will read the values from the
        # default subdatatset; we may want it to read values from all
        # subdatasets and the main raster bands (if they exist), and label the
        # bands better
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
                    for i in range(self.dataset.RasterCount):
                        band = self.dataset.GetRasterBand(i + 1)
                        try:
                            value = band.ReadRaster(int(x), int(y), 1, 1, buf_type=gdal.GDT_Float32)
                            if value:
                                pixel.setdefault('bands', {})[i + 1] = struct.unpack('f', value)[0]
                        except RuntimeError:
                            pass
        return pixel

    def _encodeTiledImageFromVips(self, vimg, iterInfo, image, **kwargs):
        """
        Save a vips image as a tiled tiff.

        :param vimg: a vips image.
        :param iterInfo: information about the region based on the tile
            iterator.
        :param image: a record with partial vips images and the current output
            size.

        Additional parameters are available.

        :param compression: the internal compression format.  This can handle
            a variety of options similar to the converter utility.
        :returns: a pathlib.Path of the output file and the output mime type.
        """
        convertParams = _vipsParameters(defaultCompression='lzw', **kwargs)
        convertParams.pop('pyramid', None)
        vimg = _vipsCast(vimg, convertParams['compression'] in {'webp', 'jpeg'})
        gdalParams = _gdalParameters(defaultCompression='lzw', **kwargs)
        for ch in range(image['channels']):
            gdalParams += [
                '-b' if ch not in (1, 3) or ch + 1 != image['channels'] else '-mask', str(ch + 1)]
        tl = self.pixelToProjection(
            iterInfo['region']['left'], iterInfo['region']['top'], iterInfo['level'])
        br = self.pixelToProjection(
            iterInfo['region']['right'], iterInfo['region']['bottom'], iterInfo['level'])
        gdalParams += [
            '-a_srs',
            iterInfo['metadata']['bounds']['srs'],
            '-a_ullr',
            str(tl[0]),
            str(tl[1]),
            str(br[0]),
            str(br[1]),
        ]
        fd, tempPath = tempfile.mkstemp('.tiff', 'tiledRegion_')
        os.close(fd)
        fd, outputPath = tempfile.mkstemp('.tiff', 'tiledGeoRegion_')
        os.close(fd)
        try:
            vimg.write_to_file(tempPath, **convertParams)
            ds = gdal.Open(tempPath, gdalconst.GA_ReadOnly)
            gdal.Translate(outputPath, ds, options=gdalParams)
            os.unlink(tempPath)
        except Exception as exc:
            try:
                os.unlink(tempPath)
            except Exception:
                pass
            try:
                os.unlink(outputPath)
            except Exception:
                pass
            raise exc
        return pathlib.Path(outputPath), TileOutputMimeTypes['TILED']

    def getRegion(self, format=(TILE_FORMAT_IMAGE, ), **kwargs):
        """
        Get a rectangular region from the current tile source.  Aspect ratio is
        preserved.  If neither width nor height is given, the original size of
        the highest resolution level is used.  If both are given, the returned
        image will be no larger than either size.

        :param format: the desired format or a tuple of allowed formats.
            Formats are members of (TILE_FORMAT_PIL, TILE_FORMAT_NUMPY,
            TILE_FORMAT_IMAGE).  If TILE_FORMAT_IMAGE, encoding may be
            specified.
        :param kwargs: optional arguments.  Some options are region, output,
            encoding, jpegQuality, jpegSubsampling, tiffCompression, fill.  See
            tileIterator.
        :returns: regionData, formatOrRegionMime: the image data and either the
            mime type, if the format is TILE_FORMAT_IMAGE, or the format.
        """
        if not isinstance(format, (tuple, set, list)):
            format = (format, )
        # The tile iterator handles determining the output region
        if 'resample' in kwargs:
            kwargs = kwargs.copy()
            kwargs.pop('resample')
        iterInfo = self.tileIterator(format=TILE_FORMAT_NUMPY, resample=None, **kwargs).info
        # Only use gdal.Warp of the original image if the region has not been
        # styled.
        useGDALWarp = (
            iterInfo and
            not self._jsonstyle and
            TILE_FORMAT_IMAGE in format and
            kwargs.get('encoding') == 'TILED')
        if not useGDALWarp:
            return super().getRegion(format, **kwargs)
        srs = self.projection or self.getProj4String()
        tl = self.pixelToProjection(
            iterInfo['region']['left'], iterInfo['region']['top'], iterInfo['level'])
        br = self.pixelToProjection(
            iterInfo['region']['right'], iterInfo['region']['bottom'], iterInfo['level'])
        outWidth = iterInfo['output']['width']
        outHeight = iterInfo['output']['height']
        gdalParams = _gdalParameters(defaultCompression='lzw', **kwargs)
        gdalParams += ['-t_srs', srs] if srs is not None else [
            '-to', 'SRC_METHOD=NO_GEOTRANSFORM']
        gdalParams += [
            '-te', str(tl[0]), str(br[1]), str(br[0]), str(tl[1]),
            '-ts', str(int(math.floor(outWidth))), str(int(math.floor(outHeight))),
        ]

        fd, outputPath = tempfile.mkstemp('.tiff', 'tiledGeoRegion_')
        os.close(fd)
        try:
            self.logger.info('Using gdal warp %r', gdalParams)
            ds = gdal.Open(self._largeImagePath, gdalconst.GA_ReadOnly)
            gdal.Warp(outputPath, ds, options=gdalParams)
        except Exception as exc:
            try:
                os.unlink(outputPath)
            except Exception:
                pass
            raise exc
        return pathlib.Path(outputPath), TileOutputMimeTypes['TILED']

    def validateCOG(self, check_tiled=True, full_check=False, strict=True, warn=True):
        """Check if this image is a valid Cloud Optimized GeoTiff.

        This will raise a :class:`large_image.exceptions.TileSourceInefficientError`
        if not a valid Cloud Optimized GeoTiff. Otherwise, returns True.

        Requires the ``osgeo_utils`` package.

        Parameters
        ----------
        check_tiled : bool
            Set to False to ignore missing tiling.
        full_check : bool
            Set to True to check tile/strip leader/trailer bytes.
            Might be slow on remote files
        strict : bool
            Enforce warnings as exceptions. Set to False to only warn and not
            raise exceptions.
        warn : bool
            Log any warnings

        """
        from osgeo_utils.samples.validate_cloud_optimized_geotiff import validate

        warnings, errors, details = validate(
            self._largeImagePath,
            check_tiled=check_tiled,
            full_check=full_check,
        )
        if errors:
            raise TileSourceInefficientError(errors)
        if strict and warnings:
            raise TileSourceInefficientError(warnings)
        if warn:
            for warning in warnings:
                self.logger.warning(warning)
        return True

    @staticmethod
    def isGeospatial(path):
        """
        Check if a path is likely to be a geospatial file.

        :param path: The path to the file
        :returns: True if geospatial.
        """
        _lazyImport()

        try:
            ds = gdal.Open(str(path), gdalconst.GA_ReadOnly)
        except Exception:
            return False
        if ds:
            if ds.GetGCPs() and ds.GetGCPProjection():
                return True
            if ds.GetProjection():
                return True
            if ds.GetGeoTransform(can_return_null=True):
                w = ds.RasterXSize
                h = ds.RasterYSize
                trans = ds.GetGeoTransform(can_return_null=True)
                cornersy = [trans[3] + x * trans[4] + y * trans[5]
                            for x, y in {(0, 0), (0, h), (w, 0), (w, h)}]
                if min(cornersy) >= -90 and max(cornersy) <= 90:
                    return True
            if ds.GetDriver().ShortName in {'NITF', 'netCDF'}:
                return True
        return False

    @classmethod
    def addKnownExtensions(cls):
        if not hasattr(cls, '_addedExtensions'):
            _lazyImport()

            cls._addedExtensions = True
            cls.extensions = cls.extensions.copy()
            cls.mimeTypes = cls.mimeTypes.copy()
            for idx in range(gdal.GetDriverCount()):
                drv = gdal.GetDriver(idx)
                if drv.GetMetadataItem(gdal.DCAP_RASTER):
                    drvexts = drv.GetMetadataItem(gdal.DMD_EXTENSIONS)
                    if drvexts is not None:
                        for ext in drvexts.split():
                            if ext.lower() not in cls.extensions:
                                cls.extensions[ext.lower()] = SourcePriority.IMPLICIT
                    drvmimes = drv.GetMetadataItem(gdal.DMD_MIMETYPE)
                    if drvmimes is not None:
                        if drvmimes not in cls.mimeTypes:
                            cls.mimeTypes[drvmimes] = SourcePriority.IMPLICIT


def open(*args, **kwargs):
    """
    Create an instance of the module class.
    """
    return GDALFileTileSource(*args, **kwargs)


def canRead(*args, **kwargs):
    """
    Check if an input can be read by the module class.
    """
    return GDALFileTileSource.canRead(*args, **kwargs)
