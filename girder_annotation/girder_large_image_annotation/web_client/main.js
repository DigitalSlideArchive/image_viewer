// import modules for side effects
import './routes';
import './views/imageViewerSelectWidget';

// expose symbols under girder.plugins
import * as largeImageAnnotation from './index';

const SearchFieldWidget = girder.views.widgets.SearchFieldWidget;
const {registerPluginNamespace} = girder.pluginUtils;

registerPluginNamespace('large_image_annotation', largeImageAnnotation);

SearchFieldWidget.addMode(
    'li_annotation_metadata',
    ['item'],
    'Annotation Metadata search',
    'You can search specific annotation metadata keys by adding "key:<key name>" to your search.  Otherwise, all primary metadata keys are searched.  For example "key:quality good" would find any items with annotations that have attributes with a key named quality (case sensitive) that contains the word "good" (case insensitive) anywhere in its value.'
);
