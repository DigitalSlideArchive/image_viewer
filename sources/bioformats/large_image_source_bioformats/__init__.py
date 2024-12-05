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

# This tile sources uses javabridge to communicate between python and java.  It
# requires some version of java's jvm to be available (see
# https://jdk.java.net/archive/).  It uses the python-bioformats wheel to get
# the bioformats JAR file.  A later version may be desirable (see
# https://www.openmicroscopy.org/bio-formats/downloads/).  See
# https://downloads.openmicroscopy.org/bio-formats/5.1.5/api/loci/formats/
#   IFormatReader.html for interface details.

import atexit
import builtins
import logging
import math
import os
import pathlib
import re
import threading
import types
import weakref
import zipfile
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _importlib_version

import numpy as np

import large_image.tilesource.base
from large_image import config
from large_image.cache_util import LruCacheMetaclass, methodcache
from large_image.constants import TILE_FORMAT_NUMPY, SourcePriority
from large_image.exceptions import TileSourceError, TileSourceFileNotFoundError
from large_image.tilesource import FileTileSource, nearPowerOfTwo

try:
    __version__ = _importlib_version(__name__)
except PackageNotFoundError:
    # package is not installed
    pass

bioformats = None
# import javabridge
javabridge = None

_javabridgeStarted = None
_javabridgeStartLock = threading.Lock()
_bioformatsVersion = None
_openImages = []


# Default to ignoring files with no extension and some specific extensions.
config.ConfigValues['source_bioformats_ignored_names'] = r'(^[^.]*|\.(jpg|jpeg|jpe|png|tif|tiff|ndpi|nd2|ome|nc|json|isyntax|mrxs|zip|zarr(\.db|\.zip)))$'  # noqa


def _monitor_thread():
    main_thread = threading.main_thread()
    main_thread.join()
    if len(_openImages):
        try:
            javabridge.attach()
            while len(_openImages):
                source = _openImages.pop()
                source = source()
                try:
                    source._bioimage.close()
                except Exception:
                    pass
                try:
                    source._bioimage = None
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            if javabridge.get_env():
                javabridge.detach()
    _stopJavabridge()


def _reduceLogging():
    # As of python-bioformats 4.0.0, org.apache.log4j isn't in the bundled
    # jar file, so setting log levels just produces needless warnings.
    # bioformats.log4j.basic_config()
    # javabridge.JClassWrapper('loci.common.Log4jTools').setRootLevel(
    #     logging.getLevelName(logger.level))
    #
    # This is taken from
    # https://github.com/pskeshu/microscoper/blob/master/microscoper/io.py
    try:
        rootLoggerName = javabridge.get_static_field(
            'org/slf4j/Logger', 'ROOT_LOGGER_NAME', 'Ljava/lang/String;')
        rootLogger = javabridge.static_call(
            'org/slf4j/LoggerFactory', 'getLogger',
            '(Ljava/lang/String;)Lorg/slf4j/Logger;', rootLoggerName)
        logLevel = javabridge.get_static_field(
            'ch/qos/logback/classic/Level', 'OFF', 'Lch/qos/logback/classic/Level;')
        javabridge.call(rootLogger, 'setLevel', '(Lch/qos/logback/classic/Level;)V', logLevel)
    except Exception:
        pass
    bioformats.formatreader.logger.setLevel(logging.ERROR)


def _startJavabridge(logger):
    global _javabridgeStarted, _bioformatsVersion

    with _javabridgeStartLock:
        if _javabridgeStarted is None:
            # Only import these when first asked.  They are slow to import.
            global bioformats
            global javabridge
            if bioformats is None:
                import bioformats
                try:
                    _bioformatsVersion = zipfile.ZipFile(
                        pathlib.Path(bioformats.__file__).parent /
                        'jars/bioformats_package.jar',
                    ).open('META-INF/MANIFEST.MF').read(8192).split(
                        b'Implementation-Version: ')[1].split()[0].decode()
                    logger.info('Bioformats.jar version: %s', _bioformatsVersion)
                except Exception:
                    pass
            if javabridge is None:
                import javabridge

            # We need something to wake up at exit and shut things down
            monitor = threading.Thread(target=_monitor_thread)
            monitor.daemon = True
            monitor.start()
            try:
                javabridge.start_vm(class_path=bioformats.JARS, run_headless=True)
                _reduceLogging()
                atexit.register(_stopJavabridge)
                logger.info('Started JVM for Bioformats tile source.')
                _javabridgeStarted = True
            except RuntimeError:
                logger.exception('Cannot start JVM for Bioformats tile source.')
                _javabridgeStarted = False
    return _javabridgeStarted


