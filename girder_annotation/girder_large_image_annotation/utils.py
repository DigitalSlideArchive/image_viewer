# General utility functions


def distance2dSquared(pt1, pt2):
    """
    Get the square of the Euclidean 2D distance between two points.

    :param pt1: The first point.  This is an array with at least two numeric
        elements.
    :param pt2: The second point.
    :returns: The distance squared.
    """
    dx = pt1[0] - pt2[0]
    dy = pt1[1] - pt2[1]
    return dx * dx + dy * dy


def distance2dToLineSquared(pt, line1, line2):
    """
    Get the square of the Euclidean 2D distance between a point and a line
    segment.

    :param pt: The point.
    :param line1: One end of the line.
    :param line2: The other end of the line.
    :returns: The distance squared.
    """
    dx = line2[0] - line1[0]
    dy = line2[1] - line1[1]
    lengthSquared = dx * dx + dy * dy
    t = 0
    if lengthSquared:
        t = float((pt[0] - line1[0]) * dx + (pt[1] - line1[1]) * dy) / lengthSquared
        t = max(0, min(1, t))
    return distance2dSquared(pt, [line1[0] + t * dx, line1[1] + t * dy])


def triangleTwiceSignedArea2d(pt1, pt2, pt3):
    """
    Get twice the signed area of a 2d triangle.

    :param pt1: A vertex.  This is an array with at least two numeric elements.
    :param pt2: A vertex.
    :param pt3: A vertex.
    :returns: Twice the signed area.
    """
    return (pt2[1] - pt1[1]) * (pt3[0] - pt2[0]) - (pt2[0] - pt1[0]) * (pt3[1] - pt2[1])


def crossLineSegments2d(seg1pt1, seg1pt2, seg2pt1, seg2pt2):
    """
    Determine if two line segments cross.  They are not considered crossing if
    they share a vertex.  They are crossing if either of one segment's
    vertices are colinear with the other segment.

    :param line1pt1: one endpoint on the first segment.
    :param line1pt2: the other endpoint on the first segment.
    :param line2pt1: one endpoint on the second segment.
    :param line2pt2: the other endpoint on the second segment.
    :returns: True uf the segments cross.
    """
    # If the segments don't have any overlap in x or y, they can't cross
    if ((seg1pt1[0] > seg2pt1[0] and seg1pt1[0] > seg2pt2[0] and
         seg1pt2[0] > seg2pt1[0] and seg1pt2[0] > seg2pt2[0]) or
        (seg1pt1[0] < seg2pt1[0] and seg1pt1[0] < seg2pt2[0] and
         seg1pt2[0] < seg2pt1[0] and seg1pt2[0] < seg2pt2[0]) or
        (seg1pt1[1] > seg2pt1[1] and seg1pt1[1] > seg2pt2[1] and
         seg1pt2[1] > seg2pt1[1] and seg1pt2[1] > seg2pt2[1]) or
        (seg1pt1[1] < seg2pt1[1] and seg1pt1[1] < seg2pt2[1] and
         seg1pt2[1] < seg2pt1[1] and seg1pt2[1] < seg2pt2[1])):
        return False
    # If any vertex is in common, it is not considered crossing
    if (seg1pt1 == seg2pt1 or seg1pt1 == seg2pt2 or seg1pt2 == seg2pt1 or
            seg1pt2 == seg2pt2):
        return False
    # If the lines cross, the signed area of the triangles formed between one
    # segment and the other's vertices will have different signs.  By using
    # > 0, colinear points are crossing.
    if (triangleTwiceSignedArea2d(seg1pt1, seg1pt2, seg2pt1) *
            triangleTwiceSignedArea2d(seg1pt1, seg1pt2, seg2pt2) > 0 or
            triangleTwiceSignedArea2d(seg2pt1, seg2pt2, seg1pt1) *
            triangleTwiceSignedArea2d(seg2pt1, seg2pt2, seg1pt2) > 0):
        return False
    return True


