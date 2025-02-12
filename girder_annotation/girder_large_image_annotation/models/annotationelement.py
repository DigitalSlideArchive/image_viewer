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

import concurrent.futures
import datetime
import io
import logging
import math
import pickle
import threading
import time

import pymongo
from girder_large_image.models.image_item import ImageItem

import large_image
from girder.constants import AccessType, SortDir
from girder.models.file import File
from girder.models.item import Item
from girder.models.model_base import Model
from girder.models.upload import Upload

# Some annotation elements can be very large.  If they pass a size threshold,
# store part of them in an associated file.  This is slower, so don't do it for
# small ones.
MAX_ELEMENT_CHECK = 100
MAX_ELEMENT_DOCUMENT = 10000
MAX_ELEMENT_USER_DOCUMENT = 1000000

logger = logging.getLogger(__name__)


class Annotationelement(Model):
    bboxKeys = {
        'left': ('bbox.highx', '$gte'),
        'right': ('bbox.lowx', '$lt'),
        'top': ('bbox.highy', '$gte'),
        'bottom': ('bbox.lowy', '$lt'),
        'low': ('bbox.highz', '$gte'),
        'high': ('bbox.lowz', '$lt'),
        'minimumSize': ('bbox.size', '$gte'),
        'size': ('bbox.size', None),
        'details': ('bbox.details', None),
    }

    def initialize(self):
        self.name = 'annotationelement'
        self.ensureIndices([
            'annotationId',
            '_version',
            ([
                ('annotationId', SortDir.ASCENDING),
                ('bbox.lowx', SortDir.DESCENDING),
                ('bbox.highx', SortDir.ASCENDING),
                ('bbox.size', SortDir.DESCENDING),
            ], {
                'name': 'annotationBboxIdx',
            }),
            ([
                ('annotationId', SortDir.ASCENDING),
                ('bbox.size', SortDir.DESCENDING),
            ], {
                'name': 'annotationBboxSizeIdx',
            }),
            ([
                ('annotationId', SortDir.ASCENDING),
                ('_version', SortDir.DESCENDING),
                ('element.group', SortDir.ASCENDING),
            ], {
                'name': 'annotationGroupIdx',
            }),
            ([
                ('annotationId', SortDir.ASCENDING),
                ('_version', SortDir.DESCENDING),
                ('_id', SortDir.ASCENDING),
            ], {
                'name': 'annotationElementIdIdx',
            }),
            ([
                ('created', SortDir.ASCENDING),
                ('_version', SortDir.ASCENDING),
            ], {}),
            'element.girderId',
        ])

        self.exposeFields(AccessType.READ, (
            '_id', '_version', 'annotationId', 'created', 'element'))
        self.versionId = None

    def getNextVersionValue(self):
        """
        Maintain a version number.  This is a single sequence that can be used
        to ensure we have the correct set of elements for an annotation.

        :returns: an integer version number that is strictly increasing.
        """
        version = None
        if self.versionId is not None:
            version = self.collection.find_one_and_update(
                {'_id': self.versionId},
                {'$inc': {'_version': 1}})
        if version is None:
            versionObject = self.collection.find_one(
                {'annotationId': 'version_sequence'})
            if versionObject is None:
                startingId = self.collection.find_one({}, sort=[('_version', SortDir.DESCENDING)])
                startingId = startingId['_version'] + 1 if startingId else 0
                self.versionId = self.collection.insert_one(
                    {'annotationId': 'version_sequence', '_version': startingId},
                ).inserted_id
            else:
                self.versionId = versionObject['_id']
            version = self.collection.find_one_and_update(
                {'_id': self.versionId},
                {'$inc': {'_version': 1}})
        return version['_version']

    def getElements(self, annotation, region=None):
        """
        Given an annotation, fetch the elements from the database and add them
        to it.

        When a region is used to request specific element, the following
        keys can be specified:

            :left, right, top, bottom, low, high: the spatial area where
                elements are located, all in pixels.  If an element's bounding
                box is at least partially within the requested area, that
                element is included.
            :minimumSize: the minimum size of an element to return.
            :sort, sortdir: standard sort options.  The sort key can include
                size and details.
            :limit: limit the total number of elements by this value.  Defaults
                to no limit.
            :offset: the offset within the query to start returning values.  If
                maxDetails is used, to get subsequent sets of elements, the
                offset needs to be increased by the actual number of elements
                returned from a previous query, which will vary based on the
                details of the elements.
            :maxDetails: if specified, limit the total number of elements by
                the sum of their details values.  This is applied in addition
                to limit.  The sum of the details values of the elements may
                exceed maxDetails slightly (the sum of all but the last element
                will be less than maxDetails, but the last element may exceed
                the value).
            :minElements: if maxDetails is specified, always return this many
                elements even if they are very detailed.
            :centroids: if specified and true, only return the id, center of
                the bounding box, and bounding box size for each element.

        :param annotation: the annotation to get elements for.  Modified.
        :param region: if present, a dictionary restricting which annotations
            are returned.
        """
        annotation['_elementQuery'] = {}
        annotation['annotation']['elements'] = list(self.yieldElements(
            annotation, region, annotation['_elementQuery']))

    def countElements(self, annotation):
        query = {
            'annotationId': annotation.get('_annotationId', annotation['_id']),
            '_version': annotation['_version'],
        }
        return self.collection.count_documents(query)

    def yieldElements(self, annotation, region=None, info=None, bbox=False):  # noqa
        """
        Given an annotation, fetch the elements from the database.

        When a region is used to request specific element, the following
        keys can be specified:

            :left, right, top, bottom, low, high: the spatial area where
                elements are located, all in pixels.  If an element's bounding
                box is at least partially within the requested area, that
                element is included.
            :minimumSize: the minimum size of an element to return.
            :sort, sortdir: standard sort options.  The sort key can include
                size and details.
            :limit: limit the total number of elements by this value.  Defaults
                to no limit.
            :offset: the offset within the query to start returning values.  If
                maxDetails is used, to get subsequent sets of elements, the
                offset needs to be increased by the actual number of elements
                returned from a previous query, which will vary based on the
                details of the elements.
            :maxDetails: if specified, limit the total number of elements by
                the sum of their details values.  This is applied in addition
                to limit.  The sum of the details values of the elements may
                exceed maxDetails slightly (the sum of all but the last element
                will be less than maxDetails, but the last element may exceed
                the value).
            :minElements: if maxDetails is specified, always return this many
                elements even if they are very detailed.
            :centroids: if specified and true, only return the id, center of
                the bounding box, and bounding box size for each element.
            :bbox: if specified and true and centroids are not specified,
                add _bbox to each element with the bounding box record.

        :param annotation: the annotation to get elements for.  Modified.
        :param region: if present, a dictionary restricting which annotations
            are returned.
        :param info: an optional dictionary that will be modified with
            additional query information, including count (total number of
            available elements), returned (number of elements in response),
            maxDetails (as specified by the region dictionary), details (sum of
            details returned), limit (as specified by region), centroids (a
            boolean based on the region specification).
        :param bbox: if True, always return bounding box information.
        :returns: a list of elements.  If centroids were requested, each entry
            is a list with str(id), x, y, size.  Otherwise, each entry is the
            element record.
        """
        info = info if info is not None else {}
        region = region or {}
        query = {
            'annotationId': annotation.get('_annotationId', annotation['_id']),
            '_version': annotation['_version'],
        }
        for key in region:
            if key in self.bboxKeys and self.bboxKeys[key][1]:
                if self.bboxKeys[key][1] == '$gte' and float(region[key]) <= 0:
                    continue
                query[self.bboxKeys[key][0]] = {
                    self.bboxKeys[key][1]: float(region[key])}
        if region.get('sort') in self.bboxKeys:
            sortkey = self.bboxKeys[region['sort']][0]
        else:
            sortkey = region.get('sort') or '_id'
        sortdir = int(region['sortdir']) if region.get('sortdir') else SortDir.ASCENDING
        limit = int(region['limit']) if region.get('limit') else 0
        maxDetails = int(region.get('maxDetails') or 0)
        minElements = int(region.get('minElements') or 0)
        queryLimit = max(minElements, maxDetails) if maxDetails and (
            not limit or max(minElements, maxDetails) < limit) else limit
        offset = int(region['offset']) if region.get('offset') else 0
        logger.debug('element query %r for %r', query, region)
        fields = {'_id': True, 'element': True, 'bbox.details': True, 'datafile': True}
        centroids = str(region.get('centroids')).lower() == 'true'
        if centroids:
            # fields = {'_id': True, 'element': True, 'bbox': True}
            fields = {
                '_id': True,
                'element.id': True,
                'bbox': True}
            proplist = []
            propskeys = ['type', 'fillColor', 'lineColor', 'lineWidth', 'closed']
            # This should match the javascript
            defaultProps = {
                'fillColor': 'rgba(0,0,0,0)',
                'lineColor': 'rgb(0,0,0)',
                'lineWidth': 2,
            }
            for key in propskeys:
                fields['element.%s' % key] = True
            props = {}
            info['centroids'] = True
            info['props'] = proplist
            info['propskeys'] = propskeys
        elif region.get('bbox'):
            fields.pop('bbox.details')
            fields['bbox'] = True
        if bbox:
            fields.pop('bbox.details', None)
            fields['bbox'] = True
        elementCursor = self.find(
            query=query, sort=[(sortkey, sortdir)], limit=queryLimit,
            offset=offset, fields=fields)

        info.update({
            'count': elementCursor.count(),
            'offset': offset,
            'filter': query,
            'sort': [sortkey, sortdir],
        })
        details = count = 0
        if maxDetails:
            info['maxDetails'] = maxDetails
        if minElements:
            info['minElements'] = minElements
        if limit:
            info['limit'] = limit
        for entry in elementCursor:
            element = entry['element']
            element.setdefault('id', entry['_id'])
            if centroids:
                bbox = entry.get('bbox')
                if not bbox or 'lowx' not in bbox or 'size' not in bbox:
                    continue
                prop = tuple(
                    element.get(key, defaultProps.get(key)) for key in propskeys
                    if element.get(key, defaultProps.get(key)) is not None)
                if prop not in props:
                    props[prop] = len(props)
                    proplist.append(list(prop))
                yield [
                    str(element['id']),
                    (bbox['lowx'] + bbox['highx']) / 2,
                    (bbox['lowy'] + bbox['highy']) / 2,
                    bbox['size'] if entry.get('type') != 'point' else 0,
                    props[prop],
                ]
                details += 1
            else:
                if entry.get('datafile'):
                    datafile = entry['datafile']
                    data = io.BytesIO()
                    chunksize = 1024 ** 2
                    with File().open(File().load(datafile['fileId'], force=True)) as fptr:
                        while True:
                            chunk = fptr.read(chunksize)
                            if not len(chunk):
                                break
                            data.write(chunk)
                    data.seek(0)
                    element[datafile['key']] = pickle.load(data)
                    if 'userFileId' in datafile:
                        data = io.BytesIO()
                        chunksize = 1024 ** 2
                        with File().open(File().load(datafile['userFileId'], force=True)) as fptr:
                            while True:
                                chunk = fptr.read(chunksize)
                                if not len(chunk):
                                    break
                                data.write(chunk)
                        data.seek(0)
                        element['user'] = pickle.load(data)
                if region.get('bbox') and 'bbox' in entry:
                    element['_bbox'] = entry['bbox']
                    if 'bbox' not in info:
                        info['bbox'] = {}
                    for axis in {'x', 'y', 'z'}:
                        lkey, hkey = 'low' + axis, 'high' + axis
                        if lkey in entry['bbox'] and hkey in entry['bbox']:
                            info['bbox'][lkey] = min(
                                info['bbox'].get(lkey, entry['bbox'][lkey]), entry['bbox'][lkey])
                            info['bbox'][hkey] = max(
                                info['bbox'].get(hkey, entry['bbox'][hkey]), entry['bbox'][hkey])
                elif bbox and 'bbox' in entry:
                    element['_bbox'] = entry['bbox']
                yield element
                details += entry.get('bbox', {}).get('details', 1)
            count += 1
            if maxDetails and details >= maxDetails and count >= minElements:
                break
        info['returned'] = count
        info['details'] = details

    def removeWithQuery(self, query):
        """
        Remove all documents matching a given query from the collection.
        For safety reasons, you may not pass an empty query.

        Note: this does NOT return a Mongo DeleteResult.

        :param query: The search query for documents to delete,
            see general MongoDB docs for "find()"
        :type query: dict
        """
        if not query:
            msg = 'query must be specified'
            raise Exception(msg)

        attachedQuery = query.copy()
        attachedQuery['datafile'] = {'$exists': True}
        for element in self.collection.find(attachedQuery):
            for key in {'fileId', 'userFileId'}:
                if key in element['datafile']:
                    file = File().load(element['datafile'][key], force=True)
                    if file:
                        File().remove(file)
        self.collection.bulk_write([pymongo.DeleteMany(query)], ordered=False)

    def removeElements(self, annotation):
        """
        Remove all elements related to the specified annotation.

        :param annotation: the annotation to remove elements from.
        """
        self.removeWithQuery({'annotationId': annotation['_id']})

    def removeOldElements(self, annotation, oldversion=None):
        """
        Remove all elements related to the specified annotation.

        :param annotation: the annotation to remove elements from.
        :param oldversion: if present, remove versions up to this number.  If
                           none, remove versions earlier than the version in
                           the annotation record.
        """
        query = {'annotationId': annotation['_id']}
        if oldversion is None or oldversion >= annotation['_version']:
            query['_version'] = {'$lt': annotation['_version']}
        else:
            query['_version'] = {'$lte': oldversion}
        self.removeWithQuery(query)

    def _overlayBounds(self, overlayElement):
        """
        Compute bounding box information in the X-Y plane for an
        image overlay element.

        This uses numpy to perform the specified transform on the given girder
        image item in order to obtain bounding box coordinates.

        :param overlayElement: An annotation element of type 'image'.
        :returns: a tuple with 4 values: lowx, highx, lowy, highy. Runtime exceptions
         during loading the image metadata will result in the tuple (0, 0, 0, 0).
        """
        if overlayElement.get('type') not in ['image', 'pixelmap']:
            msg = ('Function _overlayBounds only accepts annotation elements '
                   'of type "image", "pixelmap."')
            raise ValueError(msg)

        import numpy as np
        lowx = highx = lowy = highy = 0

        try:
            overlayItemId = overlayElement.get('girderId')
            imageItem = ImageItem().load(overlayItemId, force=True)
            overlayImageMetadata = ImageItem().getMetadata(imageItem)
            corners = [
                [0, 0],
                [0, overlayImageMetadata['sizeY']],
                [overlayImageMetadata['sizeX'], overlayImageMetadata['sizeY']],
                [overlayImageMetadata['sizeX'], 0],
            ]
            transform = overlayElement.get('transform', {})
            transformMatrix = np.array(transform.get('matrix', [[1, 0], [0, 1]]))
            corners = [np.matmul(np.array(corner), transformMatrix) for corner in corners]
            offsetArray = np.array([transform.get('xoffset', 0), transform.get('yoffset', 0)])
            corners = [np.add(corner, offsetArray) for corner in corners]
            # use .item() to convert back to native python types
            lowx = min([corner[0] for corner in corners]).item()
            highx = max([corner[0] for corner in corners]).item()
            lowy = min([corner[1] for corner in corners]).item()
            highy = max([corner[1] for corner in corners]).item()
        except Exception:
            logger.exception('Error generating bounding box for image overlay annotation')
        return lowx, highx, lowy, highy

    def _boundingBox(self, element):
        """
        Compute bounding box information for an annotation element.

        This computes the enclosing bounding box of an element.  For points, an
        small non-zero-area region is used centered on the point.
        Additionally, a metric is stored for the complexity of the element.
        The size of the bounding box's x-y diagonal is also stored.

        :param element: the element to compute the bounding box for.
        :returns: the bounding box dictionary.  This contains 'lowx', 'lowy',
            'lowz', 'highx', 'highy', and 'highz, which are the minimum and
            maximum values in each dimension, 'details' with the complexity of
            the element, and 'size' with the x-y diagonal size of the bounding
            box.
        """
        bbox = {}
        if 'points' in element:
            pts = element['points']
            p0 = [p[0] for p in pts]
            p1 = [p[1] for p in pts]
            p2 = [p[2] for p in pts]
            bbox['lowx'] = min(p0)
            bbox['lowy'] = min(p1)
            bbox['lowz'] = min(p2)
            bbox['highx'] = max(p0)
            bbox['highy'] = max(p1)
            bbox['highz'] = max(p2)
            bbox['details'] = len(pts)
        elif element.get('type') == 'griddata':
            x0, y0, z = element['origin']
            isElements = element.get('interpretation') == 'choropleth'
            x1 = x0 + element['dx'] * (element['gridWidth'] - (1 if not isElements else 0))
            y1 = y0 + element['dy'] * (math.ceil(len(element['values']) / element['gridWidth']) -
                                       (1 if not isElements else 0))
            bbox['lowx'] = min(x0, x1)
            bbox['lowy'] = min(y0, y1)
            bbox['lowz'] = bbox['highz'] = z
            bbox['highx'] = max(x0, x1)
            bbox['highy'] = max(y0, y1)
            bbox['details'] = len(element['values'])
        elif element.get('type') in ['image', 'pixelmap']:
            lowx, highx, lowy, highy = Annotationelement()._overlayBounds(element)
            bbox['lowz'] = bbox['highz'] = 0
            bbox['lowx'] = lowx
            bbox['highx'] = highx
            bbox['lowy'] = lowy
            bbox['highy'] = highy
            bbox['details'] = 1
        else:
            center = element['center']
            bbox['lowz'] = bbox['highz'] = center[2]
            if 'width' in element:
                w = element['width'] * 0.5
                h = element['height'] * 0.5
                if element.get('rotation'):
                    absin = abs(math.sin(element['rotation']))
                    abcos = abs(math.cos(element['rotation']))
                    w, h = max(abcos * w, absin * h), max(absin * w, abcos * h)
                bbox['lowx'] = center[0] - w
                bbox['lowy'] = center[1] - h
                bbox['highx'] = center[0] + w
                bbox['highy'] = center[1] + h
                bbox['details'] = 4
            elif 'radius' in element:
                rad = element['radius']
                bbox['lowx'] = center[0] - rad
                bbox['lowy'] = center[1] - rad
                bbox['highx'] = center[0] + rad
                bbox['highy'] = center[1] + rad
                bbox['details'] = 4
            else:
                # This is a fall back for points.  Although they have no
                # dimension, make the bounding box have some extent.
                bbox['lowx'] = center[0] - 0.5
                bbox['lowy'] = center[1] - 0.5
                bbox['highx'] = center[0] + 0.5
                bbox['highy'] = center[1] + 0.5
                bbox['details'] = 1
        bbox['size'] = (
            (bbox['highy'] - bbox['lowy'])**2 +
            (bbox['highx'] - bbox['lowx'])**2) ** 0.5
        # we may want to store perimeter or area as that could help when we
        # simplify to points
        return bbox

    def _entryIsLarge(self, entry):
        """
        Return True is an entry is alrge enough it might not fit in a mongo
        document.

        :param entry: the entry to check.
        :returns: True if the entry is large.
        """
        if len(entry['element'].get('points', entry['element'].get(
                'values', []))) > MAX_ELEMENT_DOCUMENT:
            return True
        if ('user' in entry['element'] and
                len(pickle.dumps(entry['element'], protocol=4)) > MAX_ELEMENT_USER_DOCUMENT):
            return True
        return False

    def saveElementAsFile(self, annotation, entries):
        """
        If an element has a large points or values array, save that array to an
        attached file.

        :param annotation: the parent annotation.
        :param entries: the database entries document.  Modified.
        """
        item = Item().load(annotation['itemId'], force=True)
        for idx, entry in enumerate(entries[:MAX_ELEMENT_CHECK]):
            if not self._entryIsLarge(entry):
                continue
            element = entry['element'].copy()
            entries[idx]['element'] = element
            key = 'points' if 'points' in element else 'values'
            # Use the highest protocol support by all python versions we
            # support
            data = pickle.dumps(element.pop(key), protocol=4)
            elementFile = Upload().uploadFromFile(
                io.BytesIO(data), size=len(data), name='_annotationElementData',
                parentType='item', parent=item, user=None,
                mimeType='application/json', attachParent=True)
            userdata = None
            if 'user' in element:
                userdata = pickle.dumps(element.pop('user'), protocol=4)
                userFile = Upload().uploadFromFile(
                    io.BytesIO(userdata), size=len(userdata), name='_annotationElementUserData',
                    parentType='item', parent=item, user=None,
                    mimeType='application/json', attachParent=True)
            entry['datafile'] = {
                'key': key,
                'fileId': elementFile['_id'],
            }
            if userdata:
                entry['datafile']['userFileId'] = userFile['_id']
            logger.debug('Storing element as file (%r)', entry)

    def updateElementChunk(self, elements, chunk, chunkSize, annotation, now, insertLock):
        """
        Update the database for a chunk of elements.  See the updateElements
        method for details.
        """
        lastTime = time.time()
        chunkStartTime = time.time()
        entries = [{
            'annotationId': annotation['_id'],
            '_version': annotation['_version'],
            'created': now,
            'bbox': self._boundingBox(element),
            'element': element,
        } for element in elements[chunk:chunk + chunkSize]]
        prepTime = time.time() - chunkStartTime
        if (len(entries) <= MAX_ELEMENT_CHECK and any(
                self._entryIsLarge(entry) for entry in entries[:MAX_ELEMENT_CHECK])):
            self.saveElementAsFile(annotation, entries)
        with insertLock:
            res = self.collection.insert_many(entries, ordered=False)
        for pos, entry in enumerate(entries):
            if 'id' not in entry['element']:
                entry['element']['id'] = str(res.inserted_ids[pos])
        # If the insert is slow, log information about it.
        if time.time() - lastTime > 10:
            logger.info('insert %d elements in %4.2fs (prep time %4.2fs), chunk %d/%d' % (
                len(entries), time.time() - chunkStartTime, prepTime,
                chunk + len(entries), len(elements)))
            lastTime = time.time()

    def updateElements(self, annotation):
        """
        Given an annotation, extract the elements from it and update the
        database of them.

        :param annotation: the annotation to save elements for.  Modified.
        """
        startTime = time.time()
        elements = annotation['annotation'].get('elements', [])
        if not len(elements):
            return
        now = datetime.datetime.now(datetime.timezone.utc)
        threads = large_image.config.cpu_count()
        chunkSize = int(max(100000 // threads, 10000))
        insertLock = threading.Lock()
        with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as pool:
            for chunk in range(0, len(elements), chunkSize):
                pool.submit(self.updateElementChunk, elements, chunk,
                            chunkSize, annotation, now, insertLock)
        if time.time() - startTime > 10:
            logger.info('inserted %d elements in %4.2fs' % (
                len(elements), time.time() - startTime))

    def getElementGroupSet(self, annotation):
        query = {
            'annotationId': annotation.get('_annotationId', annotation['_id']),
            '_version': annotation['_version'],
        }
        groups = sorted([
            group for group in self.collection.distinct('element.group', filter=query)
            if isinstance(group, str)
        ])
        query['element.group'] = None
        if self.collection.find_one(query):
            groups.append(None)
        return groups
