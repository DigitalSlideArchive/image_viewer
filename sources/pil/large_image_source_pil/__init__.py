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

import contextlib
import json
import math
import os
import threading

import numpy as np
import PIL.Image

import large_image
from large_image import config
from large_image.cache_util import LruCacheMetaclass, methodcache, strhash
from large_image.constants import TILE_FORMAT_PIL, SourcePriority
from large_image.exceptions import TileSourceError, TileSourceFileNotFoundError
from large_image.tilesource import FileTileSource

# Optionally extend PIL with some additional formats
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    from pillow_heif import register_avif_opener
    register_avif_opener()
except Exception:
    pass
try:
    import pillow_jxl  # noqa
except Exception:
    pass
try:
    import pillow_jpls  # noqa
except Exception:
    pass

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _importlib_version

try:
    __version__ = _importlib_version(__name__)
except PackageNotFoundError:
    # package is not installed
    pass

# Default to ignoring files with some specific extensions.
config.ConfigValues['source_pil_ignored_names'] = \
    r'(\.mrxs|\.vsi)$'


def getMaxSize(size=None, maxDefault=4096):
    """
    Get the maximum width and height that we allow for an image.

    :param size: the requested maximum size.  This is either a number to use
        for both width and height, or an object with {'width': (width),
        'height': height} in pixels.  If None, the default max size is used.
    :param maxDefault: a default value to use for width and height.
    :returns: maxWidth, maxHeight in pixels.  0 means no images are allowed.
    """
    maxWidth = maxHeight = maxDefault
    if size is not None:
        if isinstance(size, dict):
            maxWidth = size.get('width', maxWidth)
            maxHeight = size.get('height', maxHeight)
        else:
            maxWidth = maxHeight = size
    # We may want to put an upper limit on what is requested so it can't be
    # completely overridden.
    return maxWidth, maxHeight


