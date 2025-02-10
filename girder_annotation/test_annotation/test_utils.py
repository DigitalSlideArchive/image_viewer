import pytest
from girder_large_image_annotation import utils


@pytest.mark.parametrize('inputPoly,outputPoly', [(
    # Do nothing if the polygon doesn't cross
    [[0, 0], [0, 2], [2, 2], [2, 0]],
    [[0, 0], [0, 2], [2, 2], [2, 0]],
), (
    # Always covner polygons to clockwise
    [[0, 0], [2, 0], [2, 2], [0, 2]],
    [[0, 0], [0, 2], [2, 2], [2, 0]],
), (
    # Uncross a polygon
    [[0, 4], [0, 2], [2, 2], [2, 0], [0, 0], [2, 4]],
    [[0, 4], [2, 4], [1, 2], [2, 2], [2, 0], [0, 0], [1, 2], [0, 2]]
), (
    # Discard degenerate polygons
    [[0, 4]],
    [],
), (
    # Discard degenerate polygons
    [],
    [],
), (
    # Discard degenerate polygons, even if they have valid holes
    [[[0, 4]],
     [[1, 1], [1, 3], [3, 3], [3, 1]]],
    [[]],
), (
    # Merge a hole with a polygon if the hole crosses it
    [[[0, 0], [0, 2], [2, 2], [2, 0]],
     [[1, 1], [1, 3], [3, 3], [3, 1]]],
    [[[0, 0], [0, 2], [1, 2], [1, 1], [2, 1], [2, 2], [1, 2], [1, 3],
      [3, 3], [3, 1], [2, 1], [2, 0]]],
), (
    # Keep non-crossing holes, but holes are counter-clockwise
    [[[0, 0], [0, 4], [4, 4], [4, 0]],
     [[1, 1], [1, 3], [3, 3], [3, 1]]],
    [[[0, 0], [0, 4], [4, 4], [4, 0]],
     [[3, 1], [3, 3], [1, 3], [1, 1]]]
), (
    # Discard degenerate holes
    [[[0, 0], [0, 4], [4, 4], [4, 0]],
     [[1, 1], [1, 1], [1, 1], [1, 1]]],
    [[[0, 0], [0, 4], [4, 4], [4, 0]]]
), (
    # Handle coincident lines
    [[0, 0], [0, 2], [0, 1], [0, 3], [3, 3], [3, 0]],
    [[0, 0], [0, 2], [0, 1], [0, 2], [0, 3], [3, 3], [3, 0]]
), (
    # Handle coincident lines with a different ordering
    [[0, 0], [0, 3], [0, 1], [0, 2], [3, 2], [3, 0]],
    [[0, 0], [0, 1], [0, 2], [0, 1], [0, 2], [0, 3], [0, 2], [3, 2], [3, 0]]
), (
    # Handle coincident lines with holes
    [[0, 0], [3, 0], [3, 1], [1, 1], [1, 0], [2, 0], [2, 2], [0, 2]],
    [[0, 0], [0, 2], [2, 2], [2, 1], [3, 1], [3, 0], [2, 0], [1, 0],
     [2, 0], [2, 1], [1, 1], [1, 0]]
), (
    # Coincident line with two zones
    [[0, 0], [1, 1], [1, 0], [3, 0], [3, 1], [4, 0], [3, 0], [1, 0]],
    [[0, 0], [1, 1], [1, 0], [3, 0], [3, 1], [4, 0], [3, 0], [1, 0]]
), (
    # Coincident line with two zones and less initial verticees
    [[0, 0], [1, 1], [1, 0], [4, 0], [3, 1], [3, 0]],
    [[0, 0], [1, 1], [1, 0], [3, 0], [4, 0], [3, 1], [3, 0], [1, 0]]
)])
def testUncrossPolygon(inputPoly, outputPoly):
    assert utils.uncrossPolygon(inputPoly) == outputPoly
