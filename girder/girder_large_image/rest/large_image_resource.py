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
import json
import logging
import os
import pprint
import re
import shutil
import threading
import time

import cherrypy
import pymongo
from girder_jobs.constants import JobStatus
from girder_jobs.models.job import Job

import large_image
from girder.api import access
from girder.api.describe import Description, autoDescribeRoute, describeRoute
from girder.api.rest import Resource
from girder.constants import AccessType, SortDir, TokenScope
from girder.exceptions import RestException
from girder.models.file import File
from girder.models.folder import Folder
from girder.models.item import Item
from girder.models.setting import Setting
from girder.utility import toBool
from large_image import cache_util
from large_image.exceptions import TileGeneralError, TileSourceError

from .. import constants, girder_tilesource
from ..models.image_item import ImageItem

logger = logging.getLogger(__name__)


def createThumbnailsJobTask(item, spec):
    """
    For an individual item, check or create all of the appropriate thumbnails.

    :param item: the image item.
    :param spec: a list of thumbnail specifications.
    :returns: a dictionary with the total status of the thumbnail job.
    """
    status = {'checked': 0, 'created': 0, 'failed': 0}
    for entry in spec:
        try:
            if entry.get('imageKey'):
                result = ImageItem().getAssociatedImage(item, checkAndCreate=True, **entry)
            else:
                result = ImageItem().getThumbnail(item, checkAndCreate=True, **entry)
            status['checked' if result is True else 'created'] += 1
        except TileGeneralError as exc:
            status['failed'] += 1
            status['lastFailed'] = str(item['_id'])
            logger.info('Failed to get thumbnail for item %s: %r' % (item['_id'], exc))
        except AttributeError:
            raise
        except Exception:
            status['failed'] += 1
            status['lastFailed'] = str(item['_id'])
            logger.exception(
                'Unexpected exception when trying to create a thumbnail for item %s' %
                item['_id'])
    return status


def createThumbnailsJobLog(job, info, prefix='', status=None):
    """
    Log information about the create thumbnails job.

    :param job: the job object.
    :param info: a dictionary with the number of thumbnails checked, created,
        and failed.
    :param prefix: a string to place in front of the log message.
    :param status: if not None, a new status for the job.
    """
    msg = prefix + 'Checked %d, created %d thumbnail files' % (
        info['checked'], info['created'])
    if prefix == '' and info.get('items', 0) * info.get('specs', 0):
        done = info['checked'] + info['created'] + info['failed']
        if done < info['items'] * info['specs']:
            msg += ' (estimated %4.2f%% done)' % (
                100.0 * done / (info['items'] * info['specs']))
    msg += '\n'
    if info['failed']:
        msg += 'Failed on %d thumbnail file%s (last failure on item %s)\n' % (
            info['failed'],
            's' if info['failed'] != 1 else '', info['lastFailed'])
    job = Job().updateJob(job, log=msg, status=status)
    return job, msg


def cursorNextOrNone(cursor):
    """
    Given a Mongo cursor, return the next value if there is one.  If not,
    return None.

    :param cursor: a cursor to get a value from.
    :returns: the next value or None.
    """
    try:
        return cursor.next()
    except StopIteration:
        return None


def createThumbnailsJob(job):
    thread = threading.Thread(target=createThumbnailsJobThread, args=(job, ), daemon=True)
    thread.start()


