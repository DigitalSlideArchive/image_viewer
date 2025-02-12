import inspect
import logging
import os
import shutil
import sys
import time

from girder_worker.app import app
from girder_worker.utils import girder_job

logger = logging.getLogger(__name__)


@girder_job(title='Create a pyramidal tiff using vips', type='large_image_tiff')
@app.task(bind=True)
def create_tiff(self, inputFile, outputName=None, outputDir=None, quality=90,
                tileSize=256, **kwargs):
    """
    Take a source input file, readable by vips, and output a pyramidal tiff
    file.

    :param inputFile: the path to the input file or base file of a set.
    :param outputName: the name of the output file.  If None, the name is
        based on the input name and current date and time.  May be a full path.
    :param outputDir: the location to store the output.  If unspecified, the
        inputFile's directory is used.  If the outputName is a fully qualified
        path, this is ignored.
    :param quality: a jpeg quality passed to vips.  0 is small, 100 is high
        quality.  90 or above is recommended.
    :param tileSize: the horizontal and vertical tile size.
    Optional parameters that can be specified in kwargs:
    :param compression: one of 'jpeg', 'deflate' (zip), 'lzw', 'packbits', or
        'zstd'.
    :param level: compression level for zstd, 1-22 (default is 10).
    :param predictor: one of 'none', 'horizontal', or 'float' used for lzw and
        deflate.
    :param inputName: if no output name is specified, and this is specified,
        this is used as the basis of the output name instead of extracting the
        name from the inputFile path.
    :returns: output path.
    """
    import large_image_converter

    logger = logging.getLogger('large-image-converter')
    if not len(logger.handlers):
        logger.addHandler(logging.StreamHandler(sys.stdout))
    if not logger.level:
        logger.setLevel(logging.INFO)

    if '_concurrency' not in kwargs:
        kwargs['_concurrency'] = -2
    inputPath = os.path.abspath(os.path.expanduser(inputFile))
    geospatial = large_image_converter.is_geospatial(inputPath)
    inputName = kwargs.get('inputName', os.path.basename(inputPath))
    suffix = large_image_converter.format_hook('adjust_params', geospatial, kwargs, **kwargs)
    suffix = suffix or ('.tiff' if not geospatial else '.geo.tiff')
    if not outputName:
        outputName = os.path.splitext(inputName)[0] + suffix
        if outputName.endswith('.geo' + suffix):
            outputName = outputName[:len(outputName) - len(suffix) - 4] + suffix
        if outputName == inputName:
            outputName = (os.path.splitext(inputName)[0] + '.' +
                          time.strftime('%Y%m%d-%H%M%S') + suffix)
    renameOutput = outputName
    if not outputName.endswith(suffix):
        outputName += suffix
    if not outputDir:
        outputDir = os.path.dirname(inputPath)
    outputPath = os.path.join(outputDir, outputName)
    large_image_converter.convert(
        inputPath, outputPath, quality=quality, tileSize=tileSize, **kwargs)
    if not os.path.exists(outputPath):
        msg = 'Conversion command failed to produce output'
        raise Exception(msg)
    if renameOutput != outputName:
        renamePath = os.path.join(outputDir, renameOutput)
        shutil.move(outputPath, renamePath)
        outputPath = renamePath
    logger.info('Created a file of size %d', os.path.getsize(outputPath))
    return outputPath


class JobLogger(logging.Handler):
    def __init__(self, level=logging.NOTSET, job=None, *args, **kwargs):
        self._job = job
        super().__init__(level=level, **kwargs)

    def emit(self, record):
        from girder_jobs.models.job import Job

        self._job = Job().updateJob(self._job, log=self.format(record).rstrip() + '\n')


