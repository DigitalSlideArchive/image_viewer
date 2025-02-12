import JSONEditor from 'jsoneditor/dist/jsoneditor.js'; // can't 'jsoneditor'
import 'jsoneditor/dist/jsoneditor.css';

import '../stylesheets/metadataWidget.styl';
import MetadataWidgetTemplate from '../templates/metadataWidget.pug';
import MetadatumEditWidgetTemplate from '../templates/metadatumEditWidget.pug';
import MetadatumViewTemplate from '../templates/coreMetadatumView.pug';
import JsonMetadatumEditWidgetTemplate from '../templates/coreJsonMetadatumEditWidget.pug';
import largeImageConfig from './configView';

const {$, _} = girder;
const {wrap} = girder.utilities.PluginUtils;
const {AccessType} = girder.constants;
const events = girder.events;
const {localeSort} = girder.misc;
const {confirm} = girder.dialog;
const View = girder.views.View;
const MetadataWidget = girder.views.widgets.MetadataWidget;

function getMetadataRecord(item, fieldName) {
    if (item[fieldName]) {
        return item[fieldName];
    }
    let meta = item.attributes;
    fieldName.split('.').forEach((part) => {
        if (!meta[part]) {
            meta[part] = {};
        }
        meta = meta[part];
    });
    return meta;
}

function liMetadataKeyEntry(limetadata, key) {
    if (!limetadata || !key) {
        return;
    }
    let result;
    limetadata.forEach((entry, idx) => {
        if (entry.value === key) {
            result = entry;
            result.idx = idx;
        }
    });
    return result;
}

function validateMetadataValue(lientry, tempValue, nowarn) {
    if (lientry && lientry.regex && !(new RegExp(lientry.regex).exec(tempValue))) {
        if (!nowarn) {
            events.trigger('g:alert', {
                text: 'The value does not match the required format.',
                type: 'warning'
            });
        }
        return false;
    }
    if (lientry && ((lientry.format || lientry.type) === 'number' || (lientry.format || lientry.type) === 'integer')) {
        if (!Number.isFinite(parseFloat(tempValue)) || ((lientry.format || lientry.type) === 'integer' && !Number.isInteger(parseFloat(tempValue)))) {
            if (!nowarn) {
                events.trigger('g:alert', {
                    text: `The value must be a ${(lientry.format || lientry.type)}.`,
                    type: 'warning'
                });
            }
            return false;
        }
        tempValue = parseFloat(tempValue);
        if ((lientry.minimum !== undefined && tempValue < lientry.minimum) ||
            (lientry.exclusiveMinimum !== undefined && tempValue <= lientry.exclusiveMinimum) ||
            (lientry.maximum !== undefined && tempValue > lientry.maximum) ||
            (lientry.exclusiveMaximum !== undefined && tempValue >= lientry.exclusiveMaximum)) {
            if (!nowarn) {
                events.trigger('g:alert', {
                    text: 'The value is outside of the allowed range.',
                    type: 'warning'
                });
            }
            return false;
        }
    }
    return {value: tempValue};
}

