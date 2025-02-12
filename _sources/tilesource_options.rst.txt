Tile Source Options
===================

Each tile source can have custom options that affect how tiles are generated from that tile source.  All tile sources have a basic set of options:

Format
------

Python tile functions can return tile data as images, numpy arrays, or PIL Image objects.  The ``format`` parameter is one of the ``TILE_FORMAT_*`` constants. Refer to `constants.py <format_options_>`_ to view the format options.

Encoding
--------

The ``encoding`` parameter only affects output when ``format`` is ``TILE_FORMAT_IMAGE``.

The ``encoding`` parameter can be one of ``JPEG``, ``PNG``, ``TIFF``, ``JFIF``, or ``TILED``.  When the tile is output as an image, this is the preferred format.  Note that ``JFIF`` is a specific variant of ``JPEG`` that will always use either the Y or YCbCr color space as well as constraining other options.  ``TILED`` will output a tiled tiff file; this is slower than ``TIFF`` but can support images of arbitrary size.

Additional encoding options are available based on the PIL.Image registered encoders. Refer to the `PIL documentation <pil_encoders_>`_ for supported formats.

Associated with ``encoding``, some image formats have additional parameters.

- ``JPEG`` and ``JFIF`` can specify ``jpegQuality``, a number from 0 to 100 where 0 is small and 100 is higher-quality, and ``jpegSubsampling``, where 0 is full chrominance data, 1 is half-resolution chrominance, and 2 is quarter-resolution chrominance.

- ``TIFF`` can specify ``tiffCompression``, which is one of the ``libtiff_ctypes.COMPRESSION*`` options found `here <libtiff_compression_>`_.

Edges
-----

