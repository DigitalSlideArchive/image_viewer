import largeImageConfig from './configView';
import ItemViewWidget from './itemViewWidget';
import '../stylesheets/itemView.styl';

const $ = girder.$;
const {AccessType} = girder.constants;
const {restRequest} = girder.rest;
const {wrap} = girder.utilities.PluginUtils;
const ItemView = girder.views.body.ItemView;

wrap(ItemView, 'render', function (render) {
    // ItemView is a special case in which rendering is done asynchronously,
    // so we must listen for a render event.
    this.once('g:rendered', function () {
        if (this.model.get('largeImage') && this.model.get('largeImage').fileId) {
            largeImageConfig.getSettings((settings) => {
                var access = this.model.getAccessLevel();
                var extra = settings.extraItemInfo[access] || settings.extraItemInfo[AccessType.READ] || {};
                var largeImageMetadata = {};
                var promises = [];
                var needed = {
                    tile: extra.metadata && extra.metadata.indexOf('tile') >= 0 ? '' : undefined,
                    internal: extra.metadata && extra.metadata.indexOf('internal') >= 0 ? '/internal_metadata' : undefined,
                    images: extra.images && extra.images.length ? '/images' : undefined
                };
                Object.entries(needed).forEach(([key, url]) => {
                    if (url !== undefined) {
                        promises.push(restRequest({
                            url: `item/${this.model.id}/tiles${url}`,
                            error: null
                        }).done((resp) => {
                            largeImageMetadata[key] = resp;
                        }));
                    }
                });
                $.when.apply($, promises).then(() => {
                    this.itemViewWidget = new ItemViewWidget({
                        el: $('<div>', {class: 'g-item-view-large-image'})
                            .insertAfter(this.$('.g-item-metadata')),
                        parentView: this,
                        imageModel: this.model,
                        extra: extra,
                        metadata: largeImageMetadata
                    });
                    this.itemViewWidget.render();
                    this.trigger('g:largeImageItemViewRendered', this);
                    return null;
                });
            });
        }
    }, this);
    render.call(this);
});

export default ItemView;
