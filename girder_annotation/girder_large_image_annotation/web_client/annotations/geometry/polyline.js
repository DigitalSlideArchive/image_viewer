const _ = girder._;

export default function polyline(json) {
    const points = _.map(json.points, (p) => _.first(p, 2));
    var type;
    var coordinates;
    var annotationType;

    if (json.closed) {
        points.push(points[0]);
        coordinates = [points];
        if (json.holes) {
            const holes = (json.holes || []).map((hole) => {
                const result = hole.map((p) => _.first(p, 2));
                result.push(result[0]);
                return result;
            });
            coordinates = coordinates.concat(holes);
        }
        type = 'Polygon';
        annotationType = 'polygon';
    } else {
        type = 'LineString';
        coordinates = points;
        annotationType = 'line';
    }

    return {
        type,
        coordinates,
        annotationType
    };
}
