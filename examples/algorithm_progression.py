#!/usr/bin/env python3

import argparse
import concurrent.futures
import inspect
import itertools
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path

try:
    import algorithms
except ImportError:
    from . import algorithms
import large_image_converter
import numpy as np
import tifftools
import yaml

import large_image


class SweepAlgorithm:
    def __init__(self, algorithm, input_filename, input_params, param_order,
                 output_filename, max_workers, multiprocessing, overlay,
                 lossy=False, scale=1, dedup=False):
        self.algorithm = algorithm
        self.input_filename = input_filename
        self.output_filename = output_filename
        self.input_params = input_params
        self.param_order = param_order
        self.max_workers = max_workers
        self.multiprocessing = multiprocessing
        self.overlay = overlay
        self.lossy = lossy
        self.scale = float(scale)
        self.dedup = dedup

        self.combos = list(itertools.product(*[p['range'] for p in input_params.values()]))

    def getOverallSink(self):
        msg = 'Not implemented'
        raise Exception(msg)

    def getTileSink(self, sink):
        msg = 'Not implemented'
        raise Exception(msg)

    def writeTileSink(self, tilesink, iteration_id):
        msg = 'Not implemented'
        raise Exception(msg)

    def writeOverallSink(self, sink):
        msg = 'Not implemented'
        raise Exception(msg)

    def collectResult(self, result):
        msg = 'Not implemented'
        raise Exception(msg)

    def addTile(self, tilesink, *args, **kwargs):
        return tilesink.addTile(*args, **kwargs)

    def applyAlgorithm(self, sink, params):
        source = large_image.open(self.input_filename)
        param_indices = {
            param_name: list(values['range']).index(params[index])
            for index, (param_name, values) in enumerate(self.input_params.items())
        }
        iteration_id = [param_indices[param_name] for param_name in self.param_order]
        tilesink = self.getTileSink(sink)
        lastlogtime = time.time()
        tiparams = {}
        if self.scale and self.scale != 1:
            tiparams['output'] = {
                'maxWidth': int(math.ceil(source.sizeX / self.scale)),
                'maxHeight': int(math.ceil(source.sizeY / self.scale)),
            }
        for tile in source.tileIterator(
            format=large_image.tilesource.TILE_FORMAT_NUMPY,
            tile_size=dict(width=2048, height=2048),
            **tiparams,
        ):
            scaled = tile.get('scaled', 1)
            axisparams = {
                p['axis']: iteration_id[i] for i, p in enumerate(self.param_order.values())}
            axisparams.update({
                p['axis'] + '_value': params[i] for i, p in enumerate(self.param_order.values())})
            if self.overlay:
                self.addTile(
                    tilesink,
                    tile['tile'], int(tile['x'] * scaled), int(tile['y'] * scaled),
                    **axisparams)
            altered_data = self.algorithm(tile['tile'], *params)
            mask = None
            if self.overlay:
                if altered_data.shape[2] in {2, 4}:
                    mask = altered_data[:, :, -1] != 0
                    if altered_data.shape[2] == tile['tile'].shape[2] + 1:
                        altered_data = altered_data[:, :, :-1]
            elif altered_data.shape[2] in {2, 4}:
                altered_data[:, :, -1] = 255
            self.addTile(
                tilesink,
                altered_data, int(tile['x'] * scaled), int(tile['y'] * scaled), mask=mask,
                **axisparams)
            if time.time() - lastlogtime > 10:
                sys.stdout.write(
                    f'Processed {tile["tile_position"]["position"] + 1} of '
                    f'{tile["iterator_range"]["position"]} tiles\n')
                sys.stdout.flush()
                lastlogtime = time.time()
        return self.writeTileSink(tilesink, iteration_id)

    def run(self):
        starttime = time.time()
        sink = self.getOverallSink()

        print(f'Beginning {len(self.combos)} runs on {self.max_workers} workers...')
        num_done = 0
        poolExecutor = (
            concurrent.futures.ProcessPoolExecutor if self.multiprocessing else
            concurrent.futures.ThreadPoolExecutor)
        poolParams = {}
        if self.multiprocessing and sys.version_info >= (3, 11):
            poolParams['max_tasks_per_child'] = 1
        with poolExecutor(max_workers=self.max_workers, **poolParams) as executor:
            futures = [
                executor.submit(
                    self.applyAlgorithm,
                    sink,
                    combo,
                )
                for combo in self.combos
            ]
            for future in concurrent.futures.as_completed(futures):
                self.collectResult(future.result())
                num_done += 1
                sys.stdout.write(f'Completed {num_done} of {len(self.combos)} runs.\r')
                sys.stdout.flush()
        print(f'Generation time {time.time() - starttime:5.3f}        ')
        starttime = time.time()
        self.writeOverallSink(sink)
        print(f'Save time {time.time() - starttime:5.3f}')


