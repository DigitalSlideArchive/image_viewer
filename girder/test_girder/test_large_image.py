import json
import os
import tempfile
import threading
import time
from unittest import mock

import pytest

from . import girder_utilities as utilities

pytestmark = pytest.mark.girder

try:
    from girder_jobs.constants import JobStatus
    from girder_jobs.models.job import Job
    from girder_large_image import constants
    from girder_large_image.models.image_item import ImageItem
    from girder_worker.girder_plugin.status import CustomJobStatus

    from girder import events
    from girder.exceptions import ValidationException
    from girder.models.collection import Collection
    from girder.models.file import File
    from girder.models.folder import Folder
    from girder.models.group import Group
    from girder.models.item import Item
    from girder.models.setting import Setting
except ImportError:
    # Make it easier to test without girder
    pass


def _waitForJobToBeRunning(job):
    job = Job().load(id=job['_id'], force=True)
    while job['status'] != JobStatus.RUNNING:
        time.sleep(0.01)
        job = Job().load(id=job['_id'], force=True)
    return job


def _createThumbnails(server, admin, spec, cancel=False):
    params = {'spec': json.dumps(spec)}
    if cancel:
        params['logInterval'] = 0
        params['concurrent'] = 1
    resp = server.request(
        method='PUT', path='/large_image/thumbnails', user=admin, params=params)
    assert utilities.respStatus(resp) == 200
    job = resp.json
    if cancel:
        job = _waitForJobToBeRunning(job)
        job = Job().cancelJob(job)

    starttime = time.time()
    while True:
        assert time.time() - starttime < 30
        resp = server.request('/job/%s' % str(job['_id']), user=admin)
        assert utilities.respStatus(resp) == 200
        if resp.json.get('status') == JobStatus.SUCCESS:
            return True
        if resp.json.get('status') == JobStatus.ERROR:
            return False
        if resp.json.get('status') == JobStatus.CANCELED:
            return 'canceled'
        time.sleep(0.1)


@pytest.mark.singular
@pytest.mark.usefixtures('unbindLargeImage')
@pytest.mark.plugin('large_image')
def testSettings(server):
    for key in (constants.PluginSettings.LARGE_IMAGE_SHOW_THUMBNAILS,
                constants.PluginSettings.LARGE_IMAGE_SHOW_VIEWER,
                constants.PluginSettings.LARGE_IMAGE_AUTO_SET):
        Setting().set(key, 'false')
        assert not Setting().get(key)
        Setting().set(key, 'true')
        assert Setting().get(key)
        with pytest.raises(ValidationException, match='must be a boolean'):
            Setting().set(key, 'not valid')
    testExtraVal = json.dumps({'images': ['label']})
    for key in (constants.PluginSettings.LARGE_IMAGE_SHOW_EXTRA_PUBLIC,
                constants.PluginSettings.LARGE_IMAGE_SHOW_EXTRA,
                constants.PluginSettings.LARGE_IMAGE_SHOW_EXTRA_ADMIN,
                constants.PluginSettings.LARGE_IMAGE_SHOW_ITEM_EXTRA_PUBLIC,
                constants.PluginSettings.LARGE_IMAGE_SHOW_ITEM_EXTRA,
                constants.PluginSettings.LARGE_IMAGE_SHOW_ITEM_EXTRA_ADMIN,
                ):
        Setting().set(key, '')
        assert Setting().get(key) == ''
        Setting().set(key, testExtraVal)
        assert Setting().get(key) == testExtraVal
        with pytest.raises(ValidationException, match='must be a JSON'):
            Setting().set(key, 'not valid')
        with pytest.raises(ValidationException, match='must be a JSON'):
            Setting().set(key, '[1]')
    Setting().set(constants.PluginSettings.LARGE_IMAGE_DEFAULT_VIEWER, 'geojs')
    assert Setting().get(constants.PluginSettings.LARGE_IMAGE_DEFAULT_VIEWER) == 'geojs'
    with pytest.raises(ValidationException, match='must be a non-negative integer'):
        Setting().set(constants.PluginSettings.LARGE_IMAGE_MAX_THUMBNAIL_FILES, -1)
    Setting().set(constants.PluginSettings.LARGE_IMAGE_MAX_THUMBNAIL_FILES, 5)
    assert Setting().get(constants.PluginSettings.LARGE_IMAGE_MAX_THUMBNAIL_FILES) == 5
    with pytest.raises(ValidationException, match='must be a non-negative integer'):
        Setting().set(constants.PluginSettings.LARGE_IMAGE_MAX_SMALL_IMAGE_SIZE, -1)
    Setting().set(constants.PluginSettings.LARGE_IMAGE_MAX_SMALL_IMAGE_SIZE, 1024)
    assert Setting().get(constants.PluginSettings.LARGE_IMAGE_MAX_SMALL_IMAGE_SIZE) == 1024
    # Test the large_image/settings end point
    resp = server.request('/large_image/settings', user=None)
    settings = resp.json
    # The values were set earlier
    assert settings[constants.PluginSettings.LARGE_IMAGE_DEFAULT_VIEWER] == 'geojs'
    assert settings[constants.PluginSettings.LARGE_IMAGE_SHOW_VIEWER] is True
    assert settings[constants.PluginSettings.LARGE_IMAGE_SHOW_THUMBNAILS] is True
    assert settings[constants.PluginSettings.LARGE_IMAGE_SHOW_EXTRA_PUBLIC] == testExtraVal
    assert settings[constants.PluginSettings.LARGE_IMAGE_SHOW_EXTRA] == testExtraVal
    assert settings[constants.PluginSettings.LARGE_IMAGE_SHOW_EXTRA_ADMIN] == testExtraVal
    assert settings[constants.PluginSettings.LARGE_IMAGE_SHOW_ITEM_EXTRA_PUBLIC] == testExtraVal
    assert settings[constants.PluginSettings.LARGE_IMAGE_SHOW_ITEM_EXTRA] == testExtraVal
    assert settings[constants.PluginSettings.LARGE_IMAGE_SHOW_ITEM_EXTRA_ADMIN] == testExtraVal
    assert settings[constants.PluginSettings.LARGE_IMAGE_AUTO_SET] is True
    assert settings[constants.PluginSettings.LARGE_IMAGE_MAX_THUMBNAIL_FILES] == 5
    assert settings[constants.PluginSettings.LARGE_IMAGE_MAX_SMALL_IMAGE_SIZE] == 1024