def createThumbnailsJobThread(job):  # noqa
    """
    Create thumbnails for all of the large image items.

    The job object contains::

      - spec: an array, each entry of which is the parameter dictionary
        for the model getThumbnail function.
      - logInterval: the time in seconds between log messages.  This
        also controls the granularity of cancelling the job.
      - concurrent: the number of threads to use.  0 for the number of
        cpus.

    :param job: the job object including kwargs.
    """
    job = Job().updateJob(
        job, log='Started creating large image thumbnails\n',
        status=JobStatus.RUNNING)
    concurrency = int(job['kwargs'].get('concurrent', 0))
    concurrency = large_image.config.cpu_count(
        logical=True) if concurrency < 1 else concurrency
    status = {
        'checked': 0,
        'created': 0,
        'failed': 0,
    }

    spec = job['kwargs']['spec']
    logInterval = float(job['kwargs'].get('logInterval', 10))
    job = Job().updateJob(job, log='Creating thumbnails (%d concurrent)\n' % concurrency)
    nextLogTime = time.time() + logInterval
    tasks = []
    # This could be switched from ThreadPoolExecutor to ProcessPoolExecutor
    # without any other changes.  Doing so would probably improve parallel
    # performance, but may not work reliably under Python 2.x.
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=concurrency)
    try:
        # Get a cursor with the list of images
        query = {'largeImage.fileId': {'$exists': True}}
        sort = [('_id', SortDir.ASCENDING)]
        items = Item().find(query, sort=sort)
        if hasattr(items, 'count'):
            status['items'] = items.count()
        status['specs'] = len(spec)
        nextitem = cursorNextOrNone(items)
        while len(tasks) or nextitem is not None:
            # Create more tasks than we strictly need so if one finishes before
            # we check another will be ready.  This is balanced with not
            # creating too many to avoid excessive memory use.  As such, we
            # can't do a simple iteration over the database cursor, as it will
            # be exhausted before we are done.
            while len(tasks) < concurrency * 4 and nextitem is not None:
                tasks.append(pool.submit(createThumbnailsJobTask, nextitem, spec))
                try:
                    nextitem = cursorNextOrNone(items)
                except pymongo.errors.CursorNotFound:
                    # If the process takes long enough, the cursor is removed.
                    # In this case, redo the query and keep going.
                    items = Item().find(query, sort=sort)
                    nextitem = cursorNextOrNone(items)
                if nextitem is not None:
                    query['_id'] = {'$gt': nextitem['_id']}
            # Wait a short time or until the oldest task is complete
            try:
                tasks[0].result(0.1)
            except concurrent.futures.TimeoutError:
                pass
            # Remove completed tasks from our list, adding their results to the
            # status.
            for pos in range(len(tasks) - 1, -1, -1):
                if tasks[pos].done():
                    r = tasks[pos].result()
                    status['created'] += r['created']
                    status['checked'] += r['checked']
                    status['failed'] += r['failed']
                    status['lastFailed'] = r.get('lastFailed', status.get('lastFailed'))
                    tasks[pos:pos + 1] = []
            # Periodically, log the state of the job and check if it was
            # deleted or canceled.
            if time.time() > nextLogTime:
                job, msg = createThumbnailsJobLog(job, status)
                # Check if the job was deleted or canceled; if so, quit
                job = Job().load(id=job['_id'], force=True)
                if not job or job['status'] in (JobStatus.CANCELED, JobStatus.ERROR):
                    cause = {
                        None: 'deleted',
                        JobStatus.CANCELED: 'canceled',
                        JobStatus.ERROR: 'stopped due to error',
                    }[None if not job else job.get('status')]
                    msg = 'Large image thumbnails job %s' % cause
                    logger.info(msg)
                    # Cancel any outstanding tasks.  If they haven't started,
                    # they are discarded.  Those that have started will still
                    # run, though.
                    for task in tasks:
                        task.cancel()
                    return
                nextLogTime = time.time() + logInterval
    except Exception:
        logger.exception('Error with large image create thumbnails job')
        Job().updateJob(
            job, log='Error creating large image thumbnails\n',
            status=JobStatus.ERROR)
        return
    finally:
        # Clean up the task pool asynchronously
        pool.shutdown(False)
    job, msg = createThumbnailsJobLog(job, status, 'Finished: ', JobStatus.SUCCESS)
    logger.info(msg)