def _stopJavabridge(*args, **kwargs):
    global _javabridgeStarted

    if javabridge is not None:
        javabridge.kill_vm()
    _javabridgeStarted = None


def _getBioformatsVersion():
    """
    Get the version of the jar file.

    :returns: the version string if it is in the expected format, None
        otherwise.
    """
    if _bioformatsVersion is None:
        from large_image import config

        logger = config.getLogger()
        _startJavabridge(logger)
    return _bioformatsVersion


class BioformatsFileTileSource(FileTileSource, metaclass=LruCacheMetaclass):
    """
    Provides tile access to via Bioformats.
    """

    cacheName = 'tilesource'
    name = 'bioformats'
    extensions = {
        None: SourcePriority.FALLBACK,
        'czi': SourcePriority.PREFERRED,
        'ets': SourcePriority.LOW,  # part of vsi
        'lif': SourcePriority.MEDIUM,
        'vsi': SourcePriority.PREFERRED,
    }
    mimeTypes = {
        None: SourcePriority.FALLBACK,
        'image/czi': SourcePriority.PREFERRED,
        'image/vsi': SourcePriority.PREFERRED,
    }

    # If frames are smaller than this they are served as single tiles, which
    # can be more efficient than handling multiple tiles.
    _singleTileThreshold = 2048
    _tileSize = 512
    _associatedImageMaxSize = 8192
    _maxSkippedLevels = 3

    def __init__(self, path, **kwargs):  # noqa
        """
        Initialize the tile class.  See the base class for other available
        parameters.

        :param path: the associated file path.
        """
        super().__init__(path, **kwargs)

        largeImagePath = str(self._getLargeImagePath())
        config._ignoreSourceNames('bioformats', largeImagePath)

        header = b''
        if os.path.isfile(largeImagePath):
            try:
                header = builtins.open(largeImagePath, 'rb').read(5)
            except Exception:
                msg = 'File cannot be opened via Bioformats'
                raise TileSourceError(msg)
        # Never allow pdfs; they crash the JVM
        if header[:5] == b'%PDF-':
            msg = 'File cannot be opened via Bioformats'
            raise TileSourceError(msg)
        if not _startJavabridge(self.logger):
            msg = 'File cannot be opened by bioformats reader because javabridge failed to start'
            raise TileSourceError(msg)
        self.addKnownExtensions()

        self._tileLock = threading.RLock()

        try:
            javabridge.attach()
            try:
                self._bioimage = bioformats.ImageReader(largeImagePath, perform_init=False)
                try:
                    # So this as a separate step so, if it fails, we can ask to
                    # open something that does not exist and bioformats will
                    # release some file handles.
                    self._bioimage.init_reader()
                except Exception as exc:
                    try:
                        # Ask to open a file that should never exist
                        self._bioimage.rdr.setId('__\0__')
                    except Exception:
                        pass
                    self._bioimage.close()
                    self._bioimage = None
                    raise exc
            except (AttributeError, OSError) as exc:
                if not os.path.isfile(largeImagePath):
                    raise TileSourceFileNotFoundError(largeImagePath) from None
                self.logger.debug('File cannot be opened via Bioformats. (%r)', exc)
                raise TileSourceError('File cannot be opened via Bioformats (%r)' % exc)
            _openImages.append(weakref.ref(self))

            rdr = self._bioimage.rdr
            # Bind additional functions not done by bioformats module.
            # Functions are listed at https://downloads.openmicroscopy.org
            # /bio-formats/5.1.5/api/loci/formats/IFormatReader.html
            for (name, params, desc) in [
                ('getBitsPerPixel', '()I', 'Get the number of bits per pixel'),
                ('getDomains', '()[Ljava/lang/String;', 'Get a list of domains'),
                ('getEffectiveSizeC', '()I', 'effectiveC * Z * T = imageCount'),
                ('getOptimalTileHeight', '()I', 'the optimal sub-image height '
                 'for use with openBytes'),
                ('getOptimalTileWidth', '()I', 'the optimal sub-image width '
                 'for use with openBytes'),
                ('getResolution', '()I', 'The current resolution level'),
                ('getResolutionCount', '()I', 'The number of resolutions for '
                 'the current series'),
                ('getZCTCoords', '(I)[I', 'Gets the Z, C and T coordinates '
                 '(real sizes) corresponding to the given rasterized index value.'),
                ('hasFlattenedResolutions', '()Z', 'True if resolutions have been flattened'),
                ('isMetadataComplete', '()Z', 'True if metadata is completely parsed'),
                ('isNormalized', '()Z', 'Is float data normalized'),
                ('setFlattenedResolutions', '(Z)V', 'Set if resolution should be flattened'),
                ('setResolution', '(I)V', 'Set the resolution level'),
            ]:
                setattr(rdr, name, types.MethodType(
                    javabridge.jutil.make_method(name, params, desc), rdr))
            # rdr.setFlattenedResolutions(False)
            self._metadataForCurrentSeries(rdr)
            self._checkSeries(rdr)
            bmd = bioformats.metadatatools.MetadataRetrieve(self._bioimage.metadata)
            try:
                self._metadata['channelNames'] = [
                    bmd.getChannelName(0, c) or bmd.getChannelID(0, c)
                    for c in range(self._metadata['sizeColorPlanes'])]
            except Exception:
                self._metadata['channelNames'] = []
            for key in ['sizeXY', 'sizeC', 'sizeZ', 'sizeT']:
                if not isinstance(self._metadata[key], int) or self._metadata[key] < 1:
                    self._metadata[key] = 1
            self.sizeX = self._metadata['sizeX']
            self.sizeY = self._metadata['sizeY']
            if self.sizeX <= 0 or self.sizeY <= 0:
                msg = 'File cannot be opened with biofromats.'
                raise TileSourceError(msg)
            self._computeTiles()
            self._computeLevels()
            self._computeMagnification()
        except javabridge.JavaException as exc:
            es = javabridge.to_string(exc.throwable)
            self.logger.debug('File cannot be opened via Bioformats. (%s)', es)
            raise TileSourceError('File cannot be opened via Bioformats. (%s)' % es)
        except (AttributeError, UnicodeDecodeError):
            self.logger.exception('The bioformats reader threw an unhandled exception.')
            msg = 'The bioformats reader threw an unhandled exception.'
            raise TileSourceError(msg)
        finally:
            if javabridge.get_env():
                javabridge.detach()

        if self.levels < 1:
            msg = 'Bioformats image must have at least one level.'
            raise TileSourceError(msg)

        if self.sizeX <= 0 or self.sizeY <= 0:
            msg = 'Bioformats tile size is invalid.'
            raise TileSourceError(msg)
        try:
            self.getTile(0, 0, self.levels - 1)
        except Exception as exc:
            raise TileSourceError('Bioformats cannot read a tile: %r' % exc)
        self._populatedLevels = len([
            v for v in self._metadata['frameSeries'][0]['series'] if v is not None])

    def __del__(self):
        if getattr(self, '_bioimage', None) is not None:
            try:
                javabridge.attach()
                self._bioimage.close()
                del self._bioimage
                _openImages.remove(weakref.ref(self))
            except Exception:
                pass
            finally:
                if javabridge.get_env():
                    javabridge.detach()

    def _metadataForCurrentSeries(self, rdr):
        self._metadata = getattr(self, '_metadata', {})
        self._metadata.update({
            'dimensionOrder': rdr.getDimensionOrder(),
            'metadata': javabridge.jdictionary_to_string_dictionary(
                rdr.getMetadata()),
            'seriesMetadata': javabridge.jdictionary_to_string_dictionary(
                rdr.getSeriesMetadata()),
            'seriesCount': rdr.getSeriesCount(),
            'imageCount': rdr.getImageCount(),
            'rgbChannelCount': rdr.getRGBChannelCount(),
            'sizeColorPlanes': rdr.getSizeC(),
            'sizeT': rdr.getSizeT(),
            'sizeZ': rdr.getSizeZ(),
            'sizeX': rdr.getSizeX(),
            'sizeY': rdr.getSizeY(),
            'pixelType': rdr.getPixelType(),
            'isLittleEndian': rdr.isLittleEndian(),
            'isRGB': rdr.isRGB(),
            'isInterleaved': rdr.isInterleaved(),
            'isIndexed': rdr.isIndexed(),
            'bitsPerPixel': rdr.getBitsPerPixel(),
            'sizeC': rdr.getEffectiveSizeC(),
            'normalized': rdr.isNormalized(),
            'metadataComplete': rdr.isMetadataComplete(),
            # 'domains': rdr.getDomains(),
            'optimalTileWidth': rdr.getOptimalTileWidth(),
            'optimalTileHeight': rdr.getOptimalTileHeight(),
            'resolutionCount': rdr.getResolutionCount(),
        })

    def _getSeriesStarts(self, rdr):  # noqa
        self._metadata['frameSeries'] = [{
            'series': [0],
            'sizeX': self._metadata['sizeX'],
            'sizeY': self._metadata['sizeY'],
        }]
        if self._metadata['seriesCount'] <= 1:
            return 1
        seriesMetadata = {}
        for idx in range(self._metadata['seriesCount']):
            rdr.setSeries(idx)
            seriesMetadata.update(
                javabridge.jdictionary_to_string_dictionary(rdr.getSeriesMetadata()))
        frameList = []
        nextSeriesNum = 0
        try:
            for key, value in seriesMetadata.items():
                frameNum = int(value)
                seriesNum = int(key.split('Series ')[1].split('|')[0]) - 1
                if seriesNum >= 0 and seriesNum < self._metadata['seriesCount']:
                    while len(frameList) <= frameNum:
                        frameList.append([])
                    if seriesNum not in frameList[frameNum]:
                        frameList[frameNum].append(seriesNum)
                        frameList[frameNum].sort()
                    nextSeriesNum = max(nextSeriesNum, seriesNum + 1)
        except Exception as exc:
            self.logger.debug('Failed to parse series information: %s', exc)
            rdr.setSeries(0)
            if any(key for key in seriesMetadata if key.startswith('Series ')):
                return 1
        if not len(seriesMetadata) or not any(
                key for key in seriesMetadata if key.startswith('Series ')):
            frameList = [[0]]
            nextSeriesNum = 1
            rdr.setSeries(0)
            lastX, lastY = rdr.getSizeX(), rdr.getSizeY()
            for idx in range(1, self._metadata['seriesCount']):
                rdr.setSeries(idx)
                if (rdr.getSizeX() == self._metadata['sizeX'] and
                        rdr.getSizeY() == self._metadata['sizeY'] and
                        rdr.getImageCount() == self._metadata['imageCount']):
                    frameList.append([idx])
                    if nextSeriesNum == idx:
                        nextSeriesNum = idx + 1
                    lastX, lastY = self._metadata['sizeX'], self._metadata['sizeY']
                if (rdr.getSizeX() * rdr.getSizeY() * rdr.getImageCount() >
                        self._metadata['sizeX'] * self._metadata['sizeY'] *
                        self._metadata['imageCount']):
                    frameList = [[idx]]
                    nextSeriesNum = idx + 1
                    self._metadata['sizeX'] = self.sizeX = lastX = rdr.getSizeX()
                    self._metadata['sizeY'] = self.sizeY = lastY = rdr.getSizeY()
                    self._metadata['imageCount'] = rdr.getImageCount()
                if (lastX and lastY and
                        nearPowerOfTwo(rdr.getSizeX(), lastX) and rdr.getSizeX() < lastX and
                        nearPowerOfTwo(rdr.getSizeY(), lastY) and rdr.getSizeY() < lastY):
                    steps = int(round(math.log(
                        lastX * lastY / (rdr.getSizeX() * rdr.getSizeY())) / math.log(2) / 2))
                    frameList[-1] += [None] * (steps - 1)
                    frameList[-1].append(idx)
                    lastX, lastY = rdr.getSizeX(), rdr.getSizeY()
                    if nextSeriesNum == idx:
                        nextSeriesNum = idx + 1
        frameList = [fl for fl in frameList if len(fl)]
        self._metadata['frameSeries'] = [{
            'series': fl,
        } for fl in frameList]
        rdr.setSeries(0)
        return nextSeriesNum

    def _checkSeries(self, rdr):
        firstPossibleAssoc = self._getSeriesStarts(rdr)
        self._metadata['seriesAssociatedImages'] = {}
        for seriesNum in range(firstPossibleAssoc, self._metadata['seriesCount']):
            if any((seriesNum in series['series']) for series in self._metadata['frameSeries']):
                continue
            rdr.setSeries(seriesNum)
            info = {
                'sizeX': rdr.getSizeX(),
                'sizeY': rdr.getSizeY(),
            }
            if (info['sizeX'] < self._associatedImageMaxSize and
                    info['sizeY'] < self._associatedImageMaxSize):
                # TODO: Figure out better names for associated images.  Can
                # we tell if any of them are the macro or label image?
                info['seriesNum'] = seriesNum
                self._metadata['seriesAssociatedImages'][
                    'image%d' % seriesNum] = info
        validate = None
        for frame in self._metadata['frameSeries']:
            for level in range(len(frame['series'])):
                if level and frame['series'][level] is None:
                    continue
                rdr.setSeries(frame['series'][level])
                self._metadataForCurrentSeries(rdr)
                info = {
                    'sizeX': rdr.getSizeX(),
                    'sizeY': rdr.getSizeY(),
                }
                if not level:
                    frame.update(info)
                    self._metadata['sizeX'] = max(self._metadata['sizeX'], frame['sizeX'])
                    self._metadata['sizeY'] = max(self._metadata['sizeY'], frame['sizeY'])
                elif validate is not False:
                    if (not nearPowerOfTwo(frame['sizeX'], info['sizeX']) or
                            not nearPowerOfTwo(frame['sizeY'], info['sizeY'])):
                        frame['series'] = frame['series'][:level]
                        validate = True
                        break
            rdr.setSeries(frame['series'][0])
            self._metadataForCurrentSeries(rdr)
            if validate is None:
                validate = False
        rdr.setSeries(0)
        self._metadata['sizeXY'] = len(self._metadata['frameSeries'])

    def _computeTiles(self):
        if (self._metadata['resolutionCount'] <= 1 and
                self.sizeX <= self._singleTileThreshold and
                self.sizeY <= self._singleTileThreshold):
            self.tileWidth = self.sizeX
            self.tileHeight = self.sizeY
        elif (128 <= self._metadata['optimalTileWidth'] <= self._singleTileThreshold and
              128 <= self._metadata['optimalTileHeight'] <= self._singleTileThreshold):
            self.tileWidth = self._metadata['optimalTileWidth']
            self.tileHeight = self._metadata['optimalTileHeight']
        else:
            self.tileWidth = self.tileHeight = self._tileSize

    def _computeLevels(self):
        self.levels = int(math.ceil(max(
            math.log(float(self.sizeX) / self.tileWidth),
            math.log(float(self.sizeY) / self.tileHeight)) / math.log(2))) + 1

    def _computeMagnification(self):
        self._magnification = {}
        metadata = self._metadata['metadata']
        valuekeys = {
            'x': [('Scaling|Distance|Value #1', 1e3)],
            'y': [('Scaling|Distance|Value #2', 1e3)],
        }
        tuplekeys = [
            ('Physical pixel size', 1e-3),
        ]
        magkeys = [
            'Information|Instrument|Objective|NominalMagnification #1',
            'Magnification #1',
        ]
        for axis in {'x', 'y'}:
            for key, units in valuekeys[axis]:
                if metadata.get(key):
                    self._magnification['mm_' + axis] = float(metadata[key]) * units
        if 'mm_x' not in self._magnification and 'mm_y' not in self._magnification:
            for key, units in tuplekeys:
                if metadata.get(key):
                    found = re.match(r'^\D*(\d+(|\.\d+))\D+(\d+(|\.\d+))\D*$', metadata[key])
                    if found:
                        try:
                            self._magnification['mm_x'], self._magnification['mm_y'] = (
                                float(found.groups()[0]) * units, float(found.groups()[2]) * units)
                        except Exception:
                            pass
        for key in magkeys:
            if metadata.get(key):
                self._magnification['magnification'] = float(metadata[key])
                break

    def _nonemptyLevelsList(self, frame=0):
        """
        Return a list of one value per level where the value is None if the
        level does not exist in the file and any other value if it does.

        :param frame: the frame number.
        :returns: a list of levels length.
        """
        nonempty = [True if v is not None else None
                    for v in self._metadata['frameSeries'][0]['series']][:self.levels]
        nonempty += [None] * (self.levels - len(nonempty))
        return nonempty[::-1]

    def getNativeMagnification(self):
        """
        Get the magnification at a particular level.

        :return: magnification, width of a pixel in mm, height of a pixel in mm.
        """
        mm_x = self._magnification.get('mm_x')
        mm_y = self._magnification.get('mm_y', mm_x)
        # Estimate the magnification if we don't have a direct value
        mag = self._magnification.get('magnification') or 0.01 / mm_x if mm_x else None
        return {
            'magnification': mag,
            'mm_x': mm_x,
            'mm_y': mm_y,
        }

    def getMetadata(self):
        """
        Return a dictionary of metadata containing levels, sizeX, sizeY,
        tileWidth, tileHeight, magnification, mm_x, mm_y, and frames.

        :returns: metadata dictionary.

        """
        result = super().getMetadata()
        # sizeC, sizeZ, sizeT, sizeXY
        frames = []
        for xy in range(self._metadata['sizeXY']):
            for t in range(self._metadata['sizeT']):
                for z in range(self._metadata['sizeZ']):
                    for c in range(self._metadata['sizeC']):
                        frames.append({
                            'IndexC': c,
                            'IndexZ': z,
                            'IndexT': t,
                            'IndexXY': xy,
                        })
        if len(self._metadata['frameSeries']) == len(frames):
            for idx, frame in enumerate(frames):
                frame['sizeX'] = self._metadata['frameSeries'][idx]['sizeX']
                frame['sizeY'] = self._metadata['frameSeries'][idx]['sizeY']
                frame['levels'] = len(self._metadata['frameSeries'][idx]['series'])
        if len(frames) > 1:
            result['frames'] = frames
            self._addMetadataFrameInformation(result, self._metadata['channelNames'])
        return result

    def getInternalMetadata(self, **kwargs):
        """
        Return additional known metadata about the tile source.  Data returned
        from this method is not guaranteed to be in any particular format or
        have specific values.

        :returns: a dictionary of data or None.
        """
        return self._metadata

    @methodcache()
    def getTile(self, x, y, z, pilImageAllowed=False, numpyAllowed=False, **kwargs):
        self._xyzInRange(x, y, z)
        ft = fc = fz = 0
        fseries = self._metadata['frameSeries'][0]
        if kwargs.get('frame') is not None:
            frame = self._getFrame(**kwargs)
            fc = frame % self._metadata['sizeC']
            fz = (frame // self._metadata['sizeC']) % self._metadata['sizeZ']
            ft = (frame // self._metadata['sizeC'] //
                  self._metadata['sizeZ']) % self._metadata['sizeT']
            fxy = (frame // self._metadata['sizeC'] //
                   self._metadata['sizeZ'] // self._metadata['sizeT'])
            if frame < 0 or fxy > self._metadata['sizeXY']:
                msg = 'Frame does not exist'
                raise TileSourceError(msg)
            fseries = self._metadata['frameSeries'][fxy]
        seriesLevel = self.levels - 1 - z
        scale = 1
        while seriesLevel >= len(fseries['series']) or fseries['series'][seriesLevel] is None:
            seriesLevel -= 1
            scale *= 2
        offsetx = x * self.tileWidth * scale
        offsety = y * self.tileHeight * scale
        width = min(self.tileWidth * scale, self.sizeX // 2 ** seriesLevel - offsetx)
        height = min(self.tileHeight * scale, self.sizeY // 2 ** seriesLevel - offsety)
        sizeXAtScale = fseries['sizeX'] // (2 ** seriesLevel)
        sizeYAtScale = fseries['sizeY'] // (2 ** seriesLevel)
        finalWidth = width // scale
        finalHeight = height // scale
        width = min(width, sizeXAtScale - offsetx)
        height = min(height, sizeYAtScale - offsety)

        if scale >= 2 ** self._maxSkippedLevels:
            tile, _format = self._getTileFromEmptyLevel(x, y, z, **kwargs)
            tile = large_image.tilesource.base._imageToNumpy(tile)[0]
            format = TILE_FORMAT_NUMPY
        else:
            with self._tileLock:
                try:
                    javabridge.attach()
                    if width > 0 and height > 0:
                        tile = self._bioimage.read(
                            c=fc, z=fz, t=ft, series=fseries['series'][seriesLevel],
                            rescale=False,  # return internal data types
                            XYWH=(offsetx, offsety, width, height))
                    else:
                        # We need the same dtype, so read 1x1 at 0x0
                        tile = self._bioimage.read(
                            c=fc, z=fz, t=ft, series=fseries['series'][seriesLevel],
                            rescale=False,  # return internal data types
                            XYWH=(0, 0, 1, 1))
                        tile = np.zeros(tuple([0, 0] + list(tile.shape[2:])), dtype=tile.dtype)
                    format = TILE_FORMAT_NUMPY
                except javabridge.JavaException as exc:
                    es = javabridge.to_string(exc.throwable)
                    raise TileSourceError('Failed to get Bioformat region (%s, %r).' % (es, (
                        fc, fz, ft, fseries, self.sizeX, self.sizeY, offsetx,
                        offsety, width, height)))
                finally:
                    if javabridge.get_env():
                        javabridge.detach()
            if scale > 1:
                tile = tile[::scale, ::scale]
        if tile.shape[:2] != (finalHeight, finalWidth):
            fillValue = 0
            if tile.dtype == np.uint16:
                fillValue = 65535
            elif tile.dtype == np.int16:
                fillValue = 32767
            elif tile.dtype == np.uint8:
                fillValue = 255
            elif tile.dtype.kind == 'f':
                fillValue = 1
            retile = np.full(
                tuple([finalHeight, finalWidth] + list(tile.shape[2:])),
                fillValue,
                dtype=tile.dtype)
            retile[0:min(tile.shape[0], finalHeight), 0:min(tile.shape[1], finalWidth)] = tile[
                0:min(tile.shape[0], finalHeight), 0:min(tile.shape[1], finalWidth)]
            tile = retile
        return self._outputTile(tile, format, x, y, z, pilImageAllowed, numpyAllowed, **kwargs)

    def getAssociatedImagesList(self):
        """
        Return a list of associated images.

        :return: the list of image keys.
        """
        return sorted(self._metadata['seriesAssociatedImages'].keys())

    def _getAssociatedImage(self, imageKey):
        """
        Get an associated image in PIL format.

        :param imageKey: the key of the associated image.
        :return: the image in PIL format or None.
        """
        info = self._metadata['seriesAssociatedImages'].get(imageKey)
        if info is None:
            return
        series = info['seriesNum']
        with self._tileLock:
            try:
                javabridge.attach()
                image = self._bioimage.read(
                    series=series,
                    rescale=False,  # return internal data types
                    XYWH=(0, 0, info['sizeX'], info['sizeY']))
            except javabridge.JavaException as exc:
                es = javabridge.to_string(exc.throwable)
                raise TileSourceError('Failed to get Bioformat series (%s, %r).' % (es, (
                    series, info['sizeX'], info['sizeY'])))
            finally:
                if javabridge.get_env():
                    javabridge.detach()
        return large_image.tilesource.base._imageToPIL(image)

    @classmethod
    def addKnownExtensions(cls):
        # This starts javabridge/bioformats if needed
        _getBioformatsVersion()
        if not hasattr(cls, '_addedExtensions'):
            cls._addedExtensions = True
            cls.extensions = cls.extensions.copy()
            for dotext in bioformats.READABLE_FORMATS:
                ext = dotext.strip('.')
                if ext not in cls.extensions:
                    cls.extensions[ext] = SourcePriority.IMPLICIT


def open(*args, **kwargs):
    """
    Create an instance of the module class.
    """
    return BioformatsFileTileSource(*args, **kwargs)


def canRead(*args, **kwargs):
    """
    Check if an input can be read by the module class.
    """
    return BioformatsFileTileSource.canRead(*args, **kwargs)
