Configuration Options
=====================

Some functionality of large_image is controlled through configuration parameters.  These can be read or set via python using functions in the ``large_image.config`` module, `getConfig <./_build/large_image/large_image.html#large_image.config.getConfig>`_ and `setConfig <./_build/large_image/large_image.html#large_image.config.setConfig>`_.

.. list-table:: Configuration Parameters
   :header-rows: 1
   :widths: 20 20 20 20

   * - Key(s)
     - Description
     - Type
     - Default

       .. _config_logger:
   * - ``logger`` :ref:`🔗 <config_logger>`
     - Most log messages are sent here.
     - ``logging.Logger``
     - This defaults to the standard python logger using the name large_image. When using Girder, this default to Girder's logger, which allows colored console output.

       .. _config_logprint:
   * - ``logprint`` :ref:`🔗 <config_logprint>`
     - Messages about available tilesources are sent here.
     - ``logging.Logger``
     - This defaults to the standard python logger using the name large_image. When using Girder, this default to Girder's logger, which allows colored console output.

       .. _config_cache_backend:
   * - ``cache_backend`` :ref:`🔗 <config_cache_backend>`
     - String specifying how tiles are cached.  If memcached is not available for any reason, the python cache is used instead.
     - ``None | str: "python" | str: "memcached" | str: "redis"``
     - ``None`` (When None, the first cache available in the order memcached, redis, python is used. Otherwise, the specified cache is used if available, falling back to python if not.)

       .. _config_cache_python_memory_portion:
   * - ``cache_python_memory_portion`` :ref:`🔗 <config_cache_python_memory_portion>`
     - If tiles are cached with python, the cache is sized so that it is expected to use less than 1 / (``cache_python_memory_portion``) of the available memory.
     - ``int``
     - ``16``

       .. _config_cache_memcached_url:
   * - ``cache_memcached_url`` :ref:`🔗 <config_cache_memcached_url>`
     - If tiles are cached in memcached, the url or list of urls where the memcached server is located.
     - ``str | List[str]``
     - ``"127.0.0.1"``

       .. _config_cache_memcached_username:
   * - ``cache_memcached_username`` :ref:`🔗 <config_cache_memcached_username>`
     - A username for the memcached server.
     - ``str``
     - ``None``

       .. _config_cache_memcached_password:
   * - ``cache_memcached_password`` :ref:`🔗 <config_cache_memcached_password>`
     - A password for the memcached server.
     - ``str``
     - ``None``

       .. _config_cache_redis_url:
   * - ``cache_redis_url`` :ref:`🔗 <config_cache_redis_url>`
     - If tiles are cached in redis, the url or list of urls where the redis server is located.
     - ``str | List[str]``
     - ``"127.0.0.1:6379"``

       .. _config_cache_redis_username:
   * - ``cache_redis_username`` :ref:`🔗 <config_cache_redis_username>`
     - A username for the redis server.
     - ``str``
     - ``None``

       .. _config_cache_redis_password:
   * - ``cache_redis_password`` :ref:`🔗 <config_cache_redis_password>`
     - A password for the redis server.
     - ``str``
     - ``None``

       .. _config_cache_tilesource_memory_portion:
   * - ``cache_tilesource_memory_portion`` :ref:`🔗 <config_cache_tilesource_memory_portion>`
     - Tilesources are cached on open so that subsequent accesses can be faster.  These use file handles and memory.  This limits the maximum based on a memory estimation and using no more than 1 / (``cache_tilesource_memory_portion``) of the available memory.
     - ``int``
     - ``32`` Memory usage by tile source is necessarily a rough estimate, since it can vary due to a wide variety of image-specific and deployment-specific details; this is intended to be conservative.

       .. _config_cache_tilesource_maximum:
   * - ``cache_tilesource_maximum`` :ref:`🔗 <config_cache_tilesource_maximum>`
     - If this is zero, this signifies that ``cache_tilesource_memory_portion`` determines the number of sources that will be cached. If this greater than 0, the cache will be the smaller of the value computed for the memory portion and this value (but always at least 3).
     - ``int``
     - ``0``

       .. _config_cache_sources:
   * - ``cache_sources`` :ref:`🔗 <config_cache_sources>`
     - If set to False, the default will be to not cache tile sources.  This has substantial performance penalties if sources are used multiple times, so should only be set in singular dynamic environments such as experimental notebooks.
     - ``bool``
     - ``True``

       .. _config_max_small_image_size:
   * - ``max_small_image_size`` :ref:`🔗 <config_max_small_image_size>`
     - The PIL tilesource is used for small images if they are no more than this many pixels along their maximum dimension.
     - ``int``
     - ``4096``  Specifying values greater than this could reduce compatibility with tile use on some browsers. In general, ``8192`` is safe for all modern systems, and values greater than ``16384`` should not be specified if the image will be viewed in any browser.

       .. _config_source_ignored_names:
   * - ``source_bioformats_ignored_names``,
       ``source_pil_ignored_names``,
       ``source_vips_ignored_names`` :ref:`🔗 <config_source_ignored_names>`
     - Some tile sources can read some files that are better read by other tilesources.  Since reading these files is suboptimal, these tile sources have a setting that, by default, ignores files without extensions or with particular extensions.
     - ``str`` (regular expression)
     - Sources have different default values; see each source for its default. For example, the vips source default is ``r'(^[^.]*|\.(yml|yaml|json|png|svs|mrxs))$'``

       .. _config_all_sources_ignored_names:
   * - ``all_sources_ignored_names`` :ref:`🔗 <config_all_sources_ignored_names>`
     - If a file matches the regular expression in this setting, it will only be opened by sources that explicitly match the extension or mimetype.  Some formats are composed of multiple files that can be read as either a small image or as a large image depending on the source; this prohibits all sources that don't explicitly support the format.
     - ``str`` (regular expression)
     - ``'(\.mrxs|\.vsi)$'``

       .. _config_icc_correction:
   * - ``icc_correction`` :ref:`🔗 <config_icc_correction>`
     -  If this is True or undefined, ICC color correction will be applied for tile sources that have ICC profile information.  If False, correction will not be applied.  If the style used to open a tilesource specifies ICC correction explicitly (on or off), then this setting is not used.  This may also be a string with one of the intents defined by the PIL.ImageCms.Intents enum.  ``True`` is the same as ``perceptual``.
     - ``bool | str: one of PIL.ImageCms.Intents``
     - ``True``

       .. _config_max_annotation_input_file_length:
   * - ``max_annotation_input_file_length`` :ref:`🔗 <config_max_annotation_input_file_length>`
     - When an annotation file is uploaded through Girder, it is loaded into memory, validated, and then added to the database.  This is the maximum number of bytes that will be read directly.  Files larger than this are ignored.
     - ``int``
     - The larger of 1 GiByte and 1/16th of the system virtual memory


