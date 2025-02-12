const _ = girder._;

var ImageViewerWidgetAnnotationExtension = {
    /**
     * Returns whether or not the view supports drawing and rendering
     * annotations.
     */
    annotationAPI: _.constant(false),

    /**
     * Render an annotation model on the image.
     *
     * @param {AnnotationModel} annotation
     */
    drawAnnotation: function (/* annotation */) {
        throw new Error('Viewer does not support drawing annotations');
    },

    /**
     * Remove an annotation from the image.  This simply
     * finds a layer with the given id and removes it because
     * each annotation is contained in its own layer.  If
     * the annotation is not drawn, this is a noop.
     *
     * @param {AnnotationModel} annotation
     */
    removeAnnotation: function (/* annotation */) {
        throw new Error('Viewer does not support drawing annotations');
    },

    /**
     * Set the image interaction mode to region drawing mode.  This
     * method takes an optional `model` argument where the region will
     * be stored when created by the user.  In any case, this method
     * returns a promise that resolves to an array defining the region:
     *   [ left, top, width, height ]
     *
     * @param {Backbone.Model} [model] A model to set the region to
     * @returns {Promise}
     */
    drawRegion: function (/* model */) {
        throw new Error('Viewer does not support drawing annotations');
    },

    /**
     * Set the image interaction mode to draw the given type of annotation.
     *
     * @param {string} type An annotation type
     * @param {object} [options]
     * @param {boolean} [options.trigger=true]
     *      Trigger a global event after creating each annotation element.
     * @returns {Promise}
     *      Resolves to an array of generated annotation elements.
     */
    startDrawMode: function (/* type, options */) {
        throw new Error('Viewer does not support drawing annotations');
    }
};

export default ImageViewerWidgetAnnotationExtension;
