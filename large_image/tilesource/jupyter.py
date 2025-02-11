"""A vanilla REST interface to a ``TileSource``.

This is intended for use in JupyterLab and not intended to be used as a full
fledged REST API. Only two endpoints are exposed with minimal options:

* `/metadata`
* `/tile?z={z}&x={x}&y={y}&encoding=png`

We use Tornado because it is Jupyter's web server and will not require Jupyter
users to install any additional dependencies. Also, Tornado doesn't require us
to manage a separate thread for the web server.

Please note that this webserver will not work with Classic Notebook and will
likely lead to crashes. This is only for use in JupyterLab.

"""
import ast
import asyncio
import importlib.util
import json
import os
import threading
import weakref
from typing import Any, Dict, List, Optional, Tuple, Union, cast
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse

import numpy as np

import large_image
from large_image.exceptions import TileSourceXYZRangeError
from large_image.tilesource.utilities import JSONDict

ipyleafletPresent = importlib.util.find_spec('ipyleaflet') is not None
ipyvuePresent = importlib.util.find_spec('ipyvue') is not None
aiohttpPresent = importlib.util.find_spec('aiohttp') is not None


class IPyLeafletMixin:
    """Mixin class to support interactive visualization in JupyterLab.

    This class implements ``_ipython_display_`` with ``ipyleaflet`` to display
    an interactive image visualizer for the tile source in JupyterLab.

    Install `ipyleaflet <https://github.com/jupyter-widgets/ipyleaflet>`_ to
    interactively visualize tile sources in JupyterLab.

    For remote JupyterHub environments, you may need to configure the class
    variables ``JUPYTER_HOST`` or ``JUPYTER_PROXY``.

    If ``JUPYTER_PROXY`` is set, it overrides ``JUPYTER_HOST``.

    Use ``JUPYTER_HOST`` to set the host name of the machine such that the tile
    URL can be accessed at ``'http://{JUPYTER_HOST}:{port}'``.

    Use ``JUPYTER_PROXY`` to leverage ``jupyter-server-proxy`` to proxy the
    tile serving port through Jupyter's authenticated web interface.  This is
    useful in Docker and cloud JupyterHub environments.  You can set the
    environment variable ``LARGE_IMAGE_JUPYTER_PROXY`` to control the default
    value of ``JUPYTER_PROXY``.  If ``JUPYTER_PROXY`` is set to ``True``, the
    default will be ``'/proxy/`` which will work for most Docker Jupyter
    configurations. If in a cloud JupyterHub environment, this will get a bit
    more nuanced as the ``JUPYTERHUB_SERVICE_PREFIX`` may need to prefix the
    ``'/proxy/'``.  If set to ``'auto'``, an automatic value will be chosen
    through some effort to detect the environment.

    To programmatically set these values:

    .. code::

        from large_image.tilesource.jupyter import IPyLeafletMixin

        # Only set one of these values

        # Use a custom domain (avoids port proxying)
        IPyLeafletMixin.JUPYTER_HOST = 'mydomain'

        # Proxy in a standard JupyterLab environment
        IPyLeafletMixin.JUPYTER_PROXY = True  # defaults to `/proxy/`

        # Proxy in a cloud JupyterHub environment
        IPyLeafletMixin.JUPYTER_PROXY = '/jupyter/user/username/proxy/'
        # See if ``JUPYTERHUB_SERVICE_PREFIX`` is in the environment
        # variables to improve this

    """

    JUPYTER_HOST = '127.0.0.1'
    JUPYTER_PROXY: Union[str, bool] = os.environ.get('LARGE_IMAGE_JUPYTER_PROXY', 'auto')

    _jupyter_server_manager: Any

    def __init__(self, *args, **kwargs) -> None:
        self._jupyter_server_manager = None
        self._map = Map(ts=self)
        if ipyleafletPresent:
            self.to_map = self._map.to_map
            self.from_map = self._map.from_map

    def as_leaflet_layer(self, **kwargs) -> Any:
        # NOTE: `as_leaflet_layer` is supported by ipyleaflet.Map.add

        if self._jupyter_server_manager is None:
            # Must relaunch to ensure style updates work
            self._jupyter_server_manager = launch_tile_server(self)
        else:
            # Must update the source on the manager in case the previous reference is bad
            self._jupyter_server_manager.tile_source = self

        port = self._jupyter_server_manager.port

        if self.JUPYTER_PROXY == 'auto':
            self._autoJupyterProxy()
        if self.JUPYTER_PROXY and str(self.JUPYTER_PROXY).lower() in {'true', 'false'}:
            self.JUPYTER_PROXY = str(self.JUPYTER_PROXY).lower() == 'true'
        if self.JUPYTER_PROXY:
            if isinstance(self.JUPYTER_PROXY, str):
                base_url = f'{self.JUPYTER_PROXY.rstrip("/")}/{port}'
            else:
                base_url = f'/proxy/{port}'
        else:
            base_url = f'http://{self.JUPYTER_HOST}:{port}'

        # Use repr in URL params to prevent caching across sources/styles
        endpoint = f'tile?z={{z}}&x={{x}}&y={{y}}&encoding=png&repr={self!r}'
        return self._map.make_layer(
            self.metadata,  # type: ignore[attr-defined]
            f'{base_url}/{endpoint}')

    def _autoJupyterProxy(self):
        if importlib.util.find_spec('google') and importlib.util.find_spec('google.colab'):
            # colab intercepts localhost
            self.JUPYTER_PROXY = 'https://localhost'
        elif importlib.util.find_spec('jupyter_server_proxy'):
            self.JUPYTER_PROXY = True
        else:
            self.JUPYTER_PROXY = False

    # Only make _ipython_display_ available if ipyleaflet is installed
    if ipyleafletPresent:

        def _ipython_display_(self) -> Any:
            from IPython.display import display

            t = self.as_leaflet_layer()

            return display(self._map.make_map(
                self.metadata, t, self.getCenter(srs='EPSG:4326')))  # type: ignore[attr-defined]

        @property
        def iplmap(self) -> Any:
            """
            If using ipyleaflets, get access to the map object.
            """
            return self._map.map


