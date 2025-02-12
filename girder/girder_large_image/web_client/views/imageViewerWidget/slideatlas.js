import ImageViewerWidget from './base';

const $ = girder.$;
const Backbone = girder.Backbone;
const {parseQueryString, splitRoute} = girder.misc;

// var baseSAUrl = 'https://unpkg.com/slideatlas-viewer@4.4.1/dist/';
var baseSAUrl = 'https://cdn.jsdelivr.net/npm/slideatlas-viewer@4/dist/';

var SlideAtlasImageViewerWidget = ImageViewerWidget.extend({
    initialize: function (settings) {
        if (!CanvasRenderingContext2D.prototype.resetTransform) {
            window.CanvasRenderingContext2D.prototype.resetTransform = function () {
                return this.setTransform(1, 0, 0, 1, 0, 0);
            };
        }
        if (!$('head #large_image-slideatlas-css').length) {
            $('head').prepend(
                $('<link>', {
                    id: 'large_image-slideatlas-css',
                    rel: 'stylesheet',
                    href: baseSAUrl + 'sa.css'
                })
            );
        }

        $.when(
            ImageViewerWidget.prototype.initialize.call(this, settings),
            $.ajax({ // like $.getScript, but allow caching
                url: baseSAUrl + 'sa-all.max.js',
                dataType: 'script',
                cache: true
            }))
            .done(() => this.render());
    },

    render: function () {
        var errmsg;
        // If script or metadata isn't loaded, then abort
        if (!window.SA || !this.tileWidth || !this.tileHeight || this.deleted) {
            return this;
        }

        if (this.viewer) {
            // don't rerender the viewer
            return this;
        }

        if (this.tileWidth !== this.tileHeight) {
            errmsg = 'The SlideAtlas viewer only supports square tiles.';
        }
        if (this.tileWidth > 256) {
            errmsg = 'The SlideAtlas viewer does not support tiles wider than 256 pixels.';
        }
        if (errmsg) {
            this.viewer = $('<div/>').text(errmsg);
            this.$el.append(this.viewer);
            console.error(errmsg);
            return this;
        }

        // TODO: if a viewer already exists, do we render again?
        // SlideAtlas bundles its own version of jQuery, which should attach itself to "window.$" when it's sourced
        // The "this.$el" still uses the Girder version of jQuery, which will not have "saViewer" registered on it.
        var tileSource = {
            height: this.sizeY,
            width: this.sizeX,
            tileWidth: this.tileWidth,
            tileHeight: this.tileHeight,
            minLevel: 0,
            maxLevel: this.levels - 1,
            units: 'mm',
            spacing: [this.metadata.mm_x, this.metadata.mm_y],
            getTileUrl: (level, x, y, z) => {
                // Drop the "z" argument
                return this._getTileUrl(level, x, y);
            }
        };
        if (!this.metadata.mm_x) {
            // tileSource.units = 'pixels';
            tileSource.spacing = [1, 1];
        }
        window.SA.SAViewer(window.$(this.el), {
            zoomWidget: true,
            drawWidget: true,
            prefixUrl: baseSAUrl + 'img/',
            tileSource: tileSource
        });
        this.viewer = this.el.saViewer;

        this.girderGui = new window.SAM.LayerPanel(this.viewer, this.itemId);
        $(this.el).css({position: 'relative'});
        window.SA.SAFullScreenButton($(this.el))
            .css({position: 'absolute', left: '2px', top: '2px'});
        window.SA.GirderView = this;

        // Set the view from the URL if bounds are specified.
        var curRoute = Backbone.history.fragment,
            routeParts = splitRoute(curRoute),
            queryString = parseQueryString(routeParts.name);

        if (queryString.bounds) {
            var rot = 0;
            if (queryString.rotate) {
                rot = parseInt(queryString.rotate);
            }
            var bds = queryString.bounds.split(',');
            var x0 = parseInt(bds[0]);
            var y0 = parseInt(bds[1]);
            var x1 = parseInt(bds[2]);
            var y1 = parseInt(bds[3]);
            this.viewer.SetCamera([(x0 + x1) * 0.5, (y0 + y1) * 0.5], rot, (y1 - y0));
        }

        this.trigger('g:imageRendered', this);
        return this;
    },

    destroy: function () {
        if (this.viewer) {
            window.$(this.el).saViewer('destroy');
            this.viewer = null;
        }
        this.deleted = true;
        ImageViewerWidget.prototype.destroy.call(this);
    }
});

export default SlideAtlasImageViewerWidget;
