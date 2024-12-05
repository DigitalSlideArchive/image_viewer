#!/usr/bin/env python3

import argparse
import glob
import itertools
import logging
import math
import os
import pprint
import sys
import time

import numpy
import yaml

import large_image

os.environ['GDAL_PAM_ENABLED'] = 'NO'
os.environ['CPL_LOG'] = os.devnull


logging.getLogger('tifftools').setLevel(logging.ERROR)
logging.root.addHandler(logging.NullHandler())


def yaml_dict_dump(dumper, data):
    return dumper.represent_dict(data)


yaml.add_representer(large_image.tilesource.utilities.JSONDict, yaml_dict_dump)


def histotext(h, maxchan=None):
    ctbl = '0123456789'
    hist = None
    for entry in h['histogram'][:maxchan or len(h['histogram'])]:
        if hist is None:
            hist = entry['hist'].tolist().copy()
        else:
            for idx, val in enumerate(entry['hist'].tolist()):
                hist[idx] += val
    maxval = max(hist) or 1
    # scale up based on the second largest value if it is small compared to
    # the largest value
    secondmax = sorted(hist)[-2]
    maxval = min(maxval, secondmax * 1.5 if secondmax else maxval)
    result = ''
    for val in hist:
        scale = int(min(len(ctbl) - 1, math.floor(len(ctbl) * val / maxval)))
        result += ctbl[scale]
    return result


def write_thumb(img, source, prefix, name, opts=None, idx=None, idx2=None):
    if not prefix or not img:
        return
    ext = 'jpg' if not opts or not opts.encoding else opts.encoding.lower()
    idxStr = '' if not idx else '-%s' % str(idx)
    idx2Str = '' if not idx2 and not idx else '-%s' % str(idx2)
    path = '%s-%s-%s%s%s.%s' % (prefix, name, source, idxStr, idx2Str, ext)
    open(path, 'wb').write(img)


def float_format(val, length):
    s = ('%.' + str(length) + 'f') % val
    while ('.' in s and s[-1] == '0') or s[-1] == '.':
        s = s[:-1]
    if '.' in s and s.index('.') >= length - 1:
        s = s[:s.index('.')]
    if '.' in s:
        s = s[:length]
    elif len(s) > length:
        exp = 1
        while len(s) - (length - 1 - exp) >= 10 ** exp:
            exp += 1
        s = s[:length - 1 - exp] + 'e' + '%d' % (len(s) - (length - 1 - exp))
    if len(s) < length:
        s = ' ' * (length - len(s)) + s
    return s


def get_sources(sourceList, sources=None):
    sources = set(sources if sources else [])
    for source in sourceList:
        if os.path.isfile(source) or source.startswith(('https://', 'http://')):
            sources.add(source)
        elif os.path.isdir(source):
            for root, _dirs, files in os.walk(source):
                for file in files:
                    sources.add(os.path.join(source, root, file))
        elif source.startswith('-') and os.path.isfile(source[1:]):
            sources.remove(source[1:])
        elif source.startswith('-') and os.path.isdir(source[1:]):
            for root, _dirs, files in os.walk(source[1:]):
                for file in files:
                    sources.remove(os.path.join(source[1:], root, file))
        elif not source.startswith('-'):
            sources |= {sourcePath for sourcePath in glob.glob(source)
                        if os.path.isfile(sourcePath)}
        else:
            sources -= {sourcePath for sourcePath in glob.glob(source[1:])
                        if os.path.isfile(sourcePath)}
    sources = sorted(sources)
    return sources


def main(opts):
    if opts.out:

        class TeeOut:
            def __init__(self, stream1, stream2):
                self.stream1 = stream1
                self.stream2 = stream2

            def write(self, data):
                self.stream1.write(data)
                self.stream2.write(data)

            def flush(self):
                self.stream1.flush()
                self.stream2.flush()

        sys.stdout = TeeOut(sys.stdout, open(opts.out, 'w'))

    sources = get_sources(opts.source)
    results = []
    for sourcePath in sources:
        results.append(source_compare(sourcePath, opts))
    if opts.yaml:
        yaml.dump(results, open(opts.yaml, 'w'), sort_keys=False)


