import DWASImportButtonTemplate from '../templates/dicomwebAssetstoreImportButton.pug';

const _ = girder._;
const AssetstoresView = girder.views.body.AssetstoresView;
const { AssetstoreType } = girder.constants;
const { wrap } = girder.utilities.PluginUtils;

/**
 * Adds DICOMweb-specific info and an import button to the assetstore list
 * view.
 */
wrap(AssetstoresView, 'render', function (render) {
    render.call(this);

    const selector = '.g-assetstore-info-section[assetstore-type="' + AssetstoreType.DICOMWEB + '"]';

    _.each(this.$(selector), function (el) {
        const $el = this.$(el);
        const assetstore = this.collection.get($el.attr('cid'));

        $el.parent().find('.g-assetstore-buttons').append(
            DWASImportButtonTemplate({
                assetstore
            })
        );
    }, this);

    this.$('.g-dwas-import-button').tooltip({
        delay: 100
    });
    return this;
});
