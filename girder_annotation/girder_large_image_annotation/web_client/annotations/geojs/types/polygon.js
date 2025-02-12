import common from '../common';
import array from '../coordinates/array';

const _ = girder._;

/**
 * Convert a geojs polygon annotation to the large_image
 * annotation schema.
 */
function polygon(annotation) {
    const element = common(annotation, 'polyline');
    let coordinates = annotation.coordinates();
    const holes = coordinates.inner ? coordinates.inner.map((h) => array(h)) : undefined;
    coordinates = array(coordinates.outer || coordinates);

    return _.extend(element, {
        type: 'polyline',
        closed: true,
        points: coordinates,
        holes
    });
}

export default polygon;
