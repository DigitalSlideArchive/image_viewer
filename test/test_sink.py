import subprocess
from multiprocessing.pool import Pool, ThreadPool
from os import sys

import large_image_source_test
import large_image_source_zarr
import numpy as np
import pytest
from PIL import Image

import large_image
from large_image.constants import NEW_IMAGE_PATH_FLAG
from large_image.tilesource.resample import ResampleMethod

TMP_DIR = 'tmp/zarr_sink'
FILE_TYPES = [
    'tiff',
    'sqlite',
    'db',
    'zip',
    'zarr',
]


def copyFromSource(source, sink):
    metadata = source.getMetadata()
    for frame in metadata.get('frames', []):
        for tile in source.tileIterator(frame=frame['Frame'], format='numpy'):
            t = tile['tile']
            x, y = tile['x'], tile['y']
            kwargs = {
                'z': frame['IndexZ'],
                'c': frame['IndexC'],
            }
            sink.addTile(t, x=x, y=y, **kwargs)


def testNew():
    sink = large_image_source_zarr.new()
    assert sink.metadata['levels'] == 0
    assert sink.getRegion(format='numpy')[0].shape[:2] == (0, 0)


def testBasicAddTile():
    sink = large_image_source_zarr.new()
    sink.addTile(np.random.random((10, 10)), 0, 0)
    sink.addTile(np.random.random((10, 10, 2)), 10, 0)

    metadata = sink.getMetadata()
    assert metadata.get('levels') == 1
    assert metadata.get('sizeX') == 20
    assert metadata.get('sizeY') == 10
    assert metadata.get('bandCount') == 2
    assert metadata.get('dtype') == 'float64'


def testAddTileWithMask():
    sink = large_image_source_zarr.new()
    tile0 = np.random.random((10, 10))
    sink.addTile(tile0, 0, 0)
    orig = sink.getRegion(format='numpy')[0]
    tile1 = np.random.random((10, 10))
    sink.addTile(tile1, 0, 0, mask=np.random.random((10, 10)) > 0.5)
    cur = sink.getRegion(format='numpy')[0]
    assert (tile0 == orig[:, :, 0]).all()
    assert not (tile1 == orig[:, :, 0]).all()
    assert not (tile0 == cur[:, :, 0]).all()
    assert not (tile1 == cur[:, :, 0]).all()


def testAddTileWithLevel():
    sink = large_image_source_zarr.new()
    tile0 = np.random.random((100, 100))
    sink.addTile(tile0, 0, 0)
    arrays = dict(sink._zarr.arrays())
    assert arrays.get('0') is not None
    assert arrays.get('0').shape == (100, 100, 1)

    tile1 = np.random.random((10, 10))
    sink.addTile(tile1, 0, 0, level=1)
    arrays = dict(sink._zarr.arrays())
    assert arrays.get('0') is not None
    assert arrays.get('0').shape == (100, 100, 1)
    assert arrays.get('1') is not None
    assert arrays.get('1').shape == (10, 10, 1)

    tile1 = np.random.random((100, 100))
    sink.addTile(tile1, 0, 100)
    arrays = dict(sink._zarr.arrays())
    assert arrays.get('0') is not None
    assert arrays.get('0').shape == (200, 100, 1)
    # previously written levels should be cleared after changing level 0 data
    assert arrays.get('1') is None


def testExtraAxis():
    sink = large_image_source_zarr.new()
    sink.addTile(np.random.random((256, 256)), 0, 0, z=1)
    metadata = sink.getMetadata()
    assert metadata.get('bandCount') == 1
    assert len(metadata.get('frames')) == 2


@pytest.mark.parametrize('file_type', FILE_TYPES)
def testCrop(file_type, tmp_path):
    output_file = tmp_path / f'test.{file_type}'
    sink = large_image_source_zarr.new()

    # add tiles with some overlap
    sink.addTile(np.random.random((10, 10)), 0, 0)
    sink.addTile(np.random.random((10, 10)), 8, 0)
    sink.addTile(np.random.random((10, 10)), 0, 8)
    sink.addTile(np.random.random((10, 10)), 8, 8)

    region, _ = sink.getRegion(format='numpy')
    shape = region.shape
    assert shape == (18, 18, 1)

    sink.crop = (2, 2, 10, 10)

    # crop only applies when using write
    sink.write(output_file)
    if file_type == 'zarr':
        output_file /= '.zattrs'
    written = large_image.open(output_file)
    region, _ = written.getRegion(format='numpy')
    shape = region.shape
    assert shape == (10, 10, 1)