class SweepAlgorithmMulti(SweepAlgorithm):
    def getOverallSink(self):
        os.makedirs(os.path.splitext(self.output_filename)[0], exist_ok=True)
        algorithm_name = self.algorithm.__name__.replace('_', ' ').title()
        self.yaml_dict = {
            'name': f'{algorithm_name} iterative results',
            'description': f'{algorithm_name} algorithm performed on {self.input_filename}',
            'axes': [p['axis'] for p in self.param_order.values()],
            'sources': [],
            'uniformSources': True,
        }
        return True

    def writeOverallSink(self, sink):
        resultpath = Path(os.path.splitext(self.output_filename)[0], 'results.yml')
        with open(resultpath, 'w') as f:
            yaml.dump(
                self.yaml_dict,
                f,
                default_flow_style=False,
                sort_keys=False,
            )
        if os.path.splitext(self.output_filename)[1]:
            if (os.path.splitext(self.output_filename)[1] in {'.tif', '.tiff'} and
                    os.path.splitext(self.yaml_dict['sources'][0]['path'])[1] == '.tiff'):
                lastlogtime = time.time()
                rts = large_image.open(resultpath, noCache=True)
                info = None
                for idx, srcinfo in enumerate(rts.metadata['frames']):
                    for src in self.yaml_dict['sources']:
                        skip = False
                        for k, v in src.items():
                            if k != 'path':
                                if srcinfo['Index' + k.upper()] != v:
                                    skip = True
                        if not skip:
                            break
                    ti = tifftools.read_tiff(Path(
                        os.path.splitext(self.output_filename)[0], src['path']))
                    desc = {
                        'frame': srcinfo,
                    }
                    if info is None:
                        info = ti
                        desc['metadata'] = rts.metadata
                        if 'channels' in rts.metadata:
                            desc['channels'] = rts.metadata['channels']
                    else:
                        info['ifds'].extend(ti['ifds'])
                    ti['ifds'][0]['tags'][tifftools.Tag.ImageDescription.value] = {
                        'datatype': tifftools.Datatype.ASCII,
                        'data': json.dumps(
                            desc, separators=(',', ':'), sort_keys=True,
                            default=large_image_converter.json_serial),
                    }
                    ti = None
                    if time.time() - lastlogtime > 10:
                        sys.stdout.write(
                            f'Collected {idx + 1} of {len(self.yaml_dict["sources"])} frames\n')
                        sys.stdout.flush()
                        lastlogtime = time.time()
                tifftools.write_tiff(
                    info, self.output_filename, allowExisting=True,
                    ifdsFirst=self.dedup, dedup=self.dedup)
                rts = None
                info = None
            else:
                large_image_converter.convert(resultpath, self.output_filename, overwrite=True)
            shutil.rmtree(os.path.splitext(self.output_filename)[0], ignore_errors=True)

    def writeTileSink(self, tilesink, iteration_id):
        ext = '.tiff'
        filename = f'{self.algorithm.__name__}_{"_".join([str(v) for v in iteration_id])}{ext}'
        filepath = Path(os.path.splitext(self.output_filename)[0], filename)

        desc = dict(
            path=filename,
            **{p['axis']: iteration_id[i] for i, p in enumerate(self.param_order.values())},
        )
        tilesink.write(str(filepath), lossy=self.lossy)
        return desc

    def addTile(self, tilesink, *args, **kwargs):
        return tilesink.addTile(*args)

    def collectResult(self, result):
        self.yaml_dict['sources'].append(result)


class SweepAlgorithmMultiVips(SweepAlgorithmMulti):
    def getTileSink(self, sink):
        import large_image_source_vips

        return large_image_source_vips.new()


class SweepAlgorithmMultiZarr(SweepAlgorithmMulti):
    def getTileSink(self, sink):
        import large_image_source_zarr

        return large_image_source_zarr.new()

    def writeTileSink(self, tilesink, iteration_id):
        ext = '.zarr.zip'
        if os.path.splitext(self.output_filename)[1] in {'.tif', '.tiff'}:
            ext = '.tiff'
        filename = f'{self.algorithm.__name__}_{"_".join([str(v) for v in iteration_id])}{ext}'
        filepath = Path(os.path.splitext(self.output_filename)[0], filename)

        desc = dict(
            path=filename,
            **{p['axis']: iteration_id[i] for i, p in enumerate(self.param_order.values())},
        )
        tilesink.write(str(filepath), lossy=self.lossy)
        return desc

    def addTile(self, tilesink, *args, **kwargs):
        return tilesink.addTile(*args, **{
            k: v for k, v in kwargs.items() if k in {'mask'}})


class SweepAlgorithmZarr(SweepAlgorithm):
    def getOverallSink(self):
        import large_image_source_zarr

        return large_image_source_zarr.new()

    def writeOverallSink(self, sink):
        sink.write(self.output_filename, lossy=self.lossy)

    def getTileSink(self, sink):
        return sink

    def writeTileSink(self, tilesink, iteration_id):
        pass

    def collectResult(self, result):
        pass


