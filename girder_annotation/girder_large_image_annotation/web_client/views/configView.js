import ConfigViewTemplate from '../templates/largeImageAnnotationConfig.pug';

const View = girder.views.View;
const PluginConfigBreadcrumbWidget = girder.views.widgets.PluginConfigBreadcrumbWidget;
const {restRequest} = girder.rest;
const events = girder.events;

/**
 * Show the default quota settings for users and collections.
 */
var ConfigView = View.extend({
    events: {
        'submit #g-large-image-form': function (event) {
            event.preventDefault();
            this.$('#g-large-image-error-message').empty();
            this._saveSettings([{
                key: 'large_image.annotation_history',
                value: this.$('.g-large-image-annotation-history-show').prop('checked')
            }]);
        }
    },
    initialize: function () {
        ConfigView.getSettings((settings) => {
            this.settings = settings;
            this.render();
        });
    },

    render: function () {
        this.$el.html(ConfigViewTemplate({
            settings: this.settings,
            viewers: ConfigView.viewers
        }));
        if (!this.breadcrumb) {
            this.breadcrumb = new PluginConfigBreadcrumbWidget({
                pluginName: 'Large image annotation',
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
    }
}, {
    /* Class methods and objects */

    /**
     * Get settings if we haven't yet done so.  Either way, call a callback
     * when we have settings.
     *
     * @param {function} callback a function to call after the settings are
     *      fetched.  If the settings are already present, this is called
     *      without any delay.
     */
    getSettings: function (callback) {
        return girder.plugins.large_image.views.ConfigView.getSettings(callback);
    },

    /**
     * Clear the settings so that getSettings will refetch them.
     */
    clearSettings: function () {
        return girder.plugins.large_image.views.ConfigView.clearSettings();
    }
});

export default ConfigView;