@pytest.mark.parametrize('file_type', FILE_TYPES)
def testImageCopySmallFileTypes(file_type, tmp_path):
    output_file = tmp_path / f'test.{file_type}'
    sink = large_image_source_zarr.new()
    source = large_image_source_test.TestTileSource(
        fractal=True,
        tileWidth=128,
        tileHeight=128,
        sizeX=512,
        sizeY=1024,
        frames='c=2,z=3',
    )
    copyFromSource(source, sink)

    metadata = sink.getMetadata()
    assert metadata.get('sizeX') == 512
    assert metadata.get('sizeY') == 1024
    assert metadata.get('dtype') == 'uint8'
    assert metadata.get('levels') == 2
    assert metadata.get('bandCount') == 3
    assert len(metadata.get('frames')) == 6

    sink.write(output_file)
    if file_type == 'zarr':
        output_file /= '.zattrs'
    written = large_image.open(output_file)

    new_metadata = written.getMetadata()
    assert new_metadata.get('sizeX') == 512
    assert new_metadata.get('sizeY') == 1024
    assert new_metadata.get('dtype') == 'uint8'
    assert new_metadata.get('levels') == 2 or new_metadata.get('levels') == 3
    assert new_metadata.get('bandCount') == 3
    assert len(new_metadata.get('frames')) == 6


@pytest.mark.parametrize('resample_method', [
    ResampleMethod.PIL_LANCZOS,
    ResampleMethod.NP_NEAREST,
])
def testImageCopySmallMultiband(resample_method, tmp_path):
    output_file = tmp_path / f'test_{resample_method}.db'
    sink = large_image_source_zarr.new()
    bands = (
        'red=0-255,green=0-255,blue=0-255,'
        'ir1=0-255,ir2=0-255,gray=0-255,other=0-255'
    )
    source = large_image_source_test.TestTileSource(
        fractal=True,
        tileWidth=128,
        tileHeight=128,
        sizeX=512,
        sizeY=1024,
        frames='c=2,z=3',
        bands=bands,
    )
    copyFromSource(source, sink)

    metadata = sink.getMetadata()
    assert metadata.get('sizeX') == 512
    assert metadata.get('sizeY') == 1024
    assert metadata.get('dtype') == 'uint8'
    assert metadata.get('levels') == 2
    assert metadata.get('bandCount') == 7
    assert len(metadata.get('frames')) == 6

    sink.write(output_file, resample=resample_method)
    written = large_image.open(output_file)
    new_metadata = written.getMetadata()

    assert new_metadata.get('sizeX') == 512
    assert new_metadata.get('sizeY') == 1024
    assert new_metadata.get('dtype') == 'uint8'
    assert new_metadata.get('levels') == 2 or new_metadata.get('levels') == 3
    assert new_metadata.get('bandCount') == 7
    assert len(new_metadata.get('frames')) == 6

    written_arrays = dict(written._zarr.arrays())
    assert len(written_arrays) == written.levels
    assert written_arrays.get('0') is not None
    assert written_arrays.get('0').shape == (2, 3, 1024, 512, 7)
    assert written_arrays.get('1') is not None
    assert written_arrays.get('1').shape == (2, 3, 512, 256, 7)


