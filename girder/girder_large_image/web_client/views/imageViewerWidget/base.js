const $ = girder.$;
const View = girder.views.View;
const {getApiRoot, restRequest} = girder.rest;

var ImageViewerWidget = View.extend({
    initialize: function (settings) {
        this.itemId = settings.itemId;
        const item = (settings.model || {}).attributes || {};
        this.updated = item.updated || item.created;
        if (this.updated) {
            this.updated = this.updated.replace(/:/g, '-').replace(/\+/g, '_');
        }
        // optional query parameters, such as {encoding: 'PNG'}, may be
        // undefined or null
        this.tileQueryDefaults = settings.tileQueryDefaults;

        return restRequest({
            type: 'GET',
            url: 'item/' + this.itemId + '/tiles'
        }).done((resp) => {
            this.levels = resp.levels;
            this.tileWidth = resp.tileWidth;
            this.tileHeight = resp.tileHeight;
            this.sizeX = resp.sizeX;
            this.sizeY = resp.sizeY;
            this.metadata = resp;
        });
    },

    /**
     * Return a url for a specific tile.  This can also be used to generate a
     * template url if the level, x, and y parameters are template strings
     * rather than integers.
     *
     * @param {number|string} level: the tile level or a template string.
     * @param {number|string} x: the tile x position or a template string.
     * @param {number|string} y: the tile y position or a template string.
     * @param {object} [query]: optional query parameters to add to the url.
     */
    _getTileUrl: function (level, x, y, query) {
        if (this.tileQueryDefaults) {
            query = $.extend({}, this.tileQueryDefaults, query || {});
        }
        var url = getApiRoot() + '/item/' + this.itemId + '/tiles/zxy/' +
            level + '/' + x + '/' + y;
        if (this.updated) {
            query = $.extend({_: this.updated}, query);
        }
        if (query) {
            url += '?' + $.param(query);
        }
        return url;
    }
});

export default ImageViewerWidget;
