import * as types from './types';

const _ = girder._;

/**
 * Convert a geojs annotation object into an annotation
 * element defined by the json schema.
 *
 * @param {annotation} annotation A geojs annotation object
 * @returns {object}
 */
function convert(annotation) {
    var type = annotation.type();
    if (!_.has(types, type)) {
        throw new Error(
            `Unknown annotation type "${type}"`
        );
    }
    return types[type](annotation);
}

export default convert;