@pytest.mark.usefixtures('unbindLargeImage')
@pytest.mark.plugin('large_image')
def testThumbnailFileJob(server, admin, user, fsAssetstore):
    file = utilities.uploadExternalFile('sample_image.ptif', admin, fsAssetstore)
    itemId = str(file['itemId'])

    # We should report zero thumbnails
    item = Item().load(itemId, user=admin)
    present, removed = ImageItem().removeThumbnailFiles(item, keep=10)
    assert present == 0

    # Test PUT thumbnails
    resp = server.request(method='PUT', path='/large_image/thumbnails', user=user)
    assert utilities.respStatus(resp) == 403
    resp = server.request(method='PUT', path='/large_image/thumbnails', user=admin)
    assert utilities.respStatus(resp) == 400
    assert '"spec" is required' in resp.json['message']
    resp = server.request(
        method='PUT', path='/large_image/thumbnails', user=admin,
        params={'spec': json.dumps({})})
    assert utilities.respStatus(resp) == 400
    assert 'must be a JSON list' in resp.json['message']

    # Run a job to create two sizes of thumbnails
    assert _createThumbnails(server, admin, [
        {'width': 160, 'height': 100},
        {'encoding': 'PNG'},
    ])

    # We should report two thumbnails
    present, removed = ImageItem().removeThumbnailFiles(item, keep=10)
    assert present == 2

    # Run a job to create two sizes of thumbnails, one different than
    # before
    assert _createThumbnails(server, admin, [
        {'width': 160, 'height': 100},
        {'width': 160, 'height': 160},
    ])
    # We should report three thumbnails
    present, removed = ImageItem().removeThumbnailFiles(item, keep=10)
    assert present == 3

    # Asking for a bad thumbnail specification should just do nothing
    assert not _createThumbnails(server, admin, ['not a dictionary'])
    present, removed = ImageItem().removeThumbnailFiles(item, keep=10)
    assert present == 3

    # Test GET thumbnails
    resp = server.request(path='/large_image/thumbnails', user=user)
    assert utilities.respStatus(resp) == 403
    resp = server.request(
        path='/large_image/thumbnails', user=admin,
        params={'spec': json.dumps({})})
    assert utilities.respStatus(resp) == 400
    assert 'must be a JSON list' in resp.json['message']
    resp = server.request(path='/large_image/thumbnails', user=admin)
    assert utilities.respStatus(resp) == 200
    assert resp.json == 3
    resp = server.request(
        path='/large_image/thumbnails', user=admin,
        params={'spec': json.dumps([{'width': 160, 'height': 100}])})
    assert utilities.respStatus(resp) == 200
    assert resp.json == 1

    # Test DELETE thumbnails
    resp = server.request(method='DELETE', path='/large_image/thumbnails', user=user)
    assert utilities.respStatus(resp) == 403
    resp = server.request(
        method='DELETE', path='/large_image/thumbnails', user=admin,
        params={'spec': json.dumps({})})
    assert utilities.respStatus(resp) == 400
    assert 'must be a JSON list' in resp.json['message']

    # Delete one set of thumbnails
    resp = server.request(
        method='DELETE', path='/large_image/thumbnails', user=admin,
        params={'spec': json.dumps([{'encoding': 'PNG'}])})
    assert utilities.respStatus(resp) == 200
    present, removed = ImageItem().removeThumbnailFiles(item, keep=10)
    assert present == 2

    # Try to delete some that don't exist
    resp = server.request(
        method='DELETE', path='/large_image/thumbnails', user=admin,
        params={'spec': json.dumps([{'width': 200, 'height': 200}])})
    assert utilities.respStatus(resp) == 200
    present, removed = ImageItem().removeThumbnailFiles(item, keep=10)
    assert present == 2

    # Delete them all
    resp = server.request(
        method='DELETE', path='/large_image/thumbnails', user=admin)
    assert utilities.respStatus(resp) == 200
    present, removed = ImageItem().removeThumbnailFiles(item, keep=10)
    assert present == 0

    # We should be able to cancel a job
    slowList = [
        {'width': 1600, 'height': 1000},
        {'width': 3200, 'height': 2000},
        {'width': 1600, 'height': 1002},
        {'width': 1600, 'height': 1003},
        {'width': 1600, 'height': 1004},
    ]
    assert _createThumbnails(server, admin, slowList, cancel=True) == 'canceled'
    present, removed = ImageItem().removeThumbnailFiles(item, keep=10)
    assert present < 3 + len(slowList)

    # Disable saving thumbnails so a slow process won't create one while the
    # test is cleaning up.
    Setting().set(constants.PluginSettings.LARGE_IMAGE_MAX_THUMBNAIL_FILES, 0)