def create_argparser():
    argparser = argparse.ArgumentParser(
        prog='Algorithm Progression',
        description='Apply an algorithm to an input image '
                    'for every parameter set in a given parameter space',
    )
    argparser.add_argument(
        'algorithm_code',
        choices=algorithms.ALGORITHM_CODES.keys(),
        help='Code to specify which of the available algorithms should be used',
    )
    argparser.add_argument('input_filename', help='Path to an image to use as input')
    argparser.add_argument(
        'output_filename',
        help='Name for output file or directory',
    )
    argparser.add_argument(
        '-w',
        '--num_workers',
        required=False,
        default=-1,
        type=int,
        help='Number of workers to use for processing algorithm iterations',
    )
    argparser.add_argument(
        '--multiprocessing',
        '--process',
        '--mp',
        action='store_true',
        help='Use multiprocessing for workers',
    )
    argparser.add_argument(
        '--threading',
        '--thread',
        '--mt',
        dest='multiprocessing',
        action='store_false',
        help='Use threading for workers',
    )
    argparser.add_argument(
        '--overlay',
        action='store_true',
        help='Overlay algorithm results on top of source data.',
    )
    argparser.add_argument(
        '--lossy',
        action='store_true',
        help='Store tiff files with lossy compression.',
    )
    argparser.add_argument(
        '--sink',
        required=False,
        default='zarr',
        help='Either zarr, multizarr, or multivips.',
    )
    argparser.add_argument(
        '--scale',
        required=False,
        default=1,
        type=float,
        help='Only process a lower resolution version of the source data.  '
        'Values greater than 1 reduce the size of the data processed.',
    )
    argparser.add_argument(
        '--dedup',
        action='store_true',
        help='If specified and the destination is a tiff file, rewrite the '
        'output with the dedup option.  This may make a smaller output tiff '
        'file at the cost of a substainally longer combination tile.',
    )
    argparser.add_argument(
        '-p',
        '--param',
        action='append',
        required=False,
        help='A parameter to pass to the algorithm; instead of using the '
             'default value, Pass every item in the number space, specified '
             'as `--param=param_name,[axis_name,]start,end,num_items[,open]`',
    )
    return argparser


def main(argv):
    argparser = create_argparser()
    args = argparser.parse_args(argv[1:])
    if args.num_workers < 1:
        args.num_workers = large_image.config.cpu_count(False)
    if os.environ.get('VIPS_CONCURRENCY') is None:
        os.environ['VIPS_CONCURRENCY'] = str(max(
            1, large_image.config.cpu_count(False) // args.num_workers))
    if args.multiprocessing and os.environ.get('LARGE_IMAGE_CACHE_PYTHON_MEMORY_PORTION') is None:
        os.environ['LARGE_IMAGE_CACHE_PYTHON_MEMORY_PORTION'] = str(32 * args.num_workers)

    algorithm_code = args.algorithm_code
    input_filename = args.input_filename
    input_params = {}
    defaultAxes = ['z', 'c', 't']
    axesUsed = set()
    for p in args.param or []:
        parts = [i.strip() for i in p.split(',')]
        rangevals = (parts[1:] if parts[1].isdigit() else parts[2:]) + ['']
        input_params[parts[0]] = {
            'param': parts[0],
            'axis': (
                (defaultAxes[0] if len(defaultAxes) else parts[0])
                if parts[1].isdigit() else parts[1]),
            'range': np.linspace(
                float(rangevals[0]), float(rangevals[1]), int(rangevals[2]),
                endpoint=rangevals[3].lower() not in {'open', 'true', 'on', 'yes', 't'}),
        }
        axesUsed.add(input_params[parts[0]]['axis'].lower())
        if input_params[parts[0]]['axis'].lower() in defaultAxes:
            defaultAxes.remove(input_params[parts[0]]['axis'].lower())

    if not Path(input_filename).exists():
        msg = f'Cannot locate file {input_filename}.'
        raise ValueError(msg)

    algorithm = algorithms.ALGORITHM_CODES[algorithm_code]
    sig = inspect.signature(algorithm)

    params = {
        param.name: (
            input_params[param.name]
            if param.name in input_params
            else {
                'param': param.name,
                'axis': getattr(param, 'axis', param.name),
                'range': [param.default]}
        )
        for param in sig.parameters.values() if param.name != 'data'
    }

    # Use args.sink to pick class
    cls = {
        'multivips': SweepAlgorithmMultiVips,
        'zarr': SweepAlgorithmZarr,
        'multizarr': SweepAlgorithmMultiZarr,
    }[args.sink]

    sweep = cls(algorithm, input_filename, params, input_params,
                args.output_filename, args.num_workers, args.multiprocessing,
                args.overlay, args.lossy, args.scale, args.dedup)
    sweep.run()
    if (args.dedup and args.sink in {'zarr'} and
            os.path.splitext(args.output_filename)[1] in {'.tif', '.tiff'}):
        print('Rewriting with dedup')
        starttime = time.time()
        ti = tifftools.read_tiff(args.output_filename)
        tifftools.write_tiff(ti, args.output_filename, allowExisting=True,
                             ifdsFirst=True, dedup=True)
        print(f'Rewrite time {time.time() - starttime:5.3f}')


if __name__ == '__main__':
    main(sys.argv)
