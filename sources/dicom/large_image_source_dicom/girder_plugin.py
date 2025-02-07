from pathlib import Path

from girder.plugin import GirderPlugin, registerPluginStaticContent

from . import assetstore


class DICOMwebPlugin(GirderPlugin):
    DISPLAY_NAME = 'DICOMweb Plugin'

    def load(self, info):
        registerPluginStaticContent(
            plugin='dicomweb',
            css=[],
            js=['/girder-plugin-dicomweb.umd.js'],
            staticDir=Path(__file__).parent / 'web_client' / 'dist',
            tree=info['serverRoot'],
        )
        assetstore.load(info)
