import * as geometry from './geometry';
import * as defaults from './defaults';
import style from './style';

const _ = girder._;

function convertOne(properties) {
    return function (annotation, key) {
        if (('' + key).startsWith('_')) {
            return;
        }
        const type = annotation.type;
        annotation = _.defaults({}, annotation, defaults[type] || {});
        if (!_.has(geometry, type)) {
            return;
        }
        const geom = geometry[type](annotation);
        return {
            type: 'Feature',
            id: annotation.id,
            geometry: {type: geom.type, coordinates: geom.coordinates},
            properties: _.extend({element: annotation, annotationType: geom.annotationType}, properties, style(annotation))
        };
    };
}

export default function convert(json, properties = {}) {
    const features = _.chain(json)
        .mapObject(convertOne(properties))
        .compact()
        .value();

    return {
        type: 'FeatureCollection',
        features
    };
}
