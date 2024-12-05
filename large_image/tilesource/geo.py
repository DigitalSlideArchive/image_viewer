import pathlib
from typing import Any, Callable, Dict, List, Optional, Tuple, Union, cast
from urllib.parse import urlencode, urlparse

import numpy as np
import PIL.Image

from ..cache_util import CacheProperties, methodcache
from ..constants import SourcePriority, TileInputUnits
from ..exceptions import TileSourceError
from .base import FileTileSource
from .utilities import ImageBytes, JSONDict, getPaletteColors

# Inform the tile source cache about the potential size of this tile source
CacheProperties['tilesource']['itemExpectedSize'] = max(
    CacheProperties['tilesource']['itemExpectedSize'],
    100 * 1024 ** 2)

# Used to cache pixel size for projections
ProjUnitsAcrossLevel0: Dict[str, float] = {}
ProjUnitsAcrossLevel0_MaxSize = 100


def make_vsi(url: Union[str, pathlib.Path, Dict[Any, Any]], **options) -> str:
    if str(url).startswith('s3://'):
        s3_path = str(url).replace('s3://', '')
        vsi = f'/vsis3/{s3_path}'
    else:
        gdal_options = {
            'url': str(url),
            'use_head': 'no',
            'list_dir': 'no',
        }
        gdal_options.update(options)
        vsi = f'/vsicurl?{urlencode(gdal_options)}'
    return vsi


class GeoBaseFileTileSource(FileTileSource):
    """Abstract base class for geospatial tile sources."""

    _geospatial_source = True


