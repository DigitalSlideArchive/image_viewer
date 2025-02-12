import json
import logging
import time
import uuid

import cachetools
import orjson

import large_image.config
from girder.constants import AccessType
from girder.models.file import File
from girder.models.item import Item
from girder.models.user import User

from .models.annotation import Annotation
from .utils import isGeoJSON

_recentIdentifiers = cachetools.TTLCache(maxsize=100, ttl=86400)
logger = logging.getLogger(__name__)


def _itemFromEvent(event, identifierEnding, itemAccessLevel=AccessType.READ):
    """
    If an event has a reference and an associated identifier that ends with a
    specific string, return the associated item, user, and image file.

    :param event: the data.process event.
    :param identifierEnding: the required end of the identifier.
    :returns: a dictionary with item, user, and file if there was a match.
    """
    info = event.info
    identifier = None
    reference = info.get('reference', None)
    if reference is not None:
        try:
            reference = json.loads(reference)
            if (isinstance(reference, dict) and
                    isinstance(reference.get('identifier'), str)):
                identifier = reference['identifier']
        except (ValueError, TypeError):
            logger.debug('Failed to parse data.process reference: %r', reference)
    if identifier and 'uuid' in reference:
        if reference['uuid'] not in _recentIdentifiers:
            _recentIdentifiers[reference['uuid']] = {}
        _recentIdentifiers[reference['uuid']][identifier] = info
        reprocessFunc = _recentIdentifiers[reference['uuid']].pop('_reprocess', None)
        if reprocessFunc:
            reprocessFunc()
    if identifier is not None and identifier.endswith(identifierEnding):
        if identifier == 'LargeImageAnnotationUpload' and 'uuid' not in reference:
            reference['uuid'] = str(uuid.uuid4())
        if 'userId' not in reference or 'itemId' not in reference or 'fileId' not in reference:
            logger.error('Reference does not contain required information.')
            return None

        userId = reference['userId']
        imageId = reference['fileId']

        # load models from the database
        user = User().load(userId, force=True)
        image = File().load(imageId, level=AccessType.READ, user=user)
        item = Item().load(image['itemId'], level=itemAccessLevel, user=user)
        return {'item': item, 'user': user, 'file': image, 'uuid': reference.get('uuid')}


def resolveAnnotationGirderIds(event, results, data, possibleGirderIds):
    """
    If an annotation has references to girderIds, resolve them to actual ids.

    :param event: a data.process event.
    :param results: the results from _itemFromEvent,
    :param data: annotation data.
    :param possibleGirderIds: a list of annotation elements with girderIds
        needing resolution.
    :returns: True if all ids were processed.
    """
    # Exclude actual girderIds from resolution
    girderIds = []
    for element in possibleGirderIds:
        # This will throw an exception if the girderId isn't well-formed as an
        # actual id.
        try:
            if Item().load(element['girderId'], level=AccessType.READ, force=True) is None:
                girderIds.append(element)
        except Exception:
            girderIds.append(element)
    if not len(girderIds):
        return True
    idRecord = _recentIdentifiers.get(results.get('uuid'))
    if idRecord and not all(element['girderId'] in idRecord for element in girderIds):
        idRecord['_reprocess'] = lambda: process_annotations(event)
        return False
    for element in girderIds:
        element['girderId'] = str(idRecord[element['girderId']]['file']['itemId'])
        # Currently, all girderIds inside annotations are expected to be
        # large images.  In this case, load them and ask if they can be so,
        # in case they are small images
        from girder_large_image.models.image_item import ImageItem

        try:
            item = ImageItem().load(element['girderId'], force=True)
            ImageItem().createImageItem(
                item, list(ImageItem().childFiles(item=item, limit=1))[0], createJob=False)
        except Exception:
            pass
    return True


def process_annotations(event):  # noqa: C901
    # TODO this should become a celery task
    """Add annotations to an image on a ``data.process`` event"""
    results = _itemFromEvent(event, 'LargeImageAnnotationUpload')
    if not results:
        return
    item = results['item']
    user = results['user']

    file = File().load(
        event.info.get('file', {}).get('_id'),
        level=AccessType.READ, user=user,
    )
    startTime = time.time()

    if not file:
        logger.error('Could not load models from the database')
        return
    try:
        if file['size'] > int(large_image.config.getConfig(
                'max_annotation_input_file_length', 1024 ** 3)):
            msg = ('File is larger than will be read into memory.  If your '
                   'server will permit it, increase the '
                   'max_annotation_input_file_length setting.')
            raise Exception(msg)
        data = []
        with File().open(file) as fptr:
            while True:
                chunk = fptr.read(1024 ** 2)
                if not len(chunk):
                    break
                data.append(chunk)
        data = orjson.loads(b''.join(data).decode())
    except Exception:
        logger.error('Could not parse annotation file')
        raise
    if time.time() - startTime > 10:
        logger.info('Decoded json in %5.3fs', time.time() - startTime)

    if not isinstance(data, list) or isGeoJSON(data):
        data = [data]
    data = [entry['annotation'] if 'annotation' in entry else entry for entry in data]
    # Check some of the early elements to see if there are any girderIds
    # that need resolution.
    if 'uuid' in results:
        girderIds = [
            element for annotation in data
            for element in annotation.get('elements', [])[:100]
            if 'girderId' in element]
        if len(girderIds):
            if not resolveAnnotationGirderIds(event, results, data, girderIds):
                return
    for annotation in data:
        try:
            Annotation().createAnnotation(item, user, annotation)
        except Exception:
            logger.error('Could not create annotation object from data')
            raise
    if str(file['itemId']) == str(item['_id']):
        File().remove(file)
