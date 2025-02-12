import largeImageAnnotationConfig from './configView';

import '../stylesheets/itemList.styl';

const $ = girder.$;
const _ = girder._;
const {restRequest} = girder.rest;
const {wrap} = girder.utilities.PluginUtils;
const ItemListWidget = girder.views.widgets.ItemListWidget;

wrap(ItemListWidget, 'render', function (render) {
    render.apply(this, _.rest(arguments));

    function addLargeImageAnnotationBadge(item, parent, numAnnotations, flag) {
        const thumbnail = $('.large_image_thumbnail[g-item-cid="' + item.cid + '"]', parent).first();
        if (!thumbnail.length) {
            return;
        }

        let badge = thumbnail.find('.large_image_annotation_badge');
        if (badge.length === 0) {
            badge = $(`<div class="large_image_annotation_badge hidden"></div>`).appendTo(thumbnail);
        }
        // update badge
        badge
            .attr('title', !flag ? `${numAnnotations} annotation${numAnnotations === 1 ? '' : 's'}` : 'Referenced by an annotation')
            .text(numAnnotations)
            .toggleClass('hidden', !numAnnotations);
    }

    largeImageAnnotationConfig.getSettings((settings) => {
        // don't render or already rendered
        if (settings['large_image.show_thumbnails'] === false || this.$('.large_image_annotation_badge').length > 0) {
            return;
        }
        const items = this.collection.toArray();
        const hasAnyLargeImage = _.some(items, (item) => item.has('largeImage'));

        if (!hasAnyLargeImage || this._inFetch || this._needsFetch) {
            return;
        }

        const needCounts = items.filter((item) => item._annotationCount === undefined && item.has('largeImage')).map((item) => {
            item._annotationCount = null; // pending
            delete item._annotationReferenced;
            return item.id;
        });
        let promise;
        if (!needCounts.length) {
            promise = $.Deferred().resolve({});
        } else {
            promise = restRequest({
                type: 'POST',
                url: 'annotation/counts',
                data: {
                    items: needCounts.join(',')
                },
                headers: {'X-HTTP-Method-Override': 'GET'},
                error: null
            }).done((resp) => {
                Object.entries(resp).forEach(([id, count]) => {
                    if (id === 'referenced') {
                        Object.keys(count).forEach((rid) => {
                            if (this.collection.get(rid)) {
                                this.collection.get(rid)._annotationReferenced = true;
                            }
                        });
                    } else if (this.collection.get(id)) {
                        this.collection.get(id)._annotationCount = count;
                    }
                });
            });
        }
        promise.then(() => {
            this.collection.forEach((item) => {
                if (item._annotationCount !== undefined) {
                    if (!item._annotationReferenced) {
                        addLargeImageAnnotationBadge(item, this.$el, item._annotationCount);
                    } else {
                        addLargeImageAnnotationBadge(item, this.$el, '*', true);
                    }
                }
            });
            return null;
        });
    });
});

export default ItemListWidget;