class GDALBaseFileTileSource(GeoBaseFileTileSource):
    """Abstract base class for GDAL-based tile sources.

    This base class assumes the underlying library is powered by GDAL
    (rasterio, mapnik, etc.)
    """

    _unstyledStyle = '{}'

    extensions = {
        None: SourcePriority.MEDIUM,
        'geotiff': SourcePriority.PREFERRED,
        # National Imagery Transmission Format
        'ntf': SourcePriority.PREFERRED,
        'nitf': SourcePriority.PREFERRED,
        'tif': SourcePriority.LOW,
        'tiff': SourcePriority.LOW,
        'vrt': SourcePriority.PREFERRED,
    }
    mimeTypes = {
        None: SourcePriority.FALLBACK,
        'image/geotiff': SourcePriority.PREFERRED,
        'image/tiff': SourcePriority.LOW,
        'image/x-tiff': SourcePriority.LOW,
    }

    projection: Union[str, bytes]
    projectionOrigin: Tuple[float, float]
    sourceLevels: int
    sourceSizeX: int
    sourceSizeY: int
    unitsAcrossLevel0: float

    def _getDriver(self) -> str:
        """
        Get the GDAL driver used to read this dataset.

        :returns: The name of the driver.
        """
        raise NotImplementedError

    def _convertProjectionUnits(self, *args, **kwargs) -> Tuple[float, float, float, float, str]:
        raise NotImplementedError

    def pixelToProjection(self, *args, **kwargs) -> Tuple[float, float]:
        raise NotImplementedError

    def toNativePixelCoordinates(self, *args, **kwargs) -> Tuple[float, float]:
        raise NotImplementedError

    def getBounds(self, *args, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError

    @staticmethod
    def isGeospatial(path: Union[str, pathlib.Path]) -> bool:
        """
        Check if a path is likely to be a geospatial file.

        :param path: The path to the file
        :returns: True if geospatial.
        """
        raise NotImplementedError

    @property
    def geospatial(self) -> bool:
        """
        This is true if the source has geospatial information.
        """
        return bool(self.projection)

    def _getLargeImagePath(self) -> str:
        """Get GDAL-compatible image path.

        This will cast the output to a string and can also handle URLs
        ('http', 'https', 'ftp', 's3') for use with GDAL
        `Virtual Filesystems Interface <https://gdal.org/user/virtual_file_systems.html>`_.
        """
        if urlparse(str(self.largeImagePath)).scheme in {'http', 'https', 'ftp', 's3'}:
            return make_vsi(self.largeImagePath)
        return str(self.largeImagePath)

    def _setStyle(self, style: Any) -> None:
        """
        Check and set the specified style from a json string or a dictionary.

        :param style: The new style.
        """
        super()._setStyle(style)
        if hasattr(self, '_getTileLock'):
            self._setDefaultStyle()

    def _styleBands(self) -> List[Dict[str, Any]]:
        interpColorTable = {
            'red': ['#000000', '#ff0000'],
            'green': ['#000000', '#00ff00'],
            'blue': ['#000000', '#0000ff'],
            'gray': ['#000000', '#ffffff'],
            'alpha': ['#ffffff00', '#ffffffff'],
        }
        style = []
        if hasattr(self, '_style'):
            styleBands = (cast(JSONDict, self.style)['bands']
                          if 'bands' in cast(JSONDict, self.style) else [self.style])
            for styleBand in styleBands:

                styleBand = styleBand.copy()
                # Default to band 1 -- perhaps we should default to gray or
                # green instead.
                styleBand['band'] = self._bandNumber(styleBand.get('band', 1))
                style.append(styleBand)
        if not len(style):
            for interp in ('red', 'green', 'blue', 'gray', 'palette', 'alpha'):
                band = self._bandNumber(interp, False)
                # If we don't have the requested band, or we only have alpha,
                # or this is gray or palette and we already added another band,
                # skip this interpretation.
                if (band is None or
                        (interp == 'alpha' and not len(style)) or
                        (interp in ('gray', 'palette') and len(style))):
                    continue
                if interp == 'palette':
                    bandInfo = self.getOneBandInformation(band)
                    style.append({
                        'band': band,
                        'palette': 'colortable',
                        'min': 0,
                        'max': len(bandInfo['colortable']) - 1})
                else:
                    style.append({
                        'band': band,
                        'palette': interpColorTable[interp],
                        'min': 'auto',
                        'max': 'auto',
                        'nodata': 'auto',
                        'composite': 'multiply' if interp == 'alpha' else 'lighten',
                    })
        return style

    def _setDefaultStyle(self) -> None:
        """If no style was specified, create a default style."""
        self._bandNames = {}
        for idx, band in self.getBandInformation().items():
            if band.get('interpretation'):
                self._bandNames[band['interpretation'].lower()] = idx
        if isinstance(getattr(self, '_style', None), dict) and (
                not self._style or 'icc' in self._style and len(self._style) == 1):
            return
        if hasattr(self, '_style'):
            styleBands = (cast(JSONDict, self.style)['bands']
                          if 'bands' in cast(JSONDict, self.style) else [self.style])
            if not len(styleBands) or (len(styleBands) == 1 and isinstance(
                    styleBands[0].get('band', 1), int) and styleBands[0].get('band', 1) <= 0):
                del self._style
        style = self._styleBands()
        if len(style):
            hasAlpha = False
            for bstyle in style:
                hasAlpha = hasAlpha or self.getOneBandInformation(
                    bstyle.get('band', 0)).get('interpretation') == 'alpha'
                if 'palette' in bstyle:
                    if bstyle['palette'] == 'colortable':
                        bandInfo = self.getOneBandInformation(bstyle.get('band', 0))
                        bstyle['palette'] = [(
                            '#%02X%02X%02X' if len(entry) == 3 else
                            '#%02X%02X%02X%02X') % entry for entry in bandInfo['colortable']]
                    else:
                        bstyle['palette'] = self.getHexColors(bstyle['palette'])
                if bstyle.get('nodata') == 'auto':
                    bandInfo = self.getOneBandInformation(bstyle.get('band', 0))
                    bstyle['nodata'] = bandInfo.get('nodata', None)
            if not hasAlpha and self.projection:
                style.append({
                    'band': (
                        self._bandNumber('alpha', False)
                        if self._bandNumber('alpha', False) is not None else
                        (len(self.getBandInformation()) + 1)),
                    'min': 0,
                    'max': 'auto',
                    'composite': 'multiply',
                    'palette': ['#ffffff00', '#ffffffff'],
                })
            self.logger.debug('Using style %r', style)
            self._style = JSONDict({'bands': style})

    @staticmethod
    def getHexColors(palette: Union[str, List[Union[str, float, Tuple[float, ...]]]]) -> List[str]:
        """
        Returns list of hex colors for a given color palette

        :returns: List of colors
        """
        pal = getPaletteColors(palette)
        return ['#%02X%02X%02X%02X' % tuple(int(val) for val in clr) for clr in pal]

    def getPixelSizeInMeters(self) -> Optional[float]:
        """
        Get the approximate base pixel size in meters.  This is calculated as
        the average scale of the four edges in the WGS84 ellipsoid.

        :returns: the pixel size in meters or None.
        """
        bounds = self.getBounds('epsg:4326')
        if not bounds:
            return None
        try:
            import pyproj

            geod = pyproj.Geod(ellps='WGS84')
            computer = cast(Callable[[Any, Any, Any, Any], Tuple[Any, Any, float]], geod.inv)
        except Exception:
            # Estimate based on great-circle distance
            def computer(lon1, lat1, lon2, lat2) -> Tuple[Any, Any, float]:
                from math import acos, cos, radians, sin
                lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
                return None, None, 6.378e+6 * (
                    acos(sin(lat1) * sin(lat2) + cos(lat1) * cos(lat2) * cos(lon1 - lon2))
                )
        _, _, s1 = computer(bounds['ul']['x'], bounds['ul']['y'],
                            bounds['ur']['x'], bounds['ur']['y'])
        _, _, s2 = computer(bounds['ur']['x'], bounds['ur']['y'],
                            bounds['lr']['x'], bounds['lr']['y'])
        _, _, s3 = computer(bounds['lr']['x'], bounds['lr']['y'],
                            bounds['ll']['x'], bounds['ll']['y'])
        _, _, s4 = computer(bounds['ll']['x'], bounds['ll']['y'],
                            bounds['ul']['x'], bounds['ul']['y'])
        return (s1 + s2 + s3 + s4) / (self.sourceSizeX * 2 + self.sourceSizeY * 2)

    def getNativeMagnification(self) -> Dict[str, Optional[float]]:
        """
        Get the magnification at the base level.

        :return: width of a pixel in mm, height of a pixel in mm.
        """
        scale = self.getPixelSizeInMeters()
        return {
            'magnification': None,
            'mm_x': scale * 100 if scale else None,
            'mm_y': scale * 100 if scale else None,
        }

    def getTileCorners(self, z: int, x: float, y: float) -> Tuple[float, float, float, float]:
        """
        Returns bounds of a tile for a given x,y,z index.

        :param z: tile level
        :param x: tile offset from left.
        :param y: tile offset from right
        :returns: (xmin, ymin, xmax, ymax) in the current projection or base
            pixels.
        """
        x, y = float(x), float(y)
        if self.projection:
            # Scale tile into the range [-0.5, 0.5], [-0.5, 0.5]
            xmin = -0.5 + x / 2.0 ** z
            xmax = -0.5 + (x + 1) / 2.0 ** z
            ymin = 0.5 - (y + 1) / 2.0 ** z
            ymax = 0.5 - y / 2.0 ** z
            # Convert to projection coordinates
            xmin = self.projectionOrigin[0] + xmin * self.unitsAcrossLevel0
            xmax = self.projectionOrigin[0] + xmax * self.unitsAcrossLevel0
            ymin = self.projectionOrigin[1] + ymin * self.unitsAcrossLevel0
            ymax = self.projectionOrigin[1] + ymax * self.unitsAcrossLevel0
        else:
            xmin = 2 ** (self.sourceLevels - 1 - z) * x * self.tileWidth
            ymin = 2 ** (self.sourceLevels - 1 - z) * y * self.tileHeight
            xmax = xmin + 2 ** (self.sourceLevels - 1 - z) * self.tileWidth
            ymax = ymin + 2 ** (self.sourceLevels - 1 - z) * self.tileHeight
            ymin, ymax = self.sourceSizeY - ymax, self.sourceSizeY - ymin
        return xmin, ymin, xmax, ymax

    def _bandNumber(self, band: Optional[Union[str, int]], exc: bool = True) -> Optional[int]:
        """Given a band number or interpretation name, return a validated band number.

        :param band: either -1, a positive integer, or the name of a band interpretation
            that is present in the tile source.
        :param exc: if True, raise an exception if no band matches.

        :returns: a validated band, either 1 or a positive integer, or None if no
            matching band and exceptions are not enabled.
        """
        # retrieve the bands information from the initial dataset or cache
        bands = self.getBandInformation()

        # search for the band with multiple methods
        if isinstance(band, str) and str(band).isdigit():
            band = int(band)
        elif isinstance(band, str):
            band = next((i for i in bands if band == bands[i]['interpretation']), None)

        # set to None if not included in the possible band values
        isBandNumber = band == -1 or band in bands
        band = band if isBandNumber else None

        # raise an error if the band is not inside the dataset only if
        # requested from the function call
        if exc is True and band is None:
            msg = ('Band has to be a positive integer, -1, or a band '
                   'interpretation found in the source.')
            raise TileSourceError(msg)

        return band

    def _getRegionBounds(
            self, metadata: JSONDict, left: Optional[float] = None,
            top: Optional[float] = None, right: Optional[float] = None,
            bottom: Optional[float] = None, width: Optional[float] = None,
            height: Optional[float] = None, units: Optional[str] = None,
            desiredMagnification: Optional[Dict[str, Optional[float]]] = None,
            cropToImage: bool = True, **kwargs) -> Tuple[float, float, float, float]:
        """
        Given a set of arguments that can include left, right, top, bottom,
        width, height, and units, generate actual pixel values for left, top,
        right, and bottom.  If units is `'projection'`, use the source's
        projection.  If units starts with `'proj4:'` or `'epsg:'` or a
        custom units value, use that projection.  Otherwise, just use the super
        function.

        :param metadata: the metadata associated with this source.
        :param left: the left edge (inclusive) of the region to process.
        :param top: the top edge (inclusive) of the region to process.
        :param right: the right edge (exclusive) of the region to process.
        :param bottom: the bottom edge (exclusive) of the region to process.
        :param width: the width of the region to process.  Ignored if both
            left and right are specified.
        :param height: the height of the region to process.  Ignores if both
            top and bottom are specified.
        :param units: either 'projection', a string starting with 'proj4:',
            'epsg:' or a enumerated value like 'wgs84', or one of the super's
            values.
        :param kwargs: optional parameters.  See above.
        :returns: left, top, right, bottom bounds in pixels.
        """
        units = TileInputUnits.get(units.lower() if units else units, units)
        # If a proj4 projection is specified, convert the left, right, top, and
        # bottom to the current projection or to pixel space if no projection
        # is used.
        if (units and (units.lower().startswith('proj4:') or
                       units.lower().startswith('epsg:') or
                       units.lower().startswith('+proj='))):
            left, top, right, bottom, units = self._convertProjectionUnits(
                left, top, right, bottom, width, height, units, **kwargs)

        if units == 'projection' and self.projection:
            bounds = self.getBounds(self.projection)
            # Fill in missing values
            if left is None:
                left = bounds['xmin'] if right is None or width is None else right - width
            if right is None:
                right = bounds['xmax'] if width is None else left + width
            if top is None:
                top = bounds['ymax'] if bottom is None or width is None else bottom - width
            if bottom is None:
                bottom = bounds['ymin'] if width is None else cast(float, top) + cast(float, height)
            if not kwargs.get('unitsWH') or kwargs.get('unitsWH') == units:
                width = height = None
            # Convert to [-0.5, 0.5], [-0.5, 0.5] coordinate range
            left = (left - self.projectionOrigin[0]) / self.unitsAcrossLevel0
            right = (right - self.projectionOrigin[0]) / self.unitsAcrossLevel0
            top = (top - self.projectionOrigin[1]) / self.unitsAcrossLevel0
            bottom = (bottom - self.projectionOrigin[1]) / self.unitsAcrossLevel0
            # Convert to world=wide 'base pixels' and crop to the world
            xScale = 2 ** (self.levels - 1) * self.tileWidth
            yScale = 2 ** (self.levels - 1) * self.tileHeight
            left = max(0, min(xScale, (0.5 + left) * xScale))
            right = max(0, min(xScale, (0.5 + right) * xScale))
            top = max(0, min(yScale, (0.5 - top) * yScale))
            bottom = max(0, min(yScale, (0.5 - bottom) * yScale))
            # Ensure correct ordering
            left, right = min(cast(float, left), cast(float, right)), max(left, cast(float, right))
            top, bottom = min(cast(float, top), cast(float, bottom)), max(top, cast(float, bottom))
            units = 'base_pixels'
        return super()._getRegionBounds(
            metadata, left, top, right, bottom, width, height, units,
            desiredMagnification, cropToImage, **kwargs)

    @methodcache()
    def getThumbnail(
            self, width: Optional[Union[str, int]] = None,
            height: Optional[Union[str, int]] = None, **kwargs) -> Tuple[
                Union[np.ndarray, PIL.Image.Image, ImageBytes, bytes, pathlib.Path], str]:
        """
        Get a basic thumbnail from the current tile source.  Aspect ratio is
        preserved.  If neither width nor height is given, a default value is
        used.  If both are given, the thumbnail will be no larger than either
        size.  A thumbnail has the same options as a region except that it
        always includes the entire image if there is no projection and has a
        default size of 256 x 256.

        :param width: maximum width in pixels.
        :param height: maximum height in pixels.
        :param kwargs: optional arguments.  Some options are encoding,
            jpegQuality, jpegSubsampling, and tiffCompression.
        :returns: thumbData, thumbMime: the image data and the mime type.
        """
        if self.projection:
            if ((width is not None and float(width) < 2) or
                    (height is not None and float(height) < 2)):
                msg = 'Invalid width or height.  Minimum value is 2.'
                raise ValueError(msg)
            if width is None and height is None:
                width = height = 256
            params = dict(kwargs)
            params['output'] = {'maxWidth': width, 'maxHeight': height}
            params['region'] = {'units': 'projection'}
            return self.getRegion(**params)
        return super().getThumbnail(width, height, **kwargs)