class Map:
    """
    An IPyLeafletMap representation of a large image.
    """

    def __init__(
            self, *, ts: Optional[IPyLeafletMixin] = None,
            metadata: Optional[Dict] = None, url: Optional[str] = None,
            gc: Optional[Any] = None, id: Optional[str] = None,
            resource: Optional[str] = None) -> None:
        """
        Specify the large image to be used with the IPyLeaflet Map.  One of (a)
        a tile source, (b) metadata dictionary and tile url, (c) girder client
        and item or file id, or (d) girder client and resource path must be
        specified.

        :param ts: a TileSource.
        :param metadata: a metadata dictionary as returned by a tile source or
            a girder item/{id}/tiles endpoint.
        :param url: a slippy map template url to fetch tiles (e.g.,
            .../item/{id}/tiles/zxy/{z}/{x}/{y}?params=...)
        :param gc: an authenticated girder client.
        :param id: an item id that exists on the girder client.
        :param resource: a girder resource path of an item or file that exists
            on the girder client.
        """
        self._layer = self._map = self._metadata = self._frame_slider = None
        self._frame_histograms: Optional[Dict[int, Any]] = None
        self._ts = ts
        if (not url or not metadata) and gc and (id or resource):
            fileId = None
            if id is None:
                entry = gc.get('resource/lookup', parameters={'path': resource})
                if entry:
                    if entry.get('_modelType') == 'file':
                        fileId = entry['_id']
                    id = entry['itemId'] if entry.get('_modelType') == 'file' else entry['_id']
            if id:
                try:
                    metadata = gc.get(f'item/{id}/tiles')
                except Exception:
                    pass
                if metadata:
                    url = gc.urlBase + f'item/{id}/tiles' + '/zxy/{z}/{x}/{y}'
                    if metadata.get('geospatial'):
                        suffix = '?projection=EPSG:3857&encoding=PNG'
                        metadata = gc.get(f'item/{id}/tiles' + suffix)
                        if (cast(Dict, metadata).get('geospatial') and
                                cast(Dict, metadata).get('projection')):
                            url += suffix  # type: ignore[operator]
                    self._id = id
                else:
                    self._ts = self._get_temp_source(gc, cast(str, fileId or id))
        if url and metadata:
            self._metadata = metadata
            self._url = url
            self._layer = self.make_layer(metadata, url)
            self._map = self.make_map(metadata)

    if ipyleafletPresent:
        def _ipython_display_(self) -> Any:
            from IPython.display import display

            if self._map:
                return display(self._map)
            if self._ts:
                t = self._ts.as_leaflet_layer()
                return display(self._ts._map.make_map(
                    self._ts.metadata,  # type: ignore[attr-defined]
                    t,
                    self._ts.getCenter(srs='EPSG:4326')))  # type: ignore[attr-defined]

    def _get_temp_source(self, gc: Any, id: str) -> IPyLeafletMixin:
        """
        If the server isn't large_image enabled, download the file to view it.
        """
        import tempfile

        import large_image

        try:
            item = gc.get(f'item/{id}')
        except Exception:
            item = None
        if not item:
            file = gc.get(f'file/{id}')
        else:
            file = gc.get(f'item/{id}/files', parameters={'limit': 1})[0]
        self._tempfile = tempfile.NamedTemporaryFile(suffix='.' + file['name'].split('.', 1)[-1])
        gc.downloadFile(file['_id'], self._tempfile)
        return large_image.open(self._tempfile.name)

    def make_layer(self, metadata: Dict, url: str, **kwargs) -> Any:
        """
        Create an ipyleaflet tile layer given large_image metadata and a tile
        url.
        """
        from ipyleaflet import TileLayer

        self._geospatial = metadata.get('geospatial') and metadata.get('projection')
        if 'bounds' not in kwargs and not self._geospatial:
            kwargs = kwargs.copy()
            kwargs['bounds'] = [[0, 0], [metadata['sizeY'], metadata['sizeX']]]
        layer = TileLayer(
            url=url,
            # attribution='Tiles served with large-image',
            min_zoom=0,
            max_native_zoom=metadata['levels'] - 1,
            max_zoom=20,
            tile_size=metadata['tileWidth'],
            **kwargs,
        )
        self._layer = layer
        if not self._metadata:
            self._metadata = metadata
        return layer

    def make_map(
            self, metadata: Dict, layer: Optional[Any] = None,
            center: Optional[Tuple[float, float]] = None) -> Any:
        """
        Create an ipyleaflet map given large_image metadata, an optional
        ipyleaflet layer, and the center of the tile source.
        """
        from ipyleaflet import Map, basemaps, projections
        from ipywidgets import VBox

        try:
            default_zoom = metadata['levels'] - metadata['sourceLevels']
        except KeyError:
            default_zoom = 0

        self._geospatial = metadata.get('geospatial') and metadata.get('projection')

        if self._geospatial:
            # TODO: better handle other projections
            crs = projections.EPSG3857
        else:
            crs = dict(
                name='PixelSpace',
                custom=True,
                resolutions=[2 ** (metadata['levels'] - 1 - l) for l in range(20)],

                proj4def='+proj=longlat +axis=esu',
                bounds=[[0, 0], [metadata['sizeX'], metadata['sizeY']]],
                origin=[0, metadata['sizeY']],
            )
        layer = layer or self._layer

        if center is None:
            if 'bounds' in metadata and 'projection' in metadata:
                import pyproj

                bounds = metadata['bounds']
                center = (
                    (bounds['ymax'] + bounds['ymin']) / 2,
                    (bounds['xmax'] + bounds['xmin']) / 2,
                )
                transf = pyproj.Transformer.from_crs(
                    metadata['projection'], 'EPSG:4326', always_xy=True)
                center = tuple(transf.transform(center[1], center[0])[::-1])
            else:
                center = (metadata['sizeY'] / 2, metadata['sizeX'] / 2)

        children: List[Any] = []
        frames = metadata.get('frames')
        if frames is not None and ipyvuePresent and aiohttpPresent:
            from large_image.widgets.components import FrameSelector

            self.frame_selector = FrameSelector()
            self.frame_selector.imageMetadata = metadata
            self.frame_selector.updateFrameCallback = self.update_frame
            self.frame_selector.getFrameHistogram = self.get_frame_histogram
            children.append(self.frame_selector)

        m = Map(
            crs=crs,
            basemap=basemaps.OpenStreetMap.Mapnik if self._geospatial else layer,
            center=center,
            zoom=default_zoom,
            max_zoom=metadata['levels'] + 1,
            min_zoom=0,
            scroll_wheel_zoom=True,
            dragging=True,
            attribution_control=False,
        )
        m.layout.height = '50vh'
        if self._geospatial:
            m.add_layer(layer)
        self._map = m
        children.append(m)

        self.add_region_indicator()
        return VBox(children)

    def add_region_indicator(self):
        from ipyleaflet import DrawControl, FullScreenControl, Popup
        from ipywidgets import HTML

        metadata = self._metadata
        if self._map is None or metadata is None:
            return

        self.info_label = HTML()
        popup = Popup(child=self.info_label)
        popup.close_popup()
        draw_control = DrawControl(
            rectangle=dict(shapeOptions=dict(color='#19a7ff')),
            # enable drawing other shapes by specifying styling
            polygon=dict(),
            circle=dict(),
            polyline=dict(),
            circlemarker=dict(),
            rotate=False,
            cut=False,
            edit=False,
        )

        transformer = None
        if metadata.get('geospatial'):
            import pyproj

            transformer = pyproj.Transformer.from_crs(
                'EPSG:4326',
                metadata['projection'],
                always_xy=True,
            )

        def handle_interaction(**kwargs):
            coords = kwargs.get('coordinates')
            if self._map is None or metadata is None or coords is None:
                return
            x, y = [coords[1], coords[0]]
            interaction_type = kwargs.get('type')
            if interaction_type == 'click':
                for rectangle in draw_control.data:
                    rect_coords = rectangle.get('geometry', {}).get('coordinates', [[]])[0]
                    xmin, xmax = rect_coords[0][0], rect_coords[2][0]
                    ymin, ymax = rect_coords[0][1], rect_coords[1][1]
                    width, height = metadata['sizeX'], metadata['sizeY']
                    x_label, y_label = 'X', 'Y'
                    if (
                        x >= xmin and x <= xmax and
                        y >= ymin and y <= ymax
                    ):
                        x0, y0, x1, y1 = None, None, None, None
                        if transformer is not None:
                            x_label, y_label = 'Lon', 'Lat'
                            x0, y0 = transformer.transform(xmin, ymin)
                            x1, y1 = transformer.transform(xmax, ymax)
                            bounds = metadata['bounds']
                            x0, x1 = [
                                round((v - bounds['xmin']) /
                                      (bounds['xmax'] - bounds['xmin']) *
                                      width) for v in [x0, x1]
                            ]
                            y0, y1 = [
                                round((v - bounds['ymax']) /
                                      (bounds['ymin'] - bounds['ymax']) *
                                      height) for v in [y1, y0]
                            ]
                        else:
                            xmin, xmax = round(xmin), round(xmax)
                            ymin, ymax = round(height - ymax), round(height - ymin)
                            x0, y0, x1, y1 = xmin, ymin, xmax, ymax
                        self.info_label.value = f'<div>Box {x_label} Range: [{xmin}, {xmax}]</div>'
                        self.info_label.value += f'<div>Box {y_label} Range: [{ymin}, {ymax}]</div>'
                        if (
                            x0 >= 0 and y0 >= 0 and
                            x1 <= width and y1 <= height
                        ):
                            roi = [x0, y0, x1 - x0, y1 - y0]
                            self.info_label.value += f'<div>ROI: {roi}</div>'
                        popup.open_popup((rect_coords[1][1], (xmax - xmin) / 2 + xmin))
                        if popup not in self._map.layers:
                            self._map.add(popup)

        def handle_draw(target, action, geo_json):
            if action == 'deleted':
                popup.close_popup()

        draw_control.on_draw(handle_draw)
        self._map.on_interaction(handle_interaction)
        self._map.add(draw_control)
        self._map.add(FullScreenControl())

    @property
    def layer(self) -> Any:
        return self._layer

    @property
    def map(self) -> Any:
        return self._map

    @property
    def metadata(self) -> JSONDict:
        return JSONDict(self._metadata)

    @property
    def id(self) -> Optional[str]:
        return getattr(self, '_id', None)

    def to_map(self, coordinate: Union[List[float], Tuple[float, float]]) -> Tuple[float, float]:
        """
        Convert a coordinate from the image or projected image space to the map
        space.

        :param coordinate: a two-tuple that is x, y in pixel space or x, y in
            image projection space.
        :returns: a two-tuple that is in the map space coordinates.
        """
        x, y = coordinate[:2]
        if not self._metadata:
            return y, x
        if self._geospatial:
            import pyproj

            transf = pyproj.Transformer.from_crs(
                self._metadata['projection'], 'EPSG:4326', always_xy=True)
            return tuple(transf.transform(x, y)[::-1])
        return self._metadata['sizeY'] - y, x

    def from_map(self, coordinate: Union[List[float], Tuple[float, float]]) -> Tuple[float, float]:
        """
        :param coordinate: a two-tuple that is in the map space coordinates.
        :returns: a two-tuple that is x, y in pixel space or x, y in image
            projection space.
        """
        y, x = coordinate[:2]
        if not self._metadata:
            return x, y
        if self._geospatial:
            import pyproj

            transf = pyproj.Transformer.from_crs(
                'EPSG:4326', self._metadata['projection'], always_xy=True)
            return transf.transform(x, y)
        return x, self._metadata['sizeY'] - y

    def update_frame(self, frame, style, **kwargs):
        if self._layer:
            parsed_url = urlparse(self._layer.url)
            query = parsed_url.query
            query = {k: v[0] for k, v in parse_qs(query).items()}
            query.update(dict(
                frame=frame,
                style=json.dumps(style),
            ))
            query_string = urlencode(query, quote_via=quote, safe='{}')
            self._layer.url = urlunparse((
                parsed_url.scheme, parsed_url.netloc,
                parsed_url.path, parsed_url.params,
                query_string, parsed_url.fragment,
            ))
            self._layer.redraw()

    def get_frame_histogram(self, query):
        import aiohttp

        if self._layer is not None:
            if self._frame_histograms is None:
                self._frame_histograms = {}

            frame = query.get('frame')
            parsed_url = urlparse(self._layer.url)
            query_string = urlencode(query)
            scheme = parsed_url.scheme or 'http'
            netloc = parsed_url.netloc
            if not netloc and self._ts is not None:
                netloc = f'{self._ts.JUPYTER_HOST}:{self._ts._jupyter_server_manager.port}'
            histogram_url = urlunparse((
                scheme, netloc,
                '/histogram', parsed_url.params,
                query_string, parsed_url.fragment,
            ))

            async def fetch(url):
                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=900),
                ) as session:
                    async with session.get(url) as response:
                        self._frame_histograms[frame] = await response.json()  # type: ignore
                        # rewrite whole object for watcher
                        self.frame_selector.frameHistograms = (
                            self._frame_histograms.copy()  # type: ignore
                        )

            asyncio.ensure_future(fetch(histogram_url))


