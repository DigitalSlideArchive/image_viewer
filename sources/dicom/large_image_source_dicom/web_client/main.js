// Extends and overrides API
import './constants';
import './views/DICOMwebImportView';
import './views/AssetstoresView';
import './views/EditAssetstoreWidget';
import './views/NewAssetstoreWidget';

// expose symbols under girder.plugins
import * as dicomWeb from './index';

const { registerPluginNamespace } = girder.pluginUtils;

registerPluginNamespace('dicomweb', dicomWeb);
