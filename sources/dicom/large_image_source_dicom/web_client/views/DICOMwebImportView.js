import DWASImportTemplate from '../templates/assetstoreImport.pug';

const $ = girder.$;
const BrowserWidget = girder.views.widgets.BrowserWidget;
const router = girder.router;
const View = girder.views;
const { restRequest } = girder.rest;
const { assetstoreImportViewMap } = girder.views.body.AssetstoresView;
const { AssetstoreType } = girder.constants;

const DICOMwebImportView = View.extend({
    events: {
        'submit .g-dwas-import-form': function (e) {
            e.preventDefault();
            this.$('.g-validation-failed-message').empty();

            const destinationType = this.$('#g-dwas-import-dest-type').val();
            const destinationId = this.$('#g-dwas-import-dest-id').val().trim().split(/\s/)[0];
            const filters = this.$('#g-dwas-import-filters').val().trim();
            const limit = this.$('#g-dwas-import-limit').val().trim();

            if (!destinationId) {
                this.$('.g-validation-failed-message').html('Invalid Destination ID');
                return;
            }

            this.$('.g-submit-dwas-import').addClass('disabled');
            this.assetstore.off().on('g:imported', function () {
                router.navigate(destinationType + '/' + destinationId, { trigger: true });
            }, this).on('g:error', function (err) {
                this.$('.g-submit-dwas-import').removeClass('disabled');
                this.$('.g-validation-failed-message').html(err.responseJSON.message);
            }, this).import({
                destinationId,
                destinationType,
                limit,
                filters,
                progress: true
            });
        },
        'click .g-open-browser': '_openBrowser'
    },

    initialize: function (settings) {
        this._browserWidgetView = new BrowserWidget({
            parentView: this,
            titleText: 'Destination',
            helpText: 'Browse to a location to select it as the destination.',
            submitText: 'Select Destination',
            validate: function (model) {
                const isValid = $.Deferred();
                if (!model) {
                    isValid.reject('Please select a valid root.');
                } else {
                    isValid.resolve();
                }
                return isValid.promise();
            }
        });

        this.listenTo(this._browserWidgetView, 'g:saved', function (val) {
            this.$('#g-dwas-import-dest-id').val(val.id);
            const model = this._browserWidgetView._hierarchyView.parentModel;
            const modelType = model.get('_modelType');
            this.$('#g-dwas-import-dest-type').val(modelType);

            // Make a rest request to get the resource path
            restRequest({
                url: `resource/${val.id}/path`,
                method: 'GET',
                data: { type: modelType }
            }).done((result) => {
                // Only add the resource path if the value wasn't altered
                if (this.$('#g-dwas-import-dest-id').val() === val.id) {
                    this.$('#g-dwas-import-dest-id').val(`${val.id} (${result})`);
                }
            });
        });
        this.assetstore = settings.assetstore;
        this.render();
    },

    render: function () {
        this.$el.html(DWASImportTemplate({
            assetstore: this.assetstore
        }));

        return this;
    },

    _openBrowser: function () {
        this._browserWidgetView.setElement($('#g-dialog-container')).render();
    }
});

assetstoreImportViewMap[AssetstoreType.DICOMWEB] = DICOMwebImportView;

export default DICOMwebImportView;