@pytest.mark.parametrize('resample_method', list(ResampleMethod))
def testImageCopySmallDownsampling(resample_method, tmp_path):
    output_file = tmp_path / f'test_{resample_method}.db'
    sink = large_image_source_zarr.new()
    source = large_image_source_test.TestTileSource(
        fractal=True,
        tileWidth=128,
        tileHeight=128,
        sizeX=511,
        sizeY=1023,
        frames='c=2,z=3',
    )
    copyFromSource(source, sink)

    sink.write(output_file, resample=resample_method)
    written = large_image.open(output_file)

    written_arrays = dict(written._zarr.arrays())
    assert len(written_arrays) == written.levels
    assert written_arrays.get('0') is not None
    assert written_arrays.get('0').shape == (2, 3, 1023, 511, 3)
    assert written_arrays.get('1') is not None
    assert written_arrays.get('1').shape == (2, 3, 512, 256, 3)

    sample_region, _format = written.getRegion(
        region=dict(top=252, bottom=260, left=0, right=4),
        output=dict(maxWidth=2, maxHeight=4),
        format='numpy',
    )
    assert sample_region.shape == (4, 2, 3)
    white_mask = (sample_region[..., 0] == 255).flatten().tolist()

    expected_masks = {
        ResampleMethod.PIL_NEAREST: [
            # expect any of the four variations, this will depend on version
            [True, False, True, False, True, True, True, False],  # upper left
            [True, False, True, True, True, False, True, False],  # lower left
            [True, False, False, True, True, True, False, False],  # upper right
            [False, False, True, True, False, True, True, False],  # lower right
        ],
        ResampleMethod.PIL_LANCZOS:
        [[False, False, False, False, False, False, False, False]],
        ResampleMethod.PIL_BILINEAR:
        [[False, False, False, False, False, False, False, False]],
        ResampleMethod.PIL_BICUBIC:
        [[False, False, False, False, False, False, False, False]],
        ResampleMethod.PIL_BOX:
        [[False, False, False, False, False, False, False, False]],
        ResampleMethod.PIL_HAMMING:
        [[False, False, False, False, False, False, False, False]],
        ResampleMethod.NP_MEAN:
        [[False, False, False, False, False, False, False, False]],
        ResampleMethod.NP_MEDIAN:
        [[True, False, True, True, True, True, True, False]],
        ResampleMethod.NP_MODE:
        [[True, False, True, True, True, True, True, False]],
        ResampleMethod.NP_MAX:
        [[True, False, True, True, True, True, True, False]],
        ResampleMethod.NP_MIN:
        [[False, False, False, False, False, False, False, False]],
        ResampleMethod.NP_NEAREST:
        [[True, False, True, False, True, True, True, False]],
        ResampleMethod.NP_MAX_COLOR:
        [[True, False, True, True, True, True, True, False]],
        ResampleMethod.NP_MIN_COLOR:
        [[False, False, False, False, False, False, False, False]],
    }

    assert white_mask in expected_masks[resample_method]


def testCropAndDownsample(tmp_path):
    output_file = tmp_path / 'cropped.db'
    sink = large_image_source_zarr.new()

    # add tiles with some overlap to multiple frames
    num_frames = 4
    num_bands = 5
    for z in range(num_frames):
        sink.addTile(np.random.random((1000, 1000, num_bands)), 0, 0, z=z)
        sink.addTile(np.random.random((1000, 1000, num_bands)), 950, 0, z=z)
        sink.addTile(np.random.random((1000, 1000, num_bands)), 0, 900, z=z)
        sink.addTile(np.random.random((1000, 1000, num_bands)), 950, 900, z=z)

    current_arrays = dict(sink._zarr.arrays())
    assert len(current_arrays) == 1
    assert current_arrays.get('0') is not None
    assert current_arrays.get('0').shape == (num_frames, 1900, 1950, num_bands)

    sink.crop = (50, 100, 1825, 1800)
    sink.write(output_file)
    written = large_image_source_zarr.open(output_file)
    written_arrays = dict(written._zarr.arrays())

    assert len(written_arrays) == written.levels
    assert written_arrays.get('0') is not None
    assert written_arrays.get('0').shape == (num_frames, 1800, 1825, num_bands)
    assert written_arrays.get('1') is not None
    assert written_arrays.get('1').shape == (num_frames, 900, 913, num_bands)
    assert written_arrays.get('2') is not None
    assert written_arrays.get('2').shape == (num_frames, 450, 456, num_bands)


def testCropToTiff(tmp_path):
    output_file = tmp_path / 'cropped.tiff'
    sink = large_image_source_zarr.new()

    # add tiles with some overlap to multiple frames
    num_frames = 1
    num_bands = 3
    for z in range(num_frames):
        sink.addTile(np.random.random((1000, 1000, num_bands)), 0, 0, z=z)
        sink.addTile(np.random.random((1000, 1000, num_bands)), 950, 0, z=z)
        sink.addTile(np.random.random((1000, 1000, num_bands)), 0, 900, z=z)
        sink.addTile(np.random.random((1000, 1000, num_bands)), 950, 900, z=z)

    current_arrays = dict(sink._zarr.arrays())
    assert len(current_arrays) == 1
    assert current_arrays.get('0') is not None
    assert current_arrays.get('0').shape == (num_frames, 1900, 1950, num_bands)

    sink.crop = (100, 50, 1800, 1825)
    sink.write(output_file)
    source = large_image.open(output_file)
    assert source.sizeX == 1800
    assert source.sizeY == 1825


