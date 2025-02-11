import asyncio
import os
from urllib.parse import parse_qs, urlparse

import aiohttp
import pytest

import large_image

try:
    import ipyleaflet  # noqa: F401
    import IPython  # noqa: F401
    import tornado  # noqa: F401
except ImportError:  # pragma: no cover
    pytest.skip(reason='Requires ipyleaflet, tornado, IPython', allow_module_level=True)


def testJupyterIpyleafletGeospatial():
    testDir = os.path.dirname(os.path.realpath(__file__))
    imagePath = os.path.join(testDir, 'test_files', 'rgb_geotiff.tiff')
    source = large_image.open(imagePath, projection='EPSG:3857')
    assert source.geospatial
    assert source.projection
    source._ipython_display_()  # smoke test
    # Run twice to make sure launched only once
    port = source._jupyter_server_manager.port
    source._ipython_display_()  # smoke test
    assert source._jupyter_server_manager.port == port


@pytest.mark.asyncio
async def testJupyterIpyleafletMultiFrame():
    testDir = os.path.dirname(os.path.realpath(__file__))
    imagePath = os.path.join(testDir, 'test_files', 'multi_channels.yml')
    source = large_image.open(imagePath, projection='EPSG:3857')
    assert source.frames

    # get display in same method as _ipython_display_
    display = source._map.make_map(
        source.metadata, source.as_leaflet_layer(), source.getCenter(srs='EPSG:4326'),
    )
    # ensure first child is frame selector widget
    assert display.children[0].__class__.__name__ == 'FrameSelector'
    frame_selector = display.children[0]

    # test update_frame
    expected_query_keys = {'x', 'y', 'z', 'encoding', 'repr'}
    parsed_url = urlparse(source._map._layer.url)
    query = parse_qs(parsed_url.query)
    assert set(query.keys()) == expected_query_keys
    source._map.update_frame(frame=2, style=dict(band=2))
    expected_query_keys.add('frame')
    expected_query_keys.add('style')
    parsed_url = urlparse(source._map._layer.url)
    query = parse_qs(parsed_url.query)
    assert set(query.keys()) == expected_query_keys
    assert query.get('frame') == ['2']
    assert query.get('style') == ['{"band": 2}']

    # test get_frame_histogram
    expected_histogram_keys = {
        'min', 'max', 'mean',
        'stdev', 'range', 'hist',
        'bins', 'bin_edges', 'density', 'samples',
    }
    assert frame_selector.frameHistograms == {}
    source._map.get_frame_histogram(dict(frame=2))
    await asyncio.sleep(0.5)
    histograms = frame_selector.frameHistograms
    assert set(histograms.keys()) == {2}
    assert len(histograms.get(2)) == 1
    assert set(histograms.get(2)[0].keys()) == expected_histogram_keys


@pytest.mark.asyncio
async def testJupyterIpyleaflet():
    testDir = os.path.dirname(os.path.realpath(__file__))
    imagePath = os.path.join(testDir, 'test_files', 'test_orient0.tif')
    source = large_image.open(imagePath)
    source._ipython_display_()  # smoke test
    port = source._jupyter_server_manager.port

    async def fetch(url):
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                return response

    r = await fetch(f'http://localhost:{port}/tile?z=0&x=0&y=0&encoding=png')
    r.raise_for_status()
    assert r.content
    r = await fetch(f'http://localhost:{port}/metadata')
    r.raise_for_status()
    assert r.content


def testJupyterIpyleafletMapRegion():
    from ipyleaflet import DrawControl

    testDir = os.path.dirname(os.path.realpath(__file__))
    imagePath = os.path.join(testDir, 'test_files', 'test_orient0.tif')
    source = large_image.open(imagePath)
    display = source._map.make_map(
        source.metadata, source.as_leaflet_layer(), source.getCenter(srs='EPSG:4326'),
    )
    assert len(display.children)
    m = display.children[0]
    assert len(m.controls)

    height = source.metadata['sizeY']
    xmin, xmax, ymin, ymax = 10, 90, 30, 100
    x, y = 50, 100
    expected = f'<div>Box X Range: [{xmin}, {xmax}]</div>'
    expected += f'<div>Box Y Range: [{ymin}, {ymax}]</div>'
    expected += f'<div>ROI: [{xmin}, {ymin}, {xmax - xmin}, {ymax - ymin}]</div>'

    rectangle = [[
        [xmin, height - ymax],
        [xmin, height - ymin],
        [xmax, height - ymax],
        [xmax, height - ymin],
    ]]
    for control in m.controls:
        if isinstance(control, DrawControl):
            control.data = [
                dict(geometry=dict(coordinates=rectangle)),
            ]
    for callback in m._interaction_callbacks.callbacks:
        callback(type='click', coordinates=[y, x])
    assert source._map.info_label.value == expected


def testJupyterIpyleafletMapGeospatialRegion():
    from ipyleaflet import DrawControl

    testDir = os.path.dirname(os.path.realpath(__file__))
    imagePath = os.path.join(testDir, 'test_files', 'rgb_geotiff.tiff')
    source = large_image.open(imagePath, projection='EPSG:3857')
    display = source._map.make_map(
        source.metadata, source.as_leaflet_layer(), source.getCenter(srs='EPSG:4326'),
    )
    assert len(display.children)
    m = display.children[0]
    assert len(m.controls)

    lonmin, lonmax, latmin, latmax = -118, -116, 32.5, 34
    lon, lat = -117, 33
    roi = [11562, 7156, 52322, 46301]
    expected = f'<div>Box Lon Range: [{lonmin}, {lonmax}]</div>'
    expected += f'<div>Box Lat Range: [{latmin}, {latmax}]</div>'
    expected += f'<div>ROI: {roi}</div>'

    rectangle = [[
        [lonmin, latmin],
        [lonmin, latmax],
        [lonmax, latmax],
        [lonmax, latmin],
    ]]
    for control in m.controls:
        if isinstance(control, DrawControl):
            control.data = [
                dict(geometry=dict(coordinates=rectangle)),
            ]
    for callback in m._interaction_callbacks.callbacks:
        callback(type='click', coordinates=[lat, lon])
    assert source._map.info_label.value == expected