def convert_image_job(job):
    import tempfile

    from girder_jobs.constants import JobStatus
    from girder_jobs.models.job import Job

    from girder.constants import AccessType
    from girder.models.file import File
    from girder.models.folder import Folder
    from girder.models.item import Item
    from girder.models.upload import Upload
    from girder.models.user import User

    kwargs = job['kwargs']
    toFolder = kwargs.pop('toFolder', True)
    item = Item().load(kwargs.pop('itemId'), force=True)
    fileObj = File().load(kwargs.pop('fileId'), force=True)
    userId = kwargs.pop('userId', None)
    user = User().load(userId, force=True) if userId else None
    if toFolder:
        parentType = 'folder'
        parent = Folder().load(kwargs.pop('folderId', item['folderId']),
                               user=user, level=AccessType.WRITE)
    else:
        parentType = 'item'
        parent = item
    name = kwargs.pop('name', None)

    job = Job().updateJob(
        job, log='Started large image conversion\n',
        status=JobStatus.RUNNING)
    logger = logging.getLogger('large-image-converter')
    handler = JobLogger(job=job)
    logger.addHandler(handler)
    # We could increase the default logging level here
    # logger.setLevel(logging.DEBUG)
    try:
        inputPath = None
        if not fileObj.get('imported'):
            try:
                inputPath = File().getGirderMountFilePath(
                    fileObj,
                    **({'preferFlat': True} if 'preferFlat' in inspect.signature(
                        File.getGirderMountFilePath).parameters else {}))
            except Exception:
                pass
        inputPath = inputPath or File().getLocalFilePath(fileObj)
        with tempfile.TemporaryDirectory() as tempdir:
            dest = create_tiff(
                inputFile=inputPath,
                inputName=fileObj['name'],
                outputDir=tempdir,
                **kwargs,
            )
            job = Job().updateJob(job, log='Storing result\n')
            with open(dest, 'rb') as fobj:
                fileObj = Upload().uploadFromFile(
                    fobj,
                    size=os.path.getsize(dest),
                    name=name or os.path.basename(dest),
                    parentType=parentType,
                    parent=parent,
                    user=user,
                )
                job = Job().load(job['_id'], force=True)
                job.setdefault('results', {})
                job['results'].setdefault('file', [])
                job['results']['file'].append(fileObj['_id'])
                job = Job().save(job)
    except Exception as exc:
        status = JobStatus.ERROR
        logger.exception('Failed in large image conversion')
        job = Job().updateJob(
            job, log='Failed in large image conversion (%s)\n' % exc, status=status)
    else:
        status = JobStatus.SUCCESS
        job = Job().updateJob(
            job, log='Finished large image conversion\n', status=status)
    finally:
        logger.removeHandler(handler)


def cache_tile_frames_job(job):
    from girder_jobs.constants import JobStatus
    from girder_jobs.models.job import Job
    from girder_large_image.models.image_item import ImageItem

    kwargs = job['kwargs']
    item = ImageItem().load(kwargs.pop('itemId'), force=True)
    job = Job().updateJob(
        job, log='Started caching tile frames\n',
        status=JobStatus.RUNNING)
    try:
        for entry in kwargs.get('tileFramesList'):
            job = Job().load(job['_id'], force=True)
            if job['status'] == JobStatus.CANCELED:
                return
            job = Job().updateJob(job, log='Caching %r\n' % entry)
            ImageItem().tileFrames(item, checkAndCreate=True, **entry)
        job = Job().updateJob(job, log='Finished caching tile frames\n', status=JobStatus.SUCCESS)
    except Exception as exc:
        logger.exception('Failed caching tile frames')
        job = Job().updateJob(
            job, log='Failed caching tile frames (%s)\n' % exc, status=JobStatus.ERROR)


def cache_histograms_job(job):
    from girder_jobs.constants import JobStatus
    from girder_jobs.models.job import Job
    from girder_large_image.models.image_item import ImageItem

    kwargs = job['kwargs']
    item = ImageItem().load(kwargs.pop('itemId'), force=True)
    job = Job().updateJob(
        job, log='Started caching histograms\n',
        status=JobStatus.RUNNING)
    try:
        for entry in kwargs.get('histogramList'):
            job = Job().load(job['_id'], force=True)
            if job['status'] == JobStatus.CANCELED:
                return
            job = Job().updateJob(job, log='Caching %r\n' % entry)
            ImageItem().histogram(item, checkAndCreate=True, **entry)
        job = Job().updateJob(job, log='Finished caching histograms\n', status=JobStatus.SUCCESS)
    except Exception as exc:
        logger.exception('Failed caching histograms')
        job = Job().updateJob(
            job, log='Failed caching histograms (%s)\n' % exc, status=JobStatus.ERROR)
