from typing import Any, Dict, Optional, Tuple, Union, cast

import numpy as np
import PIL
import PIL.Image
import PIL.ImageColor
import PIL.ImageDraw

from .. import exceptions
from ..constants import TILE_FORMAT_IMAGE, TILE_FORMAT_NUMPY, TILE_FORMAT_PIL
from .utilities import ImageBytes, _encodeImage, _imageToNumpy, _imageToPIL


class LazyTileDict(dict):
    """
    Tiles returned from the tile iterator and dictionaries of information with
    actual image data in the 'tile' key and the format in the 'format' key.
    Since some applications need information about the tile but don't need the
    image data, these two values are lazily computed.  The LazyTileDict can be
    treated like a regular dictionary, except that when either of those two
    keys are first accessed, they will cause the image to be loaded and
    possibly converted to a PIL image and cropped.

    Unless setFormat is called on the tile, tile images may always be returned
    as PIL images.
    """

    def __init__(self, tileInfo: Dict[str, Any], *args, **kwargs) -> None:
        """
        Create a LazyTileDict dictionary where there is enough information to
        load the tile image.  ang and kwargs are as for the dict() class.

        :param tileInfo: a dictionary of x, y, level, format, encoding, crop,
            and source, used for fetching the tile image.
        """
        self.x = tileInfo['x']
        self.y = tileInfo['y']
        self.frame = tileInfo.get('frame')
        self.level = tileInfo['level']
        self.format = tileInfo['format']
        self.encoding = tileInfo['encoding']
        self.crop = tileInfo['crop']
        self.source = tileInfo['source']
        self.resample = tileInfo.get('resample', False)
        self.requestedScale = tileInfo.get('requestedScale')
        self.metadata = cast(Dict[str, Any], tileInfo.get('metadata'))
        self.retile = tileInfo.get('retile') and self.metadata

        self.deferredKeys = ('tile', 'format')
        self.alwaysAllowPIL = True
        self.imageKwargs: Dict[str, Any] = {}
        self.loaded = False
        super().__init__(*args, **kwargs)
        # We set this initially so that they are listed in known keys using the
        # native dictionary methods
        self['tile'] = None
        self['format'] = None
        self.width = self['width']
        self.height = self['height']

    def setFormat(
            self, format: Tuple[str, ...], resample: bool = False,
            imageKwargs: Optional[Dict[str, Any]] = None) -> None:
        """
        Set a more restrictive output format for a tile, possibly also resizing
        it via resampling.  If this is not called, the tile may either be
        returned as one of the specified formats or as a PIL image.

        :param format: a tuple or list of allowed formats.  Formats are members
            of TILE_FORMAT_*.  This will avoid converting images if they are
            in the desired output encoding (regardless of subparameters).
        :param resample: if not False or None, allow resampling.  Once turned
            on, this cannot be turned off on the tile.
        :param imageKwargs: additional parameters that should be passed to
            _encodeImage.
        """
        # If any parameters are changed, mark the tile as not loaded, so that
        # referring to a deferredKey will reload the image.
        self.alwaysAllowPIL = False
        if format is not None and format != self.format:
            self.format = format
            self.loaded = False
        if (resample not in (False, None) and not self.resample and
                self.requestedScale and round(self.requestedScale, 2) != 1.0):
            self.resample = resample
            self['scaled'] = 1.0 / self.requestedScale
            self['tile_x'] = self.get('tile_x', self['x'])
            self['tile_y'] = self.get('tile_y', self['y'])
            self['tile_width'] = self.get('tile_width', self.width)
            self['tile_height'] = self.get('tile_width', self.height)
            if self.get('magnification', None):
                self['tile_magnification'] = self.get('tile_magnification', self['magnification'])
            self['tile_mm_x'] = self.get('mm_x')
            self['tile_mm_y'] = self.get('mm_y')
            self['x'] = float(self['tile_x'])
            self['y'] = float(self['tile_y'])
            # Add provisional width and height
            if self.resample not in (False, None) and self.requestedScale:
                self['width'] = max(1, int(
                    self['tile_width'] / self.requestedScale))
                self['height'] = max(1, int(
                    self['tile_height'] / self.requestedScale))
                if self.get('tile_magnification', None):
                    self['magnification'] = self['tile_magnification'] / self.requestedScale
                if self.get('tile_mm_x', None):
                    self['mm_x'] = self['tile_mm_x'] * self.requestedScale
                if self.get('tile_mm_y', None):
                    self['mm_y'] = self['tile_mm_y'] * self.requestedScale
            # If we can resample the tile, many parameters may change once the
            # image is loaded.  Don't include width and height in this list;
            # the provisional values are sufficient.
            self.deferredKeys = ('tile', 'format')
            self.loaded = False
        if imageKwargs is not None:
            self.imageKwargs = imageKwargs
            self.loaded = False

    def _retileTile(self) -> np.ndarray:
        """
        Given the tile information, create a numpy array and merge multiple
        tiles together to form a tile of a different size.
        """
        tileWidth = self.metadata['tileWidth']
        tileHeight = self.metadata['tileHeight']
        level = self.level
        frame = self.frame
        width = self.width
        height = self.height
        tx = self['x']
        ty = self['y']

        retile = None
        xmin = int(max(0, tx // tileWidth))
        xmax = int((tx + width - 1) // tileWidth + 1)
        ymin = int(max(0, ty // tileHeight))
        ymax = int((ty + height - 1) // tileHeight + 1)
        for y in range(ymin, ymax):
            for x in range(xmin, xmax):
                tileData = self.source.getTile(
                    x, y, level,
                    numpyAllowed='always', sparseFallback=True, frame=frame)
                if not isinstance(tileData, np.ndarray) or len(tileData.shape) != 3:
                    tileData, _ = _imageToNumpy(tileData)
                x0 = int(x * tileWidth - tx)
                y0 = int(y * tileHeight - ty)
                if x0 < 0:
                    tileData = tileData[:, -x0:]
                    x0 = 0
                if y0 < 0:
                    tileData = tileData[-y0:, :]
                    y0 = 0
                tw = min(tileData.shape[1], width - x0)
                th = min(tileData.shape[0], height - y0)
                if retile is None:
                    retile = np.empty((height, width, tileData.shape[2]), dtype=tileData.dtype)
                elif tileData.shape[2] < retile.shape[2]:
                    retile = retile[:, :, :tileData.shape[2]]
                retile[y0:y0 + th, x0:x0 + tw] = tileData[
                    :th, :tw, :retile.shape[2]]  # type: ignore[misc]
        return cast(np.ndarray, retile)

    def _resample(self, tileData: Union[ImageBytes, PIL.Image.Image, bytes, np.ndarray]) -> Tuple[
        Union[ImageBytes, PIL.Image.Image, bytes, np.ndarray], Optional[PIL.Image.Image],
    ]:
        """
        If we need to resample a tile, use PIL if it is uint8 or we are using
        a specific resampling mode that is PIL-specific.  Otherwise, use
        skimage if available.

        :param tileData: the image to scale.
        :returns: tileData, pilData.  pilData will be None if the results are a
            numpy array.
        """
        pilData = None
        if self.resample in (False, None) or not self.requestedScale:
            return tileData, pilData
        pilResize = True
        if (isinstance(tileData, np.ndarray) and tileData.dtype.kind != np.uint8 and
                TILE_FORMAT_NUMPY in self.format and self.resample in {True, 2, 3}):
            try:
                import skimage.transform
                pilResize = False
            except ImportError:
                pass
        if pilResize:
            pilData = _imageToPIL(tileData)

            self['width'] = max(1, int(
                pilData.size[0] / self.requestedScale))
            self['height'] = max(1, int(
                pilData.size[1] / self.requestedScale))
            pilData = tileData = pilData.resize(
                (self['width'], self['height']),
                resample=getattr(PIL.Image, 'Resampling', PIL.Image).LANCZOS
                if self.resample is True else self.resample)
        else:
            tileData = skimage.transform.resize(
                cast(np.ndarray, tileData),
                (self['width'], self['height'],
                 cast(np.ndarray, tileData).shape[2]),  # type: ignore[misc]
                order=3 if self.resample is True else self.resample)
        return tileData, pilData

    def __getitem__(self, key: str, *args, **kwargs) -> Any:
        """
        If this is the first time either the tile or format key is requested,
        load the tile image data.  Otherwise, just return the internal
        dictionary result.

        See the base dict class for function details.
        """
        if not self.loaded and key in self.deferredKeys:
            # Flag this immediately to avoid recursion if we refer to the
            # tile's own values.
            self.loaded = True

            if not self.retile:
                tileData = self.source.getTile(
                    self.x, self.y, self.level,
                    pilImageAllowed=True,
                    numpyAllowed='always' if TILE_FORMAT_NUMPY in self.format else True,
                    sparseFallback=True, frame=self.frame)
                if self.crop:
                    tileData, _ = _imageToNumpy(tileData)
                    tileData = tileData[self.crop[1]:self.crop[3], self.crop[0]:self.crop[2]]
            else:
                tileData = self._retileTile()

            pilData = None
            # resample if needed
            if self.resample not in (False, None) and self.requestedScale:
                tileData, pilData = self._resample(tileData)

            tileFormat = (TILE_FORMAT_PIL if isinstance(tileData, PIL.Image.Image)
                          else (TILE_FORMAT_NUMPY if isinstance(tileData, np.ndarray)
                                else TILE_FORMAT_IMAGE))
            tileEncoding = None if tileFormat != TILE_FORMAT_IMAGE else (
                'JPEG' if tileData[:3] == b'\xff\xd8\xff' else
                'PNG' if tileData[:4] == b'\x89PNG' else
                'TIFF' if tileData[:4] == b'II\x2a\x00' else
                None)
            # Reformat the image if required
            if (not self.alwaysAllowPIL or
                    (TILE_FORMAT_NUMPY in self.format and isinstance(tileData, np.ndarray))):
                if (tileFormat in self.format and (tileFormat != TILE_FORMAT_IMAGE or (
                        tileEncoding and
                        tileEncoding == self.imageKwargs.get('encoding', self.encoding)))):
                    # already in an acceptable format
                    pass
                elif TILE_FORMAT_NUMPY in self.format:
                    tileData, _ = _imageToNumpy(tileData)
                    tileFormat = TILE_FORMAT_NUMPY
                elif TILE_FORMAT_PIL in self.format:
                    tileData = pilData if pilData is not None else _imageToPIL(tileData)
                    tileFormat = TILE_FORMAT_PIL
                elif TILE_FORMAT_IMAGE in self.format:
                    tileData, mimeType = _encodeImage(
                        tileData, **self.imageKwargs)
                    tileFormat = TILE_FORMAT_IMAGE
                if tileFormat not in self.format:
                    raise exceptions.TileSourceError(
                        'Cannot yield tiles in desired format %r' % (
                            self.format, ))
            elif (TILE_FORMAT_PIL not in self.format and TILE_FORMAT_NUMPY in self.format and
                    not isinstance(tileData, PIL.Image.Image)):
                tileData, _ = _imageToNumpy(tileData)
                tileFormat = TILE_FORMAT_NUMPY
            else:
                tileData = pilData if pilData is not None else _imageToPIL(tileData)
                tileFormat = TILE_FORMAT_PIL

            self['tile'] = tileData
            self['format'] = tileFormat
        return super().__getitem__(key, *args, **kwargs)

    def release(self) -> None:
        """
        If the tile has been loaded, unload it.  It can be loaded again.  This
        is useful if you want to keep tiles available in memory but not their
        actual tile data.
        """
        if self.loaded:
            self.loaded = False
            for key in self.deferredKeys:
                self[key] = None
