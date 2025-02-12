import ImageViewerWidget from './base';

const $ = girder.$;
const _ = girder._;

var OpenseadragonImageViewerWidget = ImageViewerWidget.extend({
    initialize: function (settings) {
        $.when(
            ImageViewerWidget.prototype.initialize.call(this, settings),
            $.ajax({ // like $.getScript, but allow caching
                url: 'https://openseadragon.github.io/openseadragon/openseadragon.min.js',
                dataType: 'script',
                cache: true
            }))
            .done(() => this.render());
    },

    render: function () {
        // If script or metadata isn't loaded, then abort
        if (!window.OpenSeadragon || !this.tileWidth || !this.tileHeight || this.deleted) {
            return this;
        }

        if (this.viewer) {
            // don't rerender the viewer
            return this;
        }

        var OpenSeadragon = window.OpenSeadragon; // this makes the style checker happy

        this.viewer = OpenSeadragon({ // jshint ignore:line
            element: this.el,
            prefixUrl: 'https://openseadragon.github.io/openseadragon/images/',
            minZoomImageRatio: 0.2,
            defaultZoomLevel: 0.3,
            showRotationControl: true,
            tileSources: {
                height: this.sizeY,
                width: this.sizeX,
                tileWidth: this.tileWidth,
                tileHeight: this.tileHeight,
                minLevel: 0,
                maxLevel: this.levels - 1,
                getTileUrl: _.bind(function (z, x, y) {
                    return this._getTileUrl(z, x, y, {edge: 'crop'});
                }, this),
                ajaxWithCredentials: true
            }
        });
        this.trigger('g:imageRendered', this);
        return this;
    },

    destroy: function () {
        if (this.viewer) {
            this.viewer.destroy();
            this.viewer = null;
        }
        this.deleted = true;
        ImageViewerWidget.prototype.destroy.call(this);
    }
});

export default OpenseadragonImageViewerWidget;
