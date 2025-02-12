import common from '../common';
import pointCoordinate from '../coordinates/point';

const _ = girder._;

/**
 * Convert a geojs point annotation to the large_image
 * annotation schema.
 */
function point(annotation) {
    const element = common(annotation);

    return _.extend(element, {
        type: 'point',
        center: pointCoordinate(annotation.coordinates()[0])
    });
}

export default point;
