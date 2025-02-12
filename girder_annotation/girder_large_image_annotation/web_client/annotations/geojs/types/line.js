import common from '../common';
import array from '../coordinates/array';

const _ = girder._;

/**
 * Convert a geojs line annotation to the large_image
 * annotation schema.
 */
function line(annotation) {
    const element = common(annotation, 'polyline');
    const coordinates = array(annotation.coordinates());

    return _.extend(element, {
        type: 'polyline',
        closed: !!annotation.style('closed'),
        points: coordinates
    });
}

export default line;
