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

import colorsys
import itertools
import math
import re
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _importlib_version

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from large_image.cache_util import LruCacheMetaclass, methodcache, strhash
from large_image.constants import TILE_FORMAT_NUMPY, TILE_FORMAT_PIL, SourcePriority
from large_image.exceptions import TileSourceError
from large_image.tilesource import TileSource
from large_image.tilesource.utilities import _imageToNumpy, _imageToPIL

try:
    __version__ = _importlib_version(__name__)
except PackageNotFoundError:
    # package is not installed
    pass


_counters = {
    'tiles': 0,
}


class TestTileSource(TileSource, metaclass=LruCacheMetaclass):
    cacheName = 'tilesource'
    name = 'test'
    extensions = {
        None: SourcePriority.MANUAL,
    }

    def __init__(self, ignored_path=None, minLevel=0, maxLevel=9,
                 tileWidth=256, tileHeight=256, sizeX=None, sizeY=None,
                 fractal=False, frames=None, monochrome=False, bands=None,
                 **kwargs):
        """
        Initialize the tile class.  See the base class for other available
        parameters.

        :param ignored_path: for compatibility with FileTileSource.
        :param minLevel: minimum tile level
        :param maxLevel: maximum tile level.  If both sizeX and sizeY are
            specified, this value is ignored.
        :param tileWidth: tile width in pixels
        :param tileHeight: tile height in pixels
        :param sizeX: image width in pixels at maximum level.  Computed from
            maxLevel and tileWidth if None.
        :param sizeY: image height in pixels at maximum level.  Computed from
            maxLevel and tileHeight if None.
        :param fractal: if True, and the tile size is square and a power of
            two, draw a simple fractal on the tiles.
        :param frames: if present, this is either a single number for generic
            frames, a comma-separated list of c,z,t,xy, or a string of the
            form '<axis>=<count>,<axis>=<count>,...'.
        :param monochrome: if True, return single channel tiles.
        :param bands: if present, a comma-separated list of band names.
            Defaults to red,green,blue.  Each band may optionally specify a
            value range in the form "<band name>=<min val>-<max val>".  If any
            ranges are specified, bands with no ranges will use the union of
            the specified ranges.  The internal dtype with be uint8, uint16, or
            float depending on the union of the specified ranges.  If no ranges
            are specified at all, it is the same as 0-255.
        """
        if not kwargs.get('encoding'):
            kwargs = kwargs.copy()
            kwargs['encoding'] = 'PNG'
        super().__init__(**kwargs)

        self._spec = (
            minLevel, maxLevel, tileWidth, tileHeight, sizeX, sizeY, fractal,
            frames, monochrome, bands)
        self.minLevel = minLevel
        self.maxLevel = maxLevel
        self.tileWidth = tileWidth
        self.tileHeight = tileHeight
        # Don't generate a fractal tile if the tile isn't square or not a power
        # of 2 in size.
        self.fractal = (fractal and self.tileWidth == self.tileHeight and
                        not (self.tileWidth & (self.tileWidth - 1)))
        self.sizeX = (((2 ** self.maxLevel) * self.tileWidth)
                      if not sizeX else sizeX)
        self.sizeY = (((2 ** self.maxLevel) * self.tileHeight)
                      if not sizeY else sizeY)
        self.maxLevel = max(0, int(math.ceil(math.log2(max(
            self.sizeX / self.tileWidth, self.sizeY / self.tileHeight)))))
        self.minLevel = min(self.minLevel, self.maxLevel)
        self.monochrome = bool(monochrome)
        self._bands = None
        self._dtype = np.uint8
        if bands:
            bands = [re.match(
                r'^(?P<key>[^=]+)(|=(?P<low>[+-]?((\d+(|\.\d*)))|(\.\d+))-(?P<high>[+-]?((\d+(|\.\d*))|(\.\d+))))$',  # noqa
                band) for band in bands.split(',')]
            lows = [float(band.group('low'))
                    if band.group('low') is not None else None for band in bands]
            highs = [float(band.group('high'))
                     if band.group('high') is not None else None for band in bands]
            try:
                low = min(v for v in lows + highs if v is not None)
                high = max(v for v in lows + highs if v is not None)
            except ValueError:
                low = 0
                high = 255
            self._bands = {
                band.group('key'): {
                    'low': lows[idx] if lows[idx] is not None else low,
                    'high': highs[idx] if highs[idx] is not None else high,
                }
                for idx, band in enumerate(bands)}
            if low < 0 or high < 2 or low >= 65536 or high >= 65536:
                self._dtype = np.dtype(float)
            elif low >= 256 or high >= 256:
                self._dtype = np.uint16
        # Used for reporting tile information
        self.levels = self.maxLevel + 1
        if frames:
            frameList = []
            if '=' not in str(frames) and ',' not in str(frames):
                self._axes = [('f', 'Index', int(frames))]
            elif '=' not in str(frames):
                self._axes = [
                    (axis, f'Index{axis.upper()}', int(part))
                    for axis, part in zip(['c', 'z', 't', 'xy'], frames.split(','))]
            else:
                self._axes = [
                    (part.split('=', 1)[0],
                     f'Index{part.split("=", 1)[0].upper()}',
                     int(part.split('=', 1)[1])) for part in frames.split(',')]
            self._framesParts = len(self._axes)
            axes = self._axes[::-1]
            for fidx in itertools.product(*(range(part[-1]) for part in axes)):
                curframe = {}
                for idx in range(len(fidx)):
                    k = axes[idx][1]
                    v = fidx[idx]
                    if axes[idx][-1] > 1:
                        curframe[k] = v
                frameList.append(curframe)
            if len(frameList) > 1:
                self._frames = frameList

    @classmethod
    def canRead(cls, *args, **kwargs):
        return True

    def fractalTile(self, image, x, y, widthCount, color=(0, 0, 0)):
        """
        Draw a simple fractal in a tile image.

        :param image: a Pil image to draw on.  Modified.
        :param x: the tile x position
        :param y: the tile y position
        :param widthCount: 2 ** z; the number of tiles across for a "full size"
            image at this z level.
        :param color: an rgb tuple on a scale of [0-255].
        """
        imageDraw = ImageDraw.Draw(image)
        x *= self.tileWidth
        y *= self.tileHeight
        sq = widthCount * self.tileWidth
        while sq >= 4:
            sq1 = sq // 4
            sq2 = sq1 + sq // 2
            for t in range(-(y % sq), self.tileWidth, sq):
                if t + sq1 < self.tileWidth and t + sq2 >= 0:
                    for l in range(-(x % sq), self.tileWidth, sq):
                        if l + sq1 < self.tileWidth and l + sq2 >= 0:
                            imageDraw.rectangle([
                                max(-1, l + sq1), max(-1, t + sq1),
                                min(self.tileWidth, l + sq2 - 1),
                                min(self.tileWidth, t + sq2 - 1),
                            ], color, None)
            sq //= 2

    def getMetadata(self):
        """
        Return a dictionary of metadata containing levels, sizeX, sizeY,
        tileWidth, tileHeight, magnification, mm_x, mm_y, and frames.

        :returns: metadata dictionary.
        """
        result = super().getMetadata()
        if hasattr(self, '_frames') and len(self._frames) > 1:
            result['frames'] = self._frames
            self._addMetadataFrameInformation(result)
        if self._bands:
            result['bands'] = {n + 1: {'interpretation': val}
                               for n, val in enumerate(self._bands)}
        return result

    def getInternalMetadata(self, **kwargs):
        """
        Return additional known metadata about the tile source.  Data returned
        from this method is not guaranteed to be in any particular format or
        have specific values.

        :returns: a dictionary of data or None.
        """
        return {'fractal': self.fractal, 'monochrome': self.monochrome}

    def _tileImage(self, rgbColor, x, y, z, frame, band=None, bandnum=0):
        image = Image.new(
            mode='RGB',
            size=(self.tileWidth, self.tileHeight),
            color=(rgbColor if not self.fractal else (255, 255, 255)),
        )
        if self.fractal:
            self.fractalTile(image, x, y, 2 ** z, rgbColor)

        bandtext = '\n' if band is not None else ''
        if bandnum and band and band.lower() not in {
                'r', 'red', 'g', 'green', 'b', 'blue', 'grey', 'gray', 'alpha'}:
            bandtext += band
            image = _imageToNumpy(image)[0].astype(float)
            vstripe = np.array([
                int(x / (self.tileWidth / bandnum / 2)) % 2
                for x in range(self.tileWidth)])
            hstripe = np.array([
                int(y / (self.tileHeight / (bandnum % self.tileWidth) / 2)) % 2
                if bandnum > self.tileWidth else 1 for y in range(self.tileHeight)])
            simage = image.copy()
            simage[hstripe == 0, :, :] /= 2
            simage[:, vstripe == 0, :] /= 2
            image = np.where(image != 255, simage, image)
            image = image.astype(np.uint8)
            image = _imageToPIL(image)

        imageDraw = ImageDraw.Draw(image)

        fontsize = 0.15
        text = 'x=%d\ny=%d\nz=%d' % (x, y, z)
        if hasattr(self, '_frames'):
            for k1, k2, _ in self._axes:
                if k2 in self._frames[frame]:
                    text += '\n%s=%d' % (k1.upper(), self._frames[frame][k2])
        text += bandtext
        fontsize = min(fontsize, 0.8 / len(text.split('\n')))
        try:
            # the font size should fill the whole tile
            imageDrawFont = ImageFont.truetype(
                font='/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
                size=int(fontsize * min(self.tileWidth, self.tileHeight)),
            )
        except OSError:
            imageDrawFont = ImageFont.load_default()
        imageDraw.multiline_text(
            xy=(10, 10),
            text=text,
            fill=(0, 0, 0) if band != 'alpha' else (255, 255, 255),
            font=imageDrawFont,
        )
        return image

    @methodcache()
    def getTile(self, x, y, z, *args, **kwargs):
        frame = self._getFrame(**kwargs)
        self._xyzInRange(x, y, z, frame, len(self._frames) if hasattr(self, '_frames') else None)

        if not (self.minLevel <= z <= self.maxLevel):
            msg = 'z layer does not exist'
            raise TileSourceError(msg)
        _counters['tiles'] += 1

        xFraction = (x + 0.5) * self.tileWidth * 2 ** (self.levels - 1 - z) / self.sizeX
        yFraction = (y + 0.5) * self.tileHeight * 2 ** (self.levels - 1 - z) / self.sizeY
        fFraction = yFraction
        if hasattr(self, '_frames'):
            fFraction = float(frame) / (len(self._frames) - 1)

        backgroundColor = colorsys.hsv_to_rgb(
            h=xFraction,
            s=(0.3 + (0.7 * fFraction)),
            v=(0.3 + (0.7 * yFraction)),
        )
        rgbColor = tuple(int(val * 255) for val in backgroundColor)

        if not self._bands or len(self._bands) == (1 if self.monochrome else 3):
            image = self._tileImage(rgbColor, x, y, z, frame)
            if self.monochrome:
                image = image.convert('L')
            format = TILE_FORMAT_PIL
        else:
            image = np.zeros(
                (self.tileHeight, self.tileWidth, len(self._bands)), dtype=self._dtype)
            for bandnum, band in enumerate(self._bands):
                bandimg = self._tileImage(rgbColor, x, y, z, frame, band, bandnum)
                if self.monochrome or band.upper() in {'grey', 'gray', 'alpha'}:
                    bandimg = bandimg.convert('L')
                bandimg = _imageToNumpy(bandimg)[0]
                if (self._dtype != np.uint8 or
                        self._bands[band]['low'] != 0 or
                        self._bands[band]['high'] != 255):
                    bandimg = bandimg.astype(float)
                    bandimg = (bandimg / 255) * (
                        self._bands[band]['high'] - self._bands[band]['low']
                    ) + self._bands[band]['low']
                    bandimg = bandimg.astype(self._dtype)
                image[:, :, bandnum] = bandimg[:, :, bandnum % bandimg.shape[2]]
            format = TILE_FORMAT_NUMPY
        return self._outputTile(image, format, x, y, z, **kwargs)

    @staticmethod
    def getLRUHash(*args, **kwargs):
        return strhash(
            super(TestTileSource, TestTileSource).getLRUHash(
                *args, **kwargs),
            kwargs.get('minLevel'), kwargs.get('maxLevel'),
            kwargs.get('tileWidth'), kwargs.get('tileHeight'),
            kwargs.get('fractal'), kwargs.get('sizeX'), kwargs.get('sizeY'),
            kwargs.get('frames'), kwargs.get('monochrome'),
            kwargs.get('bands'),
        )

    def getState(self):
        return 'test %r %r' % (super().getState(), self._spec)


def open(*args, **kwargs):
    """
    Create an instance of the module class.
    """
    return TestTileSource(*args, **kwargs)


def canRead(*args, **kwargs):
    """
    Check if an input can be read by the module class.
    """
    return TestTileSource.canRead(*args, **kwargs)
