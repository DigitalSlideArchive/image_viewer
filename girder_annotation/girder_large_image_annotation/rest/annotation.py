##############################################################################
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
##############################################################################

import json
import logging
import struct
import time

import cherrypy
import orjson
from bson.objectid import ObjectId
from girder_large_image.rest.tiles import _handleETag

from girder.api import access
from girder.api.describe import Description, autoDescribeRoute, describeRoute
from girder.api.rest import Resource, filtermodel, loadmodel, setResponseHeader
from girder.constants import AccessType, SortDir, TokenScope
from girder.exceptions import AccessException, RestException, ValidationException
from girder.models.folder import Folder
from girder.models.item import Item
from girder.models.user import User
from girder.utility import JsonEncoder
from girder.utility.progress import setResponseTimeLimit

from .. import constants, utils
from ..models.annotation import Annotation, AnnotationSchema
from ..models.annotationelement import Annotationelement

logger = logging.getLogger(__name__)


class AnnotationResource(Resource):

    def __init__(self):
        super().__init__()

        self.resourceName = 'annotation'
        self.route('GET', (), self.find)
        self.route('POST', (), self.createAnnotation)
        self.route('GET', ('schema',), self.getAnnotationSchema)
        self.route('GET', ('images',), self.findAnnotatedImages)
        self.route('GET', (':id',), self.getAnnotation)
        self.route('GET', (':id', ':format'), self.getAnnotationWithFormat)
        self.route('PUT', (':id',), self.updateAnnotation)
        self.route('DELETE', (':id',), self.deleteAnnotation)
        self.route('GET', (':id', 'access'), self.getAnnotationAccess)
        self.route('PUT', (':id', 'access'), self.updateAnnotationAccess)
        self.route('POST', (':id', 'copy'), self.copyAnnotation)
        self.route('GET', (':id', 'history'), self.getAnnotationHistoryList)
        self.route('GET', (':id', 'history', ':version'), self.getAnnotationHistory)
        self.route('PUT', (':id', 'history', 'revert'), self.revertAnnotationHistory)
        self.route('PUT', (':id', 'metadata'), self.setMetadata)
        self.route('DELETE', (':id', 'metadata'), self.deleteMetadata)
        self.route('GET', ('item', ':id'), self.getItemAnnotations)
        self.route('POST', ('item', ':id'), self.createItemAnnotations)
        self.route('DELETE', ('item', ':id'), self.deleteItemAnnotations)
        self.route('POST', ('item', ':id', 'plot', 'list'), self.getItemPlottableElements)
        self.route('POST', ('item', ':id', 'plot', 'data'), self.getItemPlottableData)
        self.route('GET', ('folder', ':id'), self.returnFolderAnnotations)
        self.route('GET', ('folder', ':id', 'present'), self.existFolderAnnotations)
        self.route('GET', ('folder', ':id', 'create'), self.canCreateFolderAnnotations)
        self.route('PUT', ('folder', ':id', 'access'), self.setFolderAnnotationAccess)
        self.route('DELETE', ('folder', ':id'), self.deleteFolderAnnotations)
        self.route('GET', ('counts',), self.getItemListAnnotationCounts)
        self.route('GET', ('old',), self.getOldAnnotations)
        self.route('DELETE', ('old',), self.deleteOldAnnotations)

    @describeRoute(
        Description('Search for annotations.')
        .responseClass('Annotation')
        .param('itemId', 'List all annotations in this item.', required=False)
        .param('userId', 'List all annotations created by this user.',
               required=False)
        .param('text', 'Pass this to perform a full text search for '
               'annotation names and descriptions.', required=False)
        .param('name', 'Pass to lookup an annotation by exact name match.',
               required=False)
        .pagingParams(defaultSort='lowerName')
        .errorResponse()
        .errorResponse('Read access was denied on the parent item.', 403),
    )
    @access.public(scope=TokenScope.DATA_READ)
    @filtermodel(model='annotation', plugin='large_image')
    def find(self, params):
        limit, offset, sort = self.getPagingParameters(params, 'lowerName')
        if sort and sort[0][0][0] == '[':
            sort = json.loads(sort[0][0])
        query = {'_active': {'$ne': False}}
        if 'itemId' in params:
            item = Item().load(params.get('itemId'), force=True)
            Item().requireAccess(
                item, user=self.getCurrentUser(), level=AccessType.READ)
            query['itemId'] = item['_id']
        if 'userId' in params:
            user = User().load(
                params.get('userId'), user=self.getCurrentUser(),
                level=AccessType.READ)
            query['creatorId'] = user['_id']
        if params.get('text'):
            query['$text'] = {'$search': params['text']}
        if params.get('name'):
            query['annotation.name'] = params['name']
        fields = list(
            (
                'annotation.name', 'annotation.description',
                'annotation.attributes', 'annotation.display',
                'access', 'groups', '_version',
            ) + Annotation().baseFields)
        return Annotation().findWithPermissions(
            query, sort=sort, fields=fields, user=self.getCurrentUser(),
            level=AccessType.READ, limit=limit, offset=offset)

    @describeRoute(
        Description('Get the official Annotation schema')
        .notes('In addition to the schema, if IDs are specified on elements, '
               'all IDs must be unique.')
        .errorResponse(),
    )
    @access.public(scope=TokenScope.DATA_READ)
    def getAnnotationSchema(self, params):
        return AnnotationSchema.annotationSchema

    @describeRoute(
        Description('Get an annotation by id.')
        .param('id', 'The ID of the annotation.', paramType='path')
        .param('left', 'The left column of the area to fetch.',
               required=False, dataType='float')
        .param('right', 'The right column (exclusive) of the area to fetch.',
               required=False, dataType='float')
        .param('top', 'The top row of the area to fetch.',
               required=False, dataType='float')
        .param('bottom', 'The bottom row (exclusive) of the area to fetch.',
               required=False, dataType='float')
        .param('low', 'The lowest z value of the area to fetch.',
               required=False, dataType='float')
        .param('high', 'The highest z value (exclusive) of the area to fetch.',
               required=False, dataType='float')
        .param('minimumSize', 'Only annotations larger than or equal to this '
               'size in pixels will be returned.  Size is determined by the '
               'length of the diagonal of the bounding box of an element.  '
               'This probably should be 1 at the maximum zoom, 2 at the next '
               'level down, 4 at the next, etc.', required=False,
               dataType='float')
        .param('maxDetails', 'Limit the number of annotations returned based '
               'on complexity.  The complexity of an annotation is how many '
               'points are used to defined it.  This is applied in addition '
               'to the limit.  Using maxDetails helps ensure results will be '
               'able to be rendered.', required=False, dataType='int')
        .param('minElements', 'If maxDetails is specified, always return at '
               'least this many elements, even if they are very detailed.',
               required=False, dataType='int')
        .param('centroids', 'If true, only return the centroids of each '
               'element.  The results are returned as a packed binary array '
               'with a json wrapper.', dataType='boolean', required=False)
        .param('bbox', 'If true, add _bbox records to each element.  These '
               'are computed when the annotation is stored and cannot be '
               'modified.  Cannot be used with the centroids option.',
               dataType='boolean', required=False)
        .pagingParams(defaultSort='_id', defaultLimit=None,
                      defaultSortDir=SortDir.ASCENDING)
        .errorResponse('ID was invalid.')
        .errorResponse('Read access was denied for the annotation.', 403)
        .notes('Use "size" or "details" as possible sort keys.'),
    )
    @access.public(cookie=True, scope=TokenScope.DATA_READ)
    def getAnnotation(self, id, params):
        user = self.getCurrentUser()
        annotation = Annotation().load(
            id, region=params, user=user, level=AccessType.READ, getElements=False)
        _handleETag('getAnnotation', annotation, params, max_age=86400 * 30)
        if annotation is None:
            msg = 'Annotation not found'
            raise RestException(msg, 404)
        return self._getAnnotation(annotation, params)

    @autoDescribeRoute(
        Description('Get an annotation by id in a specific format.')
        .param('id', 'The ID of the annotation.', paramType='path')
        .param('format', 'The format of the annotation.', paramType='path',
               enum=['geojson'])
        .errorResponse('ID was invalid.')
        .errorResponse('Read access was denied for the annotation.', 403)
        .notes('Use "size" or "details" as possible sort keys.'),
    )
    @access.public(cookie=True, scope=TokenScope.DATA_READ)
    @loadmodel(model='annotation', plugin='large_image', getElements=False, level=AccessType.READ)
    def getAnnotationWithFormat(self, annotation, format):
        _handleETag('getAnnotationWithFormat', annotation, format, max_age=86400 * 30)
        if annotation is None:
            msg = 'Annotation not found'
            raise RestException(msg, 404)

        def generateResult():
            for chunk in Annotation().geojson(annotation):
                yield chunk.encode()

        setResponseHeader('Content-Type', 'application/json')
        return generateResult

    def _getAnnotation(self, annotation, params):
        """
        Get a generator function that will yield the json of an annotation.

        :param annotation: the annotation document without elements.
        :param params: paging and region parameters for the annotation.
        :returns: a function that will return a generator.
        """
        # Set the response time limit to a very long value
        setResponseTimeLimit(86400)
        # Ensure that we have read access to the parent item.  We could fail
        # faster when there are permissions issues if we didn't load the
        # annotation elements before checking the item access permissions.
        #  This had been done via the filtermodel decorator, but that doesn't
        # work with yielding the elements one at a time.
        annotation = Annotation().filter(annotation, self.getCurrentUser())

        annotation['annotation']['elements'] = []
        breakStr = b'"elements": ['
        base = json.dumps(annotation, sort_keys=True, allow_nan=False,
                          cls=JsonEncoder).encode('utf8').split(breakStr)
        centroids = str(params.get('centroids')).lower() == 'true'

        def generateResult():
            info = {}
            idx = 0
            yield base[0]
            yield breakStr
            collect = []
            if centroids:
                # Add a null byte to indicate the start of the binary data
                yield b'\x00'
            for element in Annotationelement().yieldElements(annotation, params, info):
                # The json conversion is fastest if we use defaults as much as
                # possible.  The only value in an annotation element that needs
                # special handling is the id, so cast that ourselves and then
                # use a json encoder in the most compact form.
                if isinstance(element, dict):
                    element['id'] = str(element['id'])
                else:
                    element = struct.pack(
                        '>QL', int(element[0][:16], 16), int(element[0][16:24], 16),
                    ) + struct.pack('<fffl', *element[1:])
                # Use orjson; it is much faster.  The standard json library
                # could be used in its most default mode instead like so:
                #   result = json.dumps(element, separators=(',', ':'))
                # Collect multiple elements before emitting them.  This
                # balances using less memory and streaming right away with
                # efficiency in dumping the json.  Experimentally, 100 is
                # significantly faster than 10 and not much slower than 1000.
                collect.append(element)
                if len(collect) >= 100:
                    if isinstance(collect[0], dict):
                        # if switching json libraries, this may need
                        #  json.dumps(collect).encode()
                        yield (b',' if idx else b'') + orjson.dumps(collect)[1:-1]
                    else:
                        yield b''.join(collect)
                    idx += 1
                    collect = []
            if len(collect):
                if isinstance(collect[0], dict):
                    # if switching json libraries, this may need
                    #  json.dumps(collect).encode()
                    yield (b',' if idx else b'') + orjson.dumps(collect)[1:-1]
                else:
                    yield b''.join(collect)
            if centroids:
                # Add a final null byte to indicate the end of the binary data
                yield b'\x00'
            yield base[1].rstrip().rstrip(b'}')
            yield b', "_elementQuery": '
            yield json.dumps(
                info, sort_keys=True, allow_nan=False, cls=JsonEncoder).encode('utf8')
            yield b'}'

        if centroids:
            setResponseHeader('Content-Type', 'application/octet-stream')
        else:
            setResponseHeader('Content-Type', 'application/json')
        return generateResult

    @describeRoute(
        Description('Create an annotation.')
        .responseClass('Annotation')
        .param('itemId', 'The ID of the associated item.')
        .param('body', 'A JSON object containing the annotation.',
               paramType='body')
        .errorResponse('ID was invalid.')
        .errorResponse('Read access was denied for the item.', 403)
        .errorResponse('Invalid JSON passed in request body.')
        .errorResponse("Validation Error: JSON doesn't follow schema."),
    )
    @access.user(scope=TokenScope.DATA_WRITE)
    @loadmodel(map={'itemId': 'item'}, model='item', level=AccessType.READ)
    @filtermodel(model='annotation', plugin='large_image')
    def createAnnotation(self, item, params):
        user = self.getCurrentUser()
        folder = Folder().load(id=item['folderId'], user=user, level=AccessType.READ)
        if Folder().hasAccess(folder, user, AccessType.WRITE) or Folder(
        ).hasAccessFlags(folder, user, constants.ANNOTATION_ACCESS_FLAG):
            try:
                return Annotation().createAnnotation(
                    item, self.getCurrentUser(), self.getBodyJson())
            except ValidationException as exc:
                logger.exception('Failed to validate annotation')
                raise RestException(
                    "Validation Error: JSON doesn't follow schema (%r)." % (
                        exc.args, ))
        else:
            msg = 'Write access and annotation creation access were denied for the item.'
            raise RestException(msg, code=403)

    @describeRoute(
        Description('Copy an annotation from one item to an other.')
        .param('id', 'The ID of the annotation.', paramType='path',
               required=True)
        .param('itemId', 'The ID of the destination item.',
               required=True)
        .errorResponse('ID was invalid.')
        .errorResponse('Write access was denied for the item.', 403),
    )
    @access.user(scope=TokenScope.DATA_WRITE)
    @loadmodel(model='annotation', plugin='large_image', level=AccessType.READ)
    @filtermodel(model='annotation', plugin='large_image')
    def copyAnnotation(self, annotation, params):
        itemId = params['itemId']
        user = self.getCurrentUser()
        Item().load(annotation.get('itemId'),
                    user=user,
                    level=AccessType.READ)
        item = Item().load(itemId, user=user, level=AccessType.WRITE)
        return Annotation().createAnnotation(
            item, user, annotation['annotation'])

    @describeRoute(
        Description('Update an annotation or move it to a different item.')
        .param('id', 'The ID of the annotation.', paramType='path')
        .param('itemId', 'Pass this to move the annotation to a new item.',
               required=False)
        .param('body', 'A JSON object containing the annotation.  If the '
               '"annotation":"elements" property is not set, the elements '
               'will not be modified.',
               paramType='body', required=False)
        .errorResponse('Write access was denied for the item.', 403)
        .errorResponse('Invalid JSON passed in request body.')
        .errorResponse("Validation Error: JSON doesn't follow schema."),
    )
    @access.user(scope=TokenScope.DATA_WRITE)
    @loadmodel(model='annotation', plugin='large_image', level=AccessType.WRITE)
    @filtermodel(model='annotation', plugin='large_image')
    def updateAnnotation(self, annotation, params):
        # Set the response time limit to a very long value
        setResponseTimeLimit(86400)
        user = self.getCurrentUser()
        item = Item().load(annotation.get('itemId'), force=True)
        if item is not None:
            Item().hasAccessFlags(
                item, user, constants.ANNOTATION_ACCESS_FLAG) or Item().requireAccess(
                    item, user=user, level=AccessType.WRITE)
        # If we have a content length, then we have replacement JSON.  If
        # elements are not included, don't replace them
        returnElements = True
        if cherrypy.request.body.length:
            oldElements = annotation.get('annotation', {}).get('elements')
            annotation['annotation'] = self.getBodyJson()
            if 'elements' not in annotation['annotation'] and oldElements:
                annotation['annotation']['elements'] = oldElements
                returnElements = False
        if params.get('itemId'):
            newitem = Item().load(params['itemId'], force=True)
            Item().hasAccessFlags(
                newitem, user, constants.ANNOTATION_ACCESS_FLAG) or Item().requireAccess(
                    newitem, user=user, level=AccessType.WRITE)
            annotation['itemId'] = newitem['_id']
        try:
            annotation = Annotation().updateAnnotation(annotation, updateUser=user)
        except ValidationException as exc:
            logger.exception('Failed to validate annotation')
            raise RestException(
                "Validation Error: JSON doesn't follow schema (%r)." % (
                    exc.args, ))
        if not returnElements and 'elements' in annotation['annotation']:
            del annotation['annotation']['elements']
        return annotation

    @describeRoute(
        Description('Delete an annotation.')
        .param('id', 'The ID of the annotation.', paramType='path')
        .errorResponse('ID was invalid.')
        .errorResponse('Write access was denied for the annotation.', 403),
    )
    @access.user(scope=TokenScope.DATA_WRITE)
    # Load with a limit of 1 so that we don't bother getting most annotations
    @loadmodel(model='annotation', plugin='large_image', getElements=False, level=AccessType.WRITE)
    def deleteAnnotation(self, annotation, params):
        # Ensure that we have write access to the parent item
        item = Item().load(annotation.get('itemId'), force=True)
        if item is not None:
            user = self.getCurrentUser()
            Item().hasAccessFlags(
                item, user, constants.ANNOTATION_ACCESS_FLAG) or Item().requireAccess(
                    item, user, level=AccessType.WRITE)
        setResponseTimeLimit(86400)
        Annotation().remove(annotation)

    @describeRoute(
        Description('Search for annotated images.')
        .notes(
            'By default, this endpoint will return a list of recently annotated images.  '
            'This list can be further filtered by passing the creatorId and/or imageName '
            'parameters.  The creatorId parameter will limit results to annotations '
            'created by the given user.  The imageName parameter will only include '
            'images whose name (or a token in the name) begins with the given string.')
        .param('creatorId', 'Limit to annotations created by this user', required=False)
        .param('imageName', 'Filter results by image name (case-insensitive)', required=False)
        .pagingParams(defaultSort='updated', defaultSortDir=-1)
        .errorResponse(),
    )
    @access.public(scope=TokenScope.DATA_READ)
    def findAnnotatedImages(self, params):
        limit, offset, sort = self.getPagingParameters(
            params, 'updated', SortDir.DESCENDING)
        user = self.getCurrentUser()

        creator = None
        if 'creatorId' in params:
            creator = User().load(params.get('creatorId'), force=True)

        return Annotation().findAnnotatedImages(
            creator=creator, imageNameFilter=params.get('imageName'),
            user=user, level=AccessType.READ,
            offset=offset, limit=limit, sort=sort)

    @describeRoute(
        Description('Get the access control list for an annotation.')
        .param('id', 'The ID of the annotation.', paramType='path')
        .errorResponse('ID was invalid.')
        .errorResponse('Admin access was denied for the annotation.', 403),
    )
    @access.user(scope=TokenScope.DATA_OWN)
    @loadmodel(model='annotation', plugin='large_image', getElements=False, level=AccessType.ADMIN)
    def getAnnotationAccess(self, annotation, params):
        return Annotation().getFullAccessList(annotation)

    @describeRoute(
        Description('Update the access control list for an annotation.')
        .param('id', 'The ID of the annotation.', paramType='path')
        .param('access', 'The JSON-encoded access control list.')
        .param('public', 'Whether the annotation should be publicly visible.',
               dataType='boolean', required=False)
        .errorResponse('ID was invalid.')
        .errorResponse('Admin access was denied for the annotation.', 403),
    )
    @access.user(scope=TokenScope.DATA_OWN)
    @loadmodel(model='annotation', plugin='large_image', getElements=False, level=AccessType.ADMIN)
    @filtermodel(model=Annotation, addFields={'access'})
    def updateAnnotationAccess(self, annotation, params):
        access = json.loads(params['access'])
        public = self.boolParam('public', params, False)
        annotation = Annotation().setPublic(annotation, public)
        annotation = Annotation().setAccessList(
            annotation, access, save=False, user=self.getCurrentUser())
        Annotation().update({'_id': annotation['_id']}, {'$set': {
            key: annotation[key] for key in ('access', 'public', 'publicFlags')
            if key in annotation
        }})
        return annotation

    @autoDescribeRoute(
        Description("Get a list of an annotation's history.")
        .param('id', 'The ID of the annotation.', paramType='path')
        .pagingParams(defaultSort='_version', defaultLimit=0,
                      defaultSortDir=SortDir.DESCENDING)
        .errorResponse('Read access was denied for the annotation.', 403),
    )
    @access.public(cookie=True, scope=TokenScope.DATA_READ)
    def getAnnotationHistoryList(self, id, limit, offset, sort):
        return list(Annotation().versionList(id, self.getCurrentUser(), limit, offset, sort))

    @autoDescribeRoute(
        Description("Get a specific version of an annotation's history.")
        .param('id', 'The ID of the annotation.', paramType='path')
        .param('version', 'The version of the annotation.', paramType='path',
               dataType='integer')
        .errorResponse('Annotation history version not found.')
        .errorResponse('Read access was denied for the annotation.', 403),
    )
    @access.public(cookie=True, scope=TokenScope.DATA_READ)
    def getAnnotationHistory(self, id, version):
        result = Annotation().getVersion(id, version, self.getCurrentUser())
        if result is None:
            msg = 'Annotation history version not found.'
            raise RestException(msg)
        return result

    @autoDescribeRoute(
        Description('Revert an annotation to a specific version.')
        .notes('This can be used to undelete an annotation by reverting to '
               'the most recent version.')
        .param('id', 'The ID of the annotation.', paramType='path')
        .param('version', 'The version of the annotation.  If not specified, '
               'if the annotation was deleted this undeletes it.  If it was '
               'not deleted, this reverts to the previous version.',
               required=False, dataType='integer')
        .errorResponse('Annotation history version not found.')
        .errorResponse('Read access was denied for the annotation.', 403),
    )
    @access.public(scope=TokenScope.DATA_WRITE)
    def revertAnnotationHistory(self, id, version):
        setResponseTimeLimit(86400)
        annotation = Annotation().revertVersion(id, version, self.getCurrentUser())
        if not annotation:
            msg = 'Annotation history version not found.'
            raise RestException(msg)
        # Don't return the elements -- it can be too verbose
        if 'elements' in annotation['annotation']:
            del annotation['annotation']['elements']
        return annotation

    @autoDescribeRoute(
        Description('Get all annotations for an item.')
        .notes('This returns a list of annotation model records.')
        .modelParam('id', model=Item, level=AccessType.READ)
        .errorResponse('ID was invalid.')
        .errorResponse('Read access was denied for the item.', 403),
    )
    @access.public(cookie=True, scope=TokenScope.DATA_READ)
    def getItemAnnotations(self, item):
        user = self.getCurrentUser()
        query = {'_active': {'$ne': False}, 'itemId': item['_id']}

        def generateResult():
            yield b'['
            first = True
            for annotation in Annotation().find(query, limit=0, sort=[('_id', 1)]):
                if not first:
                    yield b',\n'
                try:
                    annotation = Annotation().load(
                        annotation['_id'], user=user, level=AccessType.READ, getElements=False)
                    annotationGenerator = self._getAnnotation(annotation, {})()
                except AccessException:
                    continue
                yield from annotationGenerator
                first = False
            yield b']'

        setResponseHeader('Content-Type', 'application/json')
        return generateResult

    @autoDescribeRoute(
        Description('Create multiple annotations on an item.')
        .modelParam('id', model=Item, level=AccessType.WRITE)
        # Use param instead of jsonParam; it lets us use a faster non-core json
        # library
        .param('annotations', 'A JSON list of annotation model records or '
               'annotations.  If these are complete models, the value of '
               'the "annotation" key is used and the other information is '
               'ignored (such as original creator ID).', paramType='body')
        .errorResponse('ID was invalid.')
        .errorResponse('Write access was denied for the item.', 403)
        .errorResponse('Invalid JSON passed in request body.')
        .errorResponse("Validation Error: JSON doesn't follow schema."),
    )
    @access.user(scope=TokenScope.DATA_WRITE)
    def createItemAnnotations(self, item, annotations):
        user = self.getCurrentUser()
        if hasattr(annotations, 'read'):
            startTime = time.time()
            annotations = annotations.read().decode('utf8')
            annotations = orjson.loads(annotations)
            if time.time() - startTime > 10:
                logger.info('Decoded json in %5.3fs', time.time() - startTime)
        if not isinstance(annotations, list):
            annotations = [annotations]
        for entry in annotations:
            if not isinstance(entry, dict):
                msg = 'Entries in the annotation list must be JSON objects.'
                raise RestException(msg)
            annotation = entry.get('annotation', entry)
            try:
                Annotation().createAnnotation(item, user, annotation)
            except ValidationException as exc:
                logger.exception('Failed to validate annotation')
                raise RestException(
                    "Validation Error: JSON doesn't follow schema (%r)." % (
                        exc.args, ))
        return len(annotations)

    @autoDescribeRoute(
        Description('Delete all annotations for an item.')
        .notes('This deletes all annotation model records.')
        .modelParam('id', model=Item, level=AccessType.WRITE)
        .errorResponse('ID was invalid.')
        .errorResponse('Write access was denied for the item.', 403),
    )
    @access.user(scope=TokenScope.DATA_WRITE)
    def deleteItemAnnotations(self, item):
        setResponseTimeLimit(86400)
        user = self.getCurrentUser()
        query = {'_active': {'$ne': False}, 'itemId': item['_id']}

        count = 0
        for annotation in Annotation().find(query, limit=0, sort=[('_id', 1)]):
            annot = Annotation().load(annotation['_id'], user=user, getElements=False)
            if annot:
                Annotation().remove(annot)
                count += 1
        return count

    @autoDescribeRoute(
        Description('Get a list of plottable data related to an item and its annotations.')
        .modelParam('id', model=Item, level=AccessType.READ)
        .param('adjacentItems', 'Whether to include adjacent item data.',
               required=False, default=False, enum=['false', 'true', '__all__'])
        .jsonParam('annotations', 'A JSON list of annotation IDs that should '
                   'be included.  An entry of \\__all__ will include all '
                   'annotations.', paramType='formData', requireArray=True,
                   required=False)
        .param('sources', 'An optional comma separated list that can contain '
               'folder, item, annotation, annotationelement, datafile.',
               required=False)
        .param('uuid', 'An optional uuid to allow cancelling a previous '
               'request.  If specified and there are any outstanding requests '
               'with the same uuid, they may be cancelled to save resources.',
               required=False)
        .errorResponse('ID was invalid.')
        .errorResponse('Read access was denied for the item.', 403),
    )
    @access.public(cookie=True, scope=TokenScope.DATA_READ)
    def getItemPlottableElements(self, item, annotations, adjacentItems, sources=None, uuid=None):
        user = self.getCurrentUser()
        if adjacentItems != '__all__':
            adjacentItems = str(adjacentItems).lower() == 'true'
        sources = sources or None
        data = utils.PlottableItemData(
            user, item, annotations=annotations, adjacentItems=adjacentItems,
            sources=sources, uuid=uuid)
        return [col for col in data.columns if col.get('count')]

    @autoDescribeRoute(
        Description('Get plottable data related to an item and its annotations.')
        .modelParam('id', model=Item, level=AccessType.READ)
        .param('adjacentItems', 'Whether to include adjacent item data.',
               required=False, default=False, enum=['false', 'true', '__all__'])
        .param('keys', 'A comma separated list of data keys to retrieve (not json).',
               required=True)
        .param('requiredKeys', 'A comma separated list of data keys that must '
               'be non null in all response rows (not json).', required=False)
        .jsonParam('annotations', 'A JSON list of annotation IDs that should '
                   'be included.  An entry of \\__all__ will include all '
                   'annotations.', paramType='formData', requireArray=True,
                   required=False)
        .param('sources', 'An optional comma separated list that can contain '
               'folder, item, annotation, annotationelement, datafile.',
               required=False)
        .jsonParam(
            'compute', 'A dictionary with keys "columns": a list of columns '
            'to include in the computation; if unspecified or an empty list, '
            'no computation is done, "function": a string with the name of '
            'the function, such as umap, "params": additional parameters to '
            'pass to the function.  If none of the requiredKeys are '
            'compute.(x|y|z), the computation will not be performed.  Only '
            'rows which have all selected columns present will be included in '
            'the computation.',
            paramType='formData', requireObject=True, required=False)
        .param('uuid', 'An optional uuid to allow cancelling a previous '
               'request.  If specified and there are any outstanding requests '
               'with the same uuid, they may be cancelled to save resources.',
               required=False)
        .errorResponse('ID was invalid.')
        .errorResponse('Read access was denied for the item.', 403),
    )
    @access.public(cookie=True, scope=TokenScope.DATA_READ)
    def getItemPlottableData(
            self, item, keys, adjacentItems, annotations, requiredKeys,
            sources=None, compute=None, uuid=None):
        user = self.getCurrentUser()
        if adjacentItems != '__all__':
            adjacentItems = str(adjacentItems).lower() == 'true'
        sources = sources or None
        data = utils.PlottableItemData(
            user, item, annotations=annotations, adjacentItems=adjacentItems,
            sources=sources, compute=compute, uuid=uuid)
        return data.data(keys, requiredKeys)

    def getFolderAnnotations(self, id, recurse, user, limit=False, offset=False, sort=False,
                             sortDir=False, count=False):

        accessPipeline = [
            {'$match': {
                '$or': [
                    {'access.users':
                        {'$elemMatch': {
                            'id': user['_id'],
                            'level': {'$gte': 2},
                        }}},
                    {'access.groups':
                        {'$elemMatch': {
                            'id': {'$in': user['groups']},
                            'level': {'$gte': 2},
                        }}},
                ],
            }},
        ] if not user['admin'] else []
        recursivePipeline = [
            {'$match': {'_id': ObjectId(id)}},
            {'$graphLookup': {
                'from': 'folder',
                'startWith': ObjectId(id),
                'connectFromField': '_id',
                'connectToField': 'parentId',
                'as': '__children',
            }},
            {'$lookup': {
                'from': 'folder',
                'localField': '_id',
                'foreignField': '_id',
                'as': '__self',
            }},
            {'$project': {'__children': {'$concatArrays': [
                '$__self', '$__children',
            ]}}},
            {'$unwind': {'path': '$__children'}},
            {'$replaceRoot': {'newRoot': '$__children'}},
        ] if recurse else [{'$match': {'_id': ObjectId(id)}}]

        # We are only finding anntoations that we can change the permissions
        # on.  If we wanted to expose annotations based on a permissions level,
        # we need to add a folder access pipeline immediately after the
        # recursivePipleine that for write and above would include the
        # ANNOTATION_ACCSESS_FLAG
        pipeline = recursivePipeline + [
            {'$lookup': {
                'from': 'item',
                # We have to use a pipeline to use a projection to reduce the
                # data volume, so instead of specifying localField and
                # foreignField, we set the localField to a variable, then match
                # it in a pipeline and project to exclude everything but id.
                # 'localField': '_id',
                # 'foreignField': 'folderId',
                'let': {'fid': '$_id'},
                'pipeline': [
                    {'$match': {'$expr': {'$eq': ['$$fid', '$folderId']}}},
                    {'$project': {'_id': 1}},
                ],
                'as': '__items',
            }},
            {'$lookup': {
                'from': 'annotation',
                'localField': '__items._id',
                'foreignField': 'itemId',
                'as': '__annotations',
            }},
            {'$unwind': '$__annotations'},
            {'$replaceRoot': {'newRoot': '$__annotations'}},
            {'$match': {'_active': {'$ne': False}}},
        ] + accessPipeline

        if count:
            pipeline += [{'$count': 'count'}]
        else:
            pipeline = pipeline + [{'$sort': {sort: sortDir}}] if sort else pipeline
            pipeline = pipeline + [{'$skip': offset}] if offset else pipeline
            pipeline = pipeline + [{'$limit': limit}] if limit else pipeline
        return Folder().collection.aggregate(pipeline)

    @autoDescribeRoute(
        Description('Check if the user owns any annotations for the items in a folder')
        .param('id', 'The ID of the folder', required=True, paramType='path')
        .param('recurse', 'Whether or not to recursively check '
               'subfolders for annotations', required=False, default=True, dataType='boolean')
        .errorResponse(),
    )
    @access.public(scope=TokenScope.DATA_READ)
    def existFolderAnnotations(self, id, recurse):
        user = self.getCurrentUser()
        if not user:
            return []
        annotations = self.getFolderAnnotations(id, recurse, user, 1)
        try:
            next(annotations)
            return True
        except StopIteration:
            return False

    @autoDescribeRoute(
        Description('Get the user-owned annotations from the items in a folder')
        .param('id', 'The ID of the folder', required=True, paramType='path')
        .param('recurse', 'Whether or not to retrieve all '
               'annotations from subfolders', required=False, default=False, dataType='boolean')
        .pagingParams(defaultSort='created', defaultSortDir=-1)
        .errorResponse(),
    )
    @access.public(scope=TokenScope.DATA_READ)
    def returnFolderAnnotations(self, id, recurse, limit, offset, sort):
        user = self.getCurrentUser()
        if not user:
            return []
        annotations = self.getFolderAnnotations(id, recurse, user, limit, offset,
                                                sort[0][0], sort[0][1])

        def count():
            try:
                return next(self.getFolderAnnotations(id, recurse, self.getCurrentUser(),
                                                      count=True))['count']
            except StopIteration:
                # If there are no values to iterate over, the count is 0 and should be returned
                return 0

        annotations.count = count
        return annotations

    @autoDescribeRoute(
        Description('Check if the user can create annotations in a folder')
        .param('id', 'The ID of the folder', required=True, paramType='path')
        .errorResponse('ID was invalid.'),
    )
    @access.user(scope=TokenScope.DATA_READ)
    @loadmodel(model='folder', level=AccessType.READ)
    def canCreateFolderAnnotations(self, folder):
        user = self.getCurrentUser()
        return Folder().hasAccess(folder, user, AccessType.WRITE) or Folder().hasAccessFlags(
            folder, user, constants.ANNOTATION_ACCESS_FLAG)

    @autoDescribeRoute(
        Description('Set the access for all the user-owned annotations from the items in a folder')
        .param('id', 'The ID of the folder', required=True, paramType='path')
        .param('access', 'The JSON-encoded access control list.')
        .param('public', 'Whether the annotation should be publicly visible.',
               dataType='boolean', required=False)
        .param('recurse', 'Whether or not to retrieve all '
               'annotations from subfolders', required=False, default=False, dataType='boolean')
        .errorResponse('ID was invalid.'),
    )
    @access.user(scope=TokenScope.DATA_OWN)
    def setFolderAnnotationAccess(self, id, params):
        setResponseTimeLimit(86400)
        user = self.getCurrentUser()
        if not user:
            return []
        access = json.loads(params['access'])
        public = self.boolParam('public', params, False)
        count = 0
        for annotation in self.getFolderAnnotations(id, params['recurse'], user):
            annot = Annotation().load(annotation['_id'], user=user, getElements=False)
            annot = Annotation().setPublic(annot, public)
            annot = Annotation().setAccessList(
                annot, access, user=user)
            Annotation().update({'_id': annot['_id']}, {'$set': {
                key: annot[key] for key in ('access', 'public', 'publicFlags')
                if key in annot
            }})
            count += 1

        return {'updated': count}

    @autoDescribeRoute(
        Description('Delete all user-owned annotations from the items in a folder')
        .param('id', 'The ID of the folder', required=True, paramType='path')
        .param('recurse', 'Whether or not to retrieve all '
               'annotations from subfolders', required=False, default=False, dataType='boolean')
        .errorResponse('ID was invalid.'),
    )
    @access.user(scope=TokenScope.DATA_WRITE)
    def deleteFolderAnnotations(self, id, params):
        setResponseTimeLimit(86400)
        user = self.getCurrentUser()
        if not user:
            return []
        count = 0
        for annotation in self.getFolderAnnotations(id, params['recurse'], user):
            annot = Annotation().load(annotation['_id'], user=user, getElements=False)
            Annotation().remove(annot)
            count += 1

        return {'deleted': count}

    @autoDescribeRoute(
        Description('Report on old annotations.')
        .param('age', 'The minimum age in days.', required=False,
               dataType='int', default=30)
        .param('versions', 'Keep at least this many history entries for each '
               'annotation.', required=False, dataType='int', default=10)
        .errorResponse(),
    )
    @access.admin(scope=TokenScope.DATA_READ)
    def getOldAnnotations(self, age, versions):
        setResponseTimeLimit(86400)
        return Annotation().removeOldAnnotations(False, age, versions)

    @autoDescribeRoute(
        Description('Delete old annotations.')
        .param('age', 'The minimum age in days.', required=False,
               dataType='int', default=30)
        .param('versions', 'Keep at least this many history entries for each '
               'annotation.', required=False, dataType='int', default=10)
        .errorResponse(),
    )
    @access.admin(scope=TokenScope.DATA_WRITE)
    def deleteOldAnnotations(self, age, versions):
        setResponseTimeLimit(86400)
        return Annotation().removeOldAnnotations(True, age, versions)

    @access.public(scope=TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description('Get annotation counts for a list of items.')
        .param('items', 'A comma-separated list of item ids.')
        .errorResponse(),
    )
    def getItemListAnnotationCounts(self, items):
        user = self.getCurrentUser()
        results = {}
        for itemId in items.split(','):
            item = Item().load(itemId, level=AccessType.READ, user=user)
            annotations = Annotation().findWithPermissions(
                {'_active': {'$ne': False}, 'itemId': item['_id']},
                user=self.getCurrentUser(), level=AccessType.READ, limit=-1)
            results[itemId] = annotations.count()
            if Annotationelement().findOne({'element.girderId': itemId}):
                if 'referenced' not in results:
                    results['referenced'] = {}
                results['referenced'][itemId] = True
        return results

    @access.user(scope=TokenScope.DATA_WRITE)
    @filtermodel(model='annotation', plugin='large_image')
    @autoDescribeRoute(
        Description('Set metadata (annotation.attributes) fields on an annotation.')
        .responseClass('Annotation')
        .notes('Set metadata fields to null in order to delete them.')
        .param('id', 'The ID of the annotation.', paramType='path')
        .jsonParam('metadata', 'A JSON object containing the metadata keys to add',
                   paramType='body', requireObject=True)
        .param('allowNull', 'Whether "null" is allowed as a metadata value.', required=False,
               dataType='boolean', default=False)
        .errorResponse(('ID was invalid.',
                        'Invalid JSON passed in request body.',
                        'Metadata key name was invalid.'))
        .errorResponse('Write access was denied for the annotation.', 403),
    )
    @loadmodel(model='annotation', plugin='large_image', getElements=False, level=AccessType.WRITE)
    def setMetadata(self, annotation, metadata, allowNull):
        return Annotation().setMetadata(annotation, metadata, allowNull=allowNull)

    @access.user(scope=TokenScope.DATA_WRITE)
    @filtermodel(model='annotation', plugin='large_image')
    @autoDescribeRoute(
        Description('Delete metadata (annotation.attributes) fields on an annotation.')
        .responseClass('Item')
        .param('id', 'The ID of the annotation.', paramType='path')
        .jsonParam(
            'fields', 'A JSON list containing the metadata fields to delete',
            paramType='body', schema={
                'type': 'array',
                'items': {
                    'type': 'string',
                },
            },
        )
        .errorResponse(('ID was invalid.',
                        'Invalid JSON passed in request body.',
                        'Metadata key name was invalid.'))
        .errorResponse('Write access was denied for the annotation.', 403),
    )
    @loadmodel(model='annotation', plugin='large_image', getElements=False, level=AccessType.WRITE)
    def deleteMetadata(self, annotation, fields):
        return Annotation().deleteMetadata(annotation, fields)