var MetadatumWidget = View.extend({
    className: 'g-widget-metadata-row',

    events: {
        'click .g-widget-metadata-edit-button': 'editMetadata'
    },

    initialize: function (settings) {
        if (!_.has(this.parentView.modes, settings.mode)) {
            throw new Error('Unsupported metadatum mode ' + settings.mode + ' detected.');
        }

        this.mode = settings.mode;
        this.key = settings.key;
        this.value = settings.value;
        this.accessLevel = settings.accessLevel;
        this.parentView = settings.parentView;
        this.fieldName = settings.fieldName;
        this.apiPath = settings.apiPath;
        this.noSave = settings.noSave;
        this.limetadata = settings.limetadata;
        this.onMetadataEdited = settings.onMetadataEdited;
        this.onMetadataAdded = settings.onMetadataAdded;
    },

    _validate: function (from, to, value) {
        var newMode = this.parentView.modes[to];

        if (_.has(newMode, 'validation') &&
                _.has(newMode.validation, 'from') &&
                _.has(newMode.validation.from, from)) {
            var validate = newMode.validation.from[from][0];
            var msg = newMode.validation.from[from][1];

            if (!validate(value)) {
                events.trigger('g:alert', {
                    text: msg,
                    type: 'warning'
                });
                return false;
            }
        }

        return true;
    },

    // @todo too much duplication with editMetadata
    toggleEditor: function (event, newEditorMode, existingEditor, overrides) {
        var fromEditorMode = (existingEditor instanceof JsonMetadatumEditWidget) ? 'json' : 'simple';
        var newValue = (overrides || {}).value || existingEditor.$el.attr('g-value');
        if (!this._validate(fromEditorMode, newEditorMode, newValue)) {
            return false;
        }

        var row = existingEditor.$el;
        existingEditor.destroy();
        row.addClass('editing').empty();

        var opts = _.extend({
            el: row,
            item: this.parentView.item,
            key: row.attr('g-key'),
            value: row.attr('g-value'),
            accessLevel: this.accessLevel,
            newDatum: false,
            parentView: this,
            fieldName: this.fieldName,
            apiPath: this.apiPath,
            noSave: this.noSave,
            limetadata: this.limetadata,
            onMetadataEdited: this.onMetadataEdited,
            onMetadataAdded: this.onMetadataAdded
        }, overrides || {});

        this.parentView.modes[newEditorMode].editor(opts).render();
    },

    editMetadata: function (event) {
        this.$el.addClass('editing');
        this.$el.empty();

        var opts = {
            item: this.parentView.item,
            key: this.$el.attr('g-key'),
            value: this.$el.attr('g-value'),
            accessLevel: this.accessLevel,
            newDatum: false,
            parentView: this,
            fieldName: this.fieldName,
            apiPath: this.apiPath,
            noSave: this.noSave,
            limetadata: this.limetadata,
            onMetadataEdited: this.onMetadataEdited,
            onMetadataAdded: this.onMetadataAdded
        };

        // If they're trying to open false, null, 6, etc which are not stored as strings
        if (this.mode === 'json') {
            try {
                var jsonValue = JSON.parse(this.$el.attr('g-value'));

                if (jsonValue !== undefined && !_.isObject(jsonValue)) {
                    opts.value = jsonValue;
                }
            } catch (e) {}
        }

        this.parentView.modes[this.mode].editor(opts)
            .render()
            .$el.appendTo(this.$el);
    },

    render: function () {
        this.$el.attr({
            'g-key': this.key,
            'g-value': _.bind(this.parentView.modes[this.mode].displayValue, this)()
        }).empty();
        this.$el.removeClass('editing');
        this.$el.html(this.parentView.modes[this.mode].template({
            key: this.mode === 'key' && liMetadataKeyEntry(this.limetadata, this.key) ? liMetadataKeyEntry(this.limetadata, this.key).title || this.key : this.key,
            value: _.bind(this.parentView.modes[this.mode].displayValue, this)(),
            accessLevel: this.accessLevel,
            AccessType
        }));

        return this;
    }
});

