import io
import math
import threading
import types
import xml.etree.ElementTree
from collections import defaultdict
from operator import attrgetter
from typing import Any, Dict, List, Optional, Set, Tuple, Union, cast

import numpy as np
import numpy.typing as npt
import PIL
import PIL.Image
import PIL.ImageColor
import PIL.ImageDraw

from ..constants import dtypeToGValue

# This was exposed here, once.

try:
    import simplejpeg
except ImportError:
    simplejpeg = None

from ..constants import (TILE_FORMAT_IMAGE, TILE_FORMAT_NUMPY, TILE_FORMAT_PIL,
                         TileOutputMimeTypes, TileOutputPILFormat)

# Turn off decompression warning check
PIL.Image.MAX_IMAGE_PIXELS = None

# This is used by any submodule that uses vips to avoid a race condition in
# new_from_file.  Since vips is technically optional and the various modules
# might pull it in independently, it is located here to make is shareable.
_newFromFileLock = threading.RLock()

# Extend colors so G and GREEN map to expected values.  CSS green is #0080ff,
# which is unfortunate.
colormap = {
    'R': '#ff0000',
    'G': '#00ff00',
    'B': '#0000ff',
    'RED': '#ff0000',
    'GREEN': '#00ff00',
    'BLUE': '#0000ff',
}
modesBySize = ['L', 'LA', 'RGB', 'RGBA']


class ImageBytes(bytes):
    """
    Wrapper class to make repr of image bytes better in ipython.

    Display the number of bytes and, if known, the mimetype.
    """

    def __new__(cls, source: bytes, mimetype: Optional[str] = None):
        self = super().__new__(cls, source)
        vars(self)['_mime_type'] = mimetype
        return self

    @property
    def mimetype(self) -> Optional[str]:
        return vars(self)['_mime_type']

    def _repr_png_(self) -> Optional[bytes]:
        if self.mimetype == 'image/png':
            return self
        return None

    def _repr_jpeg_(self) -> Optional[bytes]:
        if self.mimetype == 'image/jpeg':
            return self
        return None

    def __repr__(self) -> str:
        if self.mimetype:
            return f'ImageBytes<{len(self)}> ({self.mimetype})'
        return f'ImageBytes<{len(self)}> (wrapped image bytes)'


