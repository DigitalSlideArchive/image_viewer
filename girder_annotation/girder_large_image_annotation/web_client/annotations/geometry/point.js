const _ = girder._;

export default function point(json) {
    return {
        type: 'Point',
        coordinates: _.first(json.center, 2),
        annotationType: 'point'
    };
}
