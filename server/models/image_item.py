#!/usr/bin/env python
# -*- coding: utf-8 -*-

###############################################################################
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
###############################################################################

import os

from girder.models.model_base import ValidationException
from girder.models.item import Item
from girder.plugins.worker import utils as workerUtils
from girder.plugins.jobs.constants import JobStatus

from .base import TileGeneralException
from ..tilesource import AvailableTileSources, TileSourceException


class ImageItem(Item):
    # We try these sources in this order.  The first entry is the fallback for
    # items that antedate there being multiple options.
    def initialize(self):
        super(ImageItem, self).initialize()

    def createImageItem(self, item, fileObj, user=None, token=None):
        # Using setdefault ensures that 'largeImage' is in the item
        if 'fileId' in item.setdefault('largeImage', {}):
            # TODO: automatically delete the existing large file
            raise TileGeneralException('Item already has a largeImage set.')
        if fileObj['itemId'] != item['_id']:
            raise TileGeneralException('The provided file must be in the '
                                       'provided item.')
        if (item['largeImage'].get('expected') is True and
                'jobId' in item['largeImage']):
            raise TileGeneralException('Item is scheduled to generate a '
                                       'largeImage.')

        item['largeImage'].pop('expected', None)
        item['largeImage'].pop('sourceName', None)

        item['largeImage']['fileId'] = fileObj['_id']
        job = None
        for sourceName in AvailableTileSources:
            if getattr(AvailableTileSources[sourceName], 'girderSource',
                       False):
                if AvailableTileSources[sourceName].canRead(item):
                    item['largeImage']['sourceName'] = sourceName
                    break
        if 'sourceName' not in item['largeImage']:
            # No source was successful
            del item['largeImage']['fileId']
            job = self._createLargeImageJob(item, fileObj, user, token)
            item['largeImage']['expected'] = True
            item['largeImage']['originalId'] = fileObj['_id']
            item['largeImage']['jobId'] = job['_id']

        self.save(item)
        return job

    def _createLargeImageJob(self, item, fileObj, user, token):
        path = os.path.join(os.path.dirname(__file__), '..', 'create_tiff.py')
        with open(path, 'r') as f:
            script = f.read()

        title = 'TIFF conversion: %s' % fileObj['name']
        Job = self.model('job', 'jobs')
        job = Job.createJob(
            title=title, type='large_image_tiff', handler='worker_handler',
            user=user)
        jobToken = Job.createJobToken(job)

        task = {
            'mode': 'python',
            'script': script,
            'name': title,
            'inputs': [{
                'id': 'in_path',
                'target': 'filepath',
                'type': 'string',
                'format': 'text'
            }, {
                'id': 'out_filename',
                'type': 'string',
                'format': 'text'
            }, {
                'id': 'tile_size',
                'type': 'number',
                'format': 'number'
            }, {
                'id': 'quality',
                'type': 'number',
                'format': 'number'
            }],
            'outputs': [{
                'id': 'out_path',
                'target': 'filepath',
                'type': 'string',
                'format': 'text'
            }]
        }

        inputs = {
            'in_path': workerUtils.girderInputSpec(
                item, resourceType='item', token=token),
            'quality': {
                'mode': 'inline',
                'type': 'number',
                'format': 'number',
                'data': 90
            },
            'tile_size': {
                'mode': 'inline',
                'type': 'number',
                'format': 'number',
                'data': 256
            },
            'out_filename': {
                'mode': 'inline',
                'type': 'string',
                'format': 'text',
                'data': os.path.splitext(fileObj['name'])[0] + '.tiff'
            }
        }

        outputs = {
            'out_path': workerUtils.girderOutputSpec(
                parent=item, token=token, parentType='item')
        }

        # TODO: Give the job an owner
        job['kwargs'] = {
            'task': task,
            'inputs': inputs,
            'outputs': outputs,
            'jobInfo': workerUtils.jobInfoSpec(job, jobToken),
            'auto_convert': False,
            'validate': False
        }

        job = Job.save(job)
        Job.scheduleJob(job)

        return job

    @classmethod
    def _loadTileSource(cls, item, **kwargs):
        if 'largeImage' not in item:
            raise TileSourceException('No large image file in this item.')
        if item['largeImage'].get('expected'):
            raise TileSourceException('The large image file for this item is '
                                      'still pending creation.')

        sourceName = item['largeImage']['sourceName']

        tileSource = AvailableTileSources[sourceName](item, **kwargs)
        return tileSource

    def getMetadata(self, item, **kwargs):
        tileSource = self._loadTileSource(item, **kwargs)
        return tileSource.getMetadata()

    def getTile(self, item, x, y, z, **kwargs):
        tileSource = self._loadTileSource(item, **kwargs)
        tileData = tileSource.getTile(x, y, z)
        tileMimeType = tileSource.getTileMimeType()
        return tileData, tileMimeType

    def delete(self, item):
        Job = self.model('job', 'jobs')
        deleted = False
        if 'largeImage' in item:
            job = None
            if 'jobId' in item['largeImage']:
                try:
                    job = Job.load(item['largeImage']['jobId'], force=True,
                                   exc=True)
                except ValidationException:
                    # The job has been deleted, but we still need to clean up
                    # the rest of the tile information
                    pass
            if (item['largeImage'].get('expected') and job and
                    job.get('status') in (
                    JobStatus.QUEUED, JobStatus.RUNNING)):
                # cannot cleanly remove the large image, since a conversion
                # job is currently in progress
                # TODO: cancel the job
                # TODO: return a failure error code
                return False

            # If this file was created by the worker job, delete it
            if 'jobId' in item['largeImage']:
                if job:
                    # TODO: does this eliminate all traces of the job?
                    # TODO: do we want to remove the original job?
                    Job.remove(job)
                del item['largeImage']['jobId']

            if 'originalId' in item['largeImage']:
                # The large image file should not be the original file
                assert item['largeImage']['originalId'] != \
                    item['largeImage'].get('fileId')

                if 'fileId' in item['largeImage']:
                    self.model('file').remove(self.model('file').load(
                        id=item['largeImage']['fileId'], force=True))
                del item['largeImage']['originalId']

            del item['largeImage']

            self.save(item)
            deleted = True

        return deleted

    def getThumbnail(self, item, width=None, height=None, **kwargs):
        """
        Using a tile source, get a basic thumbnail.  Aspect ratio is
        preserved.  If neither width nor height is given, a default value is
        used.  If both are given, the thumbnail will be no larger than either
        size.

        :param item: the item with the tile source.
        :param width: maximum width in pixels.
        :param height: maximum height in pixels.
        :param **kwargs: optional arguments.  Some options are encoding,
            jpegQuality, and jpegSubsampling.  This is also passed to the
            tile source.
        :returns: thumbData, thumbMime: the image data and the mime type.
        """
        tileSource = self._loadTileSource(item, **kwargs)
        thumbData, thumbMime = tileSource.getThumbnail(
            width, height, **kwargs)
        return thumbData, thumbMime

    def getRegion(self, item, **kwargs):
        """
        Using a tile source, get an arbitrary region of the image, optionally
        scaling the results.  Aspect ratio is preserved.

        :param item: the item with the tile source.
        :param **kwargs: optional arguments.  Some options are left, top,
            right, bottom, regionWidth, regionHeight, units, width, height,
            encoding, jpegQuality, and jpegSubsampling.  This is also passed to
            the tile source.
        :returns: regionData, regionMime: the image data and the mime type.
        """
        tileSource = self._loadTileSource(item, **kwargs)
        regionData, regionMime = tileSource.getRegion(**kwargs)
        return regionData, regionMime
