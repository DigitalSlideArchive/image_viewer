import AnnotationModel from '../models/AnnotationModel';

const $ = girder.$;
const {wrap} = girder.utilities.PluginUtils;
const HierarchyWidget = girder.views.widgets.HierarchyWidget;
const {restRequest} = girder.rest;
const AccessWidget = girder.views.widgets.AccessWidget;

wrap(HierarchyWidget, 'render', function (render) {
    render.call(this);

    if (this.parentModel.get('_modelType') === 'folder') {
        ownAnnotation(this, this.parentModel.id);
    }
});

function ownAnnotation(root, folderId) {
    restRequest({
        type: 'GET',
        url: 'annotation/folder/' + folderId + '/present',
        data: {
            recurse: true
        }
    }).done((ownsAnnot) => {
        if (ownsAnnot) {
            addAccessControl(root);
        }
    });
}

function addAccessControl(root) {
    if (root.$('.g-edit-annotation-access').length === 0) {
        if (root.$('.g-folder-actions-menu > .divider').length > 0) {
            root.$('.g-folder-actions-menu > .divider').before(
                '<li role="presentation">' +
                    '<a class="g-edit-annotation-access" role="menuitem">' +
                        '<i class="icon-lock"></i>' +
                        'Annotation access control' +
                    '</a>' +
                '</li>'
            );
        } else {
            root.$('ul.g-folder-actions-menu').append(
                '<li role="presentation">' +
                    '<a class="g-edit-annotation-access" role="menuitem">' +
                        '<i class="icon-lock"></i>' +
                        'Annotation access control' +
                    '</a>' +
                '</li>'
            );
        }
        root.events['click .g-edit-annotation-access'] = editAnnotAccess;
        root.delegateEvents();
    }
}

function editAnnotAccess() {
    restRequest({
        type: 'GET',
        url: 'annotation/folder/' + this.parentModel.get('_id'),
        data: {
            recurse: true,
            limit: 1
        }
    }).done((resp) => {
        const model = new AnnotationModel(resp[0]);
        model.get('annotation').name = 'Your Annotations';
        model.save = () => {};
        model.updateAccess = (settings) => {
            const access = {
                access: model.get('access'),
                public: model.get('public'),
                publicFlags: model.get('publicFlags')
            };
            const defaultUpdateModel = new AnnotationModel();
            defaultUpdateModel.id = this.parentModel.get('_id');
            defaultUpdateModel.altUrl = 'annotation/folder';
            defaultUpdateModel.set(access);
            defaultUpdateModel.updateAccess(settings);
            model.trigger('g:accessListSaved');
        };
        model.fetchAccess(true)
            .done(() => {
                new AccessWidget({// eslint-disable-line no-new
                    el: $('#g-dialog-container'),
                    modelType: 'annotation',
                    model,
                    hideRecurseOption: false,
                    parentView: this,
                    noAccessFlag: true
                });
            });
    });
}

export default HierarchyWidget;
