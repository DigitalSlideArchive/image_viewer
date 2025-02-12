import ConfigView from './views/configView';

const $ = girder.$;
const Backbone = girder.Backbone;
const events = girder.events;
const router = girder.router;
const {exposePluginConfig} = girder.utilities.PluginUtils;
const {parseQueryString, splitRoute} = girder.misc;

exposePluginConfig('large_image', 'plugins/large_image/config');

router.route('plugins/large_image/config', 'largeImageConfig', function () {
    events.trigger('g:navigateTo', ConfigView);
});

/**
 * Add a dictionary of parameters to the current route.  If any entries have
 * values of undefined, null, or '', they are removed from the route.
 *
 * @param {object} params The parameters to add to the route.
 */
function addToRoute(params) {
    if (!router.enabled()) {
        return;
    }
    const curRoute = Backbone.history.fragment;
    const routeParts = splitRoute(curRoute);
    const query = parseQueryString(routeParts.name);
    let update = false;
    Object.entries(params).forEach(([key, value]) => {
        update = update || (value !== query[key]);
        if (value === undefined || value === null || value === '') {
            delete query[key];
        } else {
            query[key] = value;
        }
    });
    if (update) {
        const paramStr = $.param(query);
        // This should be
        //  router.navigate(routeParts.base + (paramStr ? '?' + paramStr : ''));
        // But backbone stores an unescaped fragment in the
        // Backbone.history.fragment, which causes a hash-variation trigger,
        // so this works around that.
        const fragment = (routeParts.base + (paramStr ? '?' + paramStr : '')).replace(/#.*$/, '');
        Backbone.history.fragment = fragment;
        Backbone.history._updateHash(Backbone.history.location, fragment);
    }
}

export {
    addToRoute
};
