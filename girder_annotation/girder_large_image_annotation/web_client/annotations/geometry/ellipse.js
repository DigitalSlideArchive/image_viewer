import rotate from '../rotate';

const _ = girder._;

export default function ellipse(json) {
    const center = json.center;
    const x = center[0];
    const y = center[1];
    const height = json.height;
    const width = json.width;
    const rotation = json.rotation || 0;

    const left = x - width / 2;
    const right = x + width / 2;
    const top = y - height / 2;
    const bottom = y + height / 2;

    return {
        type: 'Polygon',
        coordinates: [_.map([
            [left, top],
            [right, top],
            [right, bottom],
            [left, bottom],
            [left, top]
        ], rotate(rotation, center))],
        annotationType: 'ellipse'
    };
}
