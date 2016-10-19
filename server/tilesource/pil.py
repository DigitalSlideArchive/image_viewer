#!/usr/bin/env python
# -*- coding: utf-8 -*-

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

import json
import six


import PIL.Image

from .base import FileTileSource, TileSourceException
from ..cache_util import LruCacheMetaclass, pickAvailableCache, strhash, \
    methodcache

try:
    import girder
    from .base import GirderTileSource
    from girder.utility.model_importer import ModelImporter
    from .. import constants
except ImportError:
    girder = None


def getMaxSize(size=None):
    """
    Get the maximum width and height that we allow for an image.

    :param size: the requested maximum size.  This is either a number to use
        for both width and height, or an object with {'width': (width),
        'height': height} in pixels.  If None, the default max size is used.
    :returns: maxWidth, maxHeight in pixels.  0 means no images are allowed.
    """
    # We may want different defaults if the image will be sent to a viewer, as
    # texture buffers are typically 2k to 16k square.  We may want to read the
    # default value from girder settings or config.
    maxWidth = maxHeight = 4096
    if girder:
        maxWidth = maxHeight = int(ModelImporter.model('setting').get(
            constants.PluginSettings.LARGE_IMAGE_MAX_SMALL_IMAGE_SIZE))
    if size is not None:
        if isinstance(size, dict):
            maxWidth = size.get('width', maxWidth)
            maxHeight = size.get('height', maxHeight)
        else:
            maxWidth = maxHeight = size
    # We may want to put an upper limit on what is requested so it can't be
    # completely overridden.
    return maxWidth, maxHeight


@six.add_metaclass(LruCacheMetaclass)
class PILFileTileSource(FileTileSource):
    """
    Provides tile access to single image PIL files.
    """
    # Cache size is based on what the class needs, which does not include
    # individual tiles
    cacheMaxSize = pickAvailableCache(1024 ** 2)
    cacheTimeout = 300
    name = 'pilfile'

    def __init__(self, path, maxSize=None, **kwargs):
        """
        Initialize the tile class.

        :param path: the associated file path.
        :param maxSize: either a number or an object with {'width': (width),
            'height': height} in pixels.  If None, the default max size is
            used.
        """
        super(PILFileTileSource, self).__init__(path, **kwargs)

        if isinstance(maxSize, six.string_types):
            try:
                maxSize = json.loads(maxSize)
            except Exception:
                raise TileSourceException(
                    'maxSize must be None, an integer, a dictionary, or a '
                    'JSON string that converts to one of those.')
        self.maxSize = maxSize

        largeImagePath = self._getLargeImagePath()

        try:
            self._pilImage = PIL.Image.open(largeImagePath)
        except IOError:
            raise TileSourceException('File cannot be opened via PIL.')
        self.sizeX = self._pilImage.width
        self.sizeY = self._pilImage.height
        # We have just one tile which is the entire image.
        self.tileWidth = self.sizeX
        self.tileHeight = self.sizeY
        self.levels = 1
        # Throw an exception if too big
        if self.tileWidth <= 0 or self.tileHeight <= 0:
            raise TileSourceException('PIL tile size is invalid.')
        maxWidth, maxHeight = getMaxSize(maxSize)
        if self.tileWidth > maxWidth or self.tileHeight > maxHeight:
            raise TileSourceException('PIL tile size is too large.')

    @staticmethod
    def getLRUHash(*args, **kwargs):
        return strhash(
            super(PILFileTileSource, PILFileTileSource).getLRUHash(
                *args, **kwargs),
            kwargs.get('maxSize'))

    def getState(self):
        return super(PILFileTileSource, self).getState() + ',' + str(
            self.maxSize)

    @methodcache()
    def getTile(self, x, y, z, pilImageAllowed=False, **kwargs):
        if z != 0:
            raise TileSourceException('z layer does not exist')
        if x != 0:
            raise TileSourceException('x is outside layer')
        if y != 0:
            raise TileSourceException('y is outside layer')
        return self._outputTile(self._pilImage, 'PIL', x, y, z,
                                pilImageAllowed, **kwargs)


if girder:
    class PILGirderTileSource(PILFileTileSource, GirderTileSource):
        """
        Provides tile access to Girder items with a PIL file.
        """
        # Cache size is based on what the class needs, which does not include
        # individual tiles
        cacheMaxSize = pickAvailableCache(1024 ** 2)
        cacheTimeout = 300
        name = 'pil'

        @staticmethod
        def getLRUHash(*args, **kwargs):
            return strhash(
                super(PILGirderTileSource, PILGirderTileSource).getLRUHash(
                    *args, **kwargs),
                kwargs.get('maxSize'))

        def getState(self):
            return super(PILGirderTileSource, self).getState() + ',' + str(
                self.maxSize)