# used for encoding histogram data
class NumpyEncoder(json.JSONEncoder):
    """Special json encoder for numpy types from https://stackoverflow.com/a/49677241"""

    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return json.JSONEncoder.default(self, obj)


def launch_tile_server(tile_source: IPyLeafletMixin, port: int = 0) -> Any:
    import tornado.httpserver
    import tornado.netutil
    import tornado.web

    class RequestManager:
        def __init__(self, tile_source: IPyLeafletMixin) -> None:
            self._tile_source_ = weakref.ref(tile_source)
            self._ports = ()

        @property
        def tile_source(self) -> IPyLeafletMixin:
            return cast(IPyLeafletMixin, self._tile_source_())

        @tile_source.setter
        def tile_source(self, source: IPyLeafletMixin) -> None:
            self._tile_source_ = weakref.ref(source)

        @property
        def ports(self) -> Tuple[int, ...]:
            return self._ports

        @property
        def port(self) -> int:
            return self.ports[0]

    manager = RequestManager(tile_source)
    # NOTE: set `ports` manually after launching server

    class TileSourceMetadataHandler(tornado.web.RequestHandler):
        """REST endpoint to get image metadata."""

        def get(self) -> None:
            self.write(json.dumps(manager.tile_source.metadata))  # type: ignore[attr-defined]
            self.set_header('Content-Type', 'application/json')

    class TileSourceHistogramHandler(tornado.web.RequestHandler):
        """REST endpoint to get image metadata."""

        async def get(self) -> None:
            kwargs = {k: ast.literal_eval(self.get_argument(k)) for k in self.request.arguments}

            def fetch():
                if not hasattr(manager, '_histogram_semaphore'):
                    manager._histogram_semaphore = threading.Semaphore(  # type: ignore
                        min(6, large_image.config.cpu_count()),
                    )
                with manager._histogram_semaphore:  # type: ignore[attr-defined]
                    histogram = manager.tile_source._unstyled.histogram(  # type: ignore
                        **kwargs,
                    ).get('histogram', [{}])
                self.write(json.dumps(histogram, cls=NumpyEncoder))
                self.set_header('Content-Type', 'application/json')

            await tornado.ioloop.IOLoop.current().run_in_executor(None, fetch)

    class TileSourceTileHandler(tornado.web.RequestHandler):
        """REST endpoint to serve tiles from image in slippy maps standard."""

        def get(self) -> None:
            x = int(self.get_argument('x'))
            y = int(self.get_argument('y'))
            z = int(self.get_argument('z'))
            frame = int(self.get_argument('frame', default='0'))
            style = self.get_argument('style', default=None)
            if style:
                manager.tile_source.style = json.loads(style)  # type: ignore[attr-defined]
            encoding = self.get_argument('encoding', 'PNG')
            try:
                tile_binary = manager.tile_source.getTile(  # type: ignore[attr-defined]
                    x, y, z, encoding=encoding, frame=frame)
            except TileSourceXYZRangeError as e:
                self.clear()
                self.set_status(404)
                self.finish(f'<html><body>{e}</body></html>')
            else:
                self.write(tile_binary)
                self.set_header('Content-Type', 'image/png')

    app = tornado.web.Application([
        (r'/metadata', TileSourceMetadataHandler),
        (r'/histogram', TileSourceHistogramHandler),
        (r'/tile', TileSourceTileHandler),
    ])
    sockets = tornado.netutil.bind_sockets(port, '')
    server = tornado.httpserver.HTTPServer(app)
    server.add_sockets(sockets)

    manager._ports = tuple(s.getsockname()[1] for s in sockets)
    return manager