def lineIntersection2d(line1pt1, line1pt2, line2pt1, line2pt2):
    """
    Given lines defined by pairs of points, find the point of intersection.

    :param line1pt1: a point on the first line.
    :param line1pt2: a second point on the first line.
    :param line2pt1: a point on the second line.
    :param line2pt2: a second point on the second line.
    :returns: the point of intersection, or None if the lines are parallel.
    """
    line1dx, line1dy = line1pt1[0] - line1pt2[0], line1pt1[1] - line1pt2[1]
    line2dx, line2dy = line2pt1[0] - line2pt2[0], line2pt1[1] - line2pt2[1]
    det = float(line1dx * line2dy - line1dy * line2dx)
    if not det:
        return
    return [
        ((line1pt1[0] * line1pt2[1] - line1pt1[1] * line1pt2[0]) * line2dx -
         (line2pt1[0] * line2pt2[1] - line2pt1[1] * line2pt2[0]) * line1dx) / det,
        ((line1pt1[0] * line1pt2[1] - line1pt1[1] * line1pt2[0]) * line2dy -
         (line2pt1[0] * line2pt2[1] - line2pt1[1] * line2pt2[0]) * line1dy) / det,
    ]


def lineIntersectionOrEndpoint(line1pt1, line1pt2, line2pt1, line2pt2):
    """
    Given lines defined by pairs of points, find the point of intersection.  If
    the two lines are coincident, return a endpoint that is not in common.

    :param line1pt1: a point on the first line.
    :param line1pt2: a second point on the first line.
    :param line2pt1: a point on the second line.
    :param line2pt2: a second point on the second line.
    :returns: the point of intersection, or None if the lines are parallel and
        do not overlap.
    """
    crossPt = lineIntersection2d(line1pt1, line1pt2, line2pt1, line2pt2)
    if crossPt:
        return crossPt
    for pt in (line1pt1, line1pt2):
        if pt != line2pt1 and pt != line2pt2:
            if not distance2dToLineSquared(pt, line2pt1, line2pt2):
                return pt
    for pt in (line2pt1, line2pt2):
        if pt != line1pt1 and pt != line1pt2:
            if not distance2dToLineSquared(pt, line1pt1, line1pt2):
                return pt
    # The two lines segments do not overlap


def uncrossPolygonWithoutHoles(vertices):
    """
    Given a list of vertices ensure that the polygon does not cross itself.
    Repeated vertices are removed.  If resulting polygon has 2 or less vertices
    (this can only happen if so specified or there are duplicate vertices), an
    empty list is returned.

    :param vertices: a list of vertices of the polygon.  Each vertex is a list
        of at least 2 coordinates (only the first two values are considered).
    :returns: vertices: a list of vertices.
    """
    if len(vertices) <= 2:
        return []
    # Add the first point at the end so we can skip some modulo work
    pts = vertices[:] + vertices[0:1]
    idx1 = 0
    # Iterate through all segments but the last
    while idx1 < len(pts) - 2:
        seg1pt1 = pts[idx1]
        seg1pt2 = pts[idx1 + 1]
        idx2 = idx1 + 1
        # Iterate through the remaining segments
        while idx2 < len(pts) - 1:  # - 1 since we duplicated the first point
            seg2pt1 = pts[idx2]
            seg2pt2 = pts[idx2 + 1]
            # Check if the two segments cross
            if crossLineSegments2d(seg1pt1, seg1pt2, seg2pt1, seg2pt2):
                # If crossing, add the crossing point and reverse the loop
                crossPt = lineIntersectionOrEndpoint(seg1pt1, seg1pt2, seg2pt1, seg2pt2)
                pts = (pts[:idx1 + 1] + [crossPt] + pts[idx2:idx1:-1] +
                       [crossPt] + pts[idx2 + 1:])
                break
            idx2 += 1
        else:
            idx1 += 1
    # Get rid of duplicates except the duplicated first point
    pts = [pt for idx, pt in enumerate(pts) if not idx or pt != pts[idx - 1]]
    # Ensure clockwiseness (if counterclockwise, reverse points).
    #   This still leaves the possibility that the original polygon contained
    # two separable loops that are in different orientations.  For instance, if
    # the polygon is two triangles that share a single vertex and no edges, the
    # two triangles would ideally be in opposite orientations if one is inside
    # the other and the same orientation if they are not.  Adjusting this is
    # currently beyond the scope of this function.
    if sum((pts[idx + 1][0] - pt[0]) * (pts[idx + 1][1] + pt[1])
           for idx, pt in enumerate(pts[:-1])) < 0:
        pts = pts[::-1]
    # Remove duplicated first point
    pts = pts[:-1]
    return pts