@pytest.mark.usefixtures('unbindLargeImage')
@pytest.mark.plugin('large_image')
def testFolderCreateImages(server, admin, user, fsAssetstore):
    file = utilities.uploadExternalFile('sample_image.ptif', admin, fsAssetstore)
    itemId = file['itemId']
    item = Item().load(itemId, user=admin)
    folderId = str(item['folderId'])
    # Remove the large image from this item
    ImageItem().delete(item)
    # Ask to make all items in this folder large images
    resp = server.request(
        method='PUT', path=f'/large_image/folder/{folderId}/tiles', user=admin)
    assert utilities.respStatus(resp) == 200
    assert resp.json['largeImagesCreated'] == 1
    item = Item().load(itemId, user=admin)
    # Check that this item became a large image again
    assert 'largeImage' in item
    # Hitting the endpoint again should skip the item
    resp = server.request(
        method='PUT', path=f'/large_image/folder/{folderId}/tiles', user=admin)
    assert utilities.respStatus(resp) == 200
    assert resp.json['itemsSkipped'] == 1
    # If the item's source isn't working, it should be recreated.
    item['largeImage']['sourceName'] = 'unknown'
    Item().updateItem(item)
    resp = server.request(
        method='PUT', path=f'/large_image/folder/{folderId}/tiles', user=admin)
    assert utilities.respStatus(resp) == 200
    assert resp.json['largeImagesRemovedAndRecreated'] == 1


