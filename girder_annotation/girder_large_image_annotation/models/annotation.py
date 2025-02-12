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

import copy
import datetime
import enum
import logging
import re
import threading
import time

import cherrypy
import jsonschema
import numpy as np
from bson import ObjectId
from girder_large_image import constants
from girder_large_image.models.image_item import ImageItem

from girder import events
from girder.constants import AccessType, SortDir
from girder.exceptions import AccessException, ValidationException
from girder.models.folder import Folder
from girder.models.item import Item
from girder.models.model_base import AccessControlledModel
from girder.models.notification import Notification
from girder.models.setting import Setting
from girder.models.user import User

from ..utils import AnnotationGeoJSON, GeoJSONAnnotation, isGeoJSON
from .annotationelement import Annotationelement

# Some arrays longer than this are validated using numpy rather than jsonschema
VALIDATE_ARRAY_LENGTH = 1000
logger = logging.getLogger(__name__)


def extendSchema(base, add):
    extend = copy.deepcopy(base)
    for key in add:
        if key == 'required' and 'required' in base:
            extend[key] = sorted(set(extend[key]) | set(add[key]))
        elif key != 'properties' and 'properties' in base:
            extend[key] = add[key]
    if 'properties' in add:
        extend['properties'].update(add['properties'])
    return extend