def source_compare(sourcePath, opts):  # noqa
    results = {'path': sourcePath}
    if os.path.isfile(sourcePath):
        results['filesize'] = os.path.getsize(sourcePath)
    if getattr(opts, 'size', False) and os.path.isfile(sourcePath):
        sys.stdout.write('%s %d\n' % (sourcePath, os.path.getsize(sourcePath)))
    else:
        sys.stdout.write('%s\n' % sourcePath)
    sys.stdout.flush()
    sublist = {
        k: v for k, v in large_image.tilesource.AvailableTileSources.items()
        if (getattr(opts, 'skipsource', None) is None or k not in opts.skipsource) and
           (getattr(opts, 'usesource', None) is None or k in opts.usesource)}
    canread = large_image.canReadList(sourcePath, availableSources=sublist)
    if opts.can_read and not len([cr for cr in canread if cr[1]]):
        return
    large_image.cache_util.cachesClear()
    slen = max([len(source) for source, _ in canread] + [10])
    sys.stdout.write('Source' + ' ' * (slen - 6))
    sys.stdout.write('  Width Height')
    sys.stdout.write(' Fram')
    sys.stdout.write(' Axes')
    sys.stdout.write(' open')
    sys.stdout.write(' thumbnail')
    sys.stdout.write('    tile 0')
    sys.stdout.write('    tile n')
    sys.stdout.write(' tile f 0n')
    sys.stdout.write('\n')
    sys.stdout.write('%s' % (' ' * (slen - 10)))
    sys.stdout.write('mag um/pix')
    sys.stdout.write('  TileW  TileH')
    sys.stdout.write(' dtyp')
    sys.stdout.write(' lv B')
    sys.stdout.write(' aImg')
    sys.stdout.write(' Histogram')
    sys.stdout.write(' Histogram')
    sys.stdout.write(' Histogram' if opts.full else '          ')
    sys.stdout.write(' Histogram')
    sys.stdout.write('\n')
    if opts.histlevels:
        sys.stdout.write('Lvl Fram Histogram                       ')
        sys.stdout.write(' Min    Max    Mean   Stdev  Time     ')
        sys.stdout.write('\n')

    thumbs = opts.thumbs
    if thumbs and os.path.isdir(thumbs):
        thumbs = os.path.join(thumbs, 'compare-' + os.path.basename(sourcePath))
    kwargs = {}
    if opts.encoding:
        kwargs['encoding'] = opts.encoding
    styles = [None if val == '' else val for val in (opts.style or [None])]
    projections = [None if val == '' else val for val in (opts.projection or [None])]
    results['styles'] = []
    for (styleidx, style), (projidx, projection) in itertools.product(
            enumerate(styles), enumerate(projections)):
        results['styles'].append({'style': style, 'projection': projection, 'sources': {}})
        kwargs['style'] = style
        if style is None:
            kwargs.pop('style', None)
        if len(styles) > 1:
            sys.stdout.write('Style: %s\n' % (str(style)[:72]))
        kwargs['projection'] = projection
        if projection is None:
            kwargs.pop('projection', None)
        if len(projections) > 1:
            sys.stdout.write('Projection: %s\n' % (str(projection)[:72]))
        for source, couldread in canread:
            if not couldread and opts.can_read:
                continue
            if getattr(opts, 'skipsource', None) and source in opts.skipsource:
                continue
            if getattr(opts, 'usesource', None) and source not in opts.usesource:
                continue
            if projection and not getattr(
                    large_image.tilesource.AvailableTileSources[source],
                    '_geospatial_source', None):
                continue
            result = results['styles'][-1]['sources'][source] = {}
            sys.stdout.write('%s' % (source + ' ' * (slen - len(source))))
            sys.stdout.flush()
            large_image.cache_util.cachesClear()
            try:
                t = time.time()
                ts = large_image.tilesource.AvailableTileSources[source](sourcePath, **kwargs)
                opentime = time.time() - t
            except Exception as exp:
                result['exception'] = str(exp)
                result['error'] = 'open'
                sexp = str(exp).replace('\n', ' ').replace('  ', ' ').strip()
                sexp = sexp.replace(sourcePath, '<path>')
                sys.stdout.write(' %s\n' % sexp[:78 - slen])
                sys.stdout.write('%s %s\n' % (' ' * slen, sexp[78 - slen: 2 * (78 - slen)]))
                sys.stdout.flush()
                continue
            sizeX, sizeY = ts.sizeX, ts.sizeY
            result['sizeX'], result['sizeY'] = ts.sizeX, ts.sizeY
            try:
                metadata = ts.getMetadata()
            except Exception as exp:
                result['exception'] = str(exp)
                result['error'] = 'metadata'
                sys.stdout.write(' %6d %6d' % (sizeX, sizeY))
                sexp = str(exp).replace('\n', ' ').replace('  ', ' ').strip()
                sexp = sexp.replace(sourcePath, '<path>')
                sys.stdout.write(' %s\n' % sexp[:64 - slen])
                sys.stdout.write('%s %s\n' % (
                    ' ' * slen if not couldread else ' canread' + ' ' * (slen - 8),
                    sexp[64 - slen: (64 - slen) + (78 - slen)]))
                sys.stdout.flush()
                continue
            frames = len(metadata.get('frames', [])) or 1
            levels = metadata['levels']
            tx0 = ty0 = tz0 = 0
            hx = ts.sizeX // ts.tileWidth // 2
            hy = ts.sizeY // ts.tileHeight // 2
            if projection and 'bounds' in metadata:
                kwargs['region'] = dict(
                    left=metadata['bounds']['xmin'],
                    top=metadata['bounds']['ymin'],
                    right=metadata['bounds']['xmax'],
                    bottom=metadata['bounds']['ymax'],
                    units='projection')
                grb = ts._getRegionBounds(metadata, **kwargs.get('region', {}))
                for level in range(metadata['levels']):
                    if (((grb[0] + 1) // 2 ** level // ts.tileWidth ==
                         grb[2] // 2 ** level // ts.tileWidth) and
                        ((grb[1] + 1) // 2 ** level // ts.tileHeight ==
                         grb[3] // 2 ** level // ts.tileHeight)):
                        tz0 = metadata['levels'] - 1 - level
                        tx0 = grb[0] // 2 ** level // ts.tileWidth
                        ty0 = grb[1] // 2 ** level // ts.tileHeight
                        hx = (grb[0] + grb[2]) // 2 // ts.tileWidth
                        hy = (grb[1] + grb[3]) // 2 // ts.tileHeight
                        sizeX = grb[2] - grb[0]
                        sizeY = grb[3] - grb[1]
                        break
            sys.stdout.write(' %6d %6d' % (sizeX, sizeY))
            sys.stdout.write(' %4d' % frames)
            result['frames'] = frames
            result['metadata'] = ts.metadata
            if frames > 1 and 'IndexStride' in ts.metadata:
                result['IndexRange'] = ts.metadata['IndexRange']
                axes = [vk[-1] for vk in sorted([
                    (v, k) for k, v in ts.metadata['IndexStride'].items()
                    if ts.metadata['IndexRange'][k] > 1])]
                sys.stdout.write(' %-4s' % (''.join(
                    k[5:6] if k != 'IndexXY' else 'x' for k in axes)[:4]))
            else:
                sys.stdout.write('     ')
            result['opentime'] = opentime
            sys.stdout.write(' ' + ((
                '%3.0f' if opentime >= 10 else '%3.1f' if opentime >= 1 else '%4.2f'
            ) % opentime).lstrip('0') + 's')
            sys.stdout.flush()
            t = time.time()
            try:
                img = ts.getThumbnail(**kwargs)
            except Exception as exp:
                result['exception'] = str(exp)
                result['error'] = 'thumbnail'
                sexp = str(exp).replace('\n', ' ').replace('  ', ' ').strip()
                sexp = sexp.replace(sourcePath, '<path>')
                sys.stdout.write(' %s\n' % sexp[:49 - slen])
                sys.stdout.write('%s %s\n' % (
                    ' ' * slen if not couldread else ' canread' + ' ' * (slen - 8),
                    sexp[49 - slen: (49 - slen) + (78 - slen)]))
                sys.stdout.flush()
                continue
            thumbtime = time.time() - t
            result['thumbtime'] = thumbtime
            sys.stdout.write(' %8.3fs' % thumbtime)
            sys.stdout.flush()
            write_thumb(img[0], source, thumbs, 'thumbnail', opts, styleidx, projidx)
            t = time.time()
            img = ts.getTile(tx0, ty0, tz0, sparseFallback=True)
            tile0time = time.time() - t
            result['tile0time'] = tile0time
            sys.stdout.write(' %8.3fs' % tile0time)
            sys.stdout.flush()
            write_thumb(img, source, thumbs, 'tile0', opts, styleidx, projidx)
            t = time.time()
            img = ts.getTile(hx, hy, levels - 1, sparseFallback=True)
            tilentime = time.time() - t
            result['tilentime'] = tilentime
            sys.stdout.write(' %8.3fs' % tilentime)
            sys.stdout.flush()
            write_thumb(img, source, thumbs, 'tilen', opts, styleidx, projidx)
            if frames > 1:
                t = time.time()
                img = ts.getTile(0, 0, 0, frame=frames - 1, sparseFallback=True)
                tilef0time = time.time() - t
                write_thumb(img, source, thumbs, 'tilef0', opts, styleidx, projidx)
                t = time.time()
                img = ts.getTile(hx, hy, levels - 1, frame=frames - 1, sparseFallback=True)
                tilefntime = time.time() - t
                result['tilef0time'] = tilef0time
                result['tilefntime'] = tilefntime
                sys.stdout.write(' %8.3fs' % (tilef0time + tilefntime))
                sys.stdout.flush()
                write_thumb(img, source, thumbs, 'tilefn', opts, styleidx, projidx)
            sys.stdout.write('\n')

            result['couldread'] = couldread
            if not couldread:
                sys.stdout.write(' !canread' + (' ' * (slen - 9)))
            else:
                sys.stdout.write(' ' * (slen - 10))
                sys.stdout.write('%3s ' % (
                    ('%3.1f' % metadata['magnification'])[:3].rstrip('.')
                    if metadata.get('magnification') else ''))
                um = (metadata.get('mm_x', 0) or 0) * 1000
                umstr = '      '
                if um and um < 100:
                    umstr = '%6.3f' % um
                elif um:
                    prefix = 'um kM'
                    val = um
                    idx = 0
                    while val >= 10000 and idx + 1 < len(prefix):
                        idx += 1
                        val /= 1000
                    umstr = '%4.0f%sm' % (val, prefix[idx])
                sys.stdout.write(umstr)
            sys.stdout.write(' %6d %6d' % (ts.tileWidth, ts.tileHeight))
            if hasattr(ts, 'dtype'):
                result['dtype'] = str(ts.dtype)
                sys.stdout.write(' %4s' % numpy.dtype(ts.dtype).str.lstrip('|').lstrip('<')[:4])
            else:
                sys.stdout.write('     ')
            sys.stdout.flush()
            if hasattr(ts, '_populatedLevels'):
                result['populatedLevels'] = ts._populatedLevels
                sys.stdout.write(' %2d' % ts._populatedLevels)
            else:
                sys.stdout.write('   ')
            if ts.metadata.get('bandCount'):
                result['bandCount'] = ts.metadata['bandCount']
                sys.stdout.write(' %1d' % ts.metadata['bandCount'])
            else:
                sys.stdout.write('  ')
            sys.stdout.flush()
            try:
                allist = ts.getAssociatedImagesList()
                result['associatedImages'] = allist
                alnames = ''
                for alkey in ['label', 'macro']:
                    if alkey in allist:
                        alnames += alkey[:1]
                if len(alnames) or len(allist):
                    sys.stdout.write(' %s%*d' % (
                        alnames + ' ' if alnames else '',
                        4 - (len(alnames) + 1 if alnames else 0),
                        len(allist)))
                else:
                    sys.stdout.write('     ')
            except Exception as exp:
                result['associatedImagesError'] = str(exp)
                sys.stdout.write(' fail')
            sys.stdout.flush()

            # get maxval for other histograms
            h = ts.histogram(
                onlyMinMax=True, output=dict(maxWidth=2048, maxHeight=2048),
                resample=0, **kwargs)
            if 'max' not in h:
                sys.stdout.write(' fail\n')
                sys.stdout.flush()
                continue
            maxval = max(h['max'].tolist())
            maxval = 2 ** (int(math.log(maxval or 1) / math.log(2)) + 1) if maxval > 1 else 1
            # thumbnail histogram
            h = ts.histogram(bins=9, output=dict(maxWidth=256, maxHeight=256),
                             range=[0, maxval], resample=0, **kwargs)
            maxchan = len(h['histogram'])
            if maxchan == 4:
                maxchan = 3
            result['thumbnail_histogram'] = histotext(h, maxchan)
            sys.stdout.write(' %s' % histotext(h, maxchan))
            sys.stdout.flush()
            # full image histogram
            h = ts.histogram(bins=9, output=dict(maxWidth=2048, maxHeight=2048),
                             range=[0, maxval], resample=0, **kwargs)
            result['full_2048_histogram'] = histotext(h, maxchan)
            sys.stdout.write(' %s' % histotext(h, maxchan))
            sys.stdout.flush()
            if opts.full:
                # at full res
                h = ts.histogram(bins=9, range=[0, maxval], resample=0, **kwargs)
                result['full_max_histogram'] = histotext(h, maxchan)
                sys.stdout.write(' %s' % histotext(h, maxchan))
                sys.stdout.flush()
            else:
                sys.stdout.write(' %s' % (' ' * 9))
            if frames > 1:
                # last frame full image histogram
                if not opts.full:
                    h = ts.histogram(
                        bins=9, output=dict(maxWidth=2048, maxHeight=2048),
                        range=[0, maxval], frame=frames - 1, resample=0,
                        **kwargs)
                    result['full_f_2048_histogram'] = histotext(h, maxchan)
                    sys.stdout.write(' %s' % histotext(h, maxchan))
                else:
                    # at full res
                    h = ts.histogram(bins=9, range=[0, maxval],
                                     frame=frames - 1, resample=0, **kwargs)
                    result['full_f_max_histogram'] = histotext(h, maxchan)
                    sys.stdout.write(' %s' % histotext(h, maxchan))
                sys.stdout.flush()
            sys.stdout.write('\n')
            if opts.histlevels:
                # histograms at all levels on the first and last frames
                for f in range(0, frames, (frames - 1) or 1):
                    for ll in range(levels):
                        t = -time.time()
                        h = ts.histogram(bins=32, output=dict(
                            maxWidth=int(math.ceil(ts.sizeX / 2 ** (levels - 1 - ll))),
                            maxHeight=int(math.ceil(ts.sizeY / 2 ** (levels - 1 - ll))),
                        ), range=[0, maxval], frame=f, resample=0, **kwargs)
                        t += time.time()
                        result[f'level_{ll}_f_{f}_histogram'] = histotext(h, maxchan)
                        sys.stdout.write('%3d%5d %s' % (ll, f, histotext(h, maxchan)))
                        sys.stdout.write(' %s %s %s %s' % (
                            float_format(min(h['min'].tolist()[:maxchan]), 6),
                            float_format(max(h['max'].tolist()[:maxchan]), 6),
                            float_format(sum(h['mean'].tolist()[:maxchan]) / maxchan, 6),
                            float_format(sum(h['stdev'].tolist()[:maxchan]) / maxchan, 6)))
                        sys.stdout.write(' %8.3fs' % t)
                        sys.stdout.write('\n')
                        sys.stdout.flush()
            if opts.metadata:
                sys.stdout.write(pprint.pformat(ts.getMetadata()).strip() + '\n')
            if opts.internal:
                result['internal_metadata'] = ts.getInternalMetadata()
                sys.stdout.write(pprint.pformat(ts.getInternalMetadata()).strip() + '\n')
            if opts.assoc:
                sys.stdout.write(pprint.pformat(ts.getAssociatedImagesList()).strip() + '\n')
                for assoc in ts.getAssociatedImagesList():
                    img = ts.getAssociatedImage(assoc, **kwargs)
                    write_thumb(img[0], source, thumbs, 'assoc-%s' % assoc, opts, styleidx, projidx)
    return results


def command():
    parser = argparse.ArgumentParser(
        description='Compare each large_image source on how it reads a file.  '
        'For each source, times are measured to read the thumbnail, the '
        'singular tile at zero level, the center tile at maximum level (all '
        'for frame 0), the singular at zero and center at maximum tiles for '
        'the last frame for multiframe files.  A histogram is computed for '
        'the thumbnail and the singular tile(s) and, optionally, the whole '
        'image at the maximum level (which is slow).')
    parser.add_argument(
        'source', nargs='+', type=str,
        help='Source file to read and analyze.  This can be a directory for '
        'the entire directory tree, a glob pattern, urls starting with http '
        'or https.  Prefix with - to remove the file, directory, or glob '
        'pattern from the sources analyzed.  Sources are analyzed in a sorted '
        'order.')
    parser.add_argument(
        '--usesource', '--use', action='append',
        help='Only use the specified source.  Can be specified multiple times.')
    parser.add_argument(
        '--skipsource', '--skip', action='append',
        help='Do not use the specified source.  Can be specified multiple '
        'times.')
    parser.add_argument('--full', action='store_true', help='Run histogram on full image')
    parser.add_argument(
        '--histogram-levels', '--hl', action='store_true', dest='histlevels',
        help='Run histogram on each level')
    parser.add_argument(
        '--all', action='store_true',
        help='All sources to read all files.  Otherwise, some sources avoid '
        'some files based on name.')
    parser.add_argument(
        '--can-read', action='store_true',
        help='If a source reports it cannot read a file, it will not be '
        'included in the full report.')
    parser.add_argument(
        '--thumbs', '--thumbnails', type=str, required=False,
        help='Location to write thumbnails of results.  If this is not an '
        'existing directory, it is a prefix for the resultant files.')
    parser.add_argument(
        '--metadata', action='store_true',
        help='Print metadata from the file.')
    parser.add_argument(
        '--internal', action='store_true',
        help='Print internal metadata from the file.')
    parser.add_argument(
        '--assoc', '--associated', action='store_true',
        help='List associated images from the file.')
    parser.add_argument(
        '--encoding', help='Optional encoding for tiles (e.g., PNG)')
    # TODO append this to a list to allow multiple encodings tested
    parser.add_argument(
        '--style', action='append',
        help='Use the json style when testing.  Can be specified multiple times.')
    parser.add_argument(
        '--projection', action='append',
        help='Use the projection when testing.  Can be specified multiple '
        'times.  EPSG:3857 is a common choice.')
    # TODO add a flag to skip non-geospatial sources if a projection is used
    parser.add_argument(
        '--size', action='store_true',
        help='Report the size of the file.')
    parser.add_argument(
        '--yaml', '--yaml-output', help='Output the results to a yaml file.')
    parser.add_argument(
        '--out', '--output', help='Redirect output to a text file.')
    parser.add_argument(
        '--verbose', '-v', action='count', default=0, help='Increase verbosity')
    parser.add_argument(
        '--silent', '-s', action='count', default=0, help='Decrease verbosity')
    opts = parser.parse_args()
    li_logger = large_image.config.getConfig('logger')
    li_logger.setLevel(max(1, logging.CRITICAL - (opts.verbose - opts.silent) * 10))
    li_logger.addHandler(logging.StreamHandler(sys.stderr))
    if not large_image.tilesource.AvailableTileSources:
        large_image.tilesource.loadTileSources()
    if opts.all:
        for key in list(large_image.config.ConfigValues):
            if '_ignored_names' in key:
                del large_image.config.ConfigValues[key]
        large_image.config.ConfigValues.pop('all_sources_ignored_names', None)
    main(opts)


if __name__ == '__main__':
    command()