def testMetadata(tmp_path):
    output_file = tmp_path / 'test.db'
    sink = large_image_source_zarr.new()

    description = 'random data image for testing internal metadata'
    channel_names = ['red', 'green', 'blue', 'IR', 'UV']
    channel_colors = ['FF0000', '00FF00', '0000FF', 'FFFF00', 'FF00FF']
    num_frames = 4
    num_bands = 5
    for z in range(num_frames):
        sink.addTile(np.random.random((1000, 1000, num_bands)), 0, 0, z=z)
        sink.addTile(np.random.random((1000, 1000, num_bands)), 950, 0, z=z)
        sink.addTile(np.random.random((1000, 1000, num_bands)), 0, 900, z=z)
        sink.addTile(np.random.random((1000, 1000, num_bands)), 950, 900, z=z)

    sink.imageDescription = description
    sink.channelNames = channel_names
    sink.channelColors = channel_colors
    sink.mm_x = 5
    sink.mm_y = 5

    sink.write(output_file)
    written = large_image_source_zarr.open(output_file)
    assert written._is_ome

    int_metadata = written.getInternalMetadata()
    base_metadata = int_metadata.get('zarr', {}).get('base')
    assert base_metadata is not None
    assert base_metadata['bioformats2raw.layout'] == 3

    multiscales = base_metadata.get('multiscales')
    assert multiscales is not None
    assert len(multiscales) == 1
    assert multiscales[0].get('version') == '0.5'
    assert NEW_IMAGE_PATH_FLAG in multiscales[0].get('name')

    axes = multiscales[0].get('axes')
    assert axes is not None
    assert len(axes) == 4
    assert {'name': 'z'} in axes
    assert {'name': 'y', 'type': 'space', 'unit': 'millimeter'} in axes
    assert {'name': 'x', 'type': 'space', 'unit': 'millimeter'} in axes
    assert {'name': 's', 'type': 'channel'} in axes

    datasets = multiscales[0].get('datasets')
    assert len(datasets) == 3
    for i, d in enumerate(datasets):
        assert d.get('path') == str(i)
        coord_transforms = d.get('coordinateTransformations')
        assert coord_transforms is not None
        assert len(coord_transforms) == 1
        assert coord_transforms[0].get('type') == 'scale'
        assert coord_transforms[0].get('scale') == [
            1.0, 5 * 2 ** i, 5 * 2 ** i, 1.0,
        ]

    nested_metadata = multiscales[0].get('metadata')
    assert nested_metadata is not None
    assert nested_metadata.get('description') == description
    assert nested_metadata.get('kwargs', {}).get('multichannel')

    omero = base_metadata.get('omero')
    assert omero is not None
    assert omero.get('id') == 1
    assert omero.get('version') == '0.5'
    assert NEW_IMAGE_PATH_FLAG in omero.get('name')

    channels = omero.get('channels')
    assert channels is not None
    assert len(channels) == num_bands
    for i, c in enumerate(channels):
        assert c.get('active')
        assert c.get('coefficient') == 1
        assert c.get('color') == channel_colors[i]
        assert c.get('family') == 'linear'
        assert not c.get('inverted')
        assert c.get('label') == channel_names[i]
        # window = c.get('window')
        # assert window is not None
        # # max should be nearly 1 and min should be nearly 0
        # assert math.ceil(window.get('end')) == 1
        # assert math.ceil(window.get('max')) == 1
        # assert math.floor(window.get('start')) == 0
        # assert math.floor(window.get('min')) == 0

    rdefs = omero.get('rdefs')
    assert rdefs is not None
    assert rdefs.get('model') == 'color'
    assert rdefs.get('defaultZ') == 0


def testChannelNames(tmp_path):
    output_file = tmp_path / 'test.db'
    sink = large_image_source_zarr.new()

    for c in range(5):
        sink.addTile(np.random.random((4, 4, 3)), c=c)

    sink.channelNames = ['a', 'b', 'c', 'd', 'e']
    sink.write(output_file)
    written = large_image.open(output_file)
    assert len(written.metadata['channels']) == 5


