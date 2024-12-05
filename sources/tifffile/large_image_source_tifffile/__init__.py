import json
import logging
import math
import os
import threading
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _importlib_version

import numpy as np

import large_image
from large_image.cache_util import LruCacheMetaclass, methodcache
from large_image.constants import TILE_FORMAT_NUMPY, SourcePriority
from large_image.exceptions import TileSourceError, TileSourceFileNotFoundError
from large_image.tilesource import FileTileSource

tifffile = None
zarr = None

try:
    __version__ = _importlib_version(__name__)
except PackageNotFoundError:
    # package is not installed
    pass


class checkForMissingDataHandler(logging.Handler):
    def emit(self, record):
        msg = record.getMessage()
        if 'Missing data are zeroed' in msg or 'OME series expected ' in msg:
            raise TileSourceError(record.getMessage())


def _lazyImport():
    """
    Import the tifffile module.  This is done when needed rather than in the
    module initialization because it is slow.
    """
    global tifffile
    global zarr

    if tifffile is None:
        try:
            import tifffile
        except ImportError:
            msg = 'tifffile module not found.'
            raise TileSourceError(msg)
        if not hasattr(tifffile.TiffTag, 'dtype_name') or not hasattr(tifffile.TiffPage, 'aszarr'):
            tifffile = None
            msg = 'tifffile module is too old.'
            raise TileSourceError(msg)
        # The missing data handler consumes most warnings, but throws if a
        # warning about missing data occurs
        # The tifffile.tifffile logger is in older versions of tifffile
        logging.getLogger('tifffile.tifffile').setLevel(logging.WARNING)
        logging.getLogger('tifffile.tifffile').addHandler(checkForMissingDataHandler())
        logging.getLogger('tifffile').setLevel(logging.WARNING)
        logging.getLogger('tifffile').addHandler(checkForMissingDataHandler())
    if zarr is None:
        import zarr


def et_findall(tag, text):
    """
    Find all the child tags in an element tree that end with a specific string.

    :param tag: the tag to search.
    :param text: the text to end with.
    :returns: a list of tags.
    """
    return [entry for entry in tag if entry.tag.endswith(text)]


