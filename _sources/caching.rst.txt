Caching in Large Image
======================

There are two main caches in large_image in addition to caching done on the operating system level.  These are:

- Tile Cache: The tile cache stores individual images and/or numpy arrays for each tile processed.

  - May be stored in the python process memory or memcached.  Other cache backends can also be added.
  - The cache key is a hash that includes the tile source, tile location within the source, format and compression, and style.
  - If memcached is used, cached tiles can be shared across multiple processes.
  - Tiles are often bigger than what memcached was optimized for, so memcached needs to be set to allow larger values.
  - Cached tiles can include original as-read data as well as styled or transformed data.  Tiles can be synthesized for sources that are missing specific resolutions; these are also cached.
  - If using memcached, memcached determines how much memory is used (and what machine it is stored on).  If using the python process, memory is limited to a fraction of total memory as reported by psutils.

- Tile Source Cache: The source cache stores file handles, parsed metadata, and other values to optimize reading a specific large image.

  - Always stored in the python process memory (not shared between processes).
  - Memory use is wildly different depending on tile source; an estimate is based on sample files and then the maximum number of sources that should be tiled is based on a frame of total memory as reported by psutils and this estimate.
  - The cache key includes the tile source, default tile format, and style.
  - File handles and other metadata are shared if sources only differ in style (for example if ICC color correction is applied in one and not in another).
  - Because file handles are shared across sources that only differ in style, if a source implements a custom ``__del__`` operator, it needs to check if it is the unstyled source.
