import functools
import io
import json
import math
import os
import pathlib
import tempfile
import threading
import time
import types
import uuid
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union, cast

import numpy as np
import numpy.typing as npt
import PIL
import PIL.Image
import PIL.ImageCms
import PIL.ImageColor
import PIL.ImageDraw

from .. import config, exceptions
from ..cache_util import getTileCache, methodcache, strhash
from ..constants import (TILE_FORMAT_IMAGE, TILE_FORMAT_NUMPY, TILE_FORMAT_PIL,
                         SourcePriority, TileInputUnits, TileOutputMimeTypes,
                         TileOutputPILFormat)
from . import utilities
from .jupyter import IPyLeafletMixin
from .tiledict import LazyTileDict
from .tileiterator import TileIterator
from .utilities import (ImageBytes, JSONDict, _imageToNumpy,  # noqa: F401
                        _imageToPIL, dictToEtree, etreeToDict,
                        getPaletteColors, histogramThreshold, nearPowerOfTwo)


class TileSource(IPyLeafletMixin):
    # Name of the tile source
    name = None

    # A dictionary of known file extensions and the ``SourcePriority`` given
    # to each.  It must contain a None key with a priority for the tile source
    # when the extension does not match.
    extensions: Dict[Optional[str], SourcePriority] = {
        None: SourcePriority.FALLBACK,
    }

    # A dictionary of common mime-types handled by the source and the
    # ``SourcePriority`` given to each.  This are used in place of or in
    # additional to extensions.
    mimeTypes: Dict[Optional[str], SourcePriority] = {
        None: SourcePriority.FALLBACK,
    }

    # A dictionary with regex strings as the keys and the ``SourcePriority``
    # given to names that match that expression.  This is used in addition to
    # extensions and mimeTypes, with the highest priority match taken.
    nameMatches: Dict[str, SourcePriority] = {
    }

    # If a source supports creating new tiled images, specify its basic
    # priority based on expected feature set
    newPriority: Optional[SourcePriority] = None

    # When getting tiles for otherwise empty levels (missing powers of two), we
    # composite the tile from higher resolution levels.  This can use excessive
    # memory if there are too many missing levels.  For instance, if there are
    # six missing levels and the tile size is 1024 square RGBA, then 16 Gb are
    # needed for the composited tile at a minimum.  By setting
    # _maxSkippedLevels, such large gaps are composited in stages.
    _maxSkippedLevels = 3

    _initValues: Tuple[Tuple[Any, ...], Dict[str, Any]]
    _iccprofilesObjects: List[Any]

    def __init__(self, encoding: str = 'JPEG', jpegQuality: int = 95,
                 jpegSubsampling: int = 0, tiffCompression: str = 'raw',
                 edge: Union[bool, str] = False,
                 style: Optional[Union[str, Dict[str, int]]] = None,
                 noCache: Optional[bool] = None,
                 *args, **kwargs) -> None:
        """
        Initialize the tile class.

        :param jpegQuality: when serving jpegs, use this quality.
        :param jpegSubsampling: when serving jpegs, use this subsampling (0 is
            full chroma, 1 is half, 2 is quarter).
        :param encoding: 'JPEG', 'PNG', 'TIFF', or 'TILED'.
        :param edge: False to leave edge tiles whole, True or 'crop' to crop
            edge tiles, otherwise, an #rrggbb color to fill edges.
        :param tiffCompression: the compression format to use when encoding a
            TIFF.
        :param style: if None, use the default style for the file.  Otherwise,
            this is a string with a json-encoded dictionary.  The style can
            contain the following keys:

                :band: if -1 or None, and if style is specified at all, the
                    greyscale value is used.  Otherwise, a 1-based numerical
                    index into the channels of the image or a string that
                    matches the interpretation of the band ('red', 'green',
                    'blue', 'gray', 'alpha').  Note that 'gray' on an RGB or
                    RGBA image will use the green band.
                :frame: if specified, override the frame value for this band.
                    When used as part of a bands list, this can be used to
                    composite multiple frames together.  It is most efficient
                    if at least one band either doesn't specify a frame
                    parameter or specifies the same frame value as the primary
                    query.
                :framedelta: if specified and frame is not specified, override
                    the frame value for this band by using the current frame
                    plus this value.
                :min: the value to map to the first palette value.  Defaults to
                    0.  'auto' to use 0 if the reported minimum and maximum of
                    the band are between [0, 255] or use the reported minimum
                    otherwise.  'min' or 'max' to always uses the reported
                    minimum or maximum.  'full' to always use 0.
                :max: the value to map to the last palette value.  Defaults to
                    255.  'auto' to use 0 if the reported minimum and maximum
                    of the band are between [0, 255] or use the reported
                    maximum otherwise.  'min' or 'max' to always uses the
                    reported minimum or maximum.  'full' to use the maximum
                    value of the base data type (either 1, 255, or 65535).
                :palette: a single color string, a palette name, or a list of
                    two or more color strings.  Color strings are of the form
                    #RRGGBB, #RRGGBBAA, #RGB, #RGBA, or any string parseable by
                    the PIL modules, or, if it is installed, by matplotlib.   A
                    single color string is the same as the list ['#000',
                    <color>].  Palette names are the name of a palettable
                    palette or, if available, a matplotlib palette.
                :nodata: the value to use for missing data.  null or unset to
                    not use a nodata value.
                :composite: either 'lighten' or 'multiply'.  Defaults to
                    'lighten' for all except the alpha band.
                :clamp: either True to clamp (also called clip or crop) values
                    outside of the [min, max] to the ends of the palette or
                    False to make outside values transparent.
                :dtype: convert the results to the specified numpy dtype.
                    Normally, if a style is applied, the results are
                    intermediately a float numpy array with a value range of
                    [0,255].  If this is 'uint16', it will be cast to that and
                    multiplied by 65535/255.  If 'float', it will be divided by
                    255.  If 'source', this uses the dtype of the source image.
                :axis: keep only the specified axis from the numpy intermediate
                    results.  This can be used to extract a single channel
                    after compositing.

            Alternately, the style object can contain a single key of 'bands',
            which has a value which is a list of style dictionaries as above,
            excepting that each must have a band that is not -1.  Bands are
            composited in the order listed.  This base object may also contain
            the 'dtype' and 'axis' values.
        :param noCache: if True, the style can be adjusted dynamically and the
            source is not elibible for caching.  If there is no intention to
            reuse the source at a later time, this can have performance
            benefits, such as when first cataloging images that can be read.
        """
        super().__init__(**kwargs)
        self.logger = config.getLogger()
        self.cache, self.cache_lock = getTileCache()

        self.tileWidth: int = 0
        self.tileHeight: int = 0
        self.levels: int = 0
        self.sizeX: int = 0
        self.sizeY: int = 0
        self._sourceLock = threading.RLock()
        self._dtype: Optional[Union[npt.DTypeLike, str]] = None
        self._bandCount: Optional[int] = None

        if encoding not in TileOutputMimeTypes:
            raise ValueError('Invalid encoding "%s"' % encoding)

        self.encoding = encoding
        self.jpegQuality = int(jpegQuality)
        self.jpegSubsampling = int(jpegSubsampling)
        self.tiffCompression = tiffCompression
        self.edge = edge
        self._setStyle(style)

    def __getstate__(self) -> None:
        """
        Allow pickling.

        We reconstruct our state via the creation caused by the inverse of
        reduce, so we don't report state here.
        """
        return None

    def __reduce__(self) -> Tuple[functools.partial, Tuple[str]]:
        """
        Allow pickling.

        Reduce can pass the args but not the kwargs, so use a partial class
        call to reconstruct kwargs.
        """
        import functools
        import pickle

        if not hasattr(self, '_initValues') or hasattr(self, '_unpickleable'):
            msg = 'Source cannot be pickled'
            raise pickle.PicklingError(msg)
        return functools.partial(type(self), **self._initValues[1]), self._initValues[0]

    def __repr__(self) -> str:
        return self.getState()

    def _repr_png_(self) -> bytes:
        return self.getThumbnail(encoding='PNG')[0]

    @property
    def geospatial(self) -> bool:
        return False

    def _setStyle(self, style: Any) -> None:
        """
        Check and set the specified style from a json string or a dictionary.

        :param style: The new style.
        """
        for key in {'_unlocked_classkey', '_classkeyLock'}:
            try:
                delattr(self, key)
            except Exception:
                pass
        if not hasattr(self, '_bandRanges'):
            self._bandRanges: Dict[Optional[int], Any] = {}
        self._jsonstyle = style
        if style is not None:
            if isinstance(style, dict):
                self._style: Optional[JSONDict] = JSONDict(style)
                self._jsonstyle = json.dumps(style, sort_keys=True, separators=(',', ':'))
            else:
                try:
                    self._style = None
                    style = json.loads(style)
                    if not isinstance(style, dict):
                        raise TypeError
                    self._style = JSONDict(style)
                except (TypeError, json.decoder.JSONDecodeError):
                    msg = 'Style is not a valid json object.'
                    raise exceptions.TileSourceError(msg)

    def getBounds(self, *args, **kwargs) -> Dict[str, Any]:
        return {
            'sizeX': self.sizeX,
            'sizeY': self.sizeY,
        }

    def getCenter(self, *args, **kwargs) -> Tuple[float, float]:
        """Returns (Y, X) center location."""
        if self.geospatial:
            bounds = self.getBounds(*args, **kwargs)
            return (
                (bounds['ymax'] - bounds['ymin']) / 2 + bounds['ymin'],
                (bounds['xmax'] - bounds['xmin']) / 2 + bounds['xmin'],
            )
        bounds = TileSource.getBounds(self, *args, **kwargs)
        return (bounds['sizeY'] / 2, bounds['sizeX'] / 2)

    @property
    def style(self) -> Optional[JSONDict]:
        return self._style

    @style.setter
    def style(self, value: Any) -> None:
        if value is None and not hasattr(self, '_unstyledStyle'):
            return
        if not getattr(self, '_noCache', False):
            msg = 'Cannot set the style of a cached source'
            raise exceptions.TileSourceError(msg)
        args, kwargs = self._initValues
        kwargs['style'] = value
        self._initValues = (args, kwargs.copy())
        oldval = getattr(self, '_jsonstyle', None)
        self._setStyle(value)
        if oldval == getattr(self, '_jsonstyle', None):
            return
        self._classkey = str(uuid.uuid4())
        if (kwargs.get('style') != getattr(self, '_unstyledStyle', None) and
                not hasattr(self, '_unstyledInstance')):
            subkwargs = kwargs.copy()
            subkwargs['style'] = getattr(self, '_unstyledStyle', None)
            self._unstyledInstance = self.__class__(*args, **subkwargs)

    @property
    def dtype(self) -> np.dtype:
        with self._sourceLock:
            if not self._dtype:
                self._dtype = 'check'
                sample, _ = cast(Tuple[np.ndarray, Any], getattr(
                    self, '_unstyledInstance', self).getRegion(
                        region=dict(left=0, top=0, width=1, height=1),
                        format=TILE_FORMAT_NUMPY))
                self._dtype = np.dtype(sample.dtype)
                self._bandCount = len(
                    getattr(getattr(self, '_unstyledInstance', self), '_bandInfo', []))
                if not self._bandCount:
                    self._bandCount = sample.shape[-1] if len(sample.shape) == 3 else 1
        return cast(np.dtype, self._dtype)

    @property
    def bandCount(self) -> Optional[int]:
        if not self._bandCount:
            if not self._dtype or (isinstance(self._dtype, str) and self._dtype == 'check'):
                return None
        return self._bandCount

    @staticmethod
    def getLRUHash(*args, **kwargs) -> str:
        """
        Return a string hash used as a key in the recently-used cache for tile
        sources.

        :returns: a string hash value.
        """
        return strhash(
            kwargs.get('encoding', 'JPEG'), kwargs.get('jpegQuality', 95),
            kwargs.get('jpegSubsampling', 0), kwargs.get('tiffCompression', 'raw'),
            kwargs.get('edge', False),
            '__STYLESTART__', kwargs.get('style', None), '__STYLEEND__')

    def getState(self) -> str:
        """
        Return a string reflecting the state of the tile source.  This is used
        as part of a cache key when hashing function return values.

        :returns: a string hash value of the source state.
        """
        if hasattr(self, '_classkey'):
            return self._classkey
        return '%s,%s,%s,%s,%s,__STYLESTART__,%s,__STYLEEND__' % (
            self.encoding,
            self.jpegQuality,
            self.jpegSubsampling,
            self.tiffCompression,
            self.edge,
            self._jsonstyle)

    def wrapKey(self, *args, **kwargs) -> str:
        """
        Return a key for a tile source and function parameters that can be used
        as a unique cache key.

        :param args: arguments to add to the hash.
        :param kwaths: arguments to add to the hash.
        :returns: a cache key.
        """
        return strhash(self.getState()) + strhash(*args, **kwargs)

    def _scaleFromUnits(
            self, metadata: JSONDict, units: Optional[str],
            desiredMagnification: Optional[Dict[str, Any]],
            **kwargs) -> Tuple[float, float]:
        """
        Get scaling parameters based on the source metadata and specified
        units.

        :param metadata: the metadata associated with this source.
        :param units: the units used for the scale.
        :param desiredMagnification: the output from getMagnificationForLevel
            for the desired magnification used to convert mag_pixels and mm.
        :param kwargs: optional parameters.
        :returns: (scaleX, scaleY) scaling parameters in the horizontal and
            vertical directions.
        """
        scaleX = scaleY = 1.0
        if units == 'fraction':
            scaleX = metadata['sizeX']
            scaleY = metadata['sizeY']
        elif units == 'mag_pixels':
            if not (desiredMagnification or {}).get('scale'):
                msg = 'No magnification to use for units'
                raise ValueError(msg)
            scaleX = scaleY = cast(Dict[str, float], desiredMagnification)['scale']
        elif units == 'mm':
            if (not (desiredMagnification or {}).get('scale') or
                    not (desiredMagnification or {}).get('mm_x') or
                    not (desiredMagnification or {}).get('mm_y')):
                desiredMagnification = self.getNativeMagnification().copy()
                cast(Dict[str, float], desiredMagnification)['scale'] = 1.0
            if (not desiredMagnification or
                    not desiredMagnification.get('scale') or
                    not desiredMagnification.get('mm_x') or
                    not desiredMagnification.get('mm_y')):
                msg = 'No mm_x or mm_y to use for units'
                raise ValueError(msg)
            scaleX = (desiredMagnification['scale'] /
                      desiredMagnification['mm_x'])
            scaleY = (desiredMagnification['scale'] /
                      desiredMagnification['mm_y'])
        elif units in ('base_pixels', None):
            pass
        else:
            raise ValueError('Invalid units %r' % units)
        return scaleX, scaleY

    def _getRegionBounds(
            self,
            metadata: JSONDict,
            left: Optional[float] = None,
            top: Optional[float] = None,
            right: Optional[float] = None,
            bottom: Optional[float] = None,
            width: Optional[float] = None,
            height: Optional[float] = None,
            units: Optional[str] = None,
            desiredMagnification: Optional[Dict[str, Optional[float]]] = None,
            cropToImage: bool = True, **kwargs) -> Tuple[float, float, float, float]:
        """
        Given a set of arguments that can include left, right, top, bottom,
        width, height, and units, generate actual pixel values for left, top,
        right, and bottom.  If left, top, right, or bottom are negative they
        are interpreted as an offset from the right or bottom edge of the
        image.

        :param metadata: the metadata associated with this source.
        :param left: the left edge (inclusive) of the region to process.
        :param top: the top edge (inclusive) of the region to process.
        :param right: the right edge (exclusive) of the region to process.
        :param bottom: the bottom edge (exclusive) of the region to process.
        :param width: the width of the region to process.  Ignored if both
            left and right are specified.
        :param height: the height of the region to process.  Ignores if both
            top and bottom are specified.
        :param units: either 'base_pixels' (default), 'pixels', 'mm', or
            'fraction'.  base_pixels are in maximum resolution pixels.
            pixels is in the specified magnification pixels.  mm is in the
            specified magnification scale.  fraction is a scale of 0 to 1.
            pixels and mm are only available if the magnification and mm
            per pixel are defined for the image.
        :param desiredMagnification: the output from getMagnificationForLevel
            for the desired magnification used to convert mag_pixels and mm.
        :param cropToImage: if True, don't return region coordinates outside of
            the image.
        :param kwargs: optional parameters.  These are passed to
            _scaleFromUnits and may include unitsWH.
        :returns: left, top, right, bottom bounds in pixels.
        """
        if units not in TileInputUnits:
            raise ValueError('Invalid units %r' % units)
        # Convert units to max-resolution pixels
        units = TileInputUnits[units]
        scaleX, scaleY = self._scaleFromUnits(metadata, units, desiredMagnification, **kwargs)
        if kwargs.get('unitsWH'):
            if kwargs['unitsWH'] not in TileInputUnits:
                raise ValueError('Invalid units %r' % kwargs['unitsWH'])
            scaleW, scaleH = self._scaleFromUnits(
                metadata, TileInputUnits[kwargs['unitsWH']], desiredMagnification, **kwargs)
            # if unitsWH is specified, prefer width and height to right and
            # bottom
            if left is not None and right is not None and width is not None:
                right = None
            if top is not None and bottom is not None and height is not None:
                bottom = None
        else:
            scaleW, scaleH = scaleX, scaleY
        aggregion = {'left': left, 'top': top, 'right': right,
                     'bottom': bottom, 'width': width, 'height': height}
        region: Dict[str, float] = {key: cast(float, aggregion[key])
                                    for key in aggregion if aggregion[key] is not None}
        for key, scale in (
                ('left', scaleX), ('right', scaleX), ('width', scaleW),
                ('top', scaleY), ('bottom', scaleY), ('height', scaleH)):
            if key in region and scale and scale != 1:
                region[key] = region[key] * scale
        # convert negative references to right or bottom offsets
        for key in ('left', 'right', 'top', 'bottom'):
            if key in region and region[key] < 0:
                region[key] += metadata[
                    'sizeX' if key in ('left', 'right') else 'sizeY']
        # Calculate the region we need to fetch
        left = region.get(
            'left',
            (region['right'] - region['width'])
            if 'right' in region and 'width' in region else 0)
        right = region.get(
            'right',
            (left + region['width'])
            if 'width' in region else metadata['sizeX'])
        top = region.get(
            'top', region['bottom'] - region['height']
            if 'bottom' in region and 'height' in region else 0)
        bottom = region.get(
            'bottom', top + region['height']
            if 'height' in region else metadata['sizeY'])
        if cropToImage:
            # Crop the bounds to integer pixels within the actual source data
            left = min(metadata['sizeX'], max(0, int(round(left))))
            right = min(metadata['sizeX'], max(
                cast(int, left), int(round(cast(float, right)))))
            top = min(metadata['sizeY'], max(0, int(round(top))))
            bottom = min(metadata['sizeY'], max(
                cast(int, top), int(round(cast(float, bottom)))))

        return cast(int, left), cast(int, top), cast(int, right), cast(int, bottom)

    def _pilFormatMatches(self, image: Any, match: Union[bool, str] = True, **kwargs) -> bool:
        """
        Determine if the specified PIL image matches the format of the tile
        source with the specified arguments.

        :param image: the PIL image to check.
        :param match: if 'any', all image encodings are considered matching,
            if 'encoding', then a matching encoding matches regardless of
            quality options, otherwise, only match if the encoding and quality
            options match.
        :param kwargs: additional parameters to use in determining format.
        """
        encoding = TileOutputPILFormat.get(self.encoding, self.encoding)
        if match == 'any' and encoding in ('PNG', 'JPEG'):
            return True
        if image.format != encoding:
            return False
        if encoding == 'PNG':
            return True
        if encoding == 'JPEG':
            if match == 'encoding':
                return True
            originalQuality = None
            try:
                if image.format == 'JPEG' and hasattr(image, 'quantization'):
                    if image.quantization[0][58] <= 100:
                        originalQuality = int(100 - image.quantization[0][58] / 2)
                    else:
                        originalQuality = int(5000.0 / 2.5 / image.quantization[0][15])
            except Exception:
                return False
            return bool(originalQuality and abs(originalQuality - self.jpegQuality) <= 1)
        # We fail for the TIFF file format; it is general enough that ensuring
        # compatibility could be an issue.
        return False

    @methodcache()
    def histogram(  # noqa
            self, dtype: npt.DTypeLike = None, onlyMinMax: bool = False,
            bins: int = 256, density: bool = False, format: Any = None,
            *args, **kwargs) -> Dict[str, Union[np.ndarray, List[Dict[str, Any]]]]:
        """
        Get a histogram for a region.

        :param dtype: if specified, the tiles must be this numpy.dtype.
        :param onlyMinMax: if True, only return the minimum and maximum value
            of the region.
        :param bins: the number of bins in the histogram.  This is passed to
            numpy.histogram, but needs to produce the same set of edges for
            each tile.
        :param density: if True, scale the results based on the number of
            samples.
        :param format: ignored.  Used to override the format for the
            tileIterator.
        :param range: if None, use the computed min and (max + 1).  Otherwise,
            this is the range passed to numpy.histogram.  Note this is only
            accessible via kwargs as it otherwise overloads the range function.
            If 'round', use the computed values, but the number of bins may be
            reduced or the bin_edges rounded to integer values for
            integer-based source data.
        :param args: parameters to pass to the tileIterator.
        :param kwargs: parameters to pass to the tileIterator.
        :returns: if onlyMinMax is true, this is a dictionary with keys min and
            max, each of which is a numpy array with the minimum and maximum of
            all of the bands.  If onlyMinMax is False, this is a dictionary
            with a single key 'histogram' that contains a list of histograms
            per band.  Each entry is a dictionary with min, max, range, hist,
            bins, and bin_edges.  range is [min, (max + 1)].  hist is the
            counts (normalized if density is True) for each bin.  bins is the
            number of bins used.  bin_edges is an array one longer than the
            hist array that contains the boundaries between bins.
        """
        lastlog = time.time()
        kwargs = kwargs.copy()
        histRange = kwargs.pop('range', None)
        results: Optional[Dict[str, Any]] = None
        for itile in self.tileIterator(format=TILE_FORMAT_NUMPY, **kwargs):
            if time.time() - lastlog > 10:
                self.logger.info(
                    'Calculating histogram min/max for frame %d, tile %d/%d',
                    kwargs.get('frame', 0),
                    itile['tile_position']['position'], itile['iterator_range']['position'])
                lastlog = time.time()
            tile = itile['tile']
            if dtype is not None and tile.dtype != dtype:
                if tile.dtype == np.uint8 and dtype == np.uint16:
                    tile = np.array(tile, dtype=np.uint16) * 257
                else:
                    continue
            tilemin = np.array([
                np.amin(tile[:, :, idx]) for idx in range(tile.shape[2])], tile.dtype)
            tilemax = np.array([
                np.amax(tile[:, :, idx]) for idx in range(tile.shape[2])], tile.dtype)
            tilesum: np.ndarray = np.array([
                np.sum(tile[:, :, idx]) for idx in range(tile.shape[2])], float)
            tilesum2: np.ndarray = np.array([
                np.sum(np.array(tile[:, :, idx], float) ** 2)
                for idx in range(tile.shape[2])], float)
            tilecount = tile.shape[0] * tile.shape[1]
            if results is None:
                results = {
                    'min': tilemin,
                    'max': tilemax,
                    'sum': tilesum,
                    'sum2': tilesum2,
                    'count': tilecount,
                }
            else:
                results['min'] = np.minimum(results['min'], tilemin[:len(results['min'])])
                results['max'] = np.maximum(results['max'], tilemax[:len(results['min'])])
                results['sum'] += tilesum[:len(results['min'])]
                results['sum2'] += tilesum2[:len(results['min'])]
                results['count'] += tilecount
        if results is None:
            return {}
        results['mean'] = results['sum'] / results['count']
        results['stdev'] = np.maximum(
            results['sum2'] / results['count'] - results['mean'] ** 2,
            [0] * results['sum2'].shape[0]) ** 0.5
        results.pop('sum', None)
        results.pop('sum2', None)
        results.pop('count', None)
        if results is None or onlyMinMax:
            return results
        results['histogram'] = [{
            'min': float(results['min'][idx]),
            'max': float(results['max'][idx]),
            'mean': float(results['mean'][idx]),
            'stdev': float(results['stdev'][idx]),
            'range': ((float(results['min'][idx]), float(results['max'][idx]) + 1)
                      if histRange is None or histRange == 'round' else histRange),
            'hist': None,
            'bin_edges': None,
            'bins': bins,
            'density': bool(density),
        } for idx in range(len(results['min']))]
        if histRange == 'round' and np.issubdtype(dtype or self.dtype, np.integer):
            for record in results['histogram']:
                if (record['range'][1] - record['range'][0]) < bins * 10:
                    step = int(math.ceil((record['range'][1] - record['range'][0]) / bins))
                    rbins = int(math.ceil((record['range'][1] - record['range'][0]) / step))
                    record['range'] = (record['range'][0], record['range'][0] + step * rbins)
                    record['bins'] = rbins
        for tile in self.tileIterator(format=TILE_FORMAT_NUMPY, **kwargs):
            if time.time() - lastlog > 10:
                self.logger.info(
                    'Calculating histogram %d/%d',
                    tile['tile_position']['position'], tile['iterator_range']['position'])
                lastlog = time.time()
            tile = tile['tile']
            if dtype is not None and tile.dtype != dtype:
                if tile.dtype == np.uint8 and dtype == np.uint16:
                    tile = np.array(tile, dtype=np.uint16) * 257
                else:
                    continue
            for idx in range(min(len(results['min']), tile.shape[-1])):
                entry = results['histogram'][idx]
                hist, bin_edges = np.histogram(
                    tile[:, :, idx], entry['bins'], entry['range'], density=False)
                if entry['hist'] is None:
                    entry['hist'] = hist
                    entry['bin_edges'] = bin_edges
                else:
                    entry['hist'] += hist
        for idx in range(len(results['min'])):
            entry = results['histogram'][idx]
            if entry['hist'] is not None:
                entry['samples'] = np.sum(entry['hist'])
                if density:
                    entry['hist'] = entry['hist'].astype(float) / entry['samples']
        return results

    def _scanForMinMax(
            self, dtype: npt.DTypeLike, frame: Optional[int] = None,
            analysisSize: int = 1024, onlyMinMax: bool = True, **kwargs) -> None:
        """
        Scan the image at a lower resolution to find the minimum and maximum
        values.  The results are stored in an internal dictionary.

        :param dtype: the numpy dtype.  Used for guessing the range.
        :param frame: the frame to use for auto-ranging.
        :param analysisSize: the size of the image to use for analysis.
        :param onlyMinMax: if True, only find the min and max.  If False, get
            the entire histogram.
        """
        self._bandRanges[frame] = getattr(self, '_unstyledInstance', self).histogram(
            dtype=dtype,
            onlyMinMax=onlyMinMax,
            output={'maxWidth': min(self.sizeX, analysisSize),
                    'maxHeight': min(self.sizeY, analysisSize)},
            resample=False,
            frame=frame, **kwargs)
        if self._bandRanges[frame]:
            self.logger.info('Style range is %r', {
                k: v for k, v in self._bandRanges[frame].items() if k in {
                    'min', 'max', 'mean', 'stdev'}})

    def _validateMinMaxValue(
        self, value: Union[str, float], frame: int, dtype: npt.DTypeLike,
    ) -> Tuple[Union[str, int, float], Union[float, int]]:
        """
        Validate the min/max setting and return a specific string or float
        value and with any threshold.

        :param value: the specified value, 'auto', 'min', or 'max'.  'auto'
            uses the parameter specified in 'minmax' or 0 or 255 if the
            band's minimum is in the range [0, 254] and maximum is in the range
            [2, 255].  'min:<value>' and 'max:<value>' use the histogram to
            threshold the image based on the value.  'auto:<value>' applies a
            histogram threshold if the parameter specified in minmax is used.
        :param dtype: the numpy dtype.  Used for guessing the range.
        :param frame: the frame to use for auto-ranging.
        :returns: the validated value and a threshold from [0-1].
        """
        threshold: float = 0
        if value not in {'min', 'max', 'auto', 'full'}:
            try:
                if ':' in str(value) and cast(str, value).split(':', 1)[0] in {
                        'min', 'max', 'auto'}:
                    threshold = float(cast(str, value).split(':', 1)[1])
                    value = cast(str, value).split(':', 1)[0]
                else:
                    value = float(value)
            except ValueError:
                self.logger.warning('Style min/max value of %r is not valid; using "auto"', value)
                value = 'auto'
        if value in {'min', 'max', 'auto'} and (
                frame not in self._bandRanges or (
                    threshold and 'histogram' not in self._bandRanges[frame])):
            self._scanForMinMax(dtype, frame, onlyMinMax=not threshold)
        return value, threshold

    def _getMinMax(  # noqa
            self, minmax: str, value: Union[str, float], dtype: np.dtype,
            bandidx: Optional[int] = None, frame: Optional[int] = None) -> float:
        """
        Get an appropriate minimum or maximum for a band.

        :param minmax: either 'min' or 'max'.
        :param value: the specified value, 'auto', 'min', or 'max'.  'auto'
            uses the parameter specified in 'minmax' or 0 or 255 if the
            band's minimum is in the range [0, 254] and maximum is in the range
            [2, 255].  'min:<value>' and 'max:<value>' use the histogram to
            threshold the image based on the value.  'auto:<value>' applies a
            histogram threshold if the parameter specified in minmax is used.
        :param dtype: the numpy dtype.  Used for guessing the range.
        :param bandidx: the index of the channel that could be used for
            determining the min or max.
        :param frame: the frame to use for auto-ranging.
        """
        frame = frame or 0
        value, threshold = self._validateMinMaxValue(value, frame, dtype)
        if value == 'full':
            value = 0
            if minmax != 'min':
                if dtype == np.uint16:
                    value = 65535
                elif dtype.kind == 'f':
                    value = 1
                else:
                    value = 255
        if value == 'auto':
            if (self._bandRanges.get(frame) and
                    np.all(self._bandRanges[frame]['min'] >= 0) and
                    np.all(self._bandRanges[frame]['min'] <= 254) and
                    np.all(self._bandRanges[frame]['max'] >= 2) and
                    np.all(self._bandRanges[frame]['max'] <= 255)):
                value = 0 if minmax == 'min' else 255
            else:
                value = minmax
        if value == 'min':
            if bandidx is not None and self._bandRanges.get(frame):
                if threshold:
                    value = histogramThreshold(
                        self._bandRanges[frame]['histogram'][bandidx], threshold)
                else:
                    value = self._bandRanges[frame]['min'][bandidx]
            else:
                value = 0
        elif value == 'max':
            if bandidx is not None and self._bandRanges.get(frame):
                if threshold:
                    value = histogramThreshold(
                        self._bandRanges[frame]['histogram'][bandidx], threshold, True)
                else:
                    value = self._bandRanges[frame]['max'][bandidx]
            elif dtype == np.uint16:
                value = 65535
            elif dtype.kind == 'f':
                value = 1
            else:
                value = 255
        return float(value)

    def _applyStyleFunction(
            self, image: np.ndarray, sc: types.SimpleNamespace, stage: str,
            function: Optional[Dict[str, Any]] = None) -> np.ndarray:
        """
        Check if a style ahs a style function for the current stage.  If so,
        apply it.

        :param image: the numpy image to adjust.  This varies by stage:
            For pre, this is the source image.
            For preband, this is the band image (often the source image).
            For band, this is the scaled band image before palette has been
                applied.
            For postband, this is the output image at the current time.
            For main, this is the output image before adjusting to the target
                style.
            For post, this is the final output image.
        :param sc: the style context.
        :param stage: one of the stages: pre, preband, band, postband, main,
            post.
        :param function: if None, this is taken from the sc.style object using
            the appropriate band index.  Otherwise, this is a style: either a
            list of style objects, or a style object with name (the
            module.function_name), stage (either a stage or a list of stages
            that this function applies to), context (falsy to not pass the
            style context to the function, True to pass it as the parameter
            'context', or a string to pass it as a parameter of that name),
            parameters (a dictionary of parameters to pass to the function).
            If function is a string, it is shorthand for {'name': <function>}.
        :returns: the modified numpy image.
        """
        import importlib

        if function is None:
            function = (
                sc.style.get('function') if not hasattr(sc, 'styleIndex') else
                sc.style['bands'][sc.styleIndex].get('function'))
            if function is None:
                return image
        if isinstance(function, (list, tuple)):
            for func in cast(Union[List, Tuple], function):
                image = self._applyStyleFunction(image, sc, stage, func)
            return image
        if isinstance(function, str):
            function = {'name': function}
        useOnStages = (
            [function['stage']] if isinstance(function.get('stage'), str)
            else function.get('stage', ['main', 'band']))
        if stage not in useOnStages:
            return image
        sc.stage = stage
        try:
            module_name, func_name = function['name'].rsplit('.', 1)
            module = importlib.import_module(module_name)
            func = getattr(module, func_name)
        except Exception as exc:
            self._styleFunctionWarnings = getattr(self, '_styleFunctionWarnings', {})
            if function['name'] not in self._styleFunctionWarnings:
                self._styleFunctionWarnings[function['name']] = exc
                self.logger.exception('Failed to import style function %s', function['name'])
            return image
        kwargs = function.get('parameters', {}).copy()
        if function.get('context'):
            kwargs['context' if function['context'] is True else function['context']] = sc
        try:
            return func(image, **kwargs)
        except Exception as exc:
            self._styleFunctionWarnings = getattr(self, '_styleFunctionWarnings', {})
            if function['name'] not in self._styleFunctionWarnings:
                self._styleFunctionWarnings[function['name']] = exc
                self.logger.exception('Failed to execute style function %s', function['name'])
            return image

    def getICCProfiles(
            self, idx: Optional[int] = None, onlyInfo: bool = False) -> Optional[
                Union[PIL.ImageCms.ImageCmsProfile, List[Optional[PIL.ImageCms.ImageCmsProfile]]]]:
        """
        Get a list of all ICC profiles that are available for the source, or
        get a specific profile.

        :param idx: a 0-based index into the profiles to get one profile, or
            None to get a list of all profiles.
        :param onlyInfo: if idx is None and this is true, just return the
            profile information.
        :returns: either one or a list of PIL.ImageCms.CmsProfile objects, or
            None if no profiles are available.  If a list, entries in the list
            may be None.
        """
        if not hasattr(self, '_iccprofiles'):
            return None
        results = []
        for pidx, prof in enumerate(self._iccprofiles):
            if idx is not None and pidx != idx:
                continue
            if hasattr(self, '_iccprofilesObjects') and self._iccprofilesObjects[pidx] is not None:
                prof = self._iccprofilesObjects[pidx]['profile']
            elif not isinstance(prof, PIL.ImageCms.ImageCmsProfile):
                try:
                    prof = PIL.ImageCms.getOpenProfile(io.BytesIO(prof))
                except PIL.ImageCms.PyCMSError:
                    continue
            if idx == pidx:
                return prof
            results.append(prof)
        if onlyInfo:
            results = [
                PIL.ImageCms.getProfileInfo(prof).strip() or 'present'
                if prof else None for prof in results]
        return results

    def _applyICCProfile(self, sc: types.SimpleNamespace, frame: int) -> np.ndarray:
        """
        Apply an ICC profile to an image.

        :param sc: the style context.
        :param frame: the frame to use for auto ranging.
        :returns: an image with the icc profile, if any, applied.
        """
        if not hasattr(self, '_iccprofiles'):
            return sc.image
        profileIdx = frame if frame and len(self._iccprofiles) >= frame + 1 else 0
        sc.iccimage = sc.image
        sc.iccapplied = False
        if not self._iccprofiles[profileIdx]:
            return sc.image
        if not hasattr(self, '_iccprofilesObjects'):
            self._iccprofilesObjects = [None] * len(self._iccprofiles)
        image = _imageToPIL(sc.image)
        mode = image.mode
        if hasattr(PIL.ImageCms, 'Intent'):  # PIL >= 9
            intent = getattr(PIL.ImageCms.Intent, str(sc.style.get('icc')).upper(),
                             PIL.ImageCms.Intent.PERCEPTUAL)
        else:
            intent = getattr(PIL.ImageCms, 'INTENT_' + str(sc.style.get('icc')).upper(),
                             PIL.ImageCms.INTENT_PERCEPTUAL)  # type: ignore[attr-defined]
        if not hasattr(self, '_iccsrgbprofile'):
            try:
                self._iccsrgbprofile = PIL.ImageCms.createProfile('sRGB')
            except ImportError:
                self._iccsrgbprofile = None
                self.logger.warning(
                    'Failed to import PIL.ImageCms.  Cannot perform ICC '
                    'color adjustments.  Does your platform support '
                    'PIL.ImageCms?')
        if self._iccsrgbprofile is None:
            return sc.image
        try:
            key = (mode, intent)
            if self._iccprofilesObjects[profileIdx] is None:
                self._iccprofilesObjects[profileIdx] = {
                    'profile': self.getICCProfiles(profileIdx),
                }
            if key not in self._iccprofilesObjects[profileIdx]:
                self._iccprofilesObjects[profileIdx][key] = \
                    PIL.ImageCms.buildTransformFromOpenProfiles(
                        self._iccprofilesObjects[profileIdx]['profile'],
                        self._iccsrgbprofile, mode, mode,
                        renderingIntent=intent)
                self.logger.debug(
                    'Created an ICC profile transform for mode %s, intent %s', mode, intent)
            transform = self._iccprofilesObjects[profileIdx][key]

            PIL.ImageCms.applyTransform(image, transform, inPlace=True)
            sc.iccimage = _imageToNumpy(image)[0]
            sc.iccapplied = True
        except Exception as exc:
            if not hasattr(self, '_iccerror'):
                self._iccerror = exc
                self.logger.exception('Failed to apply ICC profile')
        return sc.iccimage

    def _applyStyle(  # noqa
            self, image: np.ndarray, style: Optional[JSONDict], x: int, y: int,
            z: int, frame: Optional[int] = None) -> np.ndarray:
        """
        Apply a style to a numpy image.

        :param image: the image to modify.
        :param style: a style object.
        :param x: the x tile position; used for multi-frame styles.
        :param y: the y tile position; used for multi-frame styles.
        :param z: the z tile position; used for multi-frame styles.
        :param frame: the frame to use for auto ranging.
        :returns: a styled image.
        """
        sc = types.SimpleNamespace(
            image=image, originalStyle=style, x=x, y=y, z=z, frame=frame,
            mainImage=image, mainFrame=frame, dtype=None, axis=None)
        if not style or ('icc' in style and len(style) == 1):
            sc.style = {'icc': (style or cast(JSONDict, {})).get(
                'icc', config.getConfig('icc_correction', True)), 'bands': []}
        else:
            sc.style = style if 'bands' in style else {'bands': [style]}
            sc.dtype = style.get('dtype')
            sc.axis = style.get('axis')
        if hasattr(self, '_iccprofiles') and sc.style.get(
                'icc', config.getConfig('icc_correction', True)):
            image = self._applyICCProfile(sc, frame or 0)
        if not style or ('icc' in style and len(style) == 1):
            sc.output = image
        else:
            newwidth = 4
            if (len(sc.style['bands']) == 1 and sc.style['bands'][0].get('band') != 'alpha' and
                    image.shape[-1] == 1):
                palette = getPaletteColors(sc.style['bands'][0].get('palette', ['#000', '#FFF']))
                if np.array_equal(palette, getPaletteColors('#fff')):
                    newwidth = 1
            sc.output = np.zeros(
                (image.shape[0], image.shape[1], newwidth),
                np.float32 if image.dtype != np.float64 else image.dtype)
        image = self._applyStyleFunction(image, sc, 'pre')
        for eidx, entry in enumerate(sc.style['bands']):
            sc.styleIndex = eidx
            sc.dtype = sc.dtype if sc.dtype is not None else entry.get('dtype')
            if sc.dtype == 'source':
                if sc.mainImage.dtype == np.uint16:
                    sc.dtype = 'uint16'
                elif sc.mainImage.dtype.kind == 'f':
                    sc.dtype = 'float'
            sc.axis = sc.axis if sc.axis is not None else entry.get('axis')
            sc.bandidx = 0 if image.shape[2] <= 2 else 1  # type: ignore[misc]
            sc.band = None
            if ((entry.get('frame') is None and not entry.get('framedelta')) or
                    entry.get('frame') == sc.mainFrame):
                image = sc.mainImage
                frame = sc.mainFrame
            else:
                frame = entry['frame'] if entry.get('frame') is not None else (
                    sc.mainFrame + entry['framedelta'])
                image = getattr(self, '_unstyledInstance', self).getTile(
                    x, y, z, frame=frame, numpyAllowed=True)
                image = image[:sc.mainImage.shape[0],
                              :sc.mainImage.shape[1],
                              :sc.mainImage.shape[2]]
            if (isinstance(entry.get('band'), int) and
                    entry['band'] >= 1 and entry['band'] <= image.shape[2]):  # type: ignore[misc]
                sc.bandidx = entry['band'] - 1
            sc.composite = entry.get('composite', 'lighten')
            if (hasattr(self, '_bandnames') and entry.get('band') and
                    str(entry['band']).lower() in self._bandnames and
                    image.shape[2] > self._bandnames[  # type: ignore[misc]
                        str(entry['band']).lower()]):
                sc.bandidx = self._bandnames[str(entry['band']).lower()]
            if entry.get('band') == 'red' and image.shape[2] > 2:  # type: ignore[misc]
                sc.bandidx = 0
            elif entry.get('band') == 'blue' and image.shape[2] > 2:  # type: ignore[misc]
                sc.bandidx = 2
                sc.band = image[:, :, 2]
            elif entry.get('band') == 'alpha':
                sc.bandidx = (image.shape[2] - 1 if image.shape[2] in (2, 4)  # type: ignore[misc]
                              else None)
                sc.band = (image[:, :, -1] if image.shape[2] in (2, 4) else  # type: ignore[misc]
                           np.full(image.shape[:2], 255, np.uint8))
                sc.composite = entry.get('composite', 'multiply')
            if sc.band is None:
                sc.band = image[
                    :, :, sc.bandidx  # type: ignore[index]
                    if sc.bandidx is not None and sc.bandidx < image.shape[2]  # type: ignore[misc]
                    else 0]
            sc.band = self._applyStyleFunction(sc.band, sc, 'preband')
            sc.palette = getPaletteColors(entry.get(
                'palette', ['#000', '#FFF']
                if entry.get('band') != 'alpha' else ['#FFF0', '#FFFF']))
            sc.discrete = entry.get('scheme') == 'discrete'
            sc.palettebase = np.linspace(0, 1, len(sc.palette), endpoint=True)
            sc.nodata = entry.get('nodata')
            sc.min = self._getMinMax(
                'min', entry.get('min', 'auto'), image.dtype, sc.bandidx, frame)
            sc.max = self._getMinMax(
                'max', entry.get('max', 'auto'), image.dtype, sc.bandidx, frame)
            sc.clamp = entry.get('clamp', True)
            delta = sc.max - sc.min if sc.max != sc.min else 1
            if sc.nodata is not None:
                sc.mask = sc.band != float(sc.nodata)
            else:
                sc.mask = np.full(image.shape[:2], True)
            sc.band = (sc.band - sc.min) / delta
            if not sc.clamp:
                sc.mask = sc.mask & (sc.band >= 0) & (sc.band <= 1)
            sc.band = self._applyStyleFunction(sc.band, sc, 'band')
            # To implement anything other multiply or lighten, we should mimic
            # mapnik (and probably delegate to a family of functions).
            # mapnik's options are: clear src dst src_over dst_over src_in
            # dst_in src_out dst_out src_atop dst_atop xor plus minus multiply
            # screen overlay darken lighten color_dodge color_burn hard_light
            # soft_light difference exclusion contrast invert grain_merge
            # grain_extract hue saturation color value linear_dodge linear_burn
            # divide.
            # See https://docs.gimp.org/en/gimp-concepts-layer-modes.html for
            # some details.
            for channel in range(sc.output.shape[2]):  # type: ignore[misc]
                if np.all(sc.palette[:, channel] == sc.palette[0, channel]):
                    if ((sc.palette[0, channel] == 0 and sc.composite != 'multiply') or
                            (sc.palette[0, channel] == 255 and sc.composite == 'multiply')):
                        continue
                    clrs = np.full(sc.band.shape, sc.palette[0, channel], dtype=sc.band.dtype)
                else:
                    # Don't recompute if the sc.palette is repeated two channels
                    # in a row.
                    if not channel or np.any(
                            sc.palette[:, channel] != sc.palette[:, channel - 1]):
                        if not sc.discrete:
                            clrs = np.interp(sc.band, sc.palettebase, sc.palette[:, channel])
                        else:
                            clrs = sc.palette[
                                np.floor(sc.band * len(sc.palette)).astype(int).clip(
                                    0, len(sc.palette) - 1), channel]
                if sc.composite == 'multiply':
                    if eidx:
                        sc.output[:sc.mask.shape[0], :sc.mask.shape[1], channel] = np.multiply(
                            sc.output[:sc.mask.shape[0], :sc.mask.shape[1], channel],
                            np.where(sc.mask, clrs / 255, 1))
                else:
                    if not eidx:
                        sc.output[:sc.mask.shape[0],
                                  :sc.mask.shape[1],
                                  channel] = np.where(sc.mask, clrs, 0)
                    else:
                        sc.output[:sc.mask.shape[0], :sc.mask.shape[1], channel] = np.maximum(
                            sc.output[:sc.mask.shape[0], :sc.mask.shape[1], channel],
                            np.where(sc.mask, clrs, 0))
            sc.output = self._applyStyleFunction(sc.output, sc, 'postband')
        if hasattr(sc, 'styleIndex'):
            del sc.styleIndex
        sc.output = self._applyStyleFunction(sc.output, sc, 'main')
        if sc.dtype == 'uint8':
            sc.output = sc.output.astype(np.uint8)
        elif sc.dtype == 'uint16':
            sc.output = (sc.output * 65535 / 255).astype(np.uint16)
        elif sc.dtype == 'float':
            sc.output /= 255
        if sc.axis is not None and 0 <= int(sc.axis) < sc.output.shape[2]:  # type: ignore[misc]
            sc.output = sc.output[:, :, sc.axis:sc.axis + 1]
        sc.output = self._applyStyleFunction(sc.output, sc, 'post')
        return sc.output

    def _outputTileNumpyStyle(
            self, intile: Any, applyStyle: bool, x: int, y: int, z: int,
            frame: Optional[int] = None) -> Tuple[np.ndarray, str]:
        """
        Convert a tile to a numpy array.  Optionally apply the style to a tile.
        Always returns a numpy tile.

        :param tile: the tile to convert.
        :param applyStyle: if True and there is a style, apply it.
        :param x: the x tile position; used for multi-frame styles.
        :param y: the y tile position; used for multi-frame styles.
        :param z: the z tile position; used for multi-frame styles.
        :param frame: the frame to use for auto-ranging.
        :returns: a numpy array and a target PIL image mode.
        """
        tile, mode = _imageToNumpy(intile)
        if (applyStyle and (getattr(self, 'style', None) or hasattr(self, '_iccprofiles')) and
                (not getattr(self, 'style', None) or
                 len(cast(JSONDict, self.style)) != 1 or
                 cast(JSONDict, self.style).get('icc') is not False)):
            tile = self._applyStyle(tile, getattr(self, 'style', None), x, y, z, frame)
        if tile.shape[0] != self.tileHeight or tile.shape[1] != self.tileWidth:
            extend = np.zeros(
                (self.tileHeight, self.tileWidth, tile.shape[2]),  # type: ignore[misc]
                dtype=tile.dtype)
            extend[:min(self.tileHeight, tile.shape[0]),
                   :min(self.tileWidth, tile.shape[1])] = tile
            tile = extend
        return tile, mode

    def _outputTile(
            self, tile: Union[ImageBytes, PIL.Image.Image, bytes, np.ndarray],
            tileEncoding: str, x: int, y: int, z: int,
            pilImageAllowed: bool = False,
            numpyAllowed: Union[bool, str] = False, applyStyle: bool = True,
            **kwargs) -> Union[ImageBytes, PIL.Image.Image, bytes, np.ndarray]:
        """
        Convert a tile from a numpy array, PIL image, or image in memory to the
        desired encoding.

        :param tile: the tile to convert.
        :param tileEncoding: the current tile encoding.
        :param x: tile x value.  Used for cropping or edge adjustment.
        :param y: tile y value.  Used for cropping or edge adjustment.
        :param z: tile z (level) value.  Used for cropping or edge adjustment.
        :param pilImageAllowed: True if a PIL image may be returned.
        :param numpyAllowed: True if a numpy image may be returned.  'always'
            to return a numpy array.
        :param applyStyle: if True and there is a style, apply it.
        :returns: either a numpy array, a PIL image, or a memory object with an
            image file.
        """
        isEdge = False
        if self.edge:
            sizeX = int(self.sizeX * 2 ** (z - (self.levels - 1)))
            sizeY = int(self.sizeY * 2 ** (z - (self.levels - 1)))
            maxX = (x + 1) * self.tileWidth
            maxY = (y + 1) * self.tileHeight
            isEdge = maxX > sizeX or maxY > sizeY
        hasStyle = (
            len(set(getattr(self, 'style', {})) - {'icc'}) or
            getattr(self, 'style', {}).get('icc', config.getConfig('icc_correction', True)))
        if (tileEncoding not in (TILE_FORMAT_PIL, TILE_FORMAT_NUMPY) and
                numpyAllowed != 'always' and tileEncoding == self.encoding and
                not isEdge and (not applyStyle or not hasStyle)):
            return tile

        if self._dtype is None or (isinstance(self._dtype, str) and self._dtype == 'check'):
            if isinstance(tile, np.ndarray):
                self._dtype = np.dtype(tile.dtype)
                self._bandCount = tile.shape[-1] if len(tile.shape) == 3 else 1
            elif isinstance(tile, PIL.Image.Image):
                self._dtype = np.uint8 if ';16' not in tile.mode else np.uint16
                self._bandCount = len(tile.mode)
            else:
                _img = _imageToNumpy(tile)[0]
                self._dtype = np.dtype(_img.dtype)
                self._bandCount = _img.shape[-1] if len(_img.shape) == 3 else 1

        mode = None
        if (numpyAllowed == 'always' or tileEncoding == TILE_FORMAT_NUMPY or
                (applyStyle and hasStyle) or isEdge):
            tile, mode = self._outputTileNumpyStyle(
                tile, applyStyle, x, y, z, self._getFrame(**kwargs))
        if isEdge:
            contentWidth = min(self.tileWidth,
                               sizeX - (maxX - self.tileWidth))
            contentHeight = min(self.tileHeight,
                                sizeY - (maxY - self.tileHeight))
            tile, mode = _imageToNumpy(tile)
            if self.edge in (True, 'crop'):
                tile = tile[:contentHeight, :contentWidth]
            else:
                color = PIL.ImageColor.getcolor(self.edge, mode)
                tile = tile.copy()
                tile[:, contentWidth:] = color
                tile[contentHeight:] = color
        if isinstance(tile, np.ndarray) and numpyAllowed:
            return tile
        tile = _imageToPIL(tile)
        if pilImageAllowed:
            return tile
        # If we can't redirect, but the tile is read from a file in the desired
        # output format, just read the file
        if getattr(tile, 'fp', None) and self._pilFormatMatches(tile):
            tile.fp.seek(0)  # type: ignore
            return tile.fp.read()  # type: ignore
        result = utilities._encodeImageBinary(
            tile, self.encoding, self.jpegQuality, self.jpegSubsampling, self.tiffCompression)
        return result

    def _getAssociatedImage(self, imageKey: str) -> Optional[PIL.Image.Image]:
        """
        Get an associated image in PIL format.

        :param imageKey: the key of the associated image.
        :return: the image in PIL format or None.
        """
        return None

    @classmethod
    def canRead(cls, *args, **kwargs) -> bool:
        """
        Check if we can read the input.  This takes the same parameters as
        __init__.

        :returns: True if this class can read the input.  False if it cannot.
        """
        return False

    def getMetadata(self) -> JSONDict:
        """
        Return metadata about this tile source.  This contains

            :levels: number of tile levels in this image.
            :sizeX: width of the image in pixels.
            :sizeY: height of the image in pixels.
            :tileWidth: width of a tile in pixels.
            :tileHeight: height of a tile in pixels.
            :magnification: if known, the magnificaiton of the image.
            :mm_x: if known, the width of a pixel in millimeters.
            :mm_y: if known, the height of a pixel in millimeters.
            :dtype: if known, the type of values in this image.

            In addition to the keys that listed above, tile sources that expose
            multiple frames will also contain

            :frames: a list of frames.  Each frame entry is a dictionary with

                :Frame: a 0-values frame index (the location in the list)
                :Channel: optional.  The name of the channel, if known
                :IndexC: optional if unique.  A 0-based index into the channel
                    list
                :IndexT: optional if unique.  A 0-based index for time values
                :IndexZ: optional if unique.  A 0-based index for z values
                :IndexXY: optional if unique.  A 0-based index for view (xy)
                    values
                :Index<axis>: optional if unique.  A 0-based index for an
                    arbitrary axis.
                :Index: a 0-based index of non-channel unique sets.  If the
                    frames vary only by channel and are adjacent, they will
                    have the same index.

            :IndexRange: a dictionary of the number of unique index values from
                frames if greater than 1 (e.g., if an entry like IndexXY is not
                present, then all frames either do not have that value or have
                a value of 0).
            :IndexStride: a dictionary of the spacing between frames where
                unique axes values change.
            :channels: optional.  If known, a list of channel names
            :channelmap: optional.  If known, a dictionary of channel names
                with their offset into the channel list.

        Note that this does not include band information, though some tile
        sources may do so.
        """
        mag = self.getNativeMagnification()
        return JSONDict({
            'levels': self.levels,
            'sizeX': self.sizeX,
            'sizeY': self.sizeY,
            'tileWidth': self.tileWidth,
            'tileHeight': self.tileHeight,
            'magnification': mag['magnification'],
            'mm_x': mag['mm_x'],
            'mm_y': mag['mm_y'],
            'dtype': str(self.dtype),
            'bandCount': self.bandCount,
        })

    @property
    def metadata(self) -> JSONDict:
        return self.getMetadata()

    def _getFrameValueInformation(self, frames: List[Dict]) -> Dict[str, Any]:
        """
        Given a `frames` list from a metadata response, return a dictionary describing
        the value info for any frame axes. Keys in this dictionary follow the pattern "Value[AXIS]"
        and each maps to a dictionary describing the axis, including a list of values, whether the
        axis is uniform, the units, minimum value, maximum value, and data type.

        :param frames: A list of dictionaries describing each frame in the image
        :returns: A dictionary describing the values of frame axes
        """
        refvalues: Dict[str, Dict[str, List]] = {}
        for frame in frames:
            for key, value in frame.items():
                if 'Value' in key:
                    if key not in refvalues:
                        refvalues[key] = {}
                    value_index = str(frame.get(key.replace('Value', 'Index')))
                    if value_index not in refvalues[key]:
                        refvalues[key][value_index] = [value]
                    else:
                        refvalues[key][value_index].append(value)
        frame_value_info = {}
        for key, value_mapping in refvalues.items():
            axis_name = key.replace('Value', '').lower()
            units = None
            if hasattr(self, 'frameUnits') and self.frameUnits is not None:
                units = self.frameUnits.get(axis_name)
            uniform = all(len(set(value_list)) <= 1 for value_list in value_mapping.values())
            if uniform:
                # for uniform values, only record values at each axis index
                values = [
                    value_list[0] for value_list in value_mapping.values() if len(value_list)
                ]
            else:
                # for non-uniform axes, record values at every frame
                values = [frame.get(key) for frame in frames]
            try:
                min_val = min(values)
                max_val = max(values)
            except TypeError:
                min_val = None
                max_val = None
            frame_value_info[key] = dict(
                values=values,
                uniform=uniform,
                units=units,
                min=min_val,
                max=max_val,
                datatype=np.array(values).dtype.name,
            )
        return frame_value_info

    def _addMetadataFrameInformation(
            self, metadata: JSONDict, channels: Optional[List[str]] = None) -> None:
        """
        Given a metadata response that has a `frames` list, where each frame
        has some of `Index(XY|Z|C|T)`, populate the `Frame`, `Index` and
        possibly the `Channel` of each frame in the list and the `IndexRange`,
        `IndexStride`, and possibly the `channels` and `channelmap` entries of
        the metadata.

        :param metadata: the metadata response that might contain `frames`.
            Modified.
        :param channels: an optional list of channel names.
        """
        if 'frames' not in metadata:
            return
        maxref: Dict[str, int] = {}
        refkeys = {'IndexC'}
        index = 0
        for idx, frame in enumerate(metadata['frames']):
            refkeys |= {key for key in frame
                        if key.startswith('Index') and len(key.split('Index', 1)[1])}
            for key in refkeys:
                if key in frame and frame[key] + 1 > maxref.get(key, 0):
                    maxref[key] = frame[key] + 1
            frame['Frame'] = idx
            if idx and (any(
                    frame.get(key) != metadata['frames'][idx - 1].get(key)
                    for key in refkeys if key != 'IndexC') or not any(
                    metadata['frames'][idx].get(key) for key in refkeys)):
                index += 1
            frame['Index'] = index
        metadata.update(self._getFrameValueInformation(metadata['frames']))
        if any(val > 1 for val in maxref.values()):
            metadata['IndexRange'] = {key: value for key, value in maxref.items() if value > 1}
            metadata['IndexStride'] = {
                key: [idx for idx, frame in enumerate(metadata['frames']) if frame[key] == 1][0]
                for key in metadata['IndexRange']
            }
        if channels and len(channels) >= maxref.get('IndexC', 1):
            metadata['channels'] = channels[:maxref.get('IndexC', 1)]
            metadata['channelmap'] = {
                cname: c for c, cname in enumerate(channels[:maxref.get('IndexC', 1)])}
            for frame in metadata['frames']:
                frame['Channel'] = channels[frame.get('IndexC', 0)]

    def getInternalMetadata(self, **kwargs) -> Optional[Dict[Any, Any]]:
        """
        Return additional known metadata about the tile source.  Data returned
        from this method is not guaranteed to be in any particular format or
        have specific values.

        :returns: a dictionary of data or None.
        """
        return None

    def getOneBandInformation(self, band: int) -> Dict[str, Any]:
        """
        Get band information for a single band.

        :param band: a 1-based band.
        :returns: a dictionary of band information.  See getBandInformation.
        """
        return self.getBandInformation()[band]

    def getBandInformation(self, statistics: bool = False, **kwargs) -> Dict[int, Any]:
        """
        Get information about each band in the image.

        :param statistics: if True, compute statistics if they don't already
            exist.
        :returns: a dictionary of one dictionary per band.  Each dictionary
            contains known values such as interpretation, min, max, mean,
            stdev.
        """
        if not getattr(self, '_bandInfo', None):
            bandInterp = {
                1: ['gray'],
                2: ['gray', 'alpha'],
                3: ['red', 'green', 'blue'],
                4: ['red', 'green', 'blue', 'alpha']}
            if not statistics:
                if not getattr(self, '_bandInfoNoStats', None):
                    tile = cast(LazyTileDict, self.getSingleTile())['tile']
                    bands = tile.shape[2] if len(tile.shape) > 2 else 1
                    interp = bandInterp.get(bands, bandInterp[3])
                    bandInfo = {
                        idx + 1: {'interpretation': interp[idx] if idx < len(interp)
                                  else 'unknown'} for idx in range(bands)}
                    self._bandInfoNoStats = bandInfo
                return self._bandInfoNoStats
            analysisSize = 2048
            histogram = self.histogram(
                onlyMinMax=True,
                output={'maxWidth': min(self.sizeX, analysisSize),
                        'maxHeight': min(self.sizeY, analysisSize)},
                resample=False,
                **kwargs)
            bands = histogram['min'].shape[0]
            interp = bandInterp.get(bands, bandInterp[3])
            bandInfo = {
                idx + 1: {'interpretation': interp[idx] if idx < len(interp)
                          else 'unknown'} for idx in range(bands)}
            for key in {'min', 'max', 'mean', 'stdev'}:
                if key in histogram:
                    for idx in range(bands):
                        bandInfo[idx + 1][key] = histogram[key][idx]
            self._bandInfo = bandInfo
        return self._bandInfo

    def _getFrame(self, frame: Optional[int] = None, **kwargs) -> int:
        """
        Get the current frame number.  If a style is used that completely
        specified the frame, use that value instead.

        :param frame: an integer or string with the frame number.
        :returns: an integer frame number.
        """
        frame = int(frame or 0)
        if (hasattr(self, '_style') and
                'bands' in cast(JSONDict, self.style) and
                len(cast(JSONDict, self.style)['bands']) and
                all(entry.get('frame') is not None
                    for entry in cast(JSONDict, self.style)['bands'])):
            frame = int(cast(JSONDict, self.style)['bands'][0]['frame'])
        return frame

    def _xyzInRange(
            self, x: int, y: int, z: int, frame: Optional[int] = None,
            numFrames: Optional[int] = None) -> None:
        """
        Check if a tile at x, y, z is in range based on self.levels,
        self.tileWidth, self.tileHeight, self.sizeX, and self.sizeY,  Raise an
        ``TileSourceXYZRangeError`` exception if not.
        """
        if z < 0 or z >= self.levels:
            msg = 'z layer does not exist'
            raise exceptions.TileSourceXYZRangeError(msg)
        scale = 2 ** (self.levels - 1 - z)
        offsetx = x * self.tileWidth * scale
        if not (0 <= offsetx < self.sizeX):
            msg = 'x is outside layer'
            raise exceptions.TileSourceXYZRangeError(msg)
        offsety = y * self.tileHeight * scale
        if not (0 <= offsety < self.sizeY):
            msg = 'y is outside layer'
            raise exceptions.TileSourceXYZRangeError(msg)
        if frame is not None and numFrames is not None:
            if frame < 0 or frame >= numFrames:
                msg = 'Frame does not exist'
                raise exceptions.TileSourceXYZRangeError(msg)

    def _xyzToCorners(self, x: int, y: int, z: int) -> Tuple[int, int, int, int, int]:
        """
        Convert a tile in x, y, z to corners and scale factor.   The corners
        are in full resolution image coordinates.  The scale is always a power
        of two >= 1.

        To convert the output to the resolution at the specified z level,
        integer divide the corners by the scale (e.g., x0z = x0 // scale).

        :param x, y, z: the tile position.
        :returns: x0, y0, x1, y1, scale.
        """
        step = int(2 ** (self.levels - 1 - z))
        x0 = x * step * self.tileWidth
        x1 = min((x + 1) * step * self.tileWidth, self.sizeX)
        y0 = y * step * self.tileHeight
        y1 = min((y + 1) * step * self.tileHeight, self.sizeY)
        return x0, y0, x1, y1, step

    def _nonemptyLevelsList(self, frame: Optional[int] = 0) -> List[bool]:
        """
        Return a list of one value per level where the value is None if the
        level does not exist in the file and any other value if it does.

        :param frame: the frame number.
        :returns: a list of levels length.
        """
        return [True] * self.levels

    def _getTileFromEmptyLevel(self, x: int, y: int, z: int, **kwargs) -> Tuple[
            Union[PIL.Image.Image, np.ndarray], str]:
        """
        Given the x, y, z tile location in an unpopulated level, get tiles from
        higher resolution levels to make the lower-res tile.

        :param x: location of tile within original level.
        :param y: location of tile within original level.
        :param z: original level.
        :returns: tile in PIL format.
        """
        lastlog = time.time()
        basez = z
        scale = 1
        dirlist = self._nonemptyLevelsList(kwargs.get('frame'))
        while dirlist[z] is None:
            scale *= 2
            z += 1
        # if scale >= max(tileWidth, tileHeight), we can just get one tile per
        # pixel at this point.  If dtype is not uint8 or the number of bands is
        # greater than 4, also just use nearest neighbor.
        if (scale >= max(self.tileWidth, self.tileHeight) or
                (self.dtype and self.dtype != np.uint8) or
                (self.bandCount and self.bandCount > 4)):
            nptile = np.zeros((self.tileHeight, self.tileWidth, cast(int, self.bandCount)),
                              dtype=self.dtype)
            maxX = 2.0 ** (z + 1 - self.levels) * self.sizeX / self.tileWidth
            maxY = 2.0 ** (z + 1 - self.levels) * self.sizeY / self.tileHeight
            for newY in range(scale):
                sty = (y * scale + newY) * self.tileHeight
                dy = sty % scale
                ty = (newY * self.tileHeight) // scale
                if (newY and y * scale + newY >= maxY) or dy >= self.tileHeight:
                    continue
                for newX in range(scale):
                    stx = (x * scale + newX) * self.tileWidth
                    dx = stx % scale
                    if (newX and x * scale + newX >= maxX) or dx >= self.tileWidth:
                        continue
                    tx = (newX * self.tileWidth) // scale
                    if time.time() - lastlog > 10:
                        self.logger.info(
                            'Compositing tile from higher resolution tiles x=%d y=%d z=%d',
                            x * scale + newX, y * scale + newY, z)
                        lastlog = time.time()
                    subtile = getattr(self, '_unstyledInstance', self).getTile(
                        x * scale + newX, y * scale + newY, z,
                        pilImageAllowed=False, numpyAllowed='always',
                        sparseFallback=True, edge=False, frame=kwargs.get('frame'))
                    subtile = subtile[dx::scale, dy::scale]
                    nptile[ty:ty + subtile.shape[0], tx:tx + subtile.shape[1]] = subtile
            return nptile, TILE_FORMAT_NUMPY
        while z - basez > self._maxSkippedLevels:
            z -= self._maxSkippedLevels
            scale = int(scale / 2 ** self._maxSkippedLevels)
        tile = PIL.Image.new('RGBA', (
            min(self.sizeX, self.tileWidth * scale), min(self.sizeY, self.tileHeight * scale)))
        maxX = 2.0 ** (z + 1 - self.levels) * self.sizeX / self.tileWidth
        maxY = 2.0 ** (z + 1 - self.levels) * self.sizeY / self.tileHeight
        for newY in range(scale):
            for newX in range(scale):
                if ((newX or newY) and ((x * scale + newX) >= maxX or
                                        (y * scale + newY) >= maxY)):
                    continue
                if time.time() - lastlog > 10:
                    self.logger.info(
                        'Compositing tile from higher resolution tiles x=%d y=%d z=%d',
                        x * scale + newX, y * scale + newY, z)
                    lastlog = time.time()
                subtile = getattr(self, '_unstyledInstance', self).getTile(
                    x * scale + newX, y * scale + newY, z,
                    pilImageAllowed=True, numpyAllowed=False,
                    sparseFallback=True, edge=False, frame=kwargs.get('frame'))
                subtile = _imageToPIL(subtile)
                mode = subtile.mode
                tile.paste(subtile, (newX * self.tileWidth,
                                     newY * self.tileHeight))
        return tile.resize(
            (self.tileWidth, self.tileHeight),
            getattr(PIL.Image, 'Resampling', PIL.Image).LANCZOS).convert(mode), TILE_FORMAT_PIL

    @methodcache()
    def getTile(self, x: int, y: int, z: int, pilImageAllowed: bool = False,
                numpyAllowed: Union[bool, str] = False,
                sparseFallback: bool = False, frame: Optional[int] = None) -> Union[
                    ImageBytes, PIL.Image.Image, bytes, np.ndarray]:
        """
        Get a tile from a tile source, returning it as an binary image, a PIL
        image, or a numpy array.

        :param x: the 0-based x position of the tile on the specified z level.
            0 is left.
        :param y: the 0-based y position of the tile on the specified z level.
            0 is top.
        :param z: the z level of the tile.  May range from [0, self.levels],
            where 0 is the lowest resolution, single tile for the whole source.
        :param pilImageAllowed: True if a PIL image may be returned.
        :param numpyAllowed: True if a numpy image may be returned.  'always'
            to return a numpy array.
        :param sparseFallback: if False and a tile doesn't exist, raise an
            error.  If True, check if a lower resolution tile exists, and, if
            so, interpolate the needed data for this tile.
        :param frame: the frame number within the tile source.  None is the
            same as 0 for multi-frame sources.
        :returns: either a numpy array, a PIL image, or a memory object with an
            image file.
        """
        raise NotImplementedError

    def getTileMimeType(self) -> str:
        """
        Return the default mimetype for image tiles.

        :returns: the mime type of the tile.
        """
        return TileOutputMimeTypes.get(self.encoding, 'image/jpeg')

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
        always includes the entire image and has a default size of 256 x 256.

        :param width: maximum width in pixels.
        :param height: maximum height in pixels.
        :param kwargs: optional arguments.  Some options are encoding,
            jpegQuality, jpegSubsampling, and tiffCompression.
        :returns: thumbData, thumbMime: the image data and the mime type.
        """
        if ((width is not None and (not isinstance(width, int) or width < 2)) or
                (height is not None and (not isinstance(height, int) or height < 2))):
            msg = 'Invalid width or height.  Minimum value is 2.'
            raise ValueError(msg)
        if width is None and height is None:
            width = height = 256
        params = dict(kwargs)
        params['output'] = {'maxWidth': width, 'maxHeight': height}
        params.pop('region', None)
        return self.getRegion(**params)

    def getPreferredLevel(self, level: int) -> int:
        """
        Given a desired level (0 is minimum resolution, self.levels - 1 is max
        resolution), return the level that contains actual data that is no
        lower resolution.

        :param level: desired level
        :returns level: a level with actual data that is no lower resolution.
        """
        if self.levels is None:
            return level
        level = max(0, min(level, self.levels - 1))
        baselevel = level
        levelList = self._nonemptyLevelsList()
        while levelList[level] is None and level < self.levels - 1:
            level += 1
        while level - baselevel >= self._maxSkippedLevels:
            level -= self._maxSkippedLevels
        return level

    def convertRegionScale(
            self, sourceRegion: Dict[str, Any],
            sourceScale: Optional[Dict[str, float]] = None,
            targetScale: Optional[Dict[str, float]] = None,
            targetUnits: Optional[str] = None,
            cropToImage: bool = True) -> Dict[str, Any]:
        """
        Convert a region from one scale to another.

        :param sourceRegion: a dictionary of optional values which specify the
            part of an image to process.

            :left: the left edge (inclusive) of the region to process.
            :top: the top edge (inclusive) of the region to process.
            :right: the right edge (exclusive) of the region to process.
            :bottom: the bottom edge (exclusive) of the region to process.
            :width: the width of the region to process.
            :height: the height of the region to process.
            :units: either 'base_pixels' (default), 'pixels', 'mm', or
                'fraction'.  base_pixels are in maximum resolution pixels.
                pixels is in the specified magnification pixels.  mm is in the
                specified magnification scale.  fraction is a scale of 0 to 1.
                pixels and mm are only available if the magnification and mm
                per pixel are defined for the image.

        :param sourceScale: a dictionary of optional values which specify the
            scale of the source region.  Required if the sourceRegion is
            in "mag_pixels" units.

            :magnification: the magnification ratio.
            :mm_x: the horizontal size of a pixel in millimeters.
            :mm_y: the vertical size of a pixel in millimeters.

        :param targetScale: a dictionary of optional values which specify the
            scale of the target region.  Required in targetUnits is in
            "mag_pixels" units.

            :magnification: the magnification ratio.
            :mm_x: the horizontal size of a pixel in millimeters.
            :mm_y: the vertical size of a pixel in millimeters.

        :param targetUnits: if not None, convert the region to these units.
            Otherwise, the units are will either be the sourceRegion units if
            those are not "mag_pixels" or base_pixels.  If "mag_pixels", the
            targetScale must be specified.
        :param cropToImage: if True, don't return region coordinates outside of
            the image.
        """
        units = sourceRegion.get('units')
        if units not in TileInputUnits:
            raise ValueError('Invalid units %r' % units)
        units = TileInputUnits[units]
        if targetUnits is not None:
            if targetUnits not in TileInputUnits:
                raise ValueError('Invalid units %r' % targetUnits)
            targetUnits = TileInputUnits[targetUnits]
        if (units != 'mag_pixels' and (
                targetUnits is None or targetUnits == units)):
            return sourceRegion
        magArgs: Dict[str, Any] = (sourceScale or {}).copy()
        magArgs['rounding'] = None
        magLevel = self.getLevelForMagnification(**magArgs)
        mag = self.getMagnificationForLevel(magLevel)
        metadata = self.getMetadata()
        # Get region in base pixels
        left, top, right, bottom = self._getRegionBounds(
            metadata, desiredMagnification=mag, cropToImage=cropToImage,
            **sourceRegion)
        # If requested, convert region to targetUnits
        desMagArgs: Dict[str, Any] = (targetScale or {}).copy()
        desMagArgs['rounding'] = None
        desMagLevel = self.getLevelForMagnification(**desMagArgs)
        desiredMagnification = self.getMagnificationForLevel(desMagLevel)
        scaleX, scaleY = self._scaleFromUnits(metadata, targetUnits, desiredMagnification)
        left = float(left) / scaleX
        right = float(right) / scaleX
        top = float(top) / scaleY
        bottom = float(bottom) / scaleY
        targetRegion = {
            'left': left,
            'top': top,
            'right': right,
            'bottom': bottom,
            'width': right - left,
            'height': bottom - top,
            'units': TileInputUnits[targetUnits],
        }
        # Reduce region information to match what was supplied
        for key in ('left', 'top', 'right', 'bottom', 'width', 'height'):
            if key not in sourceRegion:
                del targetRegion[key]
        return targetRegion

    def getRegion(self, format: Union[str, Tuple[str]] = (TILE_FORMAT_IMAGE, ), **kwargs) -> Tuple[
            Union[np.ndarray, PIL.Image.Image, ImageBytes, bytes, pathlib.Path], str]:
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
        if 'tile_position' in kwargs:
            kwargs = kwargs.copy()
            kwargs.pop('tile_position', None)
        tiled = TILE_FORMAT_IMAGE in format and kwargs.get('encoding') == 'TILED'
        if not tiled and 'tile_offset' not in kwargs and 'tile_size' not in kwargs:
            kwargs = kwargs.copy()
            kwargs['tile_size'] = {
                'width': max(self.tileWidth, 4096),
                'height': max(self.tileHeight, 4096)}
            kwargs['tile_offset'] = {'auto': True}
        resample = True
        if 'resample' in kwargs:
            kwargs = kwargs.copy()
            resample = kwargs.pop('resample', None)
        tileIter = TileIterator(self, format=TILE_FORMAT_NUMPY, resample=None, **kwargs)
        if tileIter.info is None:
            pilimage = PIL.Image.new('RGB', (0, 0))
            return utilities._encodeImage(pilimage, format=format, **kwargs)
        regionWidth = tileIter.info['region']['width']
        regionHeight = tileIter.info['region']['height']
        top = tileIter.info['region']['top']
        left = tileIter.info['region']['left']
        mode = None if TILE_FORMAT_NUMPY in format else tileIter.info['mode']
        outWidth = tileIter.info['output']['width']
        outHeight = tileIter.info['output']['height']
        image: Optional[Union[np.ndarray, PIL.Image.Image, ImageBytes, bytes]] = None
        tiledimage = None
        for tile in tileIter:
            # Add each tile to the image
            subimage, _ = _imageToNumpy(tile['tile'])
            x0, y0 = tile['x'] - left, tile['y'] - top
            if tiled:
                tiledimage = utilities._addRegionTileToTiled(
                    tiledimage, subimage, x0, y0, regionWidth, regionHeight, tile, **kwargs)
            else:
                image = utilities._addSubimageToImage(
                    cast(Optional[np.ndarray], image), subimage, x0, y0, regionWidth, regionHeight)
            # Somehow discarding the tile here speeds things up.
            del tile
            del subimage
        # Scale if we need to
        outWidth = int(math.floor(outWidth))
        outHeight = int(math.floor(outHeight))
        if tiled:
            return self._encodeTiledImage(
                cast(Dict[str, Any], tiledimage), outWidth, outHeight, tileIter.info, **kwargs)
        if outWidth != regionWidth or outHeight != regionHeight:
            dtype = cast(np.ndarray, image).dtype
            if dtype == np.uint8 or (resample is not None and (
                    dtype != np.uint16 or cast(np.ndarray, image).shape[-1] != 1)):
                image = _imageToPIL(cast(np.ndarray, image), mode).resize(
                    (outWidth, outHeight),
                    getattr(PIL.Image, 'Resampling', PIL.Image).NEAREST
                    if resample is None else
                    getattr(PIL.Image, 'Resampling', PIL.Image).BICUBIC
                    if outWidth > regionWidth else
                    getattr(PIL.Image, 'Resampling', PIL.Image).LANCZOS)
                if dtype == np.uint16 and TILE_FORMAT_NUMPY in format:
                    image = _imageToNumpy(image)[0].astype(dtype) * 257
            else:
                cols = [int(idx * regionWidth / outWidth) for idx in range(outWidth)]
                rows = [int(idx * regionHeight / outHeight) for idx in range(outHeight)]
                image = np.take(np.take(cast(np.ndarray, image), rows, axis=0), cols, axis=1)
        maxWidth = kwargs.get('output', {}).get('maxWidth')
        maxHeight = kwargs.get('output', {}).get('maxHeight')
        if kwargs.get('fill') and maxWidth and maxHeight:
            image = utilities._letterboxImage(
                _imageToPIL(cast(np.ndarray, image), mode), maxWidth, maxHeight, kwargs['fill'])
        return utilities._encodeImage(cast(np.ndarray, image), format=format, **kwargs)

    def _encodeTiledImage(
            self, image: Dict[str, Any], outWidth: int, outHeight: int,
            iterInfo: Dict[str, Any], **kwargs) -> Tuple[pathlib.Path, str]:
        """
        Given an image record of a set of vips image strips, generate a tiled
        tiff file at the specified output size.

        :param image: a record with partial vips images and the current output
            size.
        :param outWidth: the output size after scaling and before any
            letterboxing.
        :param outHeight: the output size after scaling and before any
            letterboxing.
        :param iterInfo: information about the region based on the tile
            iterator.

        Additional parameters are available.

        :param fill: a color to use in letterboxing.
        :param maxWidth: the output size if letterboxing is applied.
        :param maxHeight: the output size if letterboxing is applied.
        :param compression: the internal compression format.  This can handle
            a variety of options similar to the converter utility.
        :returns: a pathlib.Path of the output file and the output mime type.
        """
        import pyvips

        vimg = cast(pyvips.Image, image['strips'][0])
        for y in sorted(image['strips'].keys())[1:]:
            if image['strips'][y].bands + 1 == vimg.bands:
                image['strips'][y] = utilities._vipsAddAlphaBand(image['strips'][y], vimg)
            elif vimg.bands + 1 == image['strips'][y].bands:
                vimg = utilities._vipsAddAlphaBand(vimg, image['strips'][y])
            vimg = vimg.insert(image['strips'][y], 0, y, expand=True)

        if outWidth != image['width'] or outHeight != image['height']:
            scale = outWidth / image['width']
            vimg = vimg.resize(outWidth / image['width'], vscale=outHeight / image['height'])
            image['width'] = outWidth
            image['height'] = outHeight
            image['mm_x'] = image['mm_x'] / scale if image['mm_x'] else image['mm_x']
            image['mm_y'] = image['mm_y'] / scale if image['mm_y'] else image['mm_y']
            image['magnification'] = (
                image['magnification'] * scale
                if image['magnification'] else image['magnification'])
        return self._encodeTiledImageFromVips(vimg, iterInfo, image, **kwargs)

    def _encodeTiledImageFromVips(
            self, vimg: Any, iterInfo: Dict[str, Any], image: Dict[str, Any],
            **kwargs) -> Tuple[pathlib.Path, str]:
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
        import pyvips

        convertParams = utilities._vipsParameters(defaultCompression='lzw', **kwargs)
        vimg = utilities._vipsCast(
            cast(pyvips.Image, vimg), convertParams['compression'] in {'webp', 'jpeg'})
        maxWidth = kwargs.get('output', {}).get('maxWidth')
        maxHeight = kwargs.get('output', {}).get('maxHeight')
        if (kwargs.get('fill') and str(kwargs.get('fill')).lower() != 'none' and
                maxWidth and maxHeight and
                (maxWidth > image['width'] or maxHeight > image['height'])):
            corner: bool = False
            fill: str = str(kwargs.get('fill'))
            if fill.lower().startswith('corner:'):
                corner, fill = True, fill.split(':', 1)[1]
            color = PIL.ImageColor.getcolor(
                fill, ['L', 'LA', 'RGB', 'RGBA'][vimg.bands - 1])
            if isinstance(color, int):
                color = [color]
            lbimage = pyvips.Image.black(maxWidth, maxHeight, bands=vimg.bands)
            lbimage = lbimage.cast(vimg.format)
            lbimage = lbimage.draw_rect(
                [c * (257 if vimg.format == pyvips.BandFormat.USHORT else 1) for c in color],
                0, 0, maxWidth, maxHeight, fill=True)
            vimg = lbimage.insert(
                vimg,
                (maxWidth - image['width']) // 2 if not corner else 0,
                (maxHeight - image['height']) // 2 if not corner else 0)
        if image['mm_x'] and image['mm_y']:
            vimg = vimg.copy(xres=1 / image['mm_x'], yres=1 / image['mm_y'])
        fd, outputPath = tempfile.mkstemp('.tiff', 'tiledRegion_')
        os.close(fd)
        try:
            vimg.write_to_file(outputPath, **convertParams)
            return pathlib.Path(outputPath), TileOutputMimeTypes['TILED']
        except Exception as exc:
            try:
                pathlib.Path(outputPath).unlink()
            except Exception:
                pass
            raise exc

    def tileFrames(
            self, format: Union[str, Tuple[str]] = (TILE_FORMAT_IMAGE, ),
            frameList: Optional[List[int]] = None,
            framesAcross: Optional[int] = None,
            max_workers: Optional[int] = -4, **kwargs) -> Tuple[
                Union[np.ndarray, PIL.Image.Image, ImageBytes, bytes, pathlib.Path], str]:
        """
        Given the parameters for getRegion, plus a list of frames and the
        number of frames across, make a larger image composed of a region from
        each listed frame composited together.

        :param format: the desired format or a tuple of allowed formats.
            Formats are members of (TILE_FORMAT_PIL, TILE_FORMAT_NUMPY,
            TILE_FORMAT_IMAGE).  If TILE_FORMAT_IMAGE, encoding may be
            specified.
        :param frameList: None for all frames, or a list of 0-based integers.
        :param framesAcross: the number of frames across the final image.  If
            unspecified, this is the ceiling of sqrt(number of frames in frame
            list).
        :param kwargs: optional arguments.  Some options are region, output,
            encoding, jpegQuality, jpegSubsampling, tiffCompression, fill.  See
            tileIterator.
        :param max_workers: maximum workers for parallelism.  If negative, use
            the minimum of the absolute value of this number or
            multiprocessing.cpu_count().
        :returns: regionData, formatOrRegionMime: the image data and either the
            mime type, if the format is TILE_FORMAT_IMAGE, or the format.
        """
        import concurrent.futures

        lastlog = time.time()
        kwargs = kwargs.copy()
        kwargs.pop('tile_position', None)
        kwargs.pop('frame', None)
        numFrames = len(self.getMetadata().get('frames', [0]))
        if frameList:
            frameList = [f for f in frameList if f >= 0 and f < numFrames]
        if not frameList:
            frameList = list(range(numFrames))
        if len(frameList) == 1:
            return self.getRegion(format=format, frame=frameList[0], **kwargs)
        if not framesAcross:
            framesAcross = int(math.ceil(len(frameList) ** 0.5))
        framesAcross = min(len(frameList), framesAcross)
        framesHigh = int(math.ceil(len(frameList) / framesAcross))
        if not isinstance(format, (tuple, set, list)):
            format = (format, )
        tiled = TILE_FORMAT_IMAGE in format and kwargs.get('encoding') == 'TILED'
        tileIter = TileIterator(self, format=TILE_FORMAT_NUMPY, resample=None,
                                frame=frameList[0], **kwargs)
        if tileIter.info is None:
            pilimage = PIL.Image.new('RGB', (0, 0))
            return utilities._encodeImage(pilimage, format=format, **kwargs)
        frameWidth = tileIter.info['output']['width']
        frameHeight = tileIter.info['output']['height']
        maxWidth = kwargs.get('output', {}).get('maxWidth')
        maxHeight = kwargs.get('output', {}).get('maxHeight')
        if kwargs.get('fill') and maxWidth and maxHeight:
            frameWidth, frameHeight = maxWidth, maxHeight
        outWidth = frameWidth * framesAcross
        outHeight = frameHeight * framesHigh
        tile = next(tileIter)
        image = None
        tiledimage = None
        if max_workers is not None and max_workers < 0:
            max_workers = min(-max_workers, config.cpu_count(False))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = []
            for idx, frame in enumerate(frameList):
                futures.append((idx, frame, pool.submit(
                    self.getRegion, format=TILE_FORMAT_NUMPY, frame=frame, **kwargs)))
            for idx, frame, future in futures:
                subimage, _ = future.result()
                offsetX = (idx % framesAcross) * frameWidth
                offsetY = (idx // framesAcross) * frameHeight
                if time.time() - lastlog > 10:
                    self.logger.info(
                        'Tiling frame %d (%d/%d), offset %dx%d',
                        frame, idx, len(frameList), offsetX, offsetY)
                    lastlog = time.time()
                else:
                    self.logger.debug(
                        'Tiling frame %d (%d/%d), offset %dx%d',
                        frame, idx, len(frameList), offsetX, offsetY)
                if tiled:
                    tiledimage = utilities._addRegionTileToTiled(
                        tiledimage, cast(np.ndarray, subimage), offsetX,
                        offsetY, outWidth, outHeight, tile, **kwargs)
                else:
                    image = utilities._addSubimageToImage(
                        image, cast(np.ndarray, subimage), offsetX, offsetY,
                        outWidth, outHeight)
        if tiled:
            return self._encodeTiledImage(
                cast(Dict[str, Any], tiledimage), outWidth, outHeight, tileIter.info, **kwargs)
        return utilities._encodeImage(cast(np.ndarray, image), format=format, **kwargs)

    def getRegionAtAnotherScale(
            self, sourceRegion: Dict[str, Any],
            sourceScale: Optional[Dict[str, float]] = None,
            targetScale: Optional[Dict[str, float]] = None,
            targetUnits: Optional[str] = None, **kwargs) -> Tuple[
                Union[np.ndarray, PIL.Image.Image, ImageBytes, bytes, pathlib.Path], str]:
        """
        This takes the same parameters and returns the same results as
        getRegion, except instead of region and scale, it takes sourceRegion,
        sourceScale, targetScale, and targetUnits.  These parameters are the
        same as convertRegionScale.  See those two functions for parameter
        definitions.
        """
        for key in ('region', 'scale'):
            if key in kwargs:
                raise TypeError('getRegionAtAnotherScale() got an unexpected '
                                'keyword argument of "%s"' % key)
        region = self.convertRegionScale(sourceRegion, sourceScale,
                                         targetScale, targetUnits)
        return self.getRegion(region=region, scale=targetScale, **kwargs)

    def getPointAtAnotherScale(
            self, point: Tuple[float, float],
            sourceScale: Optional[Dict[str, float]] = None,
            sourceUnits: Optional[str] = None,
            targetScale: Optional[Dict[str, float]] = None,
            targetUnits: Optional[str] = None, **kwargs) -> Tuple[float, float]:
        """
        Given a point as a (x, y) tuple, convert it from one scale to another.
        The sourceScale, sourceUnits, targetScale, and targetUnits parameters
        are the same as convertRegionScale, where sourceUnits are the units
        used with sourceScale.
        """
        sourceRegion = {
            'units': 'base_pixels' if sourceUnits is None else sourceUnits,
            'left': point[0],
            'top': point[1],
            'right': point[0],
            'bottom': point[1],
        }
        region = self.convertRegionScale(
            sourceRegion, sourceScale, targetScale, targetUnits,
            cropToImage=False)
        return (region['left'], region['top'])

    def getNativeMagnification(self) -> Dict[str, Optional[float]]:
        """
        Get the magnification for the highest-resolution level.

        :return: magnification, width of a pixel in mm, height of a pixel in mm.
        """
        return {
            'magnification': None,
            'mm_x': None,
            'mm_y': None,
        }

    def getMagnificationForLevel(self, level: Optional[float] = None) -> Dict[str, Optional[float]]:
        """
        Get the magnification at a particular level.

        :param level: None to use the maximum level, otherwise the level to get
            the magnification factor of.
        :return: magnification, width of a pixel in mm, height of a pixel in mm.
        """
        mag = self.getNativeMagnification()

        if level is not None and self.levels and level != self.levels - 1:
            mag['scale'] = 2.0 ** (self.levels - 1 - level)
            if mag['magnification']:
                mag['magnification'] /= cast(float, mag['scale'])
            if mag['mm_x'] and mag['mm_y']:
                mag['mm_x'] *= cast(float, mag['scale'])
                mag['mm_y'] *= cast(float, mag['scale'])
        if self.levels:
            mag['level'] = level if level is not None else self.levels - 1
            if mag.get('level') == self.levels - 1:
                mag['scale'] = 1.0
        return mag

    def getLevelForMagnification(
        self, magnification: Optional[float] = None, exact: bool = False,
        mm_x: Optional[float] = None, mm_y: Optional[float] = None,
        rounding: Optional[Union[str, bool]] = 'round', **kwargs,
    ) -> Optional[Union[int, float]]:
        """
        Get the level for a specific magnification or pixel size.  If the
        magnification is unknown or no level is sufficient resolution, and an
        exact match is not requested, the highest level will be returned.

        If none of magnification, mm_x, and mm_y are specified, the maximum
        level is returned.  If more than one of these values is given, an
        average of those given will be used (exact will require all of them to
        match).

        :param magnification: the magnification ratio.
        :param exact: if True, only a level that matches exactly will be
            returned.
        :param mm_x: the horizontal size of a pixel in millimeters.
        :param mm_y: the vertical size of a pixel in millimeters.
        :param rounding: if False, a fractional level may be returned.  If
            'ceil' or 'round', that function is used to convert the level to an
            integer (the exact flag still applies).  If None, the level is not
            cropped to the actual image's level range.
        :returns: the selected level or None for no match.
        """
        mag = self.getMagnificationForLevel()
        ratios = []
        if magnification and mag['magnification']:
            ratios.append(float(magnification) / mag['magnification'])
        if mm_x and mag['mm_x']:
            ratios.append(mag['mm_x'] / mm_x)
        if mm_y and mag['mm_y']:
            ratios.append(mag['mm_y'] / mm_y)
        ratios = [math.log(ratio) / math.log(2) for ratio in ratios]
        # Perform some slight rounding to handle numerical precision issues
        ratios = [round(ratio, 4) for ratio in ratios]
        if not len(ratios):
            return mag.get('level', 0)
        if exact:
            if any(int(ratio) != ratio or ratio != ratios[0]
                   for ratio in ratios):
                return None
        ratio = round(sum(ratios) / len(ratios), 4)
        level = (mag['level'] or 0) + ratio
        if rounding:
            level = int(math.ceil(level) if rounding == 'ceil' else
                        round(level))
        if (exact and (level > (mag['level'] or 0) or level < 0) or
                (rounding == 'ceil' and level > (mag['level'] or 0))):
            return None
        if rounding is not None:
            level = max(0, min(mag['level'] or 0, level))
        return level

    def tileIterator(
            self, format: Union[str, Tuple[str]] = (TILE_FORMAT_NUMPY, ),
            resample: bool = True, **kwargs) -> Iterator[LazyTileDict]:
        """
        Iterate on all tiles in the specified region at the specified scale.
        Each tile is returned as part of a dictionary that includes

            :x, y: (left, top) coordinates in current magnification pixels
            :width, height: size of current tile in current magnification pixels
            :tile: cropped tile image
            :format: format of the tile
            :level: level of the current tile
            :level_x, level_y: the tile reference number within the level.
                Tiles are numbered (0, 0), (1, 0), (2, 0), etc.  The 0th tile
                yielded may not be (0, 0) if a region is specified.
            :tile_position: a dictionary of the tile position within the
                iterator, containing:

                :level_x, level_y: the tile reference number within the level.
                :region_x, region_y: 0, 0 is the first tile in the full
                    iteration (when not restricting the iteration to a single
                    tile).
                :position: a 0-based value for the tile within the full
                    iteration.

            :iterator_range: a dictionary of the output range of the iterator:

                :level_x_min, level_x_max: the tiles that are be included
                    during the full iteration: [layer_x_min, layer_x_max).
                :level_y_min, level_y_max: the tiles that are be included
                    during the full iteration: [layer_y_min, layer_y_max).
                :region_x_max, region_y_max: the number of tiles included during
                    the full iteration.   This is layer_x_max - layer_x_min,
                    layer_y_max - layer_y_min.
                :position: the total number of tiles included in the full
                    iteration.  This is region_x_max * region_y_max.

            :magnification: magnification of the current tile
            :mm_x, mm_y: size of the current tile pixel in millimeters.
            :gx, gy: (left, top) coordinates in maximum-resolution pixels
            :gwidth, gheight: size of of the current tile in maximum-resolution
                pixels.
            :tile_overlap: the amount of overlap with neighboring tiles (left,
                top, right, and bottom).  Overlap never extends outside of the
                requested region.

        If a region that includes partial tiles is requested, those tiles are
        cropped appropriately.  Most images will have tiles that get cropped
        along the right and bottom edges in any case.  If an exact
        magnification or scale is requested, no tiles will be returned.

        :param format: the desired format or a tuple of allowed formats.
            Formats are members of (TILE_FORMAT_PIL, TILE_FORMAT_NUMPY,
            TILE_FORMAT_IMAGE).  If TILE_FORMAT_IMAGE, encoding must be
            specified.
        :param resample: If True or one of PIL.Image.Resampling.NEAREST,
            LANCZOS, BILINEAR, or BICUBIC to resample tiles that are not the
            target output size.  Tiles that are resampled will have additional
            dictionary entries of:

            :scaled: the scaling factor that was applied (less than 1 is
                downsampled).
            :tile_x, tile_y: (left, top) coordinates before scaling
            :tile_width, tile_height: size of the current tile before
                scaling.
            :tile_magnification: magnification of the current tile before
                scaling.
            :tile_mm_x, tile_mm_y: size of a pixel in a tile in millimeters
                before scaling.

            Note that scipy.misc.imresize uses PIL internally.
        :param region: a dictionary of optional values which specify the part
            of the image to process:

            :left: the left edge (inclusive) of the region to process.
            :top: the top edge (inclusive) of the region to process.
            :right: the right edge (exclusive) of the region to process.
            :bottom: the bottom edge (exclusive) of the region to process.
            :width: the width of the region to process.
            :height: the height of the region to process.
            :units: either 'base_pixels' (default), 'pixels', 'mm', or
                'fraction'.  base_pixels are in maximum resolution pixels.
                pixels is in the specified magnification pixels.  mm is in the
                specified magnification scale.  fraction is a scale of 0 to 1.
                pixels and mm are only available if the magnification and mm
                per pixel are defined for the image.

        :param output: a dictionary of optional values which specify the size
            of the output.

            :maxWidth: maximum width in pixels.  If either maxWidth or maxHeight
                is specified, magnification, mm_x, and mm_y are ignored.
            :maxHeight: maximum height in pixels.

        :param scale: a dictionary of optional values which specify the scale
            of the region and / or output.  This applies to region if
            pixels or mm are used for inits.  It applies to output if
            neither output maxWidth nor maxHeight is specified.

            :magnification: the magnification ratio.  Only used if maxWidth and
                maxHeight are not specified or None.
            :mm_x: the horizontal size of a pixel in millimeters.
            :mm_y: the vertical size of a pixel in millimeters.
            :exact: if True, only a level that matches exactly will be returned.
                This is only applied if magnification, mm_x, or mm_y is used.

        :param tile_position: if present, either a number to only yield the
            (tile_position)th tile [0 to (xmax - min) * (ymax - ymin)) that the
            iterator would yield, or a dictionary of {region_x, region_y} to
            yield that tile, where 0, 0 is the first tile yielded, and
            xmax - xmin - 1, ymax - ymin - 1 is the last tile yielded, or a
            dictionary of {level_x, level_y} to yield that specific tile if it
            is in the region.
        :param tile_size: if present, retile the output to the specified tile
            size.  If only width or only height is specified, the resultant
            tiles will be square.  This is a dictionary containing at least
            one of:

            :width: the desired tile width.
            :height: the desired tile height.

        :param tile_overlap: if present, retile the output adding a symmetric
            overlap to the tiles.  If either x or y is not specified, it
            defaults to zero.  The overlap does not change the tile size,
            only the stride of the tiles.  This is a dictionary containing:

            :x: the horizontal overlap in pixels.
            :y: the vertical overlap in pixels.
            :edges: if True, then the edge tiles will exclude the overlap
                distance.  If unset or False, the edge tiles are full size.

                The overlap is conceptually split between the two sides of
                the tile.  This is only relevant to where overlap is reported
                or if edges is True

                As an example, suppose an image that is 8 pixels across
                (01234567) and a tile size of 5 is requested with an overlap of
                4.  If the edges option is False (the default), the following
                tiles are returned: 01234, 12345, 23456, 34567.  Each tile
                reports its overlap, and the non-overlapped area of each tile
                is 012, 3, 4, 567.  If the edges option is True, the tiles
                returned are: 012, 0123, 01234, 12345, 23456, 34567, 4567, 567,
                with the non-overlapped area of each as 0, 1, 2, 3, 4, 5, 6, 7.

        :param tile_offset: if present, adjust tile positions so that the
            corner of one tile is at the specified location.

            :left: the left offset in pixels.
            :top: the top offset in pixels.
            :auto: a boolean, if True, automatically set the offset to align
                with the region's left and top.

        :param encoding: if format includes TILE_FORMAT_IMAGE, a valid PIL
            encoding (typically 'PNG', 'JPEG', or 'TIFF') or 'TILED' (identical
            to TIFF).  Must also be in the TileOutputMimeTypes map.
        :param jpegQuality: the quality to use when encoding a JPEG.
        :param jpegSubsampling: the subsampling level to use when encoding a
            JPEG.
        :param tiffCompression: the compression format when encoding a TIFF.
            This is usually 'raw', 'tiff_lzw', 'jpeg', or 'tiff_adobe_deflate'.
            Some of these are aliased: 'none', 'lzw', 'deflate'.
        :param frame: the frame number within the tile source.  None is the
            same as 0 for multi-frame sources.
        :param kwargs: optional arguments.
        :yields: an iterator that returns a dictionary as listed above.
        """
        return TileIterator(self, format=format, resample=resample, **kwargs)

    def tileIteratorAtAnotherScale(
            self, sourceRegion: Dict[str, Any],
            sourceScale: Optional[Dict[str, float]] = None,
            targetScale: Optional[Dict[str, float]] = None,
            targetUnits: Optional[str] = None, **kwargs) -> Iterator[LazyTileDict]:
        """
        This takes the same parameters and returns the same results as
        tileIterator, except instead of region and scale, it takes
        sourceRegion, sourceScale, targetScale, and targetUnits.  These
        parameters are the same as convertRegionScale.  See those two functions
        for parameter definitions.
        """
        for key in ('region', 'scale'):
            if key in kwargs:
                raise TypeError('getRegionAtAnotherScale() got an unexpected '
                                'keyword argument of "%s"' % key)
        region = self.convertRegionScale(sourceRegion, sourceScale,
                                         targetScale, targetUnits)
        return self.tileIterator(region=region, scale=targetScale, **kwargs)

    def getSingleTile(self, *args, **kwargs) -> Optional[LazyTileDict]:
        """
        Return any single tile from an iterator.  This takes exactly the same
        parameters as tileIterator.  Use tile_position to get a specific tile,
        otherwise the first tile is returned.

        :return: a tile dictionary or None.
        """
        return next(self.tileIterator(*args, **kwargs), None)

    def getSingleTileAtAnotherScale(self, *args, **kwargs) -> Optional[LazyTileDict]:
        """
        Return any single tile from a rescaled iterator.  This takes exactly
        the same parameters as tileIteratorAtAnotherScale.  Use tile_position
        to get a specific tile, otherwise the first tile is returned.

        :return: a tile dictionary or None.
        """
        return next(self.tileIteratorAtAnotherScale(*args, **kwargs), None)

    def getTileCount(self, *args, **kwargs) -> int:
        """
        Return the number of tiles that the tileIterator will return.  See
        tileIterator for parameters.

        :return: the number of tiles that the tileIterator will yield.
        """
        tile = next(self.tileIterator(*args, **kwargs), None)
        if tile is not None:
            return tile['iterator_range']['position']
        return 0

    def getAssociatedImagesList(self) -> List[str]:
        """
        Return a list of associated images.

        :return: the list of image keys.
        """
        return []

    def getAssociatedImage(
            self, imageKey: str, *args, **kwargs) -> Optional[Tuple[ImageBytes, str]]:
        """
        Return an associated image.

        :param imageKey: the key of the associated image to retrieve.
        :param kwargs: optional arguments.  Some options are width, height,
            encoding, jpegQuality, jpegSubsampling, and tiffCompression.
        :returns: imageData, imageMime: the image data and the mime type, or
            None if the associated image doesn't exist.
        """
        image = self._getAssociatedImage(imageKey)
        if not image:
            return None
        imageWidth, imageHeight = image.size
        width = kwargs.get('width')
        height = kwargs.get('height')
        if width or height:
            width, height, calcScale = utilities._calculateWidthHeight(
                width, height, imageWidth, imageHeight)
            image = image.resize(
                (width, height),
                getattr(PIL.Image, 'Resampling', PIL.Image).BICUBIC
                if width > imageWidth else
                getattr(PIL.Image, 'Resampling', PIL.Image).LANCZOS)
        return cast(Tuple[ImageBytes, str], utilities._encodeImage(image, **kwargs))

    def getPixel(self, includeTileRecord: bool = False, **kwargs) -> JSONDict:
        """
        Get a single pixel from the current tile source.

        :param includeTileRecord: if True, include the tile used for computing
            the pixel in the response.
        :param kwargs: optional arguments.  Some options are region, output,
            encoding, jpegQuality, jpegSubsampling, tiffCompression, fill.  See
            tileIterator.
        :returns: a dictionary with the value of the pixel for each channel on
            a scale of [0-255], including alpha, if available.  This may
            contain additional information.
        """
        regionArgs = kwargs.copy()
        regionArgs['region'] = regionArgs.get('region', {}).copy()
        regionArgs['region']['width'] = regionArgs['region']['height'] = 1
        regionArgs['region']['unitsWH'] = 'base_pixels'
        pixel: Dict[str, Any] = {}
        # This could be
        #  img, format = self.getRegion(format=TILE_FORMAT_PIL, **regionArgs)
        # where img is the PIL image (rather than tile['tile'], but using
        # TileIterator is slightly more efficient.
        tile = next(TileIterator(self, format=TILE_FORMAT_NUMPY, **regionArgs), None)
        if tile is None:
            return JSONDict(pixel)
        if includeTileRecord:
            pixel['tile'] = tile
        pixel['value'] = [v.item() for v in tile['tile'][0][0]]
        img = _imageToPIL(tile['tile'])
        if img.size[0] >= 1 and img.size[1] >= 1:
            if len(img.mode) > 1:
                pixel.update(dict(zip(img.mode.lower(), img.load()[0, 0])))
            else:
                pixel.update(dict(zip([img.mode.lower()], [img.load()[0, 0]])))
        return JSONDict(pixel)

    @property
    def frames(self) -> int:
        """A property with the number of frames."""
        if not hasattr(self, '_frameCount'):
            self._frameCount = len(self.getMetadata().get('frames', [])) or 1
        return self._frameCount


class FileTileSource(TileSource):

    def __init__(
            self, path: Union[str, pathlib.Path, Dict[Any, Any]], *args, **kwargs) -> None:
        """
        Initialize the tile class.  See the base class for other available
        parameters.

        :param path: a filesystem path for the tile source.
        """
        super().__init__(*args, **kwargs)
        # Expand the user without converting datatype of path.
        try:
            path = (cast(pathlib.Path, path).expanduser()
                    if callable(getattr(path, 'expanduser', None)) else
                    os.path.expanduser(cast(str, path)))
        except TypeError:
            # Don't fail if the path is unusual -- maybe a source can handle it
            pass
        self.largeImagePath = path

    @staticmethod
    def getLRUHash(*args, **kwargs) -> str:
        return strhash(
            args[0], kwargs.get('encoding', 'JPEG'), kwargs.get('jpegQuality', 95),
            kwargs.get('jpegSubsampling', 0), kwargs.get('tiffCompression', 'raw'),
            kwargs.get('edge', False),
            '__STYLESTART__', kwargs.get('style', None), '__STYLEEND__')

    def getState(self) -> str:
        if hasattr(self, '_classkey'):
            return self._classkey
        return '%s,%s,%s,%s,%s,%s,__STYLESTART__,%s,__STYLE_END__' % (
            self._getLargeImagePath(),
            self.encoding,
            self.jpegQuality,
            self.jpegSubsampling,
            self.tiffCompression,
            self.edge,
            self._jsonstyle)

    def _getLargeImagePath(self) -> Union[str, pathlib.Path, Dict[Any, Any]]:
        return self.largeImagePath

    @classmethod
    def canRead(cls, path: Union[str, pathlib.Path, Dict[Any, Any]], *args, **kwargs) -> bool:
        """
        Check if we can read the input.  This takes the same parameters as
        __init__.

        :returns: True if this class can read the input.  False if it
                  cannot.
        """
        try:
            cls(path, *args, **kwargs)
            return True
        except exceptions.TileSourceError:
            return False