class TifffileFileTileSource(FileTileSource, metaclass=LruCacheMetaclass):
    """
    Provides tile access to files that the tifffile library can read.
    """

    cacheName = 'tilesource'
    name = 'tifffile'
    extensions = {
        None: SourcePriority.LOW,
        'scn': SourcePriority.PREFERRED,
        'tif': SourcePriority.LOW,
        'tiff': SourcePriority.LOW,
    }
    mimeTypes = {
        None: SourcePriority.FALLBACK,
        'image/scn': SourcePriority.PREFERRED,
        'image/tiff': SourcePriority.LOW,
        'image/x-tiff': SourcePriority.LOW,
    }

    # Fallback for non-tiled or oddly tiled sources
    _tileSize = 512
    _minImageSize = 128
    _minTileSize = 128
    _singleTileSize = 1024
    _maxTileSize = 2048
    _minAssociatedImageSize = 64
    _maxAssociatedImageSize = 8192

    def __init__(self, path, **kwargs):  # noqa
        """
        Initialize the tile class.  See the base class for other available
        parameters.

        :param path: a filesystem path for the tile source.
        """
        super().__init__(path, **kwargs)

        self._largeImagePath = str(self._getLargeImagePath())

        _lazyImport()
        self.addKnownExtensions()
        try:
            self._tf = tifffile.TiffFile(self._largeImagePath)
        except Exception:
            if not os.path.isfile(self._largeImagePath):
                raise TileSourceFileNotFoundError(self._largeImagePath) from None
            msg = 'File cannot be opened via tifffile.'
            raise TileSourceError(msg)
        maxseries, maxsamples = self._biggestSeries()
        self.tileWidth = self.tileHeight = self._tileSize
        s = self._tf.series[maxseries]
        self._baseSeries = s
        if len(s.levels) == 1:
            self.tileWidth = self.tileHeight = self._singleTileSize
        page = s.pages[0]
        if ('TileWidth' in page.tags and
                self._minTileSize <= page.tags['TileWidth'].value <= self._maxTileSize):
            self.tileWidth = page.tags['TileWidth'].value
        if ('TileLength' in page.tags and
                self._minTileSize <= page.tags['TileLength'].value <= self._maxTileSize):
            self.tileHeight = page.tags['TileLength'].value
        if 'InterColorProfile' in page.tags:
            self._iccprofiles = [page.tags['InterColorProfile'].value]
        self.sizeX = s.shape[s.axes.index('X')]
        self.sizeY = s.shape[s.axes.index('Y')]
        self._mm_x = self._mm_y = None
        try:
            unit = {2: 25.4, 3: 10}[page.tags['ResolutionUnit'].value.real]

            if (page.tags['XResolution'].value[0] and page.tags['XResolution'].value[1] and (
                    page.tags['XResolution'].value[0] / page.tags['XResolution'].value[1]) >= 100):
                self._mm_x = (unit * page.tags['XResolution'].value[1] /
                              page.tags['XResolution'].value[0])
            if (page.tags['YResolution'].value[0] and page.tags['YResolution'].value[1] and (
                    page.tags['YResolution'].value[0] / page.tags['YResolution'].value[1]) >= 100):
                self._mm_y = (unit * page.tags['YResolution'].value[1] /
                              page.tags['YResolution'].value[0])
        except Exception:
            pass
        self._findMatchingSeries()
        self.levels = int(max(1, math.ceil(math.log(
            float(max(self.sizeX, self.sizeY)) / self.tileWidth) / math.log(2)) + 1))
        self._findAssociatedImages()
        for key in dir(self._tf):
            if (key.startswith('is_') and hasattr(self, '_handle_' + key[3:]) and
                    getattr(self._tf, key)):
                getattr(self, '_handle_' + key[3:])()
        self._populatedLevels = len(self._baseSeries.levels)
        # Some files have their axes listed in the wrong order.  Try to access
        # the lastmost pixel; if that fails, probably the axes and shape don't
        # match the file (or the file is corrupted).
        try:
            self.getPixel(region={'left': self.sizeX - 1, 'top': self.sizeY - 1},
                          frame=self.frames - 1)
        except Exception:
            msg = 'File cannot be opened via tifffile: axes and shape do not match access pattern.'
            raise TileSourceError(msg)

    def _biggestSeries(self):
        """
        Find the series with the most pixels.  Use all series that have the
        same dimensionality and resolution.  They can differ in X, Y size.

        :returns: index of the largest series, number of pixels in a frame in
            that series.
        """
        maxseries = None
        maxsamples = 0
        ex = 'no maximum series'
        try:
            for idx, s in enumerate(self._tf.series):
                samples = math.prod(s.shape)
                if samples > maxsamples and 'X' in s.axes and 'Y' in s.axes:
                    maxseries = idx
                    maxsamples = samples
        except Exception as exc:
            self.logger.debug('Cannot use tifffile: %r', exc)
            ex = exc
            maxseries = None
        if maxseries is None:
            raise TileSourceError(
                'File cannot be opened via tifffile source: %r' % ex)
        return maxseries, maxsamples

    def _findMatchingSeries(self):
        """
        Given a series in self._baseSeries, find other series that have the
        same axes and shape except that they may different in width and height.
        Store the results in self._series, _seriesShape, _framecount, and
        _basis.
        """
        base = self._baseSeries
        page = base.pages[0]
        self._series = []
        self._seriesShape = []
        for idx, s in enumerate(self._tf.series):
            if s != base:
                if s.name.lower() in {'label', 'macro', 'thumbnail', 'map'}:
                    continue
                if 'P' in base.axes or s.axes != base.axes:
                    continue
                if not all(base.axes[sidx] in 'YX' or sl == base.shape[sidx]
                           for sidx, sl in enumerate(s.shape)):
                    continue
                skip = False
                for tag in {'ResolutionUnit', 'XResolution', 'YResolution'}:
                    if (tag in page.tags) != (tag in s.pages[0].tags) or (
                            tag in page.tags and
                            page.tags[tag].value != s.pages[0].tags[tag].value):
                        skip = True
                if skip:
                    continue
            if (s.shape[s.axes.index('X')] < min(self.sizeX, self._minImageSize) and
                    s.shape[s.axes.index('Y')] < min(self.sizeY, self._minImageSize)):
                continue
            self._series.append(idx)
            self._seriesShape.append({
                'sizeX': s.shape[s.axes.index('X')], 'sizeY': s.shape[s.axes.index('Y')]})
            self.sizeX = max(self.sizeX, s.shape[s.axes.index('X')])
            self.sizeY = max(self.sizeY, s.shape[s.axes.index('Y')])
        self._framecount = len(self._series) * math.prod(tuple(
            1 if base.axes[sidx] in 'YXS' else v for sidx, v in enumerate(base.shape)))
        self._basis = {}
        basis = 1
        if 'C' in base.axes:
            self._basis['C'] = (1, base.axes.index('C'), base.shape[base.axes.index('C')])
            basis *= base.shape[base.axes.index('C')]
        for axis in base.axes[::-1]:
            if axis in 'CYXS':
                continue
            self._basis[axis] = (basis, base.axes.index(axis), base.shape[base.axes.index(axis)])
            basis *= base.shape[base.axes.index(axis)]
        if len(self._series) > 1:
            self._basis['P'] = (basis, -1, len(self._series))
        self._zarrlock = threading.RLock()
        self._zarrcache = {}

    def _findAssociatedImages(self):
        """
        Find associated images from unused pages and series.
        """
        pagesInSeries = [p for s in self._tf.series for ll in s.pages.levels for p in ll.pages]
        hashes = [p.hash for p in pagesInSeries if getattr(p, 'keyframe', None) is not None]
        self._associatedImages = {}
        for p in self._tf.pages:
            if (p not in pagesInSeries and getattr(p, 'keyframe', None) is not None and
                    p.hash not in hashes and not len(set(p.axes) - set('YXS'))):
                try:
                    id = 'image_%s' % p.index
                    entry = {'page': p.index}
                    entry['width'] = p.shape[p.axes.index('X')]
                    entry['height'] = p.shape[p.axes.index('Y')]
                    if (id not in self._associatedImages and
                            max(entry['width'], entry['height']) <= self._maxAssociatedImageSize and
                            max(entry['width'], entry['height']) >= self._minAssociatedImageSize):
                        self._associatedImages[id] = entry
                except Exception:
                    pass
        for sidx, s in enumerate(self._tf.series):
            if sidx not in self._series and not len(set(s.axes) - set('YXS')):
                id = 'series_%d' % sidx
                if s.name and s.name.lower() not in self._associatedImages:
                    id = s.name.lower()
                entry = {'series': sidx}
                entry['width'] = s.shape[s.axes.index('X')]
                entry['height'] = s.shape[s.axes.index('Y')]
                if (id not in self._associatedImages and
                        max(entry['width'], entry['height']) <= self._maxAssociatedImageSize and
                        max(entry['width'], entry['height']) >= self._minAssociatedImageSize):
                    self._associatedImages[id] = entry

    def _handle_imagej(self):
        try:
            ijm = self._tf.pages[0].tags['IJMetadata'].value
            if (ijm['Labels'] and len(ijm['Labels']) == self._framecount and
                    not getattr(self, '_channels', None)):
                self._channels = ijm['Labels']
        except Exception:
            pass

    def _handle_indica(self):
        import xml.etree.ElementTree

        import large_image.tilesource.utilities

        try:
            root = xml.etree.ElementTree.fromstring(self._tf.pages[0].description)
            self._xml = large_image.tilesource.utilities.etreeToDict(root)
            self._channels = [c['name'] for c in
                              self._xml['indica']['image']['channels']['channel']]
            if len(self._basis) == 1 and 'I' in self._basis:
                self._basis['C'] = self._basis.pop('I')
            self._associatedImages.clear()
        except Exception:
            pass

    def _handle_ome(self):
        """
        For OME Tiff, if we didn't parse the mangification elsewhere, try to
        parse it here.
        """
        import xml.etree.ElementTree

        import large_image.tilesource.utilities

        _omeUnitsToMeters = {
            'Ym': 1e24,
            'Zm': 1e21,
            'Em': 1e18,
            'Pm': 1e15,
            'Tm': 1e12,
            'Gm': 1e9,
            'Mm': 1e6,
            'km': 1e3,
            'hm': 1e2,
            'dam': 1e1,
            'm': 1,
            'dm': 1e-1,
            'cm': 1e-2,
            'mm': 1e-3,
            '\u00b5m': 1e-6,
            'nm': 1e-9,
            'pm': 1e-12,
            'fm': 1e-15,
            'am': 1e-18,
            'zm': 1e-21,
            'ym': 1e-24,
            '\u00c5': 1e-10,
        }

        try:
            root = xml.etree.ElementTree.fromstring(self._tf.pages[0].description)
            self._xml = large_image.tilesource.utilities.etreeToDict(root)
        except Exception:
            return
        try:
            try:
                base = self._xml['OME']['Image'][0]['Pixels']
            except Exception:
                base = self._xml['OME']['Image']['Pixels']
            if self._mm_x is None and 'PhysicalSizeX' in base:
                self._mm_x = (
                    float(base['PhysicalSizeX']) * 1e3 *
                    _omeUnitsToMeters[base.get('PhysicalSizeXUnit', '\u00b5m')])
            if self._mm_y is None and 'PhysicalSizeY' in base:
                self._mm_y = (
                    float(base['PhysicalSizeY']) * 1e3 *
                    _omeUnitsToMeters[base.get('PhysicalSizeYUnit', '\u00b5m')])
            self._mm_x = self._mm_x or self._mm_y
            self._mm_y = self._mm_y or self._mm_x
        except Exception:
            pass

    def _handle_scn(self):  # noqa
        """
        For SCN files, parse the xml and possibly adjust how associated images
        are labelled.
        """
        import xml.etree.ElementTree

        import large_image.tilesource.utilities

        root = xml.etree.ElementTree.fromstring(self._tf.pages[0].description)
        self._xml = large_image.tilesource.utilities.etreeToDict(root)
        for collection in et_findall(root, 'collection'):
            sizeX = collection.attrib.get('sizeX')
            sizeY = collection.attrib.get('sizeY')
            for supplementalImage in et_findall(collection, 'supplementalImage'):
                name = supplementalImage.attrib.get('type', '').lower()
                ifd = supplementalImage.attrib.get('ifd', '')
                oldname = 'image_%s' % ifd
                if (name and ifd and oldname in self._associatedImages and
                        name not in self._associatedImages):
                    self._associatedImages[name] = self._associatedImages[oldname]
                    self._associatedImages.pop(oldname, None)
            for image in et_findall(collection, 'image'):
                name = image.attrib.get('name', 'Unknown')
                for view in et_findall(image, 'view'):
                    if (sizeX and view.attrib.get('sizeX') == sizeX and
                            sizeY and view.attrib.get('sizeY') == sizeY and
                            not int(view.attrib.get('offsetX')) and
                            not int(view.attrib.get('offsetY')) and
                            name.lower() in self._associatedImages and
                            'macro' not in self._associatedImages):
                        self._associatedImages['macro'] = self._associatedImages[name.lower()]
                        self._associatedImages.pop(name.lower(), None)
                if name != self._baseSeries.name:
                    continue
                for scanSettings in et_findall(image, 'scanSettings'):
                    for objectiveSettings in et_findall(scanSettings, 'objectiveSettings'):
                        for objective in et_findall(objectiveSettings, 'objective'):
                            if not hasattr(self, '_magnification') and float(objective.text) > 0:
                                self._magnification = float(objective.text)
                    for channelSettings in et_findall(scanSettings, 'channelSettings'):
                        channels = {}
                        for channel in et_findall(channelSettings, 'channel'):
                            channels[int(channel.attrib.get('index', 0))] = (
                                large_image.tilesource.utilities.etreeToDict(channel)['channel'])
                        self._channelInfo = channels
                        try:
                            self._channels = [
                                channels.get(idx)['name'].split('|')[0]
                                for idx in range(len(channels))]
                        except Exception:
                            pass

    def _handle_svs(self):
        """
        For SVS files, parse the magnification and pixel size.
        """
        try:
            meta = self._tf.pages[0].description
            self._magnification = float(meta.split('AppMag = ')[1].split('|')[0].strip())
            self._mm_x = self._mm_y = float(
                meta.split('|MPP = ', 1)[1].split('|')[0].strip()) * 0.001
        except Exception:
            pass

    def getNativeMagnification(self):
        """
        Get the magnification at a particular level.

        :return: magnification, width of a pixel in mm, height of a pixel in mm.
        """
        mm_x = self._mm_x
        mm_y = self._mm_y
        # Estimate the magnification; we don't have a direct value
        mag = 0.01 / mm_x if mm_x else None
        return {
            'magnification': getattr(self, '_magnification', mag),
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
        if self._framecount > 1:
            result['frames'] = frames = []
            for idx in range(self._framecount):
                frame = {'Frame': idx}
                for axis, (basis, _pos, count) in self._basis.items():
                    if axis != 'I':
                        frame['Index' + (axis.upper() if axis.upper() != 'P' else 'XY')] = (
                            idx // basis) % count
                frames.append(frame)
            self._addMetadataFrameInformation(result, getattr(self, '_channels', None))
            if any(v != self._seriesShape[0] for v in self._seriesShape):
                result['SizesXY'] = self._seriesShape
        return result

    def getInternalMetadata(self, **kwargs):
        """
        Return additional known metadata about the tile source.  Data returned
        from this method is not guaranteed to be in any particular format or
        have specific values.

        :returns: a dictionary of data or None.
        """
        result = {}
        pages = [s.pages[0] for s in self._tf.series]
        pagesInSeries = [p for s in self._tf.series for ll in s.pages.levels for p in ll.pages]
        pages.extend([page for page in self._tf.pages if page not in pagesInSeries])
        for page in pages:
            for tag in getattr(page, 'tags', []):
                if (tag.dtype_name == 'ASCII' or (
                        tag.dtype_name == 'BYTE' and isinstance(tag.value, dict))) and tag.value:
                    key = basekey = tag.name
                    suffix = 0
                    while key in result:
                        if result[key] == tag.value:
                            break
                        suffix += 1
                        key = '%s_%d' % (basekey, suffix)
                    result[key] = tag.value
                    if isinstance(result[key], dict):
                        result[key] = result[key].copy()
                        for subkey in list(result[key]):
                            try:
                                json.dumps(result[key][subkey])
                            except Exception:
                                del result[key][subkey]
        if hasattr(self, '_xml') and 'xml' not in result:
            result.pop('ImageDescription', None)
            result['xml'] = self._xml
        if hasattr(self, '_channelInfo'):
            result['channelInfo'] = self._channelInfo
        result['tifffileKind'] = self._baseSeries.kind
        return result

    def getAssociatedImagesList(self):
        """
        Get a list of all associated images.

        :return: the list of image keys.
        """
        return sorted(self._associatedImages)

    def _getAssociatedImage(self, imageKey):
        """
        Get an associated image in PIL format.

        :param imageKey: the key of the associated image.
        :return: the image in PIL format or None.
        """
        if imageKey in self._associatedImages:
            entry = self._associatedImages[imageKey]
            if 'page' in entry:
                source = self._tf.pages[entry['page']]
            else:
                source = self._tf.series[entry['series']]
            image = source.asarray()
            axes = source.axes
            if axes not in {'YXS', 'YX'}:
                # rotate axes to YXS or YX
                image = np.moveaxis(image, [
                    source.axes.index(a) for a in 'YXS' if a in source.axes
                ], range(len(source.axes)))
            return large_image.tilesource.base._imageToPIL(image)

    def _nonemptyLevelsList(self, frame=0):
        """
        Return a list of one value per level where the value is None if the
        level does not exist in the file and any other value if it does.

        :param frame: the frame number.
        :returns: a list of levels length.
        """
        if frame is None:
            frame = 0
        if hasattr(self, '_nonempty_levels_list') and frame in self._nonempty_levels_list:
            return self._nonempty_levels_list[frame]
        if len(self._series) > 1:
            sidx = frame // self._basis['P'][0]
        else:
            sidx = 0
        nonempty = [None] * self.levels
        nonempty[self.levels - 1] = True
        series = self._tf.series[self._series[sidx]]
        za, hasgbs = self._getZarrArray(series, sidx)
        xidx = series.axes.index('X')
        yidx = series.axes.index('Y')
        for ll in range(1, len(series.levels)):
            scale = round(math.log(max(za[0].shape[xidx] / za[ll].shape[xidx],
                                       za[0].shape[yidx] / za[ll].shape[yidx])) / math.log(2))
            if 0 < scale < self.levels:
                nonempty[self.levels - 1 - int(scale)] = True
        if not hasattr(self, '_nonempty_levels_list'):
            self._nonempty_levels_list = {}
        self._nonempty_levels_list[frame] = nonempty
        return nonempty

    def getPreferredLevel(self, level):
        """
        Given a desired level (0 is minimum resolution, self.levels - 1 is max
        resolution), return the level that contains actual data that is no
        lower resolution.

        :param level: desired level
        :returns level: a level with actual data that is no lower resolution.
        """
        return max(0, min(level, self.levels - 1))

    def _getZarrArray(self, series, sidx):
        with self._zarrlock:
            if sidx not in self._zarrcache:
                if len(self._zarrcache) > 10:
                    self._zarrcache = {}
                za = zarr.open(series.aszarr(), mode='r')
                hasgbs = hasattr(za[0], 'get_basic_selection')
                if not hasgbs and math.prod(series.shape) < 256 * 1024 ** 2:
                    za = series.asarray()
                self._zarrcache[sidx] = (za, hasgbs)
            za, hasgbs = self._zarrcache[sidx]
        return za, hasgbs

    @methodcache()
    def getTile(self, x, y, z, pilImageAllowed=False, numpyAllowed=False, **kwargs):
        frame = self._getFrame(**kwargs)
        self._xyzInRange(x, y, z, frame, self._framecount)
        x0, y0, x1, y1, step = self._xyzToCorners(x, y, z)
        if len(self._series) > 1:
            sidx = frame // self._basis['P'][0]
        else:
            sidx = 0
        series = self._tf.series[self._series[sidx]]
        za, hasgbs = self._getZarrArray(series, sidx)
        xidx = series.axes.index('X')
        yidx = series.axes.index('Y')
        if hasgbs:
            bza = za[0]
            # we could cache this
            for ll in range(len(series.levels) - 1, 0, -1):
                scale = round(max(za[0].shape[xidx] / za[ll].shape[xidx],
                                  za[0].shape[yidx] / za[ll].shape[yidx]))
                if scale <= step and step // scale == step / scale:
                    bza = za[ll]
                    x0 //= scale
                    x1 //= scale
                    y0 //= scale
                    y1 //= scale
                    step //= scale
                    break
        else:
            bza = za
        if step > 2 ** self._maxSkippedLevels:
            tile, _format = self._getTileFromEmptyLevel(x, y, z, **kwargs)
            tile = large_image.tilesource.base._imageToNumpy(tile)[0]
        else:
            sel = []
            baxis = ''
            for aidx, axis in enumerate(series.axes):
                if axis == 'X':
                    sel.append(slice(x0, x1, step))
                    baxis += 'X'
                elif axis == 'Y':
                    sel.append(slice(y0, y1, step))
                    baxis += 'Y'
                elif axis == 'S':
                    sel.append(slice(series.shape[aidx]))
                    baxis += 'S'
                else:
                    if axis not in self._basis and axis == 'I':
                        axis = 'C'
                    sel.append((frame // self._basis[axis][0]) % self._basis[axis][2])
            tile = bza[tuple(sel)]
            # rotate
            if baxis not in {'YXS', 'YX'}:
                tile = np.moveaxis(
                    tile, [baxis.index(a) for a in 'YXS' if a in baxis], range(len(baxis)))
        return self._outputTile(tile, TILE_FORMAT_NUMPY, x, y, z,
                                pilImageAllowed, numpyAllowed, **kwargs)

    @classmethod
    def addKnownExtensions(cls):
        if not hasattr(cls, '_addedExtensions'):
            _lazyImport()
            cls._addedExtensions = True
            cls.extensions = cls.extensions.copy()
            for ext in tifffile.TIFF.FILE_EXTENSIONS:
                if ext not in cls.extensions:
                    cls.extensions[ext] = SourcePriority.IMPLICIT


def open(*args, **kwargs):
    """
    Create an instance of the module class.
    """
    return TifffileFileTileSource(*args, **kwargs)


def canRead(*args, **kwargs):
    """
    Check if an input can be read by the module class.
    """
    return TifffileFileTileSource.canRead(*args, **kwargs)
