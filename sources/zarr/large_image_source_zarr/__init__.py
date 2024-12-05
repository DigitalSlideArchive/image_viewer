import math
import multiprocessing
import os
import shutil
import tempfile
import threading
import uuid
import warnings
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _importlib_version
from pathlib import Path

import numpy as np
import packaging.version

import large_image
from large_image.cache_util import LruCacheMetaclass, methodcache
from large_image.constants import NEW_IMAGE_PATH_FLAG, TILE_FORMAT_NUMPY, SourcePriority
from large_image.exceptions import TileSourceError, TileSourceFileNotFoundError
from large_image.tilesource import FileTileSource
from large_image.tilesource.resample import ResampleMethod, downsampleTileHalfRes
from large_image.tilesource.utilities import _imageToNumpy, nearPowerOfTwo

try:
    __version__ = _importlib_version(__name__)
except PackageNotFoundError:
    # package is not installed
    pass


zarr = None


def _lazyImport():
    """
    Import the zarr module.  This is done when needed rather than in the module
    initialization because it is slow.
    """
    global zarr

    if zarr is None:
        try:
            import zarr

            warnings.filterwarnings('ignore', category=FutureWarning, module='.*zarr.*')
        except ImportError:
            msg = 'zarr module not found.'
            raise TileSourceError(msg)


