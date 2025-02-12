import * as defaults from '../defaults';

const _ = girder._;

/**
 * Convert properties from geojs options to annotation
 * elements that all types have in common.  At the moment,
 * this handles style information, but could be expanded
 * to handle labels, names, id's, etc.
 *
 * @param {annotation} annotation A geojs native annotation object
 * @param {string} type Override the detected output type
 * @returns {object}
 */
function common(annotation, type) {
    type = type || annotation.type();
    return _.extend({}, defaults[type] || {});
}

export default common;