class AnnotationSchema:
    coordSchema = {
        'type': 'array',
        # TODO: validate that z==0 for now
        'items': {
            'type': 'number',
        },
        'minItems': 3,
        'maxItems': 3,
        'name': 'Coordinate',
        # TODO: define origin for 3D images
        'description': 'An X, Y, Z coordinate tuple, in base layer pixel '
                       'coordinates, where the origin is the upper-left.',
    }
    coordValueSchema = {
        'type': 'array',
        'items': {
            'type': 'number',
        },
        'minItems': 4,
        'maxItems': 4,
        'name': 'CoordinateWithValue',
        'description': 'An X, Y, Z, value coordinate tuple, in base layer '
                       'pixel coordinates, where the origin is the upper-left.',
    }

    colorSchema = {
        'type': 'string',
        # We accept colors of the form
        #   #rrggbb                 six digit RRGGBB hex
        #   #rgb                    three digit RGB hex
        #   #rrggbbaa               eight digit RRGGBBAA hex
        #   #rgba                   four digit RGBA hex
        #   rgb(255, 255, 255)      rgb decimal triplet
        #   rgba(255, 255, 255, 1)  rgba quad with RGB in the range [0-255] and
        #                           alpha [0-1]
        # TODO: make rgb and rgba spec validate that rgb is [0-255] and a is
        # [0-1], rather than just checking if they are digits and such.
        'pattern': r'^(#([0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})|'
                   r'rgb\(\d+,\s*\d+,\s*\d+\)|'
                   r'rgba\(\d+,\s*\d+,\s*\d+,\s*(\d?\.|)\d+\))$',
    }

    colorRangeSchema = {
        'type': 'array',
        'items': colorSchema,
        'description': 'A list of colors',
    }

    rangeValueSchema = {
        'type': 'array',
        'items': {'type': 'number'},
        'description': 'A weakly monotonic list of range values',
    }

    userSchema = {
        'type': 'object',
        'additionalProperties': True,
    }

    labelSchema = {
        'type': 'object',
        'properties': {
            'value': {'type': 'string'},
            'visibility': {
                'type': 'string',
                # TODO: change to True, False, None?
                'enum': ['hidden', 'always', 'onhover'],
            },
            'fontSize': {
                'type': 'number',
                'exclusiveMinimum': 0,
            },
            'color': colorSchema,
        },
        'required': ['value'],
        'additionalProperties': False,
    }

    groupSchema = {'type': 'string'}

    baseElementSchema = {
        'type': 'object',
        'properties': {
            'id': {
                'type': 'string',
                'pattern': '^[0-9a-f]{24}$',
            },
            'type': {'type': 'string'},
            # schema free field for users to extend annotations
            'user': userSchema,
            'label': labelSchema,
            'group': groupSchema,
        },
        'required': ['type'],
        'additionalProperties': True,
    }
    baseShapeSchema = extendSchema(baseElementSchema, {
        'properties': {
            'lineColor': colorSchema,
            'lineWidth': {
                'type': 'number',
                'minimum': 0,
            },
        },
    })

    pointShapeSchema = extendSchema(baseShapeSchema, {
        'properties': {
            'type': {
                'type': 'string',
                'enum': ['point'],
            },
            'center': coordSchema,
            'fillColor': colorSchema,
        },
        'required': ['type', 'center'],
        'additionalProperties': False,
    })

    arrowShapeSchema = extendSchema(baseShapeSchema, {
        'properties': {
            'type': {
                'type': 'string',
                'enum': ['arrow'],
            },
            'points': {
                'type': 'array',
                'items': coordSchema,
                'minItems': 2,
                'maxItems': 2,
            },
            'fillColor': colorSchema,
        },
        'description': 'The first point is the head of the arrow',
        'required': ['type', 'points'],
        'additionalProperties': False,
    })

    circleShapeSchema = extendSchema(baseShapeSchema, {
        'properties': {
            'type': {
                'type': 'string',
                'enum': ['circle'],
            },
            'center': coordSchema,
            'radius': {
                'type': 'number',
                'minimum': 0,
            },
            'fillColor': colorSchema,
        },
        'required': ['type', 'center', 'radius'],
        'additionalProperties': False,
    })

    polylineShapeSchema = extendSchema(baseShapeSchema, {
        'properties': {
            'type': {
                'type': 'string',
                'enum': ['polyline'],
            },
            'points': {
                'type': 'array',
                'items': coordSchema,
                'minItems': 2,
            },
            'fillColor': colorSchema,
            'closed': {
                'type': 'boolean',
                'description': 'polyline is open if closed flag is '
                               'not specified',
            },
            'holes': {
                'type': 'array',
                'description':
                    'If closed is true, this is a list of polylines that are '
                    'treated as holes in the base polygon. These should not '
                    'cross each other and should be contained within the base '
                    'polygon.',
                'items': {
                    'type': 'array',
                    'items': coordSchema,
                    'minItems': 3,
                },
            },
        },
        'required': ['type', 'points'],
        'additionalProperties': False,
    })

    baseRectangleShapeSchema = extendSchema(baseShapeSchema, {
        'properties': {
            'type': {'type': 'string'},
            'center': coordSchema,
            'width': {
                'type': 'number',
                'minimum': 0,
            },
            'height': {
                'type': 'number',
                'minimum': 0,
            },
            'rotation': {
                'type': 'number',
                'description': 'radians counterclockwise around normal',
            },
            'normal': coordSchema,
            'fillColor': colorSchema,
        },
        'decription': 'normal is the positive z-axis unless otherwise '
                      'specified',
        'required': ['type', 'center', 'width', 'height'],
    })

    rectangleShapeSchema = extendSchema(baseRectangleShapeSchema, {
        'properties': {
            'type': {
                'type': 'string',
                'enum': ['rectangle'],
            },
        },
        'additionalProperties': False,
    })
    rectangleGridShapeSchema = extendSchema(baseRectangleShapeSchema, {
        'properties': {
            'type': {
                'type': 'string',
                'enum': ['rectanglegrid'],
            },
            'widthSubdivisions': {
                'type': 'integer',
                'minimum': 1,
            },
            'heightSubdivisions': {
                'type': 'integer',
                'minimum': 1,
            },
        },
        'required': ['type', 'widthSubdivisions', 'heightSubdivisions'],
        'additionalProperties': False,
    })
    ellipseShapeSchema = extendSchema(baseRectangleShapeSchema, {
        'properties': {
            'type': {
                'type': 'string',
                'enum': ['ellipse'],
            },
        },
        'required': ['type'],
        'additionalProperties': False,
    })

    heatmapSchema = extendSchema(baseElementSchema, {
        'properties': {
            'type': {
                'type': 'string',
                'enum': ['heatmap'],
            },
            'points': {
                'type': 'array',
                'items': coordValueSchema,
            },
            'radius': {
                'type': 'number',
                'exclusiveMinimum': 0,
            },
            'colorRange': colorRangeSchema,
            'rangeValues': rangeValueSchema,
            'normalizeRange': {
                'type': 'boolean',
                'description':
                    'If true, rangeValues are on a scale of 0 to 1 '
                    'and map to the minimum and maximum values on the '
                    'data.  If false (the default), the rangeValues '
                    'are the actual data values.',
            },
            'scaleWithZoom': {
                'type': 'boolean',
                'description':
                    'If true, scale the size of points with the '
                    'zoom level of the map.',
            },
        },
        'required': ['type', 'points'],
        'additionalProperties': False,
        'description':
            'ColorRange and rangeValues should have a one-to-one '
            'correspondence.',
    })

    griddataSchema = extendSchema(baseElementSchema, {
        'properties': {
            'type': {
                'type': 'string',
                'enum': ['griddata'],
            },
            'origin': coordSchema,
            'dx': {
                'type': 'number',
                'description': 'grid spacing in the x direction',
            },
            'dy': {
                'type': 'number',
                'description': 'grid spacing in the y direction',
            },
            'gridWidth': {
                'type': 'integer',
                'minimum': 1,
                'description': 'The number of values across the width of the grid',
            },
            'values': {
                'type': 'array',
                'items': {'type': 'number'},
                'description':
                    'The values of the grid.  This must have a '
                    'multiple of gridWidth entries',
            },
            'interpretation': {
                'type': 'string',
                'enum': ['heatmap', 'contour', 'choropleth'],
            },
            'radius': {
                'type': 'number',
                'exclusiveMinimum': 0,
                'description': 'radius used for heatmap interpretation',
            },
            'scaleWithZoom': {
                'type': 'boolean',
                'description':
                    'If true, and interpreted as a heatmap, scale the size '
                    'of points with the zoom level of the map.',
            },
            'colorRange': colorRangeSchema,
            'rangeValues': rangeValueSchema,
            'normalizeRange': {
                'type': 'boolean',
                'description':
                    'If true, rangeValues are on a scale of 0 to 1 '
                    'and map to the minimum and maximum values on the '
                    'data.  If false (the default), the rangeValues '
                    'are the actual data values.',
            },
            'stepped': {'type': 'boolean'},
            'minColor': colorSchema,
            'maxColor': colorSchema,
        },
        'required': ['type', 'values', 'gridWidth'],
        'additionalProperties': False,
        'description':
            'ColorRange and rangeValues should have a one-to-one '
            'correspondence except for stepped contours where '
            'rangeValues needs one more entry than colorRange.  '
            'minColor and maxColor are the colors applies to values '
            'beyond the ranges in rangeValues.',
    })

    transformArray = {
        'type': 'array',
        'items': {
            'type': 'array',
            'minItems': 2,
            'maxItems': 2,
        },
        'minItems': 2,
        'maxItems': 2,
        'description': 'A 2D matrix representing the transform of an '
                       'image overlay.',
    }

    overlaySchema = extendSchema(baseElementSchema, {
        'properties': {
            'type': {
                'type': 'string',
                'enum': ['image'],
            },
            'girderId': {
                'type': 'string',
                'pattern': '^[0-9a-f]{24}$',
                'description': 'Girder item ID containing the image to '
                               'overlay.',
            },
            'opacity': {
                'type': 'number',
                'minimum': 0,
                'maximum': 1,
                'description': 'Default opacity for this image overlay. Must '
                               'be between 0 and 1. Defaults to 1.',
            },
            'hasAlpha': {
                'type': 'boolean',
                'description':
                    'If true, the image is treated assuming it has an alpha '
                    'channel.',
            },
            'transform': {
                'type': 'object',
                'description': 'Specification for an affine transform of the '
                               'image overlay. Includes a 2D transform matrix, '
                               'an X offset and a Y offset.',
                'properties': {
                    'xoffset': {
                        'type': 'number',
                    },
                    'yoffset': {
                        'type': 'number',
                    },
                    'matrix': transformArray,
                },
            },
        },
        'required': ['girderId', 'type'],
        'additionalProperties': False,
        'description': 'An image overlay on top of the base resource.',
    })

    pixelmapCategorySchema = {
        'type': 'object',
        'properties': {
            'fillColor': colorSchema,
            'strokeColor': colorSchema,
            'label': {
                'type': 'string',
                'description': 'A string representing the semantic '
                               'meaning of regions of the map with '
                               'the corresponding color.',
            },
            'description': {
                'type': 'string',
                'description': 'A more detailed explanation of the '
                               'meaining of this category.',
            },
        },
        'required': ['fillColor'],
        'additionalProperties': False,
    }

    pixelmapSchema = extendSchema(overlaySchema, {
        'properties': {
            'type': {
                'type': 'string',
                'enum': ['pixelmap'],
            },
            'values': {
                'type': 'array',
                'items': {'type': 'integer'},
                'description': 'An array where the indices '
                               'correspond to pixel values in the '
                               'pixel map image and the values are '
                               'used to look up the appropriate '
                               'color in the categories property.',
            },
            'categories': {
                'type': 'array',
                'items': pixelmapCategorySchema,
                'description': 'An array used to map between the '
                               'values array and color values. '
                               'Can also contain semantic '
                               'information for color values.',
            },
            'boundaries': {
                'type': 'boolean',
                'description': 'True if the pixelmap doubles pixel '
                               'values such that even values are the '
                               'fill and odd values the are stroke '
                               'of each superpixel. If true, the '
                               'length of the values array should be '
                               'half of the maximum value in the '
                               'pixelmap.',

            },
        },
        'required': ['values', 'categories', 'boundaries'],
        'additionalProperties': False,
        'description': 'A tiled pixelmap to overlay onto a base resource.',
    })

    annotationElementSchema = {
        # Shape subtypes are mutually exclusive, so for efficiency, don't use
        # 'oneOf'
        'anyOf': [
            # If we include the baseShapeSchema, then shapes that are as-yet
            #  invented can be included.
            # baseShapeSchema,
            arrowShapeSchema,
            circleShapeSchema,
            ellipseShapeSchema,
            griddataSchema,
            heatmapSchema,
            pointShapeSchema,
            polylineShapeSchema,
            rectangleShapeSchema,
            rectangleGridShapeSchema,
            overlaySchema,
            pixelmapSchema,
        ],
    }

    annotationSchema = {
        '$schema': 'http://json-schema.org/schema#',
        'type': 'object',
        'properties': {
            'name': {
                'type': 'string',
                # TODO: Disallow empty?
                'minLength': 1,
            },
            'description': {'type': 'string'},
            'display': {
                'type': 'object',
                'properties': {
                    'visible': {
                        'type': ['boolean', 'string'],
                        'enum': ['new', True, False],
                        'description': 'This advises viewers on when the '
                        'annotation should be shown.  If "new" (the default), '
                        'show the annotation when it is first added to the '
                        "system.  If false, don't show the annotation by "
                        'default.  If true, show the annotation when the item '
                        'is displayed.',
                    },
                },
            },
            'attributes': {
                'type': 'object',
                'additionalProperties': True,
                'title': 'Image Attributes',
                'description': 'Subjective things that apply to the entire '
                               'image.',
            },
            'elements': {
                'type': 'array',
                'items': annotationElementSchema,
                # We want to ensure unique element IDs, if they are set.  If
                # they are not set, we assign them from Mongo.
                'title': 'Image Markup',
                'description': 'Subjective things that apply to a '
                               'spatial region.',
            },
        },
        'additionalProperties': False,
    }