var MetadatumEditWidget = View.extend({
    events: {
        'click .g-widget-metadata-cancel-button': 'cancelEdit',
        'click .g-widget-metadata-save-button': 'save',
        'click .g-widget-metadata-delete-button': 'deleteMetadatum',
        'click .g-widget-metadata-toggle-button': function (event) {
            var editorType;
            // @todo modal
            // in the future this event will have the new editorType (assuming a dropdown)
            if (this instanceof JsonMetadatumEditWidget) {
                editorType = 'simple';
            } else {
                editorType = 'json';
            }

            this.parentView.toggleEditor(event, editorType, this, {
                // Save state before toggling editor
                key: this.$el.find('.g-widget-metadata-key-input').val(),
                value: this.getCurrentValue()
            });
            return false;
        }
    },

    initialize: function (settings) {
        this.item = settings.item;
        this.key = settings.key || '';
        this.fieldName = settings.fieldName || 'meta';
        this.value = (settings.value !== undefined) ? settings.value : '';
        this.accessLevel = settings.accessLevel;
        this.newDatum = settings.newDatum;
        this.fieldName = settings.fieldName;
        this.apiPath = settings.apiPath;
        this.noSave = settings.noSave;
        this.limetadata = settings.limetadata;
        this.onMetadataEdited = settings.onMetadataEdited;
        this.onMetadataAdded = settings.onMetadataAdded;
    },

    editTemplate: MetadatumEditWidgetTemplate,

    getCurrentValue: function () {
        return this.$el.find('.g-widget-metadata-value-input').val();
    },

    deleteMetadatum: function (event) {
        event.stopImmediatePropagation();
        const target = $(event.currentTarget);
        var metadataList = target.parent().parent();
        if (this.noSave) {
            delete getMetadataRecord(this.item, this.fieldName)[this.key];
            metadataList.remove();
            return;
        }
        var params = {
            text: 'Are you sure you want to delete the metadatum <b>' +
                _.escape(this.key) + '</b>?',
            escapedHtml: true,
            yesText: 'Delete',
            confirmCallback: () => {
                this.item.removeMetadata(this.key, () => {
                    metadataList.remove();
                    this.parentView.parentView.trigger('li-metadata-widget-update', {});
                }, null, {
                    field: this.fieldName,
                    path: this.apiPath
                });
            }
        };
        confirm(params);
    },

    cancelEdit: function (event) {
        event.stopImmediatePropagation();
        const target = $(event.currentTarget);
        var curRow = target.parent().parent();
        if (this.newDatum) {
            curRow.remove();
        } else {
            this.parentView.render();
        }
    },

    save: function (event, value) {
        event.stopImmediatePropagation();
        const target = $(event.currentTarget);
        var curRow = target.parent(),
            tempKey = curRow.find('.g-widget-metadata-key-input').val().trim() || curRow.find('.g-widget-metadata-key-input').attr('key'),
            keyMode = curRow.find('.g-widget-metadata-key-input').attr('key'),
            tempValue = (value !== undefined) ? value : curRow.find('.g-widget-metadata-value-input').val();

        if (this.newDatum && tempKey === '') {
            events.trigger('g:alert', {
                text: 'A key is required for all metadata.',
                type: 'warning'
            });
            return false;
        }
        const lientry = keyMode ? liMetadataKeyEntry(this.limetadata, this.key) : undefined;
        if (keyMode && lientry) {
            tempValue = tempValue.trim();
        }
        const valResult = validateMetadataValue(lientry, tempValue);
        if (!valResult) {
            return false;
        }
        tempValue = valResult.value;
        var saveCallback = () => {
            this.key = tempKey;
            this.value = tempValue;

            this.parentView.key = this.key;
            this.parentView.value = this.value;

            if (keyMode) {
                this.parentView.mode = 'key';
            } else if (this instanceof JsonMetadatumEditWidget) {
                this.parentView.mode = 'json';
            } else {
                this.parentView.mode = 'simple';
            }
            // event to re-render metadata panel header when metadata is edited
            this.parentView.parentView.trigger('li-metadata-widget-update', {});
            this.parentView.render();

            this.newDatum = false;
        };

        var errorCallback = function (out) {
            events.trigger('g:alert', {
                text: out.message,
                type: 'danger'
            });
        };

        if (this.newDatum) {
            if (this.onMetadataAdded) {
                this.onMetadataAdded(tempKey, tempValue, saveCallback, errorCallback);
            } else {
                if (this.noSave) {
                    if (getMetadataRecord(this.item, this.fieldName)[tempKey] !== undefined) {
                        events.trigger('g:alert', {
                            text: tempKey + ' is already a metadata key',
                            type: 'warning'
                        });
                        return false;
                    }
                    getMetadataRecord(this.item, this.fieldName)[tempKey] = tempValue;
                    this.parentView.parentView.render();
                }
                this.item.addMetadata(tempKey, tempValue, saveCallback, errorCallback, {
                    field: this.fieldName,
                    path: this.apiPath
                });
            }
        } else {
            if (this.onMetadataEdited) {
                this.onMetadataEdited(tempKey, this.key, tempValue, saveCallback, errorCallback);
            } else {
                if (this.noSave) {
                    tempKey = tempKey === '' ? this.key : tempKey;
                    if (tempKey !== this.key && getMetadataRecord(this.item, this.fieldName)[tempKey] !== undefined) {
                        events.trigger('g:alert', {
                            text: tempKey + ' is already a metadata key',
                            type: 'warning'
                        });
                        return false;
                    }
                    delete getMetadataRecord(this.item, this.fieldName)[this.key];
                    getMetadataRecord(this.item, this.fieldName)[tempKey] = tempValue;
                    this.parentView.parentView.render();
                    return;
                }
                this.item.editMetadata(tempKey, this.key, tempValue, saveCallback, errorCallback, {
                    field: this.fieldName,
                    path: this.apiPath
                });
            }
        }
    },

    render: function () {
        this.$el.html(this.editTemplate({
            item: this.item,
            lientry: liMetadataKeyEntry(this.limetadata, this.key),
            key: this.key,
            value: this.value,
            accessLevel: this.accessLevel,
            newDatum: this.newDatum,
            AccessType
        }));
        this.$el.find('.g-widget-metadata-key-input').trigger('focus');

        return this;
    }
});