class LargeImageResource(Resource):

    def __init__(self):
        super().__init__()

        self.resourceName = 'large_image'
        self.route('GET', ('cache', ), self.cacheInfo)
        self.route('PUT', ('cache', 'clear'), self.cacheClear)
        self.route('POST', ('config', 'format'), self.configFormat)
        self.route('POST', ('config', 'validate'), self.configValidate)
        self.route('POST', ('config', 'replace'), self.configReplace)
        self.route('GET', ('settings',), self.getPublicSettings)
        self.route('GET', ('sources',), self.listSources)
        self.route('GET', ('thumbnails',), self.countThumbnails)
        self.route('PUT', ('thumbnails',), self.createThumbnails)
        self.route('DELETE', ('thumbnails',), self.deleteThumbnails)
        self.route('GET', ('associated_images',), self.countAssociatedImages)
        self.route('DELETE', ('associated_images',), self.deleteAssociatedImages)
        self.route('GET', ('histograms',), self.countHistograms)
        self.route('DELETE', ('histograms',), self.deleteHistograms)
        self.route('DELETE', ('tiles', 'incomplete'), self.deleteIncompleteTiles)
        self.route('PUT', ('folder', ':id', 'tiles'), self.createLargeImages)

    @describeRoute(
        Description('Clear tile source caches to release resources and file handles.'),
    )
    @access.admin(scope=TokenScope.DATA_WRITE)
    def cacheClear(self, params):
        import gc

        before = cache_util.cachesInfo()
        cache_util.cachesClear()
        after = cache_util.cachesInfo()
        # Add a small delay to give the memcached time to clear
        stoptime = time.time() + 5
        while time.time() < stoptime and any(after[key]['used'] for key in after):
            time.sleep(0.1)
            after = cache_util.cachesInfo()
        gc.collect()
        return {
            'cacheCleared': datetime.datetime.now(datetime.timezone.utc),
            'before': before,
            'after': after,
        }

    @describeRoute(
        Description('Get information on caches.'),
    )
    @access.admin(scope=TokenScope.DATA_READ)
    def cacheInfo(self, params):
        return cache_util.cachesInfo()

    @describeRoute(
        Description('Get public settings for large image display.'),
    )
    @access.public(scope=TokenScope.DATA_READ)
    def getPublicSettings(self, params):
        keys = [getattr(constants.PluginSettings, key)
                for key in dir(constants.PluginSettings)
                if key.startswith('LARGE_IMAGE_')]
        return {k: Setting().get(k) for k in keys}

    @describeRoute(
        Description('Count the number of cached thumbnail files for '
                    'large_image items.')
        .param('spec', 'A JSON list of thumbnail specifications to count.  '
               'If empty, all cached thumbnails are counted.  The '
               'specifications typically include width, height, encoding, and '
               'encoding options.', required=False),
    )
    @access.admin(scope=TokenScope.DATA_READ)
    def countThumbnails(self, params):
        return self._countCachedImages(params.get('spec'))

    @describeRoute(
        Description('Count the number of cached associated image files for '
                    'large_image items.')
        .param('imageKey', 'If specific, only include images with the '
               'specified key', required=False)
        .notes('The imageKey can also be "tileFrames".'),
    )
    @access.admin(scope=TokenScope.DATA_READ)
    def countAssociatedImages(self, params):
        return self._countCachedImages(
            None, associatedImages=True, imageKey=params.get('imageKey'))

    def _countCachedImages(self, spec, associatedImages=False, imageKey=None):
        if spec is not None:
            try:
                spec = json.loads(spec)
                if not isinstance(spec, list):
                    raise ValueError
            except ValueError:
                msg = 'The spec parameter must be a JSON list.'
                raise RestException(msg)
            spec = [json.dumps(entry, sort_keys=True, separators=(',', ':'))
                    for entry in spec]
        else:
            spec = [None]
        count = 0
        for entry in spec:
            query = {'isLargeImageThumbnail': True, 'attachedToType': 'item'}
            if entry is not None:
                query['thumbnailKey'] = entry
            elif associatedImages:
                if imageKey and re.match(r'^[0-9A-Za-z].*$', imageKey):
                    query['thumbnailKey'] = {'$regex': '"imageKey":"%s"' % imageKey}
                else:
                    query['thumbnailKey'] = {'$regex': '"imageKey":'}
            count += File().find(query).count()
        return count

    @describeRoute(
        Description('Create cached thumbnail files from large_image items.')
        .notes('This creates a local job that processes all large_image '
               'items.  A common spec for the Girder API is: [{"width": 160, '
               '"height": 100}, {"width": 160, "height": 100, "imageKey": '
               '"macro"}, {"width": 160, "height": 100, "imageKey": "label"}]')
        .param('spec', 'A JSON list of thumbnail specifications to create.  '
               'The specifications typically include width, height, encoding, '
               'and encoding options.')
        .param('logInterval', 'The number of seconds between log messages.  '
               'This also determines how often the creation job is checked if '
               'it has been canceled or deleted.  A value of 0 will log after '
               'each thumbnail is checked or created.', required=False,
               dataType='float')
        .param('concurrent', 'The number of concurrent threads to use when '
               'making thumbnails.  0 or unspecified to base this on the '
               'number of reported cpus.', required=False, dataType='int'),
    )
    @access.admin(scope=TokenScope.DATA_WRITE)
    def createThumbnails(self, params):
        self.requireParams(['spec'], params)
        try:
            spec = json.loads(params['spec'])
            if not isinstance(spec, list):
                raise ValueError
        except ValueError:
            msg = 'The spec parameter must be a JSON list.'
            raise RestException(msg)
        maxThumbnailFiles = int(Setting().get(
            constants.PluginSettings.LARGE_IMAGE_MAX_THUMBNAIL_FILES))
        if maxThumbnailFiles <= 0:
            msg = 'Thumbnail files are not enabled.'
            raise RestException(msg)
        jobKwargs = {'spec': spec}
        if params.get('logInterval') is not None:
            jobKwargs['logInterval'] = float(params['logInterval'])
        if params.get('concurrent') is not None:
            jobKwargs['concurrent'] = float(params['concurrent'])
        job = Job().createLocalJob(
            module='girder_large_image.rest.large_image_resource',
            function='createThumbnailsJob',
            kwargs=jobKwargs,
            title='Create large image thumbnail files.',
            type='large_image_create_thumbnails',
            user=self.getCurrentUser(),
            public=True,
        )
        Job().scheduleJob(job)
        return job

    @describeRoute(
        Description('Delete cached thumbnail files from large_image items.')
        .param('spec', 'A JSON list of thumbnail specifications to delete.  '
               'If empty, all cached thumbnails are deleted.  The '
               'specifications typically include width, height, encoding, and '
               'encoding options.', required=False),
    )
    @access.admin(scope=TokenScope.DATA_WRITE)
    def deleteThumbnails(self, params):
        return self._deleteCachedImages(params.get('spec'))

    @describeRoute(
        Description('Delete cached associated image files from large_image items.')
        .param('imageKey', 'If specific, only include images with the '
               'specified key', required=False),
    )
    @access.admin(scope=TokenScope.DATA_WRITE)
    def deleteAssociatedImages(self, params):
        return self._deleteCachedImages(
            None, associatedImages=True, imageKey=params.get('imageKey'))

    def _deleteCachedImages(self, spec, associatedImages=False, imageKey=None):
        if spec is not None:
            try:
                spec = json.loads(spec)
                if not isinstance(spec, list):
                    raise ValueError
            except ValueError:
                msg = 'The spec parameter must be a JSON list.'
                raise RestException(msg)
            spec = [json.dumps(entry, sort_keys=True, separators=(',', ':'))
                    for entry in spec]
        else:
            spec = [None]
        removed = 0
        for entry in spec:
            query = {'isLargeImageThumbnail': True, 'attachedToType': 'item'}
            if entry is not None:
                query['thumbnailKey'] = entry
            elif associatedImages:
                if imageKey and re.match(r'^[0-9A-Za-z].*$', imageKey):
                    query['thumbnailKey'] = {'$regex': '"imageKey":"%s"' % imageKey}
                else:
                    query['thumbnailKey'] = {'$regex': '"imageKey":'}
            for file in File().find(query):
                File().remove(file)
                removed += 1
        return removed

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description('Create large images for all items within a folder.')
        .notes('Does not work for new items with multiple files.')
        .modelParam('id', 'The ID of the folder.', model=Folder,
                    level=AccessType.WRITE, required=True)
        .param('createJobs', 'If true, a job will be used to create the image '
               'when needed; if always, a job will always be used; if false, '
               'a job will never be used, creating a version of the image in '
               'a preferred format.', dataType='string', default='false',
               required=False, enum=['true', 'false', 'always'])
        .param('localJobs', 'If true, run each creation job locally; if false, '
               'run via the remote worker.', dataType='boolean', default='false',
               required=False)
        .param('recurse', 'If true, items in child folders will also be checked.',
               dataType='boolean', default=False, required=False)
        .param('cancelJobs', 'If true, unfinished large image job(s) associated '
               'with items in the folder will be canceled, then a new large '
               'image created; if false, items with an unfinished large image '
               'will be skipped.', dataType='boolean', default=False, required=False)
        .param('redoExisting', 'If true, existing large images should be removed and '
               'recreated. Otherwise they will be skipped.', dataType='boolean',
               default=False, required=False)
        .errorResponse('ID was invalid.')
        .errorResponse('Write access was denied for the folder.', 403),
    )
    def createLargeImages(self, folder, createJobs, localJobs, recurse, cancelJobs, redoExisting):
        user = self.getCurrentUser()
        if createJobs != 'always':
            createJobs = toBool(createJobs)
        return self._createLargeImagesRecurse(
            folder=folder, user=user, recurse=recurse, createJobs=createJobs,
            localJobs=localJobs, cancelJobs=cancelJobs, redo=redoExisting)

    def _createLargeImagesRecurse(
            self, folder, user, recurse, createJobs, localJobs, cancelJobs,
            redo, result=None):
        if result is None:
            result = {'childFoldersRecursed': 0,
                      'itemsSkipped': 0,
                      'jobsCanceled': 0,
                      'jobsFailedToCancel': 0,
                      'largeImagesCreated': 0,
                      'largeImagesNotCreated': 0,
                      'largeImagesRemovedAndRecreated': 0,
                      'largeImagesRemovedAndNotRecreated': 0,
                      'totalItems': 0}
        if recurse:
            for childFolder in Folder().childFolders(parent=folder, parentType='folder'):
                result['childFoldersRecursed'] += 1
                self.createLargeImagesRecurse(
                    childFolder, user, recurse, createJobs, localJobs,
                    cancelJobs, redo, result)
        for item in Folder().childItems(folder=folder):
            result['totalItems'] += 1
            self._createLargeImagesItem(
                item, user, createJobs, localJobs, cancelJobs, redo, result)
        return result

    def _createLargeImagesItem(
            self, item, user, createJobs, localJobs, cancelJobs, redo, result):
        if item.get('largeImage'):
            previousFileId = item['largeImage'].get('originalId', item['largeImage']['fileId'])
            if item['largeImage'].get('expected'):
                if not cancelJobs:
                    result['itemsSkipped'] += 1
                    return
                job = Job().load(item['largeImage']['jobId'], force=True)
                if job and job.get('status') in {
                        JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.INACTIVE}:
                    job = Job().cancelJob(job)
                if job and job.get('status') in {
                        JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.INACTIVE}:
                    result['jobsFailedToCancel'] += 1
                    result['itemsSkipped'] += 1
                    return
                result['jobsCanceled'] += 1
            else:
                try:
                    ImageItem().getMetadata(item)
                    if not redo:
                        result['itemsSkipped'] += 1
                        return
                except (TileSourceError, KeyError):
                    pass
            ImageItem().delete(item)
            try:
                ImageItem().createImageItem(
                    item, File().load(user=user, id=previousFileId),
                    createJob=createJobs, localJob=localJobs)
                result['largeImagesRemovedAndRecreated'] += 1
            except Exception:
                result['largeImagesRemovedAndNotRecreated'] += 1
        else:
            files = list(Item().childFiles(item=item, limit=2))
            if len(files) == 1:
                try:
                    ImageItem().createImageItem(
                        item, files[0], createJob=createJobs, localJob=localJobs)
                    result['largeImagesCreated'] += 1
                except Exception:
                    result['largeImagesNotCreated'] += 1
            else:
                result['itemsSkipped'] += 1

    @describeRoute(
        Description('Remove large images from items where the large image job '
                    'incomplete.')
        .notes('This is used to clean up all large image conversion jobs that '
               'have failed to complete.  If a job is in progress, it will be '
               'cancelled.  The return value is the number of items that were '
               'adjusted.'),
    )
    @access.admin(scope=TokenScope.DATA_WRITE)
    def deleteIncompleteTiles(self, params):
        result = {'removed': 0}
        while True:
            item = Item().findOne({'largeImage.expected': True})
            if not item:
                break
            job = Job().load(item['largeImage']['jobId'], force=True)
            if job and job.get('status') in (
                    JobStatus.QUEUED, JobStatus.RUNNING):
                job = Job().cancelJob(job)
            if job and job.get('status') in (
                    JobStatus.QUEUED, JobStatus.RUNNING):
                result['message'] = ('The job for item %s could not be '
                                     'canceled' % (str(item['_id'])))
                break
            ImageItem().delete(item)
            result['removed'] += 1
        return result

    @describeRoute(
        Description('List all Girder tile sources with associated extensions, '
                    'mime types, and versions.  Lower values indicate a '
                    'higher priority for an extension or mime type with that '
                    'source.'),
    )
    @access.public(scope=TokenScope.DATA_READ)
    def listSources(self, params):
        return large_image.tilesource.listSources(
            girder_tilesource.AvailableGirderTileSources)['sources']

    @describeRoute(
        Description('Count the number of cached histograms for large_image items.'),
    )
    @access.admin(scope=TokenScope.DATA_READ)
    def countHistograms(self, params):
        query = {
            'isLargeImageData': True,
            'attachedToType': 'item',
            'thumbnailKey': {'$regex': '"imageKey":"histogram"'},
        }
        count = File().find(query).count()
        return count

    @describeRoute(
        Description('Delete cached histograms from large_image items.'),
    )
    @access.admin(scope=TokenScope.DATA_WRITE)
    def deleteHistograms(self, params):
        query = {
            'isLargeImageData': True,
            'attachedToType': 'item',
            'thumbnailKey': {'$regex': '"imageKey":"histogram"'},
        }
        removed = 0
        for file in File().find(query):
            File().remove(file)
            removed += 1
        return removed

    def _configValidateException(self, exc, lineno=None):
        """
        Report a config validation exception with a line number.
        """
        try:
            msg = str(exc)
            matches = re.search(r'line: (\d+)', msg)
            if not matches:
                matches = re.search(r'\[line[ ]*(\d+)\]', msg)
            if matches:
                line = int(matches.groups()[0])
                msg = msg.split('\n', 1)[0].strip() or 'General error'
                msg = msg.rsplit(": '<string>'", 1)[0].rsplit("'<string>'", 1)[-1].strip()
                return [{'line': line - 1, 'message': msg}]
        except Exception:
            pass
        if lineno is not None:
            return [{'line': lineno, 'message': str(exc)}]
        return [{'line': 0, 'message': 'General error'}]

    def _configValidate(self, config):
        """
        Check if a Girder config file will validate.  If not, return an
        array of lines where it fails to validate.

        :param config: The string representation of the config file to
            validate.
        :returns: a list of errors, though usually only the first one.
        """
        parser = cherrypy.lib.reprconf.Parser()
        try:
            parser.read_string(config)
        except Exception as exc:
            return self._configValidateException(exc)
        err = None
        try:
            parser.as_dict()
            return []
        except Exception as exc:
            err = exc
            try:
                parser.as_dict(raw=True)
                return self._configValidateException(exc)
            except Exception:
                pass
        lines = io.StringIO(config).readlines()
        for pos in range(len(lines), 0, -1):
            try:
                parser = cherrypy.lib.reprconf.Parser()
                parser.read_string(''.join(lines[:pos]))
                parser.as_dict()
                return self._configValidateException('Config values must be valid Python.', pos)
            except Exception:
                pass
        return self._configValidateException(err)

    @autoDescribeRoute(
        Description('Validate a Girder config file')
        .notes('Returns a list of errors found.')
        .param('config', 'The contents of config file to validate.',
               paramType='body'),
    )
    @access.admin(scope=TokenScope.DATA_WRITE)
    def configValidate(self, config):
        config = config.read().decode('utf8')
        return self._configValidate(config)

    @autoDescribeRoute(
        Description('Reformat a Girder config file')
        .param('config', 'The contents of config file to format.',
               paramType='body'),
    )
    @access.admin(scope=TokenScope.DATA_WRITE)
    def configFormat(self, config):
        config = config.read().decode('utf8')
        if len(self._configValidate(config)):
            return config
        # reformat here
        # collect comments
        comments = ['[__comment__]\n']
        for line in io.StringIO(config):
            if line.strip()[:1] in {'#', ';'}:
                line = '__comment__%d = %r\n' % (len(comments), line)
                # If a comment is in the middle of a value, hoist it up
                for pos in range(len(comments), 0, -1):
                    try:
                        parser = cherrypy.lib.reprconf.Parser()
                        parser.read_string(''.join(comments[:pos]))
                        parser.as_dict(raw=True)
                        comments[pos:pos] = [line]
                        break
                    except Exception:
                        pass
            else:
                comments.append(line)
        parser = cherrypy.lib.reprconf.Parser()
        parser.read_string(''.join(comments))
        results = parser.as_dict(raw=True)
        # Build results
        out = []
        for section in results:
            if section != '__comment__':
                out.append('[%s]\n' % section)
            for key, val in results[section].items():
                if not key.startswith('__comment__'):
                    valstr = repr(val)
                    if len(valstr) + len(key) + 3 >= 79:
                        valstr = pprint.pformat(
                            val, width=79, indent=2, compact=True, sort_dicts=False)
                    out.append('%s = %s\n' % (key, valstr))
                else:
                    out.append(val)
            if section != '__comment__':
                out.append('\n')
        return ''.join(out)

    @autoDescribeRoute(
        Description('Replace the existing Girder config file')
        .param('restart', 'Whether to restart the server after updating the '
               'config file', required=False, dataType='boolean', default=True)
        .param('config', 'The new contents of config file.',
               paramType='body'),
    )
    @access.admin(scope=TokenScope.USER_AUTH)
    def configReplace(self, config, restart):
        config = config.read().decode('utf8')
        if len(self._configValidate(config)):
            msg = 'Invalid config file'
            raise RestException(msg)
        path = os.path.join(os.path.expanduser('~'), '.girder', 'girder.cfg')
        if 'GIRDER_CONFIG' in os.environ:
            path = os.environ['GIRDER_CONFIG']
        if os.path.exists(path):
            contents = open(path).read()
            if contents == config:
                return {'status': 'no change'}
            newpath = path + '.' + time.strftime(
                '%Y%m%d-%H%M%S', time.localtime(os.stat(path).st_mtime))
            logger.info('Copying existing config file from %s to %s', path, newpath)
            shutil.copy2(path, newpath)
        logger.warning('Replacing config file %s', path)
        open(path, 'w').write(config)

        class Restart(cherrypy.process.plugins.Monitor):
            def __init__(self, bus, frequency=1):
                cherrypy.process.plugins.Monitor.__init__(
                    self, bus, self.run, frequency)

            def start(self):
                cherrypy.process.plugins.Monitor.start(self)

            def run(self):
                self.bus.log('Restarting.')
                self.thread.cancel()
                self.bus.restart()

        if restart:
            restart = Restart(cherrypy.engine)
            restart.subscribe()
            restart.start()
            return {'restarted': datetime.datetime.now(datetime.timezone.utc)}
        return {'status': 'updated', 'time': datetime.datetime.now(datetime.timezone.utc)}