def testAddAssociatedImages(tmp_path):
    output_file = tmp_path / 'test.db'
    sink = large_image_source_zarr.new()

    num_frames = 4
    num_bands = 5
    for z in range(num_frames):
        sink.addTile(np.random.random((1000, 1000, num_bands)), 0, 0, z=z)
        sink.addTile(np.random.random((1000, 1000, num_bands)), 950, 0, z=z)
        sink.addTile(np.random.random((1000, 1000, num_bands)), 0, 900, z=z)
        sink.addTile(np.random.random((1000, 1000, num_bands)), 950, 900, z=z)

    image_sizes = [
        (200, 300, 3),
        (400, 500, 3),
        (600, 700, 3),
    ]

    for image_size in image_sizes:
        image_data = (np.random.random(image_size) * 255).astype(np.uint8)
        img = Image.fromarray(image_data)
        sink.addAssociatedImage(img)

    original_image_list = sink.getAssociatedImagesList()

    sink.write(output_file)
    written = large_image_source_zarr.open(output_file)
    written_image_list = written.getAssociatedImagesList()

    for image_list in [original_image_list, written_image_list]:
        assert len(image_list) == len(image_sizes)
        for i, image_name in enumerate(image_list):
            retrieved = sink._getAssociatedImage(image_name)
            expected_size = image_sizes[i]
            assert retrieved is not None
            assert isinstance(retrieved, Image.Image)
            # PIL Image size doesn't include bands and swaps x & y
            assert retrieved.size == (expected_size[1], expected_size[0])


def _add_tile_from_seed_data(sink, seed_data, position):
    tile = seed_data[
        position['z'],
        position['y'],
        position['x'],
        position['s'],
    ]
    sink.addTile(
        tile,
        position['x'].start,
        position['y'].start,
        z=position['z'],
    )


@pytest.mark.singular
def testConcurrency(tmp_path):
    output_file = tmp_path / 'test.db'
    max_workers = 5
    tile_size = (100, 100)
    target_shape = (4, 1000, 1000, 5)
    tile_positions = []
    seed_data = np.random.random(target_shape)

    for z in range(target_shape[0]):
        for y in range(int(target_shape[1] / tile_size[0])):
            for x in range(int(target_shape[2] / tile_size[1])):
                tile_positions.append({
                    'z': z,
                    'y': slice(y * tile_size[0], (y + 1) * tile_size[0]),
                    'x': slice(x * tile_size[1], (x + 1) * tile_size[1]),
                    's': slice(0, target_shape[3]),
                })

    for pool_class in [Pool, ThreadPool]:
        sink = large_image_source_zarr.new()
        # allocate space by adding last tile first
        _add_tile_from_seed_data(sink, seed_data, tile_positions[-1])
        with pool_class(max_workers) as pool:
            pool.starmap(_add_tile_from_seed_data, [
                (sink, seed_data, position)
                for position in tile_positions[:-1]
            ])
        sink.write(output_file)
        written = large_image_source_zarr.open(output_file)
        written_arrays = dict(written._zarr.arrays())
        data = np.array(written_arrays.get('0'))
        assert len(written_arrays) == written.levels
        assert data is not None
        assert data.shape == seed_data.shape
        assert np.allclose(data, seed_data)


def get_expected_metadata(axis_spec, frame_shape):
    return dict(
        levels=1,
        sizeY=frame_shape[0],
        sizeX=frame_shape[1],
        bandCount=frame_shape[2],
        frames=[],
        tileWidth=512,
        tileHeight=512,
        magnification=None,
        mm_x=0,
        mm_y=0,
        dtype='float64',
        channels=[f'Band {c + 1}' for c in range(len(axis_spec['c']['values']))],
        channelmap={f'Band {c + 1}': c for c in range(len(axis_spec['c']['values']))},
        IndexRange={
            f'Index{k.upper()}': len(v['values']) for k, v in axis_spec.items()
        },
        IndexStride={
            f'Index{k.upper()}': v['stride'] for k, v in axis_spec.items()
        },
        **{
            f'Value{k.upper()}': dict(
                values=v.get('all_values', v['values']),
                units=v['units'],
                uniform=v['uniform'],
                min=min(v.get('all_values', v['values'])),
                max=max(v.get('all_values', v['values'])),
                datatype=v['dtype'],
            ) for k, v in axis_spec.items()
        },
    )