Configuration from Python
-------------------------

As an example, configuration parameters can be set via python code like::

  import large_image

  large_image.config.setConfig('max_small_image_size', 8192)

If reading many different images but never revisiting them, it can be useful to reduce caching to a minimum.  There is a utility function to make this easier::

  large_image.config.minimizeCaching()

Configuration from Environment
------------------------------

All configuration parameters can be specified as environment parameters by prefixing their uppercase names with ``LARGE_IMAGE_``.  For instance, ``LARGE_IMAGE_CACHE_BACKEND=python`` specifies the cache backend.  If the values can be decoded as json, they will be parsed as such.  That is, numerical values will be parsed as numbers; to parse them as strings, surround them with double quotes.

As another example, to use the least memory possible, set ``LARGE_IMAGE_CACHE_BACKEND=python LARGE_IMAGE_CACHE_PYTHON_MEMORY_PORTION=1000 LARGE_IMAGE_CACHE_TILESOURCE_MAXIMUM=2``.  The first setting specifies caching tiles in the main process and not in memcached or an external cache.  The second setting asks to use 1/1000th of the memory for a tile cache.  The third settings caches no more than 2 tile sources (2 is the minimum).

Configuration within the Girder Plugin
--------------------------------------

For the Girder plugin, these can also be set in the ``girder.cfg`` file in a ``large_image`` section.  For example::

  [large_image]
  # cache_backend, used for caching tiles, is either "memcached" or "python"
  cache_backend = "python"
  # 'python' cache can use 1/(val) of the available memory
  cache_python_memory_portion = 32
  # 'memcached' cache backend can specify the memcached server.
  # cache_memcached_url may be a list
  cache_memcached_url = "127.0.0.1"
  cache_memcached_username = None
  cache_memcached_password = None
  # The tilesource cache uses the lesser of a value based on available file
  # handles, the memory portion, and the maximum (if not 0)
  cache_tilesource_memory_portion = 8
  cache_tilesource_maximum = 0
  # The PIL tilesource won't read images larger than the max small images size
  max_small_image_size = 4096
  # The bioformats tilesource won't read files that end in a comma-separated
  # list of extensions
  source_bioformats_ignored_names = r'(^[!.]*|\.(jpg|jpeg|jpe|png|tif|tiff|ndpi))$'
  # The maximum size of an annotation file that will be ingested into girder
  # via direct load
  max_annotation_input_file_length = 1 * 1024 ** 3

Logging from Python
-------------------

The log levels can be adjusted in the standard Python manner::

  import logging
  import large_image

  logger = logging.getLogger('large_image')
  logger.setLevel(logging.CRITICAL)

Alternately, a different logger can be specified via ``setConfig`` in the ``logger`` and ``logprint`` settings::

  import logging
  import large_image

  logger = logging.getLogger(__name__)
  large_image.config.setConfig('logger', logger)
  large_image.config.setConfig('logprint', logger)