class JSONDict(dict):
    """Wrapper class to improve Jupyter repr of JSON-able dicts."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # TODO: validate JSON serializable?

    def _repr_json_(self) -> Dict:
        return self


def _encodeImageBinary(
        image: PIL.Image.Image, encoding: str, jpegQuality: Union[str, int],
        jpegSubsampling: Union[str, int], tiffCompression: str) -> bytes:
    """
    Encode a PIL Image to a binary representation of the image (a jpeg, png, or
    tif).

    :param image: a PIL image.
    :param encoding: a valid PIL encoding (typically 'PNG' or 'JPEG').  Must
        also be in the TileOutputMimeTypes map.
    :param jpegQuality: the quality to use when encoding a JPEG.
    :param jpegSubsampling: the subsampling level to use when encoding a JPEG.
    :param tiffCompression: the compression format to use when encoding a TIFF.
    :returns: a binary image or b'' if the image is of zero size.
    """
    encoding = TileOutputPILFormat.get(encoding, encoding)
    if image.width == 0 or image.height == 0:
        return b''
    params: Dict[str, Any] = {}
    if encoding == 'JPEG':
        if image.mode not in ({'L', 'RGB', 'RGBA'} if simplejpeg else {'L', 'RGB'}):
            image = image.convert('RGB' if image.mode != 'LA' else 'L')
        if simplejpeg:
            return ImageBytes(simplejpeg.encode_jpeg(
                _imageToNumpy(image)[0],
                quality=jpegQuality,
                colorspace=image.mode if image.mode in {'RGB', 'RGBA'} else 'GRAY',
                colorsubsampling={-1: '444', 0: '444', 1: '422', 2: '420'}.get(
                    cast(int, jpegSubsampling), str(jpegSubsampling).strip(':')),
            ), mimetype='image/jpeg')
        params['quality'] = jpegQuality
        params['subsampling'] = jpegSubsampling
    elif encoding in {'TIFF', 'TILED'}:
        params['compression'] = {
            'none': 'raw',
            'lzw': 'tiff_lzw',
            'deflate': 'tiff_adobe_deflate',
        }.get(tiffCompression, tiffCompression)
    elif encoding == 'PNG':
        params['compress_level'] = 2
    output = io.BytesIO()
    try:
        image.save(output, encoding, **params)
    except Exception:
        retry = True
        if image.mode not in {'RGB', 'L'}:
            image = image.convert('RGB')
            try:
                image.convert('RGB').save(output, encoding, **params)
                retry = False
            except Exception:
                pass
        if retry:
            image.convert('1').save(output, encoding, **params)
    return ImageBytes(
        output.getvalue(),
        mimetype=f'image/{encoding.lower().replace("tiled", "tiff")}',
    )


def _encodeImage(
    image: Union[ImageBytes, PIL.Image.Image, bytes, np.ndarray],
    encoding: str = 'JPEG', jpegQuality: int = 95, jpegSubsampling: int = 0,
    format: Union[str, Tuple[str]] = (TILE_FORMAT_IMAGE, ),
    tiffCompression: str = 'raw', **kwargs,
) -> Tuple[Union[ImageBytes, PIL.Image.Image, bytes, np.ndarray], str]:
    """
    Convert a PIL or numpy image into raw output bytes, a numpy image, or a PIL
    Image, and a mime type.

    :param image: a PIL image.
    :param encoding: a valid PIL encoding (typically 'PNG' or 'JPEG').  Must
        also be in the TileOutputMimeTypes map.
    :param jpegQuality: the quality to use when encoding a JPEG.
    :param jpegSubsampling: the subsampling level to use when encoding a JPEG.
    :param format: the desired format or a tuple of allowed formats.  Formats
        are members of (TILE_FORMAT_PIL, TILE_FORMAT_NUMPY, TILE_FORMAT_IMAGE).
    :param tiffCompression: the compression format to use when encoding a TIFF.
    :returns:
        :imageData: the image data in the specified format and encoding.
        :imageFormatOrMimeType: the image mime type if the format is
            TILE_FORMAT_IMAGE, or the format of the image data if it is
            anything else.
    """
    if not isinstance(format, (tuple, set, list)):
        format = (format, )
    imageData = image
    imageFormatOrMimeType = TILE_FORMAT_PIL
    if TILE_FORMAT_NUMPY in format:
        imageData, _ = _imageToNumpy(image)
        imageFormatOrMimeType = TILE_FORMAT_NUMPY
    elif TILE_FORMAT_PIL in format:
        imageData = _imageToPIL(image)
        imageFormatOrMimeType = TILE_FORMAT_PIL
    elif TILE_FORMAT_IMAGE in format:
        if encoding not in TileOutputMimeTypes:
            raise ValueError('Invalid encoding "%s"' % encoding)
        imageFormatOrMimeType = TileOutputMimeTypes[encoding]
        image = _imageToPIL(image)
        imageData = _encodeImageBinary(
            image, encoding, jpegQuality, jpegSubsampling, tiffCompression)
    return imageData, imageFormatOrMimeType


def _imageToPIL(
        image: Union[ImageBytes, PIL.Image.Image, bytes, np.ndarray],
        setMode: Optional[str] = None) -> PIL.Image.Image:
    """
    Convert an image in PIL, numpy, or image file format to a PIL image.

    :param image: input image.
    :param setMode: if specified, the output image is converted to this mode.
    :returns: a PIL image.
    """
    if isinstance(image, np.ndarray):
        mode = 'L'
        if len(image.shape) == 3:
            # Fallback for hyperspectral data to just use the first three bands
            if image.shape[2] > 4:
                image = image[:, :, :3]
            mode = modesBySize[image.shape[2] - 1]
        if len(image.shape) == 3 and image.shape[2] == 1:
            image = np.resize(image, image.shape[:2])
        if image.dtype == np.uint32:
            image = np.floor_divide(image, 2 ** 24).astype(np.uint8)
        elif image.dtype == np.uint16:
            image = np.floor_divide(image, 256).astype(np.uint8)
        elif image.dtype == np.int8:
            image = (image.astype(float) + 128).astype(np.uint8)
        elif image.dtype == np.int16:
            image = np.floor_divide(image.astype(float) + 2 ** 15, 256).astype(np.uint8)
        elif image.dtype == np.int32:
            image = np.floor_divide(image.astype(float) + 2 ** 31, 2 ** 24).astype(np.uint8)
        # TODO: The scaling of float data needs to be identical across all
        # tiles of an image.  This means that we need a reference to the parent
        # tile source or some other way of regulating it.
        # elif image.dtype.kind == 'f':
        #     if numpy.max(image) > 1:
        #         maxl2 = math.ceil(math.log(numpy.max(image) + 1) / math.log(2))
        #         image = image / ((2 ** maxl2) - 1)
        #     image = (image * 255).astype(numpy.uint8)
        elif image.dtype != np.uint8:
            image = np.clip(np.nan_to_num(np.where(
                image is None, np.nan, image), nan=0), 0, 255).astype(np.uint8)
        image = PIL.Image.fromarray(image, mode)
    elif not isinstance(image, PIL.Image.Image):
        image = PIL.Image.open(io.BytesIO(image))
    if setMode is not None and image.mode != setMode:
        image = image.convert(setMode)
    return image


def _imageToNumpy(
        image: Union[ImageBytes, PIL.Image.Image, bytes, np.ndarray]) -> Tuple[np.ndarray, 'str']:
    """
    Convert an image in PIL, numpy, or image file format to a numpy array.  The
    output numpy array always has three dimensions.

    :param image: input image.
    :returns: a numpy array and a target PIL image mode.
    """
    if isinstance(image, np.ndarray) and len(image.shape) == 3 and 1 <= image.shape[2] <= 4:
        return image, modesBySize[image.shape[2] - 1]
    if (simplejpeg and isinstance(image, bytes) and image[:3] == b'\xff\xd8\xff' and
            b'\xff\xc0' in image[:1024]):
        idx = image.index(b'\xff\xc0')
        if image[idx + 9:idx + 10] in {b'\x01', b'\x03'}:
            try:
                image = simplejpeg.decode_jpeg(
                    image, colorspace='GRAY' if image[idx + 9:idx + 10] == b'\x01' else 'RGB')
            except Exception:
                pass
    if not isinstance(image, np.ndarray):
        if not isinstance(image, PIL.Image.Image):
            image = PIL.Image.open(io.BytesIO(image))
        if image.mode not in ('L', 'LA', 'RGB', 'RGBA'):
            image = image.convert('RGBA')
        mode = image.mode
        if not image.width or not image.height:
            image = np.zeros((image.height, image.width, len(mode)))
        else:
            image = np.asarray(image)
    else:
        if len(image.shape) == 3:
            mode = modesBySize[(image.shape[2] - 1) if image.shape[2] <= 4 else 3]
            return image, mode
        else:
            mode = 'L'
    if len(image.shape) == 2:
        image = np.resize(image, (image.shape[0], image.shape[1], 1))
    return image, mode


def _letterboxImage(image: PIL.Image.Image, width: int, height: int, fill: str) -> PIL.Image.Image:
    """
    Given a PIL image, width, height, and fill color, letterbox or pillarbox
    the image to make it the specified dimensions.  The image is never
    cropped.  The original image will be returned if no action is needed.

    :param image: the source image.
    :param width: the desired width in pixels.
    :param height: the desired height in pixels.
    :param fill: a fill color.
    """
    if ((image.width >= width and image.height >= height) or
            not fill or str(fill).lower() == 'none'):
        return image
    corner = False
    if fill.lower().startswith('corner:'):
        corner, fill = True, fill.split(':', 1)[1]
    color = PIL.ImageColor.getcolor(colormap.get(fill, fill), image.mode)
    width = max(width, image.width)
    height = max(height, image.height)
    result = PIL.Image.new(image.mode, (width, height), color)
    result.paste(image, (
        int((width - image.width) / 2) if not corner else 0,
        int((height - image.height) / 2) if not corner else 0))
    return result


def _vipsCast(image: Any, mustBe8Bit: bool = False) -> Any:
    """
    Cast a vips image to a format we want.

    :param image: a vips image
    :param mustBe9Bit: if True, then always cast to unsigned 8-bit.
    :returns: a vips image
    """
    import pyvips

    image = cast(pyvips.Image, image)
    formats = {
        pyvips.BandFormat.CHAR: (pyvips.BandFormat.UCHAR, 2**7, 1),
        pyvips.BandFormat.COMPLEX: (pyvips.BandFormat.USHORT, 0, 65535),
        pyvips.BandFormat.DOUBLE: (pyvips.BandFormat.USHORT, 0, 65535),
        pyvips.BandFormat.DPCOMPLEX: (pyvips.BandFormat.USHORT, 0, 65535),
        pyvips.BandFormat.FLOAT: (pyvips.BandFormat.USHORT, 0, 65535),
        pyvips.BandFormat.INT: (pyvips.BandFormat.USHORT, 2**31, 2**-16),
        pyvips.BandFormat.USHORT: (pyvips.BandFormat.UCHAR, 0, 2**-8),
        pyvips.BandFormat.SHORT: (pyvips.BandFormat.USHORT, 2**15, 1),
        pyvips.BandFormat.UINT: (pyvips.BandFormat.USHORT, 0, 2**-16),
    }
    if image.format not in formats or (image.format == pyvips.BandFormat.USHORT and not mustBe8Bit):
        return image
    target, offset, multiplier = formats[image.format]
    if image.format == pyvips.BandFormat.DOUBLE or image.format == pyvips.BandFormat.FLOAT:
        maxVal = image.max()
        # These thresholds are higher than 256 and 65536 because bicubic and
        # other interpolations can cause value spikes
        if maxVal >= 2 and maxVal < 2**9:
            multiplier = 256
        elif maxVal >= 256 and maxVal < 2**17:
            multiplier = 1
    if mustBe8Bit and target != pyvips.BandFormat.UCHAR:
        target = pyvips.BandFormat.UCHAR
        multiplier /= 256
    # logger.debug('Casting image from %r to %r', image.format, target)
    image = ((image.cast(pyvips.BandFormat.DOUBLE) + offset) * multiplier).cast(target)
    return image


def _rasterioParameters(
        defaultCompression: Optional[str] = None,
        eightbit: Optional[bool] = None, **kwargs) -> Dict[str, Any]:
    """
    Return a dictionary of creation option for the rasterio driver

    :param defaultCompression: if not specified, use this value.
    :param eightbit: True or False to indicate that the bit depth per sample
        is known.  None for unknown.

    Optional parameters that can be specified in kwargs:

    :param tileSize: the horizontal and vertical tile size.
    :param compression: one of 'jpeg', 'deflate' (zip), 'lzw', 'packbits',
        zstd', or 'none'.
    :param quality: a jpeg quality passed to gdal.  0 is small, 100 is high
        uality.  90 or above is recommended.
    :param level: compression level for zstd, 1-22 (default is 10).
    :param predictor: one of 'none', 'horizontal', or 'float' used for lzw and deflate.

    :returns: a dictionary of parameters.
    """
    # some default option and parameters
    options = {'blocksize': 256, 'compress': 'lzw', 'quality': 90}

    # the name of the predictor need to be strings so we convert here from set values to actual
    # required values (https://rasterio.readthedocs.io/en/latest/topics/image_options.html)
    predictor = {'none': 'NO', 'horizontal': 'STANDARD', 'float': 'FLOATING_POINT', 'yes': 'YES'}

    if eightbit is not None:
        options['predictor'] = 'yes' if eightbit else 'none'

    # add the values from kwargs to the options. Remove anything that isnot set.
    options.update({k: v for k, v in kwargs.items() if v not in (None, '')})

    # add the remaining options
    options.update(tiled=True, bigtiff='IF_SAFER')
    'predictor' not in options or options.update(predictor=predictor[str(options['predictor'])])

    return options


def _gdalParameters(
        defaultCompression: Optional[str] = None,
        eightbit: Optional[bool] = None, **kwargs) -> List[str]:
    """
    Return an array of gdal translation parameters.

    :param defaultCompression: if not specified, use this value.
    :param eightbit: True or False to indicate that the bit depth per sample is
        known.  None for unknown.

    Optional parameters that can be specified in kwargs:

    :param tileSize: the horizontal and vertical tile size.
    :param compression: one of 'jpeg', 'deflate' (zip), 'lzw', 'packbits',
        'zstd', or 'none'.
    :param quality: a jpeg quality passed to gdal.  0 is small, 100 is high
        quality.  90 or above is recommended.
    :param level: compression level for zstd, 1-22 (default is 10).
    :param predictor: one of 'none', 'horizontal', or 'float' used for lzw and
        deflate.
    :returns: a dictionary of parameters.
    """
    options = _rasterioParameters(
        defaultCompression=defaultCompression,
        eightbit=eightbit,
        **kwargs)
    # Remap for different names bewtwee rasterio/gdal
    options['tileSize'] = options.pop('blocksize')
    options['compression'] = options.pop('compress')
    cmdopt = ['-of', 'COG', '-co', 'BIGTIFF=%s' % options['bigtiff']]
    cmdopt += ['-co', 'BLOCKSIZE=%d' % options['tileSize']]
    cmdopt += ['-co', 'COMPRESS=%s' % options['compression'].upper()]
    cmdopt += ['-co', 'QUALITY=%s' % options['quality']]
    if 'predictor' in options:
        cmdopt += ['-co', 'PREDICTOR=%s' % options['predictor']]
    if 'level' in options:
        cmdopt += ['-co', 'LEVEL=%s' % options['level']]
    return cmdopt


def _vipsParameters(
        forTiled: bool = True, defaultCompression: Optional[str] = None,
        **kwargs) -> Dict[str, Any]:
    """
    Return a dictionary of vips conversion parameters.

    :param forTiled: True if this is for a tiled image.  False for an
        associated image.
    :param defaultCompression: if not specified, use this value.

    Optional parameters that can be specified in kwargs:

    :param tileSize: the horizontal and vertical tile size.
    :param compression: one of 'jpeg', 'deflate' (zip), 'lzw', 'packbits',
        'zstd', or 'none'.
    :param quality: a jpeg quality passed to vips.  0 is small, 100 is high
        quality.  90 or above is recommended.
    :param level: compression level for zstd, 1-22 (default is 10).
    :param predictor: one of 'none', 'horizontal', or 'float' used for lzw and
        deflate.
    :param shrinkMode: one of vips's VipsRegionShrink strings.
    :returns: a dictionary of parameters.
    """
    if not forTiled:
        convertParams = {
            'compression': defaultCompression or 'jpeg',
            'Q': 90,
            'predictor': 'horizontal',
            'tile': False,
        }
        if 'mime' in kwargs and kwargs.get('mime') != 'image/jpeg':
            convertParams['compression'] = 'lzw'
        return convertParams
    convertParams = {
        'tile': True,
        'tile_width': 256,
        'tile_height': 256,
        'pyramid': True,
        'bigtiff': True,
        'compression': defaultCompression or 'jpeg',
        'Q': 90,
        'predictor': 'horizontal',
    }
    # For lossless modes, make sure pixel values in lower resolutions are
    # values that exist in the upper resolutions.
    if convertParams['compression'] in {'none', 'lzw'}:
        convertParams['region_shrink'] = 'nearest'
    if kwargs.get('shrinkMode') and kwargs['shrinkMode'] != 'default':
        convertParams['region_shrink'] = kwargs['shrinkMode']
    for vkey, kwkeys in {
        'tile_width': {'tileSize'},
        'tile_height': {'tileSize'},
        'compression': {'compression', 'tiffCompression'},
        'Q': {'quality', 'jpegQuality'},
        'level': {'level'},
        'predictor': {'predictor'},
    }.items():
        for kwkey in kwkeys:
            if kwkey in kwargs and kwargs[kwkey] not in {None, ''}:
                convertParams[vkey] = kwargs[kwkey]
    if convertParams['compression'] == 'jp2k':
        convertParams['compression'] = 'none'
    if convertParams['compression'] == 'webp' and kwargs.get('quality') == 0:
        convertParams['lossless'] = True
        convertParams.pop('Q', None)
    if convertParams['predictor'] == 'yes':
        convertParams['predictor'] = 'horizontal'
    if convertParams['compression'] == 'jpeg':
        convertParams['rgbjpeg'] = True
    return convertParams


def etreeToDict(t: xml.etree.ElementTree.Element) -> Dict[str, Any]:
    """
    Convert an xml etree to a nested dictionary without schema names in the
    keys.  If you have an xml string, this can be converted to a dictionary via
    xml.etree.etreeToDict(ElementTree.fromstring(xml_string)).

    :param t: an etree.
    :returns: a python dictionary with the results.
    """
    # Remove schema
    tag = t.tag.split('}', 1)[1] if t.tag.startswith('{') else t.tag
    d: Dict[str, Any] = {tag: {}}
    children = list(t)
    if children:
        entries = defaultdict(list)
        for entry in map(etreeToDict, children):
            for k, v in entry.items():
                entries[k].append(v)
        d = {tag: {k: v[0] if len(v) == 1 else v
                   for k, v in entries.items()}}

    if t.attrib:
        d[tag].update({(k.split('}', 1)[1] if k.startswith('{') else k): v
                       for k, v in t.attrib.items()})
    text = (t.text or '').strip()
    if text and len(d[tag]):
        d[tag]['text'] = text
    elif text:
        d[tag] = text
    return d


def dictToEtree(
        d: Dict[str, Any],
        root: Optional[xml.etree.ElementTree.Element] = None) -> xml.etree.ElementTree.Element:
    """
    Convert a dictionary in the style produced by etreeToDict back to an etree.
    Make an xml string via xml.etree.ElementTree.tostring(dictToEtree(
    dictionary), encoding='utf8', method='xml').  Note that this function and
    etreeToDict are not perfect conversions; numerical values are quoted in
    xml.  Plain key-value pairs are ambiguous whether they should be attributes
    or text values.  Text fields are collected together.

    :param d: a dictionary.
    :prarm root: the root node to attach this dictionary to.
    :returns: an etree.
    """
    if root is None:
        if len(d) == 1:
            k, v = next(iter(d.items()))
            root = xml.etree.ElementTree.Element(k)
            dictToEtree(v, root)
            return root
        root = xml.etree.ElementTree.Element('root')
    for k, v in d.items():
        if isinstance(v, list):
            for l in v:
                elem = xml.etree.ElementTree.SubElement(root, k)
                dictToEtree(l, elem)
        elif isinstance(v, dict):
            elem = xml.etree.ElementTree.SubElement(root, k)
            dictToEtree(v, elem)
        else:
            if k == 'text':
                root.text = v
            else:
                root.set(k, v)
    return root


def nearPowerOfTwo(val1: float, val2: float, tolerance: float = 0.02) -> bool:
    """
    Check if two values are different by nearly a power of two.

    :param val1: the first value to check.
    :param val2: the second value to check.
    :param tolerance: the maximum difference in the log2 ratio's mantissa.
    :return: True if the values are nearly a power of two different from each
        other; false otherwise.
    """
    # If one or more of the values is zero or they have different signs, then
    # return False
    if val1 * val2 <= 0:
        return False
    log2ratio = math.log(float(val1) / float(val2)) / math.log(2)
    # Compare the mantissa of the ratio's log2 value.
    return abs(log2ratio - round(log2ratio)) < tolerance


def _arrayToPalette(palette: List[Union[str, float, Tuple[float, ...]]]) -> np.ndarray:
    """
    Given an array of color strings, tuples, or lists, return a numpy array.

    :param palette: an array of color strings, tuples, or lists.
    :returns: a numpy array of RGBA value on the scale of [0-255].
    """
    arr: List[Union[np.ndarray, Tuple[float, ...]]] = []
    for clr in palette:
        if isinstance(clr, (tuple, list)):
            arr.append(np.array((list(clr) + [1, 1, 1])[:4]) * 255)
        else:
            try:
                arr.append(PIL.ImageColor.getcolor(str(colormap.get(str(clr), clr)), 'RGBA'))
            except ValueError:
                try:
                    import matplotlib as mpl

                    arr.append(PIL.ImageColor.getcolor(mpl.colors.to_hex(cast(str, clr)), 'RGBA'))
                except (ImportError, ValueError):
                    raise ValueError('cannot be used as a color palette: %r.' % palette)
    return np.array(arr)


def getPaletteColors(value: Union[str, List[Union[str, float, Tuple[float, ...]]]]) -> np.ndarray:
    """
    Given a list or a name, return a list of colors in the form of a numpy
    array of RGBA.  If a list, each entry is a color name resolvable by either
    PIL.ImageColor.getcolor, by matplotlib.colors, or a 3 or 4 element list or
    tuple of RGB(A) values on a scale of 0-1.  If this is NOT a list, then, if
    it can be parsed as a color, it is treated as ['#000', <value>].  If that
    cannot be parsed, then it is assumed to be a named palette in palettable
    (such as viridis.Viridis_12) or a named palette in matplotlib (including
    plugins).

    :param value: Either a list, a single color name, or a palette name.  See
        above.
    :returns: a numpy array of RGBA value on the scale of [0-255].
    """
    palette = None
    if isinstance(value, (tuple, list)):
        palette = value
    if palette is None:
        try:
            PIL.ImageColor.getcolor(str(colormap.get(str(value), value)), 'RGBA')
            palette = ['#000', str(value)]
        except ValueError:
            pass
    if palette is None:
        import palettable

        try:
            palette = attrgetter(str(value))(palettable).hex_colors
        except AttributeError:
            pass
    if palette is None:
        try:
            import matplotlib as mpl

            if value in mpl.colors.get_named_colors_mapping():
                palette = ['#0000', mpl.colors.to_hex(str(value))]
            else:
                cmap = (mpl.colormaps.get_cmap(str(value)) if hasattr(getattr(
                    mpl, 'colormaps', None), 'get_cmap') else
                    mpl.cm.get_cmap(str(value)))
                palette = [mpl.colors.to_hex(cmap(i)) for i in range(cmap.N)]
        except (ImportError, ValueError, AttributeError):
            pass
    if palette is None:
        raise ValueError('cannot be used as a color palette.: %r.' % value)
    return _arrayToPalette(palette)


def isValidPalette(value: Union[str, List[Union[str, float, Tuple[float, ...]]]]) -> bool:
    """
    Check if a value can be used as a palette.

    :param value: Either a list, a single color name, or a palette name.  See
        getPaletteColors.
    :returns: a boolean; true if the value can be used as a palette.
    """
    try:
        getPaletteColors(value)
        return True
    except ValueError:
        return False


def _recursePalettablePalettes(
        module: types.ModuleType, palettes: Set[str],
        root: Optional[str] = None, depth: int = 0) -> None:
    """
    Walk the modules in palettable to find all of the available palettes.

    :param module: the current module.
    :param palettes: a set to add palette names to.
    :param root: a string of the parent modules.  None for palettable itself.
    :param depth: the depth of the walk.  Used to avoid needless recursion.
    """
    for key in dir(module):
        if not key.startswith('_'):
            attr = getattr(module, key)
            if isinstance(attr, types.ModuleType) and depth < 3:
                _recursePalettablePalettes(
                    attr, palettes, root + '.' + key if root else key, depth + 1)
            elif root and isinstance(getattr(attr, 'hex_colors', None), list):
                palettes.add(root + '.' + key)


def getAvailableNamedPalettes(includeColors: bool = True, reduced: bool = False) -> List[str]:
    """
    Get a list of all named palettes that can be used with getPaletteColors.

    :param includeColors: if True, include named colors.  If False, only
        include actual palettes.
    :param reduced: if True, exclude reversed palettes and palettes with
        fewer colors where a palette with the same basic name exists with more
        colors.
    :returns: a list of names.
    """
    import palettable

    palettes = set()
    if includeColors:
        palettes |= set(PIL.ImageColor.colormap.keys())
        palettes |= set(colormap.keys())
    _recursePalettablePalettes(palettable, palettes)
    try:
        import matplotlib as mpl

        if includeColors:
            palettes |= set(mpl.colors.get_named_colors_mapping())
        # matplotlib has made the colormap list more public in recent versions
        mplcm = (mpl.colormaps if hasattr(mpl, 'colormaps')
                 else mpl.cm._cmap_registry)  # type: ignore
        for key in mplcm:
            if isValidPalette(key):
                palettes.add(key)
    except ImportError:
        pass
    if reduced:
        palettes = {
            key for key in palettes
            if not key.endswith('_r') and (
                '_' not in key or
                not key.rsplit('_', 1)[-1].isdigit() or
                (key.rsplit('_', 1)[0] + '_' + str(int(
                    key.rsplit('_', 1)[-1]) + 1)) not in palettes)}
    return sorted(palettes)


def fullAlphaValue(arr: Union[np.ndarray, npt.DTypeLike]) -> int:
    """
    Given a numpy array, return the value that should be used for a fully
    opaque alpha channel.  For uint variants, this is the max value.

    :param arr: a numpy array.
    :returns: the value for the alpha channel.
    """
    dtype = arr.dtype if isinstance(arr, np.ndarray) else arr
    if not hasattr(dtype, 'kind'):
        dtype = np.dtype(dtype)
    if cast(np.dtype, dtype).kind == 'u':
        return np.iinfo(dtype).max
    return 1


def _makeSameChannelDepth(arr1: np.ndarray, arr2: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Given two numpy arrays that are either two or three dimensions, make the
    third dimension the same for both of them.  Specifically, if there are two
    dimensions, first convert to three dimensions with a single final value.
    Otherwise, the dimensions are assumed to be channels of L, LA, RGB, RGBA,
    or <all colors>.  If L is needed to change to RGB, it is repeated (LLL).
    Missing A channels are filled with 255, 65535, or 1 depending on if the
    dtype is uint8, uint16, or something else.

    :param arr1: one array to compare.
    :param arr2: a second array to compare.
    :returns: the two arrays, possibly modified.
    """
    arrays = {
        'arr1': arr1,
        'arr2': arr2,
    }
    # Make sure we have 3 dimensional arrays
    for key, arr in arrays.items():
        if len(arr.shape) == 2:
            arrays[key] = np.resize(arr, (arr.shape[0], arr.shape[1], 1))
    # If any array is RGB, make sure all arrays are RGB.
    for key, arr in arrays.items():
        other = arrays['arr1' if key == 'arr2' else 'arr2']
        if arr.shape[2] < 3 and other.shape[2] >= 3:  # type: ignore[misc]
            newarr = np.ones(
                (arr.shape[0], arr.shape[1], arr.shape[2] + 2),  # type: ignore[misc]
                dtype=arr.dtype)
            newarr[:, :, 0:1] = arr[:, :, 0:1]
            newarr[:, :, 1:2] = arr[:, :, 0:1]
            newarr[:, :, 2:3] = arr[:, :, 0:1]
            if arr.shape[2] == 2:  # type: ignore[misc]
                newarr[:, :, 3:4] = arr[:, :, 1:2]
            arrays[key] = newarr
    # If only one array has an A channel, make sure all arrays have an A
    # channel
    for key, arr in arrays.items():
        other = arrays['arr1' if key == 'arr2' else 'arr2']
        if arr.shape[2] < other.shape[2]:  # type: ignore[misc]
            arrays[key] = np.pad(
                arr,
                ((0, 0), (0, 0), (0, other.shape[2] - arr.shape[2])),  # type: ignore[misc]
                constant_values=fullAlphaValue(arr))
    return arrays['arr1'], arrays['arr2']