class Annotation(AccessControlledModel):
    """
    This model is used to represent an annotation that is associated with an
    item.  The annotation can contain any number of annotationelements, which
    are included because they reference this annotation as a parent.  The
    annotation acts like these are a native part of it, though they are each
    stored as independent models to (eventually) permit faster spatial
    searching.
    """

    validatorAnnotation = jsonschema.Draft6Validator(
        AnnotationSchema.annotationSchema)
    validatorAnnotationElement = jsonschema.Draft6Validator(
        AnnotationSchema.annotationElementSchema)
    idRegex = re.compile('^[0-9a-f]{24}$')
    numberInstance = (int, float)

    class Skill(enum.Enum):
        NOVICE = 'novice'
        EXPERT = 'expert'

    # This is everything except the annotation field, and is used, in part, to
    # determine what gets returned in a general find.
    baseFields = (
        '_id',
        'itemId',
        'creatorId',
        'created',
        'updated',
        'updatedId',
        'public',
        'publicFlags',
        'groups',
        # 'skill',
        # 'startTime'
        # 'stopTime'
    )

    def initialize(self):
        self._writeLock = threading.Lock()
        self.name = 'annotation'
        self.ensureIndices([
            'itemId',
            'created',
            'creatorId',
            ([
                ('itemId', SortDir.ASCENDING),
                ('_active', SortDir.ASCENDING),
            ], {}),
            ([
                ('_id', SortDir.ASCENDING),
                ('_version', SortDir.DESCENDING),
            ], {}),
            '_version',
            'updated',
        ])
        self.ensureTextIndex({
            'annotation.name': 10,
            'annotation.description': 1,
        })

        self.exposeFields(AccessType.READ, (
            'annotation', '_version', '_elementQuery', '_active',
        ) + self.baseFields)
        events.bind('model.item.remove', 'large_image_annotation', self._onItemRemove)
        events.bind('model.item.copy.prepare', 'large_image_annotation', self._prepareCopyItem)
        events.bind('model.item.copy.after', 'large_image_annotation', self._handleCopyItem)

        self._historyEnabled = Setting().get(
            constants.PluginSettings.LARGE_IMAGE_ANNOTATION_HISTORY)
        # Listen for changes to our relevant settings
        events.bind('model.setting.save.after', 'large_image_annotation', self._onSettingChange)
        events.bind('model.setting.remove', 'large_image_annotation', self._onSettingChange)

    def _onItemRemove(self, event):
        """
        When an item is removed, also delete associated annotations.

        :param event: the event with the item information.
        """
        item = event.info
        annotations = Annotation().find({'itemId': item['_id']})
        for annotation in annotations:
            if self._historyEnabled:
                # just mark the annotations as inactive
                self.update({'_id': annotation['_id']}, {'$set': {'_active': False}})
            else:
                Annotation().remove(annotation)

    def _prepareCopyItem(self, event):
        # check if this copy should include annotations
        if (cherrypy.request and cherrypy.request.params and
                str(cherrypy.request.params.get('copyAnnotations')).lower() == 'false'):
            return
        srcItem, newItem = event.info
        if Annotation().findOne({
                '_active': {'$ne': False}, 'itemId': srcItem['_id']}):
            newItem['_annotationItemId'] = srcItem['_id']
            Item().save(newItem, triggerEvents=False)

    def _handleCopyItem(self, event):
        newItem = event.info
        srcItemId = newItem.pop('_annotationItemId', None)
        if srcItemId:
            Item().save(newItem, triggerEvents=False)
            self._copyAnnotationsFromOtherItem(srcItemId, newItem)

    def _copyAnnotationsFromOtherItem(self, srcItemId, destItem):
        # Copy annotations from the original item to this one
        query = {'_active': {'$ne': False}, 'itemId': srcItemId}
        annotations = Annotation().find(query)
        total = annotations.count()
        if not total:
            return
        destItemId = destItem['_id']
        folder = Folder().load(destItem['folderId'], force=True)
        count = 0
        for annotation in annotations:
            logger.info('Copying annotation %d of %d from %s to %s',
                        count + 1, total, srcItemId, destItemId)
            # Make sure we have the elements
            annotation = Annotation().load(annotation['_id'], force=True)
            # This could happen, for instance, if the annotation were deleted
            # while we are copying other annotations.
            if annotation is None:
                continue
            annotation['itemId'] = destItemId
            del annotation['_id']
            # Remove existing permissions, then give it the same permissions
            # as the item's folder.
            annotation.pop('access', None)
            self.copyAccessPolicies(destItem, annotation, save=False)
            self.setPublic(annotation, folder.get('public'), save=False)
            self.save(annotation)
            count += 1
        logger.info('Copied %d annotations from %s to %s ',
                    count, srcItemId, destItemId)

    def _onSettingChange(self, event):
        settingDoc = event.info
        if settingDoc['key'] == constants.PluginSettings.LARGE_IMAGE_ANNOTATION_HISTORY:
            self._historyEnabled = settingDoc['value']

    def _migrateDatabase(self):
        # Check that all entries have ACL
        for annotation in self.collection.find({'access': {'$exists': False}}):
            self._migrateACL(annotation)
        # Check that all annotations have groups
        for annotation in self.collection.find({'groups': {'$exists': False}}):
            self.injectAnnotationGroupSet(annotation)

    def _migrateACL(self, annotation):
        """
        Add access control information to an annotation model.

        Originally annotation models were not access controlled.  This function
        performs the migration for annotations created before this change was
        made.  The access object is copied from the folder containing the image
        the annotation is attached to.   In addition, the creator is given
        admin access.
        """
        if annotation is None or 'access' in annotation:
            return annotation

        item = Item().load(annotation['itemId'], force=True)
        if item is None:
            logger.debug(
                'Could not generate annotation ACL due to missing item %s', annotation['_id'])
            return annotation

        folder = Folder().load(item['folderId'], force=True)
        if folder is None:
            logger.debug(
                'Could not generate annotation ACL due to missing folder %s', annotation['_id'])
            return annotation

        user = None
        if annotation.get('creatorId'):
            user = User().load(annotation['creatorId'], force=True)
        if user is None:
            logger.debug(
                'Could not generate annotation ACL due to missing user %s', annotation['_id'])
            return annotation

        self.copyAccessPolicies(item, annotation, save=False)
        self.setUserAccess(annotation, user, AccessType.ADMIN, force=True, save=False)
        self.setPublic(annotation, folder.get('public') or False, save=False)

        # call the super class save method to avoid messing with elements
        super().save(annotation)
        logger.info('Generated annotation ACL for %s', annotation['_id'])
        return annotation

    def createAnnotation(self, item, creator, annotation, public=None):
        if isGeoJSON(annotation):
            geojson = GeoJSONAnnotation(annotation)
            if geojson.elementCount:
                annotation = geojson.annotation
        now = datetime.datetime.now(datetime.timezone.utc)
        doc = {
            'itemId': item['_id'],
            'creatorId': creator['_id'],
            'created': now,
            'updatedId': creator['_id'],
            'updated': now,
            'annotation': annotation,
        }
        if annotation and not annotation.get('name'):
            annotation['name'] = now.strftime('Annotation %Y-%m-%d %H:%M')

        # copy access control from the folder containing the image
        folder = Folder().load(item['folderId'], force=True)
        self.copyAccessPolicies(src=folder, dest=doc, save=False)

        if public is None:
            public = folder.get('public', False)
        self.setPublic(doc, public, save=False)

        # give the current user admin access
        self.setUserAccess(doc, user=creator, level=AccessType.ADMIN, save=False)

        doc = self.save(doc)
        Notification().createNotification(
            type='large_image_annotation.create',
            data={'_id': doc['_id'], 'itemId': doc['itemId']},
            user=creator,
            expires=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=1))
        return doc

    def load(self, id, region=None, getElements=True, *args, **kwargs):
        """
        Load an annotation, adding all or a subset of the elements to it.

        :param region: if present, a dictionary restricting which annotations
            are returned.  See annotationelement.getElements.
        :param getElements: if False, don't get elements associated with this
            annotation.
        :returns: the matching annotation or none.
        """
        annotation = super().load(id, *args, **kwargs)
        if annotation is None:
            return None

        if getElements:
            # It is possible that we are trying to read the elements of an
            # annotation as another thread is updating them.  In this case,
            # there is a chance, that between when we get the annotation and
            # ask for the elements, the version will have been updated and the
            # elements will have gone away.  To work around the lack of
            # transactions in Mongo, if we don't get any elements, we check if
            # the version has shifted under us, and, if so, requery.  I've put
            # an arbitrary retry limit on this to prevent an infinite loop.
            maxRetries = 3
            for retry in range(maxRetries):
                Annotationelement().getElements(
                    annotation, region)
                if (len(annotation.get('annotation', {}).get('elements')) or
                        retry + 1 == maxRetries):
                    break
                recheck = super().load(id, *args, **kwargs)
                if (recheck is None or
                        annotation.get('_version') == recheck.get('_version')):
                    break
                annotation = recheck

        self.injectAnnotationGroupSet(annotation)
        return annotation

    def remove(self, annotation, *args, **kwargs):
        """
        When removing an annotation, remove all element associated with it.
        This overrides the collection delete_one method so that all of the
        triggers are fired as expected and cancelling from an event will work
        as needed.

        :param annotation: the annotation document to remove.
        """
        if self._historyEnabled:
            # just mark the annotations as inactive
            result = self.update({'_id': annotation['_id']}, {'$set': {'_active': False}})
        else:
            with self._writeLock:
                delete_one = self.collection.delete_one

            def deleteElements(query, *args, **kwargs):
                ret = delete_one(query, *args, **kwargs)
                Annotationelement().removeElements(annotation)
                return ret

            with self._writeLock:
                self.collection.delete_one = deleteElements
                try:
                    result = super().remove(annotation, *args, **kwargs)
                finally:
                    self.collection.delete_one = delete_one
        Notification().createNotification(
            type='large_image_annotation.remove',
            data={'_id': annotation['_id'], 'itemId': annotation['itemId']},
            user=User().load(annotation['creatorId'], force=True),
            expires=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=1))
        return result

    def save(self, annotation, *args, **kwargs):
        """
        When saving an annotation, override the collection insert_one and
        replace_one methods so that we don't save the elements with the main
        annotation.  Still use the super class's save method, so that all of
        the triggers are fired as expected and cancelling and modifications can
        be done as needed.

        Because Mongo doesn't support transactions, a version number is stored
        with the annotation and with the associated elements.  This is used to
        add the new elements first, then update the annotation, and delete the
        old elements.  The allows version integrity if another thread queries
        the annotation at the same time.

        :param annotation: the annotation document to save.
        :returns: the saved document.  If it is a new document, the _id has
                  been added.
        """
        starttime = time.time()
        with self._writeLock:
            replace_one = self.collection.replace_one
            insert_one = self.collection.insert_one
        version = Annotationelement().getNextVersionValue()
        if '_id' not in annotation:
            oldversion = None
        else:
            if '_annotationId' in annotation:
                annotation['_id'] = annotation['_annotationId']
            # We read the old version from the existing record, because we
            # don't want to trust that the input _version has not been altered
            # or is present.
            oldversion = self.collection.find_one(
                {'_id': annotation['_id']}).get('_version')
        annotation['_version'] = version
        _elementQuery = annotation.pop('_elementQuery', None)
        annotation.pop('_active', None)
        annotation.pop('_annotationId', None)

        def replaceElements(query, doc, *args, **kwargs):
            Annotationelement().updateElements(doc)
            elements = doc['annotation'].pop('elements', None)
            if self._historyEnabled:
                oldAnnotation = self.collection.find_one(query)
                if oldAnnotation:
                    oldAnnotation['_annotationId'] = oldAnnotation.pop('_id')
                    oldAnnotation['_active'] = False
                    insert_one(oldAnnotation)
            ret = replace_one(query, doc, *args, **kwargs)
            if elements:
                doc['annotation']['elements'] = elements
            if not self._historyEnabled:
                Annotationelement().removeOldElements(doc, oldversion)
            return ret

        def insertElements(doc, *args, **kwargs):
            # When creating an annotation, store the elements first, then store
            # the annotation without elements, then restore the elements.
            doc.setdefault('_id', ObjectId())
            if doc['annotation'].get('elements') is not None:
                Annotationelement().updateElements(doc)
            # If we are inserting, we shouldn't have any old elements, so don't
            # bother removing them.
            elements = doc['annotation'].pop('elements', None)
            ret = insert_one(doc, *args, **kwargs)
            if elements is not None:
                doc['annotation']['elements'] = elements
            return ret

        with self._writeLock:
            self.collection.replace_one = replaceElements
            self.collection.insert_one = insertElements
            try:
                result = super().save(annotation, *args, **kwargs)
            finally:
                self.collection.replace_one = replace_one
                self.collection.insert_one = insert_one
        if _elementQuery:
            result['_elementQuery'] = _elementQuery

        annotation.pop('groups', None)
        self.injectAnnotationGroupSet(annotation)

        if annotation['annotation'].get('elements') is not None:
            logger.info(
                'Saved annotation %s in %5.3fs with %d element(s)',
                annotation.get('_id', None),
                time.time() - starttime,
                len(annotation['annotation']['elements']))
        events.trigger('large_image.annotations.save_history', {
            'annotation': annotation,
        })
        return result

    def updateAnnotation(self, annotation, updateUser=None):
        """
        Update an annotation.

        :param annotation: the annotation document to update.
        :param updateUser: the user who is creating the update.
        :returns: the annotation document that was updated.
        """
        annotation['updated'] = datetime.datetime.now(datetime.timezone.utc)
        annotation['updatedId'] = updateUser['_id'] if updateUser else None
        annotation = self.save(annotation)
        Notification().createNotification(
            type='large_image_annotation.update',
            data={'_id': annotation['_id'], 'itemId': annotation['itemId']},
            user=User().load(annotation['creatorId'], force=True),
            expires=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=1))
        return annotation

    def _similarElementStructure(self, a, b, parentKey=None):  # noqa
        """
        Compare two elements to determine if they are similar enough that if
        one validates, the other should, too.  This is called recursively to
        validate dictionaries.  In general, types must be the same,
        dictionaries must contain the same keys, arrays must be the same
        length.  The only differences that are allowed are numerical values may
        be different, ids may be different, and point arrays may contain
        different numbers of elements.

        :param a: first element
        :param b: second element
        :param parentKey: if set, the key of the dictionary that used for this
            part of the comparison.
        :returns: True if the elements are similar.  False if they are not.
        """
        # This function exceeds the recommended complexity, but since it is
        # needs to be relatively fast, breaking it into smaller functions is
        # probably undesirable.
        if not isinstance(a, type(b)):
            return False
        if isinstance(a, dict):
            if len(a) != len(b):
                return False
            for k in a:
                if k not in b:
                    return False
                if k == 'id':
                    if not isinstance(b[k], str) or not self.idRegex.match(b[k]):
                        return False
                elif parentKey in {'user'} or k in {'fillColor', 'lineColor'}:
                    continue
                elif parentKey != 'label' or k != 'value':
                    if not self._similarElementStructure(a[k], b[k], k):
                        return False
        elif isinstance(a, list):
            if parentKey == 'holes':
                return all(
                    len(hole) == 3 and
                    # this is faster than checking the instance type, and, if
                    # it raises an exception, it would have failed validation
                    # any way.
                    1 + hole[0] + hole[1] + hole[2] is not None
                    # isinstance(hole[0], self.numberInstance) and
                    # isinstance(hole[1], self.numberInstance) and
                    # isinstance(hole[2], self.numberInstance)
                    for hlist in b
                    for hole in hlist)
            if len(a) != len(b):
                if parentKey not in {'points', 'values'} or len(a) < 2 or len(b) < 2:
                    return False
                # If this is an array of points, let it pass
                return all(
                    len(elem) == 3 and
                    # this is faster than checking the instance type, and, if
                    # it raises an exception, it would have failed validation
                    # any way.
                    1 + elem[0] + elem[1] + elem[2] is not None
                    # isinstance(elem[0], self.numberInstance) and
                    # isinstance(elem[1], self.numberInstance) and
                    # isinstance(elem[2], self.numberInstance)
                    for elem in b)
            for idx in range(len(a)):
                if not self._similarElementStructure(a[idx], b[idx], parentKey):
                    return False
        elif not isinstance(a, self.numberInstance):
            return a == b
        # Either a number or the dictionary or list comparisons passed
        return True

    def validate(self, doc):  # noqa
        startTime = lastTime = time.time()
        try:
            # This block could just use the json validator:
            #   jsonschema.validate(doc.get('annotation'),
            #                       AnnotationSchema.annotationSchema)
            # but this is very slow.  Instead, validate the main structure and
            # then validate each element.  If sequential elements are similar
            # in structure, skip validating them.
            annot = doc.get('annotation')
            elements = annot.get('elements', [])
            annot['elements'] = []
            self.validatorAnnotation.validate(annot)
            lastValidatedElement = None
            lastValidatedElement2 = None
            for idx, element in enumerate(elements):
                # Discard element keys beginning with _
                for key in list(element):
                    if key.startswith('_'):
                        del element[key]
                if isinstance(element.get('id'), ObjectId):
                    element['id'] = str(element['id'])
                # Handle elements with large arrays by checking that a
                # conversion to a numpy array works
                keys = {}
                if len(element.get('points', element.get('values', []))) > VALIDATE_ARRAY_LENGTH:
                    key = 'points' if 'points' in element else 'values'
                    try:
                        # Check if the entire array converts in an obvious
                        # manner
                        np.array(element[key], dtype=float)
                        keys[key] = element[key]
                        element[key] = element[key][:VALIDATE_ARRAY_LENGTH]
                    except Exception:
                        pass
                if any(len(h) > VALIDATE_ARRAY_LENGTH for h in element.get('holes', [])):
                    key = 'holes'
                    try:
                        for h in element['holes']:
                            np.array(h, dtype=float)
                        keys[key] = element[key]
                        element[key] = []
                    except Exception:
                        pass
                try:
                    if (not self._similarElementStructure(element, lastValidatedElement) and
                            not self._similarElementStructure(element, lastValidatedElement2)):
                        self.validatorAnnotationElement.validate(element)
                        lastValidatedElement2 = lastValidatedElement
                        lastValidatedElement = element
                except TypeError:
                    self.validatorAnnotationElement.validate(element)
                if keys:
                    element.update(keys)
                if time.time() - lastTime > 10:
                    logger.info('Validated %s of %d elements in %5.3fs',
                                idx + 1, len(elements), time.time() - startTime)
                    lastTime = time.time()
            annot['elements'] = elements
        except jsonschema.ValidationError as exp:
            raise ValidationException(exp)
        if time.time() - startTime > 10:
            logger.info('Validated in %5.3fs' % (time.time() - startTime))
        elementIds = [entry['id'] for entry in
                      doc['annotation'].get('elements', []) if 'id' in entry]
        if len(set(elementIds)) != len(elementIds):
            msg = 'Annotation Element IDs are not unique'
            raise ValidationException(msg)
        return doc

    def versionList(self, annotationId, user=None, limit=0, offset=0,
                    sort=(('_version', -1), ), force=False):
        """
        List annotation history entries for a specific annotationId.  Only
        annotations that belong to an existing item that the user is allowed to
        view are included.  If the user is an admin, all annotations will be
        included.

        :param annotationId: the annotation to get history for.
        :param user: the Girder user.
        :param limit: maximum number of history entries to return.
        :param offset: skip this many entries.
        :param sort: the sort method used.  Defaults to reverse _id.
        :param force: if True, don't authenticate the user.
        :yields: the entries in the list
        """
        if annotationId and not isinstance(annotationId, ObjectId):
            annotationId = ObjectId(annotationId)
        # Make sure we have only one of each version, plus apply our filter and
        # sort.  Don't apply limit and offset here, as they are subject to
        # access control and other effects
        entries = self.collection.aggregate([
            {'$match': {'$or': [{'_id': annotationId}, {'_annotationId': annotationId}]}},
            {'$group': {'_id': '$_version', '_doc': {'$first': '$$ROOT'}}},
            {'$replaceRoot': {'newRoot': '$_doc'}},
            {'$sort': {s[0]: s[1] for s in sort}}])
        if not force:
            entries = self.filterResultsByPermission(
                cursor=entries, user=user, level=AccessType.READ,
                limit=limit, offset=offset)
        return entries

    def getVersion(self, annotationId, version, user=None, force=False, *args, **kwargs):
        """
        Get an annotation history version.  This reconstructs the original
        annotation.

        :param annotationId: the annotation to get history for.
        :param version: the specific version to get.
        :param user: the Girder user.  If the user is not an admin, they must
            have read access on the item and the item must exist.
        :param force: if True, don't get the user access.
        """
        if annotationId and not isinstance(annotationId, ObjectId):
            annotationId = ObjectId(annotationId)
        entry = self.findOne({
            '$or': [{'_id': annotationId}, {'_annotationId': annotationId}],
            '_version': int(version),
        }, fields=['_id'])
        if not entry:
            return None
        result = self.load(entry['_id'], *args, user=user, force=force, **kwargs)
        result['_versionId'] = result['_id']
        result['_id'] = result.pop('annotationId', result['_id'])
        return result

    def revertVersion(self, id, version=None, user=None, force=False):
        """
        Revert to a previous version of an annotation.

        :param id: the annotation id.
        :param version: the version to revert to.  None reverts to the previous
            version.  If the annotation was deleted, this is the most recent
            version.
        :param user: the user doing the reversion.
        :param force: if True don't authenticate the user with the associated
            item access.
        """
        if version is None:
            oldVersions = list(Annotation().versionList(id, limit=2, force=True))
            if len(oldVersions) >= 1 and oldVersions[0].get('_active') is False:
                version = oldVersions[0]['_version']
            elif len(oldVersions) >= 2:
                version = oldVersions[1]['_version']
        annotation = Annotation().getVersion(id, version, user, force=force)
        if annotation is None:
            return None
        # If this is the most recent (active) annotation, don't do anything.
        # Otherwise, revert it.
        if not annotation.get('_active', True):
            if not force:
                self.requireAccess(annotation, user=user, level=AccessType.WRITE)
            annotation = Annotation().updateAnnotation(annotation, updateUser=user)
        return annotation

    def findAnnotatedImages(self, imageNameFilter=None, creator=None,
                            user=None, level=AccessType.ADMIN, force=None,
                            offset=0, limit=0, sort=None, **kwargs):
        r"""
        Find images associated with annotations.

        The list returned by this function is paginated and filtered by access control using
        the standard girder kwargs.

        :param imageNameFilter: A string used to filter images by name.  An image name matches
            if it (or a subtoken) begins with this string.  Subtokens are generated by splitting
            by the regex ``[\W_]+``  This filter is case-insensitive.
        :param creator: Filter by a user who is the creator of the annotation.
        """
        query = {'_active': {'$ne': False}}
        if creator:
            query['creatorId'] = creator['_id']

        annotations = self.find(
            query, sort=sort, fields=['itemId'])

        images = []
        imageIds = set()
        for annotation in annotations:
            # short cut if the image has already been added to the results
            if annotation['itemId'] in imageIds:
                continue

            try:
                item = ImageItem().load(annotation['itemId'], level=level, user=user, force=force)
            except AccessException:
                item = None

            # ignore if no such item exists
            if not item:
                continue

            if not self._matchImageName(item['name'], imageNameFilter or ''):
                continue

            if len(imageIds) >= offset:
                images.append(item)

            imageIds.add(item['_id'])
            if len(images) == limit:
                break
        return images

    def _matchImageName(self, imageName, matchString):
        matchString = matchString.lower()
        imageName = imageName.lower()
        if imageName.startswith(matchString):
            return True
        tokens = re.split(r'[\W_]+', imageName, flags=re.UNICODE)
        return any(token.startswith(matchString) for token in tokens)

    def injectAnnotationGroupSet(self, annotation):
        if 'groups' not in annotation:
            annotation['groups'] = Annotationelement().getElementGroupSet(annotation)
            query = {
                '_id': ObjectId(annotation['_id']),
            }
            update = {
                '$set': {
                    'groups': annotation['groups'],
                },
            }
            self.collection.update_one(query, update)
        return annotation

    def setAccessList(self, doc, access, save=False, **kwargs):
        """
        The super class's setAccessList function can save a document.  However,
        annotations which have not loaded elements lose their elements when
        this occurs, because the validation step of the save function adds an
        empty element list.  By using an update instead of a save, this
        prevents the problem.
        """
        update = save and '_id' in doc
        save = save and '_id' not in doc
        doc = super().setAccessList(doc, access, save=save, **kwargs)
        if update:
            self.update({'_id': doc['_id']}, {'$set': {'access': doc['access']}})
        return doc

    def removeOldAnnotations(self, remove=False, minAgeInDays=30, keepInactiveVersions=5):  # noqa
        """
        Remove annotations that (a) have no item or (b) are inactive and at
        least (1) a minimum age in days and (2) not the most recent inactive
        versions.  Also remove any annotation elements that don't have
        associated annotations and are a minimum age in days.

        :param remove: if False, just report on what would be done.  If true,
            actually remove the annotations and compact the collections.
        :param minAgeInDays: only work on annotations that are at least this
            old.  This must be greater than or equal to 7.
        :param keepInactiveVersions: keep at least this many inactive versions
            of any annotation, regardless of age.
        """
        if (remove and minAgeInDays < 7) or minAgeInDays < 0:
            msg = 'minAgeInDays must be >= 7'
            raise ValidationException(msg)
        age = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(-minAgeInDays)
        if keepInactiveVersions < 0:
            msg = 'keepInactiveVersions mist be non-negative'
            raise ValidationException(msg)
        logger.info('Checking old annotations')
        logtime = time.time()
        report = {'fromDeletedItems': 0, 'oldVersions': 0, 'abandonedVersions': 0}
        if remove:
            report['removedVersions'] = 0
        report['active'] = self.collection.count_documents({'_active': {'$ne': False}})
        if time.time() - logtime > 10:
            logger.info('Counting inactive annotations, %r' % report)
            logtime = time.time()
        report['recentVersions'] = self.collection.count_documents({'_active': False})
        recentDateStep = {'$addFields': {'mostRecentDate': {'$max': [
            '$created', {'$ifNull': ['$updated', '$created']}]}}}
        itemLookupStep = {'$lookup': {
            'from': 'item',
            'localField': 'itemId',
            'foreignField': '_id',
            'as': 'item',
        }}
        oldDeletedPipeline = [recentDateStep, itemLookupStep, {
            '$match': {'item': {'$size': 0}, 'mostRecentDate': {'$lt': age}},
        }, {
            '$project': {'item': 0},
        }]
        if time.time() - logtime > 10:
            logger.info('Finding deleted annotations, %r' % report)
            logtime = time.time()
        for annot in self.collection.aggregate(oldDeletedPipeline):
            if time.time() - logtime > 10:
                logger.info('Checking deleted annotations, %r' % report)
                logtime = time.time()
            report['fromDeletedItems'] += 1
            if annot.get('_active', True):
                report['active'] -= 1
            else:
                report['recentVersions'] -= 1
            if remove:
                self.collection.delete_one({'_id': annot['_id']})
                Annotationelement().removeWithQuery({'_version': annot['_version']})
                report['removedVersions'] += 1
        oldPipeline = [itemLookupStep, {
            '$match': {'item': {'$ne': []}, '_active': False},
        }, {
            '$group': {'_id': '$itemId', 'annotations': {'$push': '$$ROOT'}},
        }, {
            '$project': {'annotations': {'$slice': [
                '$annotations', keepInactiveVersions, {'$size': '$annotations'},
            ]}},
        }, {
            '$unwind': '$annotations',
        }, {
            '$replaceRoot': {'newRoot': '$annotations'},
        }, recentDateStep, {
            '$match': {'mostRecentDate': {'$lt': age}},
        }]
        if time.time() - logtime > 10:
            logger.info('Finding old annotations, %r' % report)
            logtime = time.time()
        for annot in self.collection.aggregate(oldPipeline):
            if time.time() - logtime > 10:
                logger.info('Checking old annotations, %r' % report)
                logtime = time.time()
            report['oldVersions'] += 1
            report['recentVersions'] -= 1
            if remove:
                self.collection.delete_one({'_id': annot['_id']})
                Annotationelement().removeWithQuery({'_version': annot['_version']})
                report['removedVersions'] += 1
        maxVersion = Annotationelement().getNextVersionValue()
        oldElementPipeline = [{
            '$group': {'_id': '$_version'},
        }, {
            '$lookup': {
                'from': 'annotation',
                'localField': '_id',
                'foreignField': '_version',
                'as': 'matchingAnnotations',
            },
        }, {
            '$match': {'matchingAnnotations': {'$eq': []}, '_id': {'$lt': maxVersion}},
        }]
        if time.time() - logtime > 10:
            logger.info('Finding abandoned versions, %r' % report)
            logtime = time.time()
        for row in Annotationelement().collection.aggregate(oldElementPipeline):
            version = row['_id']
            if time.time() - logtime > 10:
                logger.info('Removing abandoned versions, %r' % report)
                logtime = time.time()
            report['abandonedVersions'] += 1
            if remove:
                Annotationelement().removeWithQuery({'_version': version})
                report['removedVersions'] += 1
            logger.info('Compacting annotation collection')
            self.collection.database.command('compact', self.name)
            logger.info('Compacting annotationelement collection')
            self.collection.database.command('compact', Annotationelement().name)
            logger.info('Done compacting collections')
        logger.info('Finished checking old annotations, %r' % report)
        return report

    def setMetadata(self, annotation, metadata, allowNull=False):
        """
        Set metadata on an annotation.  A `ValidationException` is thrown in
        the cases where the metadata JSON object is badly formed, or if any of
        the metadata keys contains a period ('.').

        :param annotation: The annotation to set the metadata on.
        :type annotation: dict
        :param metadata: A dictionary containing key-value pairs to add to
                         the annotations meta field
        :type metadata: dict
        :param allowNull: Whether to allow `null` values to be set in the
            annotation's metadata. If set to `False` or omitted, a `null` value
            will cause that metadata field to be deleted.
        :returns: the annotation document
        """
        if 'attributes' not in annotation['annotation']:
            annotation['annotation']['attributes'] = {}

        # Add new metadata to existing metadata
        annotation['annotation']['attributes'].update(metadata.items())

        # Remove metadata fields that were set to null
        if not allowNull:
            toDelete = [k for k, v in metadata.items() if v is None]
            for key in toDelete:
                del annotation['annotation']['attributes'][key]

        self.validateKeys(annotation['annotation']['attributes'])

        annotation['updated'] = datetime.datetime.now(datetime.timezone.utc)

        # Validate and save the annotation
        return super().save(annotation)

    def deleteMetadata(self, annotation, fields):
        """
        Delete metadata on an annotation. A `ValidationException` is thrown if
        the metadata field names contain a period ('.') or begin with a dollar
        sign ('$').

        :param annotation: The annotation to delete metadata from.
        :type annotation: dict
        :param fields: An array containing the field names to delete from the
            annotation's meta field
        :type field: list
        :returns: the annotation document
        """
        self.validateKeys(fields)

        if 'attributes' not in annotation['annotation']:
            annotation['annotation']['attributes'] = {}

        for field in fields:
            annotation['annotation']['attributes'].pop(field, None)

        annotation['updated'] = datetime.datetime.now(datetime.timezone.utc)

        return super().save(annotation)

    def geojson(self, annotation):
        """
        Yield an annotation as geojson generator.

        :param annotation: The annotation to delete metadata from.
        :yields: geojson.  General annotation properties are added to the first
            feature under the annotation tag.
        """
        yield from AnnotationGeoJSON(annotation['_id'])