def compare_metadata(actual, expected):
    assert type(actual) is type(expected)
    if isinstance(actual, list):
        for i, v in enumerate(actual):
            compare_metadata(v, expected[i])
    elif isinstance(actual, dict):
        assert len(actual.keys()) == len(expected.keys())
        for k, v in actual.items():
            compare_metadata(v, expected[k])
    else:
        assert actual == expected


@pytest.mark.parametrize('use_add_tile_args', [True, False])
def testFrameValuesSmall(use_add_tile_args, tmp_path):
    output_file = tmp_path / 'test.db'
    sink = large_image_source_zarr.new()

    frame_shape = (300, 400, 3)
    axis_spec = dict(c=dict(
        values=['r', 'g', 'b'],
        uniform=True,
        units='channel',
        stride=1,
        dtype='str32',
    ))
    expected_metadata = get_expected_metadata(axis_spec, frame_shape)

    sink.frameAxes = list(axis_spec.keys())
    sink.frameUnits = {
        k: v['units'] for k, v in axis_spec.items()
    }
    frame_values_shape = [
        *[len(v['values']) for v in axis_spec.values()],
        len(axis_spec),
    ]
    frame_values = np.empty(frame_values_shape, dtype=object)

    frame = 0
    index = 0
    for c, c_value in enumerate(axis_spec['c']['values']):
        add_tile_args = dict(c=c, axes=['c', 'y', 'x', 's'])
        if use_add_tile_args:
            add_tile_args.update(c_value=c_value)
        else:
            frame_values[c] = [c_value]
        random_tile = np.random.random(frame_shape)
        sink.addTile(random_tile, 0, 0, **add_tile_args)
        expected_metadata['frames'].append(
            dict(
                Frame=frame,
                Index=index,
                IndexC=c,
                ValueC=c_value,
                Channel=f'Band {c + 1}',
            ),
        )
        frame += 1
    index += 1

    if not use_add_tile_args:
        sink.frameValues = frame_values
    compare_metadata(dict(sink.getMetadata()), expected_metadata)

    sink.write(output_file)
    written = large_image_source_zarr.open(output_file)
    compare_metadata(dict(written.getMetadata()), expected_metadata)


@pytest.mark.parametrize('use_add_tile_args', [True, False])
def testFrameValues(use_add_tile_args, tmp_path):
    output_file = tmp_path / 'test.db'
    sink = large_image_source_zarr.new()

    frame_shape = (300, 400, 3)
    axis_spec = dict(
        z=dict(
            values=[2, 4, 6, 8],
            uniform=True,
            units='meter',
            stride=9,
            dtype='int64',
        ),
        t=dict(
            values=[10.0, 20.0, 30.0],
            all_values=(
                [10.00] * 3 +
                [20.00] * 3 +
                [30.00] * 3 +
                [10.01] * 3 +
                [20.01] * 3 +
                [30.01] * 3 +
                [10.02] * 3 +
                [20.02] * 3 +
                [30.02] * 3 +
                [10.03] * 3 +
                [20.03] * 3 +
                [30.03] * 3
            ),
            uniform=False,
            units='millisecond',
            stride=3,
            dtype='float64',
        ),
        c=dict(
            values=['r', 'g', 'b'],
            uniform=True,
            units='channel',
            stride=1,
            dtype='str32',
        ),
    )
    expected_metadata = get_expected_metadata(axis_spec, frame_shape)

    sink.frameAxes = list(axis_spec.keys())
    sink.frameUnits = {
        k: v['units'] for k, v in axis_spec.items()
    }
    frame_values_shape = [
        *[len(v['values']) for v in axis_spec.values()],
        len(axis_spec),
    ]
    frame_values = np.empty(frame_values_shape, dtype=object)

    frame = 0
    index = 0
    for z, z_value in enumerate(axis_spec['z']['values']):
        for t, t_value in enumerate(axis_spec['t']['values']):
            if not axis_spec['t']['uniform']:
                t_value += 0.01 * z
            for c, c_value in enumerate(axis_spec['c']['values']):
                add_tile_args = dict(z=z, t=t, c=c, axes=['z', 't', 'c', 'y', 'x', 's'])
                if use_add_tile_args:
                    add_tile_args.update(z_value=z_value, t_value=t_value, c_value=c_value)
                else:
                    frame_values[z, t, c] = [z_value, t_value, c_value]
                random_tile = np.random.random(frame_shape)
                sink.addTile(random_tile, 0, 0, **add_tile_args)
                expected_metadata['frames'].append(
                    dict(
                        Frame=frame,
                        Index=index,
                        IndexZ=z,
                        ValueZ=z_value,
                        IndexT=t,
                        ValueT=t_value,
                        IndexC=c,
                        ValueC=c_value,
                        Channel=f'Band {c + 1}',
                    ),
                )
                frame += 1
            index += 1

    if not use_add_tile_args:
        sink.frameValues = frame_values
    compare_metadata(dict(sink.getMetadata()), expected_metadata)

    sink.write(output_file)
    written = large_image_source_zarr.open(output_file)
    compare_metadata(dict(written.getMetadata()), expected_metadata)


