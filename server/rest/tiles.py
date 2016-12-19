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

import cherrypy

from girder.api import access, filter_logging
from girder.api.v1.item import Item
from girder.api.describe import describeRoute, Description
from girder.api.rest import filtermodel, loadmodel, RestException, \
    setRawResponse, setResponseHeader
from girder.models.model_base import AccessType

from ..models import TileGeneralException

from .. import loadmodelcache


class TilesItemResource(Item):

    def __init__(self, apiRoot):
        # Don't call the parent (Item) constructor, to avoid redefining routes,
        # but do call the grandparent (Resource) constructor
        super(Item, self).__init__()

        self.resourceName = 'item'
        apiRoot.item.route('POST', (':itemId', 'tiles'), self.createTiles)
        apiRoot.item.route('GET', (':itemId', 'tiles'), self.getTilesInfo)
        apiRoot.item.route('DELETE', (':itemId', 'tiles'), self.deleteTiles)
        apiRoot.item.route('GET', (':itemId', 'tiles', 'thumbnail'),
                           self.getTilesThumbnail)
        apiRoot.item.route('GET', (':itemId', 'tiles', 'region'),
                           self.getTilesRegion)
        apiRoot.item.route('GET', (':itemId', 'tiles', 'zxy', ':z', ':x', ':y'),
                           self.getTile)
        apiRoot.item.route('GET', ('test', 'tiles'), self.getTestTilesInfo)
        apiRoot.item.route('GET', ('test', 'tiles', 'zxy', ':z', ':x', ':y'),
                           self.getTestTile)
        filter_logging.addLoggingFilter(
            'GET (/[^/ ?#]+)*/item/[^/ ?#]+/tiles/zxy(/[^/ ?#]+){3}',
            frequency=250)
        # Cache the model singleton
        self.imageItemModel = self.model('image_item', 'large_image')

    @describeRoute(
        Description('Create a large image for this item.')
        .param('itemId', 'The ID of the item.', paramType='path')
        .param('fileId', 'The ID of the source file containing the image. '
                         'Required if there is more than one file in the item.',
               required=False)
        .param('notify', 'If a job is required to create the large image, '
               'a nofication can be sent when it is complete.',
               dataType='boolean', default=True, required=False)
    )
    @access.user
    @loadmodel(model='item', map={'itemId': 'item'}, level=AccessType.WRITE)
    @filtermodel(model='job', plugin='jobs')
    def createTiles(self, item, params):
        largeImageFileId = params.get('fileId')
        if largeImageFileId is None:
            files = list(self.model('item').childFiles(
                item=item, limit=2))
            if len(files) == 1:
                largeImageFileId = str(files[0]['_id'])
        if not largeImageFileId:
            raise RestException('Missing "fileId" parameter.')
        largeImageFile = self.model('file').load(
            largeImageFileId, force=True, exc=True)
        user = self.getCurrentUser()
        token = self.getCurrentToken()
        try:
            return self.imageItemModel.createImageItem(
                item, largeImageFile, user, token,
                notify=self.boolParam('notify', params, default=True))
        except TileGeneralException as e:
            raise RestException(e.message)

    @classmethod
    def _parseTestParams(cls, params):
        return cls._parseParams(params, False, [
            ('minLevel', int),
            ('maxLevel', int),
            ('tileWidth', int),
            ('tileHeight', int),
            ('sizeX', int),
            ('sizeY', int),
            ('fractal', lambda val: val == 'true'),
            ('encoding', str),
        ])

    @classmethod
    def _parseParams(cls, params, keepUnknownParams, typeList):
        """
        Given a dictionary of parameters, check that a list of parameters are
        valid data types.  The parameters within the list are validated and
        copied to a dictionary by themselves.

        :param params: the dictionary of parameters to validate.
        :param keepUnknownParams: True to copy all parameters, not just those
            in the typeList.  The parameters in the typeList are still
            validated.
        :param typeList: a list of tuples of the form (key, dataType, [outkey1,
            [outkey2]]).  If output keys are used, the original key is renamed
            to the the output key.  If two output keys are specified, the
            original key is renamed to outkey2 and placed in a sub-dictionary
            names outkey1.
        :returns: params: a validated and possibly filtered list of parameters.
        """
        results = {}
        if keepUnknownParams:
            results = dict(params)
        for entry in typeList:
            key, dataType, outkey1, outkey2 = (list(entry) + [None]*2)[:4]
            if key in params:
                try:
                    if dataType is bool:
                        results[key] = str(params[key]).lower() in (
                            'true', 'on', 'yes', '1')
                    else:
                        results[key] = dataType(params[key])
                except ValueError:
                    raise RestException(
                        '"%s" parameter is an incorrect type.' % key)
                if outkey1 is not None:
                    if outkey2 is not None:
                        results.setdefault(outkey1, {})[outkey2] = results[key]
                    else:
                        results[outkey1] = results[key]
                    del results[key]
        return results

    def _getTilesInfo(self, item, imageArgs):
        """
        Get metadata for an item's large image.

        :param item: the item to query.
        :param imageArgs: additional arguments to use when fetching image data.
        :return: the tile metadata.
        """
        try:
            return self.imageItemModel.getMetadata(item, **imageArgs)
        except TileGeneralException as e:
            raise RestException(e.message, code=400)

    @describeRoute(
        Description('Get large image metadata.')
        .param('itemId', 'The ID of the item.', paramType='path')
        .errorResponse('ID was invalid.')
        .errorResponse('Read access was denied for the item.', 403)
    )
    @access.public
    @loadmodel(model='item', map={'itemId': 'item'}, level=AccessType.READ)
    def getTilesInfo(self, item, params):
        # TODO: parse params?
        return self._getTilesInfo(item, params)

    @describeRoute(
        Description('Get test large image metadata.')
    )
    @access.public
    def getTestTilesInfo(self, params):
        item = {'largeImage': {'sourceName': 'test'}}
        imageArgs = self._parseTestParams(params)
        return self._getTilesInfo(item, imageArgs)

    def _getTile(self, item, z, x, y, imageArgs):
        """
        Get an large image tile.

        :param item: the item to get a tile from.
        :param z: tile layer number (0 is the most zoomed-out).
        .param x: the X coordinate of the tile (0 is the left side).
        .param y: the Y coordinate of the tile (0 is the top).
        :param imageArgs: additional arguments to use when fetching image data.
        :return: a function that returns the raw image data.
        """
        try:
            x, y, z = int(x), int(y), int(z)
        except ValueError:
            raise RestException('x, y, and z must be integers', code=400)
        if x < 0 or y < 0 or z < 0:
            raise RestException('x, y, and z must be positive integers',
                                code=400)
        # In iOS 10.1, only JPEGs that have a JFIF header and read.  However,
        # if we universally add a JFIF header, this breaks the colorspace
        # parsing that browsers do on RGB-encoded JPEG (see
        # https://docs.oracle.com/javase/8/docs/api/javax/imageio/metadata/
        # doc-files/jpeg_metadata.html#color for a disuccsion on how colorspace
        # is determined.  Since we would rather not reencode tiles if possible,
        # we set a flag if we happen to be on an iOS device.  If the tile is a
        # JPEG, then it will be parsed by PIL and reencoded.
        userAgent = cherrypy.request.headers.get('User-Agent', '').lower()
        alwaysConvertJPEG = ('ipad' in userAgent or 'ipod' in userAgent or
                             'iphone' in userAgent)
        try:
            tileData, tileMime = self.imageItemModel.getTile(
                item, x, y, z, alwaysConvertJPEG=alwaysConvertJPEG, **imageArgs)
        except TileGeneralException as e:
            raise RestException(e.message, code=404)
        setResponseHeader('Content-Type', tileMime)
        setRawResponse()
        return tileData

    @describeRoute(
        Description('Get a large image tile.')
        .param('itemId', 'The ID of the item.', paramType='path')
        .param('z', 'The layer number of the tile (0 is the most zoomed-out '
               'layer).', paramType='path')
        .param('x', 'The X coordinate of the tile (0 is the left side).',
               paramType='path')
        .param('y', 'The Y coordinate of the tile (0 is the top).',
               paramType='path')
        .errorResponse('ID was invalid.')
        .errorResponse('Read access was denied for the item.', 403)
    )
    # Without caching, this checks for permissions every time.  By using the
    # LoadModelCache, three database lookups are avoided, which saves around
    # 6 ms in tests.
    #   @access.cookie   # access.cookie always looks up the token
    #   @access.public
    #   @loadmodel(model='item', map={'itemId': 'item'}, level=AccessType.READ)
    #   def getTile(self, item, z, x, y, params):
    #       return self._getTile(item, z, x, y, params)
    @access.public
    def getTile(self, itemId, z, x, y, params):
        item = loadmodelcache.loadModel(
            self, 'item', id=itemId, allowCookie=True, level=AccessType.READ)
        # Explicitly set a expires time to encourage browsers to cache this for
        # a while.
        setResponseHeader('Expires', cherrypy.lib.httputil.HTTPDate(
            cherrypy.serving.response.time + 600))
        return self._getTile(item, z, x, y, params)

    @describeRoute(
        Description('Get a test large image tile.')
        .param('z', 'The layer number of the tile (0 is the most zoomed-out '
               'layer).', paramType='path')
        .param('x', 'The X coordinate of the tile (0 is the left side).',
               paramType='path')
        .param('y', 'The Y coordinate of the tile (0 is the top).',
               paramType='path')
    )
    @access.cookie
    @access.public
    def getTestTile(self, z, x, y, params):
        item = {'largeImage': {'sourceName': 'test'}}
        imageArgs = self._parseTestParams(params)
        return self._getTile(item, z, x, y, imageArgs)

    @describeRoute(
        Description('Remove a large image from this item.')
        .param('itemId', 'The ID of the item.', paramType='path')
    )
    @access.user
    @loadmodel(model='item', map={'itemId': 'item'}, level=AccessType.WRITE)
    def deleteTiles(self, item, params):
        deleted = self.imageItemModel.delete(item)
        # TODO: a better response
        return {
            'deleted': deleted
        }

    @describeRoute(
        Description('Get a thumbnail of a large image item.')
        .notes('Aspect ratio is always preserved.  If both width and height '
               'are specified, the resulting thumbnail may be smaller in one '
               'of the two dimensions.  If neither width nor height is given, '
               'a default size will be returned.  '
               'This creates a thumbnail from the lowest level of the source '
               'image, which means that asking for a large thumbnail will not '
               'be a high-quality image.')
        .param('itemId', 'The ID of the item.', paramType='path')
        .param('width', 'The maximum width of the thumbnail in pixels.',
               required=False, dataType='int')
        .param('height', 'The maximum height of the thumbnail in pixels.',
               required=False, dataType='int')
        .param('encoding', 'Thumbnail output encoding', required=False,
               enum=['JPEG', 'PNG'], default='JPEG')
        .errorResponse('ID was invalid.')
        .errorResponse('Read access was denied for the item.', 403)
    )
    @access.cookie
    @access.public
    @loadmodel(model='item', map={'itemId': 'item'}, level=AccessType.READ)
    def getTilesThumbnail(self, item, params):
        params = self._parseParams(params, True, [
            ('width', int),
            ('height', int),
            ('jpegQuality', int),
            ('jpegSubsampling', int),
            ('encoding', str),
        ])
        try:
            result = self.imageItemModel.getThumbnail(item, **params)
        except TileGeneralException as e:
            raise RestException(e.message)
        except ValueError as e:
            raise RestException('Value Error: %s' % e.message)
        if not isinstance(result, tuple):
            return result
        thumbData, thumbMime = result
        setResponseHeader('Content-Type', thumbMime)
        setRawResponse()
        return thumbData

    @describeRoute(
        Description('Get any region of a large image item, optionally scaling '
                    'it.')
        .notes('If neither width nor height is specified, the full resolution '
               'region is returned.  If a width or height is specified, '
               'aspect ratio is always preserved (if both are given, the '
               'resulting image may be smaller in one of the two '
               'dimensions).  When scaling must be applied, the image is '
               'downsampled from a higher resolution layer, never upsampled.')
        .param('itemId', 'The ID of the item.', paramType='path')
        .param('left', 'The left column (0-based) of the region to process.  '
               'Negative values are offsets from the right edge.',
               required=False, dataType='float')

        .param('top', 'The top row (0-based) of the region to process.  '
               'Negative values are offsets from the bottom edge.',
               required=False, dataType='float')
        .param('right', 'The right column (0-based from the left) of the '
               'region to process.  The region will not include this column.  '
               'Negative values are offsets from the right edge.',
               required=False, dataType='float')
        .param('bottom', 'The bottom row (0-based from the top) of the region '
               'to process.  The region will not include this row.  Negative '
               'values are offsets from the bottom edge.',
               required=False, dataType='float')
        .param('regionWidth', 'The width of the region to process.',
               required=False, dataType='float')
        .param('regionHeight', 'The height of the region to process.',
               required=False, dataType='float')
        .param('units', 'Units used for left, top, right, bottom, '
               'regionWidth, and regionHeight.  base_pixels are pixels at the '
               'maximum resolution, pixels and mm are at the specified '
               'magnfication, fraction is a scale of [0-1].', required=False,
               enum=['base_pixels', 'pixels', 'mm', 'fraction'],
               default='base_pixels')

        .param('width', 'The maximum width of the output image in pixels.',
               required=False, dataType='int')
        .param('height', 'The maximum height of the output image in pixels.',
               required=False, dataType='int')
        .param('magnification', 'Magnification of the output image.  If '
               'neither width for height is specified, the magnification, '
               'mm_x, and mm_y parameters are used to select the output size.',
               required=False, dataType='float')
        .param('mm_x', 'The size of the output pixels in millimeters',
               required=False, dataType='float')
        .param('mm_y', 'The size of the output pixels in millimeters',
               required=False, dataType='float')
        .param('exact', 'If magnification, mm_x, or mm_y are specified, they '
               'must match an existing level of the image exactly.',
               required=False, dataType='boolean', default=False)
        .param('encoding', 'Output image encoding', required=False,
               enum=['JPEG', 'PNG'], default='JPEG')
        .param('jpegQuality', 'Quality used for generating JPEG images',
               required=False, dataType='int', default=95)
        .param('jpegSubsampling', 'Chroma subsampling used for generating '
               'JPEG images.  0, 1, and 2 are full, half, and quarter '
               'resolution chroma respectively.', required=False,
               enum=['0', '1', '2'], dataType='int', default='0')
        .errorResponse('ID was invalid.')
        .errorResponse('Read access was denied for the item.', 403)
        .errorResponse('Insufficient memory.')
    )
    @access.cookie
    @access.public
    @loadmodel(model='item', map={'itemId': 'item'}, level=AccessType.READ)
    def getTilesRegion(self, item, params):
        params = self._parseParams(params, True, [
            ('left', float, 'region', 'left'),
            ('top', float, 'region', 'top'),
            ('right', float, 'region', 'right'),
            ('bottom', float, 'region', 'bottom'),
            ('regionWidth', float, 'region', 'width'),
            ('regionHeight', float, 'region', 'height'),
            ('units', str, 'region', 'units'),
            ('width', int, 'output', 'maxWidth'),
            ('height', int, 'output', 'maxHeight'),
            ('magnification', float, 'scale', 'magnification'),
            ('mm_x', float, 'scale', 'mm_x'),
            ('mm_y', float, 'scale', 'mm_y'),
            ('exact', bool, 'scale', 'exact'),
            ('encoding', str),
            ('jpegQuality', int),
            ('jpegSubsampling', int),
        ])
        try:
            regionData, regionMime = self.imageItemModel.getRegion(
                item, **params)
        except TileGeneralException as e:
            raise RestException(e.message)
        except ValueError as e:
            raise RestException('Value Error: %s' % e.message)
        setResponseHeader('Content-Type', regionMime)
        setRawResponse()
        return regionData
