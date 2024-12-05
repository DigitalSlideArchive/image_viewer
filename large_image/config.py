import functools
import json
import logging
import os
import pathlib
import re
from typing import Any, Optional, Union, cast

from . import exceptions

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# Default logger
fallbackLogger = logging.getLogger('large_image')
fallbackLogger.setLevel(logging.INFO)
fallbackLogHandler = logging.NullHandler()
fallbackLogHandler.setLevel(logging.NOTSET)
fallbackLogger.addHandler(fallbackLogHandler)

ConfigValues = {
    'logger': fallbackLogger,
    'logprint': fallbackLogger,

    # For tiles
    'cache_backend': None,  # 'python', 'redis' or 'memcached'
    # 'python' cache can use 1/(val) of the available memory
    'cache_python_memory_portion': 32,
    # cache_memcached_url may be a list
    'cache_memcached_url': '127.0.0.1',
    'cache_memcached_username': None,
    'cache_memcached_password': None,
    'cache_redis_url': '127.0.0.1:6379',
    'cache_redis_password': None,

    # If set to False, the default will be to not cache tile sources.  This has
    # substantial performance penalties if sources are used multiple times, so
    # should only be set in singular dynamic environments such as experimental
    # notebooks.
    'cache_sources': True,

    # Generally, these keys are the form of "cache_<cacheName>_<key>"

    # For tilesources.  These are also limited by available file handles.
    # 'python' cache can use 1/(val) of the available memory based on a very
    # rough estimate of the amount of memory used by a tilesource
    'cache_tilesource_memory_portion': 16,
    # If >0, this is the maximum number of tilesources that will be cached
    'cache_tilesource_maximum': 0,

    'max_small_image_size': 4096,

    # Should ICC color correction be applied by default
    'icc_correction': True,

    # The maximum size of an annotation file that will be ingested into girder
    # via direct load
    'max_annotation_input_file_length': 1 * 1024 ** 3 if not HAS_PSUTIL else max(
        1 * 1024 ** 3, psutil.virtual_memory().total // 16),

    # Any path that matches here will only be opened by a source that matches
    # extension or mime type.
    'all_sources_ignored_names': r'(\.mrxs|\.vsi)$',
}


# Fix when we drop Python 3.8 to just be @functools.cache
@functools.lru_cache(maxsize=None)
def getConfig(key: Optional[str] = None,
              default: Optional[Union[str, bool, int, logging.Logger]] = None) -> Any:
    """
    Get the config dictionary or a value from the cache config settings.

    :param key: if None, return the config dictionary.  Otherwise, return the
        value of the key if it is set or the default value if it is not.
    :param default: a value to return if a key is requested and not set.
    :returns: either the config dictionary or the value of a key.
    """
    if key is None:
        return ConfigValues
    envKey = f'LARGE_IMAGE_{key.replace(".", "_").upper()}'
    if envKey in os.environ:
        value = os.environ[envKey]
        if value == '__default__':
            return default
        try:
            value = json.loads(value)
        except ValueError:
            pass
        return value
    return ConfigValues.get(key, default)


def getLogger(key: Optional[str] = None,
              default: Optional[logging.Logger] = None) -> logging.Logger:
    """
    Get a logger from the config.  Ensure that it is a valid logger.

    :param key: if None, return the 'logger'.
    :param default: a value to return if a key is requested and not set.
    :returns: a logger.
    """
    logger = cast(logging.Logger, getConfig(key or 'logger', default))
    if not isinstance(logger, logging.Logger):
        logger = fallbackLogger
    return logger


def setConfig(key: str, value: Optional[Union[str, bool, int, logging.Logger]]) -> None:
    """
    Set a value in the config settings.

    :param key: the key to set.
    :param value: the value to store in the key.
    """
    curConfig = getConfig()
    if curConfig.get(key) is not value:
        curConfig[key] = value
        getConfig.cache_clear()


def _ignoreSourceNames(
        configKey: str, path: Union[str, pathlib.Path], default: Optional[str] = None) -> None:
    """
    Given a path, if it is an actual file and there is a setting
    "source_<configKey>_ignored_names", raise a TileSourceError if the path
    matches the ignore names setting regex in a case-insensitive search.

    :param configKey: key to use to fetch value from settings.
    :param path: the file path to check.
    :param default: a default ignore regex, or None for no default.
    """
    ignored_names = getConfig('source_%s_ignored_names' % configKey) or default
    if not ignored_names or not os.path.isfile(path):
        return None
    if re.search(ignored_names, os.path.basename(path), flags=re.IGNORECASE):
        raise exceptions.TileSourceError('File will not be opened by %s reader' % configKey)


def cpu_count(logical: bool = True) -> int:
    """
    Get the usable CPU count.  If psutil is available, it is used, since it can
    determine the number of physical CPUS versus logical CPUs.  This returns
    the smaller of that value from psutil and the number of cpus allowed by the
    os scheduler, which means that for physical requests (logical=False), the
    returned value may be more the the number of physical cpus that are usable.

    :param logical: True to get the logical usable CPUs (which include
        hyperthreading).  False for the physical usable CPUs.
    :returns: the number of usable CPUs.
    """
    count = os.cpu_count() or 2
    try:
        count = min(count, len(os.sched_getaffinity(0)))
    except AttributeError:
        pass
    try:
        import psutil

        count = min(count, psutil.cpu_count(logical) or count)
    except ImportError:
        pass
    return max(1, count)


def total_memory() -> int:
    """
    Get the total memory in the system.  If this is in a container, try to
    determine the memory available to the cgroup.

    :returns: the available memory in bytes, or 8 GB if unknown.
    """
    mem = 0
    if HAS_PSUTIL:
        mem = psutil.virtual_memory().total
    try:
        cgroup = int(open('/sys/fs/cgroup/memory/memory.limit_in_bytes').read().strip())
        if 1024 ** 3 <= cgroup < 1024 ** 4 and (mem is None or cgroup < mem):
            mem = cgroup
    except Exception:
        pass
    if mem:
        return mem
    return 8 * 1024 ** 3


def minimizeCaching(mode=None):
    """
    Set python cache sizes to very low values.

    :param mode: None for all caching, 'tile' for the tile cache, 'source' for
        the source cache.
    """
    if not mode or str(mode).lower().startswith('source'):
        setConfig('cache_tilesource_maximum', 1)
    if not mode or str(mode).lower().startswith('tile'):
        setConfig('cache_backend', 'python')
        setConfig('cache_python_memory_portion', 256)