def _addSubimageToImage(
        image: Optional[np.ndarray], subimage: np.ndarray, x: int, y: int,
        width: int, height: int) -> np.ndarray:
    """
    Add a subimage to a larger image as numpy arrays.

    :param image: the output image record.  None for not created yet.
    :param subimage: a numpy array with the sub-image to add.
    :param x: the location of the upper left point of the sub-image within
        the output image.
    :param y: the location of the upper left point of the sub-image within
        the output image.
    :param width: the output image size.
    :param height: the output image size.
    :returns: the output image record.
    """
    if image is None:
        if (x, y, width, height) == (0, 0, subimage.shape[1], subimage.shape[0]):
            return subimage
        image = np.empty(
            (height, width, subimage.shape[2]),  # type: ignore[misc]
            dtype=subimage.dtype)
    elif len(image.shape) != len(subimage.shape) or image.shape[-1] != subimage.shape[-1]:
        image, subimage = _makeSameChannelDepth(image, subimage)
    if subimage.shape[-1] in {2, 4}:
        mask = (subimage[:, :, -1] > 0)[:, :, np.newaxis]
        image[y:y + subimage.shape[0], x:x + subimage.shape[1]] = np.where(
            mask, subimage, image[y:y + subimage.shape[0], x:x + subimage.shape[1]])
    else:
        image[y:y + subimage.shape[0], x:x + subimage.shape[1]] = subimage
    return image


