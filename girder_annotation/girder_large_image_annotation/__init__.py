#############################################################################
#  Copyright Kitware Inc.
#
#  Licensed under the Apache License, Version 2.0 ( the "License" );
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#############################################################################

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _importlib_version
from pathlib import Path

from girder import events
from girder.constants import registerAccessFlag
from girder.exceptions import ValidationException
from girder.plugin import GirderPlugin, getPlugin, registerPluginStaticContent
from girder.settings import SettingDefault
from girder.utility import search, setting_utilities
from girder.utility.model_importer import ModelImporter

from . import constants, handlers
from .models.annotation import Annotation
from .rest.annotation import AnnotationResource

try:
    __version__ = _importlib_version(__name__)
except PackageNotFoundError:
    # package is not installed
    pass


def metadataSearchHandler(*args, **kwargs):
    import girder_large_image

    return girder_large_image.metadataSearchHandler(
        *args,
        models=['item'],
        searchModels={('annotation', 'large_image'): {'model': 'item', 'reference': 'itemId'}},
        metakey='annotation.attributes', **kwargs)


# Validators

@setting_utilities.validator({
    constants.PluginSettings.LARGE_IMAGE_ANNOTATION_HISTORY,
})
def validateBoolean(doc):
    val = doc['value']
    if str(val).lower() not in ('false', 'true', ''):
        raise ValidationException('%s must be a boolean.' % doc['key'], 'value')
    doc['value'] = str(val).lower() != 'false'


# Defaults

# Defaults that have fixed values can just be added to the system defaults
# dictionary.
SettingDefault.defaults.update({
    constants.PluginSettings.LARGE_IMAGE_ANNOTATION_HISTORY: True,
})

# Access flags

registerAccessFlag(constants.ANNOTATION_ACCESS_FLAG, 'Create annotations',
                   'Allow user to create annotations')


class LargeImageAnnotationPlugin(GirderPlugin):
    DISPLAY_NAME = 'Large Image Annotation'

    def load(self, info):
        getPlugin('large_image').load(info)

        registerPluginStaticContent(
            plugin='large_image_annotation',
            css=['/style.css'],
            js=['/girder-plugin-large-image-annotation.umd.cjs'],
            staticDir=Path(__file__).parent / 'web_client' / 'dist',
            tree=info['serverRoot'],
        )

        ModelImporter.registerModel('annotation', Annotation, 'large_image')
        info['apiRoot'].annotation = AnnotationResource()
        # Ask for some models to make sure their singletons are initialized.
        # Also migrate the database as a one-time action.
        Annotation()._migrateDatabase()

        # add copyAnnotations option to POST resource/copy, POST item/{id}/copy
        # and POST folder/{id}/copy
        info['apiRoot'].resource.copyResources.description.param(
            'copyAnnotations', 'Copy annotations when copying resources (default true)',
            required=False, dataType='boolean')
        info['apiRoot'].item.copyItem.description.param(
            'copyAnnotations', 'Copy annotations when copying item (default true)',
            required=False, dataType='boolean')
        info['apiRoot'].folder.copyFolder.description.param(
            'copyAnnotations', 'Copy annotations when copying folder (default true)',
            required=False, dataType='boolean')

        events.bind(
            'data.process', 'large_image_annotation.annotations',
            handlers.process_annotations)

        search._allowedSearchMode.pop('li_annotation_metadata', None)
        search.addSearchMode('li_annotation_metadata', metadataSearchHandler)