@pytest.mark.singular
@pytest.mark.usefixtures('unbindLargeImage')
@pytest.mark.plugin('large_image')
def testDeleteIncompleteTile(server, admin, user, fsAssetstore, unavailableWorker):
    # Test the large_image/settings end point
    resp = server.request(
        method='DELETE', path='/large_image/tiles/incomplete', user=user)
    assert utilities.respStatus(resp) == 403
    resp = server.request(
        method='DELETE', path='/large_image/tiles/incomplete', user=admin)
    assert utilities.respStatus(resp) == 200
    results = resp.json
    assert results['removed'] == 0

    file = utilities.uploadTestFile('yb10kx5k.png', admin, fsAssetstore)
    itemId = str(file['itemId'])
    resp = server.request(
        method='POST', path='/item/%s/tiles' % itemId, user=admin)
    resp = server.request(
        method='DELETE', path='/large_image/tiles/incomplete',
        user=admin)
    assert utilities.respStatus(resp) == 200
    results = resp.json
    assert results['removed'] == 1

    def preventCancel(evt):
        job = evt.info['job']
        params = evt.info['params']
        if (params.get('status') and
                params.get('status') != job['status'] and
                params['status'] in (JobStatus.CANCELED, CustomJobStatus.CANCELING)):
            evt.preventDefault()

    # Prevent a job from cancelling
    events.bind('jobs.job.update', 'testDeleteIncompleteTile', preventCancel)
    # Create a job and mark it as running
    resp = server.request(
        method='POST', path='/item/%s/tiles' % itemId, user=admin)
    job = Job().load(id=resp.json['_id'], force=True)
    Job().updateJob(job, status=JobStatus.RUNNING)

    resp = server.request(
        method='DELETE', path='/large_image/tiles/incomplete',
        user=admin)
    events.unbind('jobs.job.update', 'testDeleteIncompleteTile')
    assert utilities.respStatus(resp) == 200
    results = resp.json
    assert results['removed'] == 0
    assert 'could not be canceled' in results['message']
    # Now we should be able to cancel the job
    resp = server.request(
        method='DELETE', path='/large_image/tiles/incomplete',
        user=admin)
    assert utilities.respStatus(resp) == 200
    results = resp.json
    assert results['removed'] == 1


@pytest.mark.usefixtures('unbindLargeImage')
@pytest.mark.plugin('large_image')
def testCaches(server, admin):
    resp = server.request(path='/large_image/cache', user=admin)
    assert utilities.respStatus(resp) == 200
    results = resp.json
    assert 'tilesource' in results
    resp = server.request(path='/large_image/cache/clear', method='PUT', user=admin)
    assert utilities.respStatus(resp) == 200
    results = resp.json
    assert 'cacheCleared' in results


@pytest.mark.usefixtures('unbindLargeImage')
@pytest.mark.plugin('large_image')
def testAssociateImageCaching(server, admin, user, fsAssetstore):
    file = utilities.uploadExternalFile('sample_image.ptif', admin, fsAssetstore)
    itemId = str(file['itemId'])
    resp = server.request(path='/item/%s/tiles/images/label' % itemId,
                          user=admin, isJson=False)
    assert utilities.respStatus(resp) == 200
    # Test GET associated_images
    resp = server.request(path='/large_image/associated_images', user=user)
    assert utilities.respStatus(resp) == 403
    resp = server.request(path='/large_image/associated_images', user=admin)
    assert utilities.respStatus(resp) == 200
    assert resp.json == 1
    resp = server.request(path='/large_image/associated_images', user=admin, params={
        'imageKey': 'label'})
    assert utilities.respStatus(resp) == 200
    assert resp.json == 1
    resp = server.request(path='/large_image/associated_images', user=admin, params={
        'imageKey': 'macro'})
    assert utilities.respStatus(resp) == 200
    assert resp.json == 0
    # Test DELETE associated_images
    resp = server.request(
        method='DELETE', path='/large_image/associated_images', user=user)
    assert utilities.respStatus(resp) == 403
    resp = server.request(
        method='DELETE', path='/large_image/associated_images', user=admin, params={
            'imageKey': 'macro'})
    assert utilities.respStatus(resp) == 200
    assert resp.json == 0
    resp = server.request(
        method='DELETE', path='/large_image/associated_images', user=admin)
    assert utilities.respStatus(resp) == 200
    assert resp.json == 1
    resp = server.request(path='/large_image/associated_images', user=admin)
    assert utilities.respStatus(resp) == 200
    assert resp.json == 0


@pytest.mark.usefixtures('unbindLargeImage')
@pytest.mark.plugin('large_image')
def testListSources(server):
    resp = server.request(path='/large_image/sources')
    assert resp.json['tiff']['extensions']['tiff'] > 0
    assert resp.json['tiff']['version'] is not None


@pytest.mark.usefixtures('unbindLargeImage')
@pytest.mark.plugin('large_image')
def testGetLargeImagePath(server, admin, fsAssetstore):
    file = utilities.uploadExternalFile('sample_image.ptif', admin, fsAssetstore)
    itemId = str(file['itemId'])
    item = Item().load(itemId, user=admin)
    ts = ImageItem().tileSource(item)

    with mock.patch.object(File(), 'getGirderMountFilePath', return_value='mockmount'):
        path = ts._getLargeImagePath()
        abspath = os.path.abspath(path)
        assert path != file['path']
        assert path.endswith(file['path'])
        ts._mayHaveAdjacentFiles = True
        path = ts._getLargeImagePath()
        assert path == 'mockmount'
        origFile = file
        file['imported'] = True
        file['path'] = abspath
        file = File().save(file)
        path = ts._getLargeImagePath()
        assert path == abspath
        file = File().save(origFile)