def testFrameValuesEdgeCases(tmp_path):
    # case 1
    ts = large_image.new()
    ts.addTile(np.zeros((100, 100, 3)), x=0, y=0, c=0, z=0, z_value=1, c_value='DAPI')
    assert ts.metadata.get('bandCount') == 3
    ts.addTile(np.zeros((100, 100, 3)), x=0, y=0, c=1, z=0, z_value=1, c_value='CD4')

    # case 2
    ts = large_image.new()
    ts.addTile(np.zeros((100, 100, 1)), x=0, y=0, c=0, z=0, z_value=1, c_value='DAPI')
    ts.addTile(np.zeros((100, 100, 1)), x=0, y=0, c=1, z=0, z_value=1, c_value='CD4')
    metadata = ts.getMetadata()
    assert metadata.get('frames') is not None
    assert len(metadata.get('frames')) == 2

    # case 3
    ts = large_image.new()
    ts.addTile(np.zeros((100, 100, 3)), x=0, y=0, c=0, z=0, z_value=1, c_value='DAPI')
    ts.addTile(np.zeros((100, 100, 3)), x=0, y=0, c=0, z=1, z_value=3.2, c_value='DAPI')
    ts.addTile(np.zeros((100, 100, 3)), x=0, y=0, c=0, z=2, z_value=6.3, c_value='DAPI')
    ts.addTile(np.zeros((100, 100, 3)), x=0, y=0, c=1, z=2, z_value=6.4, c_value='CD4')
    ts.addTile(np.zeros((100, 100, 3)), x=0, y=0, c=1, z=1, z_value=3.1, c_value='CD4')
    ts.addTile(np.zeros((100, 100, 3)), x=0, y=0, c=0, z=1, z_value=1.1)

    # case 4
    ts = large_image.new()
    ts.addTile(np.zeros((100, 100, 3)), x=0, y=0, c=0, z=0, z_value=1, c_value='DAPI')
    ts.addTile(np.zeros((100, 100, 3)), x=0, y=0, c=0, z=1, z_value=3.2, c_value='DAPI')
    ts.addTile(np.zeros((100, 100, 3)), x=0, y=0, c=0, z=2, z_value=6.3, c_value='DAPI')
    ts.addTile(np.zeros((100, 100, 3)), x=0, y=0, c=1, z=2, z_value=6.4, c_value='CD4')
    ts.addTile(np.zeros((100, 100, 3)), x=0, y=0, c=1, z=1, z_value=3.1, c_value='CD4')
    ts.addTile(np.zeros((100, 100, 3)), x=0, y=0, c=0, z=1, z_value=1.1)
    frame_metadata = ts.metadata.get('frames', [])
    assert len(frame_metadata) == 6

    for frame in frame_metadata:
        for value in frame.values():
            # ensure that values are cast to native python types
            assert not isinstance(value, np.generic)


@pytest.mark.singular
def testSubprocess(tmp_path):
    sink = large_image_source_zarr.new()
    path = sink.largeImagePath
    subprocess.run([sys.executable, '-c', """import large_image_source_zarr
import numpy as np
sink = large_image_source_zarr.open('%s')
sink.addTile(np.ones((1, 1, 1)), x=2047, y=2047, t=5, z=2)
""" % path], capture_output=True, text=True, check=True)
    sink.addTile(np.ones((1, 1, 1)), x=5000, y=4095, t=0, z=4)

    assert sink.metadata['IndexRange']['IndexZ'] == 5
    assert sink.getRegion(
        region=dict(left=2047, top=2047, width=1, height=1),
        format='numpy',
        frame=17,
    )[0] == 1
    assert sink.getRegion(
        region=dict(left=5000, top=4095, width=1, height=1),
        format='numpy',
        frame=24,
    )[0] == 1
    assert sink.sizeX == 5001