When a tile is requested at the right or bottom edge of the image, the tile could extend past the boundary of the image.  If the image is not an even multiple of the tile size, the ``edge`` parameter determines how the tile is generated.  A value of ``None`` (default) or ``False`` will generate a standard sized tile where the area outside of the image space could have pixels of any color.  An ``edge`` value of ``'crop'`` or ``True`` will return a tile that is smaller than the standard size.  An ``edge`` value in the form of a hexadecimal encoded 8-bit-per-channel color (e.g., ``#rrggbb``) will ensure that the area outside of the image space is all that color.

Style
-----

Often tiles are desired as 8-bit-per-sample images.  However, if the tile source is more than 8 bits per sample or has more than 3 channels, some data will be lost.  Similarly, if the data is returned as a numpy array, the range of values returned can vary by tile source.  The ``style`` parameter can remap samples values and determine how channels are composited.

If ``style`` is ``{}``, the default style for the file is used.  If it is not specified or None, it will be the default style for non-geospatial tile sources and a default style consisting of the visible bands for geospatial sources.  Otherwise, this is a json-encoded string that contains an object with a key of ``bands`` consisting of an array of band definitions.  If only one band is needed, a json-encoded string of just the band definition can be used.

A band definition is an object which can contain the following keys:

- ``band``: if -1 or None, the greyscale value is used.  Otherwise, a 1-based numerical index into the channels of the image or a string that matches the interpretation of the band ('red', 'green', 'blue', 'gray', 'alpha').  Note that 'gray' on an RGB or RGBA image will use the green band.

- ``frame``: if specified, override the frame parameter used in the tile query for this band.  Note that it is more efficient to have at least one band not specify a frame parameter or use the same value as the basic query.  Defaults to the frame value of the core query.

- ``framedelta``: if specified, and ``frame`` is not specified, override the frame parameter used in the tile query for this band by adding the value to the current frame number.  If many different frames are being requested, all with the same ``framedelta``, this is more efficient than varying the ``frame`` within the style.

- ``min``: the value to map to the first palette value.  Defaults to 0.  'auto' to use 0 if the reported minimum and maximum of the band are between [0, 255] or use the reported minimum otherwise.  'min' or 'max' to always uses the reported minimum or maximum.  'min:<threshold>' and 'max:<threshold>' pick a value that excludes a threshold amount from the histogram; for instance, 'min:0.02' would exclude at most the dimmest 2% of values by using an appropriate value for the minimum based on a computed histogram with some default binning options.  'auto:<threshold>' works like auto, though it applies the threshold if the reported minimum would otherwise be used.  'full' is the same as specifying 0.

- ``max``: the value to map to the last palette value.  Defaults to 255.  'auto' to use 255 if the reported minimum and maximum of the band are between [0, 255] or use the reported maximum otherwise.  'min' or 'max' to always uses the reported minimum or maximum.  'min:<threshold>' and 'max:<threshold>' pick a value that excludes a threshold amount from the histogram; for instance, 'max:0.02' would exclude at most the brightest 2% of values by using an appropriate value for the maximum based on a computed histogram with some default binning options.  'auto:<threshold>' works like auto, though it applies the threshold if the reported maximum would otherwise be used.  'full' uses a value based on the data type of the band.  This will be 1 for a float data type, 255 for a uint8 data type, and 65535 for a uint16 data type.

- ``palette``: This is a single color string, a palette name, or a list of two or more colors. The values between min and max are interpolated using a piecewise linear algorithm or a nearest value algorithm (depending on the ``scheme``) to map to the specified palette values.  It can be specified in a variety of ways:

  - a list of two or more color values, where the color values are css-style strings (e.g., of the form #RRGGBB, #RRGGBBAA, #RGB, #RGBA, or a css ``rgb``, ``rgba``, ``hsl``, or ``hsv`` string, or a css color name), or, if matplotlib is available, a matplotlib color name, or a list or tuple of RGB(A) values on a scale of [0-1].

  - a single string that is a color string as above.  This is functionally a two-color palette with the first color as solid black (``#000``), and the second color the specified value

  - a named color palette from the palettable library (e.g., ``matplotlib.Plasma_6``) or, if available, from the matplotlib library or one of its plugins (e.g., ``viridis``).

- ``scheme``: This is either ``linear`` (the default) or ``discrete``.  If a palette is specified, ``linear`` uses a piecewise linear interpolation, and ``discrete`` uses exact colors from the palette with the range of the data mapped into the specified number of colors (e.g., a palette with two colors will split exactly halfway between the min and max values).

- ``nodata``: the value to use for missing data.  null or unset to not use a nodata value.

- ``composite``: either 'lighten' or 'multiply'.  Defaults to 'lighten' for all except the alpha band. Read more about blend modes and see examples `here <blend_modes_>`_.

- ``clamp``: either True to clamp (also called clip or crop) values outside of the [min, max] to the ends of the palette or False to make outside values transparent.

- ``dtype``: if specified, cast the intermediate results to this data type.  Only the first such value is used, and this can be specified as a base key if ``bands`` is specified.  Normally, if a style is applied, the intermediate data is a numpy float array with values from [0,255].  If this is ``uint16``, the results are multiplied by 65535 / 255 and cast to that dtype.  If ``float``, the results are divided by 255.  If ``source``, this uses the dtype of the source image.

- ``axis``: if specified, keep on the specified axis (channel) of the intermediate numpy array.  This is typically between 0 and 3 for the red, green, blue, and alpha channels.  Only the first such value is used, and this can be specified as a base key if ``bands`` is specified.

- ``icc``: by default, sources that expose ICC color profiles (PIL, OpenJPEG, OpenSlide, OMETiff, TIFF, TiffFile) will apply those profiles to the image data, converting the results to the sRGB profile.  To use the raw image data without ICC profile adjustments, specify an ``icc`` value of ``false``.  If the entire style is ``{"icc": false}``, the results will be the same as the default bands with only the adjustment being skipped.  Similarly, if the entire style is ``{"icc": true}``, this is the same as the default style with where the adjustment is applied.  Besides a boolean, this may also be a string with one of the intents defined by the PIL.ImageCms.Intents enum.  ``true`` is the same as ``perceptual``.   Note that not all tile sources expose ICC color profile information, even if the base file format contains it.

- ``function``: if specified, call a function to modify the resulting image.  This can be specified as a base key and as a band key.  Style functions can be called at multiple stages in the styling pipeline:

  - ``pre`` stage: this passes the original tile image to the function before any band data is applied.

  - ``preband`` stage: this passes the band image (often the original tile image if a different frame is not specified) to the function before any scaling.

  - ``band`` stage: this passes the band image after scaling (via ``min`` and ``max``) and generating a ``nodata`` mask.

  - ``postband`` stage: this passes the in-progress output image after the band has been applied to it.

  - ``main`` stage: this passes the in-progress output image after all bands have been applied but before it is adjusted for ``dtype``.

  - ``post`` stage: this passes the output image just before the style function returns.

  The function parameter can be a single function or a list of functions.  Items in a list of functions can, themselves, be lists of functions.  A single function can be an object or a string.  If a string, this is shorthand for ``{"name": <function>}``.  The function object contains (all but ``name`` are optional):

  - ``name``: The name of a Python module and function that is installed in the same environment as large_image.  For instance, ``large_image.tilesource.stylefuncs.maskPixelValues`` will use the function ``maskPixelValues`` in the ``large_image.tilesource.stylefuncs`` module.  The function must be a Python function that takes a numpy array as the first parameter (the image) and has named parameters or kwargs for any passed parameters and possibly the style context.

  - ``parameters``: A dictionary of parameters to pass to the function.

  - ``stage``: A string for a single matching stage or a list of stages that this function should be applied to.  This defaults to ``["band", "main"]``.

  - ``context``: If this is present and not falsy, pass the style context to the function.  If this is ``true``, the style context is passed as the ``context`` parameter.  Otherwise, this is the name of the parameter that is passed to the function.  The style context is a namespace that contains (depending on stage), a variety of information:

    - ``image``: the source image as a numpy array.

    - ``originalStyle``: the style object from the tile source.

    - ``style``: the normalized style object (always an object with a ``bands`` key containing a list of bands).

    - ``x``, ``y``, ``z``, and ``frame``: the tile position in the source.

    - ``dtype``, ``axis``: the value specified from the style for these parameters.

    - ``output``: the output image as a numpy array.

    - ``stage``: the current stage of style processing.

    - ``styleIndex``: if in a band stage, the 0-based index within the style bands.

    - ``band``: the band numpy image in a band stage.

    - ``mask``: a mask numpy image to use when applying the band.  None for no mask (this is the equivalent of the mask being all True).

    - ``palette``: the normalized palette for a band.

    - ``palettebase``: a numpy linear interpolation array for non-discrete palettes.
    - ``discrete``: True if the scheme is discrete.

    - ``nodata``: the nodata value for the band or None.

    - ``min``, ``max``: the resolved numerical minimum and maximum value for the band.

    - ``clamp``: the clamp value for the band.

Note that some tile sources add additional options to the ``style`` parameter.

Examples
++++++++

Swap the red and green channels of a three color image
______________________________________________________

.. code-block::

  style = {"bands": [
    {"band": 1, "palette": ["#000", "#0f0"]},
    {"band": 2, "palette": ["#000", "#f00"]},
    {"band": 3, "palette": ["#000", "#00f"]}
  ]}

Apply a gamma correction to the image
_____________________________________

This used a precomputed sixteen entry greyscale palette, computed as ``(value / 255) ** gamma * 255``, where ``value`` is one of [0, 17, 34, 51, 68, 85, 102, 119, 136, 153, 170, 187, 204, 221, 238, 255] and gamma is ``0.5``.

.. code-block::

  style = {"palette": [
    "#000000", "#414141", "#5D5D5D", "#727272",
    "#838383", "#939393", "#A1A1A1", "#AEAEAE",
    "#BABABA", "#C5C5C5", "#D0D0D0", "#DADADA",
    "#E4E4E4", "#EDEDED", "#F6F6F6", "#FFFFFF"
  ]}

Composite several frames with framedelta
________________________________________

.. code-block::

  style = {
    "bands": [
      {"framedelta": 0, "palette": "#0000FF"}
      {"framedelta": 1, "palette": "#00FF00"}
      {"framedelta": 2, "palette": "#FF0000"}
    ],
    "composite": "multiply"
  }

Fill missing data and apply categorical colormap
________________________________________________

.. code-block::

  style = {
    "nodata": 0,
    "min": 0,
    "max": 6,
    "clamp": "true",
    "dtype": "uint8",
    "scheme": "discrete",
    "palette": ["#000000", "#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#FF00FF", "#00FFFF"]
  }

.. _format_options: https://github.com/girder/large_image/blob/master/large_image/constants.py#L35
.. _pil_encoders: https://pillow.readthedocs.io/en/latest/handbook/image-file-formats.html
.. _libtiff_compression: https://github.com/pearu/pylibtiff/blob/master/libtiff/tiff_h_4_2_0.py#L19
.. _blend_modes: https://developer.mozilla.org/en-US/docs/Web/CSS/blend-mode