@pytest.mark.usefixtures('unbindLargeImage')
@pytest.mark.plugin('large_image')
def testHistogramCaching(server, admin, user, fsAssetstore):
    file = utilities.uploadExternalFile('landcover_sample_1000.tif', admin, fsAssetstore)
    itemId = str(file['itemId'])
    resp = server.request(path='/item/%s/tiles/histogram' % itemId,
                          user=admin, isJson=False)
    assert utilities.respStatus(resp) == 200
    # Test GET histograms
    resp = server.request(path='/large_image/histograms', user=user)
    assert utilities.respStatus(resp) == 403
    resp = server.request(path='/large_image/histograms', user=admin)
    assert utilities.respStatus(resp) == 200
    assert resp.json == 1
    # Test DELETE histograms
    resp = server.request(
        method='DELETE', path='/large_image/histograms', user=user)
    assert utilities.respStatus(resp) == 403
    resp = server.request(
        method='DELETE', path='/large_image/histograms', user=admin)
    assert utilities.respStatus(resp) == 200
    assert resp.json == 1
    resp = server.request(path='/large_image/histograms', user=admin)
    assert utilities.respStatus(resp) == 200
    assert resp.json == 0


@pytest.mark.singular
@pytest.mark.usefixtures('unbindLargeImage')
@pytest.mark.plugin('large_image')
def testHistogramConcurrentCaching(server, admin, user, fsAssetstore):
    file = utilities.uploadExternalFile('sample_image.ptif', admin, fsAssetstore)
    itemId = str(file['itemId'])
    item = Item().load(itemId, force=True)
    orig = ImageItem().getAndCacheImageOrDataRun
    ImageItem().getAndCacheImageOrDataRun = mock.Mock(wraps=ImageItem().getAndCacheImageOrDataRun)
    lastCount = ImageItem().getAndCacheImageOrDataRun.call_count
    t1 = threading.Thread(
        target=ImageItem().histogram, args=(item, ), kwargs=dict(output=dict(maxWidth=4096)))
    t2 = threading.Thread(
        target=ImageItem().histogram, args=(item, ), kwargs=dict(output=dict(maxWidth=4096)))
    t1.start()
    # We want enough delay that thread 1 is running, but not so much that it
    # completes.  If this is too short, we can end up in the documented race
    # condition.  If it is too long, we don't exercise some of the code.
    time.sleep(0.2)
    t2.start()
    t1.join()
    t2.join()
    assert ImageItem().getAndCacheImageOrDataRun.call_count == lastCount + 1
    ImageItem().getAndCacheImageOrDataRun = orig


@pytest.mark.usefixtures('unbindLargeImage')
@pytest.mark.plugin('large_image')
def testYAMLConfigFile(server, admin, user, fsAssetstore):
    # Create some resources to use in the tests
    collection = Collection().createCollection(
        'collection A', admin)
    colFolderA = Folder().createFolder(
        collection, 'folder A', parentType='collection',
        creator=admin)
    colFolderB = Folder().createFolder(
        colFolderA, 'folder B', creator=admin)
    groupA = Group().createGroup('Group A', admin)

    resp = server.request(
        path='/folder/%s/yaml_config/.large_image_config.yaml' % str(colFolderB['_id']),
        method='GET')
    assert utilities.respStatus(resp) == 200
    assert resp.json.get('itemList') is not None

    resp = server.request(
        path='/folder/%s/yaml_config/sample.json' % str(colFolderB['_id']),
        method='GET')
    assert utilities.respStatus(resp) == 200
    assert resp.json.get('itemList') is None

    colFolderConfig = Folder().createFolder(
        collection, '.config', parentType='collection',
        creator=admin)
    utilities.uploadText(
        json.dumps({'keyA': 'value1'}),
        admin, fsAssetstore, colFolderConfig, 'sample.json')
    resp = server.request(
        path='/folder/%s/yaml_config/sample.json' % str(colFolderB['_id']))
    assert utilities.respStatus(resp) == 200
    assert resp.json['keyA'] == 'value1'

    utilities.uploadText(
        json.dumps({'keyA': 'value2'}),
        admin, fsAssetstore, colFolderA, 'sample.json')
    resp = server.request(
        path='/folder/%s/yaml_config/sample.json' % str(colFolderB['_id']))
    assert utilities.respStatus(resp) == 200
    assert resp.json['keyA'] == 'value2'

    utilities.uploadText(
        json.dumps({
            'keyA': 'value3',
            'groups': {
                'Group A': {'access': {'user': {'keyA': 'value4'}}}},
            'access': {'user': {'keyA': 'value5'}, 'admin': {'keyA': 'value6'}}}),
        admin, fsAssetstore, colFolderB, 'sample.json')
    resp = server.request(
        path='/folder/%s/yaml_config/sample.json' % str(colFolderB['_id']))
    assert utilities.respStatus(resp) == 200
    assert resp.json['keyA'] == 'value3'

    resp = server.request(
        path='/folder/%s/yaml_config/sample.json' % str(colFolderB['_id']), user=user)
    assert utilities.respStatus(resp) == 200
    assert resp.json['keyA'] == 'value5'

    resp = server.request(
        path='/folder/%s/yaml_config/sample.json' % str(colFolderB['_id']), user=admin)
    assert utilities.respStatus(resp) == 200
    assert resp.json['keyA'] == 'value6'

    Group().addUser(groupA, user)
    resp = server.request(
        path='/folder/%s/yaml_config/sample.json' % str(colFolderB['_id']), user=user)
    assert utilities.respStatus(resp) == 200
    assert resp.json['keyA'] == 'value4'

    resp = server.request(
        path='/folder/%s/yaml_config/sample.json' % str(colFolderB['_id']), user=admin)
    assert utilities.respStatus(resp) == 200
    assert resp.json['keyA'] == 'value6'


