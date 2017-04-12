import _ from 'underscore';
import Backbone from 'backbone';

import { staticRoot } from 'girder/rest';
import events from 'girder/events';

import ImageViewerWidget from './base';
import convertAnnotation from '../../annotations/geojs/convert';

function guid() {
    function s4() {
        return Math.floor((1 + Math.random()) * 0x10000)
            .toString(16)
            .substring(1);
    }
    return s4() + s4() + '-' + s4() + '-' + s4() + '-' +
        s4() + '-' + s4() + s4() + s4();
}

var GeojsImageViewerWidget = ImageViewerWidget.extend({
    initialize: function (settings) {
        ImageViewerWidget.prototype.initialize.call(this, settings);

        this._layers = {};
        this.listenTo(events, 's:widgetDrawRegion', this.drawRegion);
        this.listenTo(events, 'g:startDrawMode', this.startDrawMode);

        $.getScript(
            staticRoot + '/built/plugins/large_image/extra/geojs.js',
            () => this.render()
        );
    },

    render: function () {
        // If script or metadata isn't loaded, then abort
        if (!window.geo || !this.tileWidth || !this.tileHeight) {
            return;
        }

        this._destroyViewer();
        var geo = window.geo; // this makes the style checker happy

        var w = this.sizeX, h = this.sizeY;
        var params = geo.util.pixelCoordinateParams(
            this.el, w, h, this.tileWidth, this.tileHeight);
        params.layer.useCredentials = true;
        params.layer.url = this._getTileUrl('{z}', '{x}', '{y}');
        this.viewer = geo.map(params.map);
        this.viewer.createLayer('osm', params.layer);

        this.trigger('g:imageRendered', this);
        return this;
    },

    destroy: function () {
        this._destroyViewer();
        if (window.geo) {
            delete window.geo;
        }
        ImageViewerWidget.prototype.destroy.call(this);
    },

    _destroyViewer: function () {
        if (this.viewer) {
            this.viewer.exit();
            this.viewer = null;
        }
    },

    /**
     * Render an annotation model on the image.  Currently,
     * this is limited to annotation types that can be directly
     * converted into geojson primatives.
     *
     * Internally, this generates a new feature layer for the
     * annotation that is referenced by the annotation id.
     * All "elements" contained inside this annotations are
     * drawn in the referenced layer.
     *
     * @param {AnnotationModel} annotation
     */
    drawAnnotation: function (annotation) {
        var geojson = annotation.geojson();
        var layer = this.viewer.createLayer('feature', {
            features: ['point', 'line', 'polygon']
        });
        this._layers[annotation.id] = layer;
        window.geo.createFileReader('jsonReader', {layer})
            .read(geojson, () => this.viewer.draw());
    },

    /**
     * Remove an annotation from the image.  This simply
     * finds a layer with the given id and removes it because
     * each annotation is contained in its own layer.  If
     * the annotation is not drawn, this is a noop.
     */
    removeAnnotation: function (annotation) {
        var layer = this._layers[annotation.id];
        if (layer) {
            this.viewer.deleteLayer(layer);
        }
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
    drawRegion: function (model) {
        model = model || new Backbone.Model();
        return this.startDrawMode('rectangle', {trigger: false}).then((elements) => {
            /*
             * Strictly speaking, the rectangle drawn here could be rotated, but
             * for simplicity we will set the region model assuming it is not.
             * To be more precise, we could expand the region to contain the
             * whole rotated rectangle.  A better solution would be to add
             * a draw parameter to geojs that draws a rectangle aligned with
             * the image coordinates.
             */
            var element = elements[0];
            var width = Math.round(element.width);
            var height = Math.round(element.height);
            var left = Math.round(element.center[0] - element.width / 2);
            var top = Math.round(element.center[1] - element.height / 2);

            model.set('value', [
                left, top, width, height
            ], {trigger: true});

            return model.get('value');
        });
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
    startDrawMode: function (type, options) {
        var layer;
        var elements = [];
        var annotations = [];

        return new Promise((resolve) => {
            var element;

            options = _.defaults(options || {}, {trigger: true});
            layer = this.viewer.createLayer('annotation');
            layer.geoOn(
                window.geo.event.annotation.state,
                (evt) => {
                    element = convertAnnotation(evt.annotation);
                    if (!element.id) {
                        element.id = guid();
                    }
                    elements.push(element);
                    annotations.push(evt.annotation);

                    if (options.trigger) {
                        events.trigger('g:annotationCreated', element, evt.annotation);
                    }

                    resolve(elements, annotations);

                    // defer deleting the layer because geojs calls draw on it
                    // after triggering this event
                    window.setTimeout(() => this.viewer.deleteLayer(layer), 10);
                }
            );
            layer.mode(type);
        });
    }
});

export default GeojsImageViewerWidget;
