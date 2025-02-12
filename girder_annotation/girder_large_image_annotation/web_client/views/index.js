import ConfigView from './configView';
import HierarchyWidget from './hierarchyWidget';
import './imageViewerSelectWidget';
import ItemListWidget from './itemList';
import ImageViewerWidgetAnnotationExtension from './imageViewerWidget/base';
import * as extensions from './imageViewerWidget';

const viewers = {};

for (var key in girder.plugins.large_image.views.imageViewerWidget) {
    const largeImageViewer = girder.plugins.large_image.views.imageViewerWidget[key];
    // We have to modify the large_image classes themselves in-place, because of the way the
    // viewers are wrapped by this class (see imageViewerSelectWidget.js wrappers). Because they
    // are top-level module symbols, we can't simply replace them with these extended versions,
    // but must extend them key by key.
    Object.keys(ImageViewerWidgetAnnotationExtension).forEach(function (extKey) {
        largeImageViewer.prototype[extKey] = ImageViewerWidgetAnnotationExtension[extKey];
    });

    if (extensions[key]) {
        const ext = extensions[key](largeImageViewer);
        Object.keys(ext).forEach(function (extKey) {
            largeImageViewer.prototype[extKey] = ext[extKey];
        });
    }

    viewers[key] = largeImageViewer;
}

export {
    ConfigView,
    HierarchyWidget,
    ItemListWidget,
    viewers as ViewerWidget
};
