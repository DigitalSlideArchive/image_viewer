import common from '../common';

const _ = girder._;
/**
 * Convert a geojs rectangle annotation to the large_image
 * annotation schema.
 */
function rectangle(annotation) {
    const element = common(annotation);
    let p = annotation.coordinates();
    /* Sort the coordinates so they are always in the same winding order. */
    let ang = [
        Math.atan2(p[1].y - p[0].y, p[1].x - p[0].x),
        Math.atan2(p[2].y - p[1].y, p[2].x - p[1].x),
        Math.atan2(p[3].y - p[2].y, p[3].x - p[2].x),
        Math.atan2(p[0].y - p[3].y, p[0].x - p[3].x)
    ];
    let ang0 = ang.indexOf(Math.min(...ang));
    if (ang[(ang0 + 1) % 4] - ang[ang0] > Math.PI) {
        p = [p[0], p[3], p[2], p[1]];
        ang = [
            Math.atan2(p[1].y - p[0].y, p[1].x - p[0].x),
            Math.atan2(p[2].y - p[1].y, p[2].x - p[1].x),
            Math.atan2(p[3].y - p[2].y, p[3].x - p[2].x),
            Math.atan2(p[0].y - p[3].y, p[0].x - p[3].x)
        ];
        ang0 = ang.indexOf(Math.min(...ang));
    }
    /* If rotate, bias toward the more flat direction. */
    if (ang[ang0] < -0.75 * Math.PI) {
        ang0 += 1;
    }
    /* Sort the coordinates so that they are in a predictable order */
    const p1 = p[ang0 % 4],
        p2 = p[(ang0 + 1) % 4],
        p3 = p[(ang0 + 2) % 4],
        p4 = p[(ang0 + 3) % 4];
    const top = [p3.x - p2.x, p3.y - p2.y];
    const left = [p2.x - p1.x, p2.y - p1.y];

    // determine the rotation of the top line of the rectangle
    const rotation = Math.atan2(top[1], top[0]);
    const height = Math.sqrt(left[0] * left[0] + left[1] * left[1]);
    const width = Math.sqrt(top[0] * top[0] + top[1] * top[1]);
    const center = [
        0.25 * (p1.x + p2.x + p3.x + p4.x),
        0.25 * (p1.y + p2.y + p3.y + p4.y),
        0
    ];

    return _.extend(element, {
        type: 'rectangle',
        center,
        width,
        height,
        rotation
    });
}

export default rectangle;