@pytest.mark.usefixtures('unbindLargeImage')
@pytest.mark.plugin('large_image')
def testPutYAMLConfigFile(server, admin, user, fsAssetstore):
    # Create some resources to use in the tests
    collection = Collection().createCollection(
        'collection A', admin)
    colFolderA = Folder().createFolder(
        collection, 'folder A', parentType='collection',
        creator=admin)
    colFolderB = Folder().createFolder(
        colFolderA, 'folder B', creator=admin)
    # Wrong user
    resp = server.request(
        method='PUT', user=user,
        path='/folder/%s/yaml_config/sample.yaml' % str(colFolderA['_id']),
        body=json.dumps({'keyA': 'value0'}), type='text/yaml')
    assert utilities.respStatus(resp) == 403
    # Create
    resp = server.request(
        method='PUT', user=admin,
        path='/folder/%s/yaml_config/sample.yaml' % str(colFolderA['_id']),
        body=json.dumps({'keyA': 'value1'}), type='text/yaml')
    assert utilities.respStatus(resp) == 200
    resp = server.request(
        path='/folder/%s/yaml_config/sample.yaml' % str(colFolderB['_id']))
    assert utilities.respStatus(resp) == 200
    assert resp.json['keyA'] == 'value1'
    # Lower folder
    resp = server.request(
        method='PUT', user=admin,
        path='/folder/%s/yaml_config/sample.yaml' % str(colFolderB['_id']),
        body=json.dumps({'keyA': 'value2'}), type='text/yaml')
    assert utilities.respStatus(resp) == 200
    resp = server.request(
        path='/folder/%s/yaml_config/sample.yaml' % str(colFolderB['_id']))
    assert utilities.respStatus(resp) == 200
    assert resp.json['keyA'] == 'value2'
    # Replace
    resp = server.request(
        method='PUT', user=admin,
        path='/folder/%s/yaml_config/sample.yaml' % str(colFolderB['_id']),
        body=json.dumps({'keyA': 'value3'}), type='text/yaml')
    assert utilities.respStatus(resp) == 200
    resp = server.request(
        path='/folder/%s/yaml_config/sample.yaml' % str(colFolderB['_id']))
    assert utilities.respStatus(resp) == 200
    assert resp.json['keyA'] == 'value3'


