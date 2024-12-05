import $ from 'jquery';
import {getCurrentUser} from '@girder/core/auth';
import {AccessType} from '@girder/core/constants';
import {confirm} from '@girder/core/dialog';
import events from '@girder/core/events';
import {restRequest} from '@girder/core/rest';
import {wrap} from '@girder/core/utilities/PluginUtils';
import ItemView from '@girder/core/views/body/ItemView';
import View from '@girder/core/views/View';

/* This should all be refactored for codemirror 6 */
import jsyaml from 'js-yaml';
import jsonlint from 'jsonlint-mod';
import CodeMirror from 'codemirror';
import 'codemirror/lib/codemirror.css';
import 'codemirror/addon/lint/lint.css';
import 'codemirror/addon/fold/foldgutter.css';

import 'codemirror/addon/fold/brace-fold';
import 'codemirror/addon/fold/foldcode';
import 'codemirror/addon/fold/foldgutter';
import 'codemirror/addon/lint/lint';
import 'codemirror/addon/lint/json-lint';
import 'codemirror/addon/lint/yaml-lint';
import 'codemirror/mode/javascript/javascript';
import 'codemirror/mode/properties/properties';
import 'codemirror/mode/yaml/yaml';

import itemViewCodemirror from '../templates/itemViewCodemirror.pug';
import '../stylesheets/itemViewCodemirror.styl';

/* codemirror expects linters to be window level objects */
window.jsonlint = jsonlint;
window.jsyaml = jsyaml;

const Formats = {
    'application/json': {
        name: 'JSON',
        mode: {
            name: 'javascript',
            json: true
        },
        validator: JSON.parse,
        format: (val) => JSON.stringify(val, undefined, 2)
    },
    'text/yaml': {
        name: 'YAML',
        mode: 'yaml',
        validator: jsyaml.load,
        /* This removes comments.  Maybe the yaml package could be used to not
         * do so, or we could use sort of regex parsing, but both of those are
         * more work. */
        format: (val) => jsyaml.dump(val, {lineWidth: -1, noRefs: true})
    },
    'text/plain': {
        name: 'Text',
        mode: 'text',
        validator: (val) => val,
        format: null
    },
    'application/x-girder-ini': {
        name: 'Configuration',
        mode: 'properties',
        buttons: [{
            key: 'replace',
            text: 'Replace',
            title: 'Replace existing configuration and restart',
            action: (val, parent) => confirm({
                text: 'Are you sure you want to save this file, replace the existing configuration, and restart?',
                yesText: 'Save, Replace, and Restart',
                confirmCallback: () => {
                    parent.save();
                    restRequest({
                        url: 'system/version'
                    }).done((resp) => {
                        const lastStartDate = resp.serverStartDate;
                        restRequest({
                            method: 'POST',
                            url: 'large_image/config/replace',
                            data: val,
                            contentType: 'application/x-girder-ini'
                        }).done((result) => {
                            if (result.restarted) {
                                events.trigger('g:alert', {
                                    text: 'Restarting.',
                                    type: 'warning',
                                    timeout: 60000
                                });

                                parent.wait = () => {
                                    restRequest({
                                        url: 'system/version',
                                        error: null
                                    }).done((resp) => {
                                        if (resp.serverStartDate !== lastStartDate) {
                                            window.location.reload();
                                        } else {
                                            window.setTimeout(parent.wait, 1000);
                                        }
                                    }).fail(() => {
                                        window.setTimeout(parent.wait, 1000);
                                    });
                                };
                                parent.wait();
                            } else {
                                events.trigger('g:alert', {
                                    text: 'Configuration unchanged.',
                                    type: 'info'
                                });
                            }
                        });
                    });
                }
            })
        }],
        accessLevel: AccessType.ADMIN,
        adminOnly: true,
        validator: (val) => {
            const promise = $.Deferred();
            restRequest({
                method: 'POST',
                url: 'large_image/config/validate',
                data: val,
                contentType: 'application/x-girder-ini'
            }).done((errors) => {
                if (errors.length) {
                    promise.reject(errors[0].message);
                    return null;
                }
                promise.resolve(val);
                return null;
            }).fail((err) => {
                promise.reject(err);
                return null;
            });
            return promise;
        },
        format: (val) => {
            const promise = $.Deferred();
            restRequest({
                method: 'POST',
                url: 'large_image/config/format',
                data: val,
                contentType: 'application/x-girder-ini'
            }).done((result) => {
                promise.resolve(result);
                return null;
            }).fail((err) => {
                promise.reject(err);
                return null;
            });
            return promise;
        }
    }
};
Formats['application/vnd.geo+json'] = Formats['application/json'];
Formats['text/x-yaml'] = Formats['text/yaml'];
Formats['application/x-yaml'] = Formats['text/yaml'];
Formats['application/yaml'] = Formats['text/yaml'];

function lintGirderIni(text, callback) {
    return restRequest({
        method: 'POST',
        url: 'large_image/config/validate',
        data: text,
        contentType: 'application/x-girder-ini',
        error: null
    }).done((errorList) => {
        callback(errorList.map((entry) => ({
            from: CodeMirror.Pos(entry.line),
            to: CodeMirror.Pos(entry.line),
            message: entry.message
        })));
        return null;
    });
}
lintGirderIni.async = true;