class PILFileTileSource(FileTileSource, metaclass=LruCacheMetaclass):
    """
    Provides tile access to single image PIL files.
    """

    cacheName = 'tilesource'
    name = 'pil'

    # Although PIL is mostly a fallback source, prefer it to other fallback
    # sources
    extensions = {
        None: SourcePriority.FALLBACK_HIGH,
        'jpg': SourcePriority.LOW,
        'jpeg': SourcePriority.LOW,
        'jpe': SourcePriority.LOW,
    }
    mimeTypes = {
        None: SourcePriority.FALLBACK_HIGH,
        'image/jpeg': SourcePriority.LOW,
    }

    def __init__(self, path, maxSize=None, **kwargs):  # noqa
        """
        Initialize the tile class.  See the base class for other available
        parameters.

        :param path: the associated file path.
        :param maxSize: either a number or an object with {'width': (width),
            'height': height} in pixels.  If None, the default max size is
            used.
        """
        super().__init__(path, **kwargs)
        self.addKnownExtensions()

        self._maxSize = maxSize
        if isinstance(maxSize, str):
            try:
                maxSize = json.loads(maxSize)
            except Exception:
                msg = ('maxSize must be None, an integer, a dictionary, or a '
                       'JSON string that converts to one of those.')
                raise TileSourceError(msg)
        self.maxSize = maxSize

        largeImagePath = self._getLargeImagePath()
        # Some formats shouldn't be read this way, even if they could.  For
        # instances, mirax (mrxs) files look like JPEGs, but opening them as
        # such misses most of the data.
        config._ignoreSourceNames('pil', largeImagePath)

        self._pilImage = None
        self._fromRawpy(largeImagePath)
        if self._pilImage is None:
            try:
                self._pilImage = PIL.Image.open(largeImagePath)
            except OSError:
                if not os.path.isfile(largeImagePath):
                    raise TileSourceFileNotFoundError(largeImagePath) from None
                msg = 'File cannot be opened via PIL.'
                raise TileSourceError(msg)
        minwh = min(self._pilImage.width, self._pilImage.height)
        maxwh = max(self._pilImage.width, self._pilImage.height)
        # Throw an exception if too small or big before processing further
        if minwh <= 0:
            msg = 'PIL tile size is invalid.'
            raise TileSourceError(msg)
        maxWidth, maxHeight = getMaxSize(maxSize, self.defaultMaxSize())
        if maxwh > max(maxWidth, maxHeight):
            msg = 'PIL tile size is too large.'
            raise TileSourceError(msg)
        self._checkForFrames()
        if self._pilImage.info.get('icc_profile', None):
            self._iccprofiles = [self._pilImage.info.get('icc_profile')]
        # If the rotation flag exists, loading the image may change the width
        # and height
        if getattr(self._pilImage, '_tile_orientation', None) not in {None, 1}:
            self._pilImage.load()
        # If this is encoded as a 32-bit integer or a 32-bit float, convert it
        # to an 8-bit integer.  This expects the source value to either have a
        # maximum of 1, 2^8-1, 2^16-1, 2^24-1, or 2^32-1, and scales it to
        # [0, 255]
        pilImageMode = self._pilImage.mode.split(';')[0]
        self._factor = None
        if pilImageMode in ('I', 'F'):
            try:
                imgdata = np.asarray(self._pilImage)
                if np.isnan(np.sum(imgdata)):
                    imgdata = imgdata.copy()
                    imgdata[np.isnan(imgdata)] = 0
            except Exception:
                msg = 'PIL cannot find loader for this file.'
                raise TileSourceError(msg)
            maxval = 256 ** math.ceil(math.log(float(np.max(imgdata)) + 1, 256)) - 1
            self._factor = 255.0 / max(maxval, 1)
            self._pilImage = PIL.Image.fromarray(np.uint8(np.multiply(
                imgdata, self._factor)))
        self.sizeX = self._pilImage.width
        self.sizeY = self._pilImage.height
        # We have just one tile which is the entire image.
        self.tileWidth = self.sizeX
        self.tileHeight = self.sizeY
        self.levels = 1
        # Throw an exception if too big after processing
        if self.tileWidth > maxWidth or self.tileHeight > maxHeight:
            msg = 'PIL tile size is too large.'
            raise TileSourceError(msg)

    def _checkForFrames(self):
        self._frames = None
        self._frameCount = 1
        if hasattr(self._pilImage, 'seek'):
            try:
                baseSize, baseMode = self._pilImage.size, self._pilImage.mode
                baseMode = {baseMode}
                if 'P' in baseMode:
                    baseMode |= {'RGB', 'RGBA'}
                self._frames = [
                    idx for idx, frame in enumerate(PIL.ImageSequence.Iterator(self._pilImage))
                    if frame.size == baseSize and frame.mode in baseMode]
                self._pilImage.seek(0)
                self._frameImage = self._pilImage
                self._frameCount = len(self._frames)
                self._tileLock = threading.RLock()
            except Exception:
                self._frames = None
                self._frameCount = 1
                self._pilImage.seek(0)

    def _fromRawpy(self, largeImagePath):
        """
        Try to use rawpy to read an image.
        """
        # if rawpy is present, try reading via that library first
        try:
            import rawpy

            with contextlib.redirect_stderr(open(os.devnull, 'w')):
                rgb = rawpy.imread(largeImagePath).postprocess()
                rgb = large_image.tilesource.utilities._imageToNumpy(rgb)[0]
                if rgb.shape[2] == 2:
                    rgb = rgb[:, :, :1]
                elif rgb.shape[2] > 3:
                    rgb = rgb[:, :, :3]
                self._pilImage = PIL.Image.fromarray(
                    rgb.astype(np.uint8) if rgb.dtype != np.uint16 else rgb,
                    ('RGB' if rgb.dtype != np.uint16 else 'RGB;16') if rgb.shape[2] == 3 else
                    ('L' if rgb.dtype != np.uint16 else 'L;16'))
        except Exception:
            pass

    def defaultMaxSize(self):
        """
        Get the default max size from the config settings.

        :returns: the default max size.
        """
        return int(config.getConfig('max_small_image_size', 4096))

    @staticmethod
    def getLRUHash(*args, **kwargs):
        return strhash(
            super(PILFileTileSource, PILFileTileSource).getLRUHash(
                *args, **kwargs),
            kwargs.get('maxSize'))

    def getState(self):
        return super().getState() + ',' + str(
            self._maxSize)

    def getMetadata(self):
        """
        Return a dictionary of metadata containing levels, sizeX, sizeY,
        tileWidth, tileHeight, magnification, mm_x, mm_y, and frames.

        :returns: metadata dictionary.
        """
        result = super().getMetadata()
        if getattr(self, '_frames', None) is not None and len(self._frames) > 1:
            result['frames'] = [{} for idx in range(len(self._frames))]
            self._addMetadataFrameInformation(result)
        return result

    def getInternalMetadata(self, **kwargs):
        """
        Return additional known metadata about the tile source.  Data returned
        from this method is not guaranteed to be in any particular format or
        have specific values.

        :returns: a dictionary of data or None.
        """
        results = {'pil': {}}
        for key in ('format', 'mode', 'size', 'width', 'height', 'palette', 'info'):
            try:
                results['pil'][key] = getattr(self._pilImage, key)
            except Exception:
                pass
        return results

    @methodcache()
    def getTile(self, x, y, z, pilImageAllowed=False, numpyAllowed=False,
                mayRedirect=False, **kwargs):
        frame = self._getFrame(**kwargs)
        self._xyzInRange(x, y, z, frame, self._frameCount)
        if frame != 0:
            with self._tileLock:
                self._frameImage.seek(self._frames[frame])
                try:
                    img = self._frameImage.copy()
                except Exception:
                    pass
                self._frameImage.seek(0)
            img.load()
            if self._factor:
                img = PIL.Image.fromarray(np.uint8(np.multiply(
                    np.asarray(img), self._factor)))
        else:
            img = self._pilImage
        return self._outputTile(img, TILE_FORMAT_PIL, x, y, z,
                                pilImageAllowed, numpyAllowed, **kwargs)

    @classmethod
    def addKnownExtensions(cls):
        if not hasattr(cls, '_addedExtensions'):
            cls._addedExtensions = True
            cls.extensions = cls.extensions.copy()
            cls.mimeTypes = cls.mimeTypes.copy()
            for dotext in PIL.Image.registered_extensions():
                ext = dotext.lstrip('.')
                if ext not in cls.extensions:
                    cls.extensions[ext] = SourcePriority.IMPLICIT_HIGH
            for mimeType in PIL.Image.MIME.values():
                if mimeType not in cls.mimeTypes:
                    cls.mimeTypes[mimeType] = SourcePriority.IMPLICIT_HIGH


def open(*args, **kwargs):
    """
    Create an instance of the module class.
    """
    return PILFileTileSource(*args, **kwargs)


def canRead(*args, **kwargs):
    """
    Check if an input can be read by the module class.
    """
    return PILFileTileSource.canRead(*args, **kwargs)