@pytest.mark.usefixtures('unbindLargeImage')
@pytest.mark.plugin('large_image')
def testYAMLConfigFileInherit(server, admin, user, fsAssetstore):
    # Create some resources to use in the tests
    collection = Collection().createCollection(
        'collection A', admin)
    colFolderA = Folder().createFolder(
        collection, 'folder A', parentType='collection',
        creator=admin)
    colFolderB = Folder().createFolder(
        colFolderA, 'folder B', creator=admin)
    colFolderConfig = Folder().createFolder(
        collection, '.config', parentType='collection',
        creator=admin)
    collectionB = Collection().createCollection(
        'collection B', admin)
    configFolder = Folder().createFolder(
        collectionB, 'any', parentType='collection',
        creator=admin)
    Setting().set(constants.PluginSettings.LARGE_IMAGE_CONFIG_FOLDER, str(configFolder['_id']))
    utilities.uploadText(
        json.dumps({
            'keyA': 'value1',
            'keyB': 'value2',
            'keyC': 'value3',
            '__inherit__': True}),
        admin, fsAssetstore, colFolderB, 'sample.json')
    utilities.uploadText(
        json.dumps({
            'keyA': 'value4',
            'keyD': 'value5',
            '__inherit__': True}),
        admin, fsAssetstore, colFolderConfig, 'sample.json')
    resp = server.request(
        path='/folder/%s/yaml_config/sample.json' % str(colFolderB['_id']), user=admin)
    assert utilities.respStatus(resp) == 200
    assert resp.json['keyA'] == 'value1'
    assert resp.json['keyB'] == 'value2'
    assert resp.json['keyC'] == 'value3'
    assert resp.json['keyD'] == 'value5'
    utilities.uploadText(
        json.dumps({
            'keyB': 'value6',
            'keyE': 'value7'}),
        admin, fsAssetstore, configFolder, 'sample.json')
    resp = server.request(
        path='/folder/%s/yaml_config/sample.json' % str(colFolderB['_id']), user=admin)
    assert utilities.respStatus(resp) == 200
    assert resp.json['keyA'] == 'value1'
    assert resp.json['keyB'] == 'value2'
    assert resp.json['keyC'] == 'value3'
    assert resp.json['keyD'] == 'value5'
    assert resp.json['keyE'] == 'value7'
    Folder().remove(colFolderConfig, user=admin)
    resp = server.request(
        path='/folder/%s/yaml_config/sample.json' % str(colFolderB['_id']), user=admin)
    assert utilities.respStatus(resp) == 200
    assert resp.json['keyA'] == 'value1'
    assert resp.json['keyB'] == 'value2'
    assert resp.json['keyC'] == 'value3'
    assert resp.json['keyE'] == 'value7'


@pytest.mark.singular
@pytest.mark.usefixtures('unbindLargeImage')
@pytest.mark.plugin('large_image')
def testConfigFileEndpoints(server, admin, fsAssetstore):
    config1 = (
        '[global]\nA = "B"\nC = {\n# comment\n  "key1": "value1"\n  }\n'
        'D = [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,'
        '25,26,27,28,29,30,31,32,33,34,35,36,37,38,39]\n')
    config2 = '[global]\nA = B'
    config3 = 'A[global]\nA = "B"'

    resp = server.request(
        method='POST', path='/large_image/config/validate', body=config1,
        user=admin, type='application/x-girder-ini')
    assert utilities.respStatus(resp) == 200
    assert resp.json == []

    for config in (config2, config3):
        resp = server.request(
            method='POST', path='/large_image/config/validate', body=config,
            user=admin, type='application/x-girder-ini')
        assert utilities.respStatus(resp) == 200
        assert len(resp.json) == 1

    resp = server.request(
        method='POST', path='/large_image/config/format', body=config1,
        user=admin, type='application/x-girder-ini')
    assert utilities.respStatus(resp) == 200
    assert resp.json != config1
    formatted = resp.json

    resp = server.request(
        method='POST', path='/large_image/config/format', body=config2,
        user=admin, type='application/x-girder-ini')
    assert utilities.respStatus(resp) == 200
    assert resp.json == config2

    oldGirderConfig = os.environ.pop('GIRDER_CONFIG', None)
    try:
        with tempfile.TemporaryDirectory() as tempDir:
            os.environ['GIRDER_CONFIG'] = os.path.join(tempDir, 'girder.cfg')
            resp = server.request(
                method='POST', path='/large_image/config/replace',
                params=dict(restart='false'), body=config1, user=admin,
                type='application/x-girder-ini')
            assert utilities.respStatus(resp) == 200
            assert os.path.exists(os.environ['GIRDER_CONFIG'])
            assert open(os.environ['GIRDER_CONFIG']).read() == config1

            resp = server.request(
                method='POST', path='/large_image/config/replace',
                params=dict(restart='false'), body=config2, user=admin,
                type='application/x-girder-ini')
            assert utilities.respStatus(resp) == 400

            resp = server.request(
                method='POST', path='/large_image/config/replace',
                params=dict(restart='false'), body=formatted, user=admin,
                type='application/x-girder-ini')
            assert utilities.respStatus(resp) == 200
            assert open(os.environ['GIRDER_CONFIG']).read() == formatted
    finally:
        os.environ.pop('GIRDER_CONFIG', None)
        if oldGirderConfig is not None:
            os.environ['GIRDER_CONFIG'] = oldGirderConfig


