import $ from 'jquery';
import View from '@girder/core/views/View';

import {AccessType} from '@girder/core/constants';
import events from '@girder/core/events';
import {restRequest} from '@girder/core/rest';
import BrowserWidget from '@girder/core/views/widgets/BrowserWidget';
import PluginConfigBreadcrumbWidget from '@girder/core/views/widgets/PluginConfigBreadcrumbWidget';

import ConfigViewTemplate from '../templates/largeImageConfig.pug';
import '../stylesheets/largeImageConfig.styl';

/**
 * Show the default quota settings for users and collections.
 */
var ConfigView = View.extend({
    events: {
        'submit #g-large-image-form': function (event) {
            event.preventDefault();
            this.$('#g-large-image-error-message').empty();
            this._saveSettings([{
                key: 'large_image.show_thumbnails',
                value: this.$('.g-large-image-thumbnails-show').prop('checked')
            }, {
                key: 'large_image.show_viewer',
                value: this.$('.g-large-image-viewer-show').prop('checked')
            }, {
                key: 'large_image.default_viewer',
                value: this.$('.g-large-image-default-viewer').val()
            }, {
                key: 'large_image.auto_set',
                value: this.$('.g-large-image-auto-set-all').prop('checked') ? 'all' : this.$('.g-large-image-auto-set-on').prop('checked')
            }, {
                key: 'large_image.max_thumbnail_files',
                value: +this.$('.g-large-image-max-thumbnail-files').val()
            }, {
                key: 'large_image.max_small_image_size',
                value: +this.$('.g-large-image-max-small-image-size').val()
            }, {
                key: 'large_image.show_extra_public',
                value: this.$('.g-large-image-show-extra-public').val()
            }, {
                key: 'large_image.show_extra',
                value: this.$('.g-large-image-show-extra').val()
            }, {
                key: 'large_image.show_extra_admin',
                value: this.$('.g-large-image-show-extra-admin').val()
            }, {
                key: 'large_image.show_item_extra_public',
                value: this.$('.g-large-image-show-item-extra-public').val()
            }, {
                key: 'large_image.show_item_extra',
                value: this.$('.g-large-image-show-item-extra').val()
            }, {
                key: 'large_image.show_item_extra_admin',
                value: this.$('.g-large-image-show-item-extra-admin').val()
            }, {
                key: 'large_image.config_folder',
                value: (this.$('#g-large-image-config-folder').val() || '').split(' ')[0]
            }, {
                key: 'large_image.notification_stream_fallback',
                value: this.$('.g-large-image-stream-fallback').prop('checked')
            }, {
                key: 'large_image.icc_correction',
                value: this.$('.g-large-image-icc-correction').prop('checked')
            }]);
        },
        'click .g-open-browser': '_openBrowser'
    },
    initialize: function () {
        ConfigView.getSettings((settings) => {
            this.settings = settings;
            this.render();
        });

        this._browserWidgetView = new BrowserWidget({
            parentView: this,
            titleText: 'Configuration File Location',
            helpText: 'Browse to a location to select it.',
            submitText: 'Select Location',
            validate: function (model) {
                const isValid = $.Deferred();
                if (!model || model.get('_modelType') !== 'folder') {
                    isValid.reject('Please select a folder.');
                } else {
                    isValid.resolve();
                }
                return isValid.promise();
            }
        });
        this.listenTo(this._browserWidgetView, 'g:saved', function (val) {
            this.$('#g-large-image-config-folder').val(val.id);
            restRequest({
                url: `resource/${val.id}/path`,
                method: 'GET',
                data: {type: val.get('_modelType')}
            }).done((result) => {
                // Only add the resource path if the value wasn't altered
                if (this.$('#g-large-image-config-folder').val() === val.id) {
                    this.$('#g-large-image-config-folder').val(`${val.id} (${result})`);
                }
            });
        });
    },

    render: function () {
        this.$el.html(ConfigViewTemplate({
            settings: this.settings,
            viewers: ConfigView.viewers
        }));
        if (!this.breadcrumb) {
            this.breadcrumb = new PluginConfigBreadcrumbWidget({
                pluginName: 'Large image',
                el: this.$('.g-config-breadcrumb-container'),
                parentView: this
            }).render();
        }

        return this;
    },

    _saveSettings: function (settings) {
        /* Now save the settings */
        return restRequest({
            type: 'PUT',
            url: 'system/setting',
            data: {
                list: JSON.stringify(settings)
            },
            error: null
        }).done(() => {
            /* Clear the settings that may have been loaded. */
            ConfigView.clearSettings();
            events.trigger('g:alert', {
                icon: 'ok',
                text: 'Settings saved.',
                type: 'success',
                timeout: 4000
            });
        }).fail((resp) => {
            this.$('#g-large-image-error-message').text(
                resp.responseJSON.message
            );
        });
    },

    _openBrowser: function () {
        this._browserWidgetView.setElement($('#g-dialog-container')).render();
    }
}, {
    /* Class methods and objects */

    /* The list of viewers is added as a property to the select widget view so
     * that it is also available to the settings page. */
    viewers: [
        {
            name: 'geojs',
            label: 'GeoJS',
            type: 'geojs'
        }, {
            name: 'openseadragon',
            label: 'OpenSeaDragon',
            type: 'openseadragon'
        }, {
            name: 'openlayers',
            label: 'OpenLayers',
            type: 'openlayers'
        }, {
            name: 'leaflet',
            label: 'Leaflet',
            type: 'leaflet'
        }, {
            name: 'slideatlas',
            label: 'SlideAtlas',
            type: 'slideatlas'
        }
    ],

    /**
     * Get settings if we haven't yet done so.  Either way, call a callback
     * when we have settings.
     *
     * @param {function} callback a function to call after the settings are
     *      fetched.  If the settings are already present, this is called
     *      without any delay.
     */
    getSettings: function (callback) {
        if (!ConfigView.settings && !ConfigView._settingsRequest) {
            ConfigView._settingsRequest = restRequest({
                type: 'GET',
                url: 'large_image/settings'
            }).done((resp) => {
                resp.extraInfo = {};
                resp.extraItemInfo = {};
                const extraList = [{
                    access: null,
                    extraInfo: 'large_image.show_extra_public',
                    extraItemInfo: 'large_image.show_item_extra_public'
                }, {
                    access: AccessType.READ,
                    extraInfo: 'large_image.show_extra',
                    extraItemInfo: 'large_image.show_item_extra'
                }, {
                    access: AccessType.ADMIN,
                    extraInfo: 'large_image.show_extra_admin',
                    extraItemInfo: 'large_image.show_item_extra_admin'
                }];
                extraList.forEach((entry) => {
                    ['extraInfo', 'extraItemInfo'].forEach((key) => {
                        try {
                            resp[key][entry.access] = JSON.parse(resp[entry[key]]);
                        } catch (err) {
                        }
                    });
                });
                ConfigView.settings = resp;
                if (callback) {
                    callback(ConfigView.settings);
                }
            });
        } else if (callback) {
            ConfigView._settingsRequest.done(() => {
                callback(ConfigView.settings);
            });
        }
    },

    /**
     * Get the folder config file for the current user.
     *
     * @param {string} folderId the folder to get the config for.
     * @param {boolean} reload if true, refetch the config file even if it was
     *      the last one fetched.  Since config files can be changed by the
     *      user, this should be done based on the UI behavior.
     * @param {function} callback a function to call after the config file is
     *      fetched.  If the file is already fetched, this is called without
     *      any delay.
     * @returns a promise that resolves to the config file values.
     */
    getConfigFile: function (folderId, reload, callback) {
        if (!folderId) {
            const result = {};
            if (callback) {
                callback(result);
            }
            return $.Deferred().resolve({});
        }
        if (ConfigView._lastliconfig === folderId && !reload) {
            if (callback) {
                callback(ConfigView._liconfig || {});
            }
            return $.Deferred().resolve(ConfigView._liconfig);
        }
        if (ConfigView._liconfigSettingsRequest) {
            if (ConfigView._nextliconfig === folderId) {
                if (callback) {
                    ConfigView._liconfigSettingsRequest.done((val) => {
                        callback(val || {});
                    });
                }
                return ConfigView._liconfigSettingsRequest;
            }
            ConfigView._liconfigSettingsRequest.cancel();
        }
        ConfigView._nextliconfig = folderId;
        ConfigView._liconfigSettingsRequest = restRequest({
            url: `folder/${folderId}/yaml_config/.large_image_config.yaml`
        }).done((val) => {
            val = val || {};
            ConfigView._lastliconfig = folderId;
            ConfigView._liconfigSettingsRequest = null;
            ConfigView._liconfig = val;
            if (callback) {
                callback(ConfigView._liconfig);
            }
            return val;
        }).fail(() => {
            // fallback matching server values
            const li = {
                columns: [
                    {type: 'record', value: 'name', title: 'Name'},
                    {type: 'record', value: 'controls', title: 'Controls'},
                    {type: 'record', value: 'size', title: 'Size'}]
            };
            const val = {itemList: li, itemListDialog: li};
            ConfigView._lastliconfig = folderId;
            ConfigView._liconfigSettingsRequest = null;
            ConfigView._liconfig = val;
            if (callback) {
                callback(ConfigView._liconfig);
            }
            return val;
        });
        return ConfigView._liconfigSettingsRequest;
    },

    /**
     * Save the folder config file for the current user.
     *
     * @param {string} folderId the folder to get the config for.
     * @param {Object} content the content of the config as an Object.
     * @param {function} callback a function to call after the config file is
     *      saved.
     * @returns a promise that resolves to the config file values.
     */
    saveConfigFile: function (folderId, content, callback) {
        const userContent = JSON.parse(JSON.stringify(content));

        // Only save the editable views (e.g. the ones the user created)
        userContent.namedItemLists = {};
        for (const view in content.namedItemLists) {
            if (content.namedItemLists[view].edit) {
                userContent.namedItemLists[view] = content.namedItemLists[view];
            }
        }
        // User should not set the columns that can be used
        delete userContent.allColumns;

        restRequest({
            method: 'PUT',
            url: `folder/${folderId}/yaml_config/.large_image_config.yaml?user_context=true`,
            data: JSON.stringify(userContent, null, 2),
            contentType: 'application/json'
        }).done(() => {
            if (callback) {
                callback();
            }
        });
    },

    /**
     * Clear the settings so that getSettings will refetch them.
     */
    clearSettings: function () {
        delete ConfigView.settings;
        delete ConfigView._settingsRequest;
    }
});

export default ConfigView;