def _vipsAddAlphaBand(vimg: Any, otherImages: List[Any]) -> Any:
    """
    Add an alpha band to a vips image.  The alpha value is either 1, 255, or
    65535 depending on the max value in the image and any other images passed
    for reference.

    :param vimg: the vips image to modify.
    :param otherImages: a list of other vips images to use for determining the
        alpha value.
    :returns: the original image with an alpha band.
    """
    maxValue = vimg.max()
    for img in otherImages:
        maxValue = max(maxValue, img.max())
    alpha = 1
    if maxValue >= 2 and maxValue < 2**9:
        alpha = 255
    elif maxValue >= 2**8 and maxValue < 2**17:
        alpha = 65535
    return vimg.bandjoin(alpha)


def _addRegionTileToTiled(
        image: Optional[Dict[str, Any]], subimage: np.ndarray, x: int, y: int,
        width: int, height: int, tile: Dict[str, Any], **kwargs) -> Dict[str, Any]:
    """
    Add a subtile to a vips image.

    :param image: an object with information on the output.
    :param subimage: a numpy array with the sub-image to add.
    :param x: the location of the upper left point of the sub-image within the
        output image.
    :param y: the location of the upper left point of the sub-image within the
        output image.
    :param width: the output image size.
    :param height: the output image size.
    :param tile: the original tile record with the current scale, etc.
    :returns: the output object.
    """
    import pyvips

    if subimage.dtype.char not in dtypeToGValue:
        subimage = subimage.astype('d')
    vimgMem = pyvips.Image.new_from_memory(
        np.ascontiguousarray(subimage).data,
        subimage.shape[1], subimage.shape[0], subimage.shape[2],  # type: ignore[misc]
        dtypeToGValue[subimage.dtype.char])
    vimg = pyvips.Image.new_temp_file('%s.v')
    vimgMem.write(vimg)
    if image is None:
        image = {
            'width': width,
            'height': height,
            'mm_x': tile.get('mm_x') if tile else None,
            'mm_y': tile.get('mm_y') if tile else None,
            'magnification': tile.get('magnification') if tile else None,
            'channels': subimage.shape[2],  # type: ignore[misc]
            'strips': {},
        }
    if y not in image['strips']:
        image['strips'][y] = vimg
        if not x:
            return image
    if image['strips'][y].bands + 1 == vimg.bands:
        image['strips'][y] = _vipsAddAlphaBand(image['strips'][y], vimg)
    elif vimg.bands + 1 == image['strips'][y].bands:
        vimg = _vipsAddAlphaBand(vimg, image['strips'][y])
    image['strips'][y] = image['strips'][y].insert(vimg, x, 0, expand=True)
    return image