@pytest.mark.usefixtures('unbindLargeImage')
@pytest.mark.plugin('large_image')
def testMetadataSearch(server, admin, fsAssetstore):
    resp = server.request(
        path='/resource/search', user=admin,
        params={'q': 'value', 'mode': 'li_metadata', 'types': '["item","folder"]'})
    assert utilities.respStatus(resp) == 200
    assert resp.json == {'item': [], 'folder': []}
    resp = server.request(
        path='/resource/search', user=admin,
        params={'q': 'key:key1 value', 'mode': 'li_metadata', 'types': '["item","folder"]'})
    assert utilities.respStatus(resp) == 200
    assert resp.json == {'item': [], 'folder': []}
    resp = server.request(
        path='/resource/search', user=admin,
        params={'q': 'key:key2 value', 'mode': 'li_metadata', 'types': '["item","folder"]'})
    assert utilities.respStatus(resp) == 200
    assert resp.json == {'item': [], 'folder': []}
    file = utilities.uploadTestFile('yb10kx5k.png', admin, fsAssetstore)
    itemId = str(file['itemId'])
    item = Item().load(id=itemId, force=True)
    Item().setMetadata(item, {'key1': 'value1'})
    resp = server.request(
        path='/resource/search', user=admin,
        params={'q': 'value', 'mode': 'li_metadata', 'types': '["item","folder"]'})
    assert utilities.respStatus(resp) == 200
    assert resp.json != {'item': [], 'folder': []}
    assert len(resp.json['item']) == 1
    resp = server.request(
        path='/resource/search', user=admin,
        params={'q': 'key:key1 value', 'mode': 'li_metadata', 'types': '["item","folder"]'})
    assert utilities.respStatus(resp) == 200
    assert len(resp.json['item']) == 1
    resp = server.request(
        path='/resource/search', user=admin,
        params={'q': 'key:key2 value', 'mode': 'li_metadata', 'types': '["item","folder"]'})
    assert utilities.respStatus(resp) == 200
    assert len(resp.json['item']) == 0


@pytest.mark.usefixtures('unbindLargeImage')
@pytest.mark.plugin('large_image')
def testFlattenItemLists(server, admin, user, fsAssetstore):
    collection = Collection().createCollection(
        'collection A', admin)
    colFolderA = Folder().createFolder(
        collection, 'folder A', parentType='collection',
        creator=admin)
    colFolderB = Folder().createFolder(
        colFolderA, 'folder B', creator=admin)
    utilities.uploadText(
        json.dumps({'keyA': 'value1'}),
        admin, fsAssetstore, colFolderA, 'sample1.json')
    utilities.uploadText(
        json.dumps({'keyB': 'value2'}),
        admin, fsAssetstore, colFolderB, 'sample2.json')
    resp = server.request(
        path='/item', user=admin,
        params={'folderId': str(colFolderA['_id'])})
    assert utilities.respStatus(resp) == 200
    assert len(resp.json) == 1
    resp = server.request(
        path='/item', user=admin,
        params={'folderId': str(colFolderB['_id'])})
    assert utilities.respStatus(resp) == 200
    assert len(resp.json) == 1
    resp = server.request(
        path='/item', user=admin,
        params={'folderId': str(colFolderA['_id']), 'text': '_recurse_:'})
    assert utilities.respStatus(resp) == 200
    assert len(resp.json) == 2
    resp = server.request(
        path='/item', user=admin,
        params={'folderId': str(colFolderB['_id']), 'text': '_recurse_:'})
    assert utilities.respStatus(resp) == 200
    assert len(resp.json) == 1
    resp = server.request(
        path='/item', user=admin,
        params={'folderId': str(colFolderA['_id']), 'text': '_recurse_:sample1'})
    assert utilities.respStatus(resp) == 200
    assert len(resp.json) == 1
    resp = server.request(
        path='/item', user=admin,
        params={'folderId': str(colFolderB['_id']), 'text': '_recurse_:sample1'})
    assert utilities.respStatus(resp) == 200
    assert len(resp.json) == 0
    resp = server.request(
        path='/item', user=admin,
        params={'folderId': str(colFolderA['_id']), 'text': '_recurse_:', 'name': 'sample1.json'})
    assert utilities.respStatus(resp) == 200
    assert len(resp.json) == 1
    resp = server.request(
        path='/item', user=admin,
        params={'folderId': str(colFolderB['_id']), 'text': '_recurse_:', 'name': 'sample1.json'})
    assert utilities.respStatus(resp) == 200
    assert len(resp.json) == 0
