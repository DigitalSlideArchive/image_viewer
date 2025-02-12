import yaml from 'js-yaml';

import itemViewWidgetTemplate from '../templates/itemView.pug';

const {getApiRoot} = girder.rest;
const View = girder.views.View;

var ItemViewWidget = View.extend({
    initialize: function (settings) {
        this.itemId = settings.imageModel.id;
        this.model = settings.imageModel;
        this.extra = settings.extra;
        this.metadata = settings.metadata;
    },

    render: function () {
        this.$el.html(itemViewWidgetTemplate({
            extra: this.extra,
            updated: this.model.get('updated'),
            largeImageMetadata: this.metadata,
            yaml: yaml,
            imageUrl: `${getApiRoot()}/item/${this.itemId}/tiles/images/`
        }));
        return this;
    }
});

export default ItemViewWidget;