def _calculateWidthHeight(
        width: Optional[float], height: Optional[float], regionWidth: float,
        regionHeight: float) -> Tuple[int, int, float]:
    """
    Given a source width and height and a maximum destination width and/or
    height, calculate a destination width and height that preserves the aspect
    ratio of the source.

    :param width: the destination width.  None to only use height.
    :param height: the destination height.  None to only use width.
    :param regionWidth: the width of the source data.
    :param regionHeight: the height of the source data.
    :returns: the width and height that is no larger than that specified and
        preserves aspect ratio, and the scaling factor used for the conversion.
    """
    if regionWidth == 0 or regionHeight == 0:
        return 0, 0, 1
    # Constrain the maximum size if both width and height weren't
    # specified, in case the image is very short or very narrow.
    if height and not width:
        width = height * 16
    if width and not height:
        height = width * 16
    scaledWidth = max(1, int(regionWidth * cast(float, height) / regionHeight))
    scaledHeight = max(1, int(regionHeight * cast(float, width) / regionWidth))
    if scaledWidth == width or (
            cast(float, width) * regionHeight > cast(float, height) * regionWidth and
            not scaledHeight == height):
        scale = float(regionHeight) / cast(float, height)
        width = scaledWidth
    else:
        scale = float(regionWidth) / cast(float, width)
        height = scaledHeight
    return int(cast(float, width)), int(cast(float, height)), scale


