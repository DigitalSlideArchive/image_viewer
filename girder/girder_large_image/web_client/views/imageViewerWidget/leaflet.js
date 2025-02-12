import ImageViewerWidget from './base';

const $ = girder.$;

var LeafletImageViewerWidget = ImageViewerWidget.extend({
    initialize: function (settings) {
        if (!$('head #large_image-leaflet-css').length) {
            $('head').prepend(
                $('<link>', {
                    id: 'large_image-leaflet-css',
                    rel: 'stylesheet',
                    href: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/leaflet.css'
                })
            );
        }

        $.when(
            ImageViewerWidget.prototype.initialize.call(this, settings),
            $.ajax({ // like $.getScript, but allow caching
                url: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/leaflet.js',
                dataType: 'script',
                cache: true
            }))
            .done(() => this.render());
    },

    render: function () {
        var errmsg;
        // If script or metadata isn't loaded, then abort
        if (!window.L || !this.tileWidth || !this.tileHeight || this.deleted) {
            return this;
        }

        if (this.viewer) {
            // don't rerender the viewer
            return this;
        }

        if (this.tileWidth !== this.tileHeight) {
            errmsg = 'The Leaflet viewer only supports square tiles.';
        }
        if (this.tileWidth > 256) {
            errmsg = 'The Leaflet viewer does not support tiles wider than 256 pixels.';
        }
        if (errmsg) {
            this.viewer = $('<div/>').text(errmsg);
            this.$el.append(this.viewer);
            console.error(errmsg);
            return this;
        }

        // TODO: if a viewer already exists, do we render again?

        var L = window.L; // this makes the style checker happy

        this.viewer = L.map(this.el, {
            center: [0.0, 0.0], // initial position, must be set
            zoom: 0, // initial zoom, must be set
            minZoom: 0,
            maxZoom: this.levels - 1,
            maxBounds: [
                [-90.0, -180.0],
                [90.0, 180.0]
            ],
            layers: [
                L.tileLayer(
                    this._getTileUrl('{z}', '{x}', '{y}', {edge: '#DDD'}), {
                        // in theory, tileSize: new L.Point(this.tileWidth,
                        // this.tileHeight) is supposed to support non-square
                        // tiles, but it doesn't work
                        tileSize: this.tileWidth,
                        continuousWorld: true
                    })
            ],
            attributionControl: false
        });
        this.trigger('g:imageRendered', this);
        return this;
    },

    destroy: function () {
        if (this.viewer) {
            this.viewer.remove();
            this.viewer = null;
        }
        this.deleted = true;
        // TODO: delete CSS
        ImageViewerWidget.prototype.destroy.call(this);
    }
});

export default LeafletImageViewerWidget;
