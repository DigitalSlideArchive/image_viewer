import imageViewerAnnotationList from '../templates/imageViewerAnnotationList.pug';

import AnnotationListWidget from './annotationListWidget';

const _ = girder._;
const {wrap} = girder.utilities.PluginUtils;
const events = girder.events;

events.on('g:appload.before', function () {
    const ImageViewerSelectWidget = girder.plugins.large_image.views.ImageViewerSelectWidget;

    wrap(ImageViewerSelectWidget, 'initialize', function (initialize, settings) {
        this.itemId = settings.imageModel.id;
        this.model = settings.imageModel;
        this._annotationList = new AnnotationListWidget({
            model: this.model,
            parentView: this
        });
        initialize.apply(this, _.rest(arguments));
    });

    wrap(ImageViewerSelectWidget, 'render', function (render) {
        render.apply(this, _.rest(arguments));
        this.$el.append(imageViewerAnnotationList());
        this._annotationList
            .setViewer(this.currentViewer)
            .setElement(this.$('.g-annotation-list-container'))
            .render();
        return this;
    });

    wrap(ImageViewerSelectWidget, '_selectViewer', function (_selectViewer) {
        _selectViewer.apply(this, _.rest(arguments));
        this._annotationList
            .setViewer(this.currentViewer)
            .render();
        return this;
    });
});