def _computeFramesPerTexture(
        opts: Dict[str, Any], numFrames: int, sizeX: int,
        sizeY: int) -> Tuple[int, int, int, int, int]:
    """
    Compute the number of frames for each tile_frames texture.

    :param opts: the options dictionary from getTileFramesQuadInfo.
    :param numFrames: the number of frames that need to be included.
    :param sizeX: the size of one frame of the image.
    :param sizeY: the size of one frame of the image.
    :returns:
        :fw: the width of an individual frame in the texture.
        :fh: the height of an individual frame in the texture.
        :fhorz: the number of frames across the texture.
        :fperframe: the number of frames per texture.  The last texture may
            have fewer frames.
        :textures: the number of textures to be used.  This many calls will
            need to be made to tileFrames.
    """
    # defining fw, fh, fhorz, fvert, fperframe
    alignment = opts['alignment'] or 16
    texSize = opts['maxTextureSize']
    textures = opts['maxTextures'] or 1
    while texSize ** 2 > opts['maxTotalTexturePixels']:
        texSize //= 2
    while textures > 1 and texSize ** 2 * textures > opts['maxTotalTexturePixels']:
        textures -= 1
    # Iterate in case we can reduce the number of textures or the texture size
    while True:
        f = int(math.ceil(numFrames / textures))  # frames per texture
        if opts['frameGroup'] > 1:
            fg = int(math.ceil(f / opts['frameGroup'])) * opts['frameGroup']
            if fg / f <= opts['frameGroupFactor']:
                f = fg
        texScale2 = texSize ** 2 / f / sizeX / sizeY
        # frames across the texture
        fhorz = int(math.ceil(texSize / (math.ceil(
            sizeX * texScale2 ** 0.5 / alignment) * alignment)))
        fvert = int(math.ceil(texSize / (math.ceil(
            sizeY * texScale2 ** 0.5 / alignment) * alignment)))
        # tile sizes
        fw = int(math.floor(texSize / fhorz / alignment)) * alignment
        fvert = int(max(math.ceil(f / (texSize // fw)), fvert))
        fh = int(math.floor(texSize / fvert / alignment) * alignment)
        if opts['maxFrameSize']:
            maxFrameSize = opts['maxFrameSize'] // alignment * alignment
            fw = min(fw, maxFrameSize)
            fh = min(fh, maxFrameSize)
        if fw > sizeX:
            fw = int(math.ceil(sizeX / alignment) * alignment)
        if fh > sizeY:
            fh = int(math.ceil(sizeY / alignment) * alignment)
        # shrink one dimension to account for aspect ratio
        fw = int(min(math.ceil(fh * sizeX / sizeY / alignment) * alignment, fw))
        fh = int(min(math.ceil(fw * sizeY / sizeX / alignment) * alignment, fh))
        # recompute frames across the texture
        fhorz = texSize // fw
        fvert = int(min(texSize // fh, math.ceil(numFrames / fhorz)))
        fperframe = fhorz * fvert
        if textures > 1 and opts['frameGroup'] > 1:
            fperframe = int(fperframe // opts['frameGroup'] * opts['frameGroup'])
            if textures * fperframe < numFrames and fhorz * fvert * textures >= numFrames:
                fperframe = fhorz * fvert
        # check if we are not using all textures or are using less than a
        # quarter of one texture.  If not, stop, if so, reduce and recalculate
        if textures > 1 and numFrames <= fperframe * (textures - 1):
            textures -= 1
            continue
        if fhorz >= 2 and math.ceil(f / (fhorz // 2)) * fh <= texSize / 2:
            texSize //= 2
            continue
        return fw, fh, fhorz, fperframe, textures


def getTileFramesQuadInfo(
        metadata: Dict[str, Any], options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Compute what tile_frames need to be requested for a particular condition.

    Options is a dictionary of:
        :format: The compression and format for the texture.  Defaults to
            {'encoding': 'JPEG', 'jpegQuality': 85, 'jpegSubsampling': 1}.
        :query: Additional query options to add to the tile source, such as
            style.
        :frameBase: (default 0) Starting frame number used.  c/z/xy/z to step
            through that index length (0 to 1 less than the value), which is
            probably only useful for cache reporting or scheduling.
        :frameStride: (default 1) Only use every ``frameStride`` frame of the
            image.  c/z/xy/z to use that axis length.
        :frameGroup: (default 1) If above 1 and multiple textures are used, each
            texture will have an even multiple of the group size number of
            frames.  This helps control where texture loading transitions
            occur.  c/z/xy/z to use that axis length.
        :frameGroupFactor: (default 4) If ``frameGroup`` would reduce the size
            of the tile images beyond this factor, don't use it.
        :frameGroupStride: (default 1) If ``frameGroup`` is above 1 and multiple
            textures are used, then the frames are reordered based on this
            stride value.  "auto" to use frameGroup / frameStride if that
            value is an integer.
        :maxTextureSize: Limit the maximum texture size to a square of this
            size.
        :maxTextures: (default 1) If more than one, allow multiple textures to
            increase the size of the individual frames.  The number of textures
            will be capped by ``maxTotalTexturePixels`` as well as this number.
        :maxTotalTexturePixels: (default 1073741824) Limit the maximum texture
            size and maximum number of textures so that the combined set does
            not exceed this number of pixels.
        :alignment: (default 16) Individual frames are buffered to an alignment
            of this maxy pixels.  If JPEG compression is used, this should
            be 8 for monochrome images or jpegs without subsampling, or 16 for
            jpegs with moderate subsampling to avoid compression artifacts from
            leaking between frames.
        :maxFrameSize: If set, limit the maximum width and height of an
            individual frame to this value.


    :param metadata: the tile source metadata.  Needs to contain sizeX, sizeY,
        tileWidth, tileHeight, and a list of frames.
    :param options: dictionary of options, as described above.
    :returns: a dictionary of values to use for making calls to tile_frames.
    """
    defaultOptions = {
        'format': {
            'encoding': 'JPEG',
            'jpegQuality': 85,
            'jpegSubsampling': 1,
        },
        'query': {},
        'frameBase': 0,
        'frameStride': 1,
        'frameGroup': 1,
        'frameGroupFactor': 4,
        'frameGroupStride': 1,
        'maxTextureSize': 8192,
        'maxTextures': 1,
        'maxTotalTexturePixels': 1024 * 1024 * 1024,
        'alignment': 16,
        'maxFrameSize': None,
    }
    opts = defaultOptions.copy()
    opts.update(options or {})

    opts['frameStride'] = (
        int(cast(Union[str, int], opts['frameStride'])) if str(opts['frameStride']).isdigit() else
        metadata.get('IndexRange', {}).get('Index' + str(opts['frameStride']).upper(), 1))
    opts['frameGroup'] = (
        int(cast(Union[str, int], opts['frameGroup'])) if str(opts['frameGroup']).isdigit() else
        metadata.get('IndexRange', {}).get('Index' + str(opts['frameGroup']).upper(), 1))
    opts['frameGroupStride'] = (
        int(cast(Union[str, int], opts['frameGroupStride']))
        if opts['frameGroupStride'] != 'auto' else
        max(1, cast(int, opts['frameGroup']) // cast(int, opts['frameStride'])))
    if str(opts['frameBase']).isdigit():
        opts['frameBase'] = int(cast(Union[str, int], opts['frameBase']))
    else:
        statusidx = {
            'metadata': metadata,
            'options': opts,
            'src': [],
        }
        for val in range(metadata.get(
                'IndexRange', {}).get('Index' + str(opts['frameBase']).upper(), 1)):
            opts['frameBase'] = val
            result = getTileFramesQuadInfo(metadata, opts)
            cast(List[Any], statusidx['src']).extend(cast(List[Any], result['src']))
        return statusidx
    sizeX, sizeY = metadata['sizeX'], metadata['sizeY']
    numFrames = len(metadata.get('frames', [])) or 1
    frames = []
    for fds in range(cast(int, opts['frameGroupStride'])):
        frames.extend(list(range(
            cast(int, opts['frameBase']) + fds * cast(int, opts['frameStride']),
            numFrames,
            cast(int, opts['frameStride']) * cast(int, opts['frameGroupStride']))))
    numFrames = len(frames)
    # check if numFrames zero and return early?
    fw, fh, fhorz, fperframe, textures = _computeFramesPerTexture(
        opts, numFrames, sizeX, sizeY)
    # used area of each tile
    usedw = int(math.floor(sizeX / max(sizeX / fw, sizeY / fh)))
    usedh = int(math.floor(sizeY / max(sizeX / fw, sizeY / fh)))
    # get the set of texture images
    status: Dict[str, Any] = {
        'metadata': metadata,
        'options': opts,
        'src': [],
        'quads': [],
        'quadsToIdx': [],
        'frames': frames,
        'framesToIdx': {},
    }
    if metadata.get('tileWidth') and metadata.get('tileHeight'):
        # report that tiles below this level are not needed
        status['minLevel'] = int(math.ceil(math.log(min(
            usedw / metadata['tileWidth'], usedh / metadata['tileHeight'])) / math.log(2)))
    status['framesToIdx'] = {frame: idx for idx, frame in enumerate(frames)}
    for idx in range(textures):
        frameList = frames[idx * fperframe: (idx + 1) * fperframe]
        tfparams: Dict[str, Any] = {
            'framesAcross': fhorz,
            'width': fw,
            'height': fh,
            'fill': 'corner:black',
            'exact': False,
        }
        if len(frameList) != len(metadata.get('frames', [])):
            tfparams['frameList'] = frameList
        tfparams.update(cast(Dict[str, Any], opts['format']))
        tfparams.update(cast(Dict[str, Any], opts['query']))
        status['src'].append(tfparams)
        f = len(frameList)
        ivert = int(math.ceil(f / fhorz))
        ihorz = int(min(f, fhorz))
        for fidx in range(f):
            quad = {
                # z = -1 to place under other tile layers
                'ul': {'x': 0, 'y': 0, 'z': -1},
                # y coordinate is inverted
                'lr': {'x': sizeX, 'y': -sizeY, 'z': -1},
                'crop': {
                    'x': sizeX,
                    'y': sizeY,
                    'left': (fidx % ihorz) * fw,
                    'top': (ivert - (fidx // ihorz)) * fh - usedh,
                    'right': (fidx % ihorz) * fw + usedw,
                    'bottom': (ivert - (fidx // ihorz)) * fh,
                },
            }
            status['quads'].append(quad)
            status['quadsToIdx'].append(idx)
    return status


_recentThresholds: Dict[Tuple, Any] = {}


def histogramThreshold(histogram: Dict[str, Any], threshold: float, fromMax: bool = False) -> float:
    """
    Given a histogram and a threshold on a scale of [0, 1], return the bin
    edge that excludes no more than the specified threshold amount of values.
    For instance, a threshold of 0.02 would exclude at most 2% of the values.

    :param histogram: a histogram record for a specific channel.
    :param threshold: a value from 0 to 1.
    :param fromMax: if False, return values excluding the low end of the
        histogram; if True, return values from excluding the high end of the
        histogram.
    :returns: the value the excludes no more than the threshold from the
        specified end.
    """
    key = (id(histogram), threshold, fromMax)
    if key in _recentThresholds:
        return _recentThresholds[key]
    hist = histogram['hist']
    edges = histogram['bin_edges']
    samples = histogram['samples'] if not histogram.get('density') else 1
    if fromMax:
        hist = hist[::-1]
        edges = edges[::-1]
    tally = 0
    result = edges[-1]
    for idx in range(len(hist)):
        if tally + hist[idx] > threshold * samples:
            if not idx:
                result = histogram['min' if not fromMax else 'max']
            else:
                result = edges[idx]
            break
        tally += hist[idx]
    if len(_recentThresholds) > 100:
        _recentThresholds.clear()
    _recentThresholds[key] = result
    return result


def addPILFormatsToOutputOptions() -> None:
    """
    Check PIL for available formats that be saved and add them to the lists of
    of available formats.
    """
    # Call this to actual register the extensions
    PIL.Image.registered_extensions()
    for key, value in PIL.Image.MIME.items():
        # We don't support these formats; ICNS and ICO have fixed sizes; PALM
        # and PDF can't be read back by PIL without extensions
        if key in {'ICNS', 'ICO', 'PALM', 'PDF'}:
            continue
        if key not in TileOutputMimeTypes and key in PIL.Image.SAVE:
            TileOutputMimeTypes[key] = value
    for key, value in PIL.Image.registered_extensions().items():
        key = key.lstrip('.')
        if (key not in TileOutputMimeTypes and value in TileOutputMimeTypes and
                key not in TileOutputPILFormat):
            TileOutputPILFormat[key] = value


addPILFormatsToOutputOptions()