var JsonMetadatumEditWidget = MetadatumEditWidget.extend({
    editTemplate: JsonMetadatumEditWidgetTemplate,

    getCurrentValue: function () {
        return this.editor.getText();
    },

    save: function (event) {
        try {
            return MetadatumEditWidget.prototype.save.call(
                this, event, this.editor.get());
        } catch (err) {
            events.trigger('g:alert', {
                text: 'The field contains invalid JSON and can not be saved.',
                type: 'warning'
            });
            return false;
        }
    },

    render: function () {
        MetadatumEditWidget.prototype.render.apply(this, arguments);

        const jsonEditorEl = this.$el.find('.g-json-editor');
        this.editor = new JSONEditor(jsonEditorEl[0], {
            mode: 'tree',
            modes: ['code', 'tree'],
            onError: () => {
                events.trigger('g:alert', {
                    text: 'The field contains invalid JSON and can not be viewed in Tree Mode.',
                    type: 'warning'
                });
            }
        });

        if (this.value !== undefined) {
            this.editor.setText(JSON.stringify(this.value));
            this.editor.expandAll();
        }

        return this;
    }
});

wrap(MetadataWidget, 'initialize', function (initialize, settings) {
    try {
        initialize.call(this, settings);
    } catch (err) {
    }
    this.noSave = settings.noSave;
    if (this.item && this.item.get('_modelType') === 'item') {
        largeImageConfig.getConfigFile(this.item.get('folderId')).done((val) => {
            this._limetadata = (val || {}).itemMetadata;
            if (this._limetadata) {
                this.render();
            }
        });
    } else {
        this._limetadata = null;
    }
});

wrap(MetadataWidget, 'render', function (render) {
    let metaDict;
    if (this.item.get(this.fieldName)) {
        metaDict = this.item.get(this.fieldName) || {};
    } else if (this.item[this.fieldName]) {
        metaDict = this.item[this.fieldName] || {};
    } else {
        const fieldParts = this.fieldName.split('.');
        metaDict = this.item.get(fieldParts[0]) || {};
        fieldParts.slice(1).forEach((part) => {
            metaDict = metaDict[part] || {};
        });
    }
    var metaKeys = Object.keys(metaDict);
    metaKeys.sort(localeSort);
    if (this._limetadata) {
        const origOrder = metaKeys.slice();
        metaKeys.sort((a, b) => {
            const aentry = liMetadataKeyEntry(this._limetadata, a);
            const bentry = liMetadataKeyEntry(this._limetadata, b);
            if (aentry && !bentry) {
                return -1;
            }
            if (bentry && !aentry) {
                return 1;
            }
            if (aentry && bentry) {
                return aentry.idx - bentry.idx;
            }
            return origOrder.indexOf(a) - origOrder.indexOf(b);
        });
    }
    this._sortedMetaKeys = metaKeys;
    this._renderedMetaDict = metaDict;
    const contents = (this.MetadataWidgetTemplate || MetadataWidgetTemplate)({
        item: this.item,
        title: this.title,
        accessLevel: this.accessLevel,
        AccessType: AccessType,
        limetadata: this._limetadata
    });
    this._renderHeader(contents);

    // Append each metadatum
    _.each(metaKeys, function (metaKey) {
        if ((liMetadataKeyEntry(this._limetadata, metaKey) || {}).hidden) {
            return;
        }
        this.$el.find('.g-widget-metadata-container').append(new MetadatumWidget({
            mode: this.getModeFromValue(metaDict[metaKey], metaKey),
            key: metaKey,
            value: metaDict[metaKey],
            accessLevel: this.accessLevel,
            parentView: this,
            fieldName: this.fieldName,
            apiPath: this.apiPath,
            limetadata: this._limetadata,
            noSave: this.noSave,
            onMetadataEdited: this.onMetadataEdited,
            onMetadataAdded: this.onMetadataAdded
        }).render().$el);
    }, this);

    return this;
});

