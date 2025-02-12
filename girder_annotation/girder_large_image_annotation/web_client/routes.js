import ConfigView from './views/configView';

const events = girder.events;
const router = girder.router;
const {exposePluginConfig} = girder.utilities.PluginUtils;

exposePluginConfig('large_image_annotation', 'plugins/large_image_annotation/config');

router.route('plugins/large_image_annotation/config', 'largeImageAnnotationConfig', function () {
    events.trigger('g:navigateTo', ConfigView);
});