CodeMirror.registerHelper('lint', 'properties', lintGirderIni);

var CodemirrorEditWidget = View.extend({
    events: {
        'click .g-view-codemirror-general-button': 'generalAction',
        'click .g-view-codemirror-revert-button': 'revert',
        'click .g-view-codemirror-format-button': 'format',
        'click .g-view-codemirror-save-button': 'save'
    },

    initialize: function (settings) {
        this.file = settings.file;
        this.accessLevel = settings.accessLevel;
        this.mimeType = settings.mimeType;
        restRequest({
            url: `file/${this.file.id}/download`,
            processData: false,
            dataType: 'text',
            error: null
        }).done((resp) => {
            this._contents = resp;
            this._lastSave = this._contents;
            this.render();
        });
    },

    render: function () {
        this.$el.html(itemViewCodemirror({
            formatName: Formats[this.mimeType].name,
            accessLevel: this.accessLevel,
            buttonList: Formats[this.mimeType].buttons || [],
            formatRecord: Formats[this.mimeType],
            AccessType: AccessType
        }));
        this.code = CodeMirror(this.$el.find('.editor')[0], {
            value: this._contents,
            mode: Formats[this.mimeType].mode,
            lineNumbers: true,
            indentWithTabs: false,
            extraKeys: {
                Tab: function (cm) {
                    var spaces = Array(cm.getOption('tabSize') + 1).join(' ');
                    cm.replaceSelection(spaces);
                }
            },
            gutters: ['CodeMirror-lint-markers'],
            lint: true,
            readOnly: this.accessLevel < AccessType.WRITE
        });
        return this;
    },

    format: function () {
        if (this._informat) {
            return;
        }
        this._informat = true;
        const content = this.code.getValue();
        try {
            $.when(Formats[this.mimeType].validator(content)).done((validated) => {
                try {
                    $.when(Formats[this.mimeType].format(validated)).done((content) => {
                        this.code.setValue(content);
                        this._informat = false;
                        return null;
                    }).fail(() => {
                        this._informat = false;
                        return null;
                    });
                } catch (e) {
                    events.trigger('g:alert', {
                        text: 'Contents do not format. ' + e,
                        type: 'warning'
                    });
                    this._informat = false;
                }
            }).fail(() => {
                this._informat = undefined;
            });
        } catch (e) {
            events.trigger('g:alert', {
                text: 'Contents do not validate. ' + e,
                type: 'warning'
            });
            this._informat = false;
        }
    },

    revert: function () {
        this.code.setValue(this._contents);
    },

    generalAction: function (evt) {
        const key = $(evt.target).attr('button-key');
        const button = Formats[this.mimeType].buttons.filter((but) => (but.key || but.name) === key);
        if (button.length !== 1) {
            return;
        }
        const content = this.code.getValue();
        button[0].action(content, this);
    },

    save: function () {
        const content = this.code.getValue();
        if (content === this._lastSave) {
            return;
        }
        if (this._insave) {
            this._insave = 'again';
            return;
        }
        this._insave = true;
        try {
            $.when(Formats[this.mimeType].validator(content)).done(() => {
                this.file.updateContents(content);
                // functionally, this just marks the parent item's updated time
                this.parentView.model._sendMetadata({});
                this._lastSave = content;
                const lastInsave = this._insave;
                this._insave = undefined;
                if (lastInsave === 'again') {
                    this.save();
                }
            }).fail((err) => {
                events.trigger('g:alert', {
                    text: 'Contents do not validate. ' + err,
                    type: 'warning'
                });
                const lastInsave = this._insave;
                this._insave = undefined;
                if (lastInsave === 'again') {
                    this.save();
                }
            });
        } catch (e) {
            events.trigger('g:alert', {
                text: 'Contents do not validate. ' + e,
                type: 'warning'
            });
            const lastInsave = this._insave;
            this._insave = undefined;
            if (lastInsave === 'again') {
                this.save();
            }
        }
    }
});

wrap(ItemView, 'render', function (render) {
    this.once('g:rendered', () => {
        if (this.codemirrorEditWidget) {
            this.codemirrorEditWidget.remove();
        }
        if (this.fileListWidget.collection.models.length !== 1) {
            return;
        }
        const firstFile = this.fileListWidget.collection.models[0];
        const mimeType = firstFile.get('mimeType');
        if (!Formats[mimeType] || firstFile.get('size') > 100000) {
            return;
        }
        if (Formats[mimeType].accessLevel !== undefined && this.accessLevel < Formats[mimeType].accessLevel) {
            return;
        }
        if (Formats[mimeType].adminOnly && !(getCurrentUser() && getCurrentUser().get('admin'))) {
            return;
        }
        this.codemirrorEditWidget = new CodemirrorEditWidget({
            el: $('<div>', {class: 'g-codemirror-edit-container'})
                .insertAfter(this.$('.g-item-files')),
            file: firstFile,
            parentView: this,
            mimeType: mimeType,
            accessLevel: this.accessLevel
        });
    });
    return render.call(this);
});

export default ItemView;