wrap(MetadataWidget, 'setItem', function (setItem, item) {
    if (item !== this.item) {
        this._limetadata = null;
        if (item && item.get('_modelType') === 'item') {
            largeImageConfig.getConfigFile(item.get('folderId')).done((val) => {
                this._limetadata = (val || {}).itemMetadata;
                if (this._limetadata) {
                    this.render();
                }
            });
        }
    }
    setItem.call(this, item);
    this.item.on('g:changed', function () {
        this.render();
    }, this);
    this.render();
    return this;
});

MetadataWidget.prototype.modes.simple.editor = (args) => new MetadatumEditWidget(args);
MetadataWidget.prototype.modes.json.editor = (args) => {
    if (args.value !== undefined) {
        args.value = JSON.parse(args.value);
    }
    return new JsonMetadatumEditWidget(args);
};
MetadataWidget.prototype.modes.key = {
    editor: function (args) {
        return new MetadatumEditWidget(args);
    },
    displayValue: function () {
        return this.value;
    },
    template: MetadatumViewTemplate
};

MetadataWidget.prototype.events['click .li-add-metadata'] = function (evt) {
    this.addMetadataByKey(evt);
};

MetadataWidget.prototype.getModeFromValue = function (value, key) {
    if (liMetadataKeyEntry(this._limetadata, key)) {
        return 'key';
    }
    return _.isString(value) ? 'simple' : 'json';
};

MetadataWidget.prototype.addMetadata = function (evt, mode) {
    var EditWidget = this.modes[mode].editor;
    var value = (mode === 'json') ? '{}' : '';

    var widget = new MetadatumWidget({
        className: 'g-widget-metadata-row editing',
        mode: mode,
        key: '',
        value: value,
        item: this.item,
        fieldName: this.fieldName,
        noSave: this.noSave,
        apiPath: this.apiPath,
        accessLevel: this.accessLevel,
        parentView: this,
        onMetadataEdited: this.onMetadataEdited,
        onMetadataAdded: this.onMetadataAdded
    });
    widget.$el.appendTo(this.$('.g-widget-metadata-container'));

    EditWidget({
        item: this.item,
        key: '',
        value: value,
        fieldName: this.fieldName,
        noSave: this.noSave,
        apiPath: this.apiPath,
        accessLevel: this.accessLevel,
        newDatum: true,
        parentView: widget,
        onMetadataEdited: this.onMetadataEdited,
        onMetadataAdded: this.onMetadataAdded
    })
        .render()
        .$el.appendTo(widget.$el);
};

MetadataWidget.prototype.addMetadataByKey = function (evt) {
    const key = $(evt.target).attr('metadata-key');
    // if this key already exists, just go to editing it
    if (this.$el.find(`.g-widget-metadata-row[g-key="${key}"]`).length) {
        this.$el.find(`.g-widget-metadata-row[g-key="${key}"] button.g-widget-metadata-edit-button`).click();
        return false;
    }
    var EditWidget = this.modes.key.editor;
    var lientry = liMetadataKeyEntry(this._limetadata, key) || {};
    var value = lientry.default ? lientry.default : '';

    var widget = new MetadatumWidget({
        className: 'g-widget-metadata-row editing',
        mode: 'key',
        key: key,
        value: value,
        item: this.item,
        fieldName: this.fieldName,
        apiPath: this.apiPath,
        accessLevel: this.accessLevel,
        parentView: this,
        limetadata: this._limetadata,
        onMetadataEdited: this.onMetadataEdited,
        onMetadataAdded: this.onMetadataAdded
    });
    widget.$el.appendTo(this.$('.g-widget-metadata-container'));

    EditWidget({
        item: this.item,
        key: key,
        value: value,
        fieldName: this.fieldName,
        apiPath: this.apiPath,
        accessLevel: this.accessLevel,
        newDatum: true,
        noSave: this.noSave,
        parentView: widget,
        limetadata: this._limetadata,
        onMetadataEdited: this.onMetadataEdited,
        onMetadataAdded: this.onMetadataAdded
    })
        .render()
        .$el.appendTo(widget.$el);
};

MetadataWidget.prototype._renderHeader = function (contents) {
    this.$el.html(contents);
};

export {
    MetadataWidget,
    MetadatumWidget,
    MetadatumEditWidget,
    JsonMetadatumEditWidget,
    liMetadataKeyEntry,
    validateMetadataValue
};
