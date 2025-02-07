import DWASEditFieldsTemplate from '../templates/dicomwebAssetstoreEditFields.pug';

import authOptions from './AuthOptions';

const EditAssetstoreWidget = girder.views.widgets.EditAssetstoreWidget;
const { AssetstoreType } = girder.constants;
const { wrap } = girder.utilities.PluginUtils;

/**
 * Adds DICOMweb-specific fields to the edit dialog.
 */
wrap(EditAssetstoreWidget, 'render', function (render) {
    render.call(this);

    if (this.model.get('type') === AssetstoreType.DICOMWEB) {
        this.$('.g-assetstore-form-fields').append(
            DWASEditFieldsTemplate({
                assetstore: this.model,
                authOptions
            })
        );
    }
    return this;
});

EditAssetstoreWidget.prototype.fieldsMap[AssetstoreType.DICOMWEB] = {
    get: function () {
        return {
            url: this.$('#g-edit-dwas-url').val(),
            qido_prefix: this.$('#g-edit-dwas-qido-prefix').val(),
            wado_prefix: this.$('#g-edit-dwas-wado-prefix').val(),
            auth_type: this.$('#g-edit-dwas-auth-type').val(),
            auth_token: this.$('#g-edit-dwas-auth-token').val()
        };
    },
    set: function () {
        const dwInfo = this.model.get('dicomweb_meta');
        this.$('#g-edit-dwas-url').val(dwInfo.url);
        this.$('#g-edit-dwas-qido-prefix').val(dwInfo.qido_prefix);
        this.$('#g-edit-dwas-wado-prefix').val(dwInfo.wado_prefix);
        // HTML can't accept null, so set it to an empty string
        this.$('#g-edit-dwas-auth-type').val(dwInfo.auth_type || '');
        this.$('#g-edit-dwas-auth-token').val(dwInfo.auth_token);
    }
};