class ZarrFileTileSource(FileTileSource, metaclass=LruCacheMetaclass):
    """
    Provides tile access to files that the zarr library can read.
    """

    cacheName = 'tilesource'
    name = 'zarr'
    extensions = {
        None: SourcePriority.LOW,
        'zarr': SourcePriority.PREFERRED,
        'zgroup': SourcePriority.PREFERRED,
        'zattrs': SourcePriority.PREFERRED,
        'zarray': SourcePriority.PREFERRED,
        'db': SourcePriority.MEDIUM,
        'zip': SourcePriority.LOWER,
    }
    mimeTypes = {
        None: SourcePriority.FALLBACK,
        'application/zip+zarr': SourcePriority.PREFERRED,
        'application/vnd+zarr': SourcePriority.PREFERRED,
        'application/x-zarr': SourcePriority.PREFERRED,
    }
    newPriority = SourcePriority.HIGH

    _tileSize = 512
    _minTileSize = 128
    _maxTileSize = 1024
    _minAssociatedImageSize = 64
    _maxAssociatedImageSize = 8192

    def __init__(self, path, **kwargs):
        """
        Initialize the tile class.  See the base class for other available
        parameters.

        :param path: a filesystem path for the tile source.
        """
        super().__init__(path, **kwargs)

        _lazyImport()
        if str(path).startswith(NEW_IMAGE_PATH_FLAG):
            self._initNew(path, **kwargs)
        else:
            self._initOpen(**kwargs)
        self._tileLock = threading.RLock()

    def _initOpen(self, **kwargs):
        self._largeImagePath = str(self._getLargeImagePath())
        self._zarr = None
        self._editable = False
        self._frameValues = None
        self._frameAxes = None
        self._frameUnits = None
        if not os.path.isfile(self._largeImagePath) and '//:' not in self._largeImagePath:
            raise TileSourceFileNotFoundError(self._largeImagePath) from None
        try:
            self._zarr = zarr.open(zarr.SQLiteStore(self._largeImagePath), mode='r')
        except Exception:
            try:
                self._zarr = zarr.open(self._largeImagePath, mode='r')
            except Exception:
                if os.path.basename(self._largeImagePath) in {'.zgroup', '.zattrs', '.zarray'}:
                    try:
                        self._zarr = zarr.open(os.path.dirname(self._largeImagePath), mode='r')
                    except Exception:
                        pass
        if self._zarr is None:
            if not os.path.isfile(self._largeImagePath):
                raise TileSourceFileNotFoundError(self._largeImagePath) from None
            msg = 'File cannot be opened via zarr.'
            raise TileSourceError(msg)
        try:
            self._validateZarr()
        except TileSourceError:
            raise
        except Exception:
            msg = 'File cannot be opened -- not an OME NGFF file or understandable zarr file.'
            raise TileSourceError(msg)

    def _initNew(self, path, **kwargs):
        """
        Initialize the tile class for creating a new image.
        """
        self._tempdir = Path(tempfile.gettempdir(), path)
        self._created = False
        if not self._tempdir.exists():
            self._created = True
        self._zarr_store = zarr.DirectoryStore(str(self._tempdir))
        self._zarr = zarr.open(self._zarr_store, mode='a')
        self._largeImagePath = None
        self._dims = {}
        self.sizeX = self.sizeY = self.levels = 0
        self.tileWidth = self.tileHeight = self._tileSize
        self._cacheValue = str(uuid.uuid4())
        self._output = None
        self._editable = True
        self._bandRanges = None
        self._threadLock = threading.RLock()
        self._processLock = multiprocessing.Lock()
        self._framecount = 0
        self._mm_x = 0
        self._mm_y = 0
        self._channelNames = []
        self._channelColors = []
        self._imageDescription = None
        self._levels = []
        self._associatedImages = {}
        self._frameValues = None
        self._frameAxes = None
        self._frameUnits = None

    def __del__(self):
        if not hasattr(self, '_derivedSource'):
            try:
                self._zarr.close()
            except Exception:
                pass
            try:
                if self._created:
                    shutil.rmtree(self._tempdir)
            except Exception:
                pass

    def _checkEditable(self):
        """
        Raise an exception if this is not an editable image.
        """
        if not self._editable:
            msg = 'Not an editable image'
            raise TileSourceError(msg)

    def _getGeneralAxes(self, arr):
        """
        Examine a zarr array an guess what the axes are.  We assume the two
        maximal dimensions are y, x.  Then, if there is a dimension that is 3
        or 4 in length, it is channels.  If there is more than one other that
        is not 1, we don't know how it is sorted, so we will fail.

        :param arr: a zarr array.
        :return: a dictionary of axes with the axis as the key and the index
            within the array axes as the value.
        """
        shape = arr.shape
        maxIndex = shape.index(max(shape))
        secondMaxIndex = shape.index(max(x for idx, x in enumerate(shape) if idx != maxIndex))
        axes = {
            'x': max(maxIndex, secondMaxIndex),
            'y': min(maxIndex, secondMaxIndex),
        }
        for idx, val in enumerate(shape):
            if idx not in axes.values() and val == 4 and 'c' not in axes:
                axes['c'] = idx
            if idx not in axes.values() and val == 3:
                axes['c'] = idx
        for idx, val in enumerate(shape):
            if idx not in axes.values() and val > 1:
                if 'f' in axes:
                    msg = 'Too many large axes'
                    raise TileSourceError(msg)
                axes['f'] = idx
        return axes

    def _scanZarrArray(self, group, arr, results):
        """
        Scan a zarr array and determine if is the maximal dimension array we
        can read.  If so, update a results dictionary with the information.  If
        it is the shape as a previous maximum, append it as a multi-series set.
        If not, and it is small enough, add it to a list of possible associated
        images.

        :param group: a zarr group; the parent of the array.
        :param arr: a zarr array.
        :param results: a dictionary to store the results.  'best' contains a
            tuple that is used to find the maximum size array, preferring ome
            arrays, then total pixels, then channels.  'is_ome' is a boolean.
            'series' is a list of the found groups and arrays that match the
            best criteria.  'axes', 'axes_values', 'axes_units', and 'channels'
            are from the best array. 'associated' is a list of all groups and
            arrays that might be associated images.  These have to be culled
            for the actual groups used in the series.
        """
        attrs = group.attrs.asdict() if group is not None else {}
        min_version = packaging.version.Version('0.4')
        is_ome = (
            isinstance(attrs.get('multiscales', None), list) and
            'omero' in attrs and
            isinstance(attrs['omero'], dict) and
            all(isinstance(m, dict) for m in attrs['multiscales']) and
            all(packaging.version.Version(m['version']) >= min_version
                for m in attrs['multiscales'] if 'version' in m))
        channels = None
        axes_values = None
        axes_units = None
        if is_ome:
            axes = {axis['name']: idx for idx, axis in enumerate(
                attrs['multiscales'][0]['axes'])}
            axes_values = {
                axis['name']: axis.get('values')
                for axis in attrs['multiscales'][0]['axes']
            }
            axes_units = {
                axis['name']: axis.get('unit')
                for axis in attrs['multiscales'][0]['axes']
            }
            if isinstance(attrs['omero'].get('channels'), list):
                channels = [channel['label'] for channel in attrs['omero']['channels']]
                if all(channel.startswith('Channel ') for channel in channels):
                    channels = None
        else:
            try:
                axes = self._getGeneralAxes(arr)
            except TileSourceError:
                return
        if 'x' not in axes or 'y' not in axes:
            return
        check = (is_ome, math.prod(arr.shape), channels is not None,
                 tuple(axes.keys()), tuple(channels) if channels else ())
        if results['best'] is None or check > results['best']:
            results['best'] = check
            results['series'] = [(group, arr)]
            results['is_ome'] = is_ome
            results['axes'] = axes
            results['axes_values'] = axes_values
            results['axes_units'] = axes_units
            results['channels'] = channels
        elif check == results['best']:
            results['series'].append((group, arr))
        if not any(group is g for g, _ in results['associated']):
            axes = {k: v for k, v in axes.items() if arr.shape[axes[k]] > 1}
            if (len(axes) <= 3 and
                    self._minAssociatedImageSize <= arr.shape[axes['x']] <=
                    self._maxAssociatedImageSize and
                    self._minAssociatedImageSize <= arr.shape[axes['y']] <=
                    self._maxAssociatedImageSize and
                    (len(axes) == 2 or ('c' in axes and arr.shape[axes['c']] in {1, 3, 4}))):
                results['associated'].append((group, arr))

    def _scanZarrGroup(self, group, results=None):
        """
        Scan a zarr group for usable arrays.

        :param group: a zarr group
        :param results: a results dicitionary, updated.
        :returns: the results dictionary.
        """
        if results is None:
            results = {'best': None, 'series': [], 'associated': []}
        if isinstance(group, zarr.core.Array):
            self._scanZarrArray(None, group, results)
            return results
        for val in group.values():
            if isinstance(val, zarr.core.Array):
                self._scanZarrArray(group, val, results)
            elif isinstance(val, zarr.hierarchy.Group):
                results = self._scanZarrGroup(val, results)
        return results

    def _zarrFindLevels(self):
        """
        Find usable multi-level images.  This checks that arrays are nearly a
        power of two.  This updates self._levels and self._populatedLevels.
        self._levels is an array the same length as the number of series, each
        entry of which is an array of the number of conceptual tile levels
        where each entry of that is either the zarr array that can be used to
        get pixels or None if it is not populated.
        """
        levels = [[None] * self.levels for _ in self._series]
        baseGroup, baseArray = self._series[0]
        for idx, (_, arr) in enumerate(self._series):
            levels[idx][0] = arr
        arrs = [[arr for _, arr in s.arrays()] if s is not None else [a] for s, a in self._series]
        for idx, arr in enumerate(arrs[0]):
            if any(idx >= len(sarrs) for sarrs in arrs[1:]):
                break
            if any(arr.shape != sarrs[idx].shape for sarrs in arrs[1:]):
                continue
            if (nearPowerOfTwo(self.sizeX, arr.shape[self._axes['x']]) and
                    nearPowerOfTwo(self.sizeY, arr.shape[self._axes['y']])):
                level = int(round(math.log(self.sizeX / arr.shape[self._axes['x']]) / math.log(2)))
                if level < self.levels and levels[0][level] is None:
                    for sidx in range(len(self._series)):
                        levels[sidx][level] = arrs[sidx][idx]
        self._levels = levels
        self._populatedLevels = len([l for l in self._levels[0] if l is not None])
        # TODO: check for inefficient file and raise warning

    def _getScale(self):
        """
        Get the scale values from the ome metadata and populate the class
        values for _mm_x and _mm_y.
        """
        unit = {'micrometer': 1e-3, 'millimeter': 1, 'meter': 1e3}
        self._mm_x = self._mm_y = None
        baseGroup, baseArray = self._series[0]
        try:
            ms = baseGroup.attrs.asdict()['multiscales'][0]
            self._mm_x = ms['datasets'][0]['coordinateTransformations'][0][
                'scale'][self._axes['x']] * unit[ms['axes'][self._axes['x']]['unit']]
            self._mm_y = ms['datasets'][0]['coordinateTransformations'][0][
                'scale'][self._axes['y']] * unit[ms['axes'][self._axes['y']]['unit']]
        except Exception:
            pass

    def _readFrameValues(self, found, baseArray):
        """
        Populate frame values and frame units from image metadata.
        """
        axes_values = found.get('axes_values')
        axes_units = found.get('axes_units')
        if isinstance(axes_values, dict):
            self._frameAxes = [
                a for a, i in sorted(self._axes.items(), key=lambda x: x[1])
                if axes_values.get(a) is not None
            ]
            self._frameUnits = {k: axes_units.get(k) for k in self.frameAxes if k in axes_units}
            frame_values_shape = [baseArray.shape[self._axes[a]] for a in self.frameAxes]
            frame_values_shape.append(len(frame_values_shape))
            frame_values = np.empty(frame_values_shape, dtype=object)
            all_frame_specs = self.getMetadata().get('frames')
            for axis, values in axes_values.items():
                if axis in self.frameAxes:
                    slicing = [slice(None) for i in range(len(frame_values_shape))]
                    axis_index = self.frameAxes.index(axis)
                    slicing[-1] = axis_index
                    if len(values) == frame_values_shape[axis_index]:
                        # uniform values have same length as axis
                        for i, value in enumerate(values):
                            slicing[axis_index] = i
                            frame_values[tuple(slicing)] = value
                    elif len(values) == self._framecount:
                        # non-uniform values have a value for every frame
                        for i, value in enumerate(values):
                            if all_frame_specs and len(all_frame_specs) > i:
                                for k, j in all_frame_specs[i].items():
                                    if 'Index' in k:
                                        name = k.replace('Index', '').lower()
                                        if name:
                                            slicing[self._frameAxes.index(name)] = j
                            frame_values[tuple(slicing)] = value
            self._frameValues = frame_values

    def _validateZarr(self):
        """
        Validate that we can read tiles from the zarr parent group in
        self._zarr.  Set up the appropriate class variables.
        """
        if self._editable and hasattr(self, '_axes'):
            self._writeInternalMetadata()
        found = self._scanZarrGroup(self._zarr)
        if found['best'] is None:
            msg = 'No data array that can be used.'
            raise TileSourceError(msg)
        self._series = found['series']
        baseGroup, baseArray = self._series[0]
        self._is_ome = found['is_ome']
        self._axes = {
            k.lower(): v
            for k, v in found['axes'].items()
            if baseArray.shape[v] > 1 or k in found.get('axes_values', {})
        }
        if len(self._series) > 1 and 'xy' in self._axes:
            msg = 'Conflicting xy axis data.'
            raise TileSourceError(msg)
        self._channels = found['channels']
        self._associatedImages = {
            g.name.replace('/', ''): (g, a)
            for g, a in found['associated'] if not any(g is gb for gb, _ in self._series)
        }
        self.sizeX = baseArray.shape[self._axes['x']]
        self.sizeY = baseArray.shape[self._axes['y']]
        self.tileWidth = (
            baseArray.chunks[self._axes['x']]
            if self._minTileSize <= baseArray.chunks[self._axes['x']] <= self._maxTileSize else
            self._tileSize)
        self.tileHeight = (
            baseArray.chunks[self._axes['y']]
            if self._minTileSize <= baseArray.chunks[self._axes['y']] <= self._maxTileSize else
            self._tileSize)
        # If we wanted to require equal tile width and height:
        # self.tileWidth = self.tileHeight = self._tileSize
        # if (baseArray.chunks[self._axes['x']] == baseArray.chunks[self._axes['y']] and
        #         self._minTileSize <= baseArray.chunks[self._axes['x']] <= self._maxTileSize):
        #     self.tileWidth = self.tileHeight = baseArray.chunks[self._axes['x']]
        self.levels = int(max(1, math.ceil(math.log(max(
            self.sizeX / self.tileWidth, self.sizeY / self.tileHeight)) / math.log(2)) + 1))
        self._dtype = np.dtype(baseArray.dtype)
        self._bandCount = 1
        if ('c' in self._axes and 's' not in self._axes and not self._channels and
                baseArray.shape[self._axes.get('c')] in {1, 3, 4}):
            self._bandCount = baseArray.shape[self._axes['c']]
            self._axes['s'] = self._axes.pop('c')
        elif 's' in self._axes:
            self._bandCount = baseArray.shape[self._axes['s']]
        self._zarrFindLevels()
        self._getScale()
        stride = 1
        self._strides = {}
        self._axisCounts = {}
        for _, k in sorted(
            (-self._axes.get(k, 'tzc'.index(k) if k in 'tzc' else -1), k)
            for k in self._axes if k not in 'xys'
        ):
            self._strides[k] = stride
            self._axisCounts[k] = baseArray.shape[self._axes[k]]
            stride *= baseArray.shape[self._axes[k]]
        if len(self._series) > 1:
            self._strides['xy'] = stride
            self._axisCounts['xy'] = len(self._series)
            stride *= len(self._series)
        self._framecount = stride
        self._readFrameValues(found, baseArray)

    def _nonemptyLevelsList(self, frame=0):
        """
        Return a list of one value per level where the value is None if the
        level does not exist in the file and any other value if it does.

        :param frame: the frame number.
        :returns: a list of levels length.
        """
        return [True if l is not None else None for l in self._levels[0][::-1]]

    def getNativeMagnification(self):
        """
        Get the magnification at a particular level.

        :return: magnification, width of a pixel in mm, height of a pixel in mm.
        """
        mm_x = self._mm_x
        mm_y = self._mm_y
        # Estimate the magnification; we don't have a direct value
        mag = 0.01 / mm_x if mm_x else None
        return {
            'magnification': getattr(self, '_magnification', mag),
            'mm_x': mm_x,
            'mm_y': mm_y,
        }

    def getState(self):
        # Use the _cacheValue to avoid caching the source and tiles if we are
        # creating something new.
        if not hasattr(self, '_cacheValue'):
            return super().getState()
        return super().getState() + ',%s' % (self._cacheValue, )

    def getMetadata(self):
        """
        Return a dictionary of metadata containing levels, sizeX, sizeY,
        tileWidth, tileHeight, magnification, mm_x, mm_y, and frames.

        :returns: metadata dictionary.
        """
        if self._levels is None:
            self._validateZarr()
        result = super().getMetadata()
        if self._framecount > 1:
            result['frames'] = frames = []
            for idx in range(self._framecount):
                frame = {'Frame': idx}
                for axis in self._strides:
                    frame['Index' + axis.upper()] = (
                        idx // self._strides[axis]) % self._axisCounts[axis]
                if self.frameValues is not None and self.frameAxes is not None:
                    current_frame_slice = tuple(
                        frame['Index' + axis.upper()] for axis in self.frameAxes
                    )
                    current_frame_values = self.frameValues[current_frame_slice]
                    for i, axis in enumerate(self.frameAxes):
                        value = current_frame_values[i]
                        # ensure that values are returned as native python types
                        native_value = getattr(value, 'tolist', lambda v=value: v)()
                        frame['Value' + axis.upper()] = native_value
                frames.append(frame)
            self._addMetadataFrameInformation(result, getattr(self, '_channels', None))
        return result

    def getInternalMetadata(self, **kwargs):
        """
        Return additional known metadata about the tile source.  Data returned
        from this method is not guaranteed to be in any particular format or
        have specific values.

        :returns: a dictionary of data or None.
        """
        if self._editable:
            self._writeInternalMetadata()
        result = {}
        result['zarr'] = {
            'base': self._zarr.attrs.asdict(),
        }
        try:
            result['zarr']['main'] = self._series[0][0].attrs.asdict()
        except Exception:
            pass
        return result

    def getAssociatedImagesList(self):
        """
        Get a list of all associated images.

        :return: the list of image keys.
        """
        return list(self._associatedImages.keys())

    def _getAssociatedImage(self, imageKey):
        """
        Get an associated image in PIL format.

        :param imageKey: the key of the associated image.
        :return: the image in PIL format or None.
        """
        if imageKey not in self._associatedImages:
            return
        group, arr = self._associatedImages[imageKey]
        axes = self._getGeneralAxes(arr)
        trans = [idx for idx in range(len(arr.shape))
                 if idx not in axes.values()] + [axes['y'], axes['x']]
        if 'c' in axes or 's' in axes:
            trans.append(axes.get('c', axes.get('s')))
        with self._tileLock:
            img = np.transpose(arr, trans).squeeze()
        if len(img.shape) == 2:
            img.expand_dims(axis=2)
        return large_image.tilesource.base._imageToPIL(img)

    @methodcache()
    def getTile(self, x, y, z, pilImageAllowed=False, numpyAllowed=False, **kwargs):
        if self._levels is None:
            self._validateZarr()

        frame = self._getFrame(**kwargs)
        self._xyzInRange(x, y, z, frame, self._framecount)
        x0, y0, x1, y1, step = self._xyzToCorners(x, y, z)
        sidx = 0 if len(self._series) <= 1 else frame // self._strides['xy']
        targlevel = self.levels - 1 - z
        while targlevel and self._levels[sidx][targlevel] is None:
            targlevel -= 1
        arr = self._levels[sidx][targlevel]
        scale = int(2 ** targlevel)
        x0 //= scale
        y0 //= scale
        x1 //= scale
        y1 //= scale
        step //= scale
        if step > 2 ** self._maxSkippedLevels:
            tile, _format = self._getTileFromEmptyLevel(x, y, z, **kwargs)
            tile = large_image.tilesource.base._imageToNumpy(tile)[0]
        else:
            idx = [slice(None) for _ in arr.shape]
            idx[self._axes['x']] = slice(x0, x1, step)
            idx[self._axes['y']] = slice(y0, y1, step)
            for key in self._axes:
                if key in self._strides:
                    pos = (frame // self._strides[key]) % self._axisCounts[key]
                    idx[self._axes[key]] = slice(pos, pos + 1)
            trans = [idx for idx in range(len(arr.shape))
                     if idx not in {self._axes['x'], self._axes['y'],
                                    self._axes.get('s', self._axes['x'])}]
            squeezeCount = len(trans)
            trans += [self._axes['y'], self._axes['x']]
            if 's' in self._axes:
                trans.append(self._axes['s'])
            with self._tileLock:
                tile = arr[tuple(idx)]
                tile = np.transpose(tile, trans)
            for _ in range(squeezeCount):
                tile = tile.squeeze(0)
            if len(tile.shape) == 2:
                tile = np.expand_dims(tile, axis=2)
        return self._outputTile(tile, TILE_FORMAT_NUMPY, x, y, z,
                                pilImageAllowed, numpyAllowed, **kwargs)

    def _validateNewTile(self, tile, mask, placement, axes):
        if not isinstance(tile, np.ndarray) or axes is None:
            axes = 'yxs'
            tile, mode = _imageToNumpy(tile)
        elif not isinstance(axes, str) and not isinstance(axes, list):
            err = 'Invalid type for axes. Must be str or list[str].'
            raise ValueError(err)
        axes = [x.lower() for x in axes]
        if axes[-1] != 's':
            axes.append('s')
        if mask is not None and len(axes) - 1 == len(mask.shape):
            mask = mask[:, :, np.newaxis]
        if 'x' not in axes or 'y' not in axes:
            err = 'Invalid value for axes. Must contain "y" and "x".'
            raise ValueError(err)
        for k in placement:
            if k not in axes:
                axes[0:0] = [k]
        while len(tile.shape) < len(axes):
            tile = np.expand_dims(tile, axis=0)
        while mask is not None and len(mask.shape) < len(axes):
            mask = np.expand_dims(mask, axis=0)

        return tile, mask, placement, axes

    def addTile(self, tile, x=0, y=0, mask=None, axes=None, **kwargs):
        """
        Add a numpy or image tile to the image, expanding the image as needed
        to accommodate it.  Note that x and y can be negative.  If so, the
        output image (and internal memory access of the image) will act as if
        the 0, 0 point is the most negative position.  Cropping is applied
        after this offset.

        :param tile: a numpy array, PIL Image, or a binary string
            with an image.  The numpy array can have 2 or 3 dimensions.
        :param x: location in destination for upper-left corner.
        :param y: location in destination for upper-left corner.
        :param mask: a 2-d numpy array (or 3-d if the last dimension is 1).
            If specified, areas where the mask is false will not be altered.
        :param axes: a string or list of strings specifying the names of axes
            in the same order as the tile dimensions.
        :param kwargs: start locations for any additional axes.  Note that
            ``level`` is a reserved word and not permitted for an axis name.
        """
        self._checkEditable()
        store_path = str(kwargs.pop('level', 0))
        placement = {
            'x': x,
            'y': y,
            **{k: v for k, v in kwargs.items() if not k.endswith('_value')},
        }
        frame_values = {
            k.replace('_value', ''): v for k, v in kwargs.items()
            if k not in placement
        }
        tile, mask, placement, axes = self._validateNewTile(tile, mask, placement, axes)

        with self._threadLock and self._processLock:
            self._axes = {k: i for i, k in enumerate(axes)}
            new_dims = {
                a: max(
                    self._dims.get(store_path, {}).get(a, 0),
                    placement.get(a, 0) + tile.shape[i],
                )
                for a, i in self._axes.items()
            }
            self._dims[store_path] = new_dims
            placement_slices = tuple([
                slice(placement.get(a, 0), placement.get(a, 0) + tile.shape[i], 1)
                for i, a in enumerate(axes)
            ])

            if len(frame_values.keys()) > 0:
                # update self.frameValues
                self.frameAxes = [
                    a for a in axes
                    if a in frame_values or
                    (self.frameAxes is not None and a in self.frameAxes)
                ]
                frames_shape = [new_dims[a] for a in self.frameAxes]
                frames_shape.append(len(frames_shape))
                if self.frameValues is None:
                    self.frameValues = np.empty(frames_shape, dtype=object)
                elif self.frameValues.shape != frames_shape:
                    self.frameValues = np.pad(
                        self.frameValues,
                        [(0, s - self.frameValues.shape[i]) for i, s in enumerate(frames_shape)],
                    )
                current_frame_slice = tuple(placement.get(a) for a in self.frameAxes)
                for i, k in enumerate(self.frameAxes):
                    self.frameValues[(*current_frame_slice, i)] = frame_values.get(k)

            current_arrays = dict(self._zarr.arrays())
            if store_path == '0':
                # if writing to base data, invalidate generated levels
                for path in current_arrays:
                    if path != store_path:
                        self._zarr_store.rmdir(path)
            chunking = None
            if store_path not in current_arrays:
                arr = np.empty(tuple(new_dims.values()), dtype=tile.dtype)
                chunking = tuple([
                    self._tileSize if a in ['x', 'y'] else
                    new_dims.get('s') if a == 's' else 1
                    for a in axes
                ])
            else:
                arr = current_arrays[store_path]
                new_shape = tuple(max(v, arr.shape[i]) for i, v in enumerate(new_dims.values()))
                if new_shape != arr.shape:
                    arr.resize(*new_shape)
                    if arr.chunks[-1] != new_dims.get('s'):
                        # rechunk if length of samples axis changes
                        chunking = tuple([
                            self._tileSize if a in ['x', 'y'] else
                            new_dims.get('s') if a == 's' else 1
                            for a in axes
                        ])

            if mask is not None:
                arr[placement_slices] = np.where(mask, tile, arr[placement_slices])
            else:
                arr[placement_slices] = tile
            if chunking:
                zarr.array(
                    arr,
                    chunks=chunking,
                    overwrite=True,
                    store=self._zarr_store,
                    path=store_path,
                )

            # If base data changed, update large_image attributes
            if store_path == '0':
                self._dtype = np.dtype(tile.dtype)
                self._bandCount = new_dims.get(axes[-1])  # last axis is assumed to be bands
                self.sizeX = new_dims.get('x')
                self.sizeY = new_dims.get('y')
                self._framecount = math.prod([
                    length
                    for axis, length in new_dims.items()
                    if axis in axes[:-3]
                ])
                self._cacheValue = str(uuid.uuid4())
                self._levels = None
                self.levels = int(max(1, math.ceil(math.log(max(
                    self.sizeX / self.tileWidth, self.sizeY / self.tileHeight)) / math.log(2)) + 1))

    def addAssociatedImage(self, image, imageKey=None):
        """
        Add an associated image to this source.

        :param image: a numpy array, PIL Image, or a binary string
            with an image.  The numpy array can have 2 or 3 dimensions.
        """
        data, _ = _imageToNumpy(image)
        with self._threadLock and self._processLock:
            if imageKey is None:
                # Each associated image should be in its own group
                num_existing = len(self.getAssociatedImagesList())
                imageKey = f'image_{num_existing + 1}'
            group = self._zarr.require_group(imageKey)
            arr = zarr.array(
                data,
                store=self._zarr_store,
                path=f'{imageKey}/image',
            )
            self._associatedImages[imageKey] = (group, arr)

    def _getAxisInternalMetadata(self, axis_name):
        """
        Get the metadata structure describing an axis in the image.
        This will be written to the image metadata.

        :param axis_name: a string corresponding to an axis in the image
        :returns: a dictionary describing the target axis
        """
        axis_metadata = {'name': axis_name}
        if axis_name in ['x', 'y']:
            axis_metadata['type'] = 'space'
            axis_metadata['unit'] = 'millimeter'
        elif axis_name in ['s', 'c']:
            axis_metadata['type'] = 'channel'
        if self.frameAxes is not None:
            axis_index = self.frameAxes.index(axis_name) if axis_name in self.frameAxes else None
            if axis_index is not None and self.frameValues is not None:
                all_frame_values = self.frameValues[..., axis_index]
                split = np.split(
                    all_frame_values,
                    all_frame_values.shape[axis_index],
                    axis=axis_index,
                )
                uniform = all(len(np.unique(
                    # convert all values to strings for mixed type comparison with np.unique
                    (a[np.not_equal(a, None)]).astype(str),
                )) == 1 for a in split)
                if uniform:
                    values = [a.flat[0] for a in split]
                else:
                    values = all_frame_values.flatten().tolist()
                axis_metadata['values'] = values
            unit = self.frameUnits.get(axis_name) if self.frameUnits is not None else None
            if unit is not None:
                axis_metadata['unit'] = unit
        return axis_metadata

    def _writeInternalMetadata(self):
        """
        Write metadata to Zarr attributes.
        Metadata structure adheres to OME schema from https://ngff.openmicroscopy.org/latest/
        """
        self._checkEditable()
        with self._threadLock and self._processLock:
            name = str(self._tempdir.name).split('/')[-1]
            arrays = dict(self._zarr.arrays())
            channel_axis = self._axes.get('c', self._axes.get('s'))
            datasets = []
            axes = []
            channels = []
            rdefs = {'model': 'color' if len(self._channelColors) else 'greyscale'}
            sorted_axes = [a[0] for a in sorted(self._axes.items(), key=lambda item: item[1])]
            for arr_name in arrays:
                level = int(arr_name)
                scale = [1.0 for a in sorted_axes]
                scale[self._axes.get('x')] = (self._mm_x or 0) * (2 ** level)
                scale[self._axes.get('y')] = (self._mm_y or 0) * (2 ** level)
                dataset_metadata = {
                    'path': arr_name,
                    'coordinateTransformations': [{
                        'type': 'scale',
                        'scale': scale,
                    }],
                }
                datasets.append(dataset_metadata)
            for a in sorted_axes:
                if a == 't':
                    rdefs['defaultT'] = 0
                elif a == 'z':
                    rdefs['defaultZ'] = 0
                axes.append(self._getAxisInternalMetadata(a))
            if channel_axis is not None and len(arrays) > 0:
                base_array = list(arrays.values())[0]
                base_shape = base_array.shape
                for c in range(base_shape[channel_axis]):
                    channel_metadata = {
                        'active': True,
                        'coefficient': 1,
                        'color': 'FFFFFF',
                        'family': 'linear',
                        'inverted': False,
                        'label': f'Band {c + 1}',
                    }
                    # slicing = tuple(
                    #     slice(None)
                    #     if k != ('c' if 'c' in self._axes else 's')
                    #     else c
                    #     for k, v in self._axes.items()
                    # )
                    # channel_data = base_array[slicing]
                    # channel_min = np.min(channel_data)
                    # channel_max = np.max(channel_data)
                    # channel_metadata['window'] = {
                    #     'end': channel_max,
                    #     'max': channel_max,
                    #     'min': channel_min,
                    #     'start': channel_min,
                    # }
                    if len(self._channelNames) > c:
                        channel_metadata['label'] = self._channelNames[c]
                    if len(self._channelColors) > c:
                        channel_metadata['color'] = self._channelColors[c]
                    channels.append(channel_metadata)
            # Guidelines from https://ngff.openmicroscopy.org/latest/
            self._zarr.attrs.update({
                'multiscales': [{
                    'version': '0.5',
                    'name': name,
                    'axes': axes,
                    'datasets': datasets,
                    'metadata': {
                        'description': self._imageDescription or '',
                        'kwargs': {
                            'multichannel': (channel_axis is not None),
                        },
                    },
                }],
                'omero': {
                    'id': 1,
                    'version': '0.5',
                    'name': name,
                    'channels': channels,
                    'rdefs': rdefs,
                },
                'bioformats2raw.layout': 3,
            })

    @property
    def crop(self):
        """
        Crop only applies to the output file, not the internal data access.

        It consists of x, y, w, h in pixels.
        """
        return getattr(self, '_crop', None)

    @crop.setter
    def crop(self, value):
        self._checkEditable()
        if value is None:
            self._crop = None
            return
        x, y, w, h = value
        x = int(x)
        y = int(y)
        w = int(w)
        h = int(h)
        if x < 0 or y < 0 or w <= 0 or h <= 0:
            msg = 'Crop must have non-negative x, y and positive w, h'
            raise TileSourceError(msg)
        self._crop = (x, y, w, h)

    @property
    def mm_x(self):
        return self._mm_x

    @mm_x.setter
    def mm_x(self, value):
        self._checkEditable()
        value = float(value) if value is not None else None
        if value is not None and value <= 0:
            msg = 'mm_x must be positive or None'
            raise TileSourceError(msg)
        self._mm_x = value

    @property
    def mm_y(self):
        return self._mm_y

    @mm_y.setter
    def mm_y(self, value):
        self._checkEditable()
        value = float(value) if value is not None else None
        if value is not None and value <= 0:
            msg = 'mm_y must be positive or None'
            raise TileSourceError(msg)
        self._mm_y = value

    @property
    def imageDescription(self):
        return self._imageDescription

    @imageDescription.setter
    def imageDescription(self, description):
        self._checkEditable()
        self._imageDescription = description

    @property
    def channelNames(self):
        return self._channelNames

    @channelNames.setter
    def channelNames(self, names):
        self._checkEditable()
        self._channelNames = names

    @property
    def channelColors(self):
        return self._channelColors

    @channelColors.setter
    def channelColors(self, colors):
        self._checkEditable()
        self._channelColors = colors

    @property
    def frameAxes(self):
        return self._frameAxes

    @frameAxes.setter
    def frameAxes(self, axes):
        self._checkEditable()
        self._frameAxes = axes

    @property
    def frameUnits(self):
        return self._frameUnits

    @frameUnits.setter
    def frameUnits(self, units):
        self._checkEditable()
        if self.frameAxes is None:
            err = 'frameAxes must be set first with a list of frame axis names.'
            raise ValueError(err)
        if not isinstance(units, dict) or not all(
            k in self.frameAxes for k in units.keys()
        ):
            err = 'frameUnits must be a dictionary with keys that exist in frameAxes.'
            raise ValueError(err)
        self._frameUnits = units

    @property
    def frameValues(self):
        return self._frameValues

    @frameValues.setter
    def frameValues(self, a):
        self._checkEditable()
        if self.frameAxes is None:
            err = 'frameAxes must be set first with a list of frame axis names.'
            raise ValueError(err)
        if len(a.shape) != len(self.frameAxes) + 1:
            err = f'frameValues must have {len(self.frameAxes) + 1} dimensions.'
            raise ValueError(err)
        self._frameValues = a

    def _generateDownsampledLevels(self, resample_method):
        self._checkEditable()
        current_arrays = dict(self._zarr.arrays())
        if '0' not in current_arrays:
            msg = 'No root data found, cannot generate lower resolution levels.'
            raise TileSourceError(msg)
        if 'x' not in self._axes or 'y' not in self._axes:
            msg = 'Data must have an X axis and Y axis to generate lower resolution levels.'
            raise TileSourceError(msg)

        metadata = self.getMetadata()

        if (
            resample_method.value < ResampleMethod.PIL_MAX_ENUM.value and
            resample_method != ResampleMethod.PIL_NEAREST
        ):
            tile_overlap = dict(x=4, y=4, edges=True)
        else:
            tile_overlap = dict(x=0, y=0)
        tile_size = dict(
            width=4096 + tile_overlap['x'],
            height=4096 + tile_overlap['y'],
        )
        sorted_axes = [a[0] for a in sorted(self._axes.items(), key=lambda item: item[1])]
        for level in range(1, self.levels):
            scale_factor = 2 ** level
            iterator_output = dict(
                maxWidth=self.sizeX // scale_factor,
                maxHeight=self.sizeY // scale_factor,
            )
            for frame in metadata.get('frames', [{'Index': 0}]):
                frame_position = {
                    k.replace('Index', '').lower(): v
                    for k, v in frame.items()
                    if k.replace('Index', '').lower() in self._axes
                }
                for tile in self.tileIterator(
                    tile_size=tile_size,
                    tile_overlap=tile_overlap,
                    frame=frame['Index'],
                    output=iterator_output,
                    resample=False,  # TODO: incorporate resampling in core
                ):
                    new_tile = downsampleTileHalfRes(tile['tile'], resample_method)
                    overlap = {k: int(v / 2) for k, v in tile['tile_overlap'].items()}
                    new_tile = new_tile[
                        slice(overlap['top'], new_tile.shape[0] - overlap['bottom']),
                        slice(overlap['left'], new_tile.shape[1] - overlap['right']),
                    ]

                    x = int(tile['x'] / 2 + overlap['left'])
                    y = int(tile['y'] / 2 + overlap['top'])

                    self.addTile(
                        new_tile,
                        x=x,
                        y=y,
                        **frame_position,
                        axes=sorted_axes,
                        level=level,
                    )
            self._validateZarr()  # refresh self._levels before continuing

    def write(
        self,
        path,
        lossy=True,
        alpha=True,
        overwriteAllowed=True,
        resample=None,
        **converterParams,
    ):
        """
        Output the current image to a file.

        :param path: output path.
        :param lossy: if false, emit a lossless file.
        :param alpha: True if an alpha channel is allowed.
        :param overwriteAllowed: if False, raise an exception if the output
            path exists.
        :param resample: one of the ``ResampleMethod`` enum values.  Defaults
            to ``NP_NEAREST`` for lossless and non-uint8 data and to
            ``PIL_LANCZOS`` for lossy uint8 data.
        :param converterParams: options to pass to the large_image_converter if
            the output is not a zarr variant.
        """
        if os.path.exists(path):
            if overwriteAllowed:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
            else:
                raise TileSourceError('Output path exists (%s).' % str(path))

        suffix = Path(path).suffix
        source = self

        if self.crop:
            left, top, width, height = self.crop
            source = new()
            source._zarr.attrs.update(self._zarr.attrs)
            for frame in self.getMetadata().get('frames', [{'Index': 0}]):
                frame_position = {
                    k.replace('Index', '').lower(): v
                    for k, v in frame.items()
                    if k.replace('Index', '').lower() in self._axes
                }
                for tile in self.tileIterator(
                    frame=frame['Index'],
                    region=dict(top=top, left=left, width=width, height=height),
                    resample=False,
                ):
                    source.addTile(
                        tile['tile'],
                        x=tile['x'] - left,
                        y=tile['y'] - top,
                        axes=list(self._axes.keys()),
                        **frame_position,
                    )

        source._validateZarr()

        if suffix in ['.zarr', '.db', '.sqlite', '.zip']:
            if resample is None:
                resample = (
                    ResampleMethod.PIL_LANCZOS
                    if lossy and source.dtype == np.uint8
                    else ResampleMethod.NP_NEAREST
                )
            source._generateDownsampledLevels(resample)
            source._writeInternalMetadata()  # rewrite with new level datasets

            if suffix == '.zarr':
                shutil.copytree(str(source._tempdir), path)
            elif suffix in ['.db', '.sqlite']:
                sqlite_store = zarr.SQLiteStore(path)
                zarr.copy_store(source._zarr_store, sqlite_store, if_exists='replace')
                sqlite_store.close()
            elif suffix == '.zip':
                zip_store = zarr.ZipStore(path)
                zarr.copy_store(source._zarr_store, zip_store, if_exists='replace')
                zip_store.close()

        else:
            from large_image_converter import convert

            attrs_path = source._tempdir / '.zattrs'
            params = {}
            if lossy and self.dtype == np.uint8:
                params['compression'] = 'jpeg'
            params.update(converterParams)
            convert(str(attrs_path), path, overwrite=overwriteAllowed, **params)


def open(*args, **kwargs):
    """
    Create an instance of the module class.
    """
    return ZarrFileTileSource(*args, **kwargs)


def canRead(*args, **kwargs):
    """
    Check if an input can be read by the module class.
    """
    return ZarrFileTileSource.canRead(*args, **kwargs)


def new(*args, **kwargs):
    """
    Create a new image, collecting the results from patches of numpy arrays or
    smaller images.
    """
    return ZarrFileTileSource(NEW_IMAGE_PATH_FLAG + str(uuid.uuid4()), *args, **kwargs)