def mergeCrossingPolygons(poly1, poly2):
    """
    Given two polygons, check if any edge from the first polygon crosses any
    edge in the second polygon.  If so, merge the two polygons by adding the
    crossing point, combining the second polygon at this point, and passing the
    result through `uncrossPolygonWithoutHoles`.

    :param poly1: a list of vertices forming an uncrossed polygon without
        holes.
    :param poly2: a list of vertices forming an uncrossed polygon without
        holes.
    :returns: None if the polygons do not cross, or a new polygon if they do.
    """
    for idx1, seg1pt1 in enumerate(poly1):
        seg1pt2 = poly1[(idx1 + 1) % len(poly1)]
        for idx2, seg2pt1 in enumerate(poly2):
            seg2pt2 = poly2[(idx2 + 1) % len(poly2)]
            if crossLineSegments2d(seg1pt1, seg1pt2, seg2pt1, seg2pt2):
                # If crossing, combine the polygons at the crossing point
                crossPt = lineIntersectionOrEndpoint(seg1pt1, seg1pt2, seg2pt1, seg2pt2)
                poly = (poly1[:idx1 + 1] + [crossPt] +
                        (poly2[idx2 + 1:] + poly2[:idx2 + 1])[::-1] +
                        [crossPt] + poly1[idx1 + 1:])
                return uncrossPolygonWithoutHoles(poly)


def uncrossPolygon(vertices):
    """
    Given a list of vertices, or a list of lists of vertices where the first
    entry if the polygon and subsequent entries are holes, ensure that the
    polygon does not cross itself.  Each hole is uncrossed on its own.  If two
    holes (or a hole and a polygon) cross each other, they are
    joined into a single more complicated polygon.  Repeated vertices and
    degenerate polygons (2 or less vertices) are removed.

    :param vertices: a list of vertices of the polygon.  Each vertex is a list
        of at least 2 coordinates (only the first two values are considered).
        Alternately, a list of lists of vertices, where the first entry is the
        polygon and subsequent entries are holes.
    :returns: vertices: a list of vertices or a list of lists of vertices.
        This has the same depth as the original argument.
    """
    if not len(vertices) or not len(vertices[0]):
        return vertices
    if not isinstance(vertices[0][0], list):
        return uncrossPolygonWithoutHoles(vertices)
    # uncross the outer polygon and all holes
    polygons = [uncrossPolygonWithoutHoles(pts) for pts in vertices]
    # If the containing polygon is degenerate, return an empty set
    if not len(polygons[0]):
        return [[]]
    # discard degenerate holes
    polygons = [polygon for polygon in polygons if len(polygon)]
    # For each polygon, check if it crosses any other polygon.  If it does,
    # join them together at the first crossing point and uncross the result.
    pidx1 = 0
    while pidx1 < len(polygons) - 1:
        poly1 = polygons[pidx1]
        pidx2 = pidx1 + 1
        while pidx2 < len(polygons):
            poly2 = polygons[pidx2]
            crossed = mergeCrossingPolygons(poly1, poly2)
            if crossed:
                polygons[pidx1] = crossed
                del polygons[pidx2]
                break
            pidx2 += 1
        else:
            pidx1 += 1
    # reverse all holes so that they are opposite direction as the main polygon
    for idx in range(1, len(polygons)):
        polygons[idx] = polygons[idx][::-1]
    return polygons
